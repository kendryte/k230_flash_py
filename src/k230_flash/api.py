import json
import warnings
from pathlib import Path

from loguru import logger

from .burners import handle_bootrom_mode, handle_uboot_mode
from .constants import DEFAULT_LOADER_ADDRESS, MEDIA_TYPES, USB_PID, USB_VID, normalise_media_type
from .progress import progress_callback as default_progress_callback
from .usb_utils import (
    KBURN_USB_DEV_BROM,
    KBURN_USB_DEV_UBOOT,
    detect_device_type,
    device_identity,
    find_device,
    init_device,
    list_usb_devices,
    release_device,
    wait_for_device_mode,
)

# How long to wait for the loader to re-enumerate as a U-Boot-stage device, and
# how many times to re-push the loader if the chip never gets there.
LOADER_ENUMERATION_TIMEOUT = 15.0
# How long to look for the chip back in BootROM before concluding the loader did
# not merely fail to start but that the device is gone entirely.
LOADER_FALLBACK_TIMEOUT = 5.0
LOADER_BOOT_ATTEMPTS = 3


def _warn_if_log_level_passed(log_level):
    """`log_level` never did anything on any of these functions.

    Configuring loguru is the application's job -- the library reconfiguring a
    process-wide logger behind its caller's back would be worse than the wart.
    The parameter stays so existing keyword calls do not break, but it now says
    so out loud instead of silently ignoring the request.
    """
    if log_level is not None:
        warnings.warn(
            "log_level has no effect and will be removed; configure loguru in "
            "your own application instead (see the README library example).",
            DeprecationWarning,
            stacklevel=3,
        )


def find_devices(vid=USB_VID, pid=USB_PID):
    """Return connected K230 devices as a list of plain dicts.

    Prefer this over list_devices() when calling from Python; list_devices()
    returns pre-serialised JSON because the CLI prints it verbatim.
    """
    entries = list_usb_devices(vid, pid)
    try:
        return [
            {
                "bus": entry["bus"],
                "address": entry["address"],
                "port_path": entry["port_path"],
                "vid": vid,
                "pid": pid,
            }
            for entry in entries
        ]
    finally:
        # Enumerating hands back live device objects. Leaving them to the
        # garbage collector keeps libusb handles open, which on Windows is
        # enough to disturb a later re-enumeration.
        for entry in entries:
            release_device(entry["device"])


def list_devices(vid=USB_VID, pid=USB_PID, log_level=None):
    """
    Lists all connected K230 USB devices

    :param vid: USB Vendor ID (default 0x29F1)
    :param pid: USB Product ID (default 0x0230)
    :param log_level: deprecated, has no effect
    :return: JSON string of the device list
    """
    _warn_if_log_level_passed(log_level)
    return json.dumps(find_devices(vid, pid), indent=4, ensure_ascii=False)


