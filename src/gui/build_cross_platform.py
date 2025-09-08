#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跨平台GUI构建脚本
自动检测平台并执行相应的构建流程
"""

import os
import platform
import sys
from pathlib import Path


def main():
    """主函数 - 根据平台执行对应构建脚本"""
    system = platform.system().lower()
    gui_dir = Path(__file__).parent
    
    print(f"K230 Flash GUI - 跨平台构建脚本")
    print(f"检测到平台: {system}")
    print("=" * 50)
    
    # 切换到GUI目录
    os.chdir(gui_dir)
    
    if system == "windows":
        print("执行Windows构建...")
        from build_windows import main as build_windows
        build_windows()
    elif system == "darwin":
        print("执行macOS构建...")
        from build_macos import main as build_macos
        build_macos()
    elif system == "linux":
        print("Linux平台建议使用Docker构建AppImage")
        print("请运行以下命令:")
        print("cd ../../")
        print("docker build -f docker/Dockerfile.ubuntu2204 -t k230_build .")
        print("然后参考.github/workflows/build-and-release.yml中的Linux构建步骤")
        sys.exit(1)
    else:
        print(f"不支持的平台: {system}")
        sys.exit(1)

if __name__ == "__main__":
    main()