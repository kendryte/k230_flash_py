#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Windows平台GUI打包脚本
使用PyInstaller将k230_flash_gui打包为exe文件
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def setup_windows_build():
    """Setup Windows build environment"""
    print("=== Setting up Windows build environment ===")
    
    # Ensure we're in the gui directory
    gui_dir = Path(__file__).parent
    os.chdir(gui_dir)
    
    # Check required files
    required_files = [
        "k230_flash_gui.spec",
        "main.py",
        "config.ini",
        "libusb-1.0.dll"  # Windows USB driver
    ]
    
    for file in required_files:
        if not Path(file).exists():
            print(f"Error: Missing required file {file}")
            return False
    
    # Check assets directory
    if not Path("assets").exists():
        print("Error: Missing assets directory")
        return False
    
    print("Windows build environment check completed")
    return True

def build_executable():
    """Build exe file using PyInstaller"""
    print("=== Building Windows executable ===")
    
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
            return False
        
        print("PyInstaller build successful")
        return True
        
    except Exception as e:
        print(f"Error occurred during build: {e}")
        return False

def create_installer():
    """Create Windows installer package"""
    print("=== Creating Windows installer package ===")
    
    dist_dir = Path("dist/k230_flash_gui")
    if not dist_dir.exists():
        print("Error: Build output directory not found")
        return False
    
    # Create zip package
    output_dir = Path("../../upload")
    output_dir.mkdir(exist_ok=True)
    
    # Get version information - prefer environment variable, fallback to git
    version = os.environ.get('VERSION')
    if not version:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                capture_output=True, text=True, cwd="../.."
            )
            version = result.stdout.strip() if result.returncode == 0 else "dev"
        except:
            version = "dev"
    
    print(f"Using version: {version}")
    
    # Create zip file
    zip_name = f"k230_flash_gui-windows-{version}"
    shutil.make_archive(
        str(output_dir / zip_name),
        'zip',
        str(dist_dir.parent),
        dist_dir.name
    )
    
    print(f"Windows installer package created: {zip_name}.zip")
    return True

def main():
    """Main function"""
    print("K230 Flash GUI - Windows Build Script")
    print("=" * 50)
    
    if not setup_windows_build():
        sys.exit(1)
    
    if not build_executable():
        sys.exit(1)
    
    if not create_installer():
        sys.exit(1)
    
    print("\n=== Windows build completed ===")
    print("Output directory: dist/k230_flash_gui/")
    print("Installer package: ../../upload/")

if __name__ == "__main__":
    main()