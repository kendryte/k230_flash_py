<div align="center">

# K230 Flash Tool (Python)

[**English**](README.md) | [**简体中文**](docs/cn/README.md)
</div>

This is a cross-platform Kendryte K230 chip firmware flashing tool written in Python. It provides command-line tools (CLI), graphical user interface (GUI), and programmable Python API for flashing firmware to K230 devices via USB.

This project aims to provide K230 chip users with a feature-rich, high-performance, cross-platform, and easily extensible firmware flashing tool.

---

## ✨ Features

- **Device Discovery**: List all currently connected K230 USB devices and their paths.
- **Multiple Media Types**: Support flashing to different storage media like `EMMC`, `SDCARD`, `SPI_NAND`, `SPI_NOR`, and automatically select corresponding loaders.
- **Flexible Flashing Methods**:
  - Support flashing complete `.kdimg` firmware packages.
  - Support `.kdimg` address command-line override.
  - Support flashing multiple independent `.img` files to specified memory addresses.
  - Support automatic extraction and flashing of compressed image files (gz, tgz, zip).
- **Progress and Speed Display**: Provide real-time progress bars displayed during flashing.
- **Cross-platform**: Based on Python and `pyusb`, runs on Windows, Linux, macOS.
- **Multiple Usage Methods**:
  - **Command-line Tool**: Provides simple and easy-to-use command-line interface, suitable for terminal users and automation scripts.
  - **Python Library**: Can be imported as a third-party library into your own Python applications to implement customized flashing logic.
  - **GUI Tool**: Integrated `K230_flash_GUI` tool with source code for user reference and customization.

---

## 🔌 Driver Setup

Before using `k230-flash`, please ensure that the K230 device is in flashing mode and the operating system has properly installed USB drivers.

### How to put K230 device into flashing mode?

First, hold down the boot button on the K230 device, then insert the USB cable to connect the K230 device to the computer. For Windows, you will see `K230 USB Boot Device` displayed under `Universal Serial Bus devices` in `Device Manager`, which indicates that K230 is in flashing mode and ready for subsequent operations.

### Windows

When using for the first time, you may need to install **WinUSB driver** for the K230 device. It's recommended to use the [Zadig](https://zadig.akeo.ie/) tool:

1. Download and run Zadig (no installation required).
2. Check **Options → List All Devices** in the menu.
3. Select `K230 USB Boot Device` from the dropdown list (or shown as `Unknown Device`, Vendor ID: `29f1`, Product ID: `0230`).
4. Select **WinUSB** driver on the right side.
5. Click **Install Driver** and wait for completion.

After completion, Windows will be able to recognize the device, and the `k230-flash` tool can be used normally.

### Linux (Ubuntu / Debian)

Linux has built-in **usbfs/libusb** drivers by default, usually no additional installation is required.
But you need to configure **udev rules** for non-root users, otherwise you may need to use `sudo` to execute commands.

1. Create rule file `/etc/udev/rules.d/99-k230.rules`:

```bash
SUBSYSTEM=="usb", ATTRS{idVendor}=="29f1", ATTRS{idProduct}=="0230", MODE="0666"
```

2. Apply rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

3. Unplug and reinsert the K230 device.

After completion, regular users can run `k230-flash` directly without `sudo`.

---

### macOS

