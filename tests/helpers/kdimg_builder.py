"""Build .kdimg containers in memory for tests.

The suite used to ask for hand-supplied sample files and skipped itself when
they were missing, which meant the parser was effectively untested. Generating
the images here instead makes the tests deterministic, keeps binaries out of the
repo, and lets each test assert exact offsets and sizes because it knows exactly
what it built.

Layout follows src/k230_flash/kdimage.md: a 512-byte header, a partition table of
256 bytes per entry, then the partition payloads.
"""

import hashlib
import struct
import zlib

KDIMG_HEADER_MAGIC = 0x27CB8F93
KDIMG_PART_MAGIC = 0x91DF6DA4

HEADER_FORMAT = "<6I32s32s64s"
HEADER_SIZE = 512
PART_STRUCT_SIZE = 256
PART_FORMAT_V1 = "<8I32s32s"
PART_FORMAT_V2 = "<5I4xQII32s32s"


class Partition:
    """One partition to place in the image.

    `size` is the on-media size the parser reports (`part_size`). When it is
    larger than the payload the reader pads with 0xFF up to it, so passing a
    `size` bigger than `data` is how a test exercises that padding.
    """

    def __init__(self, name, offset, data, size=None, erase_size=4096, max_size=None, flag=0):
        self.name = name
        self.offset = offset
        self.data = data
        self.size = size if size is not None else len(data)
        self.erase_size = erase_size
        self.max_size = max_size if max_size is not None else self.size
        self.flag = flag


def _pack_partition(part, content_offset, version, sha_override=None):
    sha = sha_override if sha_override is not None else hashlib.sha256(part.data).digest()
    name = part.name.encode()[:32].ljust(32, b"\x00")

    if version >= 2:
        raw = struct.pack(
            PART_FORMAT_V2,
            KDIMG_PART_MAGIC,
            part.offset,
            part.size,
            part.erase_size,
            part.max_size,
            part.flag,
            content_offset,
            len(part.data),
            sha,
            name,
        )
    else:
        raw = struct.pack(
            PART_FORMAT_V1,
            KDIMG_PART_MAGIC,
            part.offset,
            part.size,
            part.erase_size,
            part.max_size,
            part.flag,
            content_offset,
            len(part.data),
            sha,
            name,
        )
    return raw.ljust(PART_STRUCT_SIZE, b"\x00")


def build_kdimg(
    partitions,
    version=2,
    *,
    header_magic=KDIMG_HEADER_MAGIC,
    corrupt_header_crc=False,
    corrupt_table_crc=False,
    corrupt_sha_of=None,
    image_info=b"test-image",
    chip_info=b"K230",
    board_info=b"unit-test",
):
    """Return the bytes of a .kdimg holding `partitions`.

    The keyword flags each break exactly one integrity field, so a test can show
    that the parser rejects that specific corruption and nothing else:
      header_magic       -- wrong magic in the header
      corrupt_header_crc -- header CRC32 that does not match the header
      corrupt_table_crc  -- partition-table CRC32 that does not match the table
      corrupt_sha_of     -- partition name whose recorded SHA-256 is wrong
    """
    table_size = len(partitions) * PART_STRUCT_SIZE
    content_cursor = HEADER_SIZE + table_size

    table = b""
    payload = b""
    for part in partitions:
        bad_sha = b"\x00" * 32 if corrupt_sha_of == part.name else None
        table += _pack_partition(part, content_cursor, version, sha_override=bad_sha)
        payload += part.data
        content_cursor += len(part.data)

    table_crc = zlib.crc32(table) & 0xFFFFFFFF
    if corrupt_table_crc:
        table_crc ^= 0xFFFFFFFF

    header = struct.pack(
        HEADER_FORMAT,
        header_magic,
        0,  # CRC placeholder, filled in below
        0,  # flags
        version,
        len(partitions),
        table_crc,
        image_info[:32].ljust(32, b"\x00"),
        chip_info[:32].ljust(32, b"\x00"),
        board_info[:64].ljust(64, b"\x00"),
    ).ljust(HEADER_SIZE, b"\x00")

    # The parser zeroes the CRC field before hashing, so compute it the same way.
    header_crc = zlib.crc32(header) & 0xFFFFFFFF
    if corrupt_header_crc:
        header_crc ^= 0xFFFFFFFF
    header = header[:4] + struct.pack("<I", header_crc) + header[8:]

    return header + table + payload


def write_kdimg_file(path, partitions, version=2, **kwargs):
    """Build an image and write it to `path`, returning the path."""
    path.write_bytes(build_kdimg(partitions, version=version, **kwargs))
    return path
