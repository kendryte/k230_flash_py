"""End-to-end flashing against a simulated board.

These drive the public API the way the CLI does -- no internals monkeypatched --
through both stages: loader upload over BootROM, re-enumeration, probe, write,
completion. Because the simulator keeps a storage medium, the assertions are
about *bytes landing at the right offsets*, not merely "did not raise".

The BootROM half in particular had no coverage before: every earlier test had to
patch `handle_bootrom_mode` away because there was nothing to upload a loader to.
"""

import pytest
from helpers.board_simulator import UBOOT_EP_OUT, Faults, SimulatedK230, install
from helpers.kdimg_builder import Partition, write_kdimg_file

from k230_flash import api


@pytest.fixture
def sim(monkeypatch):
    return install(monkeypatch, SimulatedK230())


def _quiet(current, total):
    pass


# --- the full two-stage flow --------------------------------------------------


def test_flashes_raw_images_end_to_end(sim, tmp_path):
    """Mode 1, all the way through, with the written bytes verified."""
    first = tmp_path / "uboot.img"
    second = tmp_path / "rtt.img"
    first.write_bytes(b"\x11" * 2048)
    second.write_bytes(b"\x22" * 4096)

    api.flash_addr_file_pairs(
        addr_filename_pairs=[(0x0, first), (0x400000, second)],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=_quiet,
    )

    assert sim.read_back(0x0) == b"\x11" * 2048
    assert sim.read_back(0x400000) == b"\x22" * 4096


def test_the_loader_really_is_uploaded_and_started(sim, tmp_path):
    """The BootROM half: a loader image must be pushed to the right SRAM address
    and the chip must actually leave BootROM. Previously untestable off-bench."""
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x33" * 512)

    api.flash_addr_file_pairs(
        addr_filename_pairs=[(0x0, image)],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=_quiet,
    )

    assert sim.stage == "uboot", "the chip never left BootROM"
    assert sim.load_address == 0x80360000
    assert len(sim.loader_bytes) > 100_000, "loader upload looks truncated"
    # Whatever was uploaded must be the loader that ships for this medium.
    from k230_flash.burners import K230BROMBurner

    expected = K230BROMBurner.__new__(K230BROMBurner).get_loader("SDCARD")
    assert sim.loader_bytes == expected


def test_endpoints_switch_across_the_handoff(sim, tmp_path):
    """The regression that started all of this: after the loader boots we must be
    writing to the U-Boot OUT endpoint, not BootROM's."""
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x44" * 1024)
    assert sim.endpoints[0] == 0x01, "precondition: BootROM exposes OUT 0x01"

    api.flash_addr_file_pairs(
        addr_filename_pairs=[(0x0, image)],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=_quiet,
    )

    assert sim.endpoints[0] == UBOOT_EP_OUT


def test_flashes_a_kdimg_end_to_end(sim, tmp_path):
    """Mode 2: every partition lands at its declared offset with its own bytes.

    A partition written to the wrong offset, or two partitions swapped, would
    pass a "did not raise" test and brick a board.
    """
    image = write_kdimg_file(
        tmp_path / "fw.kdimg",
        [
            Partition("uboot_a", offset=0x0, data=b"\xaa" * 1024),
            Partition("rtt", offset=0x200000, data=b"\xbb" * 2048),
            Partition("data", offset=0x800000, data=b"\xcc" * 512),
        ],
    )

    api.flash_kdimg(kdimg_file=image, port_path=sim.port_path, media_type="SDCARD", progress_callback=_quiet)

    assert sim.read_back(0x0) == b"\xaa" * 1024
    assert sim.read_back(0x200000) == b"\xbb" * 2048
    assert sim.read_back(0x800000) == b"\xcc" * 512


def test_kdimg_partition_selection_writes_only_what_was_asked(sim, tmp_path):
    """Mode 3. Writing an unselected partition would silently clobber data the
    user meant to keep."""
    image = write_kdimg_file(
        tmp_path / "fw.kdimg",
        [
            Partition("uboot_a", offset=0x0, data=b"\xaa" * 512),
            Partition("keep_me", offset=0x200000, data=b"\xbb" * 512),
        ],
    )

    api.flash_kdimg(
        kdimg_file=image,
        selected_partitions=["uboot_a"],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=_quiet,
    )

    assert sim.read_back(0x0) == b"\xaa" * 512
    assert sim.read_back(0x200000) is None, "an unselected partition was written"


def test_padded_partition_is_written_at_full_declared_size(sim, tmp_path):
    """Short payloads are padded to part_size with 0xFF before being sent."""
    image = write_kdimg_file(
        tmp_path / "padded.kdimg",
        [Partition("padded", offset=0x0, data=b"\xa5" * 100, size=512)],
    )

    api.flash_kdimg(kdimg_file=image, port_path=sim.port_path, media_type="SDCARD", progress_callback=_quiet)

    written = sim.read_back(0x0)
    assert len(written) == 512
    assert written[:100] == b"\xa5" * 100
    assert written[100:] == b"\xff" * 412


