<div align="center">

# K230 Flash Tool (Python)

[**English**](../../README.md) | **简体中文**
</div>

这是一个使用 Python 编写的、跨平台的 Kendryte K230 芯片固件烧录工具。它提供了命令行工具（CLI）、图形界面（GUI）以及可编程的 Python API，用于通过 USB 将固件烧录到 K230 设备中。

该项目旨在为 K230 芯片用户提供一个功能齐全、性能优异、跨平台使用、易于扩展的固件烧录工具。

---

## ✨ 功能列表 (Features)

- **设备发现**: 可列出当前所有已连接的 K230 USB 设备及其路径。
- **多种介质类型**: 支持向 `EMMC`, `SDCARD`, `SPI_NAND`, `SPI_NOR` 等不同存储介质烧录，并自动选择对应的 loader。
- **灵活的烧录方式**:
  - 支持烧录完整的 `.kdimg` 固件包。
  - 支持 `.kdimg` 地址命令行覆盖。
  - 支持将多个独立的 `.img` 文件烧录到内存的指定地址。
  - 支持 gz、tgz、zip 等镜像压缩文件自动解压烧写。
- **进度与速度显示**: 在烧录过程中提供实时进度显示。
- **跨平台**: 基于 Python 和 `pyusb`，可在 Windows, Linux, macOS 上运行。
- **双重使用方式**:
  - **命令行工具**: 提供简单易用的命令行接口，适合终端用户和自动化脚本。
  - **Python 库**: 可作为第三方库导入到你自己的 Python 应用中，实现定制化的烧录逻辑。
  - **GUI 工具**：集成 `K230_flash_GUI` 工具及源码，供用户参考和定制改写。

---

## 🔌 驱动程序安装 (Driver Setup)

在使用 `k230-flash` 前，请确保 K230 设备处于烧录模式，并且操作系统已正确安装 USB 驱动。

### K230 设备如何进入烧录模式？

首先按住 K230 设备的 boot 按键，然后将 USB 线插入，将 K230 设备连接至电脑。对于 Windows, 您会在`设备管理器` 的 [通用串行总线设备] 下面看到显示 `K230 USB Boot Device`，这表示 K230 已经处于烧录模式，可以进行后续操作。

### Windows

