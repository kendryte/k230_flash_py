# arg_parser.py
import argparse
import textwrap
from difflib import get_close_matches
from pathlib import Path

from .constants import DEFAULT_LOADER_ADDRESS, MEDIA_ALIASES, MEDIA_TYPES, normalise_media_type
from .file_utils import extract_if_compressed

# Everything in this module exists to fail *before* main() starts waiting for a
# board. A mistyped media type or a path with a typo in it used to sail through
# argument parsing, wait up to five minutes for the device, push the loader, and
# only then blow up somewhere deep in the burner.


def _media_type(value):
    canonical = normalise_media_type(value)
    if canonical:
        return canonical
    # Suggest against every spelling we accept, not just the canonical names,
    # so a near-miss on an abbreviation ("NADN") still gets a useful hint.
    hint = get_close_matches(value.strip().upper(), sorted(MEDIA_ALIASES), n=1)
    suggestion = f" (did you mean {hint[0]}?)" if hint else ""
    raise argparse.ArgumentTypeError(f"invalid media type '{value}'{suggestion}; choose from {', '.join(MEDIA_TYPES)}")


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not an integer")
    if parsed <= 0:
        # A retry interval of 0 is a busy loop, and a non-positive timeout means
        # the wait expires before it begins.
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {parsed}")
    return parsed


def _address(value):
    try:
        parsed = int(value, 0)  # Allow hexadecimal (0x...) and decimal
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid address")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"address must not be negative, got {value}")
    return parsed


def _existing_file(value):
    path = Path(value)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"file does not exist: {path}")
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"not a regular file: {path}")
    return path


def _resolve_image(parser, raw_value, expected_suffix):
    """Check the path exists, decompress if needed, and confirm the extension.

    Extension matching is case-insensitive here to agree with the api module,
    which lowercases before comparing. They disagreed before, so `FW.KDIMG` was
    rejected by the CLI and accepted by the library.
    """
    original_path = Path(raw_value)
    if not original_path.exists():
        parser.error(f"file does not exist: {original_path}")
    if not original_path.is_file():
        parser.error(f"not a regular file: {original_path}")

    extracted_path = original_path
    try:
        extracted_path = extract_if_compressed(original_path)
    except Exception as e:
        # Decompression happens at parse time, so a corrupt archive would
        # otherwise surface as a raw traceback instead of a usage error.
        parser.error(f"failed to decompress {original_path}: {e}")

    if extracted_path.suffix.lower() != expected_suffix:
        if extracted_path == original_path:
            parser.error(f"{original_path} is not a {expected_suffix} file")
        parser.error(f"{original_path} (extracted to {extracted_path.name}) is not a {expected_suffix} file")
    return extracted_path


class MultiModeAction(argparse.Action):
    """Parses three modes:
    1. A single .kdimg file
    2. [address, .img] parameter pairs
    3. A single .kdimg file (will be combined with --kdimg-select parameters)
    """

    def __call__(self, parser, namespace, values, option_string=None):
        # Record the raw positionals too. argparse only fills `dest` when the
        # action does it itself, so without this `args.files` stays None even
        # when positionals were supplied, which is confusing for anything
        # inspecting the namespace.
        setattr(namespace, self.dest, values)

        # If there is only one argument, check if it ends with .kdimg
        if len(values) == 1:
            setattr(namespace, "kdimg_file", _resolve_image(parser, values[0], ".kdimg"))
            setattr(namespace, "addr_filename_pairs", None)  # Set the other mode to None
            return

        # Otherwise, parse as [address, .img] pairs
        if len(values) % 2 != 0:
            parser.error("[address, *.img] parameter pairs must appear in pairs")

        pairs = []
        seen = {}
        for i in range(0, len(values), 2):
            try:
                address = int(values[i], 0)  # Allow hexadecimal (0x...) and decimal
            except ValueError:
                parser.error(f"invalid address: {values[i]} is not a valid integer")
            if address < 0:
                parser.error(f"invalid address: {values[i]} must not be negative")

            extracted_path = _resolve_image(parser, values[i + 1], ".img")

            # Two images at one address means the second silently overwrites the
            # first; that is never what anyone meant to type.
            if address in seen:
                parser.error(f"duplicate address 0x{address:X}: {seen[address]} and {extracted_path}")
            seen[address] = extracted_path

            pairs.append((address, extracted_path))

        setattr(namespace, "addr_filename_pairs", pairs)
        setattr(namespace, "kdimg_file", None)  # Set the other mode to None


