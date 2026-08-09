"""Tests for the kburn protocol implementation (burners.py).

Driven against FakeKburnDevice, which answers commands the way the real gadget
does, so the request/response pairing is exercised rather than mocked away.
"""

import io
import struct

import pytest
import usb.core
from helpers import fake_usb
from helpers.fake_usb import BROM_EP_OUT, UBOOT_EP_IN, UBOOT_EP_OUT, FakeDevice, FakeKburnDevice, make_packet

from k230_flash.burners import (
    KBURN_CMD_WRITE_LBA,
    DataWriteError,
    DeviceConfigurationError,
    K230UBOOTBurner,
    USBCommunicationError,
    write_images,
)


@pytest.fixture
def burner():
    return K230UBOOTBurner(FakeKburnDevice(), "SDCARD")


# --- endpoint discovery -------------------------------------------------------


def test_discovers_uboot_endpoints_not_bootrom_ones():
    """The stages expose different OUT endpoints. Reading them from whatever
    device we are actually holding is the entire fix for the handoff bug."""
    b = K230UBOOTBurner(FakeKburnDevice(), "SDCARD")

    assert b.ep_out == UBOOT_EP_OUT
    assert b.ep_in == UBOOT_EP_IN
    assert b.ep_out != BROM_EP_OUT


def test_rejects_a_descriptor_missing_an_endpoint():
    """A half-enumerated device must fail loudly instead of leaving ep_out None
    and writing to nothing."""
    dev = FakeDevice(mode="uboot")
    dev.get_active_configuration = lambda: fake_usb.FakeConfiguration(
        [fake_usb.FakeInterface([fake_usb.FakeEndpoint(UBOOT_EP_IN)])]
    )

    with pytest.raises(DeviceConfigurationError):
        K230UBOOTBurner(dev, "SDCARD")


def test_ignores_non_bulk_endpoints():
    """Only bulk endpoints carry kburn traffic; an interrupt endpoint in the
    descriptor must not be mistaken for one."""
    dev = FakeDevice(mode="uboot")
    dev.get_active_configuration = lambda: fake_usb.FakeConfiguration(
        [
            fake_usb.FakeInterface(
                [
                    fake_usb.FakeEndpoint(0x03, bulk=False),
                    fake_usb.FakeEndpoint(UBOOT_EP_OUT),
                    fake_usb.FakeEndpoint(UBOOT_EP_IN),
                ]
            )
        ]
    )

    b = K230UBOOTBurner(dev, "SDCARD")

    assert (b.ep_out, b.ep_in) == (UBOOT_EP_OUT, UBOOT_EP_IN)


# --- probe / capacity ---------------------------------------------------------


def test_probe_and_capacity_read_device_values(burner):
    burner.probe()
    capacity = burner.get_capacity()

    assert burner.out_chunk_size == 131072
    assert capacity == 16 * 1024**3
    assert burner.blk_sz == 512


# --- write_end ----------------------------------------------------------------


def test_write_end_accepts_the_completion_packet(burner):
    burner.dev.queue_response(make_packet(KBURN_CMD_WRITE_LBA, data=b"WRITE DONE"))

    assert burner.write_end() is True


def test_write_end_raises_when_the_device_reports_a_write_error(burner):
    """This is the bug that mattered most: the gadget said the write failed and
    the host reported success because nobody read the reply."""
    burner.dev.queue_response(make_packet(KBURN_CMD_WRITE_LBA, fake_usb.KBURN_RESULT_ERROR_MSG, b"WRITE ERROR, 0x5"))

    with pytest.raises(DataWriteError) as exc:
        burner.write_end()

    assert "WRITE ERROR" in str(exc.value), "the device's own message should reach the user"


def test_write_end_raises_on_a_mismatched_response(burner):
    """A reply for a different command means the pipe is out of step; continuing
    would attribute someone else's result to this write."""
    burner.dev.queue_response(make_packet(0x10, data=b"probe reply"))

    with pytest.raises(DataWriteError):
        burner.write_end()


def test_write_end_raises_when_nothing_comes_back(burner):
    with pytest.raises(DataWriteError):
        burner.write_end()  # nothing queued -> read times out


# --- streaming ----------------------------------------------------------------


def test_write_chunks_from_streams_in_chunk_sized_pieces(burner):
    burner.probe()
    burner.dev.written.clear()  # drop probe's command packets; count payload only
    payload = b"\xa5" * (131072 * 2 + 100)

    burner.write_chunks_from(io.BytesIO(payload), len(payload))

    sent = b"".join(data for ep, data in burner.dev.written if ep == UBOOT_EP_OUT)
    assert sent == payload
    sizes = [len(d) for ep, d in burner.dev.written if ep == UBOOT_EP_OUT]
    assert sizes == [131072, 131072, 100]


def test_write_chunks_from_sends_zlp_on_exact_multiple(burner):
    """A transfer that is an exact multiple of the chunk size needs a zero-length
    packet to mark the boundary, or the device keeps waiting for more."""
    burner.probe()
    burner.dev.written.clear()  # drop probe's command packets; count payload only
    payload = b"\x5a" * 131072

    burner.write_chunks_from(io.BytesIO(payload), len(payload))

    sizes = [len(d) for ep, d in burner.dev.written if ep == UBOOT_EP_OUT]
    assert sizes == [131072, 0]


