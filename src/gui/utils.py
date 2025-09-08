import configparser
import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path
import configparser

from loguru import logger
from platformdirs import user_config_dir

CONFIG_FILE = "config.ini"
HELP_FILE = "flash-python-gui.pdf"
APP_NAME = "k230_flash_gui"
LOG_FILE_NAME = "k230_flash.log"


# -------------------------
# 路径管理
# -------------------------

def get_app_config_dir() -> Path:
    """
    获取跨平台的用户配置目录
    - Linux: ~/.config/k230_flash_gui
    - Windows: %APPDATA%\\k230_flash_gui
    - macOS: ~/Library/Application Support/k230_flash_gui
    """
    config_dir = Path(user_config_dir(APP_NAME))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_exe_dir() -> Path:
    """获取 exe 所在目录（只读）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd() / "src" / "gui"


def get_base_path() -> Path:
    """获取资源根路径（PyInstaller 打包 or 源码运行）"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path.cwd()


def get_resource_path(filename: str) -> Path:
    """获取只读资源文件路径"""
    return get_base_path() / filename


FULL_LOG_FILE_PATH = get_app_config_dir() / LOG_FILE_NAME


# -------------------------
# 平台环境初始化
# -------------------------

def init_platform_env():
    """
    初始化跨平台运行环境：
    - Linux: 设置 gdk-pixbuf 环境变量并确保 loaders.cache 存在
    - 统一资源路径
    """
    base_path = get_base_path()

    if platform.system().lower() == "linux":
        gdk_base = base_path / "gdk-pixbuf"
        loaders_dir = gdk_base / "loaders"
        cache_file = gdk_base / "loaders.cache"
        
        # 设置环境变量
        os.environ["GDK_PIXBUF_MODULE_FILE"] = str(cache_file)
        os.environ["GDK_PIXBUF_MODULEDIR"] = str(loaders_dir)
        logger.debug(f"已设置 GDK_PIXBUF_MODULE_FILE={os.environ['GDK_PIXBUF_MODULE_FILE']}")
        logger.debug(f"已设置 GDK_PIXBUF_MODULEDIR={os.environ['GDK_PIXBUF_MODULEDIR']}")
        
        # 检查并生成 loaders.cache 文件
        if loaders_dir.exists() and (not cache_file.exists() or cache_file.stat().st_size == 0):
            try:
                # 尝试生成 loaders.cache 文件
                import subprocess
                logger.debug("loaders.cache文件不存在或为空，尝试生成...")
                
                # 使用 gdk-pixbuf-query-loaders 生成缓存文件
                query_cmd = None
                for cmd in [
                    "gdk-pixbuf-query-loaders",
                    "/usr/bin/gdk-pixbuf-query-loaders",
                    "/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders"
                ]:
                    if shutil.which(cmd) or os.path.exists(cmd):
                        query_cmd = cmd
                        break
                
                if query_cmd:
                    # 生成 loaders.cache 内容
                    result = subprocess.run(
                        [query_cmd] + list(loaders_dir.glob("*.so")),
                        capture_output=True,
                        text=True,
                        cwd=str(loaders_dir)
                    )
                    
                    if result.returncode == 0 and result.stdout:
                        # 将路径替换为相对路径以确保可移植性
                        cache_content = result.stdout
                        cache_content = cache_content.replace(str(loaders_dir), str(loaders_dir))
                        
                        with open(cache_file, 'w') as f:
                            f.write(cache_content)
                        logger.debug(f"成功生成 loaders.cache 文件: {cache_file}")
                    else:
                        logger.warning(f"生成 loaders.cache 失败: {result.stderr}")
                        # 生成一个最小的 loaders.cache 文件
                        _generate_minimal_loaders_cache(cache_file, loaders_dir)
                else:
                    logger.warning("未找到 gdk-pixbuf-query-loaders 命令，生成最小缓存文件")
                    _generate_minimal_loaders_cache(cache_file, loaders_dir)
                    
            except Exception as e:
                logger.warning(f"生成 loaders.cache 失败: {e}")
                _generate_minimal_loaders_cache(cache_file, loaders_dir)

    return {
        "base": base_path,
        "assets": base_path / "assets",
        "translations": base_path / "translations",
    }


