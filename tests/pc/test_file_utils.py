"""Tests for transparent decompression of flash inputs (file_utils.py).

This module had no coverage at all, which is how the zip and tar branches
shipped returning paths inside an already-deleted temporary directory: they used
`with tempfile.TemporaryDirectory()` and returned a path from inside the `with`.
Every assertion here checks the returned path actually *exists*, because that is
precisely what was broken.
"""

import gzip
import io
import tarfile
import zipfile

import pytest

from k230_flash.file_utils import extract_if_compressed


@pytest.fixture
def payload():
    return b"\xa5" * 2048


def _make_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _make_targz(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


# --- the happy paths, all four container types --------------------------------


def test_zip_yields_a_path_that_exists(tmp_path, payload):
    """The returned file must survive the call. It used to be deleted with its
    temporary directory before extract_if_compressed even returned."""
    archive = _make_zip(tmp_path / "fw.zip", {"boot.img": payload})

    result = extract_if_compressed(archive)

    assert result.exists(), "extracted image was deleted before it could be flashed"
    assert result.read_bytes() == payload
    assert result.suffix == ".img"


def test_targz_yields_a_path_that_exists(tmp_path, payload):
    archive = _make_targz(tmp_path / "fw.tar.gz", {"boot.img": payload})

    result = extract_if_compressed(archive)

    assert result.exists()
    assert result.read_bytes() == payload


def test_tgz_yields_a_path_that_exists(tmp_path, payload):
    archive = _make_targz(tmp_path / "fw.tgz", {"sys.kdimg": payload})

    result = extract_if_compressed(archive)

    assert result.exists()
    assert result.read_bytes() == payload


def test_plain_gz_yields_a_path_that_exists(tmp_path, payload):
    archive = tmp_path / "boot.img.gz"
    with gzip.open(archive, "wb") as f:
        f.write(payload)

    result = extract_if_compressed(archive)

    assert result.exists()
    assert result.read_bytes() == payload
    assert result.name == "boot.img"


def test_uncompressed_file_is_passed_through(tmp_path, payload):
    img = tmp_path / "boot.img"
    img.write_bytes(payload)

    assert extract_if_compressed(img) == img


# --- selection rules ----------------------------------------------------------


def test_kdimg_is_preferred_over_img(tmp_path):
    """_find_first_image looks for .kdimg before .img, so a package containing
    both flashes the whole-image container rather than one of its parts."""
    archive = _make_zip(tmp_path / "both.zip", {"part.img": b"\x01" * 16, "whole.kdimg": b"\x02" * 16})

    assert extract_if_compressed(archive).suffix == ".kdimg"


def test_selection_is_deterministic_across_calls(tmp_path):
    """rglob order is filesystem-dependent; a package with several images must
    not resolve to a different one on a different machine."""
    members = {f"img_{i}.img": bytes([i]) * 16 for i in range(6)}
    first = extract_if_compressed(_make_zip(tmp_path / "a.zip", members))
    second = extract_if_compressed(_make_zip(tmp_path / "b.zip", members))

    assert first.name == second.name


def test_archive_without_an_image_is_reported(tmp_path):
    archive = _make_zip(tmp_path / "empty.zip", {"README.txt": b"nothing to flash"})

    with pytest.raises(FileNotFoundError):
        extract_if_compressed(archive)


# --- hardening ----------------------------------------------------------------


def test_zip_traversal_entry_is_refused(tmp_path, payload):
    """Firmware archives arrive from build servers and chat apps. An entry that
    escapes the extraction directory must be refused, not written."""
    archive = _make_zip(tmp_path / "evil.zip", {"../escaped.img": payload})

    with pytest.raises(ValueError):
        extract_if_compressed(archive)

    assert not (tmp_path / "escaped.img").exists()


def test_tar_traversal_entry_is_refused(tmp_path, payload):
    archive = _make_targz(tmp_path / "evil.tar.gz", {"../escaped.img": payload})

    with pytest.raises(ValueError):
        extract_if_compressed(archive)

    assert not (tmp_path / "escaped.img").exists()
