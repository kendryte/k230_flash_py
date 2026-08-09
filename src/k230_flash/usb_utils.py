# usb_utils.py

import time

import usb.core
import usb.util
from loguru import logger

from .constants import USB_PID, USB_VID

# ----------------------------
# Constant definitions (refer to the original C++ definitions)
# ----------------------------

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


class DeviceNotFoundError(Exception):
    """No K230 in flashing mode matched the requested path.

    Raised instead of a bare Exception so the retry loop in main can tell
    "board is not plugged in yet" (worth waiting for) apart from a programming
    error (not worth waiting five minutes for).
    """


class DeviceOpenError(Exception):
    """A device was found but could not be configured for use."""


def list_usb_devices(vid=USB_VID, pid=USB_PID, backend=None):
    """Lists all connected K230 USB devices with bus and port paths.

    `backend` lets callers enumerate through a private libusb context (see
    fresh_usb_backend); None uses pyusb's process-wide one.
    """
    devices = usb.core.find(find_all=True, idVendor=vid, idProduct=pid, backend=backend)
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


def open_device_by_path(port_path=None, vid=USB_VID, pid=USB_PID):
    """Opens a device by matching the target_path against port_path.

    Devices that do not match are released rather than left for the garbage
    collector: every enumeration hands back live libusb handles, and holding
    open the ones we rejected is enough to disturb a later re-enumeration.
    """
    match = None
    for entry in list_usb_devices(vid, pid):
        if match is None and port_path and entry["port_path"] == port_path:
            match = entry["device"]
        else:
            release_device(entry["device"])
    return match


def find_device(port_path=None):
    """Find and return the USB device.

    :raises DeviceNotFoundError: if nothing matches.
    """
    if port_path:
        dev = open_device_by_path(port_path=port_path)
        if dev is None:
            raise DeviceNotFoundError(f"Device with port_path {port_path} not found")
    else:
        devices = list_usb_devices()
        if not devices:
            raise DeviceNotFoundError("No K230 USB devices found")
        dev = devices[0]["device"]
        port_path = devices[0]["port_path"]
        for entry in devices[1:]:
            release_device(entry["device"])

    return dev, port_path


def init_device(dev):
    """Ensure the device is configured and ready."""
    try:
        dev.set_configuration()
        return dev
    except usb.core.USBError as e:
        raise DeviceOpenError(f"USB device initialization failed: {e}") from e


_DEV_TYPE_NAMES = {
    KBURN_USB_DEV_INVALID: "未知/无响应",
    KBURN_USB_DEV_BROM: "BootROM",
    KBURN_USB_DEV_UBOOT: "U-Boot (loader)",
}


def detect_device_type(dev):
    """Detect device mode"""
    dev_type = probe_device(dev)
    # Logged by name, not as a bare integer: "设备模式: 1" told the user nothing
    # about which of the two stages the chip was in.
    logger.info(f"设备模式: {_DEV_TYPE_NAMES.get(dev_type, dev_type)}")
    return dev_type


def _read_cpu_info(dev):
    """Ask EP0 which stage the chip is in. Propagates usb.core.USBError.

    Split out from probe_device so the two callers can treat a failure
    differently: for a device we believe is ready it is an error worth
    reporting, while for one we are watching through a reboot it is the normal
    state of affairs.
    """
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


def probe_device(dev):
    """Probe a device that is expected to be ready; a failure here is an error."""
    try:
        return _read_cpu_info(dev)
    except usb.core.USBError as e:
        logger.error(f"Failed to probe device: {e}")
        return KBURN_USB_DEV_INVALID


def fresh_usb_backend():
    """Return a libusb backend with its own, brand-new context.

    pyusb memoises a single libusb context per process. On Windows that context
    does not notice a device that re-enumerated: it keeps reporting the
    pre-reboot bus/address *and* the pre-reboot configuration descriptor, so a
    running loader is still described with BootROM's endpoints (OUT 0x01 rather
    than OUT 0x02) even though EP0 already answers "Uboot Stage for K230".
    Measured on Windows 10 / pyusb 1.x: a freshly started process sees the
    correct descriptor, an already-running one never does. Linux does not need
    this (pass rates are identical either way), but it is harmless there.

    Note we deliberately do NOT `importlib.reload()` the backend module to get
    this, which is what this code used to do. Reloading swaps the module's
    library handle out from under every `usb.core.Device` already in flight, and
    their finalizers then call `libusb_unref_device` through freed state --
    observed as an access violation on Windows and a core dump on Linux. Building
    a separate context leaves the module singleton alone; each Device keeps its
    own backend alive by reference, so teardown stays ordered.

    Returns None if the private constructor is unavailable (pyusb layout change),
    in which case callers fall back to the process-wide backend.
    """
    try:
        import usb.backend.libusb1 as libusb1

        if libusb1.get_backend() is None:  # ensures the library itself is loaded
            return None
        return libusb1._LibUSB(libusb1._lib)
    except Exception as e:  # pragma: no cover - depends on pyusb internals
        logger.debug(f"无法创建独立的 libusb context，回退到全局 backend: {e}")
        return None


