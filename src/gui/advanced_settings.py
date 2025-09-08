import json
import os

import utils
from loguru import logger
from PySide6.QtCore import QCoreApplication, QTranslator, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AdvancedSettingsDialog(QDialog):
    # 定义自定义信号，用于通知主窗口日志级别变更
    log_level_changed = Signal(str)  # 参数为新的日志级别字符串

    def __init__(self, parent=None):
        if not isinstance(parent, QWidget):
            parent = None
        super().__init__(parent)

        self.setWindowTitle("高级设置")
        self.setFixedSize(400, 250)  # 设置窗口大小

        # 加载配置
        self.config = utils.load_config()

        # 日志等级选项
        self.log_level_label = QLabel("日志等级：")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setCurrentText(self.config.get("AdvancedSettings", "log_level", fallback="INFO"))

        # 连接日志级别变更信号，实现实时更新
        self.log_level_combo.currentTextChanged.connect(self.on_log_level_changed)

        # 自定义 Loader 选项
        self.loader_label = QLabel("自定义 Loader 文件：")
        self.loader_path = QLabel(self.config.get("AdvancedSettings", "custom_loader", fallback="未选择文件"))
        self.loader_button = QPushButton("选择文件")
        self.loader_button.clicked.connect(self.select_loader_file)

        # **Loader Address 选项**
        self.loader_address_label = QLabel("Loader 地址：")
        self.loader_address_input = QLineEdit()
        self.loader_address_input.setText(self.config.get("AdvancedSettings", "loader_address", fallback="0x80360000"))

        # 自动重启选项
        self.auto_reboot_checkbox = QCheckBox("烧录完成后自动重启")
        self.auto_reboot_checkbox.setChecked(self.config.getboolean("AdvancedSettings", "auto_reboot", fallback=False))

        # 确定和取消按钮
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")
        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject)

        # 布局管理
        layout = QVBoxLayout()

        # 日志等级布局
        log_layout = QHBoxLayout()
        log_layout.addWidget(self.log_level_label)
        log_layout.addWidget(self.log_level_combo)

        # Loader 文件布局
        loader_layout = QHBoxLayout()
        loader_layout.addWidget(self.loader_label)
        loader_layout.addWidget(self.loader_button)

        # **Loader Address 布局**
        loader_address_layout = QHBoxLayout()
        loader_address_layout.addWidget(self.loader_address_label)
        loader_address_layout.addWidget(self.loader_address_input)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)

        # 添加到主布局
        layout.addLayout(log_layout)
        layout.addLayout(loader_layout)
        layout.addLayout(loader_address_layout)  # Loader Address
        layout.addWidget(self.auto_reboot_checkbox)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # **加载语言**
        self.current_language = self.config.get("General", "language", fallback="zh")
        self.load_language(self.current_language)

    def on_log_level_changed(self, new_log_level):
        """
        日志级别变更时的回调函数
        通过Signal-Slot机制通知主窗口更新日志配置
        """
        try:
            # 先保存到配置文件
            if "AdvancedSettings" not in self.config:
                self.config["AdvancedSettings"] = {}
            self.config["AdvancedSettings"]["log_level"] = new_log_level
            utils.save_config(self.config)

            # 发射信号通知主窗口更新日志级别
            self.log_level_changed.emit(new_log_level)
            logger.debug(f"日志级别变更信号已发射: {new_log_level}")

        except Exception as e:
            logger.error(f"更新日志级别失败: {e}")

    def load_language(self, language):
        """加载当前语言"""
        self.config.set("General", "language", language)
        utils.save_config(self.config)

        # **加载翻译文件**
        translator = QTranslator()
        if language == "en":
            qm_path = ":/translations/english.qm"
            success = translator.load(str(qm_path))
            logger.debug(f"加载英文翻译文件 {qm_path} 结果：{success}")
        else:
            translator.load("")  # 清空翻译器，恢复默认

        # **应用翻译**
        QCoreApplication.instance().installTranslator(translator)

        # **更新 UI**
        self.update_ui_text()

    def update_ui_text(self):
        self.setWindowTitle(QCoreApplication.translate("AdvancedSettingsDialog", "高级设置"))
        self.log_level_label.setText(QCoreApplication.translate("AdvancedSettingsDialog", "日志等级："))
        self.loader_label.setText(QCoreApplication.translate("AdvancedSettingsDialog", "自定义 Loader 文件："))
        self.loader_button.setText(QCoreApplication.translate("AdvancedSettingsDialog", "选择文件"))
        self.loader_address_label.setText(QCoreApplication.translate("AdvancedSettingsDialog", "Loader 地址："))
        self.auto_reboot_checkbox.setText(QCoreApplication.translate("AdvancedSettingsDialog", "烧录完成后自动重启"))
        self.save_button.setText(QCoreApplication.translate("AdvancedSettingsDialog", "保存"))
        self.cancel_button.setText(QCoreApplication.translate("AdvancedSettingsDialog", "取消"))

    def select_loader_file(self):
        """选择自定义 Loader 文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 Loader 文件", "", "Bin Files (*.bin);;All Files (*)")
        if file_path:
            self.loader_path.setText(file_path)
            self.config["AdvancedSettings"]["custom_loader"] = file_path
            logger.debug(f"已选择 Loader 文件: {file_path}")

    def save_settings(self):
        """保存设置到 config.ini"""
        if "AdvancedSettings" not in self.config:
            self.config["AdvancedSettings"] = {}

        # 获取当前设置值
        current_log_level = self.log_level_combo.currentText()

        self.config["AdvancedSettings"]["log_level"] = current_log_level
        self.config["AdvancedSettings"]["auto_reboot"] = str(self.auto_reboot_checkbox.isChecked())
        self.config["AdvancedSettings"]["loader_address"] = self.loader_address_input.text()

        utils.save_config(self.config)  # 直接保存整个 config 对象

        # 发射信号确保主窗口的日志级别也被更新（防止用户直接点击保存而不触发下拉框变更事件）
        self.log_level_changed.emit(current_log_level)
        logger.debug(f"保存设置时发射日志级别更新信号: {current_log_level}")

        self.accept()
