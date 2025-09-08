# file_utils.py
import atexit
import gzip
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

from loguru import logger

_temp_dirs = []


def _cleanup_temp_dirs():
    for d in _temp_dirs:
        try:
            shutil.rmtree(d)
            logger.debug(f"Cleaning up temporary directory: {d}")
        except OSError as e:
            logger.warning(f"Failed to clean up temporary directory {d}: {e}")


atexit.register(_cleanup_temp_dirs)


def extract_if_compressed(file_path: Path) -> Path:
    """
    If the file is a zip/gz/tgz/tar.gz, it will be automatically decompressed and the path to the decompressed file will be returned.
    Otherwise, the original path is returned directly.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    # Handle .zip
    if suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                logger.info(f"正在解压 ZIP 文件...")
                zip_ref.extractall(tmpdir)
                return _find_first_image(tmpdir)

    # Handle .gz (single file)
    if suffix == ".gz" and not file_path.name.endswith(".tar.gz"):
        # Create a temporary directory
        tmpdir = tempfile.mkdtemp()
        _temp_dirs.append(tmpdir)  # Add to cleanup list
        # Construct the output path using the original file's stem
        output_path = Path(tmpdir) / file_path.stem
        logger.info(f"正在解压 GZ 文件...")
        with gzip.open(file_path, "rb") as gz_ref:
            with open(output_path, "wb") as out_f:
                shutil.copyfileobj(gz_ref, out_f)

        return output_path

    # Handle .tar.gz / .tgz
    if suffix in [".tgz", ".gz"] or file_path.suffixes[-2:] == [".tar", ".gz"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(file_path, "r:gz") as tar_ref:
                logger.info(f"正在解压 TAR.GZ 文件...")
                tar_ref.extractall(tmpdir)
                return _find_first_image(tmpdir)

    # Not a compressed file
    return file_path


def _find_first_image(directory) -> Path:
    """
    Find the first .img or .kdimg file in the decompressed directory
    """
    for ext in ("*.kdimg", "*.img"):
        files = list(Path(directory).rglob(ext))
        if files:
            logger.debug(f"找到镜像文件: {files[0]}")
            return files[0]
    raise FileNotFoundError("No flashable image file found after decompression")