def _generate_minimal_loaders_cache(cache_file: Path, loaders_dir: Path):
    """
    生成一个最小的 loaders.cache 文件，包含基本的图像格式支持
    """
    try:
        cache_content = '# GDK Pixbuf Image Loader Modules file\n'
        cache_content += '# Automatically generated file, do not edit\n'
        cache_content += '# Created by K230 Flash GUI\n\n'
        
        # 添加常用的图像格式加载器
        loaders = {
            'libpixbufloader-png.so': ['png'],
            'libpixbufloader-jpeg.so': ['jpeg', 'jpg'],
            'libpixbufloader-gif.so': ['gif'],
            'libpixbufloader-bmp.so': ['bmp'],
            'libpixbufloader-ico.so': ['ico'],
            'libpixbufloader-svg.so': ['svg'],
            'libpixbufloader-tiff.so': ['tiff', 'tif'],
            'libpixbufloader-xpm.so': ['xpm'],
        }
        
        for loader_file, extensions in loaders.items():
            loader_path = loaders_dir / loader_file
            if loader_path.exists():
                cache_content += f'"/{loader_path}"\n'
                cache_content += f'"image/{extensions[0]}" 5 "gdk-pixbuf" "The {extensions[0].upper()} image format" "LGPL"\n'
                for ext in extensions:
                    cache_content += f'"{ext}" "" 100\n'
                cache_content += '\n'
        
        with open(cache_file, 'w') as f:
            f.write(cache_content)
        logger.debug(f"已生成最小 loaders.cache 文件: {cache_file}")
        
    except Exception as e:
        logger.error(f"生成最小 loaders.cache 文件失败: {e}")
        if loaders_dir.exists() and (not cache_file.exists() or cache_file.stat().st_size == 0):
            try:
                # 尝试生成 loaders.cache 文件
                import subprocess
                logger.debug("loaders.cache文件不存在或为空，尝试生成...")
                
                # 使用 gdk-pixbuf-query-loaders 生成缓存文件
                query_cmd = None
                for cmd in [
                    "gdk-pixbuf-query-loaders",
                    "/usr/bin/gdk-pixbuf-query-loaders",
                    "/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders"
                ]:
                    if shutil.which(cmd) or os.path.exists(cmd):
                        query_cmd = cmd
                        break
                
                if query_cmd:
                    # 生成 loaders.cache 内容
                    result = subprocess.run(
                        [query_cmd] + list(loaders_dir.glob("*.so")),
                        capture_output=True,
                        text=True,
                        cwd=str(loaders_dir)
                    )
                    
                    if result.returncode == 0 and result.stdout:
                        # 将路径替换为相对路径以确保可移植性
                        cache_content = result.stdout
                        cache_content = cache_content.replace(str(loaders_dir), str(loaders_dir))
                        
                        with open(cache_file, 'w') as f:
                            f.write(cache_content)
                        logger.debug(f"成功生成 loaders.cache 文件: {cache_file}")
                    else:
                        logger.warning(f"生成 loaders.cache 失败: {result.stderr}")
                        # 生成一个最小的 loaders.cache 文件
                        _generate_minimal_loaders_cache(cache_file, loaders_dir)
                else:
                    logger.warning("未找到 gdk-pixbuf-query-loaders 命令，生成最小缓存文件")
                    _generate_minimal_loaders_cache(cache_file, loaders_dir)
                    
            except Exception as e:
                logger.warning(f"生成 loaders.cache 失败: {e}")
                _generate_minimal_loaders_cache(cache_file, loaders_dir)

    return {
        "base": base_path,
        "assets": base_path / "assets",
        "translations": base_path / "translations",
    }


def _generate_minimal_loaders_cache(cache_file: Path, loaders_dir: Path):
    """
    生成一个最小的 loaders.cache 文件，包含基本的图像格式支持
    """
    try:
        cache_content = '# GDK Pixbuf Image Loader Modules file\n'
        cache_content += '# Automatically generated file, do not edit\n'
        cache_content += '# Created by K230 Flash GUI\n\n'
        
        # 添加常用的图像格式加载器
        loaders = {
            'libpixbufloader-png.so': ['png'],
            'libpixbufloader-jpeg.so': ['jpeg', 'jpg'],
            'libpixbufloader-gif.so': ['gif'],
            'libpixbufloader-bmp.so': ['bmp'],
            'libpixbufloader-ico.so': ['ico'],
            'libpixbufloader-svg.so': ['svg'],
            'libpixbufloader-tiff.so': ['tiff', 'tif'],
            'libpixbufloader-xpm.so': ['xpm'],
        }
        
        for loader_file, extensions in loaders.items():
            loader_path = loaders_dir / loader_file
            if loader_path.exists():
                cache_content += f'"/{loader_path}"\n'
                cache_content += f'"image/{extensions[0]}" 5 "gdk-pixbuf" "The {extensions[0].upper()} image format" "LGPL"\n'
                for ext in extensions:
                    cache_content += f'"{ext}" "" 100\n'
                cache_content += '\n'
        
        with open(cache_file, 'w') as f:
            f.write(cache_content)
        logger.debug(f"已生成最小 loaders.cache 文件: {cache_file}")
        
    except Exception as e:
        logger.error(f"生成最小 loaders.cache 文件失败: {e}")


