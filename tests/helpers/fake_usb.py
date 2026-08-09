"""A fake pyusb device that speaks enough of the K230 protocol to test on a PC.

The two stages of a flash are exactly where the bugs live -- the BootROM to
U-Boot handoff, endpoint rediscovery, and the kburn request/response pairing --
and all of it used to be reachable only with a board on the bench. These fakes
model the parts that matter:

  * BootROM and U-Boot expose *different* bulk endpoints (OUT 0x01 vs OUT 0x02),
    which is the whole reason endpoints must be re-read after the handoff.
  * The gadget answers every command with a 60-byte packet whose `cmd` field is
    the request or'd with 0x8000, so a response left unread desynchronises
    everything that follows.

Anything not needed by the code under test is deliberately absent, so a fake
that drifts out of step with pyusb fails loudly rather than quietly passing.
"""

import struct

import usb.core

# --- protocol constants (mirrored from burners.py so a change there shows up) ---
PACKET_SIZE = 60
HEADER_SIZE = 6
MAX_DATA_SIZE = PACKET_SIZE - HEADER_SIZE
CMD_FLAG_DEV_TO_HOST = 0x8000
KBURN_RESULT_OK = 0x1
KBURN_RESULT_ERROR_MSG = 0xFF

CMD_NONE = 0x00
CMD_REBOOT = 0x01
CMD_DEV_PROBE = 0x10
CMD_DEV_GET_INFO = 0x11
CMD_WRITE_LBA = 0x21

BROM_EP_OUT, BROM_EP_IN = 0x01, 0x81
UBOOT_EP_OUT, UBOOT_EP_IN = 0x02, 0x81

EP0_GET_CPU_INFO = 0


class FakeEndpoint:
    def __init__(self, address, bulk=True):
        self.bEndpointAddress = address
        # low two bits of bmAttributes are the transfer type; 2 == bulk
        self.bmAttributes = 2 if bulk else 3


class FakeInterface:
    def __init__(self, endpoints, protocol=0):
        self._endpoints = endpoints
        self.bInterfaceProtocol = protocol

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfiguration:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class _FakeBackendDevice:
    """Stands in for pyusb's backend device wrapper.

    release_device() finalizes this explicitly, because the real one holds a
    libusb device pointer but not its context.
    """

    def __init__(self):
        self.finalize_calls = 0

    def finalize(self):
        self.finalize_calls += 1


class _FakeCtx:
    def __init__(self):
        self.dev = _FakeBackendDevice()


class FakeDevice:
    """Minimal usb.core.Device stand-in.

    `mode` drives what EP0 reports and which endpoints the descriptor exposes,
    so a test can hand back a BootROM device and then a U-Boot one and check the
    caller notices the difference.
    """

    def __init__(self, mode="uboot", bus=1, address=1, ports=(5, 3, 2), ep0_error=False):
        self.mode = mode
        self.bus = bus
        self.address = address
        self.port_numbers = tuple(ports)
        self.idVendor = 0x29F1
        self.idProduct = 0x0230
        self.iSerialNumber = 0
        self.ep0_error = ep0_error

        self._ctx = _FakeCtx()
        self.disposed = False
        self.set_configuration_calls = 0
        self.reset_calls = 0
        self.written = []  # list of (endpoint, bytes)
        self._read_queue = []  # responses the host will read back

    # -- descriptor ---------------------------------------------------------
    @property
    def endpoints(self):
        return (UBOOT_EP_OUT, UBOOT_EP_IN) if self.mode == "uboot" else (BROM_EP_OUT, BROM_EP_IN)

    def get_active_configuration(self):
        out, in_ = self.endpoints
        protocol = 0 if self.mode == "uboot" else 80
        return FakeConfiguration([FakeInterface([FakeEndpoint(out), FakeEndpoint(in_)], protocol)])

    def set_configuration(self, *args, **kwargs):
        self.set_configuration_calls += 1

    def reset(self):
        self.reset_calls += 1

    # -- transfers ----------------------------------------------------------
    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        if self.ep0_error:
            raise usb.core.USBError("fake EP0 failure")
        if bRequest == EP0_GET_CPU_INFO:
            text = b"Uboot Stage for K230" if self.mode == "uboot" else b"K230"
            return array_like(text)
        return 0

    def write(self, endpoint, data, timeout=None):
        payload = bytes(data)
        self.written.append((endpoint, payload))
        self._on_write(endpoint, payload)
        return len(payload)

    def read(self, endpoint, size, timeout=None):
        if not self._read_queue:
            raise usb.core.USBTimeoutError("fake: nothing queued to read")
        return array_like(self._read_queue.pop(0))

    # -- hooks for subclasses ----------------------------------------------
    def _on_write(self, endpoint, payload):
        pass

    def queue_response(self, raw):
        self._read_queue.append(raw)


