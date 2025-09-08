"""
Test the arg_parser.py command line argument parser

Instructions:
- This test does not depend on any external files.
- To run the test: execute the `pytest src/k230_flash/tests` command in the project root directory (`k230-flash/`).
"""

import sys
from pathlib import Path

import pytest

# Add the src directory to sys.path to resolve ModuleNotFoundError
src_path = str(Path(__file__).parent.parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Since the test file is inside a package, it can be imported directly
from k230_flash.arg_parser import parse_arguments


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
    args = parse_arguments(
        [
            "firmware.kdimg",
            "--kdimg-select",
            "uboot_spl_a",
            "uboot_spl_b",
        ]
    )
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.addr_filename_pairs is None
    assert args.kdimg_selected_partitions == ["uboot_spl_a", "uboot_spl_b"]


def test_kdimg_select_single_partition():
    """Test kdimg-select with single partition"""
    args = parse_arguments(["firmware.kdimg", "--kdimg-select", "uboot_spl_a"])
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.addr_filename_pairs is None
    assert args.kdimg_selected_partitions == ["uboot_spl_a"]


def test_kdimg_select_multiple_partitions():
    """Test kdimg-select with multiple partitions"""
    args = parse_arguments(
        [
            "firmware.kdimg",
            "--kdimg-select",
            "uboot_spl_a",
            "uboot_spl_b",
            "uboot_a",
            "uboot_b",
        ]
    )
    assert args.kdimg_file == Path("firmware.kdimg")
    assert args.addr_filename_pairs is None
    assert args.kdimg_selected_partitions == [
        "uboot_spl_a",
        "uboot_spl_b",
        "uboot_a",
        "uboot_b",
    ]


def test_list_devices_only():
    """Test that --list-devices does not require other file parameters"""
    args = parse_arguments(["--list-devices"])
    assert args.list_devices is True
    assert args.files == []


# --- Test error handling --- #


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
    # MultiModeAction will recognize firmware.kdimg as a file name,
    # and then fail because it does not end with .img.
    with pytest.raises(SystemExit):
        parse_arguments(["0x1000", "firmware.kdimg"])
