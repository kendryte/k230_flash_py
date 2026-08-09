# burners.py
import importlib.resources
import io
import struct
import time
from pathlib import Path

import usb.core
import usb.util
from loguru import logger

from .constants import MEDIA_TYPES, normalise_media_type
from .kdimage import get_kdimage_items
from .kdimg_utils import write_kdimg
from .usb_utils import EP0_PROG_START, EP0_SET_DATA_ADDRESS, USB_TIMEOUT


# 自定义异常类
class BurnerError(Exception):
    """烧录器基础异常类"""

    pass


class USBCommunicationError(BurnerError):
    """USB通信异常"""

    pass


class DeviceConfigurationError(BurnerError):
    """设备配置异常"""

    pass


class DataWriteError(BurnerError):
    """数据写入异常"""

    pass


class DeviceProbeError(BurnerError):
    """设备探测异常"""

    pass


class LoaderError(BurnerError):
    """Loader相关异常"""

    pass


# Media types
KBURN_MEDIUM_INVALID = 0
KBURN_MEDIUM_EMMC = 1
KBURN_MEDIUM_SDCARD = 2
KBURN_MEDIUM_SPI_NAND = 3
KBURN_MEDIUM_SPI_NOR = 4
KBURN_MEDIUM_OTP = 5

# Command definitions
KBURN_CMD_NONE = 0
KBURN_CMD_REBOOT = 0x01
KBURN_CMD_DEV_PROBE = 0x10
KBURN_CMD_DEV_GET_INFO = 0x11
KBURN_CMD_ERASE_LBA = 0x20
KBURN_CMD_WRITE_LBA = 0x21
KBURN_CMD_WRITE_LBA_CHUNK = 0x22
KBURN_CMD_READ_LBA = 0x23
KBURN_CMD_READ_LBA_CHUNK = 0x24

CMD_FLAG_DEV_TO_HOST = 0x8000
PACKET_SIZE = 60  # The entire USB packet is fixed at 60 bytes
HEADER_SIZE = 6  # Header contains: uint16_t cmd, uint16_t result, uint16_t data_size
MAX_DATA_SIZE = PACKET_SIZE - HEADER_SIZE  # 54 bytes

KBURN_RESULT_OK = 0x1

REBOOT_MARK = 0x52626F74

# Command round trips are quick; bulk payload chunks are not, because the gadget
# writes each chunk to the medium synchronously before accepting the next one, so
# a 128 KiB chunk can stall behind a slow SD/NAND write. A spurious timeout mid
# stream desynchronises the whole transfer, so these are deliberately generous.
DATA_TIMEOUT = 15000  # ms, per bulk payload chunk
WRITE_ACK_TIMEOUT = 30000  # ms, final "WRITE DONE" after the last chunk is committed
DRAIN_TIMEOUT = 50  # ms, per stale packet when resynchronising
MAX_DRAIN_PACKETS = 4


def do_sleep(ms):
    time.sleep(ms / 1000.0)


class KBurner:
    def __init__(self, dev):
        self.dev = dev  # usb.core.Device object
        self.media_type = KBURN_MEDIUM_INVALID
        self.progress_callback = None
        self.ep_in = None
        self.ep_out = None

    def _discover_endpoints(self):
        """Read the bulk endpoint pair from the device's active configuration.

        The addresses differ between the two stages -- BootROM exposes OUT 0x01,
        the U-Boot loader exposes OUT 0x02 -- so they must always be re-read from
        the descriptor of the device we are actually holding, never assumed nor
        carried over from before the loader was started.
        """
        cfg = self.dev.get_active_configuration()
        for interface in cfg:
            for endpoint in interface:
                if usb.util.endpoint_type(endpoint.bmAttributes) != usb.util.ENDPOINT_TYPE_BULK:
                    continue
                if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN:
                    if self.ep_in is None:
                        self.ep_in = endpoint.bEndpointAddress
                elif self.ep_out is None:
                    self.ep_out = endpoint.bEndpointAddress

        if self.ep_in is None or self.ep_out is None:
            raise DeviceConfigurationError(
                f"未能找到完整的 Bulk 端点对 (IN={self.ep_in}, OUT={self.ep_out})，" "设备可能仍在重新枚举"
            )
        logger.debug(f"Bulk endpoints: IN={hex(self.ep_in)} OUT={hex(self.ep_out)}")

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def log_progress(self, current, total):
        if self.progress_callback:
            self.progress_callback(current, total)
        else:
            percent = (current / total * 100) if total else 0
            logger.info(f"Progress: {percent:.2f}% ({current}/{total})")

    def write(self, data, address):
        raise NotImplementedError("The write method must be implemented in a derived class")


