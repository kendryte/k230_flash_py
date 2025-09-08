#!/usr/bin/env python3
"""
测试 main.py 中设备等待功能的单元测试
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# 添加源码路径到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import _wait_for_device_ready


class TestDeviceWait:
    """测试设备等待功能"""

    def test_wait_for_device_ready_success(self):
        """测试设备等待成功的情况"""
        with patch("main.find_device") as mock_find_device:
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
        with patch("main.find_device") as mock_find_device:
            # 模拟设备一直未找到
            mock_find_device.side_effect = Exception("Device not found")

            # 执行等待函数，应该抛出超时异常
            with pytest.raises(TimeoutError) as exc_info:
                _wait_for_device_ready("1-2", timeout_seconds=3, retry_interval=0.5)

            # 验证异常信息
            assert "等待设备 1-2 就绪超时" in str(exc_info.value)
            assert "已等待 3 秒" in str(exc_info.value)

    def test_wait_for_device_ready_retry_then_success(self):
        """测试设备等待重试后成功的情况"""
        with patch("main.find_device") as mock_find_device:
            # 模拟前两次失败，第三次成功
            mock_device = MagicMock()
            mock_find_device.side_effect = [
                Exception("Device not found"),
                Exception("Device not found"),
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
        with patch("main.find_device") as mock_find_device:
            mock_device = MagicMock()
            mock_find_device.return_value = (mock_device, "test-path")

            # 测试不同的设备路径
            _wait_for_device_ready("test-path")
            mock_find_device.assert_called_with(port_path="test-path")

            # 测试另一个设备路径
            mock_find_device.reset_mock()
            _wait_for_device_ready("another-path")
            mock_find_device.assert_called_with(port_path="another-path")


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])
