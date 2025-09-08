"""
Test the kdimage.py parser

Instructions:
1. Put your test .kdimg file into the `sample_files` folder.
   - A correct V1 version file, renamed to `v1_correct.kdimg`
   - A correct V2 version file, renamed to `v2_correct.kdimg`
   - A file with an incorrect header magic number, renamed to `corrupt_magic.kdimg`
   - A file with tampered partition data (SHA256 mismatch), renamed to `corrupt_sha.kdimg`

2. According to the actual partition information of your `v2_correct.kdimg` file,
   modify the `assert` assertion in the `test_parse_valid_v2_kdimage` function.

3. To run the test: execute the `pytest src/k230_flash/tests` command in the project root directory (`k230-flash/`).
"""

import sys
from pathlib import Path

import pytest

# Add the src directory to sys.path to resolve ModuleNotFoundError
src_path = str(Path(__file__).parent.parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Since the test file is inside a package, it can be imported directly
from k230_flash.kdimage import KburnKdImage, get_kdimage_items


@pytest.fixture
def sample_files_dir():
    """Return the directory path where the sample files are stored"""
    return Path(__file__).parent / "sample_files"


def test_parse_valid_v2_kdimage(sample_files_dir):
    """Test whether a correctly structured V2 version kdimage file can be successfully parsed"""
    v2_file = sample_files_dir / "v2_correct.kdimg"
    if not v2_file.exists():
        pytest.skip(f"Sample file does not exist: {v2_file}")

    # Clean up the singleton before each test to ensure independence
    KburnKdImage.deleteInstance()
    items = get_kdimage_items(v2_file)

    assert items is not None
    assert items.size() > 0

    # --- Please modify the following assertions according to the actual situation of your V2 file ---
    # 例如，如果你的文件有3个分区:
    # assert items.size() == 3

    # # 检查第一个分区
    # first_part = items.data[0]
    # assert first_part.partName == "uboot_spl_a"
    # assert first_part.partOffset == 0x00000000
    # assert first_part.partSize == 0x34000
    # ---------------------------------------------


def test_parse_valid_v1_kdimage(sample_files_dir):
    """Test whether a correctly structured V1 version kdimage file can be successfully parsed"""
    v1_file = sample_files_dir / "v1_correct.kdimg"
    if not v1_file.exists():
        pytest.skip(f"Sample file does not exist: {v1_file}")

    KburnKdImage.deleteInstance()
    items = get_kdimage_items(v1_file)

    assert items is not None
    assert items.size() > 0
    # --- Please modify the assertion according to the actual situation of your V1 file ---


def test_read_and_verify_sha256(sample_files_dir):
    """Test whether read_part_data can successfully read data and pass the SHA256 check"""
    v2_file = sample_files_dir / "v2_correct.kdimg"
    if not v2_file.exists():
        pytest.skip(f"Sample file does not exist: {v2_file}")

    KburnKdImage.deleteInstance()
    kdimg_instance = KburnKdImage.instance(v2_file)
    items = kdimg_instance.items()
    assert items is not None

    # Read the data of the first partition
    first_item = items.data[0]
    data = kdimg_instance.read_part_data(first_item)

    assert data is not None
    assert len(data) == first_item.partSize


def test_corrupt_magic_file(sample_files_dir):
    """Test whether parsing a kdimage file with an incorrect header magic will fail"""
    corrupt_file = sample_files_dir / "corrupt_magic.kdimg"
    if not corrupt_file.exists():
        pytest.skip(f"Sample file does not exist: {corrupt_file}")

    KburnKdImage.deleteInstance()
    items = get_kdimage_items(corrupt_file)

    # Parsing should fail and return None
    assert items is None


def test_corrupt_sha256_file(sample_files_dir):
    """Test whether read_part_data will fail when the partition data does not match the SHA256"""
    corrupt_file = sample_files_dir / "corrupt_sha.kdimg"
    if not corrupt_file.exists():
        pytest.skip(f"Sample file does not exist: {corrupt_file}")

    KburnKdImage.deleteInstance()
    kdimg_instance = KburnKdImage.instance(corrupt_file)
    items = kdimg_instance.items()
    assert items is not None, "The file structure itself should be correct, only the data content is damaged"

    # Assume that the data of the first partition is corrupted
    first_item = items.data[0]

    # Reading this corrupted partition should fail and return None
    data = kdimg_instance.read_part_data(first_item)
    assert data is None
