# Tests

Two suites, split by what they need to run.

| Suite | Needs | When it runs |
|---|---|---|
| `tests/pc/` | nothing but Python | every push and PR, on Linux/Windows/macOS |
| `tests/hardware/` | a real K230 on a board-control rig | manually, on a self-hosted runner |

```bash
pytest                          # PC tests only (hardware is deselected by default)
pytest --hardware -m hardware   # hardware tests only
pytest --hardware               # everything
```

Hardware tests are deselected by `addopts` in `pyproject.toml`. Passing
`--hardware` re-enables them; without a configured rig they **skip** rather than
fail, so a half-provisioned machine reports honestly instead of going red.

## PC tests

USB is faked (`tests/helpers/fake_usb.py`), which is what makes the interesting
parts testable without a board:

- `FakeDevice` exposes **different endpoints per stage** — BootROM `OUT 0x01`,
  U-Boot `OUT 0x02`. That difference is the entire reason the handoff was broken,
  so the fake models it rather than pretending endpoints are stable.
- `FakeKburnDevice` answers commands like the real gadget: it opens a write
  session on `WRITE_LBA`, counts the payload bytes that follow, and only then
  sends `WRITE DONE`. A host that stops waiting for that acknowledgement fails
  here.
- `patch_find()` scripts what `usb.core.find` returns, including "device gone"
  and "device back at the same address", so the re-enumeration window can be
  reproduced deterministically.

### The board simulator

`tests/helpers/board_simulator.py` goes further than the fakes above: it models a
whole board and is driven through the **public API**, with nothing patched out.

- **Both stages.** It starts in BootROM, accepts the loader upload over EP0, and
  on `EP0_PROG_START` *becomes* the U-Boot stage — new address, new bulk
  endpoints. The BootROM half previously had no coverage at all, because every
  test had to patch `handle_bootrom_mode` away.
- **A storage medium.** Writes land in a sparse buffer tests read back, so a
  flash is verified byte-for-byte at the right offsets rather than just "did not
  raise". A partition written to the wrong offset fails here.
- **Fault injection** (`Faults`): probe failure, write failure, a loader that
  never starts, a too-small medium, and the wedged-gadget defect where the
  device stops answering both endpoints.

**What it cannot do.** It replaces pyusb, so nothing below that line is
simulated. The worst bug this project has had — libusb serving a *stale
configuration descriptor* after re-enumeration on Windows — is invisible here by
construction, and was only ever caught on real Windows hardware. The simulator
widens coverage; it does not remove the need for the one board.

`tests/helpers/kdimg_builder.py` generates `.kdimg` containers in memory. The
kdimage tests used to ask for hand-supplied sample files and skipped themselves
when they were missing; generating the images keeps binaries out of the repo and
lets each test assert exact offsets, because it built them.

## Hardware tests

Configured entirely through environment variables, so a runner is pointed at its
own rig without editing tests:

| Variable | Meaning |
|---|---|
| `K230_TEST_PORT` | USB path of the board in download mode, e.g. `1-5.3.2` (required) |
| `K230_TEST_MEDIA` | storage media, default `SDCARD` |
| `K230_BOARD_SCRIPTS` | directory containing the rig's `board.py` |
| `K230_BOARD_NAME` | board entry in that tooling's `config.yaml` |
| `K230_OWNER` | lease owner. **Required on Windows**, where `board.py` otherwise dies in `os.getsid()` |

Example:

```bash
export K230_TEST_PORT=1-5.3.2
export K230_TEST_MEDIA=SDCARD
export K230_BOARD_SCRIPTS=~/.config/opencode/skills/k230/scripts
export K230_BOARD_NAME=board-for-tester-1
export K230_OWNER=me
pytest --hardware -m hardware -v
```

**`tests/hardware/test_flash_roundtrip.py` is destructive** — it overwrites the
board's storage. Only point `K230_TEST_PORT` at a board you can afford to erase.

### The one tolerated device fault

The loader's medium init runs synchronously inside the USB completion handler.
When it fails, the gadget stops serving *both* endpoints, so the host cannot
recover it — only a power cycle can. Flash tests therefore go through the
`flash_with_retry` fixture, which retries past **only** that documented fault
(`tests/helpers/known_faults.py`) and lets everything else through. The retry
count is recorded per test, so a rising trend stays visible instead of being
silently absorbed.

Without it these tests would go red roughly half the time for a reason unrelated
to the code under test, which is the fastest way to teach people to ignore CI.

## How many boards do you actually need?

**One.** Not one per storage type.

Only two things in the host depend on the media type, and both are dict lookups:
which loader binary gets pushed, and which byte goes into `DEV_PROBE`.
`part_flags` is hardcoded to `0` — the host never sends media-specific write
flags, not even SPI NAND's OOB flag. Everything else that differs per medium
happens *inside the loader*, on the device.

So a second board exercises the same host code path as the first. Both lookups
are covered by `tests/pc/test_media_matrix.py`, which also checks that all three
loader binaries ship, are readable, and carry the expected u-boot provenance
string — none of which needs hardware.

| Change you made | What to run |
|---|---|
| Host code (the usual case) | PC tests + the one board you keep wired |
| Rebuilt a loader binary | PC tests + **borrow** a board per affected loader |
| Packaging / release | PC tests + one board smoke test |

Note eMMC and SDCARD **share** `loader_mmc.bin`, so an eMMC board adds almost
nothing over an SD one. Three loaders exist, but only two risk classes:
MMC-family and SPI-family.

Borrowing boards for a loader rebuild is worth it because that is the one change
PC tests genuinely cannot cover: whether that binary works against real silicon.
Everything else — handoff, protocol framing, streaming, error paths — is
identical regardless of what the medium is.

## Setting up a self-hosted runner

The `hardware` job in `.github/workflows/tests.yml` targets a runner labelled
`self-hosted, k230-rig` and only runs on `workflow_dispatch`. To enable it:

1. Register a self-hosted runner on the machine wired to the board and give it
   the `k230-rig` label.
2. Set repository variables `K230_TEST_PORT`, `K230_TEST_MEDIA`,
   `K230_BOARD_SCRIPTS`, `K230_BOARD_NAME` — kept out of the repo so the rig's
   wiring is not hard-coded here.
3. Make sure the runner can access USB (udev rule on Linux, WinUSB via Zadig on
   Windows) and the board-control tooling.
