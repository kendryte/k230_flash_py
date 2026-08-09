"""Tests for the device discovery / handoff helpers in usb_utils.py.

These cover the logic that used to fail 8 times out of 10 on real hardware: the
window after the loader starts where the old device is still listed, gone, or
back at the same address with a stale descriptor.
"""

import pytest
import usb.core
from helpers.fake_usb import FakeDevice, patch_find

from k230_flash import usb_utils
from k230_flash.usb_utils import (
    KBURN_USB_DEV_BROM,
    KBURN_USB_DEV_INVALID,
    KBURN_USB_DEV_UBOOT,
    device_identity,
    list_usb_devices,
    probe_device,
    release_device,
    wait_for_device_mode,
)

# --- probing ------------------------------------------------------------------


def test_probe_distinguishes_the_two_stages():
    assert probe_device(FakeDevice(mode="brom")) == KBURN_USB_DEV_BROM
    assert probe_device(FakeDevice(mode="uboot")) == KBURN_USB_DEV_UBOOT


def test_probe_reports_invalid_when_ep0_fails():
    """A device mid-reboot answers EP0 with an I/O error. That must read as
    'not ready', not as a hard failure, or the handoff aborts early."""
    assert probe_device(FakeDevice(ep0_error=True)) == KBURN_USB_DEV_INVALID


def test_list_usb_devices_builds_port_path(monkeypatch):
    patch_find(monkeypatch, [FakeDevice(bus=1, address=95, ports=(5, 3, 2))])

    entries = list_usb_devices()

    assert entries[0]["port_path"] == "1-5.3.2"
    assert entries[0]["address"] == 95


# --- release_device -----------------------------------------------------------


def test_release_device_finalizes_backend_wrapper():
    """dispose_resources() alone leaves the backend wrapper to be unref'd by the
    GC. When it is unref'd after its private libusb context is gone, the process
    segfaults -- so release_device must finalize it while the context is valid."""
    dev = FakeDevice()

    release_device(dev)

    assert dev._ctx.dev.finalize_calls == 1


def test_release_device_is_idempotent_and_tolerates_none():
    dev = FakeDevice()
    release_device(dev)
    release_device(dev)
    release_device(None)  # must not raise

    assert dev._ctx.dev.finalize_calls == 2


# --- wait_for_device_mode -----------------------------------------------------


def test_waits_until_device_reports_expected_mode(monkeypatch):
    """The new device may enumerate before it answers EP0. Polling must keep
    going rather than accept the first thing that appears."""
    not_ready = FakeDevice(mode="uboot", address=96, ep0_error=True)
    ready = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[not_ready], [not_ready], [ready]])

    dev, port_path = wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=5, poll_interval=0)

    assert dev is ready
    assert port_path == "1-5.3.2"
    assert ready.set_configuration_calls == 1


def test_skips_devices_still_reporting_the_old_stage(monkeypatch):
    """For ~140ms after boot_from the BootROM device is still listed. Matching it
    would hand the caller BootROM's endpoints."""
    stale = FakeDevice(mode="brom", address=95)
    fresh = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[stale], [stale], [fresh]])

    dev, _ = wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=5, poll_interval=0)

    assert dev is fresh


def test_accepts_a_device_that_reused_the_old_address(monkeypatch):
    """Windows brings the loader back at the *same* bus/address. Filtering on the
    pre-reboot identity would reject the very device being waited for, which is
    exactly how this broke Windows (0/5) while Linux stayed green."""
    same_address = FakeDevice(mode="uboot", bus=2, address=13, ports=(6, 2))
    patch_find(monkeypatch, [same_address])

    dev, _ = wait_for_device_mode("2-6.2", KBURN_USB_DEV_UBOOT, timeout=5, poll_interval=0)

    assert dev is same_address
    assert device_identity(dev) == (2, 13)


def test_ignores_devices_on_a_different_port(monkeypatch):
    """A second board mid-flash on the same host must not be picked up."""
    other_board = FakeDevice(mode="uboot", bus=1, address=20, ports=(4, 1))
    patch_find(monkeypatch, [other_board])

    with pytest.raises(TimeoutError):
        wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=0.2, poll_interval=0)


def test_times_out_with_a_useful_message(monkeypatch):
    patch_find(monkeypatch, [[]])

    with pytest.raises(TimeoutError) as exc:
        wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=0.2, poll_interval=0)

    assert "1-5.3.2" in str(exc.value)


