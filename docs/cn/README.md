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

该工具支持三种烧录模式。

### 模式 1: 烧录完整的 `.kdimg` 文件包

这是最简单的模式。直接将 `.kdimg` 文件作为参数传递即可。

```bash
k230-flash -m SDCARD /path/to/your/firmware.kdimg
```

### 模式 2: 烧录独立的 `.img` 文件

你可以指定一系列 `[地址, 文件路径]` 对，将不同的 `.img` 文件烧录到介质的不同位置。

```bash
# 格式: k230-flash [地址1] [文件1] [地址2] [文件2] ...
k230-flash -m SDCARD 0x000000 uboot.img 0x400000 rtt.img
```

### 模式 3: 只烧录 `.kdimg` 中的部分分区

用 `--kdimg-select` 指定分区名，只烧录其中几个分区，其余分区保持设备上原有内容不变。适合只更新 uboot 等场景，比重刷整包快很多。

```bash
k230-flash -m SDCARD firmware.kdimg --kdimg-select uboot_spl_a uboot_a
```

> 传入的 `.img` / `.kdimg` 也可以是 `.zip` / `.gz` / `.tar.gz` / `.tgz` 压缩包，工具会自动解压并取其中第一个镜像文件。

### 完整参数列表

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-l, --list-devices` | — | 列出当前已连接的 K230 设备并退出 |
| `-d, --device-path` | 自动选择第一个 | 指定 USB 端口路径（如 `1-5.3.2`）。指定后工具会轮询等待该设备出现 |
| `-m, --media-type` | `EMMC` | 目标介质：`EMMC` / `SDCARD` / `SPI_NAND` / `SPI_NOR` / `OTP`。大小写、分隔符、常见缩写都接受 —— `spi-nand`、`spinand`、`nand` 都是 `SPI_NAND`，`sd` 就是 `SDCARD`。`OTP` 需配合 `-lf`，见下方说明 |
| `--kdimg-select` | — | 只烧录 `.kdimg` 中指定名字的分区（可多个） |
| `-lf, --loader-file` | 内置 loader | 自定义 loader 二进制路径 |
| `-la, --loader-address` | `0x80360000` | loader 加载地址 |
| `--auto-reboot` | 关闭 | 烧录完成后自动重启设备 |
| `--device-timeout` | `300` | 指定 `-d` 时，等待设备出现的超时时间（秒） |
| `--device-retry-interval` | `1` | 等待设备时的轮询间隔（秒） |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |

几个常用例子：

```bash
# 多设备时指定要烧录哪一个
k230-flash -d "1-5" firmware.kdimg

# 烧到 SPI NOR（工具会自动换用对应的 loader）
k230-flash --media-type SPI_NOR firmware.kdimg

# 使用自定义 loader
k230-flash --loader-file my_loader.bin --loader-address 0x80360000 firmware.kdimg

