"""A simulated K230 that speaks the whole flashing protocol, both stages.

`fake_usb.FakeKburnDevice` is a unit-level stand-in: it answers kburn commands
but is always already in U-Boot stage, and it throws payload bytes away. This
simulator goes further and models the parts that were previously only reachable
with a board on the bench:

  * **Both stages.** It starts in BootROM, accepts the loader upload over EP0,
    and on EP0_PROG_START *becomes* the U-Boot stage -- new bus address, new
    bulk endpoints (OUT 0x01 -> 0x02). That is the transition that used to fail
    8 times out of 10, and it was previously untestable without hardware:
    `handle_bootrom_mode` had to be monkeypatched away entirely.
  * **A storage medium.** Writes land in a sparse buffer that tests read back,
    so a flash can be verified byte-for-byte at the right offsets instead of
    merely "did not raise".
  * **Fault injection.** Probe failures, write failures and dead endpoints are
    configurable, so error paths get exercised deliberately rather than by luck.

What it deliberately cannot do: this replaces pyusb, so it cannot reproduce
anything in libusb itself. The worst bug this project has had -- libusb serving
a stale configuration descriptor after re-enumeration on Windows -- lives
strictly below this layer and is invisible here. That is why the hardware suite
still exists. See tests/README.md.
"""

import struct

import usb.core

from .fake_usb import (
    CMD_DEV_GET_INFO,
    CMD_DEV_PROBE,
    CMD_NONE,
    CMD_REBOOT,
    CMD_WRITE_LBA,
    HEADER_SIZE,
    KBURN_RESULT_ERROR_MSG,
    KBURN_RESULT_OK,
    PACKET_SIZE,
    FakeConfiguration,
    FakeEndpoint,
    FakeInterface,
    _FakeCtx,
    array_like,
    make_packet,
)

EP0_GET_CPU_INFO = 0
EP0_SET_DATA_ADDRESS = 1
EP0_SET_DATA_LENGTH = 2
EP0_PROG_START = 4

BROM_EP_OUT, BROM_EP_IN = 0x01, 0x81
UBOOT_EP_OUT, UBOOT_EP_IN = 0x02, 0x81


class Faults:
    """Which failures the simulated board should exhibit.

    Defaults are all-healthy; a test turns on exactly the one it is about.
    """

    def __init__(
        self,
        probe_fails=False,
        write_fails=False,
        dead_after_probe=False,
        loader_never_starts=False,
        capacity=16 * 1024**3,
    ):
        # The loader cannot find the medium -- "no suitable MMC/SD device".
        self.probe_fails = probe_fails
        # The medium rejects the data mid-write.
        self.write_fails = write_fails
        # Reproduces the known device defect: after a failed probe the gadget
        # stops serving *both* endpoints, so the host cannot even reboot it.
        self.dead_after_probe = dead_after_probe
        # boot_from is accepted but the chip stays in BootROM.
        self.loader_never_starts = loader_never_starts
        self.capacity = capacity


