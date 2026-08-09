#!/usr/bin/env python3
"""
测试 main.py 中设备等待功能的单元测试
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from k230_flash.main import _wait_for_device_ready
from k230_flash.usb_utils import DeviceNotFoundError


class TestDeviceWait:
    """测试设备等待功能"""

    def test_wait_for_device_ready_success(self):
        """测试设备等待成功的情况"""
        with patch("k230_flash.main.find_device") as mock_find_device:
            # 模拟设备找到
            mock_device = MagicMock()
            mock_find_device.return_value = (mock_device, "1-2")

            # 执行等待函数，应该立即返回
            start_time = time.time()
            _wait_for_device_ready("1-2", timeout_seconds=10)
            elapsed_time = time.time() - start_time

            # 验证函数几乎立即返回（小于1秒）
            assert elapsed_time < 1.0
            mock_find_device.assert_called_once_with(port_path="1-2")

    def test_wait_for_device_ready_timeout(self):
        """测试设备等待超时的情况"""
        with patch("k230_flash.main.find_device") as mock_find_device:
            # 模拟设备一直未找到
            mock_find_device.side_effect = DeviceNotFoundError("Device not found")

            # 执行等待函数，应该抛出超时异常
            with pytest.raises(TimeoutError) as exc_info:
                _wait_for_device_ready("1-2", timeout_seconds=3, retry_interval=0.5)

            # 验证异常信息
            assert "等待设备 1-2 就绪超时" in str(exc_info.value)
            assert "已等待 3 秒" in str(exc_info.value)

    def test_wait_for_device_ready_retry_then_success(self):
        """测试设备等待重试后成功的情况"""
        with patch("k230_flash.main.find_device") as mock_find_device:
            # 模拟前两次失败，第三次成功
            mock_device = MagicMock()
            mock_find_device.side_effect = [
                DeviceNotFoundError("Device not found"),
                DeviceNotFoundError("Device not found"),
                (mock_device, "1-2"),
            ]

            # 执行等待函数，应该在重试后成功
            start_time = time.time()
            _wait_for_device_ready("1-2", timeout_seconds=10, retry_interval=0.1)
            elapsed_time = time.time() - start_time

            # 验证函数在重试后成功（时间应该大于0.2秒，小于3秒）
            assert 0.2 <= elapsed_time < 3.0
            # 验证调用了3次
            assert mock_find_device.call_count == 3

    def test_wait_for_device_ready_parameters(self):
        """测试设备等待函数的参数处理"""
        with patch("k230_flash.main.find_device") as mock_find_device:
            mock_device = MagicMock()
            mock_find_device.return_value = (mock_device, "test-path")

            # 测试不同的设备路径
            _wait_for_device_ready("test-path")
            mock_find_device.assert_called_with(port_path="test-path")

            # 测试另一个设备路径
            mock_find_device.reset_mock()
            _wait_for_device_ready("another-path")
            mock_find_device.assert_called_with(port_path="another-path")

    def test_unexpected_error_is_not_retried(self):
        """Only "device not here yet" is worth waiting out.

        The loop used to catch bare Exception, so a bug inside it -- a TypeError,
        an AttributeError -- was patiently retried for the full five-minute
        timeout and then reported as "device not ready", pointing the user at
        their hardware instead of at the defect.
        """
        with patch("k230_flash.main.find_device") as mock_find_device:
            mock_find_device.side_effect = TypeError("bug in the caller")

            with pytest.raises(TypeError):
                _wait_for_device_ready("1-2", timeout_seconds=30, retry_interval=0.1)

            assert mock_find_device.call_count == 1, "should fail immediately, not retry"

    def test_found_device_is_released(self):
        """The flash re-finds the device; holding this handle open across the
        BootROM handoff is exactly the kind of stale reference the handoff code
        goes to some trouble to avoid."""
        with (
            patch("k230_flash.main.find_device") as mock_find_device,
            patch("k230_flash.main.release_device") as mock_release,
        ):
            mock_device = MagicMock()
            mock_find_device.return_value = (mock_device, "1-2")

            _wait_for_device_ready("1-2", timeout_seconds=10)

            mock_release.assert_called_once_with(mock_device)


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])
