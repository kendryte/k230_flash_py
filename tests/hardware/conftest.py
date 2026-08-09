"""Fixtures for tests that need a real K230 board.

Everything is configured through environment variables so a CI runner can be
pointed at its own rig without touching the tests:

    K230_TEST_PORT     USB path of the board in download mode, e.g. 1-5.3.2  (required)
    K230_TEST_MEDIA    storage media, default SDCARD
    K230_TEST_IMAGE    path to a .img used by the flash round-trip test
    K230_BOARD_SCRIPTS directory holding board.py (power/BOOT control)
    K230_BOARD_NAME    board entry inside that tooling's config.yaml
    K230_OWNER         lease owner; also required on Windows, where board.py
                       otherwise dies in os.getsid()

Tests that need something unavailable skip rather than fail, so a partially
provisioned runner reports honestly instead of going red.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers.known_faults import is_known_medium_probe_failure

pytestmark = pytest.mark.hardware

FLASH_VID, FLASH_PID = 0x29F1, 0x0230


def _env(name, default=None):
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


@pytest.fixture(scope="session")
def board_port():
    port = _env("K230_TEST_PORT")
    if not port:
        pytest.skip("set K230_TEST_PORT to the board's USB path (e.g. 1-5.3.2)")
    return port


@pytest.fixture(scope="session")
def media_type():
    return _env("K230_TEST_MEDIA", "SDCARD")


@pytest.fixture(scope="session")
def test_image():
    path = _env("K230_TEST_IMAGE")
    if not path or not Path(path).is_file():
        pytest.skip("set K230_TEST_IMAGE to a flashable .img for this board")
    return Path(path)


class BoardControl:
    """Thin wrapper over the rig's board.py (power relay + BOOT pin).

    Deliberately a subprocess rather than an import: the rig tooling lives in a
    separate repo and has its own dependencies, and we only need three verbs.
    """

    def __init__(self, scripts_dir, board_name, owner):
        self.scripts_dir = Path(scripts_dir)
        self.board_name = board_name
        self.env = dict(os.environ)
        # board.py's lease code calls os.getsid(), which does not exist on
        # Windows and is only guarded against OSError. Setting an owner makes
        # current_owner() return before reaching it.
        self.env.setdefault("K230_OWNER", owner)

    def _run(self, verb, timeout=120):
        return subprocess.run(
            [sys.executable, str(self.scripts_dir / "board.py"), "--board", self.board_name, verb],
            check=True,
            capture_output=True,
            timeout=timeout,
            env=self.env,
        )

    def enter_download_mode(self, settle=2.5):
        """Power-cycle into BootROM/download mode."""
        self._run("bootmode")
        time.sleep(settle)

    def normal_boot(self, settle=0.0):
        # NOTE: the rig's naming is inverted relative to its own docs --
        # `bootup` means BOOT HIGH == normal run mode.
        self._run("bootup")
        self._run("powercycle")
        if settle:
            time.sleep(settle)


@pytest.fixture(scope="session")
def board():
    scripts = _env("K230_BOARD_SCRIPTS")
    name = _env("K230_BOARD_NAME")
    if not scripts or not name:
        pytest.skip("set K230_BOARD_SCRIPTS and K230_BOARD_NAME to drive board power/BOOT")
    if not (Path(scripts) / "board.py").is_file():
        pytest.skip(f"board.py not found under {scripts}")
    return BoardControl(scripts, name, owner=_env("K230_OWNER", "k230-flash-ci"))


@pytest.fixture
def flash_with_retry(board, board_port, record_property):
    """Run a flash, retrying past the known medium-probe defect.

    Anything else propagates immediately -- the point is to absorb one specific,
    documented device fault without also masking real regressions. The number of
    retries is recorded on the test so a rising trend is visible in CI rather
    than silently tolerated.
    """

    def _run(operation, attempts=4):
        last = None
        for attempt in range(attempts):
            _require_download_mode(board, board_port)
            try:
                result = operation()
                record_property("medium_probe_retries", attempt)
                return result
            except Exception as exc:  # noqa: BLE001 - re-raised below if unknown
                if not is_known_medium_probe_failure(exc):
                    raise
                last = exc
        record_property("medium_probe_retries", attempts)
        pytest.fail(
            f"medium probe failed on all {attempts} attempts -- either the board's "
            f"storage is genuinely absent/misconfigured, or the known loader defect "
            f"has become permanent. Last error: {last}"
        )

    return _run


@pytest.fixture
def enter_download_mode(board, board_port):
    """Callable that re-enters download mode, for tests that loop over flashes."""

    def _enter():
        _require_download_mode(board, board_port)

    return _enter


@pytest.fixture
def board_in_download_mode(board, board_port):
    """Leave the board in download mode before the test, normal boot after.

    Restoring afterwards matters for a shared rig: a board left in download mode
    looks 'broken' to whatever runs next.
    """
    _require_download_mode(board, board_port)
    yield board
    try:
        board.normal_boot()
    except Exception:  # teardown must not mask a real test failure
        pass


def _require_download_mode(board, port, attempts=4):
    from k230_flash.usb_utils import KBURN_USB_DEV_BROM, list_usb_devices, probe_device, release_device

    for _ in range(attempts):
        board.enter_download_mode()
        for entry in list_usb_devices(FLASH_VID, FLASH_PID):
            dev = entry["device"]
            if entry["port_path"] != port:
                release_device(dev)
                continue
            try:
                found = probe_device(dev) == KBURN_USB_DEV_BROM
            except Exception:
                found = False
            release_device(dev)
            if found:
                return
    pytest.fail(f"board at {port} would not enter BootROM mode after {attempts} attempts")