class SimulatedK230:
    """A K230 that can be flashed end to end.

    Present it to the code under test with `install(monkeypatch, sim)`.
    """

    def __init__(self, faults=None, blk_size=512, chunk_size=131072, bus=1, ports=(5, 3, 2)):
        self.faults = faults or Faults()
        self.blk_size = blk_size
        self.chunk_size = chunk_size
        self.bus = bus
        self.port_numbers = tuple(ports)

        self.stage = "brom"
        self.address = 95
        self.idVendor, self.idProduct = 0x29F1, 0x0230
        self.iSerialNumber = 0

        self._ctx = _FakeCtx()
        self.set_configuration_calls = 0
        self.reset_calls = 0

        # BootROM stage state
        self.load_address = None
        self.loader_bytes = b""

        # U-Boot stage state
        self._read_queue = []
        self._expecting = 0
        self._write_offset = None
        self._probed = False
        self._dead = False

        # the "medium": sparse, so a 16 GiB capacity costs nothing
        self.storage = {}
        self.writes = []  # (offset, length) per completed session

    # -- descriptor ---------------------------------------------------------
    @property
    def endpoints(self):
        return (UBOOT_EP_OUT, UBOOT_EP_IN) if self.stage == "uboot" else (BROM_EP_OUT, BROM_EP_IN)

    @property
    def port_path(self):
        return f"{self.bus}-" + ".".join(str(p) for p in self.port_numbers)

    def get_active_configuration(self):
        out, in_ = self.endpoints
        protocol = 0 if self.stage == "uboot" else 80
        return FakeConfiguration([FakeInterface([FakeEndpoint(out), FakeEndpoint(in_)], protocol)])

    def set_configuration(self, *args, **kwargs):
        self.set_configuration_calls += 1

    def reset(self):
        self.reset_calls += 1

    # -- EP0 ----------------------------------------------------------------
    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        if self._dead:
            raise usb.core.USBTimeoutError("simulated: gadget wedged, EP0 unresponsive")

        if bRequest == EP0_GET_CPU_INFO:
            text = b"Uboot Stage for K230" if self.stage == "uboot" else b"K230"
            return array_like(text)

        if bRequest == EP0_SET_DATA_ADDRESS:
            self.load_address = (wValue << 16) | wIndex
            self.loader_bytes = b""
            return 0

        if bRequest == EP0_PROG_START:
            self._start_loader()
            return 0

        return 0

    def _start_loader(self):
        """Model the re-enumeration: the chip comes back as a different device."""
        if self.faults.loader_never_starts:
            return
        if not self.loader_bytes:
            raise AssertionError("boot_from issued but no loader was uploaded")
        self.stage = "uboot"
        # A new bus address, as Linux does. (Windows reuses the old one; that
        # difference lives in libusb and is out of reach here.)
        self.address += 1
        self._read_queue.clear()

    # -- bulk ---------------------------------------------------------------
    def write(self, endpoint, data, timeout=None):
        payload = bytes(data)
        if self._dead:
            raise usb.core.USBTimeoutError("simulated: gadget wedged, OUT endpoint unresponsive")

        if self.stage == "brom":
            # BootROM has no command protocol -- everything on the OUT endpoint
            # is loader image data.
            self.loader_bytes += payload
            return len(payload)

        if self._expecting > 0:
            self._absorb_payload(payload)
            return len(payload)

        if len(payload) == PACKET_SIZE:
            self._handle_command(payload)
        return len(payload)

    def read(self, endpoint, size, timeout=None):
        if self._dead:
            raise usb.core.USBTimeoutError("simulated: gadget wedged, IN endpoint unresponsive")
        if not self._read_queue:
            raise usb.core.USBTimeoutError("simulated: nothing to read")
        return array_like(self._read_queue.pop(0))

    # -- protocol -----------------------------------------------------------
    def _handle_command(self, packet):
        cmd, _result, size = struct.unpack("<HHH", packet[:HEADER_SIZE])
        body = packet[HEADER_SIZE : HEADER_SIZE + size]

        if cmd == CMD_NONE:
            self._reply(CMD_NONE, KBURN_RESULT_ERROR_MSG, b"NOT SUPPORT FUNC")

        elif cmd == CMD_DEV_PROBE:
            if self.faults.probe_fails:
                if self.faults.dead_after_probe:
                    # The real defect: medium init runs inside the USB completion
                    # handler, so a failure takes the whole gadget down with it.
                    self._dead = True
                    return
                self._reply(CMD_DEV_PROBE, KBURN_RESULT_ERROR_MSG, b"PROBE FAILED")
                return
            self._probed = True
            self._reply(CMD_DEV_PROBE, KBURN_RESULT_OK, struct.pack("<QQ", self.chunk_size, 32768))

        elif cmd == CMD_DEV_GET_INFO:
            if not self._probed:
                self._reply(CMD_DEV_GET_INFO, KBURN_RESULT_ERROR_MSG, b"MEDIUM INFO INVALID")
                return
            bitfields = (1 << 47) | 1000
            info = struct.pack("<QQQQ", self.faults.capacity, self.blk_size, self.blk_size, bitfields)
            self._reply(CMD_DEV_GET_INFO, KBURN_RESULT_OK, info)

        elif cmd == CMD_WRITE_LBA:
            offset, length, _max, _flag = struct.unpack("<QQQQ", body)
            if offset + length > self.faults.capacity:
                self._reply(CMD_WRITE_LBA, KBURN_RESULT_ERROR_MSG, b"DATA SIZE EXCEED")
                return
            self._write_offset = offset
            self._expecting = length
            self._buffer = b""
            self._reply(CMD_WRITE_LBA, KBURN_RESULT_OK, b"START DL")

        elif cmd == CMD_REBOOT:
            self.stage = "brom"
            self.address += 1
            self._probed = False

    def _absorb_payload(self, payload):
        self._buffer += payload
        self._expecting -= len(payload)
        if self._expecting > 0:
            return

        if self.faults.write_fails:
            self._reply(CMD_WRITE_LBA, KBURN_RESULT_ERROR_MSG, b"WRITE ERROR, 0x5")
        else:
            self.storage[self._write_offset] = self._buffer
            self.writes.append((self._write_offset, len(self._buffer)))
            self._reply(CMD_WRITE_LBA, KBURN_RESULT_OK, b"WRITE DONE")
        self._buffer = b""
        self._expecting = 0

    def _reply(self, cmd, result, data):
        self._read_queue.append(make_packet(cmd, result, data))

    # -- assertions for tests ----------------------------------------------
    def read_back(self, offset):
        """Bytes written at `offset`, or None if nothing was written there."""
        return self.storage.get(offset)

    @property
    def total_bytes_written(self):
        return sum(length for _offset, length in self.writes)


def install(monkeypatch, sim):
    """Present `sim` to the code under test as the only K230 on the bus."""

    def fake_find(*args, find_all=False, **kwargs):
        found = [sim]
        return iter(found) if find_all else found[0]

    monkeypatch.setattr(usb.core, "find", fake_find)
    return sim
