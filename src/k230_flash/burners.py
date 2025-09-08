# burners.py
import importlib.resources
import struct
import time
from pathlib import Path

import usb.core
import usb.util
from loguru import logger

from .kdimage import get_kdimage_items
from .kdimg_utils import write_kdimg
from .usb_utils import (
    EP0_GET_CPU_INFO,
    EP0_PROG_START,
    EP0_SET_DATA_ADDRESS,
    EP0_SET_DATA_LENGTH,
    KBURN_USB_DEV_BROM,
    KBURN_USB_DEV_INVALID,
    KBURN_USB_DEV_UBOOT,
    USB_TIMEOUT,
    list_usb_devices,
    refresh_pyusb_after_reboot,
)


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

REBOOT_MARK=0x52626F74


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
        "Dynamically update in/out endpoints"
        cfg = self.dev.get_active_configuration()
        for interface in cfg:
            for endpoint in interface:
                if endpoint.bEndpointAddress & 0x80:  # Check if IN endpoint
                    self.ep_in = endpoint.bEndpointAddress
                    logger.debug(f"Updated IN endpoint: {hex(self.ep_in)}")
                else:  # OUT endpoint
                    self.ep_out = endpoint.bEndpointAddress
                    logger.debug(f"Updated OUT endpoint: {hex(self.ep_out)}")

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def log_progress(self, current, total):
        if self.progress_callback:
            self.progress_callback(current, total)
        else:
            percent = (current / total * 100) if total else 0
            logger.info(f"Progress: {percent:.2f}% ({current}/{total})")

    def write(self, data, address):
        raise NotImplementedError(
            "The write method must be implemented in a derived class"
        )


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
                bmRequestType=usb.util.CTRL_OUT
                | usb.util.CTRL_TYPE_VENDOR
                | usb.util.CTRL_RECIPIENT_DEVICE,
                bRequest=EP0_PROG_START,
                wValue=addr_high,
                wIndex=addr_low,
                data_or_wLength=None,
                timeout=USB_TIMEOUT,
            )
            logger.debug(f"boot_from: return value {ret}")
        except usb.core.USBError as e:
            logger.error(f"boot_from failed: {e}")
            raise USBCommunicationError(
                f"启动Loader失败，地址: {hex(address)}, 错误: {e}"
            )

    def get_loader_path(self, filename):
        """Get the path of the bin file in the `loaders` directory"""
        return str(
            importlib.resources.files("k230_flash").joinpath("loaders", filename)
        )

    def get_loader(self, media_type="EMMC"):
        # Select different built-in loaders according to media_type
        loader_map = {
            "EMMC": "loader_mmc.bin",
            "SDCARD": "loader_mmc.bin",
            "SPI_NAND": "loader_spi_nand.bin",
            "SPI_NOR": "loader_spi_nor.bin",
        }

        media_type_upper = media_type.upper()
        if media_type_upper not in loader_map:
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
                bmRequestType=usb.util.CTRL_OUT
                | usb.util.CTRL_TYPE_VENDOR
                | usb.util.CTRL_RECIPIENT_DEVICE,
                bRequest=EP0_SET_DATA_ADDRESS,
                wValue=addr_high,
                wIndex=addr_low,
                data_or_wLength=None,
                timeout=USB_TIMEOUT,
            )
            logger.debug(f"set_data_address: return value {ret}")
        except usb.core.USBError as e:
            logger.error(f"set_data_address failed: {e}")
            raise USBCommunicationError(
                f"设置数据地址失败，地址: {hex(address)}, 错误: {e}"
            )

    def write_data_chunk(self, chunk):
        try:
            written = self.dev.write(self.ep_out, chunk, timeout=USB_TIMEOUT)
            if written != len(chunk):
                logger.error("write_data_chunk write length is insufficient")
                raise DataWriteError(
                    f"数据块写入长度不足，期望: {len(chunk)}, 实际: {written}"
                )
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

        self.chunk_size = None
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
        media_type_upper = media_type_str.upper()
        if media_type_upper not in media_map:
            raise ValueError(f"Unsupported media_type: {media_type_str}")
        self.media_type = media_map[media_type_upper]

    def reboot(self):
        """
        发送重启命令到设备
        使用 KBURN_CMD_REBOOT 命令实现真正的设备重启
        注意：重启命令比较特殊，设备可能在收到命令后立即重启，无法正常响应
        """
        logger.info("正在重启设备...")

        try:
            # 清除可能的错误状态
            self.kburn_nop()

            # Construct configuration data
            cfg_data = struct.pack("<Q", REBOOT_MARK)
            expected_info_size = 0
            response = self.send_cmd(
                KBURN_CMD_REBOOT, cfg_data, expected_response_length=expected_info_size
            )

            # 等待设备重启完成
            logger.info("等待设备重启完成...")
            do_sleep(2000)  # 等待2秒让设备完成重启过程

            return True

        except usb.core.USBError as e:
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
        logger.debug(
            "Sending NOP (KBURN_CMD_NONE) command to clear device error status"
        )

        # Read the last packet (ignore the return value)
        try:
            _ = self.dev.read(self.ep_in, PACKET_SIZE, timeout=1000)
        except usb.core.USBError:
            pass  # Ignore possible timeout errors

        # Send KBURN_CMD_NONE
        response = self.send_cmd(KBURN_CMD_NONE, b"", expected_response_length=16)

    def write_start(self, offset: int, size: int) -> bool:
        """Initialize write operation"""
        # Check alignment
        if offset % self.blk_sz != 0:
            logger.error("Address not aligned to erase size")
            raise ValueError(
                f"地址未对齐到擦除大小，偏移: {offset}, 块大小: {self.blk_sz}"
            )

        self.kburn_nop()  # Clear device error status

        # Construct configuration data
        part_flags = 0x00
        cfg_data = struct.pack("<QQQQ", offset, size, size, part_flags)
        expected_info_size = 8
        response = self.send_cmd(
            KBURN_CMD_WRITE_LBA, cfg_data, expected_response_length=expected_info_size
        )
        if response is None or len(response) != expected_info_size:
            logger.error(
                f"get_capacity: failed to get valid response, expected {expected_info_size} bytes, got {len(response) if response else None}"
            )
            raise DataWriteError(
                f"初始化写入操作失败，期望响应: {expected_info_size} 字节，实际: {len(response) if response else None}"
            )
        return True

    def write_chunks(self, data: bytes) -> bool:
        """Write data chunks"""
        try:
            total_size = len(data)
            bytes_sent = 0
            # Automatically handle ZLP
            chunk_size = self.out_chunk_size
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                self.dev.write(self.ep_out, chunk, timeout=1000)
                bytes_sent += len(chunk)
                self.log_progress(bytes_sent, total_size)

            # Send zero-length packet (if needed)
            if len(data) % chunk_size == 0:
                self.dev.write(self.ep_out, b"", timeout=1000)

            return True
        except usb.core.USBError as e:
            logger.error(f"Write chunk failed: {str(e)}")
            raise USBCommunicationError(f"数据块写入失败: {e}")

    def write_end(self) -> bool:
        """Complete write operation"""

        return True

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

    def write(self, data, address):
        # In U-Boot mode, write firmware data in chunks via Bulk transfer
        CHUNK_SIZE = 512
        total_size = len(data)
        logger.info(f"开始写入 {total_size} 字节数据到地址 {hex(address)}")
        bytes_sent = 0
        while bytes_sent < total_size:
            chunk = data[bytes_sent : bytes_sent + CHUNK_SIZE]
            try:
                written = self.dev.write(self.ep_out, chunk, timeout=USB_TIMEOUT)
                if written != len(chunk):
                    logger.error(
                        "Insufficient data block length written in U-Boot mode"
                    )
                    raise DataWriteError(
                        f"U-Boot模式下数据块写入长度不足，期望: {len(chunk)}, 实际: {written}"
                    )
            except usb.core.USBError as e:
                logger.error(f"Bulk write error: {e}")
                raise USBCommunicationError(f"批量写入错误: {e}")
            except Exception as e:
                logger.critical(e)
                raise DataWriteError(f"写入时发生未知错误: {e}")
            bytes_sent += len(chunk)
            self.log_progress(bytes_sent, total_size)
        logger.info("数据写入完成")
        # Here you can add steps to send the write end command and read the response
        return True

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
            self.dev.write(self.ep_out, packet, timeout=1000)
        except Exception as e:
            logger.error(f"send_cmd: write failed: {e}")
            raise USBCommunicationError(f"USB命令写入失败: {e}")

        if expected_response_length == 0:
            return None

        try:
            # Read 60-byte response from the read endpoint
            response = self.dev.read(self.ep_in, PACKET_SIZE, timeout=1000)
        except Exception as e:
            logger.error(f"send_cmd: read failed: {e}")
            raise USBCommunicationError(f"USB命令响应读取失败: {e}")

        if len(response) < HEADER_SIZE:
            logger.error(f"send_cmd: response too short ({len(response)} bytes)")
            raise USBCommunicationError(f"响应数据太短: {len(response)} 字节")

        # Parse response header: return value result, data area length data_size
        resp_cmd, resp_result, resp_data_size = struct.unpack(
            "<HHH", bytes(response[:HEADER_SIZE])
        )
        # Check if the response command is correct: should be (cmd | CMD_FLAG_DEV_TO_HOST)
        if resp_cmd != (cmd | CMD_FLAG_DEV_TO_HOST):
            logger.error(
                f"send_cmd: response cmd mismatch: got 0x{resp_cmd:04x}, expected 0x{(cmd | CMD_FLAG_DEV_TO_HOST)}"
            )
            raise USBCommunicationError(
                f"响应命令不匹配: 得到 0x{resp_cmd:04x}, 期望 0x{(cmd | CMD_FLAG_DEV_TO_HOST):04x}"
            )
        if resp_result != KBURN_RESULT_OK and cmd != KBURN_CMD_NONE:
            logger.error(f"send_cmd: response error, result = 0x{resp_result:04X}")
            raise USBCommunicationError(
                f"设备响应错误: 0x{resp_result:04X}, 请检查目标存储介质是否存在？"
            )
        if resp_data_size != expected_response_length:
            logger.error(
                f"send_cmd: response data size mismatch, expected {expected_response_length}, got {resp_data_size}"
            )
            raise USBCommunicationError(
                f"响应数据长度不匹配: 期望 {expected_response_length}, 实际 {resp_data_size}"
            )

        # Return the data area
        mid = response[HEADER_SIZE : HEADER_SIZE + resp_data_size]
        payload = bytes(mid)
        return mid

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

        response = self.send_cmd(
            KBURN_CMD_DEV_PROBE, payload, expected_response_length=16
        )
        if response is None or len(response) != 16:
            logger.error("probe: failed to get valid response")
            raise DeviceProbeError(
                f"设备探测失败，期望响应: 16 字节，实际: {len(response) if response else None}"
            )

        # Parse the 16-byte response into two uint64_t, little-endian
        out_chunk_size, in_chunk_size = struct.unpack("<QQ", response)
        logger.debug(
            f"probe: out_chunk_size = {out_chunk_size}, in_chunk_size = {in_chunk_size}"
        )
        self.out_chunk_size = out_chunk_size
        self.in_chunk_size = in_chunk_size

    def get_capacity(self):
        """
        Use the KBURN_CMD_DEV_GET_INFO command to get device media information.
        Assume that the medium info structure returned by the device uses the following packing format (1-byte alignment):
            - capacity : uint64_t (8 bytes)
            - blk_sz   : uint32_t (4 bytes)
            - erase_size: uint32_t (4 bytes)
            - wp       : uint8_t  (1 byte)
        Total 17 bytes.
        Returns the capacity value, or raises exception on failure.
        """
        expected_info_size = 32  # According to the packing format "<QII B"
        try:
            response = self.send_cmd(
                KBURN_CMD_DEV_GET_INFO, b"", expected_response_length=expected_info_size
            )
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

        logger.info(
            f"设备信息: 容量 {capacity // (1024*1024)} MB, 块大小 {blk_sz}, 擦除大小 {erase_size}"
        )
        self.capacity = capacity
        self.blk_sz = blk_sz
        self.erase_size = erase_size
        self.wp = wp
        self.device_type = type_val

        return capacity