def array_like(data):
    """pyusb hands back an array('B', ...); bytes() over it must give the payload."""
    import array

    return array.array("B", data)


def make_packet(cmd, result=KBURN_RESULT_OK, data=b""):
    """Build a 60-byte device->host response packet."""
    header = struct.pack("<HHH", cmd | CMD_FLAG_DEV_TO_HOST, result, len(data))
    return header + data.ljust(MAX_DATA_SIZE, b"\x00")


class FakeKburnDevice(FakeDevice):
    """A U-Boot-stage device that actually answers kburn commands.

    Enough of the state machine to drive K230UBOOTBurner end to end: it tracks a
    write session opened by WRITE_LBA, counts the payload bytes that follow, and
    only then answers "WRITE DONE" -- so a test can prove the host waits for that
    acknowledgement instead of assuming success.
    """

    def __init__(self, capacity=16 * 1024**3, blk_size=512, chunk_size=131072, write_should_fail=False, **kwargs):
        super().__init__(mode="uboot", **kwargs)
        self.capacity = capacity
        self.blk_size = blk_size
        self.chunk_size = chunk_size
        self.write_should_fail = write_should_fail

        self.expecting = 0  # payload bytes still owed by the host
        self.write_offset = None
        self.received = b""  # payload accumulated for the current session
        self.sessions = []  # (offset, size, payload) per completed write

    def _on_write(self, endpoint, payload):
        if self.expecting > 0:
            self.received += payload
            self.expecting -= len(payload)
            if self.expecting <= 0:
                if self.write_should_fail:
                    self.queue_response(make_packet(CMD_WRITE_LBA, KBURN_RESULT_ERROR_MSG, b"WRITE ERROR, 0x5"))
                else:
                    self.sessions.append((self.write_offset, len(self.received), self.received))
                    self.queue_response(make_packet(CMD_WRITE_LBA, KBURN_RESULT_OK, b"WRITE DONE"))
                self.received = b""
                self.expecting = 0
            return

        if len(payload) != PACKET_SIZE:
            return  # not a command packet; ignore

        cmd, _result, size = struct.unpack("<HHH", payload[:HEADER_SIZE])
        body = payload[HEADER_SIZE : HEADER_SIZE + size]

        if cmd == CMD_NONE:
            # The gadget has no handler for this and replies with a fixed
            # 16-byte string, which the host relies on as a liveness probe.
            self.queue_response(make_packet(CMD_NONE, KBURN_RESULT_ERROR_MSG, b"NOT SUPPORT FUNC"))
        elif cmd == CMD_DEV_PROBE:
            self.queue_response(make_packet(CMD_DEV_PROBE, KBURN_RESULT_OK, struct.pack("<QQ", self.chunk_size, 32768)))
        elif cmd == CMD_DEV_GET_INFO:
            bitfields = (1 << 47) | (0 << 40) | (0 << 32) | 1000
            info = struct.pack("<QQQQ", self.capacity, self.blk_size, self.blk_size, bitfields)
            self.queue_response(make_packet(CMD_DEV_GET_INFO, KBURN_RESULT_OK, info))
        elif cmd == CMD_WRITE_LBA:
            offset, size_, _max, _flag = struct.unpack("<QQQQ", body)
            self.write_offset = offset
            self.expecting = size_
            self.received = b""
            self.queue_response(make_packet(CMD_WRITE_LBA, KBURN_RESULT_OK, b"START DL"))
        elif cmd == CMD_REBOOT:
            pass  # reboot expects no response


def patch_find(monkeypatch, devices):
    """Point usb.core.find at `devices`.

    Three shapes, in increasing order of control:
      [dev, ...]        -- returned on every call
      [[dev], [], ...]  -- scripted per successive call, last entry repeats
      callable          -- called per lookup, returns the current device list

    Prefer the callable when the test depends on *state* rather than on a
    particular number of lookups: polling loops call find() a
    timing-dependent number of times, so a positional script can desynchronise
    on a slow machine and make the test flaky.
    """
    if callable(devices):
        provider = devices
    elif devices and isinstance(devices[0], list):
        sequence = list(devices)

        def provider(_state={"n": 0}):
            idx = min(_state["n"], len(sequence) - 1)
            _state["n"] += 1
            return sequence[idx]

    else:
        fixed = list(devices)

        def provider():
            return fixed

    calls = {"n": 0}

    def fake_find(*args, find_all=False, **kwargs):
        calls["n"] += 1
        found = list(provider())
        return iter(found) if find_all else (found[0] if found else None)

    monkeypatch.setattr(usb.core, "find", fake_find)
    return calls
