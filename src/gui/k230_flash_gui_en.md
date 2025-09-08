# **K230 Flash GUI User Manual**  

## **1. Software Overview**  

**K230 Flash GUI** is a tool for flashing firmware to K230 development boards, providing both **single flash** and **batch flash** modes, and supporting multiple storage media (eMMC, SD Card, Nand Flash, NOR Flash, OTP).  

This tool is based on the **k230-flash** library with a friendly GUI interface. If you need to use **command-line tools** for automated flashing workflows, you can directly call the **k230-flash** library without GUI interaction.  

## **2. System Requirements**  

- **Operating System**: Windows 10/11, Linux, or macOS  
- **Hardware Requirements**: USB port for connecting K230 development board  
- **Required Components**: libusb drivers (must be installed for Windows users) or libusb library (required for Linux/macOS users)

## **3. Development Board Hardware Setup**  

Before flashing, you need to put the **K230 development board** into **Burning Mode**:  

1. **Method 1** (Recommended):  
   - **Hold down** the **BOOT** button on the development board, then **plug in the USB cable** to power on the board.  

2. **Method 2**:  
   - When the board is already powered on, **hold down** the **BOOT** button, then **press and hold the RESET** button, then **release RESET**, and finally **release BOOT**.  

After entering **Burning Mode**, you can check in **Device Manager** (Windows), `lsusb` (Linux), or `system_profiler SPUSBDataType` (macOS) to see if the **"K230 USB Boot Device"** is recognized.  

## **4. Driver Installation**  

### **4.1 Windows Users**  

**K230 Flash GUI** uses **libusb** for USB device communication. On Windows, you **must** install the corresponding drivers:  

1. **Download Zadig tool** ([https://zadig.akeo.ie/](https://zadig.akeo.ie/)).  
2. **Connect K230 development board to PC and enter Burning Mode**.  
3. **Open Zadig**, select **Options > List All Devices**, then find **K230 USB Boot Device**.  
4. In the **Driver** option, select **WinUSB**.  
5. Click **Install Driver** and wait for installation to complete.  
6. After installation, you can see **K230 USB Boot Device (WinUSB)** in **Device Manager**.  

### **4.2 Linux Users**  

1. **Install libusb development package**:  

   ```bash
   # Ubuntu/Debian
   sudo apt-get install libusb-1.0-0-dev
   
   # CentOS/RHEL/Fedora
   sudo yum install libusb1-devel
   ```

2. **Add udev rules** (optional, to avoid requiring sudo permissions):

   ```bash
   echo 'SUBSYSTEM=="usb", ATTR{idVendor}="29f1", ATTR{idProduct}=="*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-k230.rules
   sudo udevadm control --reload-rules
   ```  

### **4.3 macOS Users**  

1. **Install libusb**:  
   It is recommended to install libusb using Homebrew:  

   ```bash
   # Install libusb
   brew install libusb
   ```

2. **Verify installation**:  

   ```bash
   # Verify libusb installation
   brew list libusb
   ```

3. **Notes**:  
   - macOS usually does not require additional drivers, the system will automatically recognize K230 devices  
   - If you encounter permission issues, you may need to allow relevant permissions in "System Preferences > Security & Privacy"  

## **5. User Interface**  

The software provides an intuitive graphical interface, including menu bar, main interface, and log area.

![K230 Flash GUI](images/k230_flash_gui.png)

### **5.1 Menu Bar**  

- **File (F)**: Provides exit function (shortcut `Ctrl+Q`).  
- **Settings (S)**: Select flash mode (single / batch) and advanced settings.  
- **Language / Language (L)**: Supports Chinese / English switching.  
- **Help (H)**: Contains "About" information and user manual.  

### **5.2 Main Interface**  

- **Image File Selection**: Select `.bin`, `.img`, `.kdimg` files, as well as compressed format files (`.zip`, `.gz`, `.tgz`, `.tar.gz`).  
- **Target Storage Media**: Supports eMMC, SD Card, Nand Flash, NOR Flash, OTP.  
- **Progress Bar and Log**: Shows flashing progress and log information.  

## **6. Flashing Process**  

### **6.1 Select Flash Mode**  

In **Settings > Flash Mode**, choose:  

- **Single Flash Mode**: Flash a single device individually.  
- **Batch Flash Mode**: Flash multiple devices simultaneously (this feature is still under development).  

### **6.2 Select Firmware File**  

1. Click the "Add Image File" button to select files in the following formats:  
   - **Image files**: `.bin`, `.img`, `.kdimg`  
   - **Compressed files**: `.zip`, `.gz`, `.tgz`, `.tar.gz` (the tool will automatically extract and find image files within)  
2. If you select a `.kdimg` file, it will be parsed into multiple partitions, and users can check the parts they want to flash.  
3. For compressed files, the system will automatically extract them in a temporary directory and find the first available image file.

### **6.3 Select Target Storage Media**  

Select **eMMC / SD Card / Nand Flash / NOR Flash / OTP** in the media options.  

### **6.4 Start Flashing**  

1. **Confirm the image file, target storage media, and flash address**.  
2. Click the **"Start Flash"** button, and the progress bar will show real-time flashing progress.  
3. After flashing is complete, the log area will show **"Flash Complete!"**.  

## **7. Advanced Settings**  

You can configure advanced options in **Settings > Advanced Settings**, such as adjusting flash parameters, modifying flash addresses, etc.  

## **8. Language Switching**  

Select **Chinese** or **English** in the **Language / Language** menu, and the interface language will switch automatically.  

## **9. Troubleshooting**  

### **9.1 Cannot Find Flash Device**  

If you cannot find the K230 device in the device list, please check the following:  

1. **Confirm if the development board is in Burning Mode**:  
   - Re-follow the steps in Chapter 3 to put the development board into burning mode  
   - Confirm in Device Manager (Windows) or `lsusb` (Linux) if the K230 device is recognized  

2. **Check drivers** (Windows users):  
   - Ensure WinUSB driver has been installed according to Chapter 4.1  
   - Confirm in Device Manager that the device shows as "K230 USB Boot Device (WinUSB)"  

3. **Check libusb** (Linux users):  
   - Ensure libusb-1.0-0-dev package is installed  
   - Try running the program with sudo privileges, or configure udev rules  

4. **Check libusb** (macOS users):  
   - Ensure libusb has been installed via Homebrew: `brew install libusb`  
   - Check if relevant permissions are allowed in System Preferences  
   - Try running `system_profiler SPUSBDataType` in terminal to see if K230 device is recognized  

5. **Check USB connection**:  
   - Replace USB data cable (avoid using charging-only cables)  
   - Try different USB ports  
   - Ensure USB cable quality is good and supports data transmission  

### **9.2 Flash Process Failure**  

- **Check firmware file**: Ensure firmware file is complete and compatible with current development board model  
- **Check storage media**: Confirm correct target storage media is selected (eMMC/SD Card, etc.)  
- **Re-enter burning mode**: Disconnect USB connection, let development board re-enter Burning Mode  
- **Check log information**: Pay attention to error messages in log area, troubleshoot based on specific error information  
