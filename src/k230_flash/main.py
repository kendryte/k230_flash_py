#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path

from loguru import logger

from . import api
from .arg_parser import parse_arguments
from .constants import FULL_LOG_FILE_PATH
from .progress import progress_callback as default_progress_callback
from .usb_utils import find_device


def _wait_for_device_ready(device_path=None, timeout_seconds=300, retry_interval=2):
    """
    等待指定路径的设备就绪

    :param device_path: 设备路径，例如 "1-2"
    :param timeout_seconds: 最大等待时间（秒），默认5分钟
    :param retry_interval: 重试间隔（秒），默认2秒
    :raises TimeoutError: 超时未找到设备时抛出异常
    """
    start_time = time.time()
    retry_count = 0

    logger.info(f"等待设备就绪: {device_path}")

    while True:
        try:
            # 尝试查找设备
            dev, found_path = find_device(port_path=device_path)
            if dev is not None:
                logger.info(f"设备已就绪: {found_path}")
                return
        except Exception as e:
            # 设备未找到，继续等待
            retry_count += 1
            elapsed_time = time.time() - start_time

            # 检查是否超时
            if elapsed_time >= timeout_seconds:
                logger.error(f"等待设备超时 ({timeout_seconds}秒): {device_path}")
                raise TimeoutError(
                    f"等待设备 {device_path} 就绪超时，已等待 {timeout_seconds} 秒"
                )

            # 每30秒或前几次重试时输出等待信息
            if retry_count <= 3 or retry_count % 15 == 0:
                remaining_time = timeout_seconds - elapsed_time
                logger.info(
                    f"设备 {device_path} 暂未就绪，继续等待... (剩余 {remaining_time:.0f}秒)"
                )

            # 等待后重试
            time.sleep(retry_interval)


def main(args_list=None, progress_callback=None, use_external_logging=False):
    """
    Command-line entry point for the k230_flash tool.

    :param args_list: 命令行参数列表
    :param progress_callback: 进度回调函数
    :param use_external_logging: 是否使用外部日志配置，默认False（使用库自己的日志配置）
    """
    if progress_callback is None:
        progress_callback = default_progress_callback

    try:
        args = parse_arguments(args_list=args_list)

        # 根据use_external_logging参数决定是否配置logger
        # 只在解析完参数后进行一次性配置，避免重复配置
        if not use_external_logging:
            log_level = getattr(args, "log_level", "INFO").upper()

            # 移除现有的所有处理器，使用库自己的配置
            logger.remove()

            # 添加控制台输出处理器（在GUI模式下检查sys.stdout）
            if sys.stdout is not None:
                logger.add(
                    sys.stdout,
                    level=log_level,
                )

            # 添加文件输出处理器
            try:
                if FULL_LOG_FILE_PATH:
                    logger.add(
                        FULL_LOG_FILE_PATH,
                        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
                        rotation="10 MB",
                        retention="10 days",
                        level=log_level,
                        enqueue=True,  # Ensure non-blocking file writes
                    )
            except Exception as e:
                # 如果文件日志设置失败，只使用控制台输出
                if sys.stdout is not None:
                    print(f"Warning: Failed to setup file logging: {e}")
                    print(f"Log file path: {FULL_LOG_FILE_PATH}")

        logger.debug(f"Parsed arguments: {args}")

        if args.list_devices:
            devices_json = api.list_devices(log_level=args.log_level)
            print(devices_json)
            return

        # 等待设备就绪
        timeout_seconds = getattr(args, "device_timeout", 300)
        retry_interval = getattr(args, "device_retry_interval", 1)
        _wait_for_device_ready(
            args.device_path.strip(),
            timeout_seconds=timeout_seconds,
            retry_interval=retry_interval,
        )

        # Refactored logic to call API functions
        if (
            args.kdimg_file
            and hasattr(args, "kdimg_selected_partitions")
            and args.kdimg_selected_partitions
        ):
            # Mode 3: kdimg file with selected partitions
            api.flash_kdimg(
                kdimg_file=args.kdimg_file,
                selected_partitions=args.kdimg_selected_partitions,
                port_path=args.device_path,
                loader_file=args.loader_file,
                loader_address=args.loader_address,
                media_type=args.media_type,
                auto_reboot=args.auto_reboot,
                progress_callback=progress_callback,
                log_level=args.log_level,
            )
        elif args.kdimg_file and args.addr_filename_pairs:
            # This should not happen with the corrected arg_parser, but keep for safety
            logger.warning(
                "Unexpected combination: kdimg_file with addr_filename_pairs. Using kdimg mode."
            )
            api.flash_kdimg(
                kdimg_file=args.kdimg_file,
                port_path=args.device_path,
                loader_file=args.loader_file,
                loader_address=args.loader_address,
                media_type=args.media_type,
                auto_reboot=args.auto_reboot,
                progress_callback=progress_callback,
                log_level=args.log_level,
            )
        elif args.kdimg_file:
            api.flash_kdimg(
                kdimg_file=args.kdimg_file,
                port_path=args.device_path,
                loader_file=args.loader_file,
                loader_address=args.loader_address,
                media_type=args.media_type,
                auto_reboot=args.auto_reboot,
                progress_callback=progress_callback,
                log_level=args.log_level,
            )
        elif args.addr_filename_pairs:
            api.flash_addr_file_pairs(
                addr_filename_pairs=args.addr_filename_pairs,
                port_path=args.device_path,
                loader_file=args.loader_file,
                loader_address=args.loader_address,
                media_type=args.media_type,
                auto_reboot=args.auto_reboot,
                progress_callback=progress_callback,
                log_level=args.log_level,
            )
        else:
            logger.warning("No operation specified. Use -h for help.")

    except Exception as e:
        raise


if __name__ == "__main__":
    main()