macOS comes with libusb drivers built-in, usually no additional operations are required.
If permission issues occur, try using `sudo` to run, or ensure the latest libusb is installed via [brew](https://brew.sh/):

```bash
brew install libusb
```

---

## 🚀 Quick Start

### 1. Install Tool

Install from PyPI:

```bash
pip install k230-flash
```

### 2. List Devices

Ensure the K230 device is connected to the computer via USB, then run the following command to check if the device is properly recognized:

```bash
k230-flash --list-devices
```

If the device is connected, you will see output similar to the following:

```json
[
    {
        "bus": 1,
        "address": 5,
        "port_path": "1-5.1",
        "vid": 10737,
        "pid": 560
    }
]
```

---

## 📖 Usage

The tool supports three flashing modes.

### Mode 1: Flash Complete `.kdimg` File Package

This is the simplest mode. Just pass the `.kdimg` file as a parameter.

```bash
k230-flash -m SDCARD /path/to/your/firmware.kdimg
```

### Mode 2: Flash Independent `.img` Files

You can specify a series of `[address, file path]` pairs to flash different `.img` files to different locations on the media.

```bash
# Format: k230-flash [address1] [file1] [address2] [file2] ...
k230-flash -m SDCARD 0x000000 uboot.img 0x400000 rtt.img
```

### Mode 3: Flash Only Selected Partitions of a `.kdimg`

Use `--kdimg-select` to write just some of the partitions in a `.kdimg`, leaving the rest of the device untouched. Handy for updating only U-Boot, and much faster than rewriting the whole package.

```bash
k230-flash -m SDCARD firmware.kdimg --kdimg-select uboot_spl_a uboot_a
```

> The `.img` / `.kdimg` you pass may also be a `.zip` / `.gz` / `.tar.gz` / `.tgz` archive — it is extracted automatically and the first image inside is used.

### Full Option Reference

| Option | Default | Description |
|---|---|---|
| `-l, --list-devices` | — | List connected K230 devices and exit |
| `-d, --device-path` | first device found | USB port path (e.g. `1-5.3.2`). When given, the tool waits for that device to appear |
| `-m, --media-type` | `EMMC` | Target media: `EMMC` / `SDCARD` / `SPI_NAND` / `SPI_NOR` / `OTP`. Case, separators and abbreviations are accepted — `spi-nand`, `spinand`, `nand` all mean `SPI_NAND`; `sd` means `SDCARD`. `OTP` needs `-lf`, see note below |
| `--kdimg-select` | — | Flash only the named partitions from a `.kdimg` (accepts several) |
| `-lf, --loader-file` | built-in loader | Path to a custom loader binary |
| `-la, --loader-address` | `0x80360000` | Loader load address |
| `--auto-reboot` | off | Reboot the device once flashing completes |
| `--device-timeout` | `300` | With `-d`, how long to wait for the device to appear (seconds) |
| `--device-retry-interval` | `1` | Polling interval while waiting for the device (seconds) |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |

Common examples:

```bash
# Pick a specific board when several are connected
k230-flash -d "1-5" firmware.kdimg

# Flash to SPI NOR (the matching loader is selected automatically)
k230-flash --media-type SPI_NOR firmware.kdimg

# Use a custom loader
k230-flash --loader-file my_loader.bin --loader-address 0x80360000 firmware.kdimg

# Verbose logging when troubleshooting
k230-flash --log-level DEBUG -m SDCARD firmware.kdimg
```

The package is also runnable without installing an entry point:

```bash
python -m k230_flash --list-devices
```

### Exit Codes and Error Reporting

The tool is meant to be scriptable, so failures are reported through the exit
code rather than only in the log:

| Code | Meaning |
|---|---|
| `0` | Flash completed successfully |
| `1` | The flash failed (device not found, wrong media, image too large, device reported a write error, …) |
| `2` | The command line was rejected (bad option, missing file, unknown media type) |
| `130` | Interrupted with Ctrl-C |

Arguments are validated **before** the tool starts waiting for a device, so a
mistyped path or media type fails immediately instead of after the device
timeout. Failures print a single-line reason rather than a Python traceback.

### Accepted Media Names

`-m` is matched on the separator-free, upper-case form of what you type, so
case and `-`/`_`/space differences never matter. On top of that a few
abbreviations are accepted:

| Canonical | Also accepted |
|---|---|
| `EMMC` | `emmc` |
| `SDCARD` | `sdcard`, `sd` |
| `SPI_NAND` | `spi-nand`, `spinand`, `spi nand`, `nand` |
| `SPI_NOR` | `spi-nor`, `spinor`, `spi nor`, `nor` |
| `OTP` | `otp` |

`MMC` is deliberately **not** accepted. eMMC and SD share a loader but send
different probe bytes, so either guess would be wrong half the time and fail on
the board with a confusing "no suitable device"; you get
`did you mean EMMC?` instead. Anything unrecognised is still rejected, with a
suggestion where one is close enough.

The same normalisation is used by the CLI, the library API and the burners, so
`k230-flash -m nand` and `flash_kdimg(media_type="nand")` cannot disagree.

### A Note on `OTP`

`OTP` is a valid target for a loader that is already running, but no OTP loader
ships with the tool, so it cannot be reached from BootROM with `-m OTP` alone —
pass `-lf/--loader-file` with a loader that supports it.

### What Happens During Flashing

Knowing the flow makes the logs and any errors much easier to read — flashing runs in two stages:

1. The device powers up in flashing mode running the chip's built-in **BootROM**, which can only receive a small piece of code and cannot access storage media on its own.
2. The tool pushes a **loader** (a trimmed-down U-Boot) matching your target media into chip memory and starts it.
3. Starting the loader makes the device **re-enumerate on USB**. The tool waits for this and re-detects the device automatically — typically under a second, no user action needed.
4. Through the loader, the tool probes the media, reads its capacity, and writes the firmware while showing live progress.
5. With `--auto-reboot`, the device restarts into normal boot once writing finishes.

So a log line about waiting for the device to switch to U-Boot mode is expected. If it stalls at media probing (the error suggests checking `-m`), the media type usually doesn't match the actual hardware, or the media isn't seated properly.

---

## 📦 Using as a Library

You can easily integrate the functionality of this tool into your own Python scripts.

```python
import sys
from loguru import logger
from k230_flash import flash_kdimg, flash_addr_file_pairs, list_devices

# Configure logging to see detailed output. The library never reconfigures
# logging itself, so this is the only place log levels are decided.
logger.remove()
logger.add(sys.stderr, level="INFO")

def main():
    try:
        # List devices
        print("Connected devices:")
        print(list_devices())

        # Flash .kdimg file
        logger.info("Flashing kdimg file...")
        flash_kdimg(
            kdimg_file="/path/to/your/firmware.kdimg",
            media_type="EMMC",
            auto_reboot=True
        )
        logger.info("kdimg flash completed.")

        # Flash independent .img files
        logger.info("Flashing individual image files...")
        image_pairs = [
            (0x000000, "/path/to/uboot.img"),
            (0x400000, "/path/to/rtt.img")
        ]
        flash_addr_file_pairs(
            addr_filename_pairs=image_pairs,
            media_type="SDCARD"
        )
        logger.info("Image files flash completed.")

    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
```

Notes on the library API:

- Paths may be `str` or `pathlib.Path`; both are accepted everywhere.
- Arguments are validated before any hardware is touched — an unknown
  `media_type`, a missing file or an empty `addr_filename_pairs` raises
  immediately rather than after the loader has been pushed to the board.
- `list_devices()` returns pre-serialised JSON because the CLI prints it
  verbatim. Use `k230_flash.api.find_devices()` to get a list of dicts instead.
- The `log_level` argument these functions used to accept never had any effect
  and is deprecated; configure loguru yourself as shown above.

---

## 📦 GUI Tool

In addition to the command-line tool and Python library, this project also provides a feature-complete graphical user interface tool **K230 Flash GUI**, allowing users to perform firmware flashing operations through an intuitive interface.

<img src="https://raw.githubusercontent.com/kendryte/k230_flash_py/main/src/gui/images/single_flash_mode.png" width="600">

### 📥 Download and Installation

You can download the latest version of pre-compiled executable files from the [GitHub Releases](https://github.com/kendryte/k230_flash_py/releases) page. After downloading, run directly without installing Python environment.

On Linux the GUI ships as a single `.AppImage`; make it executable and run it:

```bash
chmod +x k230_flash_gui-linux-x86_64-*.AppImage
./k230_flash_gui-linux-x86_64-*.AppImage
```

It needs FUSE to mount itself, which every desktop install has (`fuse3`; note
that `libfuse2` is *not* required). On a headless server, in a container, or
anywhere mounting is not permitted, use the CLI instead — `pip install
k230-flash` — which is the better fit for those environments anyway.

For detailed usage instructions of the GUI tool, please refer to [K230 Flash GUI User Manual](src/gui/k230_flash_gui_en.md).

---

## 🔧 Development

Contributions to this project are welcome!

### Project Structure

```bash
.
├── src/                          # Source code root directory
│   ├── k230_flash/              # Core flashing library
│   └── gui/                     # Graphical interface tool
```

### Building

`./build.sh` is the single entry point; it mirrors what the release workflow
does, so you do not have to remember three sets of commands.

```bash
./build.sh wheel            # sdist + wheel        -> dist/
./build.sh gui --venv       # GUI bundle           -> src/gui/dist/k230_flash_gui/
./build.sh gui --appimage   # Linux AppImage       -> dist/   (Docker, like CI)
./build.sh all              # wheel + GUI
./build.sh clean            # remove build artefacts
./build.sh --help
```

By default it only reports missing dependencies; add `--install-deps` to let it
install them.

**Use `--venv` for GUI builds.** PyInstaller bundles whatever Qt it can see in
the environment, so if your interpreter has a second Qt beside PySide6 — a
conda base with `PyQt6` and `qt6-main` does — you get a bundle whose Qt
libraries and Qt plugins are different versions. It builds without complaint and
then refuses to start:

```
qt.core.plugin.factoryloader: Ignoring QPA plugin due to mismatching Qt versions
This application failed to start because no Qt platform plugin could be initialized.
```

`--venv` builds against `requirements.txt` alone in `.build-venv/`. On one conda
box that was the difference between a 1.2 GB bundle that would not start (400 MB
of it Intel MKL, dragged in via numpy) and a working 221 MB one. `build.sh`
warns when it spots a second Qt, and again if the finished bundle is suspiciously
large.

The AppImage is built inside `docker/Dockerfile.ubuntu2204` rather than natively
on purpose: it has to link against an older glibc than a current dev box has, or
it will not start on the distributions it targets.

### Contributing

1. Fork this repository.
2. Create a new feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push the branch to your Fork (`git push origin feature/AmazingFeature`).
5. Create a Pull Request.

It's recommended to use `black` or `ruff format` to format your code.

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
