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


def _make_temp_dir():
    """Create a scratch directory that outlives this call.

    The zip and tar branches used to use `with tempfile.TemporaryDirectory()`
    and return a path *inside* it, so the directory was deleted the moment the
    function returned and every caller got a path that did not exist. Extracted
    files have to survive until the flash is over, so the directory is torn down
    at interpreter exit instead.
    """
    tmpdir = tempfile.mkdtemp(prefix="k230_flash_")
    _temp_dirs.append(tmpdir)
    return tmpdir


def _is_within(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False


def _safe_extract_zip(zip_ref, tmpdir):
    """Extract, refusing entries that would land outside `tmpdir`.

    A crafted archive can carry names like `../../.ssh/authorized_keys`; the
    stdlib's extractall() happily follows them. Firmware archives arrive from
    build servers and chat apps, so this is worth the few lines.
    """
    for member in zip_ref.namelist():
        destination = Path(tmpdir) / member
        if not _is_within(tmpdir, destination):
            raise ValueError(f"压缩包中包含非法路径，已拒绝解压: {member}")
    zip_ref.extractall(tmpdir)


def _safe_extract_tar(tar_ref, tmpdir):
    for member in tar_ref.getmembers():
        destination = Path(tmpdir) / member.name
        if not _is_within(tmpdir, destination):
            raise ValueError(f"压缩包中包含非法路径，已拒绝解压: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"压缩包中包含链接条目，已拒绝解压: {member.name}")
    # filter="data" is the hardened extraction mode; it exists from 3.12 and is
    # the default from 3.14, so pass it explicitly where available.
    try:
        tar_ref.extractall(tmpdir, filter="data")
    except TypeError:  # pragma: no cover - Python < 3.12
        tar_ref.extractall(tmpdir)


def extract_if_compressed(file_path: Path) -> Path:
    """
    If the file is a zip/gz/tgz/tar.gz, it will be automatically decompressed and the path to the decompressed file will be returned.
    Otherwise, the original path is returned directly.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    is_tar_gz = file_path.name.lower().endswith(".tar.gz")

    # Handle .zip
    if suffix == ".zip":
        tmpdir = _make_temp_dir()
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            logger.info(f"正在解压 ZIP 文件: {file_path.name}")
            _safe_extract_zip(zip_ref, tmpdir)
        return _find_first_image(tmpdir)

    # Handle .tar.gz / .tgz
    if suffix == ".tgz" or is_tar_gz:
        tmpdir = _make_temp_dir()
        with tarfile.open(file_path, "r:gz") as tar_ref:
            logger.info(f"正在解压 TAR.GZ 文件: {file_path.name}")
            _safe_extract_tar(tar_ref, tmpdir)
        return _find_first_image(tmpdir)

    # Handle .gz (single file, not a tarball)
    if suffix == ".gz":
        tmpdir = _make_temp_dir()
        # Construct the output path using the original file's stem
        output_path = Path(tmpdir) / file_path.stem
        logger.info(f"正在解压 GZ 文件: {file_path.name}")
        with gzip.open(file_path, "rb") as gz_ref:
            with open(output_path, "wb") as out_f:
                shutil.copyfileobj(gz_ref, out_f)
        return output_path

    # Not a compressed file
    return file_path


def _find_first_image(directory) -> Path:
    """
    Find the first .img or .kdimg file in the decompressed directory
    """
    for ext in ("*.kdimg", "*.img"):
        files = sorted(Path(directory).rglob(ext))
        if files:
            logger.debug(f"找到镜像文件: {files[0]}")
            return files[0]
    raise FileNotFoundError("No flashable image file found after decompression")
