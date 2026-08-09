"""Real-hardware coverage of the BootROM -> U-Boot handoff.

The PC suite proves the logic with a fake device; this proves it against the
actual re-enumeration, which is what differs between Linux and Windows and is
where the original 2/10 failure rate lived.

Run with:  pytest --hardware -m hardware tests/hardware/test_handoff.py
"""

import time

import pytest

from k230_flash import api
from k230_flash.burners import K230UBOOTBurner
from k230_flash.usb_utils import KBURN_USB_DEV_BROM, find_device, probe_device, release_device

pytestmark = pytest.mark.hardware

# The U-Boot gadget's bulk OUT endpoint. BootROM uses 0x01, so seeing 0x01 here
# means the caller is holding a pre-reboot descriptor.
EXPECTED_UBOOT_EP_OUT = 0x02


def _handoff(port, media):
    """Run the handoff and report what the U-Boot-stage device looks like."""
    seen = {}

    def inspect(dev):
        burner = K230UBOOTBurner(dev, media)
        seen["ep_out"] = burner.ep_out
        seen["ep_in"] = burner.ep_in
        seen["address"] = dev.address
        # Storage-independent liveness check: the gadget answers CMD_NONE with a
        # fixed string, so this proves the bulk pipe works without depending on
        # the medium being present or healthy.
        burner.kburn_nop()
        seen["bulk_ok"] = True

    api._flash_firmware(
        port_path=port,
        loader_file=None,
        loader_address=0x80360000,
        media_type=media,
        progress_callback=lambda current, total: None,
        flash_func=inspect,
    )
    return seen


def test_board_starts_in_bootrom(board_in_download_mode, board_port):
    """Precondition check, so a rig problem is not misread as a handoff bug."""
    dev, _ = find_device(port_path=board_port)
    try:
        assert probe_device(dev) == KBURN_USB_DEV_BROM
    finally:
        release_device(dev)


def test_handoff_yields_uboot_endpoints(board_in_download_mode, board_port, media_type):
    """The core regression: after the loader boots we must be talking to the
    loader's endpoints, not BootROM's."""
    seen = _handoff(board_port, media_type)

    assert seen["bulk_ok"], "bulk pipe did not answer after the handoff"
    assert (
        seen["ep_out"] == EXPECTED_UBOOT_EP_OUT
    ), f"got OUT {hex(seen['ep_out'])}; 0x01 means a stale BootROM descriptor"


@pytest.mark.parametrize("run", range(5))
def test_handoff_is_repeatable(enter_download_mode, board_port, media_type, run):
    """Once passed 2/10. Repeating catches a regression that only shows up
    intermittently, which a single run would miss."""
    enter_download_mode()
    seen = _handoff(board_port, media_type)

    assert seen["ep_out"] == EXPECTED_UBOOT_EP_OUT
    assert seen["bulk_ok"]


def test_handoff_completes_promptly(board_in_download_mode, board_port, media_type):
    """Guards against a regression that reintroduces a fixed sleep: measured
    0.5-1.2s across Linux and Windows, so several seconds means someone is
    waiting on a timer again rather than on the device."""
    started = time.monotonic()
    _handoff(board_port, media_type)
    elapsed = time.monotonic() - started

    assert elapsed < 8.0, f"handoff took {elapsed:.1f}s; expected roughly 1s"


def test_loader_reports_a_serial_number(board_in_download_mode, board_port, media_type):
    """The shipped loader derives an iSerialNumber from the PUF chip UID. Without
    it Windows reuses the BootROM device node and serves a stale descriptor, so a
    loader rebuilt without the patch must not pass silently.
    """
    import usb.util

    serial = {}

    def read_serial(dev):
        serial["value"] = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None

    api._flash_firmware(
        port_path=board_port,
        loader_file=None,
        loader_address=0x80360000,
        media_type=media_type,
        progress_callback=lambda current, total: None,
        flash_func=read_serial,
    )

    assert serial["value"], "loader exposed no iSerialNumber"
    assert serial["value"].startswith("K230-"), f"unexpected serial {serial['value']!r}"