def handle_bootrom_mode(
    dev, media_type, loader_address, loader_file, progress_callback
):
    """处理 BootROM 模式，下载 loader 并启动至 U-Boot"""
    try:
        burner = K230BROMBurner(dev)
        # burner.set_progress_callback(progress_callback)   # bootrom无需进度回调

        # 读取 loader
        loader_data = None
        if loader_file:
            try:
                with open(loader_file, "rb") as f:
                    loader_data = f.read()
                logger.info(f"使用自定义 loader: {loader_file}")
            except Exception as e:
                raise FileNotFoundError(f"读取 loader 文件失败: {e}")
        else:
            loader_data = burner.get_loader(media_type)
            if loader_data is None:
                raise RuntimeError("获取内置 loader 失败")

        # 写入并启动 loader
        try:
            burner.write(loader_data, loader_address)
            burner.boot_from(loader_address)
        except (USBCommunicationError, DataWriteError) as e:
            raise RuntimeError(f"Loader操作失败: {e}")

        logger.info("loader 写入成功，等待设备切换至 U-Boot 模式")
        time.sleep(1)
    except FileNotFoundError as e:
        logger.error(f"文件错误: {e}")
        raise
    except usb.core.USBError as e:
        logger.error(f"USB 设备通信错误: {e}")
        raise
    except RuntimeError as e:
        logger.error(f"运行时错误: {e}")
        raise
    except Exception as e:
        logger.error(f"未知错误: {e}")
        raise


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
    except DeviceProbeError as e:
        raise RuntimeError(f"U-Boot 模式探测失败: {e}")

    try:
        burner.get_capacity()
    except DeviceProbeError as e:
        raise RuntimeError(f"获取设备容量信息失败: {e}")

    # --- 新增：计算总大小并记录开始时间 ---
    total_size = 0
    if kdimg_path:
        items = get_kdimage_items(kdimg_path)
        if not items:
            raise RuntimeError(f"无法解析 kdimg 文件: {kdimg_path}")

        if selected_partitions:
            # Only count selected partitions
            total_size = sum(
                item.partSize
                for item in items.data
                if item.partName in selected_partitions
            )
        else:
            # Count all partitions
            total_size = sum(item.partSize for item in items.data)
    elif addr_filename_pairs:
        total_size = sum(file.stat().st_size for _, file in addr_filename_pairs)

    logger.info(f"准备烧录，总大小: {total_size / 1024 / 1024:.2f} MB")
    start_time = time.time()
    # --- 结束新增部分 ---

    # 执行烧录
    if kdimg_path and selected_partitions:
        if not kdimg_path.exists():
            raise FileNotFoundError(f"KDIMG 文件 {kdimg_path} 不存在")

        logger.info(f"模式 3: 选择性烧录 kdimg 文件: {kdimg_path}")
        logger.info(f"  - 选中的分区: {', '.join(selected_partitions)}")
        write_kdimg(kdimg_path, burner, selected_partitions=selected_partitions)

    elif kdimg_path and not addr_filename_pairs:
        if not kdimg_path.exists():
            raise FileNotFoundError(f"KDIMG 文件 {kdimg_path} 不存在")

        logger.info(f"模式 2: 烧录 kdimg 文件: {kdimg_path}")
        write_kdimg(kdimg_path, burner)

    else:
        logger.info("模式 1: 烧录 image 文件列表")
        for addr, file in addr_filename_pairs:
            if not file.exists():
                raise FileNotFoundError(f"文件 {file} 不存在")
            logger.info(f"  - 烧录地址: 0x{addr:08X}, 文件: {file}")
        write_images(addr_filename_pairs, burner)

    # --- 新增：计算并打印速度 ---
    end_time = time.time()
    elapsed_time = end_time - start_time

    logger.info("固件写入完成")

    if elapsed_time > 0.001:
        speed_kbs = (total_size / 1024) / elapsed_time
        speed_mbs = speed_kbs / 1024
        logger.info(f"总计用时: {elapsed_time:.2f} 秒")
        logger.info(f"平均速度: {speed_mbs:.2f} MB/s ({speed_kbs:.2f} KB/s)")
    # --- 结束新增部分 ---

    if auto_reboot:
        burner.reboot()
        logger.info("设备已自动重启")

    return True


def write_images(addr_filename_pairs, burner):
    "写入单个 .img 文件"
    # 对每个固件文件进行写入操作
    for address, filename in addr_filename_pairs:
        try:
            if not filename.exists():
                raise FileNotFoundError(f"文件 {filename} 不存在")
            with filename.open("rb") as f:
                file_data = f.read()
            logger.info(
                f"写入文件 {filename} 至地址 {hex(address)}，大小 {len(file_data)} 字节"
            )
            try:
                burner.write_image(file_data, address)
            except (ValueError, DataWriteError, USBCommunicationError) as e:
                raise RuntimeError(f"写入文件 {filename} 失败: {e}")
        except Exception as e:
            raise RuntimeError(f"烧录文件 {filename} 失败: {e}")