class K230BROMBurner(KBurner):
    def __init__(self, dev):
        super().__init__(dev)
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            logger.error(f"set_configuration error: {e}")
        self._discover_endpoints()

    def boot_from(self, address=0x80360000):
        # Send EP0_PROG_START command to start the loader
        addr_high = (address >> 16) & 0xFFFF
        addr_low = address & 0xFFFF
        try:
            ret = self.dev.ctrl_transfer(
                bmRequestType=usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                bRequest=EP0_PROG_START,
                wValue=addr_high,
                wIndex=addr_low,
                data_or_wLength=None,
                timeout=USB_TIMEOUT,
            )
            logger.debug(f"boot_from: return value {ret}")
        except usb.core.USBError as e:
            logger.error(f"boot_from failed: {e}")
            raise USBCommunicationError(f"启动Loader失败，地址: {hex(address)}, 错误: {e}")

    def get_loader_path(self, filename):
        """Get the path of the bin file in the `loaders` directory"""
        return str(importlib.resources.files("k230_flash").joinpath("loaders", filename))

    def get_loader(self, media_type="EMMC"):
        # Select different built-in loaders according to media_type
        loader_map = {
            "EMMC": "loader_mmc.bin",
            "SDCARD": "loader_mmc.bin",
            "SPI_NAND": "loader_spi_nand.bin",
            "SPI_NOR": "loader_spi_nor.bin",
        }

        media_type_upper = normalise_media_type(media_type) or media_type.strip().upper()
        if media_type_upper not in loader_map:
            # OTP lands here: the loader stage can write it, but no
            # loader_otp.bin exists to *boot* from BootROM, so the only way to
            # reach OTP is with an already-running loader or a custom -lf.
            if media_type_upper in MEDIA_TYPES:
                raise LoaderError(
                    f"介质类型 {media_type_upper} 没有内置 loader，无法从 BootROM 启动；"
                    f"请改用 -lf/--loader-file 指定 loader，或选择 {', '.join(loader_map)} 之一"
                )
            raise ValueError(f"Unsupported media_type: {media_type}")

        loader_filename = loader_map[media_type_upper]
        loader_path = Path(self.get_loader_path(loader_filename)).resolve()
        logger.debug(f"Selected loader file for {media_type}: {loader_path}")

        if not loader_path.exists():
            raise FileNotFoundError(f"Loader file {loader_path} does not exist")
        try:
            with loader_path.open("rb") as f:
                loader_data = f.read()
            logger.info(f"Successfully loaded loader: {loader_path}")
            return loader_data
        except Exception as e:
            raise RuntimeError(f"Failed to read Loader: {e}")

    def set_data_address(self, address=0x80360000):
        addr_high = (address >> 16) & 0xFFFF
        addr_low = address & 0xFFFF
        try:
            ret = self.dev.ctrl_transfer(
                bmRequestType=usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                bRequest=EP0_SET_DATA_ADDRESS,
                wValue=addr_high,
                wIndex=addr_low,
                data_or_wLength=None,
                timeout=USB_TIMEOUT,
            )
            logger.debug(f"set_data_address: return value {ret}")
        except usb.core.USBError as e:
            logger.error(f"set_data_address failed: {e}")
            raise USBCommunicationError(f"设置数据地址失败，地址: {hex(address)}, 错误: {e}")

    def write_data_chunk(self, chunk):
        try:
            written = self.dev.write(self.ep_out, chunk, timeout=USB_TIMEOUT)
            if written != len(chunk):
                logger.error("write_data_chunk write length is insufficient")
                raise DataWriteError(f"数据块写入长度不足，期望: {len(chunk)}, 实际: {written}")
        except usb.core.USBError as e:
            logger.error(f"write_data_chunk failed: {e}")
            raise USBCommunicationError(f"数据块写入失败: {e}")

    def write(self, data, address=0x80360000):
        PAGE_SIZE = 1000  # Corresponds to K230_SRAM_PAGE_SIZE in C++
        try:
            self.set_data_address(address)
            total_size = len(data)
            pages = (total_size + PAGE_SIZE - 1) // PAGE_SIZE
            for page in range(pages):
                offset = page * PAGE_SIZE
                chunk = data[offset : offset + PAGE_SIZE]
                self.write_data_chunk(chunk)
                self.log_progress(min(offset + len(chunk), total_size), total_size)
            self.log_progress(total_size, total_size)
        except (USBCommunicationError, DataWriteError) as e:
            logger.error(f"写入数据失败: {e}")
            raise
        except Exception as e:
            logger.error(f"写入数据时发生未知错误: {e}")
            raise DataWriteError(f"数据写入失败: {e}")