def _boot_loader_and_wait(dev, port_path, media_type, loader_file, loader_address, progress_callback):
    """Push the loader over BootROM and wait for it to come back as U-Boot stage.

    Starting the loader makes the chip re-enumerate with *different bulk
    endpoints* (BootROM exposes OUT 0x01, the U-Boot gadget exposes OUT 0x02),
    so anything still holding the pre-reboot descriptor ends up writing to an
    endpoint that no longer exists.

    The two platforms differ in a way that matters here:

    * Linux  -- the chip comes back at a new bus address, and libusb notices.
    * Windows -- it comes back at the *same* address, and libusb's cached
      context never notices at all: it keeps serving BootROM's descriptor even
      though EP0 already answers "Uboot Stage". Only a fresh libusb context
      sees the truth, hence refresh_backend=True below.

    So instead of sleeping a fixed amount and hoping, drive the handoff as an
    explicit state machine: release the old handle, then poll -- rebuilding
    libusb's context each round -- until a device answers EP0 as U-Boot stage.
    If the loader never starts, the chip stays in BootROM and we re-push it.

    Returns (device, port_path) for the U-Boot-stage device.
    """
    last_error = None

    for attempt in range(1, LOADER_BOOT_ATTEMPTS + 1):
        brom_identity = device_identity(dev)  # for logging only

        handle_bootrom_mode(
            dev=dev,
            media_type=media_type,
            loader_file=loader_file,
            loader_address=loader_address,
            progress_callback=progress_callback,
        )

        # The chip is already jumping into the loader; all we owe it is to let
        # go of the handle. Resetting here would only force a second, competing
        # re-enumeration on a device that is mid-reboot.
        release_device(dev)
        dev = None

        try:
            dev, port_path = wait_for_device_mode(
                port_path,
                KBURN_USB_DEV_UBOOT,
                timeout=LOADER_ENUMERATION_TIMEOUT,
                refresh_backend=True,
            )
            logger.info("设备已切换至 U-Boot 模式")
            return dev, port_path
        except TimeoutError as e:
            last_error = e
            if attempt >= LOADER_BOOT_ATTEMPTS:
                break
            logger.warning(f"Loader 启动失败（第 {attempt}/{LOADER_BOOT_ATTEMPTS} 次）: {e}")
            # If the chip fell back into BootROM the loader simply did not take;
            # re-push it. If it is not there either, give up with the original error.
            try:
                dev, port_path = wait_for_device_mode(
                    port_path, KBURN_USB_DEV_BROM, timeout=LOADER_FALLBACK_TIMEOUT, refresh_backend=True
                )
                logger.info("设备重新回到 BootROM 模式，重试载入 loader")
            except TimeoutError:
                break

    raise RuntimeError(f"设备未能进入 U-Boot 模式: {last_error}")


def _normalise_media_type(media_type):
    """Reject an unusable media type before any hardware is touched.

    Library callers do not go through the argument parser, so without this the
    first sign of a typo is a ValueError raised after the device has been
    found, the loader pushed and the chip re-enumerated.
    """
    if not isinstance(media_type, str):
        raise TypeError(f"media_type must be a string, got {type(media_type).__name__}")
    canonical = normalise_media_type(media_type)
    if canonical is None:
        raise ValueError(f"Unsupported media_type: {media_type!r}; choose from {', '.join(MEDIA_TYPES)}")
    return canonical


def _flash_firmware(
    port_path,
    loader_file,
    loader_address,
    media_type,
    progress_callback,
    flash_func,
):
    """Helper function to flash firmware.

    auto_reboot/log_level used to be parameters here too, but the ones that
    took effect were the ones captured by the flash_func closure, so the copies
    passed down here were dead weight that read as if they did something.
    """
    # If no progress callback is provided, use the default one
    if progress_callback is None:
        progress_callback = default_progress_callback

    dev = None  # Initialize dev to None

    try:
        # Find and open the device
        dev, port_path = find_device(port_path=port_path)
        if dev is None:
            raise RuntimeError("USB device not found")
        else:
            init_device(dev)

        # Detect device mode
        dev_type = detect_device_type(dev)

        # Handle BootROM mode
        if dev_type == KBURN_USB_DEV_BROM:
            dev, port_path = _boot_loader_and_wait(
                dev=dev,
                port_path=port_path,
                media_type=media_type,
                loader_file=loader_file,
                loader_address=loader_address,
                progress_callback=progress_callback,
            )
            dev_type = KBURN_USB_DEV_UBOOT

        # Handle U-Boot mode
        if dev_type == KBURN_USB_DEV_UBOOT:
            flash_func(dev)
        else:
            raise RuntimeError("Device is not in a flashable mode")

    finally:
        # Ensure device resources are disposed of, regardless of success or failure.
        # release_device also drops the backend-level libusb reference now, which
        # matters because the handoff may have handed us a device belonging to a
        # private libusb context (see usb_utils.release_device).
        if dev:
            try:
                release_device(dev)
                logger.debug("USB device resources disposed.")
            except Exception as e:
                logger.warning(f"Error disposing USB device resources: {e}")


