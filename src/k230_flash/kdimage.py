#!/usr/bin/env python3
"""Parsing and validation of the ``.kdimg`` container format.

The format itself (header, partition table, per-partition payloads and their
checksums) is documented in ``kdimage.md``; this module only implements it.

Partition payloads are handed to callers as *streams* rather than as bytes.
A full-card rootfs partition is easily multiple GB, and materialising it --
plus its 0xFF padding -- would put twice its size on the heap for no reason.
"""

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

# A sane upper bound on the partition count. The field is a uint32, so a
# corrupt header can ask us to read 4 billion * 256 bytes; without this the
# read() below tries to allocate a terabyte before the CRC ever gets a chance
# to reject the image.
MAX_PART_TBL_NUM = 512

# How much to move per read when streaming a payload off disk.
STREAM_CHUNK_SIZE = 1024 * 1024


class KdimageError(ValueError):
    """Raised when a .kdimg file cannot be parsed or fails verification.

    Subclasses ValueError because that is what the write path already raised
    for a rejected image, so existing `except ValueError` callers keep working
    while gaining an explicit reason instead of a bare None.
    """


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

    @property
    def writeSize(self):
        """Number of bytes actually handed to the device for this partition.

        Normally partSize, with the payload padded out to it using 0xFF. A
        payload larger than the declared size is written in full rather than
        silently truncated.
        """
        return max(self.partContentSize, self.partSize)

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


class _PaddedPartitionStream:
    """Read-only file-like view of one partition: payload then 0xFF padding.

    Exposes just enough of the file protocol for ``write_image_stream`` --
    ``read(n)`` plus the context-manager methods -- so a partition can be fed
    to the device a chunk at a time instead of being assembled in memory.
    """

    def __init__(self, image_path, content_offset, content_size, total_size):
        self._file = image_path.open("rb")
        self._file.seek(content_offset)
        self._content_size = content_size
        self._total_size = total_size
        self._pos = 0

    def read(self, size=-1):
        remaining = self._total_size - self._pos
        if size is None or size < 0:
            size = remaining
        size = min(size, remaining)
        if size <= 0:
            return b""

        out = b""
        # Payload portion.
        if self._pos < self._content_size:
            want = min(size, self._content_size - self._pos)
            out = self._file.read(want)
            if len(out) != want:
                raise KdimageError(f"分区数据提前结束: 期望 {want} 字节, 实际 {len(out)}")
            self._pos += len(out)
            size -= len(out)

        # Padding portion, generated rather than stored.
        if size > 0:
            out += b"\xff" * size
            self._pos += size

        return out

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# KburnKdImage: parses a .kdimg file and holds the metadata of each part.
#
# This deliberately is NOT a singleton. It used to be, keyed on nothing at all,
# so `instance(a)` followed by `instance(b)` handed back a's parse of a's file --
# meaning the GUI's partition list and, worse, a batch flash of several images
# in one process silently operated on whichever image happened to be opened
# first. Parsing is cheap; construct one per file.
class KburnKdImage:
    def __init__(self, image_path):
        self._image_path = Path(image_path).resolve()  # Normalize the path
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
            logger.error(f"Failed to read the full header: got {len(header_data)} of {HEADER_SIZE} bytes")
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
                f"Invalid image header magic! Expected 0x{KDIMG_HADER_MAGIC:08X}, " f"got 0x{hdr['img_hdr_magic']:08X}"
            )
            return False

        # Verify the CRC32 of the header: first set the CRC32 field to 0
        header_bytes = bytearray(header_data)
        header_bytes[4:8] = b"\x00\x00\x00\x00"
        calc_crc32 = zlib.crc32(header_bytes) & 0xFFFFFFFF
        if calc_crc32 != hdr["img_hdr_crc32"]:
            logger.error(f"Invalid header CRC32! Expected 0x{hdr['img_hdr_crc32']:08X}, got 0x{calc_crc32:08X}")
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
        if num_parts > MAX_PART_TBL_NUM:
            logger.error(f"Implausible partition count {num_parts} (max {MAX_PART_TBL_NUM}); refusing to read table")
            return False
        part_table_size = num_parts * PART_STRUCT_SIZE
        part_table_data = self._image_file.read(part_table_size)
        if len(part_table_data) < part_table_size:
            logger.error(
                f"Failed to read the complete part table: got {len(part_table_data)} of {part_table_size} bytes"
            )
            return False

        calc_part_tbl_crc32 = zlib.crc32(part_table_data) & 0xFFFFFFFF
        if calc_part_tbl_crc32 != hdr["part_tbl_crc32"]:
            logger.error(
                f"Invalid part table CRC32! Expected 0x{hdr['part_tbl_crc32']:08X}, got 0x{calc_part_tbl_crc32:08X}"
            )
            return False

        self._curr_parts.clear()
        for i in range(num_parts):
            offset = i * PART_STRUCT_SIZE
            part_data = part_table_data[offset : offset + PART_STRUCT_SIZE]
            if len(part_data) < part_format_size:
                logger.error(f"Insufficient part data, part {i}")
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
                logger.error(f"Invalid magic for part {i}: 0x{part['part_magic']:08X}")
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

    def verify_part_sha256(self, item):
        """Check a partition's payload against its recorded digest.

        Done as a separate streaming pass *before* any bytes go to the device:
        a partition that fails verification must never be partially written,
        and hashing while writing would do exactly that. The extra read is off
        the page cache and costs nothing next to the USB transfer.
        """
        digest = hashlib.sha256()
        read = 0
        with self._image_path.open("rb") as f:
            f.seek(item.partContentOffset)
            while read < item.partContentSize:
                chunk = f.read(min(STREAM_CHUNK_SIZE, item.partContentSize - read))
                if not chunk:
                    break
                digest.update(chunk)
                read += len(chunk)

        if read != item.partContentSize:
            raise KdimageError(f"分区 {item.partName} 数据不完整: 期望 {item.partContentSize} 字节, 实际 {read}")

        calculated = digest.hexdigest()
        logger.debug(f"Part: {item.partName}")
        logger.debug(f"Calculated SHA256: {calculated}")
        logger.debug(f"Expected SHA256:   {item.expectedSha256}")

        if calculated != item.expectedSha256:
            raise KdimageError(
                f"分区 {item.partName} SHA256 校验失败。" f"计算值: {calculated}, 期望值: {item.expectedSha256}"
            )

    def open_part_stream(self, item):
        """Return a file-like yielding the partition payload padded to size.

        The caller is responsible for closing it; it is also a context manager.
        Verify with verify_part_sha256() first -- this does no checking.
        """
        return _PaddedPartitionStream(
            self._image_path,
            item.partContentOffset,
            item.partContentSize,
            item.writeSize,
        )

    def read_part_data(self, item):
        """Verify and return a partition's full padded contents as bytes.

        Kept for callers that genuinely want the bytes; the write path streams
        instead (see open_part_stream). Raises KdimageError rather than
        returning None, so the reason for a failure is not thrown away.
        """
        self.verify_part_sha256(item)
        with self.open_part_stream(item) as stream:
            return stream.read()


# External interface
def get_kdimage_items(image_path: Path):
    return KburnKdImage(image_path).items()


def get_kdimage_max_offset(image_path: Path):
    kdimg = KburnKdImage(image_path)
    if not kdimg.open():
        return 0
    if not kdimg.parse_parts():
        kdimg.close()
        return 0
    max_off = kdimg.max_offset()
    kdimg.close()
    return max_off
