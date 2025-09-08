#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
macOS平台GUI打包脚本
使用PyInstaller将k230_flash_gui打包为.app，然后创建dmg文件
"""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def setup_macos_build():
    """Setup macOS build environment"""
    print("=== Setting up macOS build environment ===")
    
    # Ensure we're in the gui directory
    gui_dir = Path(__file__).parent
    os.chdir(gui_dir)
    
    # Check required files
    required_files = [
        "k230_flash_gui.spec",
        "main.py",
        "config.ini"
    ]
    
    for file in required_files:
        if not Path(file).exists():
            print(f"Error: Missing required file {file}")
            return False
    
    # Check assets directory
    if not Path("assets").exists():
        print("Error: Missing assets directory")
        return False
    
    # Check if running on macOS
    if sys.platform != "darwin":
        print("Warning: Not running on macOS platform, some features may not be available")
    
    print("macOS build environment check completed")
    return True

def build_app():
    """Build .app file using PyInstaller"""
    print("=== Building macOS application ===")
    
    try:
        # Clean previous builds
        if Path("build").exists():
            shutil.rmtree("build")
        if Path("dist").exists():
            shutil.rmtree("dist")
        
        # Run PyInstaller
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--clean", "-y",
            "k230_flash_gui.spec"
        ]
        
        print(f"Executing command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"PyInstaller build failed:")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            
            # 如果是符号链接冲突错误，尝试多次清理和重试
            if "FileExistsError" in result.stderr and ("symlink" in result.stderr.lower() or "framework" in result.stderr.lower()):
                print("Detected symlink conflict, attempting comprehensive cleanup and retry...")
                
                # 清理所有可能的冲突文件
                cleanup_framework_conflicts()
                
                # 重试构建，最多3次
                for attempt in range(3):
                    print(f"Retry attempt {attempt + 1}/3...")
                    
                    # 再次清理
                    if Path("dist").exists():
                        shutil.rmtree("dist")
                    if Path("build").exists():
                        shutil.rmtree("build")
                    
                    # 重试构建
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"Build successful on retry attempt {attempt + 1}")
                        break
                    else:
                        print(f"Retry {attempt + 1} failed:")
                        print(f"STDERR: {result.stderr}")
                        if attempt < 2:  # 不是最后一次重试
                            cleanup_framework_conflicts()
                
                if result.returncode != 0:
                    print("All retry attempts failed")
                    return False
            else:
                return False
        
        print("PyInstaller build successful")
        return True
        
    except Exception as e:
        print(f"Error occurred during build: {e}")
        return False

def cleanup_framework_conflicts():
    """Clean up potential framework conflicts"""
    print("Performing comprehensive framework cleanup...")
    
    try:
        # 清理可能的冲突目录
        conflict_paths = [
            Path("dist"),
            Path("build"),
            Path("/tmp/pyinstaller_cache"),
        ]
        
        for path in conflict_paths:
            if path.exists():
                try:
                    shutil.rmtree(path)
                    print(f"Cleaned up: {path}")
                except Exception as e:
                    print(f"Warning: Failed to clean {path}: {e}")
        
        # 清理Qt框架缓存
        qt_cache_dirs = [
            Path.home() / ".cache" / "pyinstaller",
            Path("/tmp") / "_MEI*",
        ]
        
        for cache_dir in qt_cache_dirs:
            if cache_dir.exists():
                try:
                    if "*" in str(cache_dir):
                        # 处理通配符路径
                        import glob
                        for path in glob.glob(str(cache_dir)):
                            shutil.rmtree(path)
                            print(f"Cleaned up cache: {path}")
                    else:
                        shutil.rmtree(cache_dir)
                        print(f"Cleaned up cache: {cache_dir}")
                except Exception as e:
                    print(f"Warning: Failed to clean cache {cache_dir}: {e}")
        
        print("Framework cleanup completed")
        
    except Exception as e:
        print(f"Warning: Framework cleanup failed: {e}")

def create_app_bundle():
    """Create standard macOS .app bundle"""
    print("=== Creating macOS application bundle ===")
    
    dist_dir = Path("dist/k230_flash_gui")
    app_dir = Path("dist/K230FlashGUI.app")
    
    if not dist_dir.exists():
        print("Error: PyInstaller output directory not found")
        return False
    
    # If .app bundle already exists, skip
    if app_dir.exists():
        print("Application bundle already exists")
        return True
    
    try:
        # Create .app directory structure
        app_dir.mkdir(exist_ok=True)
        contents_dir = app_dir / "Contents"
        contents_dir.mkdir(exist_ok=True)
        macos_dir = contents_dir / "MacOS"
        macos_dir.mkdir(exist_ok=True)
        resources_dir = contents_dir / "Resources"
        resources_dir.mkdir(exist_ok=True)
        
        # Copy executable files and resources
        if (dist_dir / "k230_flash_gui").exists():
            shutil.copy2(dist_dir / "k230_flash_gui", macos_dir / "K230FlashGUI")
        else:
            # Copy entire directory contents
            for item in dist_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, macos_dir)
                else:
                    shutil.copytree(item, macos_dir / item.name, dirs_exist_ok=True)
        
        # Copy icon file
        icon_src = Path("assets/k230_flash_gui_logo.icns")
        if icon_src.exists():
            icon_dst = resources_dir / "icon.icns"
            shutil.copy2(icon_src, icon_dst)
        
        # Get version info for Info.plist
        version = os.environ.get('VERSION', '1.0.0')
        
        # Create Info.plist file
        info_plist = {
            'CFBundleName': 'K230 Flash GUI',
            'CFBundleDisplayName': 'K230 Flash GUI',
            'CFBundleIdentifier': 'com.kendryte.k230flashgui',
            'CFBundleVersion': version,
            'CFBundleShortVersionString': version,
            'CFBundleExecutable': 'K230FlashGUI',
            'CFBundleIconFile': 'icon.icns',
            'CFBundlePackageType': 'APPL',
            'CFBundleSignature': '????',
            'LSMinimumSystemVersion': '10.14.0',
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSUIElement': False,
            'CFBundleInfoDictionaryVersion': '6.0'
        }
        
        with open(contents_dir / "Info.plist", 'wb') as f:
            plistlib.dump(info_plist, f)
        
        print("macOS application bundle created successfully")
        return True
        
    except Exception as e:
        print(f"Error creating App Bundle: {e}")
        return False

def create_dmg():
    """Create DMG installer package"""
    print("=== Creating DMG installer package ===")
    
    app_path = Path("dist/K230FlashGUI.app")
    if not app_path.exists():
        print("Error: Application bundle not found")
        return False
    
    # Get version information - prefer environment variable, fallback to git
    version = os.environ.get('VERSION')
    if not version:
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                capture_output=True, text=True, cwd="../.."
            )
            version = result.stdout.strip() if result.returncode == 0 else "dev"
        except:
            version = "dev"
    
    print(f"Using version: {version}")
    
    # Create output directory
    output_dir = Path("../../upload")
    output_dir.mkdir(exist_ok=True)
    
    dmg_name = f"k230_flash_gui-macos-{version}.dmg"
    dmg_path = output_dir / dmg_name
    
    # Delete existing dmg file
    if dmg_path.exists():
        dmg_path.unlink()
    
    try:
        # Create temporary DMG directory
        temp_dmg_dir = Path("temp_dmg")
        if temp_dmg_dir.exists():
            shutil.rmtree(temp_dmg_dir)
        temp_dmg_dir.mkdir()
        
        # Copy application to temporary directory
        shutil.copytree(app_path, temp_dmg_dir / "K230FlashGUI.app")
        
        # Create Applications symbolic link
        applications_link = temp_dmg_dir / "Applications"
        if not applications_link.exists():
            os.symlink("/Applications", applications_link)
        
        # Create DMG using hdiutil
        cmd = [
            "hdiutil", "create",
            "-volname", "K230 Flash GUI",
            "-srcfolder", str(temp_dmg_dir),
            "-ov", "-format", "UDZO",
            str(dmg_path)
        ]
        
        print(f"Executing command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"DMG creation failed:")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False
        
        # Clean up temporary directory
        shutil.rmtree(temp_dmg_dir)
        
        print(f"DMG installer package created: {dmg_name}")
        return True
        
    except Exception as e:
        print(f"Error creating DMG: {e}")
        return False

def main():
    """Main function"""
    print("K230 Flash GUI - macOS Build Script")
    print("=" * 50)
    
    if not setup_macos_build():
        sys.exit(1)
    
    if not build_app():
        sys.exit(1)
    
    if not create_app_bundle():
        sys.exit(1)
    
    if not create_dmg():
        sys.exit(1)
    
    print("\n=== macOS build completed ===")
    print("Output directory: dist/K230FlashGUI.app")
    print("Installer package: ../../upload/")

if __name__ == "__main__":
    main()