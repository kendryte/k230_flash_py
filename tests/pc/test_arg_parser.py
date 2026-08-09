"""Tests for the command line argument parser (arg_parser.py).

The parser's job is to reject bad input *before* main() starts waiting up to
five minutes for a board to appear. So alongside the mode-detection tests there
is a block of rejection tests: each one is a mistake that used to be diagnosed
only after the device had been found and the loader pushed, if at all.

Files referenced here are created for real, because path validation is now part
of what the parser does.
"""

from pathlib import Path

import pytest

from k230_flash.arg_parser import parse_arguments


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """Give every test a directory containing the files it names."""
    for name in ("firmware.kdimg", "boot.img", "firmware.img", "file1.img", "file1.txt", "my_loader.bin"):
        (tmp_path / name).write_bytes(b"\x00" * 64)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- mode detection -----------------------------------------------------------


def test_kdimg_mode():
    """Test mode 2: single .kdimg file"""
    args = parse_arguments(["firmware.kdimg"])
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.addr_filename_pairs is None


def test_addr_filename_mode():
    """Test mode 1: [address, .img] file pairs"""
    args = parse_arguments(["0x0", "boot.img", "0x10000", "firmware.img"])
    assert args.addr_filename_pairs == [
        (0, Path("boot.img")),
        (0x10000, Path("firmware.img")),
    ]
    assert args.kdimg_file is None


def test_all_options():
    """Test whether all long options can be parsed correctly"""
    args = parse_arguments(
        [
            "--list-devices",
            "--device-path",
            "1-3.2",
            "--loader-file",
            "my_loader.bin",
            "--loader-address",
            "0x80100000",
            "--media-type",
            "SPI_NOR",
            "--auto-reboot",
            "--kdimg-select",
            "uboot_spl_a",
            "uboot_spl_b",
            "--log-level",
            "DEBUG",
            "firmware.kdimg",
        ]
    )
    assert args.list_devices is True
    assert args.device_path == "1-3.2"
    assert args.loader_file == Path("my_loader.bin")
    assert args.loader_address == 0x80100000
    assert args.media_type == "SPI_NOR"
    assert args.auto_reboot is True
    assert args.kdimg_selected_partitions == ["uboot_spl_a", "uboot_spl_b"]
    assert args.log_level == "DEBUG"
    assert args.kdimg_file == Path("firmware.kdimg")


def test_kdimg_select_mode():
    """Test mode 3: kdimg file with selected partitions"""
    args = parse_arguments(["firmware.kdimg", "--kdimg-select", "uboot_spl_a", "uboot_spl_b"])
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.addr_filename_pairs is None
    assert args.kdimg_selected_partitions == ["uboot_spl_a", "uboot_spl_b"]


def test_kdimg_select_single_partition():
    """Test kdimg-select with single partition"""
    args = parse_arguments(["firmware.kdimg", "--kdimg-select", "uboot_spl_a"])
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.kdimg_selected_partitions == ["uboot_spl_a"]


def test_kdimg_select_multiple_partitions():
    """Test kdimg-select with multiple partitions"""
    args = parse_arguments(["firmware.kdimg", "--kdimg-select", "uboot_spl_a", "uboot_spl_b", "uboot_a", "uboot_b"])
    assert args.kdimg_selected_partitions == ["uboot_spl_a", "uboot_spl_b", "uboot_a", "uboot_b"]


def test_list_devices_only():
    """Test that --list-devices does not require other file parameters"""
    args = parse_arguments(["--list-devices"])
    assert args.list_devices is True
    assert args.files == []


# --- structural errors --------------------------------------------------------


def test_no_files_or_list_devices_fails():
    """Test whether it will exit when there are no file parameters and no --list-devices"""
    with pytest.raises(SystemExit):
        parse_arguments([])


