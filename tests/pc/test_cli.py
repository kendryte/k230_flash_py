"""Tests for the CLI entry point (main.py), driven against a simulated board.

The parser tests cover what gets rejected before a device is touched; these
cover what main() does with a *runtime* failure. Previously every one of these
ended in a Python traceback printed at the user with the exit code left to the
interpreter, so a CI script could not tell a failed flash from a successful one
without scraping stderr.
"""

import json

import pytest
from helpers.board_simulator import Faults, SimulatedK230, install
from helpers.kdimg_builder import Partition, write_kdimg_file

from k230_flash import main as cli


@pytest.fixture(autouse=True)
def _log_to_tmp(tmp_path, monkeypatch):
    """main() configures its own file sink; keep it out of the repo root."""
    monkeypatch.setattr(cli, "FULL_LOG_FILE_PATH", tmp_path / "k230_flash.log")


@pytest.fixture
def sim(monkeypatch):
    return install(monkeypatch, SimulatedK230())


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "fw.img"
    img.write_bytes(b"\x11" * 2048)
    return img


def _quiet(current, total):
    pass


# --- success ------------------------------------------------------------------


def test_successful_flash_returns_zero(sim, image):
    code = cli.main(
        ["-d", sim.port_path, "-m", "SDCARD", "0x0", str(image)],
        progress_callback=_quiet,
    )

    assert code == 0
    assert sim.read_back(0x0) == b"\x11" * 2048


def test_list_devices_prints_json_and_returns_zero(sim, capsys):
    code = cli.main(["--list-devices"], progress_callback=_quiet)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["port_path"] == sim.port_path


def test_kdimg_mode_flashes_through_the_cli(sim, tmp_path):
    img = write_kdimg_file(
        tmp_path / "fw.kdimg",
        [Partition("uboot_a", offset=0x0, data=b"\xaa" * 512)],
    )

    code = cli.main(["-d", sim.port_path, "-m", "SDCARD", str(img)], progress_callback=_quiet)

    assert code == 0
    assert sim.read_back(0x0) == b"\xaa" * 512


def test_device_path_is_stripped_consistently(sim, image):
    """The wait used the stripped path and the flash used the raw one, so a
    padded -d value waited for a device it then failed to open."""
    code = cli.main(
        ["-d", f"  {sim.port_path}  ", "-m", "SDCARD", "0x0", str(image)],
        progress_callback=_quiet,
    )

    assert code == 0
    assert sim.read_back(0x0) == b"\x11" * 2048


# --- runtime failures ---------------------------------------------------------


def test_device_side_write_failure_exits_nonzero(monkeypatch, tmp_path, image):
    """The device rejects the write; the CLI must fail loudly, not exit 0."""
    install(monkeypatch, SimulatedK230(faults=Faults(write_fails=True)))

    with pytest.raises(SystemExit) as exc:
        cli.main(["-m", "SDCARD", "0x0", str(image)], progress_callback=_quiet)

    assert exc.value.code == 1


def test_probe_failure_exits_nonzero_without_a_traceback(monkeypatch, image, capsys):
    install(monkeypatch, SimulatedK230(faults=Faults(probe_fails=True)))

    with pytest.raises(SystemExit) as exc:
        cli.main(["-m", "SDCARD", "0x0", str(image)], progress_callback=_quiet)

    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().err


def test_missing_device_times_out_and_exits_nonzero(sim, image):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "-d",
                "9-9.9",
                "-m",
                "SDCARD",
                "--device-timeout",
                "1",
                "--device-retry-interval",
                "1",
                "0x0",
                str(image),
            ],
            progress_callback=_quiet,
        )

    assert exc.value.code == 1


def test_image_too_large_for_the_medium_exits_nonzero(monkeypatch, tmp_path):
    """Mode 1 had no capacity check at all; this used to fail as an opaque
    protocol timeout somewhere deep in the write loop."""
    install(monkeypatch, SimulatedK230(faults=Faults(capacity=64 * 1024)))
    img = tmp_path / "big.img"
    img.write_bytes(b"\x55" * (128 * 1024))

    with pytest.raises(SystemExit) as exc:
        cli.main(["-m", "SDCARD", "0x0", str(img)], progress_callback=_quiet)

    assert exc.value.code == 1


# --- GUI mode -----------------------------------------------------------------
#
# The GUI calls main() in-process and treats "returned without raising" as a
# successful flash, logging 烧录成功！ on that path (src/gui/single_flash.py:1055).
# So every failure must *raise* in GUI mode too; returning a non-zero code would
# be reported to the user as success. Both GUI call sites already catch
# SystemExit and Exception.


def test_gui_mode_still_raises_on_a_failed_flash(monkeypatch, image):
    install(monkeypatch, SimulatedK230(faults=Faults(write_fails=True)))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["-m", "SDCARD", "0x0", str(image)],
            progress_callback=_quiet,
            use_external_logging=True,
        )

    assert exc.value.code == 1


def test_gui_mode_raises_for_bad_arguments(monkeypatch):
    """Argument errors used to be swallowed in GUI mode, so the GUI's own
    SystemExit handler never fired and a rejected command line was announced as
    a successful flash."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--media-type", "NOPE", "whatever.kdimg"], use_external_logging=True)

    assert exc.value.code != 0


def test_gui_mode_returns_zero_on_success(sim, image):
    assert (
        cli.main(
            ["-d", sim.port_path, "-m", "SDCARD", "0x0", str(image)],
            progress_callback=_quiet,
            use_external_logging=True,
        )
        == 0
    )
