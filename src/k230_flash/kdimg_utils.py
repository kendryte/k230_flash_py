# kdimg_utils.py
from loguru import logger

from .kdimage import KburnKdImage


def write_kdimg(kdimg_path, burner, selected_partitions=None):
    """Write a single .kdimg file

    :param kdimg_path: Path to the .kdimg file
    :param burner: The burner instance
    :param selected_partitions: List of partition names to flash (if None, flash all)
    """

    # These used to `return False`/`return` on failure while the caller ignored the
    # return value, so a rejected image or an unwritten partition was reported to
    # the user as a successful flash. They raise now.
    kdimg = KburnKdImage(kdimg_path)
    kdimg_items = kdimg.items()
    if not kdimg_items:
        raise ValueError(f"无法解析 kdimg 文件: {kdimg_path}")

    max_offset = kdimg.max_offset()
    logger.info(f"kdimage 最大偏移量: {max_offset // (1024*1024)} MB (0x{max_offset:08X})")
    if max_offset > burner.capacity:
        raise ValueError(
            f"kdimg 超出设备容量: 需要 {max_offset // (1024*1024)} MB, " f"设备容量 {burner.capacity // (1024*1024)} MB"
        )

    # Validate the selection *before* writing anything. This check used to run
    # after the write loop, so `--kdimg-select uboot_a typo` would flash uboot_a
    # and only then report that `typo` does not exist -- leaving the board in a
    # half-updated state that the error message gave no hint about.
    available = {item.partName for item in kdimg_items.data}
    if selected_partitions:
        missing = set(selected_partitions) - available
        if missing:
            raise ValueError(f"kdimg 中不存在指定的分区: {', '.join(sorted(missing))}")
        targets = [item for item in kdimg_items.data if item.partName in selected_partitions]
    else:
        targets = list(kdimg_items.data)

    if not targets:
        raise ValueError("没有任何分区被烧录")

    # The max_offset check above uses the *declared* layout (part_max_size). What
    # actually goes to the device is writeSize = max(partContentSize, partSize),
    # which can exceed part_max_size for a malformed image. Without this second
    # pass the per-write guard in write_start() would only trip partway through,
    # after earlier partitions had already been committed to the medium.
    for item in targets:
        end = item.partOffset + item.writeSize
        if end > burner.capacity:
            raise ValueError(
                f"分区 {item.partName} 超出设备容量: 0x{item.partOffset:08X} + {item.writeSize} 字节 "
                f"= {end} 字节, 设备容量 {burner.capacity} 字节"
            )

    # Write in partition order
    for item in targets:
        logger.info(f"烧录分区: {item.partName} (0x{item.partOffset:08X}, {item.partSize // 1024} KB)")
        # Verify first, then stream. Verifying up front means a corrupt payload
        # is rejected before a single byte reaches the medium; streaming means
        # peak memory is one chunk rather than the whole (padded) partition,
        # which for a multi-GB rootfs used to be twice its size on the heap.
        kdimg.verify_part_sha256(item)
        with kdimg.open_part_stream(item) as stream:
            burner.write_image_stream(stream, item.writeSize, item.partOffset)

    return True