class K230UBOOTBurner(KBurner):
    def __init__(self, dev, media_type_str="EMMC"):
        super().__init__(dev)
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            logger.error(f"set_configuration error: {e}")
            raise DeviceConfigurationError(f"USB设备配置失败: {e}")

        self._discover_endpoints()

        # Negotiated by probe(); write_chunks_from reads out_chunk_size, so it
        # must exist even if a caller skips the probe -- it used to be set only
        # inside probe(), turning that mistake into a bare AttributeError.
        self.out_chunk_size = None
        self.in_chunk_size = None
        self.capacity = None  # Device capacity
        self.blk_sz = 512  # Block size
        self.erase_size = 512  # Erase size
        self.wp = 0  # Write protection

        # Set the media type according to the incoming string
        media_map = {
            "EMMC": KBURN_MEDIUM_EMMC,
            "SDCARD": KBURN_MEDIUM_SDCARD,
            "SPI_NAND": KBURN_MEDIUM_SPI_NAND,
            "SPI_NOR": KBURN_MEDIUM_SPI_NOR,
            "OTP": KBURN_MEDIUM_OTP,
        }
        # Same normalisation as the CLI and the api, so "spi-nand" or "nand"
        # mean the same thing whichever door a caller came in through.
        canonical = normalise_media_type(media_type_str)
        if canonical is None or canonical not in media_map:
            raise ValueError(f"Unsupported media_type: {media_type_str}")
        self.media_type = media_map[canonical]

    def reboot(self):
        """
        发送重启命令到设备
        使用 KBURN_CMD_REBOOT 命令实现真正的设备重启
        注意：重启命令比较特殊，设备可能在收到命令后立即重启，无法正常响应

        Returns True if the command went out cleanly. A USB error is *not* a
        failure here -- the device rebooting mid-transfer looks exactly like
        one -- but anything else is, and the caller is expected to say so
        rather than announce a reboot that never happened.
        """
        logger.info("正在重启设备...")

        try:
            # 清除可能的错误状态
            self.kburn_nop()

            # Construct configuration data
            cfg_data = struct.pack("<Q", REBOOT_MARK)
            self.send_cmd(KBURN_CMD_REBOOT, cfg_data, expected_response_length=0)

            # 等待设备重启完成
            logger.info("等待设备重启完成...")
            do_sleep(2000)  # 等待2秒让设备完成重启过程

            return True

        except (usb.core.USBError, USBCommunicationError) as e:
            logger.warning(f"重启命令发送过程中发生 USB 错误: {e}")
            logger.info("设备可能已开始重启过程，将等待完成")
            # 即使 USB 通信失败，设备也可能已经开始重启
            do_sleep(2000)
            return True

        except Exception as e:
            logger.error(f"重启设备时发生未知错误: {e}")
            # 即使发生错误，也尝试等待一段时间
            do_sleep(2000)
            return False

    def kburn_nop(self):
        """Send KBURN_CMD_NONE command to clear device error status"""
        logger.debug("Sending NOP (KBURN_CMD_NONE) command to clear device error status")

        # Drain anything the device may still have queued. Now that every command
        # response is consumed by its issuer (see write_end) this normally finds
        # nothing, so the timeout is short -- it used to be 1s and was paid on
        # every partition as well as on every probe.
        for _ in range(MAX_DRAIN_PACKETS):
            try:
                self.dev.read(self.ep_in, PACKET_SIZE, timeout=DRAIN_TIMEOUT)
            except usb.core.USBError:
                break

        # Send KBURN_CMD_NONE
        self.send_cmd(KBURN_CMD_NONE, b"", expected_response_length=16)

    def write_start(self, offset: int, size: int) -> bool:
        """Initialize write operation"""
        if offset < 0 or size < 0:
            raise ValueError(f"写入参数非法，偏移: {offset}, 大小: {size}")

        # Check alignment
        if offset % self.blk_sz != 0:
            logger.error("Address not aligned to erase size")
            raise ValueError(f"地址未对齐到擦除大小，偏移: {offset}, 块大小: {self.blk_sz}")

        # The kdimg path checks the image against the capacity before it starts,
        # but the raw [address, file] path had no check at all: an image too big
        # for the medium just failed somewhere deep in the protocol with a
        # timeout. Catch it here so both paths report the same clear error.
        if self.capacity and offset + size > self.capacity:
            raise ValueError(
                f"写入超出设备容量: 偏移 0x{offset:X} + {size} 字节 = {offset + size} 字节, "
                f"设备容量 {self.capacity} 字节 ({self.capacity // (1024*1024)} MB)"
            )

        self.kburn_nop()  # Clear device error status

        # Construct configuration data
        part_flags = 0x00
        cfg_data = struct.pack("<QQQQ", offset, size, size, part_flags)
        expected_info_size = 8
        response = self.send_cmd(KBURN_CMD_WRITE_LBA, cfg_data, expected_response_length=expected_info_size)
        if response is None or len(response) != expected_info_size:
            logger.error(
                f"write_start: failed to get valid response, expected {expected_info_size} bytes, "
                f"got {len(response) if response else None}"
            )
            raise DataWriteError(
                f"初始化写入操作失败，期望响应: {expected_info_size} 字节，实际: {len(response) if response else None}"
            )
        return True

    def write_chunks(self, data: bytes) -> bool:
        """Write data chunks"""
        return self.write_chunks_from(io.BytesIO(data), len(data))

    def write_chunks_from(self, stream, total_size: int) -> bool:
        """Stream `total_size` bytes from `stream` to the device's OUT endpoint.

        Reading a chunk at a time keeps peak memory at one chunk instead of the
        whole image, which matters for the multi-GB single-file case.
        """
        if not self.out_chunk_size:
            raise DataWriteError("尚未协商传输块大小，请先调用 probe()")

        chunk_size = self.out_chunk_size
        bytes_sent = 0
        try:
            while bytes_sent < total_size:
                chunk = stream.read(min(chunk_size, total_size - bytes_sent))
                if not chunk:
                    raise DataWriteError(f"数据源提前结束: 已发送 {bytes_sent}/{total_size} 字节")
                self.dev.write(self.ep_out, chunk, timeout=DATA_TIMEOUT)
                bytes_sent += len(chunk)
                self.log_progress(bytes_sent, total_size)

            # Send zero-length packet (if needed)
            if total_size % chunk_size == 0:
                self.dev.write(self.ep_out, b"", timeout=DATA_TIMEOUT)

            return True
        except usb.core.USBError as e:
            logger.error(f"Write chunk failed: {str(e)}")
            raise USBCommunicationError(f"数据块写入失败: {e}")

    def write_end(self) -> bool:
        """Consume and verify the device's end-of-write acknowledgement.

        The gadget replies "WRITE DONE" once it has committed every byte it was
        promised, or "WRITE ERROR, 0x.." if a medium write failed. This used to
        be a no-op, which meant two things: a failed write was reported to the
        caller as a success, and the unread packet left the response pipe one
        step out of sync for the next command.
        """
        try:
            response = self.dev.read(self.ep_in, PACKET_SIZE, timeout=WRITE_ACK_TIMEOUT)
        except usb.core.USBError as e:
            logger.error(f"write_end: no completion response: {e}")
            raise DataWriteError(f"未收到写入完成应答: {e}")

        if len(response) < HEADER_SIZE:
            raise DataWriteError(f"写入完成应答长度异常: {len(response)} 字节")

        resp_cmd, resp_result, resp_size = struct.unpack("<HHH", bytes(response[:HEADER_SIZE]))
        message = bytes(response[HEADER_SIZE : HEADER_SIZE + resp_size]).decode("utf-8", errors="ignore")

        if resp_cmd != (KBURN_CMD_WRITE_LBA | CMD_FLAG_DEV_TO_HOST):
            raise DataWriteError(
                f"写入完成应答命令不匹配: 得到 0x{resp_cmd:04x}, "
                f"期望 0x{(KBURN_CMD_WRITE_LBA | CMD_FLAG_DEV_TO_HOST):04x}"
            )
        if resp_result != KBURN_RESULT_OK:
            raise DataWriteError(f"设备报告写入失败: {message}")

        logger.debug(f"write_end: {message}")
        return True

    def write_image_stream(self, stream, size: int, offset: int) -> bool:
        """Write `size` bytes read from `stream` at `offset`."""
        try:
            self.write_start(offset, size)
            self.write_chunks_from(stream, size)
            return self.write_end()
        except (ValueError, DataWriteError, USBCommunicationError) as e:
            logger.error(f"镜像写入失败: {e}")
            raise
        except Exception as e:
            logger.error(f"镜像写入时发生未知错误: {e}")
            raise DataWriteError(f"镜像写入失败: {e}")

    def write_image(self, data: bytes, offset: int) -> bool:
        """Complete write process"""
        try:
            self.write_start(offset, len(data))
            self.write_chunks(data)
            return self.write_end()
        except (ValueError, DataWriteError, USBCommunicationError) as e:
            logger.error(f"镜像写入失败: {e}")
            raise
        except Exception as e:
            logger.error(f"镜像写入时发生未知错误: {e}")
            raise DataWriteError(f"镜像写入失败: {e}")

    def send_cmd(self, cmd, data, expected_response_length):
        """
        Constructs and sends a USB command packet, the packet format is as follows:
            - Header (6 bytes): uint16_t cmd, uint16_t result, uint16_t data_size
            - Data area (54 bytes): if the data length is less than 54 bytes, it is padded with 0 on the right
        After sending, read a fixed 60-byte response packet from the device and parse it:
            - The cmd in the response header should be (cmd | CMD_FLAG_DEV_TO_HOST)
            - The response header result should be KBURN_RESULT_OK (1)
            - The response header data_size should match expected_response_length
        Returns the response data part (bytes) on success, otherwise raises exception.
        """
        # cmd = 0x10
        # data = b'\x01\xff'

        if len(data) > MAX_DATA_SIZE:
            logger.error(f"send_cmd: command data size too large ({len(data)} bytes)")
            raise ValueError(f"命令数据太大: {len(data)} 字节")

        # Construct header: cmd, result (set to 0), data_size
        header = struct.pack("<HHH", cmd, 0, len(data))
        # Construct the complete packet, padding the data area with 0s on the right if it is not full
        packet = header + data.ljust(MAX_DATA_SIZE, b"\x00")
        if len(packet) != PACKET_SIZE:
            logger.error(f"send_cmd: packet size error: {len(packet)} bytes")
            raise ValueError(f"数据包大小错误: {len(packet)} 字节")

        try:
            # Send USB packet to the write endpoint
            self.dev.write(self.ep_out, packet, timeout=USB_TIMEOUT)
        except Exception as e:
            logger.error(f"send_cmd: write failed: {e}")
            raise USBCommunicationError(f"USB命令写入失败: {e}")

        if expected_response_length == 0:
            return None

        try:
            # Read 60-byte response from the read endpoint
            response = self.dev.read(self.ep_in, PACKET_SIZE, timeout=USB_TIMEOUT)
        except Exception as e:
            logger.error(f"send_cmd: read failed: {e}")
            raise USBCommunicationError(f"USB命令响应读取失败: {e}")

        if len(response) < HEADER_SIZE:
            logger.error(f"send_cmd: response too short ({len(response)} bytes)")
            raise USBCommunicationError(f"响应数据太短: {len(response)} 字节")

        # Parse response header: return value result, data area length data_size
        resp_cmd, resp_result, resp_data_size = struct.unpack("<HHH", bytes(response[:HEADER_SIZE]))
        # Check if the response command is correct: should be (cmd | CMD_FLAG_DEV_TO_HOST)
        if resp_cmd != (cmd | CMD_FLAG_DEV_TO_HOST):
            logger.error(
                f"send_cmd: response cmd mismatch: got 0x{resp_cmd:04x}, expected 0x{(cmd | CMD_FLAG_DEV_TO_HOST):04x}"
            )
            raise USBCommunicationError(
                f"响应命令不匹配: 得到 0x{resp_cmd:04x}, 期望 0x{(cmd | CMD_FLAG_DEV_TO_HOST):04x}"
            )
        if resp_result != KBURN_RESULT_OK and cmd != KBURN_CMD_NONE:
            # On failure the device puts a human-readable reason in the data area
            # ("DATA SIZE EXCEED", "MEDIUM INFO INVALID", "PROBE FAILED", ...).
            # Dropping it left the user with a bare result code and a guess about
            # the storage medium, which was wrong as often as it was right.
            reason = (
                bytes(response[HEADER_SIZE : HEADER_SIZE + resp_data_size]).decode("utf-8", errors="ignore").strip()
            )
            logger.error(f"send_cmd: response error, result = 0x{resp_result:04X}, message = {reason!r}")
            detail = f": {reason}" if reason else "，请检查目标存储介质是否存在？"
            raise USBCommunicationError(f"设备响应错误 0x{resp_result:04X}{detail}")
        if resp_data_size != expected_response_length:
            logger.error(
                f"send_cmd: response data size mismatch, expected {expected_response_length}, got {resp_data_size}"
            )
            raise USBCommunicationError(f"响应数据长度不匹配: 期望 {expected_response_length}, 实际 {resp_data_size}")

        # Return the data area
        return bytes(response[HEADER_SIZE : HEADER_SIZE + resp_data_size])

    def probe(self):
        """
        Probe the device media type. Construct a 2-byte payload:
            - Byte 1: media_type (set externally)
            - Byte 2: 0xFF
        Send the probe command KBURN_CMD_DEV_PROBE, the expected response data is 16 bytes (2 uint64_t).
        Save the parsed two 64-bit values to out_chunk_size and in_chunk_size respectively.
        """
        if self.media_type is None:
            logger.error("probe: media_type is not set")
            raise DeviceProbeError("设备媒体类型未设置")

        self.kburn_nop()  # Clear device error status

        payload = bytes([self.media_type, 0xFF])
        logger.debug(f"probe: target medium type {self.media_type}")

        response = self.send_cmd(KBURN_CMD_DEV_PROBE, payload, expected_response_length=16)
        if response is None or len(response) != 16:
            logger.error("probe: failed to get valid response")
            raise DeviceProbeError(f"设备探测失败，期望响应: 16 字节，实际: {len(response) if response else None}")

        # Parse the 16-byte response into two uint64_t, little-endian
        out_chunk_size, in_chunk_size = struct.unpack("<QQ", response)
        logger.debug(f"probe: out_chunk_size = {out_chunk_size}, in_chunk_size = {in_chunk_size}")
        # A zero chunk size would make write_chunks_from read 0 bytes forever
        # and then divide by it for the zero-length-packet check; say what is
        # actually wrong instead of surfacing ZeroDivisionError.
        if out_chunk_size <= 0:
            raise DeviceProbeError(f"设备返回了非法的传输块大小: {out_chunk_size}")
        self.out_chunk_size = out_chunk_size
        self.in_chunk_size = in_chunk_size

    def get_capacity(self):
        """
        Use the KBURN_CMD_DEV_GET_INFO command to get device media information.
        The device returns four little-endian uint64_t ("<QQQQ", 32 bytes):
            - capacity   : total medium size in bytes
            - blk_sz     : block size
            - erase_size : erase granularity
            - bitfields  : timeout_ms (bits 0-31), wp (32-39), type (40-46),
                           valid (47); the top 16 bits are unused
        Returns the capacity value, or raises exception on failure.
        """
        expected_info_size = 32
        try:
            response = self.send_cmd(KBURN_CMD_DEV_GET_INFO, b"", expected_response_length=expected_info_size)
        except (USBCommunicationError, ValueError) as e:
            logger.error(f"get_capacity: 获取设备信息失败: {e}")
            raise DeviceProbeError(f"获取设备容量信息失败: {e}")

        if response is None or len(response) != expected_info_size:
            logger.error(
                f"get_capacity: failed to get valid response, expected {expected_info_size} bytes, got {len(response) if response else None}"
            )
            raise DeviceProbeError(
                f"获取设备容量信息失败，期望 {expected_info_size} 字节，实际 {len(response) if response else None}"
            )

        # Parse medium info
        capacity, blk_sz, erase_size, bitfields = struct.unpack("<QQQQ", response)
        # Parse the bitfields of the last 8 bytes (bitfields):
        # The lower 32 bits are timeout_ms
        timeout_ms = bitfields & 0xFFFFFFFF
        # The next 8 bits are wp
        wp = (bitfields >> 32) & 0xFF
        # The next 7 bits are type
        type_val = (bitfields >> 40) & 0x7F
        # The next 1 bit is valid (the remaining 16 bits are unused)
        valid = (bitfields >> 47) & 0x01

        logger.info(f"设备信息: 容量 {capacity // (1024*1024)} MB, 块大小 {blk_sz}, 擦除大小 {erase_size}")
        self.capacity = capacity
        self.blk_sz = blk_sz
        self.erase_size = erase_size
        self.wp = wp
        self.device_type = type_val

        return capacity


