"""Tests for the .kdimg write loop (kdimg_utils.py).

Every path here used to `return False` while the caller ignored the return
value, so a rejected image or an unwritten partition was reported to the user as
a successful flash. These assert they raise instead.
"""

import tracemalloc

import pytest
from helpers.fake_usb import FakeKburnDevice
from helpers.kdimg_builder import Partition, write_kdimg_file

from k230_flash.burners import K230UBOOTBurner
from k230_flash.kdimg_utils import write_kdimg


@pytest.fixture
def burner():
    b = K230UBOOTBurner(FakeKburnDevice(capacity=64 * 1024 * 1024), "SDCARD")
    b.probe()
    b.get_capacity()
    return b


@pytest.fixture
def image(tmp_path):
    return write_kdimg_file(
        tmp_path / "fw.kdimg",
        [
            Partition("uboot_a", offset=0x0, data=b"\x11" * 512),
            Partition("rtt", offset=0x100000, data=b"\x22" * 1024),
        ],
    )


def test_writes_every_partition(burner, image):
    assert write_kdimg(image, burner) is True

    offsets = [offset for offset, _size, _data in burner.dev.sessions]
    assert offsets == [0x0, 0x100000]
    assert burner.dev.sessions[0][2] == b"\x11" * 512


def test_selected_partitions_limits_what_is_written(burner, image):
    write_kdimg(image, burner, selected_partitions=["rtt"])

    assert [o for o, _s, _d in burner.dev.sessions] == [0x100000]


def test_unknown_selected_partition_is_reported(burner, image):
    """Asking for a partition the image does not contain used to silently write
    nothing and exit successfully."""
    with pytest.raises(ValueError) as exc:
        write_kdimg(image, burner, selected_partitions=["does_not_exist"])

    assert "does_not_exist" in str(exc.value)


def test_image_larger_than_the_device_is_rejected(burner, tmp_path):
    """The capacity check existed but only logged and returned False."""
    too_big = write_kdimg_file(
        tmp_path / "big.kdimg",
        [Partition("huge", offset=0, data=b"\x00" * 16, size=16, max_size=128 * 1024 * 1024)],
    )

    with pytest.raises(ValueError) as exc:
        write_kdimg(too_big, burner)

    assert "容量" in str(exc.value) or "capacity" in str(exc.value).lower()


def test_oversized_partition_is_caught_before_earlier_ones_are_written(burner, tmp_path):
    """The whole-image check uses the declared layout (part_max_size), but what
    is actually sent is max(partContentSize, partSize). For an image where a
    payload exceeds its declared max_size, the two disagree -- and the per-write
    guard in write_start() would only trip partway through, after earlier
    partitions had already been committed. Every capacity check must happen
    before the first byte goes out.
    """
    img = write_kdimg_file(
        tmp_path / "overflow.kdimg",
        [
            Partition("first", offset=0x0, data=b"\x11" * 512),
            Partition("second", offset=burner.capacity - 1024, data=b"\x22" * 4096, max_size=1024),
        ],
    )

    with pytest.raises(ValueError) as exc:
        write_kdimg(img, burner)

    assert "second" in str(exc.value)
    assert burner.dev.sessions == [], "first must not have been written"


def test_unparseable_image_is_rejected(burner, tmp_path):
    broken = tmp_path / "broken.kdimg"
    broken.write_bytes(b"not a kdimg at all" * 64)

    with pytest.raises(ValueError):
        write_kdimg(broken, burner)


def test_unknown_selected_partition_is_caught_before_anything_is_written(burner, image):
    """The check used to run *after* the write loop, so a typo in one name
    flashed every valid name first and only then reported the mistake, leaving
    the board half updated with nothing in the error to say so."""
    with pytest.raises(ValueError):
        write_kdimg(image, burner, selected_partitions=["uboot_a", "typo"])

    assert burner.dev.sessions == [], "uboot_a must not have been written"


class _DiscardingDevice(FakeKburnDevice):
    """Like FakeKburnDevice but records only sizes, never payload bytes.

    The stock double keeps every byte it is sent -- once in `written`, once in
    `received`/`sessions` -- which would dominate any memory measurement and
    hide what the code under test actually does.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chunk_lengths = []

    def write(self, endpoint, data, timeout=None):
        payload = bytes(data)
        self._on_write(endpoint, payload)
        return len(payload)

    def _on_write(self, endpoint, payload):
        if self.expecting > 0:
            self.chunk_lengths.append(len(payload))
            self.received = b""  # drop it; only the running total matters
        return super()._on_write(endpoint, payload)


def _flash_one_partition_and_measure(tmp_path, name, part_size, chunk_size=128 * 1024):
    """Write a single padded partition of `part_size` and return (peak, device)."""
    img = write_kdimg_file(
        tmp_path / f"{name}.kdimg",
        [Partition("rootfs", offset=0x0, data=b"\x5a" * (part_size // 2), size=part_size)],
    )
    burner = K230UBOOTBurner(_DiscardingDevice(capacity=512 * 1024 * 1024, chunk_size=chunk_size), "SDCARD")
    burner.probe()
    burner.get_capacity()

    tracemalloc.start()
    try:
        write_kdimg(img, burner)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, burner.dev


def test_partitions_are_streamed_not_buffered(tmp_path):
    """Peak memory must not scale with partition size.

    read_part_data used to build the whole payload in memory and then append its
    0xFF padding to it, so peak heap was roughly twice the partition size --
    several GB for a full rootfs. Asserting a fixed byte ceiling would just pin
    whatever the chunk constants happen to be, so this compares two partition
    sizes instead: quadrupling the partition must not meaningfully move the
    peak. Under the old code it would quadruple it.
    """
    chunk_size = 128 * 1024
    small_peak, small_dev = _flash_one_partition_and_measure(tmp_path, "small", 8 * 1024 * 1024, chunk_size)
    large_peak, large_dev = _flash_one_partition_and_measure(tmp_path, "large", 32 * 1024 * 1024, chunk_size)

    # The device still receives every byte, padding included.
    assert sum(small_dev.chunk_lengths) == 8 * 1024 * 1024
    assert sum(large_dev.chunk_lengths) == 32 * 1024 * 1024
    assert max(large_dev.chunk_lengths) <= chunk_size, "payload must be split into chunks"

    assert large_peak < small_peak * 1.5, (
        f"peak grew from {small_peak} to {large_peak} when the partition grew 4x; "
        "the partition is being buffered rather than streamed"
    )
    assert large_peak < 8 * 1024 * 1024, f"peak {large_peak} is on the order of the partition size"


def test_corrupt_partition_payload_is_rejected(burner, tmp_path):
    """A SHA-256 mismatch means read_part_data returns None; writing that to a
    board would brick it, so the flash must stop."""
    from helpers.kdimg_builder import build_kdimg

    img = tmp_path / "bad_sha.kdimg"
    img.write_bytes(build_kdimg([Partition("uboot_a", offset=0, data=b"\x11" * 512)], corrupt_sha_of="uboot_a"))

    with pytest.raises(ValueError):
        write_kdimg(img, burner)

    assert burner.dev.sessions == [], "nothing should have been written"
