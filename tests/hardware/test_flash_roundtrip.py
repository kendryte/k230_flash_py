"""Real-hardware coverage of an end-to-end flash.

Destructive: these overwrite the board's storage. Only point K230_TEST_PORT at a
board whose contents you are willing to lose.

Every flash goes through the `flash_with_retry` fixture, which absorbs one known
device-side defect (the loader's medium init intermittently wedges the gadget)
while letting every other failure through. Without that these tests would go red
roughly half the time for a reason unrelated to the code under test.

Run with:  pytest --hardware -m hardware tests/hardware/test_flash_roundtrip.py
"""

import time
import tracemalloc

import pytest
from helpers.known_faults import is_known_medium_probe_failure

from k230_flash import api

pytestmark = pytest.mark.hardware


def _flash(port, media, pairs):
    api.flash_addr_file_pairs(
        addr_filename_pairs=pairs,
        port_path=port,
        media_type=media,
        auto_reboot=False,
        progress_callback=lambda current, total: None,
        log_level="INFO",
    )


def test_flash_small_image(flash_with_retry, board_port, media_type, tmp_path):
    """Smallest useful end-to-end: handoff, probe, write, and the completion
    acknowledgement all have to succeed.

    A device-side write failure now raises instead of being reported as success,
    so this fails loudly if that regresses.
    """
    image = tmp_path / "smoke.img"
    image.write_bytes(bytes(range(256)) * 4096)  # 1 MiB, non-uniform

    flash_with_retry(lambda: _flash(board_port, media_type, [(0x0, image)]))


def test_flash_reports_reasonable_throughput(flash_with_retry, board_port, media_type, tmp_path):
    """Throughput is bounded by the medium, not USB: measured ~11 MB/s to SD
    against ~37 MB/s for the USB link alone. The floor is deliberately loose --
    it catches a collapse (a chunk-size or timeout regression dropping it by an
    order of magnitude), not normal variation between cards.
    """
    size_mb = 32
    image = tmp_path / "perf.img"
    image.write_bytes(b"\xa5" * (size_mb * 1024 * 1024))

    started = time.monotonic()
    flash_with_retry(lambda: _flash(board_port, media_type, [(0x0, image)]))
    elapsed = time.monotonic() - started

    throughput = size_mb / elapsed
    assert throughput > 2.0, f"{throughput:.1f} MB/s is far below the ~11 MB/s baseline"


def test_flash_streams_instead_of_buffering_the_image(flash_with_retry, board_port, media_type, tmp_path):
    """Images must be streamed a chunk at a time.

    Reading one whole used to peak at 1.13 GB for a 1.14 GiB file; streaming
    holds one chunk. tracemalloc is used rather than RSS because it attributes
    allocations to this code instead of tracking a process-wide high-water mark
    that never comes back down.
    """
    size_mb = 64
    image = tmp_path / "mem.img"
    image.write_bytes(b"\x5a" * (size_mb * 1024 * 1024))

    tracemalloc.start()
    try:
        flash_with_retry(lambda: _flash(board_port, media_type, [(0x0, image)]))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    assert peak_mb < size_mb / 2, (
        f"peak Python allocation was {peak_mb:.0f} MB while flashing a {size_mb} MB "
        "image; the image is probably being read whole again"
    )


def test_rejects_an_image_larger_than_the_device(flash_with_retry, board_port, media_type, tmp_path):
    """Sparse file, so this costs no real disk. The size check must reject it
    rather than starting a write that cannot finish."""
    oversized = tmp_path / "toobig.img"
    with open(oversized, "wb") as handle:
        handle.seek(2 * 1024**4)  # 2 TiB
        handle.write(b"\x00")

    def attempt():
        with pytest.raises(Exception) as exc:
            _flash(board_port, media_type, [(0x0, oversized)])
        message = str(exc.value)
        # Let the known probe defect bubble up so the fixture can retry it;
        # anything else here is the real rejection we are asserting on.
        if is_known_medium_probe_failure(exc.value):
            raise exc.value
        assert (
            "exceed" in message.lower() or "容量" in message or "DATA SIZE" in message
        ), f"expected a size rejection, got: {message}"

    flash_with_retry(attempt)