# --- what the user sees while the chip reboots --------------------------------


def _capture_logs(level):
    """Collect loguru records at or above `level`. Returns (records, stop)."""
    from loguru import logger

    records = []
    sink_id = logger.add(lambda m: records.append(m.record), level=level)
    return records, lambda: logger.remove(sink_id)


def test_probes_during_reenumeration_are_not_logged_as_errors(monkeypatch):
    """A chip mid-reboot answers EP0 with EIO. That is the expected state here,
    not a fault.

    Each one used to be logged at ERROR, so a perfectly normal handoff printed a
    wall of "Failed to probe device: [Errno 5] Input/Output Error" and then,
    immediately after, "设备已切换至 U-Boot 模式" -- reading as though something
    had broken and the flash had somehow succeeded anyway.
    """
    not_ready = FakeDevice(mode="uboot", address=96, ep0_error=True)
    ready = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[not_ready], [not_ready], [not_ready], [ready]])
    errors, stop = _capture_logs("ERROR")

    try:
        dev, _ = wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=5, poll_interval=0)
    finally:
        stop()

    assert dev is ready, "precondition: the wait still has to succeed"
    assert errors == [], f"handoff logged errors on the happy path: {[r['message'] for r in errors]}"


def test_a_wait_that_times_out_does_report_the_probe_failure(monkeypatch):
    """The failures are only silenced while there is still time. Once the device
    genuinely never comes back the reason has to reach the user, or demoting the
    log level would just be hiding the diagnostic."""
    never_ready = FakeDevice(mode="uboot", address=96, ep0_error=True)
    patch_find(monkeypatch, [never_ready])

    with pytest.raises(TimeoutError) as exc:
        wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=0.2, poll_interval=0)

    message = str(exc.value)
    assert "1-5.3.2" in message
    assert "U-Boot" in message, "the mode should be named, not printed as a bare integer"
    assert "fake EP0 failure" in message, "the underlying USB error should be carried through"


def test_one_shot_probe_still_logs_an_error():
    """probe_device is used where the device is believed to be ready already
    (api._flash_firmware, straight after find+init). A failure there is real, so
    that diagnostic must survive the change above."""
    errors, stop = _capture_logs("ERROR")
    try:
        assert probe_device(FakeDevice(ep0_error=True)) == KBURN_USB_DEV_INVALID
    finally:
        stop()

    assert len(errors) == 1
    assert "Failed to probe device" in errors[0]["message"]


def test_rejected_devices_are_released(monkeypatch):
    """Every candidate we do not return must be released while its context is
    still alive, or tearing the context down later crashes the interpreter."""
    stale = FakeDevice(mode="brom", address=95)
    fresh = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[stale], [fresh]])

    wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=5, poll_interval=0)

    assert stale._ctx.dev.finalize_calls >= 1, "the rejected device was never released"
    assert fresh._ctx.dev.finalize_calls == 0, "the returned device must stay usable"


def test_refresh_backend_builds_a_private_context(monkeypatch):
    """On Windows the process-wide context never notices the re-enumeration, so
    enumeration has to go through a fresh one. Assert we actually ask for it."""
    made = []

    def fake_fresh():
        made.append(1)
        return object()

    monkeypatch.setattr(usb_utils, "fresh_usb_backend", fake_fresh)
    patch_find(monkeypatch, [FakeDevice(mode="uboot")])

    wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=1, poll_interval=0, refresh_backend=True)

    assert made, "refresh_backend=True did not create a private libusb context"


def test_falls_back_to_shared_backend_when_private_one_unavailable(monkeypatch):
    """fresh_usb_backend() returns None if pyusb's internals move. That must
    degrade to the shared backend, not crash the flash."""
    monkeypatch.setattr(usb_utils, "fresh_usb_backend", lambda: None)
    patch_find(monkeypatch, [FakeDevice(mode="uboot")])

    dev, _ = wait_for_device_mode("1-5.3.2", KBURN_USB_DEV_UBOOT, timeout=1, poll_interval=0, refresh_backend=True)

    assert dev is not None


def test_fresh_usb_backend_returns_distinct_contexts():
    """Guards the real implementation against a pyusb layout change: either it
    hands back independent contexts, or it must return None so callers fall back."""
    first = usb_utils.fresh_usb_backend()
    second = usb_utils.fresh_usb_backend()

    if first is None or second is None:
        pytest.skip("no libusb backend available on this machine")
    assert first is not second