def test_write_chunks_from_rejects_a_short_source(burner):
    """Declaring more bytes than the stream holds would otherwise leave the
    device waiting forever for payload that never arrives."""
    burner.probe()

    with pytest.raises(DataWriteError) as exc:
        burner.write_chunks_from(io.BytesIO(b"only ten!!"), 1000)

    assert "10/1000" in str(exc.value)


def test_write_image_stream_does_a_full_round_trip(burner):
    """Start, payload and completion together -- the device only acknowledges
    after it has received every promised byte."""
    burner.probe()
    burner.get_capacity()
    payload = b"\x11" * 4096

    assert burner.write_image_stream(io.BytesIO(payload), len(payload), 0x400000) is True

    assert burner.dev.sessions == [(0x400000, 4096, payload)]


def test_write_image_stream_surfaces_a_device_write_failure(burner):
    burner.dev.write_should_fail = True
    burner.probe()
    burner.get_capacity()

    with pytest.raises(DataWriteError):
        burner.write_image_stream(io.BytesIO(b"\x22" * 2048), 2048, 0)


def test_write_start_rejects_unaligned_offset(burner):
    burner.probe()
    burner.get_capacity()

    with pytest.raises(ValueError):
        burner.write_start(0x201, 512)


# --- write_images (mode 1) ----------------------------------------------------


def test_write_images_streams_files_without_reading_them_whole(tmp_path, burner):
    """A full-card image is easily multiple GB; write_images must not slurp it."""
    burner.probe()
    burner.get_capacity()
    img = tmp_path / "firmware.img"
    img.write_bytes(b"\x33" * 5000)

    write_images([(0x0, img)], burner)

    assert burner.dev.sessions == [(0x0, 5000, b"\x33" * 5000)]


def test_write_images_reports_a_missing_file(tmp_path, burner):
    """Reported as FileNotFoundError rather than repackaged as a RuntimeError,
    so a caller can tell "you named a file that isn't there" apart from "the
    write failed"."""
    burner.probe()
    burner.get_capacity()

    with pytest.raises(FileNotFoundError):
        write_images([(0x0, tmp_path / "nope.img")], burner)


def test_write_images_rejects_an_empty_file(tmp_path, burner):
    """A zero-byte image writes nothing and would otherwise be reported as a
    successful flash."""
    burner.probe()
    burner.get_capacity()
    empty = tmp_path / "empty.img"
    empty.write_bytes(b"")

    with pytest.raises(ValueError):
        write_images([(0x0, empty)], burner)

    assert burner.dev.sessions == []


def test_write_beyond_capacity_is_refused_before_transferring(tmp_path, burner):
    """The kdimg path checked capacity; the raw [address, file] path did not, so
    an oversized image failed as an opaque protocol timeout instead."""
    burner.probe()
    burner.get_capacity()
    img = tmp_path / "huge.img"
    img.write_bytes(b"\x44" * 4096)

    with pytest.raises(RuntimeError) as exc:
        write_images([(burner.capacity - 512, img)], burner)

    assert "容量" in str(exc.value)
    assert burner.dev.sessions == [], "nothing should have been sent"


# --- command framing ----------------------------------------------------------


def test_send_cmd_frames_a_60_byte_packet(burner):
    burner.dev.queue_response(make_packet(0x10, data=b"x" * 16))

    burner.send_cmd(0x10, b"\x02\xff", expected_response_length=16)

    endpoint, packet = burner.dev.written[0]
    assert endpoint == UBOOT_EP_OUT
    assert len(packet) == 60
    cmd, result, size = struct.unpack("<HHH", packet[:6])
    assert (cmd, result, size) == (0x10, 0, 2)
    assert packet[6:8] == b"\x02\xff"


def test_send_cmd_rejects_oversized_payload(burner):
    with pytest.raises(ValueError):
        burner.send_cmd(0x10, b"x" * 55, expected_response_length=0)


def test_send_cmd_surfaces_the_device_error_message(burner):
    """On failure the device explains itself in the data area ("DATA SIZE
    EXCEED", "PROBE FAILED", ...). That used to be discarded in favour of a bare
    result code plus a guess about the storage medium."""
    burner.dev.queue_response(make_packet(KBURN_CMD_WRITE_LBA, fake_usb.KBURN_RESULT_ERROR_MSG, b"DATA SIZE EXCEED"))

    with pytest.raises(USBCommunicationError) as exc:
        burner.send_cmd(KBURN_CMD_WRITE_LBA, b"\x00" * 32, expected_response_length=8)

    assert "DATA SIZE EXCEED" in str(exc.value)


def test_send_cmd_raises_on_unexpected_response_length(burner):
    burner.dev.queue_response(make_packet(0x10, data=b"short"))

    with pytest.raises(USBCommunicationError):
        burner.send_cmd(0x10, b"\x02\xff", expected_response_length=16)


def test_probe_failure_explains_that_the_host_cannot_recover(burner):
    """When medium init fails the loader stops serving both endpoints, so the
    user has to power-cycle. A bare 'Operation timed out' gives them nothing."""
    from k230_flash.burners import handle_uboot_mode

    burner.dev.read = lambda *a, **k: (_ for _ in ()).throw(usb.core.USBTimeoutError("timed out"))

    with pytest.raises(RuntimeError) as exc:
        handle_uboot_mode(
            dev=burner.dev,
            media_type="SDCARD",
            auto_reboot=False,
            progress_callback=None,
            addr_filename_pairs=[],
        )

    message = str(exc.value)
    assert "SDCARD" in message
    assert "media-type" in message or "介质" in message
