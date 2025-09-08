# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
import os
import platform
from pathlib import Path

spec_dir = Path.cwd()
block_cipher = None
system = platform.system().lower()

# 应用资源文件配置
extra_datas = [("config.ini", ".")]
if os.path.exists("version.txt"):
    extra_datas.append(("version.txt", "."))
if os.path.exists("k230_flash_gui_zh.pdf"):
    extra_datas.append(("k230_flash_gui_zh.pdf", "."))
if os.path.exists("k230_flash_gui_en.pdf"):
    extra_datas.append(("k230_flash_gui_en.pdf", "."))
if os.path.exists("english.qm"):
    extra_datas.append(("english.qm", "."))
if os.path.exists("assets"):
    extra_datas.append(("assets/*", "assets/"))

# K230 Flash loaders
k230_loaders_path = spec_dir.parent / "k230_flash" / "loaders"
if k230_loaders_path.exists():
    extra_datas.append((str(k230_loaders_path), "k230_flash/loaders"))

binaries = []

# Windows特定配置
if system == "windows":
    # 添加libusb-1.0.dll
    libusb_dll = os.path.join(spec_dir, "libusb-1.0.dll")
    if os.path.exists(libusb_dll):
        binaries.append((libusb_dll, "."))
        print(f"Adding Windows USB library: {libusb_dll}")

# macOS特定配置
elif system == "darwin":
    # macOS USB库配置
    try:
        # 查找libusb库
        import subprocess
        result = subprocess.run(["brew", "--prefix", "libusb"], capture_output=True, text=True)
        if result.returncode == 0:
            libusb_path = result.stdout.strip()
            libusb_lib = os.path.join(libusb_path, "lib", "libusb-1.0.dylib")
            if os.path.exists(libusb_lib):
                binaries.append((libusb_lib, "."))
                print(f"Adding macOS USB library: {libusb_lib}")
    except:
        # 备用路径
        for path in ["/usr/local/lib/libusb-1.0.dylib", "/opt/homebrew/lib/libusb-1.0.dylib"]:
            if os.path.exists(path):
                binaries.append((path, "."))
                break

# Linux配置 - 移除gdk-pixbuf相关配置，因为PySide6不需要GTK相关组件


a = Analysis(
    ["main.py"],
    pathex=[str(spec_dir), str(spec_dir.parent)],
    binaries=binaries,
    datas=extra_datas,
    hiddenimports=[
        # K230 Flash 核心模块
        *collect_submodules("k230_flash"),
        # GUI 模块
        "advanced_settings",
        "batch_flash",
        "common_widget_styles",  # 修正拼写错误
        "log_file_monitor",
        "single_flash",
        "utils",
        "resources_rc",
        # USB 相关
        "usb",
        "usb.core",
        "usb.util",
        "usb.backend",
        "usb.backend.libusb1",
        # 日志
        "loguru",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 不使用WebEngine，排除相关模块
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        # 3D相关模块（如果不使用）
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore", 
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,  # 生成 onedir
    name="k230_flash_gui",
    debug=False,
    strip=False,
    upx=False,  # 禁用UPX压缩，避免macOS签名问题
    console=False,
    icon="assets/k230_flash_gui_logo.ico" if system != "darwin" else "assets/k230_flash_gui_logo.icns",
    # Windows特定设置
    version="version_info.txt" if system == "windows" and os.path.exists("version_info.txt") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="k230_flash_gui"
)

# macOS .app bundle配置
if system == "darwin":
    app = BUNDLE(
        coll,
        name="K230FlashGUI.app",
        icon="assets/k230_flash_gui_logo.icns",
        bundle_identifier="com.kendryte.k230flashgui",
        version="1.0.0",
        info_plist={
            'CFBundleName': 'K230 Flash GUI',
            'CFBundleDisplayName': 'K230 Flash GUI',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'LSMinimumSystemVersion': '10.14.0',
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSUIElement': False,
            'NSHighResolutionCapable': True,
            'CFBundleDocumentTypes': [{
                'CFBundleTypeName': 'K230 Image Files',
                'CFBundleTypeExtensions': ['kdimg', 'img'],
                'CFBundleTypeRole': 'Editor'
            }]
        }
    )