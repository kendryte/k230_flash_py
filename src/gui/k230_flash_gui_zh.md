# **K230 Flash GUI 使用说明书**  

## **1. 软件概述**  

**K230 Flash GUI** 是一款用于烧录 K230 开发板固件的工具，提供 **单机烧录** 和 **批量烧录** 两种模式，并支持多种存储介质（eMMC、SD Card、Nand Flash、NOR Flash、OTP）。  

本工具基于 **k230-flash** 库进行封装，提供了更友好的 GUI 界面。如果希望使用 **命令行工具** 开发自动化烧录流程，可以直接调用 **k230-flash** 库，无需 GUI 交互。  

## **2. 系统要求**  

- **操作系统**：Windows 10/11、Linux 或 macOS  
- **硬件要求**：USB 接口，用于连接 K230 开发板  
- **必要组件**：libusb 驱动程序（Windows 用户必须安装）或 libusb 库（Linux/macOS 用户需要安装）

## **3. 开发板硬件准备**  

在烧录前，需要让 **K230 开发板** 进入 **Burning Mode（烧录模式）**，步骤如下：  

1. **方法 1**（推荐）：  
   - **先按住** 开发板上的 **BOOT** 按键，然后 **插入 USB 线** 给开发板上电。  

2. **方法 2**：  
   - 开发板已经上电时，**先按住** **BOOT** 按键，再 **按住 RESET** 按键，然后 **松开 RESET**，最后 **松开 BOOT**。  

进入 **Burning Mode** 后，可以在 **设备管理器**（Windows）、`lsusb`（Linux）或 `system_profiler SPUSBDataType`（macOS）中查看是否识别到 **"K230 USB Boot Device"**。  

## **4. 驱动安装**  

### **4.1 Windows 用户**  

**K230 Flash GUI** 使用 **libusb** 进行 USB 设备通信。在 Windows 下，**必须** 安装相应的驱动程序：  

1. **下载 Zadig 工具**（[https://zadig.akeo.ie/](https://zadig.akeo.ie/)）。  
2. **将 K230 开发板连接到电脑并进入 Burning Mode**。  
3. **打开 Zadig**，选择 **Options > List All Devices**，然后找到 **K230 USB Boot Device**。  
4. 在 **Driver** 选项中，选择 **WinUSB**。  
5. 点击 **Install Driver**，等待安装完成。  
6. 安装完成后，可以在 **设备管理器** 中看到 **K230 USB Boot Device（WinUSB）**。  

### **4.2 Linux 用户**  

1. **安装 libusb 开发包**：  

   ```bash
   # Ubuntu/Debian
   sudo apt-get install libusb-1.0-0-dev
   
   # CentOS/RHEL/Fedora
   sudo yum install libusb1-devel
   ```

2. **添加 udev 规则**（可选，避免需要 sudo 权限）：

   ```bash
   echo 'SUBSYSTEM=="usb", ATTR{idVendor}="29f1", ATTR{idProduct}=="*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-k230.rules
   sudo udevadm control --reload-rules
   ```  

### **4.3 macOS 用户**  

1. **安装 libusb**：  
   推荐使用 Homebrew 安装 libusb：  

   ```bash  
   # 安装 libusb
   brew install libusb
   ```

2. **检查安装**：  

   ```bash
   # 验证 libusb 是否安装成功
   brew list libusb
   ```

3. **注意事项**：  
   - macOS 通常不需要额外的驱动程序，系统会自动识别 K230 设备  
   - 如果遇到权限问题，可能需要在"系统偏好设置 > 安全性与隐私"中允许相关权限  

## **5. 界面介绍**  

软件提供直观的图形化界面，包括菜单栏、主界面和日志区域。

![K230 Flash GUI](images/k230_flash_gui.png)

### **5.1 菜单栏**  

- **文件（F）**：提供退出功能（快捷键 `Ctrl+Q`）。  
- **设置（S）**：可选择烧录模式（单机 / 批量）及高级设置。  
- **语言 / Language（L）**：支持中文 / 英文切换。  
- **帮助（H）**：包含“关于”信息和使用说明文档。  

### **5.2 主界面**  

- **镜像文件选择**：可选择 `.bin`、`.img`、`.kdimg` 文件，以及压缩格式文件（`.zip`、`.gz`、`.tgz`、`.tar.gz`）。  
- **目标存储介质**：支持 eMMC、SD Card、Nand Flash、NOR Flash、OTP。  
- **进度条与日志**：显示烧录进度及日志信息。  

## **6. 烧录流程**  

### **6.1 选择烧录模式**  

在 **设置 > 烧录模式** 中选择：  

- **单机烧录模式**：单独对一台设备进行烧录。  
- **批量烧录模式**：对多台设备同时烧录（此功能尚在开发中）。  

### **6.2 选择固件文件**  

1. 点击"添加镜像文件"按钮，选择以下格式的文件：  
   - **镜像文件**：`.bin`、`.img`、`.kdimg`  
   - **压缩文件**：`.zip`、`.gz`、`.tgz`、`.tar.gz`（工具会自动解压并查找其中的镜像文件）  
2. 如果选择的是 `.kdimg` 文件，会解析出多个分区，用户可勾选需要烧录的部分。  
3. 对于压缩文件，系统会在临时目录中自动解压，并查找第一个可用的镜像文件。

### **6.3 选择目标存储介质**  

在介质选项中选择 **eMMC / SD Card / Nand Flash / NOR Flash / OTP**。  

### **6.4 开始烧录**  

1. **确认镜像文件、目标存储介质及烧录地址**。  
2. 点击 **“开始烧录”** 按钮，进度条会实时显示烧录进度。  
3. 烧录完成后，日志区域会提示 **“烧录完成！”**。  

## **7. 高级设置**  

可在 **设置 > 高级设置** 进行配置，如调整烧录参数、修改烧录地址等。  

## **8. 语言切换**  

在 **语言 / Language** 菜单中选择 **中文** 或 **English**，界面语言会自动切换。  

## **9. 常见问题**  

### **9.1 找不到烧录设备**  

如果在设备列表中找不到 K230 设备，请检查以下几点：  

1. **确认开发板是否处于 Burning Mode**：  
   - 重新按照第3章的步骤让开发板进入烧录模式  
   - 在设备管理器（Windows）或 `lsusb`（Linux）中确认是否识别到 K230 设备  

2. **检查驱动程序**（Windows 用户）：  
   - 确保已按照第4.1章安装了 WinUSB 驱动  
   - 在设备管理器中确认设备显示为 "K230 USB Boot Device (WinUSB)"  

3. **检查 libusb**（Linux 用户）：  
   - 确保已安装 libusb-1.0-0-dev 包  
   - 尝试使用 sudo 权限运行程序，或配置 udev 规则  

4. **检查 libusb**（macOS 用户）：  
   - 确保已通过 Homebrew 安装 libusb：`brew install libusb`  
   - 检查系统偷好设置中是否允许了相关权限  
   - 尝试在终端中运行 `system_profiler SPUSBDataType` 查看 K230 设备是否被识别  

5. **检查 USB 连接**：  
   - 更换 USB 数据线（避免使用仅充电线）  
   - 尝试不同的 USB 接口  
   - 确保 USB 线缆质量良好，支持数据传输  

### **9.2 烧录过程中失败**  

- **检查固件文件**：确保固件文件完整且适配当前开发板型号  
- **检查存储介质**：确认选择了正确的目标存储介质（eMMC/SD Card 等）  
- **重新进入烧录模式**：断开 USB 连接，重新让开发板进入 Burning Mode  
- **查看日志信息**：注意日志区域的错误提示，根据具体错误信息进行排查  