def release_device(dev):
    """Fully release a device, including its backend-level libusb reference.

    usb.util.dispose_resources() closes handles but leaves pyusb's backend device
    wrapper to be unref'd whenever the garbage collector gets round to it. That is
    harmless against pyusb's permanent context, but this module also builds private
    contexts (see fresh_usb_backend), and an unref that runs *after* its context
    has been torn down reads freed memory -- a segfault on Linux, an access
    violation on Windows. Finalizing here, while the context is still valid, makes
    the teardown order deterministic. finalize() is idempotent, so the later
    __del__ becomes a no-op.
    """
    if dev is None:
        return
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    try:
        dev._ctx.dev.finalize()
    except Exception:  # pragma: no cover - depends on pyusb internals
        pass


def device_identity(dev):
    """Return the (bus, address) pair that uniquely identifies a live device.

    Note this is *not* reliable for telling the pre- and post-reboot instances
    apart: on Windows the chip comes back at the same bus/address, so the pair
    is identical either side of the handoff. Use it for logging, not matching.
    """
    return (dev.bus, dev.address)


def _iter_matching_devices(port_path, vid=USB_VID, pid=USB_PID, backend=None):
    """Yield device entries on `port_path`, disposing the ones we skip."""
    for entry in list_usb_devices(vid, pid, backend=backend):
        if port_path and entry["port_path"] != port_path:
            release_device(entry["device"])
            continue
        yield entry


def wait_for_device_mode(
    port_path,
    expected_type,
    timeout=15.0,
    poll_interval=0.05,
    refresh_backend=False,
    refresh_interval=0.2,
    vid=USB_VID,
    pid=USB_PID,
):
    """Wait until a device on `port_path` actually reports `expected_type`.

    Presence on the bus is not readiness: right after the loader is started the
    old instance can still be listed for a moment, and the new one may enumerate
    before it answers EP0. So the gate is a successful EP0_GET_CPU_INFO probe
    returning the expected mode -- anything else just means "not yet", and we
    keep polling.

    `refresh_backend` periodically enumerates through a brand-new libusb context
    (at most every `refresh_interval` seconds). That is what makes the handoff
    work on Windows, where the process-wide context never notices the loader
    re-enumerating and keeps serving BootROM's descriptor (see
    fresh_usb_backend). We deliberately do NOT filter on the pre-reboot
    bus/address: on Windows the chip legitimately comes back at the same
    address, so that would reject the very device we are waiting for.

    Every context created here is kept alive until the function is done and then
    released in one go, after a collection -- pyusb's backend-level device
    wrappers don't hold their context alive, so freeing a context while one of
    its devices is still pending finalization crashes the interpreter.

    Returns (device, port_path) with the device configured and ready to use.
    Raises TimeoutError if the mode is not reached within `timeout`.
    """
    deadline = time.monotonic() + timeout
    probes = 0
    backends = []  # keep every context alive until the single release below
    backend = None
    next_refresh = 0.0
    dev = entry = None
    last_error = None  # reported only if we run out of time

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if refresh_backend and now >= next_refresh:
                fresh = fresh_usb_backend()
                if fresh is not None:
                    backends.append(fresh)
                    backend = fresh
                next_refresh = now + refresh_interval

            for entry in _iter_matching_devices(port_path, vid, pid, backend=backend):
                dev = entry["device"]
                probes += 1
                try:
                    # _read_cpu_info, not probe_device: a device that is
                    # mid-reboot answers EP0 with EIO, and that is the expected
                    # state here, not a fault. Logging each one at ERROR printed
                    # a wall of "Failed to probe device: [Errno 5] Input/Output
                    # Error" during a perfectly normal handoff, immediately
                    # followed by "设备已切换至 U-Boot 模式" -- which reads as if
                    # something went wrong and then the flash somehow worked
                    # anyway. The error is kept and reported only if the wait
                    # actually times out, where it is genuinely the reason.
                    if _read_cpu_info(dev) == expected_type:
                        dev.set_configuration()
                        logger.debug(f"设备就绪: {device_identity(dev)}，共探测 {probes} 次")
                        return dev, entry["port_path"]
                except usb.core.USBError as e:
                    last_error = e
                    logger.debug(f"设备尚未就绪（第 {probes} 次探测）: {e}")
                release_device(dev)
            dev = entry = None
            time.sleep(poll_interval)

        # Only here is a probe failure actually worth showing: the individual
        # failures above are what a reboot looks like, this is what never
        # coming back looks like.
        expected_name = _DEV_TYPE_NAMES.get(expected_type, expected_type)
        detail = f"，最后一次探测失败: {last_error}" if last_error else ""
        if probes == 0:
            detail = "，期间未发现任何匹配的设备"
        raise TimeoutError(
            f"等待设备 {port_path} 进入 {expected_name} 模式超时" f"（{timeout}s，探测 {probes} 次）{detail}"
        )
    finally:
        # Every rejected device was hard-released above, so no unref is pending
        # against these contexts and they can be dropped safely. The device we
        # return keeps its own context alive by reference.
        dev = entry = None
        backends.clear()