class KdimgSelectAction(argparse.Action):
    """Parses kdimg partition selection parameters: [partition_name] list"""

    def __call__(self, parser, namespace, values, option_string=None):
        # Parse as list of partition names
        if not values:
            parser.error("--kdimg-select requires at least one partition name")

        duplicates = {name for name in values if values.count(name) > 1}
        if duplicates:
            parser.error(f"--kdimg-select lists a partition more than once: {', '.join(sorted(duplicates))}")

        setattr(namespace, "kdimg_selected_partitions", list(values))


def parse_arguments(args_list=None):
    parser = argparse.ArgumentParser(
        prog="k230-flash",
        description="K230 Flash tool",
        usage="k230-flash [options] (ADDRESS FILE [ADDRESS FILE ...] | KDIMG_FILE)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:

            Mode 1: Pass [address, image] parameter pairs. Each img file can also be a
            zip/gz/tgz archive; the first image inside is extracted and used.
                k230-flash 0x400000 firmware1.img 0x800000 firmware2.img

            Mode 2: Pass a single .kdimg file (also accepted compressed).
                k230-flash my_image.kdimg

            Mode 3: Pass a .kdimg file + select specific partitions to flash
                k230-flash my_image.kdimg --kdimg-select uboot_spl_a uboot_a
            """
        ),
    )

    parser.add_argument("-l", "--list-devices", action="store_true", help="List available USB devices")

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
        type=_existing_file,
        default=None,
        help="Specify a custom loader file path",
    )

    parser.add_argument(
        "-la",
        "--loader-address",
        type=_address,
        default=DEFAULT_LOADER_ADDRESS,
        help=f"Specify the loader load address (default: 0x{DEFAULT_LOADER_ADDRESS:08X})",
    )

    parser.add_argument(
        "-m",
        "--media-type",
        type=_media_type,
        default="EMMC",
        metavar="MEDIA",
        help=(
            f"Media type: {', '.join(MEDIA_TYPES)} (default: EMMC). "
            "Case, separators and common abbreviations are accepted: "
            "spi-nand / spinand / nand, spi_nor / nor, sd"
        ),
    )

    parser.add_argument("--auto-reboot", action="store_true", help="Reboot automatically after writing")

    parser.add_argument(
        "--device-timeout",
        type=_positive_int,
        default=300,
        help="Device wait timeout in seconds when device path is specified (default: 300)",
    )

    parser.add_argument(
        "--device-retry-interval",
        type=_positive_int,
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
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level",
    )

    parser.add_argument(
        "files",
        nargs="*",
        metavar="ADDRESS FILE or KDIMG_FILE",
        action=MultiModeAction,
        help="Mode 1: Pass [address, *.img] parameter pairs | Mode 2: Pass a single *.kdimg file | Mode 3: Pass a single *.kdimg file + --kdimg-select to choose specific partitions",
    )

    args = parser.parse_args(args_list)

    # Nothing to do: no image to write and nothing queried. Fail with usage
    # rather than exiting 0 having done nothing -- an automation script that
    # dropped its arguments should not look like a successful flash.
    if (
        not args.list_devices
        and not getattr(args, "kdimg_file", None)
        and not getattr(args, "addr_filename_pairs", None)
    ):
        parser.error("nothing to do: pass an image to flash, or use --list-devices")

    # --kdimg-select only means something in kdimg mode. Silently ignoring it
    # alongside [address, file] pairs looked like a partial flash had been
    # requested while the whole image was actually written.
    if getattr(args, "kdimg_selected_partitions", None) and not getattr(args, "kdimg_file", None):
        parser.error("--kdimg-select only applies to a .kdimg file (mode 3)")

    return args
