import re
import sys
from pathlib import Path

# Determine the base directory for logs
# For packaged apps, this might be in user's app data directory
# For development, it's usually project root
if getattr(sys, "frozen", False):  # Check if running as a bundled executable
    BASE_LOG_DIR = Path(sys.executable).parent
else:
    BASE_LOG_DIR = Path(__file__).parent.parent.parent  # Project root

LOG_FILE_NAME = "k230_flash.log"
FULL_LOG_FILE_PATH = BASE_LOG_DIR / LOG_FILE_NAME

# USB identity of a K230 in flashing mode. Both BootROM and the loader stage
# enumerate under these; the stages are told apart by an EP0 probe, not by IDs.
# These used to be repeated as default arguments across five functions.
USB_VID = 0x29F1
USB_PID = 0x0230

# Storage media the device side understands. These are the canonical spellings;
# what a user may type is wider, see normalise_media_type().
MEDIA_TYPES = ("EMMC", "SDCARD", "SPI_NAND", "SPI_NOR", "OTP")

# Accepted spellings, keyed on the separator-free upper-case form. Reducing the
# input that way first means SPI_NAND, SPI-NAND, "spi nand" and SpiNand all
# arrive here as SPINAND, so only the genuine abbreviations need listing.
#
# MMC is deliberately absent. It reads as an obvious alias but is ambiguous:
# eMMC and SD share a loader yet send *different* probe bytes
# (KBURN_MEDIUM_EMMC=1 vs KBURN_MEDIUM_SDCARD=2), so guessing either way makes
# the loader probe the wrong controller and report "no suitable device". A
# rejected argument with a did-you-mean is a much better outcome than a
# confident wrong guess.
MEDIA_ALIASES = {
    "EMMC": "EMMC",
    "SDCARD": "SDCARD",
    "SD": "SDCARD",
    "SPINAND": "SPI_NAND",
    "NAND": "SPI_NAND",
    "SPINOR": "SPI_NOR",
    "NOR": "SPI_NOR",
    "OTP": "OTP",
}


def normalise_media_type(value):
    """Return the canonical media name for a user-supplied spelling, or None.

    Shared by the CLI, the library API and the burners so they cannot drift
    apart -- the same class of bug as the CLI and api once disagreeing about
    whether FW.KDIMG was a valid filename.
    """
    if not isinstance(value, str):
        return None
    key = re.sub(r"[\s_\-]+", "", value.strip().upper())
    return MEDIA_ALIASES.get(key)


# Media reachable from BootROM, i.e. the ones a built-in loader exists for.
# OTP is a valid target for an already-running loader but there is no
# loader_otp.bin to boot, so starting from BootROM with -m OTP cannot work.
MEDIA_TYPES_WITH_LOADER = ("EMMC", "SDCARD", "SPI_NAND", "SPI_NOR")

# Default address the loader is copied to in SRAM before being jumped into.
DEFAULT_LOADER_ADDRESS = 0x80360000
