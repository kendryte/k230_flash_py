# arg_parser.py
import argparse
import sys
import textwrap
from difflib import get_close_matches
from pathlib import Path

from loguru import logger

from .file_utils import extract_if_compressed


class MultiModeAction(argparse.Action):
    """Parses three modes:
    1. A single .kdimg file
    2. [address, .img] parameter pairs
    3. A single .kdimg file (will be combined with --kdimg-select parameters)
    """

    def __call__(self, parser, namespace, values, option_string=None):
        # If there is only one argument, check if it ends with .kdimg
        if len(values) == 1:
            original_path = Path(values[0])
            extracted_path = extract_if_compressed(original_path)
            if not extracted_path.suffix == ".kdimg":
                parser.error(
                    f"Error: {original_path} (extracted to {extracted_path}) is not a .kdimg file"
                )
            setattr(namespace, "kdimg_file", extracted_path)  # Parse as Path
            setattr(
                namespace, "addr_filename_pairs", None
            )  # Set the other mode to None
            return

        # Otherwise, parse as [address, .img] pairs
        if len(values) % 2 != 0:
            parser.error("Error: [address, *.img] parameter pairs must appear in pairs")

        pairs = []
        for i in range(0, len(values), 2):
            try:
                address = int(values[i], 0)  # Allow hexadecimal (0x...) and decimal
            except ValueError:
                parser.error(f"Invalid address: {values[i]} is not a valid integer")

            original_path = Path(values[i + 1])
            extracted_path = extract_if_compressed(original_path)
            if not extracted_path.suffix == ".img":
                parser.error(
                    f"Error: {original_path} (extracted to {extracted_path}) is not an .img file"
                )

            pairs.append((address, extracted_path))

        setattr(namespace, "addr_filename_pairs", pairs)
        setattr(namespace, "kdimg_file", None)  # Set the other mode to None


class KdimgSelectAction(argparse.Action):
    """Parses kdimg partition selection parameters: [partition_name] list"""

    def __call__(self, parser, namespace, values, option_string=None):
        # Parse as list of partition names
        if not values:
            parser.error("Error: --kdimg-select requires at least one partition name")

        partition_names = values  # List of partition names to flash
        setattr(namespace, "kdimg_selected_partitions", partition_names)


def parse_arguments(args_list=None):
    parser = argparse.ArgumentParser(
        description="K230 Flash tool",
        usage="python main.py [options] (ADDRESS FILE | KDIMG_FILE) [ADDRESS FILE ...Как это работает?",
        epilog=textwrap.dedent(
            """
        Examples:
        
        Mode 1: Pass [address, image] parameter pairs. Each img file can also be a zip file; the system will automatically decompress it and return the path of the first decompressed file.
            python main.py 0x400000 firmware1.img 0x800000 firmware2.img

        Mode 2: Pass a single .kdimg file. Each kdimg file can also be a zip file; the system will automatically decompress it and return the path of the first decompressed file.
            python main.py my_image.kdimg

        Mode 3: Pass a .kdimg file + select specific partitions to flash
            python main.py my_image.kdimg --kdimg-select uboot_spl_a uboot_a
        """
        ),
    )

    parser.add_argument(
        "-l", "--list-devices", action="store_true", help="List available USB devices"
    )

    parser.add_argument(
        "-d",
        "--device-path",
        type=str,
        default="",
        help="Specify the USB device path (e.g., '1-2.1')",
    )

    parser.add_argument(
        "-lf",
        "--loader-file",
        type=Path,
        default=None,
        help="Specify a custom loader file path",
    )

    parser.add_argument(
        "-la",
        "--loader-address",
        type=lambda x: int(x, 0),
        default=0x80360000,
        help="Specify the loader load address (default: 0x80360000)",
    )

    parser.add_argument(
        "-m",
        "--media-type",
        type=str,
        default="EMMC",
        help="Media type: EMMC, SDCARD, SPI_NAND, SPI_NOR, OTP",
    )

    parser.add_argument(
        "--auto-reboot", action="store_true", help="Reboot automatically after writing"
    )

    parser.add_argument(
        "--device-timeout",
        type=int,
        default=300,
        help="Device wait timeout in seconds when device path is specified (default: 300)",
    )

    parser.add_argument(
        "--device-retry-interval",
        type=int,
        default=1,
        help="Device retry interval in seconds when waiting for device (default: 1)",
    )

    parser.add_argument(
        "--kdimg-select",
        nargs="+",
        metavar="PARTITION_NAME",
        action=KdimgSelectAction,
        help="Select specific partitions to flash from kdimg file (only works with kdimg mode)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level",
    )

    parser.add_argument(
        "files",
        nargs="*",
        metavar=("ADDRESS FILE or KDIMG_FILE"),
        action=MultiModeAction,
        help="Mode 1: Pass [address, *.img] parameter pairs | Mode 2: Pass a single *.kdimg file | Mode 3: Pass a single *.kdimg file + --kdimg-select to choose specific partitions",
    )

    if args_list is not None:
        args = parser.parse_args(args_list)
    else:
        args = parser.parse_args()

    return args
