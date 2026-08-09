#!/usr/bin/env python3
import sys
import time

from loguru import logger

from . import api
from .arg_parser import parse_arguments
from .burners import BurnerError
from .constants import FULL_LOG_FILE_PATH
from .kdimage import KdimageError
from .progress import progress_callback as default_progress_callback
from .usb_utils import DeviceNotFoundError, DeviceOpenError, find_device, release_device

# Failures that are the user's problem, not a bug in this tool: a wrong media
# type, an image that does not fit, a board that never showed up. These get a
# one-line message and a non-zero exit; anything else keeps its traceback,
# because that is a defect worth reporting.
EXPECTED_FAILURES = (
    BurnerError,
    DeviceNotFoundError,
    DeviceOpenError,
    FileNotFoundError,
    KdimageError,
    TimeoutError,
    ValueError,
    RuntimeError,
)


def _wait_for_device_ready(device_path=None, timeout_seconds=300, retry_interval=2):
    """
    等待指定路径的设备就绪

    :param device_path: 设备路径，例如 "1-2"
    :param timeout_seconds: 最大等待时间（秒），默认5分钟
    :param retry_interval: 重试间隔（秒），默认2秒
    :raises TimeoutError: 超时未找到设备时抛出异常
    """
    start_time = time.monotonic()
    retry_count = 0

    logger.info(f"等待设备就绪: {device_path}")

    while True:
        try:
            # 尝试查找设备
            dev, found_path = find_device(port_path=device_path)
        except DeviceNotFoundError:
            # Only "not there yet" is worth retrying. This used to catch every
            # exception, so a TypeError in this very function would be retried
            # patiently for five minutes before surfacing as a timeout.
            pass
        else:
            logger.info(f"设备已就绪: {found_path}")
            # The caller re-finds the device when it actually flashes; holding
            # this handle open until then serves no purpose and keeps a libusb
            # handle alive across the BootROM handoff.
            release_device(dev)
            return

        retry_count += 1
        elapsed_time = time.monotonic() - start_time

        # 检查是否超时
        if elapsed_time >= timeout_seconds:
            logger.error(f"等待设备超时 ({timeout_seconds}秒): {device_path}")
            raise TimeoutError(f"等待设备 {device_path} 就绪超时，已等待 {timeout_seconds} 秒")

        # 每30秒或前几次重试时输出等待信息
        if retry_count <= 3 or retry_count % 15 == 0:
            remaining_time = timeout_seconds - elapsed_time
            logger.info(f"设备 {device_path} 暂未就绪，继续等待... (剩余 {remaining_time:.0f}秒)")

        # 等待后重试
        time.sleep(retry_interval)


def _setup_logging(log_level):
    # 移除现有的所有处理器，使用库自己的配置
    logger.remove()

    # 添加控制台输出处理器（在GUI模式下检查sys.stdout）
    if sys.stdout is not None:
        logger.add(sys.stdout, level=log_level)

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


def _run(args, progress_callback):
    """Do the work described by `args`. Raises on failure."""
    if args.list_devices:
        print(api.list_devices())
        return

    # Normalised once, then used everywhere. The wait used to be given the
    # stripped path while the flash was given the raw one, so `-d " 1-2 "`
    # waited for a device it then failed to open.
    device_path = (args.device_path or "").strip() or None

    _wait_for_device_ready(
        device_path,
        timeout_seconds=args.device_timeout,
        retry_interval=args.device_retry_interval,
    )

    # The parser guarantees exactly one of these is set, and that
    # --kdimg-select only accompanies a kdimg file.
    common = dict(
        port_path=device_path,
        loader_file=args.loader_file,
        loader_address=args.loader_address,
        media_type=args.media_type,
        auto_reboot=args.auto_reboot,
        progress_callback=progress_callback,
    )

    if args.kdimg_file:
        api.flash_kdimg(
            kdimg_file=args.kdimg_file,
            selected_partitions=getattr(args, "kdimg_selected_partitions", None),
            **common,
        )
    else:
        api.flash_addr_file_pairs(addr_filename_pairs=args.addr_filename_pairs, **common)


def main(args_list=None, progress_callback=None, use_external_logging=False):
    """
    Command-line entry point for the k230_flash tool.

    :param args_list: 命令行参数列表
    :param progress_callback: 进度回调函数
    :param use_external_logging: 是否使用外部日志配置，默认False（使用库自己的日志配置）
    :returns: 0 on success
    :raises SystemExit: on any failure, with a non-zero code

    Failure is always raised, never returned, in both CLI and GUI mode. The GUI
    calls this in-process and treats "returned without raising" as a successful
    flash (see src/gui/single_flash.py), so a failure that came back as a return
    value would be announced to the user as 烧录成功.
    """
    if progress_callback is None:
        progress_callback = default_progress_callback

    try:
        args = parse_arguments(args_list=args_list)

        # 根据use_external_logging参数决定是否配置logger
        # 只在解析完参数后进行一次性配置，避免重复配置
        if not use_external_logging:
            _setup_logging(getattr(args, "log_level", "INFO").upper())

        logger.debug(f"Parsed arguments: {args}")

        _run(args, progress_callback)
        return 0

    except SystemExit as e:
        # Argument errors arrive here from argparse. This used to be swallowed
        # in GUI mode, which meant the GUI's own SystemExit handler never fired
        # and a rejected command line was reported as a successful flash.
        if e.code:
            logger.error(f"参数错误，已退出（代码 {e.code}）")
        raise
    except KeyboardInterrupt:
        logger.warning("已被用户中断")
        raise SystemExit(130)
    except EXPECTED_FAILURES as e:
        # A failed flash used to dump a full traceback at the user and leave the
        # exit code to the interpreter, so a CI script could not tell it from a
        # successful one without scraping stderr.
        logger.error(f"烧录失败: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    sys.exit(main())
