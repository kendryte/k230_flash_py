import json
from pathlib import Path

import usb.core
import usb.util
from loguru import logger

from .burners import handle_bootrom_mode, handle_uboot_mode
from .progress import progress_callback as default_progress_callback
from .usb_utils import (
    KBURN_USB_DEV_BROM,
    KBURN_USB_DEV_UBOOT,
    detect_device_type,
    find_device,
    init_device,
    list_usb_devices,
    refresh_pyusb_after_reboot,
)


def list_devices(vid=0x29F1, pid=0x0230, log_level="INFO"):
    """
    Lists all connected K230 USB devices

    :param vid: USB Vendor ID (default 0x29F1)
    :param pid: USB Product ID (default 0x0230)
    :param log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    :return: JSON string of the device list
    """
    # Set log level
    devices = list_usb_devices(vid, pid)
    device_list = [
        {
            "bus": dev["bus"],
            "address": dev["address"],
            "port_path": dev["port_path"],
            "vid": vid,
            "pid": pid,
        }
        for dev in devices
    ]
    return json.dumps(device_list, indent=4, ensure_ascii=False)


def _flash_firmware(
    port_path,
    loader_file,
    loader_address,
    media_type,
    auto_reboot,
    progress_callback,
    log_level,
    flash_func,
):
    """Helper function to flash firmware."""
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
            handle_bootrom_mode(
                dev=dev,
                media_type=media_type,
                loader_file=loader_file,
                loader_address=loader_address,
                progress_callback=progress_callback,
            )
            
            try:
                # 释放旧设备资源，刷新 USB 设备列表
                dev.reset()  # Reset the device to clear any state
                usb.util.dispose_resources(dev)
                dev = None  # Set dev to None after disposing
                # 刷新 pyusb 以重新枚举设备
                refresh_pyusb_after_reboot()
                logger.debug("刷新 pyusb 以重新枚举设备")
            except Exception as e:
                pass

            dev, port_path = find_device(port_path=port_path)
            if dev is None:
                raise RuntimeError("USB device not found")
            init_device(dev)
            # Re-detect device type after flashing

            dev_type = detect_device_type(dev)

        # Handle U-Boot mode
        if dev_type == KBURN_USB_DEV_UBOOT:
            flash_func(dev)
            # dev.reset()  # Reset the device to clear any state - moved to finally
            # usb.util.dispose_resources(dev) - moved to finally
            # dev = None - moved to finally
        else:
            raise RuntimeError("Device is not in a flashable mode")

    finally:
        # Ensure device resources are disposed of, regardless of success or failure
        if dev:
            try:
                dev.reset()  # Reset the device before disposing
                usb.util.dispose_resources(dev)
                logger.debug("USB device resources disposed.")
            except Exception as e:
                logger.warning(f"Error disposing USB device resources: {e}")


def flash_addr_file_pairs(
    addr_filename_pairs,
    port_path=None,
    loader_file=None,
    loader_address=0x80360000,
    media_type="EMMC",
    auto_reboot=False,
    progress_callback=None,
    log_level="INFO",
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
    :param log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Validate file extensions
    for addr, file_path in addr_filename_pairs:
        if not Path(file_path).suffix.lower() == ".img":
            raise ValueError(f"File '{file_path}' must be in .IMG format")

    def flash_op(dev):
        handle_uboot_mode(
            dev=dev,
            media_type=media_type,
            auto_reboot=auto_reboot,
            progress_callback=progress_callback,
            addr_filename_pairs=addr_filename_pairs,
        )

    _flash_firmware(
        port_path=port_path,
        loader_file=loader_file,
        loader_address=loader_address,
        media_type=media_type,
        auto_reboot=auto_reboot,
        progress_callback=progress_callback,
        log_level=log_level,
        flash_func=flash_op,
    )


def flash_kdimg(
    kdimg_file,
    selected_partitions=None,  # New parameter for partition selection
    port_path=None,
    loader_file=None,
    loader_address=0x80360000,
    media_type="EMMC",
    auto_reboot=False,
    progress_callback=None,
    log_level="INFO",
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
    :param log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Validate file extension
    kdimg_path = Path(kdimg_file)
    if not kdimg_path.suffix.lower() == ".kdimg":
        raise ValueError(f"File '{kdimg_file}' must be in .KDIMG format")

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
        auto_reboot=auto_reboot,
        progress_callback=progress_callback,
        log_level=log_level,
        flash_func=flash_op,
    )