def handle_bootrom_mode(dev, media_type, loader_address, loader_file, progress_callback):
    """处理 BootROM 模式，下载 loader 并启动至 U-Boot

    Exceptions propagate as-is. There used to be four except-clauses here that
    each logged and re-raised the same exception, which produced the same
    message twice and hid nothing.
    """
    burner = K230BROMBurner(dev)
    # burner.set_progress_callback(progress_callback)   # bootrom无需进度回调

    # 读取 loader
    if loader_file:
        loader_path = Path(loader_file)
        try:
            loader_data = loader_path.read_bytes()
        except OSError as e:
            # Not FileNotFoundError unconditionally: a loader that exists but
            # cannot be read (permissions, bad mount) used to be reported as
            # "file not found", which sends people looking in the wrong place.
            raise LoaderError(f"读取 loader 文件失败 ({loader_path}): {e}") from e
        if not loader_data:
            raise LoaderError(f"loader 文件为空: {loader_path}")
        logger.info(f"使用自定义 loader: {loader_path} ({len(loader_data)} 字节)")
    else:
        loader_data = burner.get_loader(media_type)
        if not loader_data:
            raise LoaderError("获取内置 loader 失败")

    # 写入并启动 loader
    try:
        burner.write(loader_data, loader_address)
        burner.boot_from(loader_address)
    except (USBCommunicationError, DataWriteError) as e:
        raise LoaderError(f"Loader 操作失败: {e}") from e

    # No sleep here on purpose: the caller watches the device leave the bus
    # and come back, which is both faster and more reliable than guessing.
    logger.info("loader 写入成功，等待设备切换至 U-Boot 模式")


