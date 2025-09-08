#!/usr/bin/env python3
import hashlib
import struct
import zlib
from pathlib import Path

from loguru import logger

# Define constants to be consistent with the C++ version
KDIMG_HADER_MAGIC = 0x27CB8F93
KDIMG_PART_MAGIC = 0x91DF6DA4

# Header structure: 6 uint32, 32 bytes image_info, 32 bytes chip_info, 64 bytes board_info
HEADER_FORMAT = "<6I32s32s64s"
HEADER_SIZE = 512

# Each part occupies 256 bytes
PART_STRUCT_SIZE = 256
# V1 partition format (part_flag is uint32_t)
PART_FORMAT_V1 = "<8I32s32s"
# V2 partition format (part_flag is uint64_t, with padding)
PART_FORMAT_V2 = "<5I4xQII32s32s"


# Define the image item class to save the metadata of each part
class KburnImageItem:
    def __init__(
        self,
        partName,
        partOffset,
        partSize,
        partEraseSize,
        partContentOffset,
        partContentSize,
        expectedSha256,
    ):
        self.partName = partName  # Partition name
        self.partOffset = partOffset  # Partition start offset (logical position in kdimage)
        self.partSize = partSize  # Expected partition size (usually part_max_size)
        self.partEraseSize = partEraseSize  # Partition erase size
        self.partContentOffset = partContentOffset  # Start offset of partition data in kdimage
        self.partContentSize = partContentSize  # Actual data size of the partition
        self.expectedSha256 = expectedSha256  # Expected SHA-256 value represented by a hex string

    def __lt__(self, other):
        return self.partOffset < other.partOffset