# 排查问题时打开详细日志
k230-flash --log-level DEBUG -m SDCARD firmware.kdimg
```

不装入口脚本时也可以直接用模块方式运行：

```bash
python -m k230_flash --list-devices
```

### 退出码与报错方式

本工具面向脚本调用，失败通过退出码体现，而不是只写在日志里：

| 退出码 | 含义 |
|---|---|
| `0` | 烧录成功 |
| `1` | 烧录失败（设备找不到、介质选错、镜像超出容量、设备报告写入错误等） |
| `2` | 命令行被拒绝（参数错误、文件不存在、介质类型不认识） |
| `130` | 被 Ctrl-C 中断 |

参数校验发生在**等待设备之前**，所以路径写错或介质类型拼错会立即失败，不必先等满设备超时。失败时只打印一行原因，不再抛 Python traceback。

### 介质名称的写法

`-m` 会把输入去掉分隔符、转成大写后再匹配，所以大小写和 `-`/`_`/空格的差异从来不影响结果。在此之上还接受几个缩写：

| 规范写法 | 同样接受 |
|---|---|
| `EMMC` | `emmc` |
| `SDCARD` | `sdcard`、`sd` |
| `SPI_NAND` | `spi-nand`、`spinand`、`spi nand`、`nand` |
| `SPI_NOR` | `spi-nor`、`spinor`、`spi nor`、`nor` |
| `OTP` | `otp` |

**`MMC` 故意不接受**：eMMC 和 SD 共用同一个 loader，但发送的探测字节不同，随便猜一个就有一半概率是错的，而且会在板子上表现为难懂的 "no suitable device"。现在你会得到 `did you mean EMMC?` 的提示。无法识别的输入仍然会被拒绝，足够接近时会给出建议。

CLI、库 API、burner 三处用的是同一个归一化函数，所以 `k230-flash -m nand` 和 `flash_kdimg(media_type="nand")` 不可能出现口径不一致。

### 关于 `OTP`

`OTP` 对于已经运行起来的 loader 是合法的目标介质，但工具没有内置 OTP 的 loader，因此单靠 `-m OTP` 无法从 BootROM 进入——需要用 `-lf/--loader-file` 指定一个支持它的 loader。

### 烧录过程中发生了什么

了解这个流程有助于看懂日志和定位报错——烧录分两个阶段：

1. 设备以烧录模式上电，此时运行的是芯片内固化的 **BootROM**，它只能接收一小段代码，不具备读写存储介质的能力。
2. 工具把与目标介质匹配的 **loader**（一个裁剪过的 U-Boot）推送到芯片内存并启动它。
3. loader 启动会让设备**从 USB 上重新枚举**——工具会自动等待并重新识别，这一步通常不到 1 秒，无需人工干预。
4. 工具通过 loader 探测介质、获取容量，然后写入固件，期间显示实时进度。
5. 若指定了 `--auto-reboot`，写入完成后设备自动重启进入正常启动流程。

因此日志里出现"等待设备切换至 U-Boot 模式"是正常现象。如果卡在介质探测（提示检查 `-m` 介质类型），通常是 `-m` 与实际硬件不符，或介质未插好。

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

<img src="https://raw.githubusercontent.com/kendryte/k230_flash_py/main/src/gui/images/single_flash_mode.png" width="600">

### 📥 下载安装

您可以从 [GitHub Releases](https://github.com/kendryte/k230_flash_py/releases) 页面下载最新版本的预编译可执行文件。下载后直接运行即可，无需安装 Python 环境。

Linux 下 GUI 是单个 `.AppImage` 文件，加执行权限后直接运行：

```bash
chmod +x k230_flash_gui-linux-x86_64-*.AppImage
./k230_flash_gui-linux-x86_64-*.AppImage
```

它需要 FUSE 来挂载自身，桌面版发行版都自带（`fuse3`；注意**不需要** `libfuse2`）。如果是无头服务器、容器，或者环境不允许挂载，请改用命令行版 —— `pip install k230-flash` —— 那些场景本来也更适合用 CLI。

GUI 工具的详细使用说明请参考 [K230 Flash GUI 使用手册](../../src/gui/k230_flash_gui_zh.md)。

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

### 构建 (Building)

`./build.sh` 是唯一入口，行为与 release workflow 保持一致，不用再记三套命令。

```bash
./build.sh wheel            # sdist + wheel     -> dist/
./build.sh gui --venv       # GUI 包            -> src/gui/dist/k230_flash_gui/
./build.sh gui --appimage   # Linux AppImage    -> dist/   （走 Docker，同 CI）
./build.sh all              # wheel + GUI
./build.sh clean            # 清理构建产物
./build.sh --help
```

默认只报告缺失的依赖，加 `--install-deps` 才会真的去装。

**构建 GUI 请加 `--venv`。** PyInstaller 会把它在当前环境里看到的 Qt 一并打包，
所以只要解释器里除了 PySide6 还有第二套 Qt（conda base 装了 `PyQt6` 和
`qt6-main` 就是这种情况），打出来的包里 Qt 动态库和 Qt 插件版本就会对不上。
构建过程不会报错，运行时才启动失败：

```
qt.core.plugin.factoryloader: Ignoring QPA plugin due to mismatching Qt versions
This application failed to start because no Qt platform plugin could be initialized.
```

`--venv` 会在 `.build-venv/` 里只按 `requirements.txt` 装依赖再构建。在一台
conda 机器上实测：不加是 1.2 GB 且根本起不来（其中 400 MB 是 numpy 带进来的
Intel MKL），加了是 221 MB 且正常启动。`build.sh` 检测到第二套 Qt 会警告，
成品体积异常偏大时也会再提醒一次。

AppImage 特意放在 `docker/Dockerfile.ubuntu2204` 里构建而不是本机直接打：它必须
链接比当前开发机更老的 glibc，否则在目标发行版上起不来。

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
