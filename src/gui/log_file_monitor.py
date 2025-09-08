import os
import time

from PySide6.QtCore import QObject, QTimer, Signal


class LogFileMonitor(QObject):
    """实时监控日志文件变化并发送新内容"""

    new_content = Signal(str)  # 信号：发送新增的日志内容

    def __init__(self, log_file_path, parent=None):
        super().__init__(parent)
        self.log_file_path = log_file_path
        self.last_position = 0  # 记录上次读取位置
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_for_updates)
        self.timer.start(500)  # 每500ms检查一次文件更新

    def check_for_updates(self):
        """检查文件是否有新内容"""
        try:
            if not self.log_file_path.exists():
                return

            with open(self.log_file_path, "r", encoding="utf-8") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size < self.last_position:
                    # 文件被截断（例如日志轮换），从头读取
                    self.last_position = 0
                f.seek(self.last_position)
                new_content = f.read()
                if new_content:
                    self.new_content.emit(new_content)
                    self.last_position = f.tell()
        except Exception as e:
            print(f"Failed to monitor log file: {e}")