# Define the item list class
class KburnImageItemList:
    def __init__(self):
        self.data = []

    def push(self, item):
        self.data.append(item)

    def size(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def sort(self):
        self.data.sort()

    def clear(self):
        self.data.clear()


# KburnKdImage class: responsible for parsing the kdimage file and saving the metadata of each part
# Singleton mode is used here to ensure that there is only one instance globally (for easy management and caching of parsing results)
class KburnKdImage:
    _instance = None

    @classmethod
    def instance(cls, image_path=None):
        if cls._instance is None:
            if image_path is None:
                raise ValueError("image_path must be provided when creating an instance for the first time")
            cls._instance = cls(Path(image_path))  # Pass in the Path object
        return cls._instance

    @classmethod
    def deleteInstance(cls):
        cls._instance = None

    def __init__(self, image_path):
        self._image_path = image_path.resolve()  # Normalize the path
        self._image_file = None
        self._header = None
        self._curr_parts = []  # Save the parsed part data (list of dictionaries)
        self._items = KburnImageItemList()

    def open(self):
        try:
            self._image_file = self._image_path.open("rb")
        except Exception as e:
            logger.error(f"Failed to open image file {self._image_path}: {e}")
            return False
        return True

    def close(self):
        if self._image_file:
            self._image_file.close()
            self._image_file = None

    def parse_parts(self):
        if not self._image_file and not self.open():
            return False

        self._image_file.seek(0)
        header_data = self._image_file.read(HEADER_SIZE)
        if len(header_data) < HEADER_SIZE:
            logger.error("Failed to read the full header")
            return False

        header_unpacked = struct.unpack(HEADER_FORMAT, header_data[: struct.calcsize(HEADER_FORMAT)])
        hdr = {
            "img_hdr_magic": header_unpacked[0],
            "img_hdr_crc32": header_unpacked[1],
            "img_hdr_flag": header_unpacked[2],
            "img_hdr_version": header_unpacked[3],
            "part_tbl_num": header_unpacked[4],
            "part_tbl_crc32": header_unpacked[5],
            "image_info": header_unpacked[6].rstrip(b"\x00").decode("utf-8", errors="ignore"),
            "chip_info": header_unpacked[7].rstrip(b"\x00").decode("utf-8", errors="ignore"),
            "board_info": header_unpacked[8].rstrip(b"\x00").decode("utf-8", errors="ignore"),
        }
        self._header = hdr

        if hdr["img_hdr_magic"] != KDIMG_HADER_MAGIC:
            logger.error(
                "Invalid image header magic! Expected 0x%08X, got 0x%08X",
                KDIMG_HADER_MAGIC,
                hdr["img_hdr_magic"],
            )
            return False

        # Verify the CRC32 of the header: first set the CRC32 field to 0
        header_bytes = bytearray(header_data)
        header_bytes[4:8] = b"\x00\x00\x00\x00"
        calc_crc32 = zlib.crc32(header_bytes) & 0xFFFFFFFF
        if calc_crc32 != hdr["img_hdr_crc32"]:
            logger.error(
                "Invalid header CRC32! Expected 0x%08X, got 0x%08X",
                hdr["img_hdr_crc32"],
                calc_crc32,
            )
            return False

        # Select the partition table format according to the header version
        if self._header["img_hdr_version"] >= 2:
            logger.debug("使用 V2 分区表格式")
            part_format = PART_FORMAT_V2
        else:
            logger.debug("使用 V1 分区表格式")
            part_format = PART_FORMAT_V1
        part_format_size = struct.calcsize(part_format)

        # Read part table
        num_parts = hdr["part_tbl_num"]
        part_table_size = num_parts * PART_STRUCT_SIZE
        part_table_data = self._image_file.read(part_table_size)
        if len(part_table_data) < part_table_size:
            logger.error("Failed to read the complete part table")
            return False

        calc_part_tbl_crc32 = zlib.crc32(part_table_data) & 0xFFFFFFFF
        if calc_part_tbl_crc32 != hdr["part_tbl_crc32"]:
            logger.error(
                "Invalid part table CRC32! Expected 0x%08X, got 0x%08X",
                hdr["part_tbl_crc32"],
                calc_part_tbl_crc32,
            )
            return False

        self._curr_parts.clear()
        for i in range(num_parts):
            offset = i * PART_STRUCT_SIZE
            part_data = part_table_data[offset : offset + PART_STRUCT_SIZE]
            if len(part_data) < part_format_size:
                logger.error("Insufficient part data, part %d", i)
                return False

            unpacked = struct.unpack(part_format, part_data[:part_format_size])

            # Uniformly map to a dictionary, Python's integer type can automatically handle uint32 and uint64
            part = {
                "part_magic": unpacked[0],
                "part_offset": unpacked[1],
                "part_size": unpacked[2],
                "part_erase_size": unpacked[3],
                "part_max_size": unpacked[4],
                "part_flag": unpacked[5],
                "part_content_offset": unpacked[6],
                "part_content_size": unpacked[7],
                "part_content_sha256": unpacked[8],  # 32 bytes
                "part_name": unpacked[9].rstrip(b"\x00").decode("utf-8", errors="ignore"),
            }

            if part["part_magic"] != KDIMG_PART_MAGIC:
                logger.error("Invalid magic for part %d", i)
                return False
            self._curr_parts.append(part)
        return True

    def build_items(self):
        self._items.clear()
        for part in self._curr_parts:
            item = KburnImageItem(
                partName=part["part_name"],
                partOffset=part["part_offset"],
                partSize=part["part_size"],
                partEraseSize=part["part_erase_size"],
                partContentOffset=part["part_content_offset"],
                partContentSize=part["part_content_size"],
                expectedSha256=part["part_content_sha256"].hex(),
            )
            self._items.push(item)
        self._items.sort()
        return True

    def convert(self):
        if not self.parse_parts():
            logger.error("Failed to parse kdimage part table")
            return False
        if not self.build_items():
            logger.error("Failed to construct items")
            return False
        return True

    def items(self):
        # Close the file after parsing and constructing the item list, and return the metadata list
        self.close()
        if not self.open():
            return None
        if not self.convert():
            self.close()
            return None
        self.close()
        return self._items

    def max_offset(self):
        max_off = 0
        for part in self._curr_parts:
            curr = part["part_offset"] + part["part_max_size"]
            if curr > max_off:
                max_off = curr
        return max_off

    def read_part_data(self, item):
        """
        Directly read partition data from the original kdimage file according to the item information.
        First verify the original data, and then supplement with 0xFF as needed.
        """
        try:
            with self._image_path.open("rb") as f:
                # 1. Read original data
                f.seek(item.partContentOffset)
                data = f.read(item.partContentSize)
                if len(data) != item.partContentSize:
                    raise ValueError(f"Insufficient data read: Expected {item.partContentSize}, got {len(data)}")

                # 2. Perform SHA256 verification on the original data
                sha256_calculated = hashlib.sha256(data).hexdigest()

                # --- Added debug log ---
                logger.debug(f"Part: {item.partName}")
                logger.debug(f"Calculated SHA256: {sha256_calculated}")
                logger.debug(f"Expected SHA256:   {item.expectedSha256}")
                # --- End of debug log ---

                if sha256_calculated != item.expectedSha256:
                    raise ValueError(
                        f"SHA256 verification failed for part {item.partName}. "
                        f"Calculated value: {sha256_calculated}, Expected value: {item.expectedSha256}"
                    )

                # 3. After successful verification, perform data padding
                if item.partContentSize < item.partSize:
                    padding_size = item.partSize - item.partContentSize
                    data += b"\xff" * padding_size

                # 4. Return the final data
                return data
        except Exception as e:
            logger.error("Failed to read partition %s data: %s", item.partName, e)
            return None


# External interface
def get_kdimage_items(image_path: Path):
    return KburnKdImage.instance(image_path).items()


def get_kdimage_max_offset(image_path: Path):
    kdimg = KburnKdImage.instance(image_path)
    if not kdimg.open():
        return 0
    if not kdimg.parse_parts():
        kdimg.close()
        return 0
    max_off = kdimg.max_offset()
    kdimg.close()
    return max_off


# ----------------------------
# Test code
# ----------------------------
if __name__ == "__main__":
    import argparse
    import sys

    logger.remove()
    logger.add(sys.stderr, level="DEBUG")

    test_file = Path(
        "C:/data/wechat/WeChat Files/huangzhenming847866/FileStorage/File/2025-07/k230_xwy01_rtsmart_local_nncase_v2.9.0(4).kdimg"
    )

    logger.info(f"Start parsing kdimage file: {test_file}")
    items = get_kdimage_items(test_file)
    if items is None or items.size() == 0:
        logger.error("No part information was parsed.")
    else:
        logger.info("Parsed %d parts:", items.size())
        for item in items.data:
            logger.info(
                f"Part Name: {item.partName}, Offset: 0x{item.partOffset:08X}, Size: 0x{item.partSize:X}, ContentOffset: 0x{item.partContentOffset:08X}, ContentSize: 0x{item.partContentSize:X}"
            )
        max_offset = get_kdimage_max_offset(test_file)
        logger.info(
            f"kdimage maximum offset: 0x{max_offset}08X",
        )

        # Test reading the data of the first part
        kdimg = KburnKdImage.instance(test_file)
        first_item = items.data[2]
        data = kdimg.read_part_data(first_item)
        if data is not None:
            logger.info(f"Successfully read part {first_item.partName} data, data length: {len(data)} bytes")
        else:
            logger.error("Failed to read part data")