def flash_addr_file_pairs(
    addr_filename_pairs,
    port_path=None,
    loader_file=None,
    loader_address=DEFAULT_LOADER_ADDRESS,
    media_type="EMMC",
    auto_reboot=False,
    progress_callback=None,
    log_level=None,
):
    """
    Flashes multiple firmware files to specified addresses

    :param addr_filename_pairs: List of address and file path pairs, e.g., [(0x400000, "firmware1.img"), (0x800000, "firmware2.img")]
    :param port_path: USB device path (e.g., "1-2")
    :param loader_file: Custom loader file path
    :param loader_address: Loader load address (default 0x80360000)
    :param media_type: Storage media type (EMMC, SDCARD, SPI_NAND, SPI_NOR, OTP)
    :param auto_reboot: Whether to automatically reboot the device after flashing
    :param progress_callback: Progress callback function, receives (current, total) arguments
    :param log_level: deprecated, has no effect
    """
    _warn_if_log_level_passed(log_level)
    media_type = _normalise_media_type(media_type)

    if not addr_filename_pairs:
        # Writing nothing used to look exactly like a successful flash.
        raise ValueError("addr_filename_pairs is empty: nothing to flash")

    # Paths are coerced rather than required: the documented signature (and the
    # README example) passes plain strings, but everything downstream calls
    # .exists()/.stat(), so a string used to fail with a bare AttributeError --
    # and only after the loader had already been pushed to the board.
    pairs = []
    for addr, file_path in addr_filename_pairs:
        path = Path(file_path)
        if path.suffix.lower() != ".img":
            raise ValueError(f"File '{file_path}' must be in .IMG format")
        if not path.exists():
            raise FileNotFoundError(f"File '{path}' does not exist")
        if int(addr) < 0:
            raise ValueError(f"Address must not be negative: {addr}")
        pairs.append((int(addr), path))

    def flash_op(dev):
        handle_uboot_mode(
            dev=dev,
            media_type=media_type,
            auto_reboot=auto_reboot,
            progress_callback=progress_callback,
            addr_filename_pairs=pairs,
        )

    _flash_firmware(
        port_path=port_path,
        loader_file=loader_file,
        loader_address=loader_address,
        media_type=media_type,
        progress_callback=progress_callback,
        flash_func=flash_op,
    )


def flash_kdimg(
    kdimg_file,
    selected_partitions=None,  # New parameter for partition selection
    port_path=None,
    loader_file=None,
    loader_address=DEFAULT_LOADER_ADDRESS,
    media_type="EMMC",
    auto_reboot=False,
    progress_callback=None,
    log_level=None,
):
    """
    Flashes a .kdimg file, with optional partition selection or overlay

    :param kdimg_file: .kdimg file path
    :param selected_partitions: List of partition names to flash from kdimg, e.g., ["uboot_spl_a", "uboot_a"]
    :param port_path: USB device path (e.g., "1-2")
    :param loader_file: Custom loader file path
    :param loader_address: Loader load address (default 0x80360000)
    :param media_type: Storage media type (EMMC, SDCARD, SPI_NAND, SPI_NOR, OTP)
    :param auto_reboot: Whether to automatically reboot the device after flashing
    :param progress_callback: Progress callback function, receives (current, total) arguments
    :param log_level: deprecated, has no effect
    """
    _warn_if_log_level_passed(log_level)
    media_type = _normalise_media_type(media_type)

    # Validate file extension
    kdimg_path = Path(kdimg_file)
    if not kdimg_path.suffix.lower() == ".kdimg":
        raise ValueError(f"File '{kdimg_file}' must be in .KDIMG format")
    if not kdimg_path.exists():
        raise FileNotFoundError(f"File '{kdimg_path}' does not exist")

    if selected_partitions is not None:
        if isinstance(selected_partitions, str):
            # A bare string would iterate character by character and ask the
            # image for partitions named "u", "b", "o", ...
            raise TypeError("selected_partitions must be a list of names, not a single string")
        selected_partitions = list(selected_partitions)
        if not selected_partitions:
            raise ValueError("selected_partitions is empty: pass None to flash every partition")

    def flash_op(dev):
        handle_uboot_mode(
            dev=dev,
            media_type=media_type,
            auto_reboot=auto_reboot,
            progress_callback=progress_callback,
            kdimg_path=kdimg_path,
            selected_partitions=selected_partitions,
        )

    _flash_firmware(
        port_path=port_path,
        loader_file=loader_file,
        loader_address=loader_address,
        media_type=media_type,
        progress_callback=progress_callback,
        flash_func=flash_op,
    )
