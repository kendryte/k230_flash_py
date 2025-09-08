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

The tool mainly supports two flashing modes.

### Mode 1: Flash Complete `.kdimg` File Package

This is the simplest mode. Just pass the `.kdimg` file as a parameter.

```bash
k230-flash -m SDCARD /path/to/your/firmware.kdimg
```

### Mode 2: Flash Independent `.img` Files

You can specify a series of `[address, file path]` pairs to flash different `.img` files to different memory locations.

```bash
# Format: k230-flash [address1] [file1] [address2] [file2] ...
k230-flash -m SDCARD 0x000000 uboot.img 0x400000 rtt.img
```

### Advanced Options

- **Specify Device**: If multiple devices are connected, use `-d` or `--device-path` to specify the device path to operate on.

  ```bash
  k230-flash -d "1-5" firmware.kdimg
  ```

- **Specify Storage Media**: Use `-m` or `--media-type` to specify the target media, and the tool will select the correct loader accordingly. Default is `EMMC`.

  ```bash
  k230-flash --media-type SPI_NOR firmware.kdimg
  ```

- **Custom Loader**: Use `-lf` and `-la` to specify your own loader file and load address.

  ```bash
  k230-flash --loader-file my_loader.bin --loader-address 0x80360000 firmware.kdimg
  ```

- **Auto Reboot**: Use `--auto-reboot` to automatically restart the device after flashing is complete.

---

## 📦 Using as a Library

You can easily integrate the functionality of this tool into your own Python scripts.

```python
import sys
from loguru import logger
from k230_flash import flash_kdimg, flash_addr_file_pairs, list_devices

# Configure logging to see detailed output
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

---

## 📦 GUI Tool

In addition to the command-line tool and Python library, this project also provides a feature-complete graphical user interface tool **K230 Flash GUI**, allowing users to perform firmware flashing operations through an intuitive interface.

### 📥 Download and Installation

You can download the latest version of pre-compiled executable files from the [GitHub Releases](https://github.com/kendryte/k230_flash_py/releases) page. After downloading, run directly without installing Python environment.

For detailed usage instructions of the GUI tool, please refer to [K230 Flash GUI User Manual](src/gui/k230_flash_gui.md).

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