def test_large_image_is_chunked_but_arrives_intact(sim, tmp_path):
    """Multi-chunk transfer: the device negotiates 128 KiB, so this crosses
    several boundaries plus a partial tail. Reassembly errors show up as
    corrupted content rather than a raised exception."""
    payload = bytes(range(256)) * 2048  # 512 KiB, non-uniform
    image = tmp_path / "big.img"
    image.write_bytes(payload)

    api.flash_addr_file_pairs(
        addr_filename_pairs=[(0x0, image)],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=_quiet,
    )

    assert sim.read_back(0x0) == payload
    assert sim.total_bytes_written == len(payload)


def test_progress_is_reported_up_to_completion(sim, tmp_path):
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x55" * 300_000)
    seen = []

    api.flash_addr_file_pairs(
        addr_filename_pairs=[(0x0, image)],
        port_path=sim.port_path,
        media_type="SDCARD",
        progress_callback=lambda current, total: seen.append((current, total)),
    )

    assert seen, "no progress was reported"
    assert seen[-1] == (300_000, 300_000), "progress never reached 100%"
    assert all(c <= t for c, t in seen), "progress exceeded the total"


# --- failure paths ------------------------------------------------------------


def test_medium_probe_failure_is_reported_not_swallowed(monkeypatch, tmp_path):
    sim = install(monkeypatch, SimulatedK230(faults=Faults(probe_fails=True)))
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x66" * 512)

    with pytest.raises(RuntimeError) as exc:
        api.flash_addr_file_pairs(
            addr_filename_pairs=[(0x0, image)],
            port_path=sim.port_path,
            media_type="SDCARD",
            progress_callback=_quiet,
        )

    assert "SDCARD" in str(exc.value)
    assert sim.storage == {}, "nothing should have been written"


def test_wedged_gadget_is_reported_with_recovery_advice(monkeypatch, tmp_path):
    """Reproduces the known device defect in software: after a failed probe the
    gadget stops answering entirely. The user must be told to power-cycle, since
    nothing on the host side can recover it."""
    sim = install(monkeypatch, SimulatedK230(faults=Faults(probe_fails=True, dead_after_probe=True)))
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x77" * 512)

    with pytest.raises(RuntimeError) as exc:
        api.flash_addr_file_pairs(
            addr_filename_pairs=[(0x0, image)],
            port_path=sim.port_path,
            media_type="SDCARD",
            progress_callback=_quiet,
        )

    message = str(exc.value)
    assert "media-type" in message or "介质" in message
    assert "上电" in message or "power" in message.lower()


def test_device_side_write_failure_is_not_reported_as_success(monkeypatch, tmp_path):
    """The bug that mattered most: the device said the write failed and the host
    reported success because nobody read the reply."""
    sim = install(monkeypatch, SimulatedK230(faults=Faults(write_fails=True)))
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x88" * 4096)

    with pytest.raises(Exception) as exc:
        api.flash_addr_file_pairs(
            addr_filename_pairs=[(0x0, image)],
            port_path=sim.port_path,
            media_type="SDCARD",
            progress_callback=_quiet,
        )

    assert "WRITE ERROR" in str(exc.value) or "写入" in str(exc.value)


def test_loader_that_never_starts_is_retried_then_reported(monkeypatch, tmp_path):
    sim = install(monkeypatch, SimulatedK230(faults=Faults(loader_never_starts=True)))
    monkeypatch.setattr(api, "LOADER_ENUMERATION_TIMEOUT", 0.05)
    monkeypatch.setattr(api, "LOADER_FALLBACK_TIMEOUT", 0.05)
    monkeypatch.setattr(api, "LOADER_BOOT_ATTEMPTS", 2)
    image = tmp_path / "fw.img"
    image.write_bytes(b"\x99" * 512)

    with pytest.raises(RuntimeError) as exc:
        api.flash_addr_file_pairs(
            addr_filename_pairs=[(0x0, image)],
            port_path=sim.port_path,
            media_type="SDCARD",
            progress_callback=_quiet,
        )

    assert "U-Boot" in str(exc.value)
    assert sim.stage == "brom"


def test_image_larger_than_capacity_is_rejected_before_writing(monkeypatch, tmp_path):
    sim = install(monkeypatch, SimulatedK230(faults=Faults(capacity=1024 * 1024)))
    image = tmp_path / "big.img"
    image.write_bytes(b"\x00" * (2 * 1024 * 1024))

    with pytest.raises(Exception):
        api.flash_addr_file_pairs(
            addr_filename_pairs=[(0x0, image)],
            port_path=sim.port_path,
            media_type="SDCARD",
            progress_callback=_quiet,
        )

    assert sim.storage == {}, "data was written despite exceeding capacity"