def test_uneven_addr_filename_pairs_fails():
    """Test whether it will exit when the [address, .img] parameters are not in pairs"""
    with pytest.raises(SystemExit):
        parse_arguments(["0x1000", "file1.img", "0x2000"])


def test_invalid_address_fails():
    """Test whether it will exit when an invalid address is provided"""
    with pytest.raises(SystemExit):
        parse_arguments(["not_an_address", "file1.img"])


def test_invalid_file_extension_fails():
    """Test whether it will exit when a non-.img file is provided in [address, file] mode"""
    with pytest.raises(SystemExit):
        parse_arguments(["0x1000", "file1.txt"])


def test_kdimg_and_addr_filename_fails():
    """Test that .kdimg and [address, .img] pairs cannot be mixed"""
    with pytest.raises(SystemExit):
        parse_arguments(["0x1000", "firmware.kdimg"])


# --- rejections that used to be deferred until after the device was found -----


def test_missing_image_is_rejected_at_parse_time(capsys):
    """A typo'd path used to wait out the full device timeout first."""
    with pytest.raises(SystemExit):
        parse_arguments(["typo.kdimg"])

    assert "does not exist" in capsys.readouterr().err


def test_missing_loader_file_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_arguments(["--loader-file", "nope.bin", "firmware.kdimg"])

    assert "does not exist" in capsys.readouterr().err


def test_directory_in_place_of_image_is_rejected(tmp_path):
    (tmp_path / "adir.kdimg").mkdir()
    with pytest.raises(SystemExit):
        parse_arguments(["adir.kdimg"])


def test_unknown_media_type_is_rejected_with_a_suggestion(capsys):
    """`-m SDCART` used to be accepted here and only rejected once the loader
    was already running, after a full BootROM handoff."""
    with pytest.raises(SystemExit):
        parse_arguments(["-m", "SDCART", "firmware.kdimg"])

    assert "SDCARD" in capsys.readouterr().err


def test_media_type_is_case_insensitive():
    args = parse_arguments(["-m", "sdcard", "firmware.kdimg"])
    assert args.media_type == "SDCARD"


def test_uppercase_extension_is_accepted(workdir):
    """The parser compared extensions case-sensitively while api.py lowercased
    first, so FW.KDIMG was rejected by the CLI and accepted by the library."""
    (workdir / "FW.KDIMG").write_bytes(b"\x00" * 64)

    args = parse_arguments(["FW.KDIMG"])

    assert args.kdimg_file.name == "FW.KDIMG"


def test_kdimg_select_with_raw_pairs_is_rejected(capsys):
    """Mixing them silently ignored the selection and flashed everything."""
    with pytest.raises(SystemExit):
        parse_arguments(["0x0", "boot.img", "--kdimg-select", "uboot_a"])

    assert "kdimg" in capsys.readouterr().err


def test_duplicate_partition_selection_is_rejected():
    with pytest.raises(SystemExit):
        parse_arguments(["firmware.kdimg", "--kdimg-select", "uboot_a", "uboot_a"])


def test_duplicate_address_is_rejected(capsys):
    """Two images at one address means the second overwrites the first."""
    with pytest.raises(SystemExit):
        parse_arguments(["0x1000", "boot.img", "0x1000", "firmware.img"])

    assert "duplicate address" in capsys.readouterr().err


def test_negative_address_is_rejected(capsys):
    # `--` so argparse hands the leading-dash token to the positional action
    # rather than rejecting it as an unknown option; that way this exercises the
    # address check itself.
    with pytest.raises(SystemExit):
        parse_arguments(["--", "-0x1000", "boot.img"])

    assert "negative" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--device-timeout", "--device-retry-interval"])
@pytest.mark.parametrize("value", ["0", "-5"])
def test_non_positive_wait_settings_are_rejected(option, value):
    """A retry interval of 0 is a busy loop; a timeout of 0 expires instantly."""
    with pytest.raises(SystemExit):
        parse_arguments([option, value, "firmware.kdimg"])