def handle_uboot_mode(
    dev,
    media_type,
    auto_reboot,
    progress_callback,
    kdimg_path=None,
    addr_filename_pairs=None,
    selected_partitions=None,
):
    """处理 U-Boot 模式，执行烧录"""
    burner = K230UBOOTBurner(dev, media_type)
    burner.set_progress_callback(progress_callback)

    try:
        burner.probe()
    except (DeviceProbeError, USBCommunicationError) as e:
        # A probe timeout here is almost always the loader failing to initialise
        # the storage medium, not a USB problem. cb_probe_device() runs the
        # medium init synchronously inside the USB completion handler, so when
        # that init fails the gadget stops servicing BOTH endpoints -- the device
        # cannot even be sent KBURN_CMD_REBOOT afterwards. Nothing the host does
        # can recover it, so say so plainly instead of surfacing "read timeout".
        raise RuntimeError(
            f"U-Boot 模式探测失败（介质类型 {media_type}）: {e}\n"
            f"  设备已停止响应，主机侧无法恢复。请依次检查：\n"
            f"  1) -m/--media-type 是否与实际硬件一致（当前: {media_type}）；\n"
            f"  2) 存储介质是否插好、是否被写保护；\n"
            f"  3) 给开发板重新上电后再试 —— loader 的介质初始化失败后必须断电复位。"
        ) from e

    try:
        burner.get_capacity()
    except (DeviceProbeError, USBCommunicationError) as e:
        raise RuntimeError(f"获取设备容量信息失败: {e}") from e

    if not kdimg_path and not addr_filename_pairs:
        # Writing nothing and returning True looked identical to a successful
        # flash, which is the worst possible way to report a dropped argument.
        raise ValueError("没有需要烧录的内容")

    # 计算总大小并记录开始时间
    total_size = 0
    if kdimg_path:
        kdimg_path = Path(kdimg_path)
        if not kdimg_path.exists():
            raise FileNotFoundError(f"KDIMG 文件 {kdimg_path} 不存在")

        items = get_kdimage_items(kdimg_path)
        if not items:
            raise RuntimeError(f"无法解析 kdimg 文件: {kdimg_path}")

        if selected_partitions:
            # Only count selected partitions
            total_size = sum(item.writeSize for item in items.data if item.partName in selected_partitions)
        else:
            # Count all partitions
            total_size = sum(item.writeSize for item in items.data)
    else:
        for _addr, file in addr_filename_pairs:
            if not file.exists():
                raise FileNotFoundError(f"文件 {file} 不存在")
        total_size = sum(file.stat().st_size for _, file in addr_filename_pairs)

    logger.info(f"准备烧录，总大小: {total_size / 1024 / 1024:.2f} MB")
    start_time = time.time()

    # 执行烧录
    if kdimg_path and selected_partitions:
        logger.info(f"模式 3: 选择性烧录 kdimg 文件: {kdimg_path}")
        logger.info(f"  - 选中的分区: {', '.join(selected_partitions)}")
        write_kdimg(kdimg_path, burner, selected_partitions=selected_partitions)
    elif kdimg_path:
        logger.info(f"模式 2: 烧录 kdimg 文件: {kdimg_path}")
        write_kdimg(kdimg_path, burner)
    else:
        logger.info("模式 1: 烧录 image 文件列表")
        for addr, file in addr_filename_pairs:
            logger.info(f"  - 烧录地址: 0x{addr:08X}, 文件: {file}")
        write_images(addr_filename_pairs, burner)

    # 计算并打印速度
    elapsed_time = time.time() - start_time

    logger.info("固件写入完成")

    if elapsed_time > 0.001:
        speed_kbs = (total_size / 1024) / elapsed_time
        speed_mbs = speed_kbs / 1024
        logger.info(f"总计用时: {elapsed_time:.2f} 秒")
        logger.info(f"平均速度: {speed_mbs:.2f} MB/s ({speed_kbs:.2f} KB/s)")

    if auto_reboot:
        # reboot() reports whether the command actually went out; announcing a
        # reboot that failed used to be unconditional.
        if burner.reboot():
            logger.info("设备已自动重启")
        else:
            logger.warning("自动重启失败，请手动给设备重新上电")

    return True


def write_images(addr_filename_pairs, burner):
    "写入单个 .img 文件"
    # 对每个固件文件进行写入操作
    for address, filename in addr_filename_pairs:
        if not filename.exists():
            raise FileNotFoundError(f"文件 {filename} 不存在")
        file_size = filename.stat().st_size
        if file_size == 0:
            raise ValueError(f"文件 {filename} 为空，无法烧录")
        logger.info(f"写入文件 {filename} 至地址 {hex(address)}，大小 {file_size} 字节")
        try:
            # Streamed rather than read() in full: a full-card .img is easily
            # multiple GB and there is no reason to hold it all in memory.
            with filename.open("rb") as f:
                burner.write_image_stream(f, file_size, address)
        except (ValueError, DataWriteError, USBCommunicationError) as e:
            # One wrapping layer, not two. This used to nest the same message
            # inside itself: "烧录文件 X 失败: 写入文件 X 失败: ...".
            raise RuntimeError(f"写入文件 {filename} (0x{address:X}) 失败: {e}") from e
