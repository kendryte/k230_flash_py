"""Tests for the BootROM -> U-Boot handoff orchestration in api.py.

_boot_loader_and_wait is the piece that failed 8 times out of 10 on hardware, so
it gets its own coverage: the happy path, the retry when the loader does not
take, and the guarantee that we never hand the caller a BootROM-stage device.
"""

import pytest
from helpers.fake_usb import BROM_EP_OUT, UBOOT_EP_OUT, FakeDevice, patch_find

from k230_flash import api
from k230_flash.usb_utils import KBURN_USB_DEV_UBOOT


@pytest.fixture
def no_loader_push(monkeypatch):
    """Skip the actual EP0 loader upload; these tests are about what happens
    after boot_from, not about the upload itself."""
    calls = []
    monkeypatch.setattr(api, "handle_bootrom_mode", lambda **kw: calls.append(kw))
    return calls


def _boot(port_path="1-5.3.2"):
    return api._boot_loader_and_wait(
        dev=FakeDevice(mode="brom", address=95),
        port_path=port_path,
        media_type="SDCARD",
        loader_file=None,
        loader_address=0x80360000,
        progress_callback=None,
    )


def test_returns_the_uboot_device_once_it_appears(monkeypatch, no_loader_push):
    uboot = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[], [uboot]])

    dev, port_path = _boot()

    assert dev is uboot
    assert port_path == "1-5.3.2"
    assert len(no_loader_push) == 1, "the loader should be pushed exactly once"


def test_never_returns_a_bootrom_stage_device(monkeypatch, no_loader_push):
    """Returning the pre-reboot device is precisely the bug: its descriptor
    advertises OUT 0x01, which does not exist once the loader is running."""
    stale = FakeDevice(mode="brom", address=95)
    uboot = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[stale], [stale], [uboot]])

    dev, _ = _boot()

    cfg = dev.get_active_configuration()
    endpoints = [ep.bEndpointAddress for intf in cfg for ep in intf]
    assert UBOOT_EP_OUT in endpoints
    assert BROM_EP_OUT not in endpoints


def test_releases_the_bootrom_handle_without_resetting_it(monkeypatch, no_loader_push):
    """reset() on a device already rebooting forces a second, competing
    re-enumeration; the old code did that and produced 'No such device' warnings."""
    brom = FakeDevice(mode="brom", address=95)
    uboot = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [[uboot]])

    api._boot_loader_and_wait(
        dev=brom,
        port_path="1-5.3.2",
        media_type="SDCARD",
        loader_file=None,
        loader_address=0x80360000,
        progress_callback=None,
    )

    assert brom.reset_calls == 0
    assert brom._ctx.dev.finalize_calls == 1


def test_repushes_the_loader_if_the_chip_falls_back_to_bootrom(monkeypatch, no_loader_push):
    """If the loader does not take, the chip stays in BootROM. Retrying the push
    beats failing the whole flash."""
    monkeypatch.setattr(api, "LOADER_ENUMERATION_TIMEOUT", 0.05)
    brom = FakeDevice(mode="brom", address=95)
    uboot = FakeDevice(mode="uboot", address=96)

    # Keyed on how many times the loader has been pushed rather than on a call
    # count: the first push never takes (the chip stays in BootROM), the second
    # one does. Polling frequency then cannot affect the outcome.
    patch_find(monkeypatch, lambda: [uboot] if len(no_loader_push) >= 2 else [brom])

    dev, _ = _boot()

    assert dev is uboot
    assert len(no_loader_push) == 2, "the loader should have been pushed again"


def test_gives_up_with_a_clear_error_when_the_loader_never_starts(monkeypatch, no_loader_push):
    monkeypatch.setattr(api, "LOADER_ENUMERATION_TIMEOUT", 0.05)
    monkeypatch.setattr(api, "LOADER_FALLBACK_TIMEOUT", 0.05)
    monkeypatch.setattr(api, "LOADER_BOOT_ATTEMPTS", 2)
    patch_find(monkeypatch, [[]])

    with pytest.raises(RuntimeError) as exc:
        _boot()

    assert "U-Boot" in str(exc.value)


def test_flash_firmware_skips_the_handoff_when_already_in_uboot(monkeypatch):
    """A board left running the loader from a previous attempt should be flashed
    directly rather than having the loader pushed on top of itself."""
    pushed = []
    monkeypatch.setattr(api, "handle_bootrom_mode", lambda **kw: pushed.append(kw))
    uboot = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [uboot])

    seen = {}
    api._flash_firmware(
        port_path="1-5.3.2",
        loader_file=None,
        loader_address=0x80360000,
        media_type="SDCARD",
        progress_callback=None,
        flash_func=lambda dev: seen.setdefault("dev", dev),
    )

    assert pushed == [], "no loader push was needed"
    assert seen["dev"] is uboot


def test_flash_firmware_releases_the_device_even_when_flashing_raises(monkeypatch):
    uboot = FakeDevice(mode="uboot", address=96)
    patch_find(monkeypatch, [uboot])

    def boom(dev):
        raise RuntimeError("write failed")

    with pytest.raises(RuntimeError):
        api._flash_firmware(
            port_path="1-5.3.2",
            loader_file=None,
            loader_address=0x80360000,
            media_type="SDCARD",
            progress_callback=None,
            flash_func=boom,
        )

    assert uboot._ctx.dev.finalize_calls == 1, "device leaked on the failure path"


def test_probe_mode_constant_is_what_the_handoff_waits_for():
    """Cheap guard: the handoff waits for this exact constant, and a renumbering
    would otherwise make it wait forever."""
    assert KBURN_USB_DEV_UBOOT == 2
