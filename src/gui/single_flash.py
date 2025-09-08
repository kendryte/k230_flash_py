import json
import logging
import os
import time
from pathlib import Path

import PySide6.QtWidgets as QtWidgets
import resources_rc
import utils
from advanced_settings import AdvancedSettingsDialog
from common_widget_sytles import CommonWidgetStyles
from log_file_monitor import LogFileMonitor
from loguru import logger
from PySide6 import QtGui
from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QMetaObject,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QThread,
    QTime,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QFontDatabase,
    QGradient,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QMovie,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
    QTextCursor,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils import FULL_LOG_FILE_PATH

import k230_flash.file_utils as cmd_file_utils
import k230_flash.kdimage as cmd_kdimg
import k230_flash.main as cmd_main
from k230_flash import *

USE_DUMMY_FLASHING = False


class SingleFlash(QMainWindow):
    def __init__(self):
        super().__init__()

        # 创建 log_output QTextEdit
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)

        self.ui = Ui_MainWindow(log_output_widget=self.log_output)
        self.ui.setupUi(self)

    def init_logging_display(self):
        # 初始化日志文件监控
        log_file_path = FULL_LOG_FILE_PATH
        self.log_monitor = LogFileMonitor(log_file_path)
        self.log_monitor.new_content.connect(self.append_log_content)

    @Slot(str)
    def append_log_content(self, content):
        """将新增日志内容追加到 QTextEdit"""
        self.log_output.moveCursor(QtGui.QTextCursor.End)  # 移动光标到末尾
        self.log_output.insertPlainText(content)
        self.log_output.ensureCursorVisible()

        # 自动滚动到底部
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class Ui_MainWindow(object):

    def __init__(self, log_output_widget):
        self.log_output = log_output_widget

    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName("MainWindow")

        # 创建 centralwidget
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        MainWindow.setCentralWidget(self.centralwidget)

        # 创建垂直布局
        main_layout = QVBoxLayout(self.centralwidget)
        main_layout.addWidget(self.create_file_browser_region())
        main_layout.addWidget(self.create_table())
        comb_layout = QHBoxLayout()
        comb_layout.addWidget(self.create_device_list_region(), stretch=1)
        comb_layout.addWidget(self.create_target_media_region(), stretch=5)
        main_layout.addLayout(comb_layout)
        # main_layout.addWidget(self.create_target_media_region())
        # main_layout.addWidget(self.create_device_list_region())
        main_layout.addWidget(self.create_progress_bar_layout())
        main_layout.addWidget(self.create_log_output_groupbox())

        # 新增状态变量
        self.flash_thread = None
        self.addr_filename_pairs = []
        self.img_list_mode = None

        # 设备等待相关状态
        self.waiting_for_device = False
        self.waiting_timer = None

        # 新增定时器相关变量
        self.sim_timer = None
        self.sim_elapsed = 0
        self.sim_total_time = 20  # 总模拟时间20秒

        # 新增：定时器，1 秒刷新设备列表
        self.device_refresh_timer = QTimer(MainWindow)
        self.device_refresh_timer.timeout.connect(self.refresh_device_list)
        self.device_refresh_timer.start(1000)  # 每 1000ms 调用一次

        # 初始化界面文本（必须在所有UI元素创建完成后调用）
        self.update_ui_text()

    def update_ui_text(self):
        # self.setWindowTitle(QCoreApplication.translate("SingleFlash", "单机烧录"))

        self.image_file_label.setText(
            QCoreApplication.translate("SingleFlash", "镜像文件：")
        )
        self.file_dialog_button.setText(
            QCoreApplication.translate("SingleFlash", "添加镜像文件")
        )
        self.image_table_groupbox.setTitle(
            QCoreApplication.translate("SingleFlash", "镜像文件内容：")
        )

        self.target_media_region_group.setTitle(
            QCoreApplication.translate("SingleFlash", "目标存储介质：")
        )
        self.device_list_region_group.setTitle(
            QCoreApplication.translate("SingleFlash", "设备列表：")
        )
        self.list_device_button.setText(
            QCoreApplication.translate("SingleFlash", "刷新设备列表")
        )
        self.start_button.setText(QCoreApplication.translate("SingleFlash", "开始烧录"))
        self.advanced_setting_button.setText(
            QCoreApplication.translate("SingleFlash", "高级设置")
        )
        self.log_output_groupbox.setTitle(
            QCoreApplication.translate("SingleFlash", "日志输出：")
        )

        # 更新表格头部标签
        self.update_table_headers()

        # 更新复选框文本
        if hasattr(self, "header_checkbox"):
            self.header_checkbox.setText(
                QCoreApplication.translate("SingleFlash", "全选")
            )

        # 更新帮助提示文本
        if hasattr(self, "device_help_tip"):
            self.device_help_tip.setText(self.get_translated_text("device_help_tip"))

    def update_table_headers(self):
        """更新表格头部标签"""
        if hasattr(self, "table"):
            headers = [
                "",  # 第一列空白，用于复选框
                QCoreApplication.translate("SingleFlash", "镜像名称"),
                QCoreApplication.translate("SingleFlash", "烧录地址"),
                QCoreApplication.translate("SingleFlash", "镜像大小"),
            ]
            self.table.setHorizontalHeaderLabels(headers)

    def get_translated_text(self, key):
        """获取翻译文本的辅助方法"""
        translations = {
            "start_flash": QCoreApplication.translate("SingleFlash", "开始烧录"),
            "cancel_waiting": QCoreApplication.translate("SingleFlash", "取消等待"),
            "waiting_device": QCoreApplication.translate(
                "SingleFlash", "等待设备连接..."
            ),
            "progress_format": "%p%",  # 进度条格式不需要翻译
            "device_help_tip": QCoreApplication.translate(
                "SingleFlash", "💡 找不到烧录设备？查看解决办法"
            ),
        }
        return translations.get(key, key)

    def create_file_browser_region(self):
        # 创建一个 QWidget 作为容器
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # 创建 "镜像" 标签
        self.image_file_label = QLabel("镜像文件：")
        layout.addWidget(self.image_file_label)

        # 创建 QLineEdit 用于显示文件路径
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)  # 设置为只读
        layout.addWidget(self.file_path_edit)

        # 创建文件选择按钮
        self.file_dialog_button = QPushButton("添加镜像文件")
        # 添加一个 add_image_file.png 图片到按钮
        # self.file_dialog_button.setIcon(QIcon(os.path.abspath("assets/add_image_file.png")))
        layout.addWidget(self.file_dialog_button)

        # 连接按钮点击事件
        self.file_dialog_button.clicked.connect(self.open_file_dialog)

        self.file_dialog_button.setStyleSheet(CommonWidgetStyles.QPushButton_css())

        return widget

    def open_file_dialog(self):
        config = utils.load_config()
        last_image_path = config.get("General", "last_image_path", fallback="")

        # 打开文件对话框并获取文件路径
        file_path, _ = QFileDialog.getOpenFileName(
            parent=None,  # Use parent=None to make it a top-level dialog
            caption="选择镜像文件",
            dir=last_image_path,  # Set initial directory
            filter="镜像文件 (*.bin *.img *.kdimg *.zip *.gz *.tgz)",
        )
        if file_path:  # 如果用户选择了文件
            self.file_path_edit.setText(file_path)  # 将文件路径显示在 QLineEdit 中
            logger.info(f"已选择文件: {file_path}")
            # 调用解压函数，获取真实文件路径
            extracted_path = cmd_file_utils.extract_if_compressed(Path(file_path))
            self.update_table_for_img(extracted_path)  # 更新表格内容

            # Save the directory of the selected file
            selected_dir = str(Path(file_path).parent)
            config.set("General", "last_image_path", selected_dir)
            utils.save_config(config)

    def update_table_for_img(self, file_path):
        """如果选择了 .img 文件，则更新表格内容"""
        if file_path.suffix == ".img":
            # 如果当前模式是kdimg，则切换为img,并清空表格
            if self.img_list_mode == "kdimg":
                self.table.clearContents()
            self.img_list_mode = "img"

            file_name = file_path.name
            file_size = file_path.stat().st_size
            formatted_size = self.format_size(file_size)

            # 对于.img文件，只允许添加一个，如果再次添加则替换原有文件
            # 清空表格内容并重新设置为只有一行
            self.table.clearContents()
            self.table.setRowCount(1)

            row = 0  # 始终使用第一行

            # 复选框列（默认选中）
            checkbox_item = QTableWidgetItem()
            checkbox_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, checkbox_item)

            # 名称列（可编辑）
            name_item = QTableWidgetItem(str(file_path))
            self.table.setItem(row, 1, name_item)

            # 地址列（可编辑）
            address_item = QTableWidgetItem("0x00000000")
            address_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, address_item)

            # 大小列（可编辑）
            size_item = QTableWidgetItem(formatted_size)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, size_item)

        elif file_path.suffix == ".kdimg":
            self.img_list_mode = "kdimg"
            # 清空表格
            self.table.clearContents()

            # 解析 kdimge
            logger.info(f"正在解析 KDIMG 文件: {file_path.name}")
            items = cmd_kdimg.get_kdimage_items(file_path)

            if items is None or items.size() == 0:
                logger.error("解析 KDIMG 文件失败！")
                return

            # **先设置表格行数**
            self.table.setRowCount(len(items.data))  # 关键代码

            # 添加到表格
            row = 0
            for item in items.data:
                logger.debug(f"添加镜像: {item}")

                # 复选框列（默认选中）
                checkbox_item = QTableWidgetItem()
                checkbox_item.setCheckState(Qt.Checked)
                self.table.setItem(row, 0, checkbox_item)

                # 名称列（可编辑）
                name_item = QTableWidgetItem(item.partName)
                self.table.setItem(row, 1, name_item)

                # 地址列（可编辑）
                # 格式化地址为 0x 开头的十六进制字符串
                hex_address = f"0x{item.partOffset:08X}"
                address_item = QTableWidgetItem(hex_address)
                address_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 2, address_item)

                # 大小列（可编辑）
                formatted_size = self.format_size(item.partSize)
                size_item = QTableWidgetItem(formatted_size)
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 3, size_item)
                row += 1

    def format_size(self, size):
        """以 KB、MB、GB 格式化文件大小"""
        if size >= 1 << 30:
            return f"{size / (1 << 30):.2f} GB"
        elif size >= 1 << 20:
            return f"{size / (1 << 20):.2f} MB"
        elif size >= 1 << 10:
            return f"{size / (1 << 10):.2f} KB"
        else:
            return f"{size} bytes"

    def create_table(self):
        # 创建一个 QGroupBox 作为容器
        self.image_table_groupbox = QGroupBox("镜像文件内容：")
        layout = QVBoxLayout(self.image_table_groupbox)  # 将布局应用到 QGroupBox

        # 创建 QTableWidget
        self.table = QTableWidget()
        self.table.setRowCount(1)
        self.table.setColumnCount(4)
        # 设置列宽可伸缩
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        # 设置表头（初始化为空，由update_table_headers方法更新）
        self.table.setColumnCount(4)
        # 初始化时设置为空标签，等待update_ui_text调用
        self.table.setHorizontalHeaderLabels(["", "", "", ""])

        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Fixed
        )  # 第一列固定
        self.table.setColumnWidth(0, 40)  # 具体设定宽度
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )  # 让第二列自动拉伸

        # 在表头的第一列中添加“全选”复选框
        self.add_header_checkbox()

        # 美化表格
        self.style_table()

        # 将表格添加到 QGroupBox 的布局中
        layout.addWidget(self.table)

        return self.image_table_groupbox  # 返回 QGroupBox

    def add_header_checkbox(self):
        # 获取水平表头
        header = self.table.horizontalHeader()

        # 创建一个 QCheckBox 作为表头的复选框
        self.header_checkbox = QCheckBox()
        # 初始化时不设置文本，等待update_ui_text调用
        self.header_checkbox.setStyleSheet(CommonWidgetStyles.QCheckBox_css())
        self.header_checkbox.stateChanged.connect(self.toggle_all_checkboxes)

        # 将复选框添加到表头
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.addWidget(self.header_checkbox)
        header_layout.setAlignment(Qt.AlignCenter)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)

        self.table.setHorizontalHeaderItem(0, QTableWidgetItem())
        self.table.setCellWidget(-1, 0, header_widget)

    def style_table(self):
        """设置表格的样式"""
        # 设置表格整体样式
        self.table.setStyleSheet(CommonWidgetStyles.QTableWidgetItem_css())

        # 设置交替行颜色
        self.table.setAlternatingRowColors(True)

        # 设置表头属性
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)  # 表头文字居中对齐
        # header.setSectionResizeMode(QHeaderView.Stretch)  # 表头自适应宽度

        # 设置表格属性
        self.table.setShowGrid(True)  # 显示网格线
        self.table.setGridStyle(Qt.SolidLine)  # 网格线样式
        self.table.setSelectionMode(QTableWidget.SingleSelection)  # 单选模式
        self.table.setSelectionBehavior(QTableWidget.SelectRows)  # 选中整行
        # self.table.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止编辑

    def toggle_all_checkboxes(self, state):
        """根据表头复选框的状态，设置所有行的复选框状态"""
        for row in range(self.table.rowCount()):
            checkbox_item = self.table.item(row, 0)
            if checkbox_item:
                checkbox_item.setCheckState(state)

    def create_target_media_region(self):
        # 创建一个 QGroupBox 作为容器
        self.target_media_region_group = QGroupBox("目标存储介质：")

        layout = QHBoxLayout(self.target_media_region_group)  # 将布局应用到 QGroupBox

        # 统一按钮样式
        radio_style = CommonWidgetStyles.QRadioButton_css()
        # 创建单选按钮
        self.radio_emmc = QRadioButton("eMMC")
        self.radio_emmc.setStyleSheet(radio_style)
        self.radio_sdcard = QRadioButton("SD Card")
        self.radio_sdcard.setStyleSheet(radio_style)
        self.radio_nand = QRadioButton("Nand Flash")
        self.radio_nand.setStyleSheet(radio_style)
        self.radio_nor = QRadioButton("NOR Flash")
        self.radio_nor.setStyleSheet(radio_style)
        self.radio_otp = QRadioButton("OTP")
        self.radio_otp.setStyleSheet(radio_style)

        # 将单选按钮添加到布局中
        layout.addWidget(self.radio_emmc)
        layout.addWidget(self.radio_sdcard)
        layout.addWidget(self.radio_nand)
        layout.addWidget(self.radio_nor)
        layout.addWidget(self.radio_otp)

        # 默认选中第一个单选按钮
        self.radio_sdcard.setChecked(True)

        return self.target_media_region_group

    def create_device_list_region(self):
        # 创建一个 QGroupBox 作为容器
        self.device_list_region_group = QGroupBox("设备列表：")
        layout = QVBoxLayout(self.device_list_region_group)

        # 添加USB设备列表
        self.device_address_combo = QComboBox()
        self.device_address_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,  # 水平扩展
            QtWidgets.QSizePolicy.Fixed,  # 垂直固定
        )
        # self.refresh_device_list()  # 加载 USB 设备列表,默认不加载，k230_flash 会自动检测第1个设备，更方便
        self.list_device_button = QPushButton("刷新设备列表")
        self.list_device_button.setFixedWidth(130)  # 固定宽度
        self.list_device_button.setStyleSheet(CommonWidgetStyles.QPushButton_css())
        self.list_device_button.clicked.connect(self.on_list_device_button_clicked)

        # **设备地址布局**
        device_layout = QHBoxLayout()
        device_layout.addWidget(self.device_address_combo, stretch=5)
        device_layout.addWidget(self.list_device_button, stretch=2)  # 添加刷新按钮
        device_layout.setContentsMargins(0, 0, 0, 0)  # 减少边距

        # 添加至布局
        layout.addLayout(device_layout)

        # 创建并添加帮助提示组件
        help_tip = self.create_device_help_tip()
        layout.addWidget(help_tip)

        return self.device_list_region_group

    def create_progress_bar_layout(self):
        # 创建一个 QWidget 作为容器
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setAlignment(Qt.AlignVCenter)

        # 创建进度条
        self.progress_bar: QProgressBar = QProgressBar()
        self.progress_bar.setValue(0)  # 设置初始值

        # 设置进度条样式
        self.progress_bar.setStyleSheet(CommonWidgetStyles.QProgressBar_css())

        # 设置固定高度（可选）
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setAlignment(Qt.AlignVCenter)

        layout.addWidget(self.progress_bar)

        # 创建 "开始烧录" 按钮
        self.start_button = QPushButton()  # 初始化时不设置文本，等待update_ui_text调用
        self.advanced_setting_button = QPushButton("高级设置")
        layout.addWidget(self.start_button)
        layout.addWidget(self.advanced_setting_button)
        qbtn_css = CommonWidgetStyles.QPushButton_css()
        self.start_button.setStyleSheet(qbtn_css)
        self.advanced_setting_button.setStyleSheet(qbtn_css)

        self.start_button.clicked.connect(self.start_programming_flash)
        self.advanced_setting_button.clicked.connect(self.show_advanced_settings)

        return widget

    def create_log_output_groupbox(self):
        # 创建 QGroupBox
        self.log_output_groupbox = QGroupBox("日志输出：")

        # 创建 QTextEdit 用于日志输出
        # self.log_output = QTextEdit()
        # self.log_output.setReadOnly(True)

        # 创建垂直布局
        layout = QHBoxLayout()
        layout.addWidget(self.log_output)
        layout.addWidget(self.create_gif_display())

        # 将布局应用到 QGroupBox
        self.log_output_groupbox.setLayout(layout)

        return self.log_output_groupbox

    def create_gif_display(self):
        gif_label = QLabel()
        gif_label.setFixedSize(270, 320)
        # 设置固定的宽度
        # gif_label.setFixedWidth(200)
        # 设置 gif_label 最小尺寸
        # gif_label.setMinimumSize(350, 420)
        gif_label.setAlignment(Qt.AlignCenter)
        # 设置等比例综放显示
        gif_label.setScaledContents(True)

        movie = QMovie(":/icons/assets/flash_animation.gif")
        gif_label.setMovie(movie)
        movie.start()

        return gif_label

    def start_programming_flash(self):
        # debugpy.debug_this_thread()

        """开始烧录按钮点击处理"""
        # 如果当前在等待设备状态，则取消等待
        if self.waiting_for_device:
            self.cancel_waiting_for_device()
            return

        # 验证输入
        if not self.validate_inputs():
            return

        # 检查是否有选中的设备
        device_path = self.device_address_combo.currentText()
        if not device_path or device_path.strip() == "":
            # 没有设备，进入等待模式
            self.start_waiting_for_device()
            return

        # 有设备，直接开始烧录
        self.start_actual_flash()

    def start_waiting_for_device(self):
        """开始等待设备模式"""
        self.waiting_for_device = True
        self.start_button.setText(self.get_translated_text("cancel_waiting"))
        self.progress_bar.setFormat(self.get_translated_text("waiting_device"))
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(CommonWidgetStyles.QProgressBar_css())

        logger.info("没有检测到设备，等待设备连接...")

        # 启动等待定时器，每秒检查一次设备
        self.waiting_timer = QTimer()
        self.waiting_timer.timeout.connect(self.check_device_connection)
        self.waiting_timer.start(1000)  # 每秒检查一次

    def cancel_waiting_for_device(self):
        """取消等待设备"""
        self.waiting_for_device = False
        if self.waiting_timer:
            self.waiting_timer.stop()
            self.waiting_timer = None

        self.start_button.setText(self.get_translated_text("start_flash"))
        self.progress_bar.setFormat(self.get_translated_text("progress_format"))
        self.progress_bar.setValue(0)

        logger.info("用户取消等待设备")

    def check_device_connection(self):
        """检查设备连接状态"""
        if not self.waiting_for_device:
            return

        # 检查是否有设备连接
        device_path = self.device_address_combo.currentText()
        if device_path and device_path.strip() != "":
            # 发现设备，自动开始烧录
            logger.info(f"检测到设备: {device_path}，开始烧录")
            self.cancel_waiting_for_device()
            self.start_actual_flash()

    def start_actual_flash(self):
        """开始实际的烧录过程"""
        self.progress_bar.setStyleSheet(CommonWidgetStyles.QProgressBar_css())
        self.progress_bar.setFormat("%p%")

        config = utils.load_config()
        log_level = config.get("AdvancedSettings", "log_level", fallback="INFO")
        custom_loader = config.get("AdvancedSettings", "custom_loader", fallback=None)
        loader_address = int(
            config.get("AdvancedSettings", "loader_address", fallback="0x80360000"), 0
        )
        auto_reboot = config.getboolean(
            "AdvancedSettings", "auto_reboot", fallback=False
        )

        device_path = self.device_address_combo.currentText()

        logger.debug(f"当前日志等级: {log_level}")
        if custom_loader:
            logger.debug(f"使用自定义 Loader 文件: {custom_loader}")
        if auto_reboot:
            logger.debug("启用了自动重启功能")

        # 收集参数
        params = {
            "auto_reboot": auto_reboot,
            "device_path": device_path,
            "custom_loader": custom_loader,  # 可根据需要扩展
            "loader_address": loader_address,
            "log_level": log_level,
            "media_type": self.get_media_type(),
            "kdimg-path": (
                self.file_path_edit.text() if self.img_list_mode == "kdimg" else None
            ),
            "addr_filename": self.get_addr_filename_pairs(),
            "selected_partitions": (
                self.get_selected_partition_names()
                if self.img_list_mode == "kdimg"
                else None
            ),
        }

        logger.info(f"开始烧录: {params}")

        # 模拟烧录
        if USE_DUMMY_FLASHING:
            # 初始化模拟参数
            self.sim_elapsed = 0
            self.progress_bar.setValue(0)
            self.start_button.setEnabled(False)

            # 创建并启动定时器
            self.sim_timer = QTimer()
            self.sim_timer.timeout.connect(self.update_simulation)
            self.sim_timer.start(1000)  # 每秒触发一次

            logger.debug("开始模拟烧录...")
        else:
            # 创建并启动线程
            self.flash_thread = FlashThread(params)
            self.flash_thread.progress_signal.connect(self.update_progress_bar)
            self.flash_thread.finished.connect(self.handle_flash_result)
            self.flash_thread.error_signal.connect(
                self.display_flash_error
            )  # Connect new error signal
            self.flash_thread.start()

        # 禁用按钮防止重复点击
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(False)

    def update_simulation(self):
        """定时器回调函数，更新模拟进度"""
        self.sim_elapsed += 1
        progress = int((self.sim_elapsed / self.sim_total_time) * 100)

        # 更新进度条
        self.progress_bar.setValue(progress)

        # 记录日志
        logger.debug(
            f"烧录进度: {progress}% ({self.sim_elapsed}/{self.sim_total_time}秒)"
        )

        # 完成处理
        if self.sim_elapsed >= self.sim_total_time:
            self.sim_timer.stop()
            self.start_button.setEnabled(True)
            self.start_button.setText(self.get_translated_text("start_flash"))
            logger.success("烧录模拟完成！")

    def validate_inputs(self):
        """验证输入有效性"""
        if not self.file_path_edit.text():
            self.append_log("错误：请先选择镜像文件！")
            return False

        # 对于 img 模式，需要检查是否选中了地址文件对
        # 对于 kdimg 模式，如果没有选中任何分区，则烧录所有分区
        if self.img_list_mode == "img" and len(self.get_addr_filename_pairs()) == 0:
            self.append_log("错误：请配置烧录地址！")
            return False

        return True

    def get_media_type(self):
        """获取选择的介质类型"""
        media_map = {
            "eMMC": "EMMC",
            "SD Card": "SDCARD",
            "Nand Flash": "SPINAND",
            "NOR Flash": "SPINOR",
            "OTP": "OTP",
        }
        return media_map.get(self.get_selected_media(), None)  # 添加默认值

    def get_selected_media(self):
        """获取选中的单选按钮文本"""
        if self.target_media_region_group is None:
            return "SD Card"

        for radio in [
            self.radio_emmc,
            self.radio_sdcard,
            self.radio_nand,
            self.radio_nor,
            self.radio_otp,
        ]:
            if radio.isChecked():
                return radio.text()

    def get_addr_filename_pairs(self):
        """从表格获取地址-文件对"""
        pairs = []
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is not None and cell.checkState() == Qt.Checked:
                address_item = self.table.item(row, 2)
                file_item = self.table.item(row, 1)
                if address_item is not None and file_item is not None:
                    address = int(address_item.text(), 16)
                    file_path = file_item.text()
                    pairs.append((address, file_path))
        return pairs

    def get_selected_partition_names(self):
        """获取选中的分区名列表（仅适用于kdimg模式）"""
        partition_names = []
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is not None and cell.checkState() == Qt.Checked:
                name_item = self.table.item(row, 1)
                if name_item is not None:
                    partition_names.append(name_item.text())
        return partition_names

    def update_progress_bar(self, current, total, progress):
        """更新进度条"""
        if progress is not None:
            self.progress_bar.setFormat("%p%")  # Set format to percentage
            self.progress_bar.setValue(progress)

    def append_log(self, message):
        """添加日志信息"""
        # self.log_output.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        logger.info(message)  # 使用 loguru 记录日志

    def handle_flash_result(self):
        """处理烧录结果"""
        self.start_button.setEnabled(True)
        self.start_button.setText(self.get_translated_text("start_flash"))

    @Slot(str)
    def display_flash_error(self, error_message):
        """显示烧录错误信息，并更新进度条状态"""
        self.progress_bar.setFormat("烧录失败：100%")  # Set format to error message
        self.progress_bar.setValue(
            100
        )  # Reset value or set to a specific error value if desired
        # 设置红色背景（QProgressBar 的 chunk 是进度条填充部分）
        self.progress_bar.setStyleSheet(CommonWidgetStyles.QProgressBar_css_error())
        self.start_button.setEnabled(True)  # Re-enable button on error
        self.start_button.setText(
            self.get_translated_text("start_flash")
        )  # Reset button text

    def refresh_device_list(self):
        """调用 k230_flash -l 获取 USB 设备列表，并保持选中状态"""
        try:
            device_list_json = list_devices()
            device_list = json.loads(device_list_json)
            devices = [dev["port_path"] for dev in device_list]
        except Exception as e:
            logger.error(f"获取设备列表失败: {str(e)}")
            devices = []

        # 保存当前选中的值
        current_selection = self.device_address_combo.currentText()

        # 清空并重新添加
        self.device_address_combo.blockSignals(True)  # 避免触发 indexChanged 信号
        self.device_address_combo.clear()
        self.device_address_combo.addItems(devices)

        # 如果之前的选择还存在，恢复它
        if current_selection in devices:
            self.device_address_combo.setCurrentText(current_selection)
        elif devices:
            # 如果之前的选择已经不存在，则保持默认第一个
            self.device_address_combo.setCurrentIndex(0)

        self.device_address_combo.blockSignals(False)

        # 更新帮助提示的显示状态
        self.update_device_help_tip_visibility()

    def update_device_help_tip_visibility(self):
        """根据设备列表状态更新帮助提示的显示状态"""
        if hasattr(self, "device_help_tip"):
            # 如果设备列表为空，显示帮助提示
            is_device_list_empty = self.device_address_combo.count() == 0
            self.device_help_tip.setVisible(is_device_list_empty)

    def create_device_help_tip(self):
        """创建设备帮助提示组件"""
        self.device_help_tip = QLabel()
        self.device_help_tip.setText(self.get_translated_text("device_help_tip"))

        # 设置优化后的样式
        self.device_help_tip.setStyleSheet(
            """
            QLabel {
                color: #1976D2;
                font-weight: bold;
                padding: 8px 4px;
                border-radius: 4px;
                background-color: transparent;
                font-size: 13px;
            }
            QLabel:hover {
                color: #0D47A1;
                background-color: #E3F2FD;
            }
        """
        )

        # 设置手型光标
        self.device_help_tip.setCursor(Qt.PointingHandCursor)

        # 设置左对齐
        self.device_help_tip.setAlignment(Qt.AlignLeft)

        # 设置尺寸策略，使其自适应内容
        self.device_help_tip.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )

        # 添加鼠标点击事件
        self.device_help_tip.mousePressEvent = self.on_device_help_tip_clicked

        # 初始状态为隐藏
        self.device_help_tip.setVisible(False)

        return self.device_help_tip

    def on_device_help_tip_clicked(self, event):
        """处理帮助提示点击事件"""
        # 只处理左键点击
        if event.button() == Qt.LeftButton:
            # 获取主窗口并调用其打开帮助文档的方法
            main_window = self.get_main_window()
            if main_window and hasattr(main_window, "open_user_manual"):
                main_window.open_user_manual()

    def get_main_window(self):
        """获取主窗口实例"""
        # 遍历父级组件，找到FlashTool主窗口
        widget = self.centralwidget
        while widget:
            parent = widget.parent()
            if parent and hasattr(parent, "open_user_manual"):
                return parent
            widget = parent
        return None

    def show_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self)

        # 连接信号和slot，实现日志级别实时更新
        dialog.log_level_changed.connect(utils.update_log_level)

        if dialog.exec():
            logger.info(f"用户已修改高级设置")

    def on_list_device_button_clicked(self):
        self.refresh_device_list()
        self.list_device_button.setText("已刷新")
        QTimer.singleShot(1000, lambda: self.list_device_button.setText("刷新设备列表"))