首次使用时，可能需要为 K230 设备安装 **WinUSB 驱动**。推荐使用 [Zadig](https://zadig.akeo.ie/) 工具：

1. 下载并运行 Zadig（无需安装）。  
2. 在菜单 **Options → List All Devices** 勾选。  
3. 在下拉列表中选择 `K230 USB Boot Device`（或显示为 `Unknown Device`，Vendor ID: `29f1`，Product ID: `0230`）。  
4. 在右侧选择驱动程序 **WinUSB**。  
5. 点击 **Install Driver** 并等待完成。  

完成后，Windows 就能识别设备，`k230-flash` 工具即可正常使用。

### Linux (Ubuntu / Debian)

Linux 默认已内置 **usbfs/libusb** 驱动，通常不需要额外安装。  
但需要为非 root 用户配置 **udev 规则**，否则可能需要使用 `sudo` 执行命令。

1. 创建规则文件 `/etc/udev/rules.d/99-k230.rules`：

```bash
SUBSYSTEM=="usb", ATTRS{idVendor}=="29f1", ATTRS{idProduct}=="0230", MODE="0666"
```

2. 应用规则:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

3. 拔掉并重新插入 K230 设备。

完成后，普通用户即可直接运行 `k230-flash`，无需 `sudo`。

---

### macOS

macOS 自带 libusb 驱动，通常无需额外操作。
如果出现权限问题，可尝试使用 `sudo` 运行，或通过 [brew](https://brew.sh/) 确保已安装最新的 libusb：

```bash
brew install libusb
```

---

## 🚀 快速开始 (Quick Start)

### 1. 安装工具

从 PyPI 安装：

```bash
pip install k230-flash
```

### 2. 列出设备

确保 K230 设备已经在 通过 USB 连接到电脑，然后运行以下命令来查看设备是否被正确识别：

```bash
k230-flash --list-devices
```

如果设备已连接，你将看到类似以下的输出：

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

## 📖 使用方法 (Usage)

该工具主要支持两种烧录模式。

### 模式 1: 烧录完整的 `.kdimg` 文件包

这是最简单的模式。直接将 `.kdimg` 文件作为参数传递即可。

```bash
k230-flash -m SDCARD /path/to/your/firmware.kdimg
```

### 模式 2: 烧录独立的 `.img` 文件

你可以指定一系列 `[地址, 文件路径]` 对，将不同的 `.img` 文件烧录到内存的不同位置。

```bash
# 格式: k230-flash [地址1] [文件1] [地址2] [文件2] ...
k230-flash -m SDCARD 0x000000 uboot.img 0x400000 rtt.img
```

### 高级选项

- **指定设备**: 如果连接了多个设备，使用 `-d` 或 `--device-path` 指定要操作的设备路径。

  ```bash
  k230-flash -d "1-5" firmware.kdimg
  ```

- **指定存储介质**: 使用 `-m` 或 `--media-type` 来指定目标介质，工具会据此选择正确的 loader。默认为 `EMMC`。

  ```bash
  k230-flash --media-type SPI_NOR firmware.kdimg
  ```

- **自定义 Loader**: 使用 `-lf` 和 `-la` 指定自己的 loader 文件和加载地址。

  ```bash
  k230-flash --loader-file my_loader.bin --loader-address 0x80360000 firmware.kdimg
  ```

- **自动重启**: 使用 `--auto-reboot` 可以在烧录完成后自动重启设备。

---

## 📦 作为库使用(Using as a Library)

你可以方便地将此工具的功能集成到自己的 Python 脚本中。

```python
import sys
from loguru import logger
from k230_flash import flash_kdimg, flash_addr_file_pairs, list_devices

# 配置日志，以便看到详细输出
logger.remove()
logger.add(sys.stderr, level="INFO")

def main():
    try:
        # 列出设备
        print("Connected devices:")
        print(list_devices())

        # 烧录 .kdimg 文件
        logger.info("Flashing kdimg file...")
        flash_kdimg(
            kdimg_file="/path/to/your/firmware.kdimg",
            media_type="EMMC",
            auto_reboot=True
        )
        logger.info("kdimg flash completed.")

        # 烧录独立的 .img 文件
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

## 📦 图形界面工具 (GUI Tool)

除了命令行工具和Python库，本项目还提供了功能完整的图形界面工具 **K230 Flash GUI**，让用户能够通过直观的界面进行固件烧录操作。

### 📥 下载安装

您可以从 [GitHub Releases](https://github.com/kendryte/k230_flash_py/releases) 页面下载最新版本的预编译可执行文件。下载后直接运行即可，无需安装 Python 环境。

GUI 工具的详细使用说明请参考 [K230 Flash GUI 使用手册](src/gui/k230_flash_gui.md)。

---

## 🔧 开发 (Development)

欢迎为此项目贡献代码！

### 项目结构

```bash
.
├── src/                          # 源代码根目录
│   ├── k230_flash/              # 核心烧录库
│   └── gui/                     # 图形界面工具
```

### 贡献代码

1. Fork 本仓库。
2. 创建新的功能分支 (`git checkout -b feature/AmazingFeature`)。
3. 提交你的修改 (`git commit -m 'Add some AmazingFeature'`)。
4. 将分支推送到你的 Fork (`git push origin feature/AmazingFeature`)。
5. 发起一个 Pull Request。

建议使用 `black` 或 `ruff format` 对代码进行格式化。

---

## 📄 许可证 (License)

本项目采用 MIT 许可证。详情请见 `LICENSE` 文件。
