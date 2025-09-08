# usb_utils.py
import time

import usb.core
import usb.util
from loguru import logger

# ----------------------------
# Constant definitions (refer to the original C++ definitions)
# ----------------------------
LIBUSB_TIMEOUT = 1000  # 毫秒

# EP0 commands
EP0_GET_CPU_INFO = 0
EP0_SET_DATA_ADDRESS = 1
EP0_SET_DATA_LENGTH = 2
EP0_PROG_START = 4

# USB device types
KBURN_USB_DEV_INVALID = 0
KBURN_USB_DEV_BROM = 1
KBURN_USB_DEV_UBOOT = 2

# Other parameters
USB_TIMEOUT = 1000  # 毫秒


def list_usb_devices(vid=0x29F1, pid=0x0230):
    """Lists all connected K230 USB devices with bus and port paths."""
    devices = usb.core.find(find_all=True, idVendor=vid, idProduct=pid)
    device_list = []
    for dev in devices:
        # --- Create stable port_path ---
        port_path = None

        if hasattr(dev, "port_numbers"):
            try:
                port_path_str = ".".join(str(p) for p in dev.port_numbers)
                port_path = f"{dev.bus}-{port_path_str}"
            except Exception:
                pass  # Ignore errors in getting port_numbers

        device_list.append(
            {
                "device": dev,
                "bus": dev.bus,
                "address": dev.address,
                "port_path": port_path,
                "vid": vid,
                "pid": pid,
            }
        )
    return device_list


def open_device_by_path(port_path=None, vid=0x29F1, pid=0x0230):
    """Opens a device by matching the target_path against port_path."""
    devices = list_usb_devices(vid, pid)
    for d in devices:
        # Check against both port_path
        if port_path and d["port_path"] == port_path:
            return d["device"]
    return None


def find_device(port_path=None):
    """Find and return the USB device"""
    if port_path:
        dev = open_device_by_path(port_path=port_path)
        if dev is None:
            raise Exception(f"Device with path port_path:{port_path} not found")
    else:
        devices = list_usb_devices()
        if not devices:
            raise Exception("No USB devices found")
        dev = devices[0]["device"]
        port_path = devices[0]["port_path"]

    return dev, port_path


def init_device(dev):
    """Ensure the device is configured and ready."""
    try:
        dev.set_configuration()
        return dev
    except usb.core.USBError as e:
        raise Exception(f"USB device initialization failed: {e}")


def detect_device_type(dev):
    """Detect device mode"""
    dev_type = probe_device(dev)
    logger.info(f"设备模式: {dev_type}")
    return dev_type


def probe_device(dev):
    try:
        info = dev.ctrl_transfer(
            bmRequestType=usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
            bRequest=EP0_GET_CPU_INFO,
            wValue=0,
            wIndex=0,
            data_or_wLength=32,
            timeout=USB_TIMEOUT,
        )
        info_str = bytes(info).decode("utf-8", errors="ignore").strip()
        logger.debug(f"设备 CPU 信息: {info_str}")
        if "Uboot Stage" in info_str:
            return KBURN_USB_DEV_UBOOT
        elif "K230" in info_str:
            return KBURN_USB_DEV_BROM
        else:
            return KBURN_USB_DEV_INVALID
    except usb.core.USBError as e:
        logger.error(f"Failed to probe device: {e}")
        return KBURN_USB_DEV_INVALID


def refresh_pyusb_after_reboot():
    """Workaround: Reloads pyusb modules to force re-enumeration of USB devices.
    This is often necessary after a device mode switch (e.g., BootROM to U-Boot)
    due to potential caching issues in pyusb/libusb that prevent detection of the new device state.
    Ideally, this would not be needed, but it ensures reliable device re-detection.
    """
    import importlib

    # importlib.reload(usb.core)
    # importlib.reload(usb.util)
    # importlib.reload(usb.backend)
    importlib.reload(usb.backend.libusb1)