# 线程类，防止 GUI 卡死
class FlashThread(QThread):
    progress_signal = Signal(int, int, float)  # (当前值, 总量, 进度)
    error_signal = Signal(str)  # New signal for errors

    def __init__(self, params):
        super().__init__()
        self.params = params

    def get_selected_partitions(self):
        """获取选中的分区名列表（仅适用于kdimg模式）"""
        return self.params.get("selected_partitions", [])

    def run(self):
        # 调试模式下，可以打开此句话，以便在此处设置断点

        def gui_progress_callback(current, total):
            percent = int(current / total * 100) if total else 0
            logger.debug(f"progress: {percent}")
            self.progress_signal.emit(current, total, percent)

        # 构造命令行参数
        args_list = []
        if self.params["device_path"]:
            args_list.extend(["--device-path", self.params["device_path"]])
        if self.params["custom_loader"]:
            args_list.extend(
                ["--custom-loader", "--loader-file", self.params["loader_file"]]
            )
        if self.params["loader_address"]:
            args_list.extend(["--loader-address", hex(self.params["loader_address"])])
        if self.params["log_level"]:
            args_list.extend(["--log-level", self.params["log_level"]])
        if self.params["media_type"]:
            args_list.extend(["-m", self.params["media_type"]])
        if self.params.get("auto_reboot", False):
            args_list.append("--auto-reboot")
        if self.params["kdimg-path"]:
            # 对于kdimg文件，添加文件路径
            args_list.append(self.params["kdimg-path"])

            # 如果有选中的分区，添加 --kdimg-select 参数
            selected_partitions = self.get_selected_partitions()
            if selected_partitions:
                args_list.append("--kdimg-select")
                args_list.extend(selected_partitions)
        else:
            # 处理 addr_filename_pairs 模式的文件参数
            for addr, filename in self.params["addr_filename"]:
                args_list.extend([hex(addr), filename])

        try:
            logger.info("准备开始烧录...")
            logger.info(f"pass args_list to k230_flash: {args_list}")
            cmd_main.main(
                args_list,
                progress_callback=gui_progress_callback,
                use_external_logging=True,
            )
            logger.info("烧录成功！")
        except SystemExit as e:
            error_message = f"烧录失败: cmd_main 试图退出 GUI，错误代码: {e.code}"
            logger.error(error_message)
            self.error_signal.emit(error_message)  # Emit error signal
        except Exception as e:
            error_message = f"烧录失败: {str(e)}"
            logger.error(error_message)
            self.error_signal.emit(error_message)  # Emit error signal
