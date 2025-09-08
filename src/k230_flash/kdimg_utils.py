# kdimg_utils.py
from pathlib import Path

from loguru import logger

from .kdimage import KburnKdImage, get_kdimage_items, get_kdimage_max_offset


def write_kdimg(kdimg_path, burner, selected_partitions=None):
    """Write a single .kdimg file

    :param kdimg_path: Path to the .kdimg file
    :param burner: The burner instance
    :param selected_partitions: List of partition names to flash (if None, flash all)
    """

    # If the maximum offset address is greater than the device capacity, prompt the user
    max_offset = get_kdimage_max_offset(kdimg_path)
    logger.info(f"kdimage 最大偏移量: {max_offset // (1024*1024)} MB (0x{max_offset:08X})")
    if max_offset > burner.capacity:
        logger.error("kdimage file exceeds device capacity")
        return False

    kdimg = KburnKdImage.instance(kdimg_path)

    kdimg_items = get_kdimage_items(kdimg_path)
    if not kdimg_items:
        logger.error("Failed to parse `.kdimg` file")
        return False

    # Write in partition order
    for item in kdimg_items.data:
        # Skip partition if selected_partitions is specified and this partition is not in the list
        if selected_partitions and item.partName not in selected_partitions:
            logger.debug(f"Skipping partition {item.partName} (not in selected partitions)")
            continue

        logger.info(f"烧录分区: {item.partName} (0x{item.partOffset:08X}, {item.partSize // 1024} KB)")
        part_data = kdimg.read_part_data(item)
        partOffset = item.partOffset
        if not burner.write_image(part_data, partOffset):
            logger.error(f"Failed to write partition {item.partName}")
            return