# -------------------------
# 配置文件管理
# -------------------------

def load_config():
    """从用户配置目录加载 config.ini"""
    config_path = get_app_config_dir() / CONFIG_FILE
    logger.debug(f"加载配置文件: {config_path}")

    config = configparser.ConfigParser()
    if config_path.exists():
        config.read(config_path, encoding="utf-8")
    else:
        logger.warning("未找到 config.ini，创建默认配置")
        save_config(config)

    return config


def save_config(config):
    """保存 ConfigParser 对象到用户配置目录"""
    config_path = get_app_config_dir() / CONFIG_FILE
    with open(config_path, "w", encoding="utf-8") as configfile:
        config.write(configfile)
    logger.debug(f"配置已保存到 {config_path}")


# -------------------------
# 日志管理
# -------------------------

def update_log_level(log_level):
    """动态更新日志级别"""
    try:
        logger.remove()
        if sys.stdout is not None:
            logger.add(sys.stdout, level=log_level.upper(),
                       format="{time:HH:mm:ss.SSS} | {level:<8} | {message}")

        if FULL_LOG_FILE_PATH:
            log_path = get_app_config_dir() / LOG_FILE_NAME
            logger.add(
                log_path,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name} | {message}",
                rotation="10 MB",
                retention="10 days",
                level=log_level.upper(),
                enqueue=True,
                encoding="utf-8",
            )
        logger.debug(f"日志级别已更新为: {log_level.upper()}")

    except Exception as e:
        if sys.stdout is not None:
            print(f"Warning: 更新日志级别失败: {e}")


# -------------------------
# 资源文件提取
# -------------------------

def extract_resource(filename: str):
    """
    从资源中复制文件到用户配置目录（仅第一次）
    例如帮助文档、默认模板等
    """
    target_path = get_app_config_dir() / filename
    if not target_path.exists():
        try:
            shutil.copy(get_resource_path(filename), target_path)
            logger.info(f"提取 {filename} 到 {target_path}")
        except Exception as e:
            logger.error(f"提取 {filename} 失败: {e}")


# -------------------------
# 版本号管理
# -------------------------

def get_version_from_file(name="version.txt"):
    """
    从版本文件中读取版本号
    优先查找顺序：
    1. 打包后的应用程序内部资源目录中的version.txt（CI构建时生成）
    2. 打包后的应用程序目录中的version.txt（备用）
    3. 配置目录中的version.txt（备用）
    4. 默认版本号 "dev"
    """
    # 在打包后的应用程序中，version.txt在_internal目录中
    if getattr(sys, "frozen", False):
        # PyInstaller打包后的环境
        version_paths = [
            Path(sys._MEIPASS) / name,  # _internal目录中的资源文件（优先）
            Path(sys.executable).parent / name,  # 与可执行文件同级（备用）
            Path(sys.executable).parent / ".." / name,  # 上一级目录（备用）
        ]
    else:
        # 开发环境，检查多个可能的位置
        current_dir = Path(__file__).parent
        version_paths = [
            current_dir / name,  # 当前目录
            current_dir / ".." / ".." / name,  # 项目根目录
            get_app_config_dir() / name,  # 配置目录
        ]
    
    # 按优先级查找版本文件
    for version_path in version_paths:
        try:
            if version_path.exists():
                with open(version_path, "r", encoding="utf-8") as f:
                    version = f.read().strip()
                    if version:  # 确保版本不为空
                        logger.debug(f"从 {version_path} 读取版本号: {version}")
                        return version
        except Exception as e:
            logger.debug(f"读取版本文件 {version_path} 失败: {e}")
            continue
    
    # 如果所有路径都失败，返回默认版本
    logger.warning("未找到版本文件，使用默认版本号")
    return "dev"


def get_version():
    """
    获取应用程序版本号
    - 打包后的应用程序：从CI构建时生成的version.txt读取
    - 开发环境：从可能的位置查找version.txt，如果没有则返回"dev"
    """
    return get_version_from_file()


# -------------------------
# 入口
# -------------------------

if __name__ == "__main__":
    # 开发环境测试
    print(f"当前版本: {get_version()}")
    print(f"应用配置目录: {get_app_config_dir()}")
    
    # 加载配置测试
    config = load_config()
    print(f"配置文件已加载，段数: {len(config.sections())}")
