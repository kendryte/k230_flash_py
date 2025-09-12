import json
from pathlib import Path

import PySide6.QtWidgets as QtWidgets
import utils as utils
from advanced_settings import AdvancedSettingsDialog
from common_widget_sytles import CommonWidgetStyles
from loguru import logger
from PySide6 import QtGui
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
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
    QLayout,
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

import k230_flash.file_utils as cmd_file_utils
import k230_flash.kdimage as cmd_kdimg
import k230_flash.main as cmd_main
from k230_flash import *
from k230_flash.api import list_devices


class BatchFlash(QMainWindow):
    def __init__(self):
        super().__init__()

        # 移除日志输出控件的创建，因为我们不再需要它
        self.log_output = None

        self.ui = Ui_BatchFlashWindow(log_output_widget=self.log_output)
        self.ui.setupUi(self)

    @Slot(str)
    def append_log_content(self, content):
        """由于移除了日志输出窗口，这里不需要追加日志内容"""
        pass


class DeviceFlashThread(QThread):
    progress_signal = Signal(str, int, int, float)  # (设备路径, 当前值, 总量, 进度)
    finished_signal = Signal(str, bool, str)  # (设备路径, 是否成功, 错误信息)

    def __init__(self, device_path, params):
        super().__init__()
        self.device_path = device_path
        self.params = params

    def get_selected_partitions(self):
        """获取选中的分区名列表（仅适用于kdimg模式）"""
        return self.params.get("selected_partitions", [])

    def run(self):
        def gui_progress_callback(current, total):
            percent = int(current / total * 100) if total else 0
            logger.debug(f"设备 {self.device_path} 进度: {percent}%")
            self.progress_signal.emit(self.device_path, current, total, percent)

        # 构造命令行参数
        args_list = []
        args_list.extend(["--device-path", self.device_path])
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
            logger.info(f"设备 {self.device_path} 准备开始烧录...")
            logger.info(f"传递参数给 k230_flash: {args_list}")
            cmd_main.main(
                args_list,
                progress_callback=gui_progress_callback,
                use_external_logging=True,
            )
            logger.info(f"设备 {self.device_path} 烧录成功！")
            self.finished_signal.emit(self.device_path, True, "")
        except SystemExit as e:
            # 捕获SystemExit异常，避免程序退出
            error_message = f"设备 {self.device_path} 烧录失败: cmd_main 试图退出 GUI，错误代码: {e.code}"
            logger.error(error_message)
            self.finished_signal.emit(self.device_path, False, error_message)
        except Exception as e:
            error_message = f"设备 {self.device_path} 烧录失败: {str(e)}"
            logger.error(error_message)
            self.finished_signal.emit(self.device_path, False, error_message)


class Ui_BatchFlashWindow(object):
    def __init__(self, log_output_widget):
        # 由于移除了日志输出窗口，这里不再需要log_output_widget参数
        self.log_output = None

    def setupUi(self, BatchFlashWindow):
        if not BatchFlashWindow.objectName():
            BatchFlashWindow.setObjectName("BatchFlashWindow")

        # 创建 centralwidget
        self.centralwidget = QWidget(BatchFlashWindow)
        self.centralwidget.setObjectName("centralwidget")
        BatchFlashWindow.setCentralWidget(self.centralwidget)

        # 创建垂直布局
        main_layout = QVBoxLayout(self.centralwidget)
        main_layout.addWidget(self.create_file_browser_region())

        # 调整镜像文件内容区域的高度
        table_widget = self.create_table()
        table_widget.setMaximumHeight(200)  # 设置最大高度为200像素
        main_layout.addWidget(table_widget)

        # 创建上半部分区域（包含目标介质和批量烧录控制）
        top_layout = QHBoxLayout()
        # 设置目标介质区域
        target_media_widget = self.create_target_media_region()
        # 创建批量烧录控制区域（替代原来的设备列表区域）
        batch_control_widget = self.create_batch_control_region()
        top_layout.addWidget(target_media_widget, stretch=3)
        top_layout.addWidget(batch_control_widget, stretch=1)
        main_layout.addLayout(top_layout)

        # 创建下半部分区域（设备烧录进度）
        device_progress_widget = self.create_device_progress_region()
        main_layout.addWidget(device_progress_widget)

        # 新增状态变量
        self.flash_threads = {}  # 存储每个设备的烧录线程
        self.addr_filename_pairs = []
        self.img_list_mode = None
        self.known_devices = set()  # 跟踪已知设备，实现累积增量更新
        self.device_states = (
            {}
        )  # 跟踪设备状态 {'device_path': 'ready'/'disabled'/'flashing'/'success'/'failed'}
        

        # 设备相关状态（移除了device_checkboxes和device_status_labels）
        # self.device_checkboxes = {}  # 存储设备复选框
        self.device_progress_bars = {}  # 存储设备进度条
        # self.device_status_labels = {}  # 存储设备状态标签

        # 自动烧录模式状态
        self.auto_flash_mode = False

        # 新增：定时器，1 秒刷新设备列表和进度区域
        self.device_refresh_timer = QTimer(BatchFlashWindow)
        self.device_refresh_timer.timeout.connect(self.refresh_device_list)
        self.device_refresh_timer.start(1000)  # 每 1000ms 调用一次

        # 初始化界面文本（必须在所有UI元素创建完成后调用）
        self.update_ui_text()

    def set_device_state(self, device_path, state):
        """设置设备状态"""
        old_state = self.device_states.get(device_path, "unknown")
        # 如果正在烧录中，因为会有bootm至uboot切换，update device list时会有missed device, 所以在烧录进行中时，禁止更新状态
        if old_state == "flashing" and device_path in self.flash_threads:
            logger.debug("只有烧录线程退出后，才能设置新状态: {device_path}")
            return
        self.device_states[device_path] = state
        logger.debug(f"设备状态变更: {device_path} 从 {old_state} 变为 {state}")

    def get_device_state(self, device_path):
        """获取设备状态"""
        state = self.device_states.get(device_path, "unknown")
        logger.debug(f"查询设备状态: {device_path} 当前状态为 {state}")
        return state

    def is_device_in_state(self, device_path, state):
        """检查设备是否处于指定状态"""
        current_state = self.get_device_state(device_path)
        result = current_state == state
        logger.debug(f"检查设备状态: {device_path} 是否为 {state}: {result}")
        return result

    def update_ui_text(self):
        self.image_file_label.setText(
            QCoreApplication.translate("BatchFlash", "镜像文件：")
        )
        self.file_dialog_button.setText(
            QCoreApplication.translate("BatchFlash", "添加镜像文件")
        )
        self.image_table_groupbox.setTitle(
            QCoreApplication.translate("BatchFlash", "镜像文件内容：")
        )

        self.target_media_region_group.setTitle(
            QCoreApplication.translate("BatchFlash", "目标存储介质：")
        )
        # 移除设备列表区域的标题设置，因为我们不再需要设备列表区域
        # self.device_list_region_group.setTitle(
        #     QCoreApplication.translate("BatchFlash", "设备列表：")
        # )
        # self.list_device_button.setText(
        #     QCoreApplication.translate("BatchFlash", "刷新设备列表")
        # )

        self.batch_control_group.setTitle(
            QCoreApplication.translate("BatchFlash", "批量烧录控制：")
        )
        self.start_button.setText(QCoreApplication.translate("BatchFlash", "开始烧录"))
        # 根据当前状态设置自动烧录复选框的文本
        if self.auto_flash_mode:
            self.auto_flash_checkbox.setText(
                QCoreApplication.translate("BatchFlash", "取消自动烧录")
            )
        else:
            self.auto_flash_checkbox.setText(
                QCoreApplication.translate("BatchFlash", "自动烧录")
            )
        # 移除高级设置按钮的文本设置
        # self.advanced_setting_button.setText(
        #     QCoreApplication.translate("BatchFlash", "高级设置")
        # )

        self.device_progress_group.setTitle(
            QCoreApplication.translate("BatchFlash", "设备烧录进度：")
        )

        # 移除对日志输出控件的引用，因为我们已经移除了日志输出窗口
        # self.log_output_groupbox.setTitle(
        #     QCoreApplication.translate("BatchFlash", "日志输出：")
        # )

        # 更新表格头部标签
        self.update_table_headers()

        # 移除了复选框文本更新，因为我们已经移除了复选框
        # if hasattr(self, "header_checkbox"):
        #     self.header_checkbox.setText(
        #         QCoreApplication.translate("BatchFlash", "全选")
        #     )

    def update_table_headers(self):
        """更新表格头部标签"""
        if hasattr(self, "table"):
            headers = [
                "",  # 第一列空白
                QCoreApplication.translate("BatchFlash", "镜像名称"),
                QCoreApplication.translate("BatchFlash", "烧录地址"),
                QCoreApplication.translate("BatchFlash", "镜像大小"),
            ]
            self.table.setHorizontalHeaderLabels(headers)

    def create_file_browser_region(self):
        # 创建一个 QWidget 作为容器
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # 创建 "镜像" 标签
        self.image_file_label = QLabel(
            QCoreApplication.translate("BatchFlash", "镜像文件：")
        )
        layout.addWidget(self.image_file_label)

        # 创建 QLineEdit 用于显示文件路径
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)  # 设置为只读
        layout.addWidget(self.file_path_edit)

        # 创建文件选择按钮
        self.file_dialog_button = QPushButton(
            QCoreApplication.translate("BatchFlash", "添加镜像文件")
        )
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
            caption=QCoreApplication.translate("BatchFlash", "选择镜像文件"),
            dir=last_image_path,  # Set initial directory
            filter=QCoreApplication.translate(
                "BatchFlash", "镜像文件 (*.bin *.img *.kdimg *.zip *.gz *.tgz)"
            ),
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

            # 空白列（移除了复选框）
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

                # 空白列（移除了复选框）
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
        self.image_table_groupbox = QGroupBox(
            QCoreApplication.translate("BatchFlash", "镜像文件内容：")
        )
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

        # 移除了表头复选框的添加

        # 美化表格
        self.style_table()

        # 将表格添加到 QGroupBox 的布局中
        layout.addWidget(self.table)

        return self.image_table_groupbox  # 返回 QGroupBox

    # 移除了add_header_checkbox方法

    def style_table(self):
        """设置表格的样式"""
        # 设置表格整体样式
        self.table.setStyleSheet(CommonWidgetStyles.QTableWidgetItem_css())

        # 设置交替行颜色
        self.table.setAlternatingRowColors(True)

        # 设置表头属性
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)  # 表头文字居中对齐

        # 设置表格属性
        self.table.setShowGrid(True)  # 显示网格线
        self.table.setGridStyle(Qt.SolidLine)  # 网格线样式
        self.table.setSelectionMode(QTableWidget.SingleSelection)  # 单选模式
        self.table.setSelectionBehavior(QTableWidget.SelectRows)  # 选中整行

    # 移除了toggle_all_checkboxes方法

    def create_target_media_region(self):
        # 创建一个 QGroupBox 作为容器
        self.target_media_region_group = QGroupBox(
            QCoreApplication.translate("BatchFlash", "目标存储介质：")
        )

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

    def create_batch_control_region(self):
        # 创建一个 QGroupBox 作为容器
        self.batch_control_group = QGroupBox(
            QCoreApplication.translate("BatchFlash", "批量烧录控制：")
        )
        layout = QVBoxLayout(self.batch_control_group)
        layout.setSpacing(10)  # 增加按钮之间的间距

        # 创建 "开始烧录" 按钮
        self.start_button = QPushButton(
            QCoreApplication.translate("BatchFlash", "开始烧录")
        )
        self.start_button.setStyleSheet(CommonWidgetStyles.QPushButton_Flash_css())
        self.start_button.clicked.connect(self.start_batch_flash)
        # 增大按钮高度
        self.start_button.setFixedHeight(60)

        # 创建 "自动烧录" 复选框
        self.auto_flash_checkbox = QCheckBox(
            QCoreApplication.translate("BatchFlash", "自动烧录")
        )
        self.auto_flash_checkbox.stateChanged.connect(self.toggle_auto_flash_mode)
        # 设置复选框样式
        self.auto_flash_checkbox.setStyleSheet("QCheckBox { font-size: 14px; }")

        layout.addWidget(self.start_button)
        layout.addWidget(self.auto_flash_checkbox)
        # 移除高级设置按钮
        # layout.addWidget(self.advanced_setting_button)

        return self.batch_control_group

    def create_device_progress_region(self):
        # 创建一个 QGroupBox 作为容器
        self.device_progress_group = QGroupBox(
            QCoreApplication.translate("BatchFlash", "设备烧录进度：")
        )

        # 创建一个滚动区域以容纳大量设备
        self.device_progress_scroll = QtWidgets.QScrollArea()
        self.device_progress_scroll.setWidgetResizable(True)
        self.device_progress_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 创建一个widget作为滚动区域的内容
        self.device_progress_content = QWidget()
        # 使用流式布局来平铺设备图标
        self.device_progress_layout = FlowLayout(self.device_progress_content)

        # 设置布局的间距和边距
        self.device_progress_layout.setSpacing(10)  # 控件间距
        self.device_progress_layout.setContentsMargins(10, 10, 10, 10)

        # 将内容widget设置到滚动区域
        self.device_progress_scroll.setWidget(self.device_progress_content)

        # 创建主布局并添加滚动区域
        layout = QVBoxLayout(self.device_progress_group)
        layout.addWidget(self.device_progress_scroll)
        layout.setContentsMargins(0, 0, 0, 0)

        return self.device_progress_group

    def start_batch_flash(self):
        """开始批量烧录"""
        # 禁用开始按钮，防止重复点击
        self.start_button.setEnabled(False)
        self.start_button.setText(QCoreApplication.translate("BatchFlash", "烧录中..."))
        # disable flash checkbox
        self.auto_flash_checkbox.setEnabled(False)

        # 验证输入
        if not self.validate_inputs():
            if not self.auto_flash_mode:
                self.start_button.setEnabled(True)
                self.start_button.setText(
                    QCoreApplication.translate("BatchFlash", "开始烧录")
                )
            return

        # 获取所有已知设备中处于ready状态的设备（只处理点击时的ready设备）
        ready_devices = [
            device
            for device in self.known_devices
            if self.is_device_in_state(device, "ready")
        ]
        if not ready_devices:
            logger.warning("没有处于ready状态的设备进行烧录")
            # 重新启用按钮
            self.start_button.setEnabled(True)
            self.start_button.setText(
                QCoreApplication.translate("BatchFlash", "开始烧录")
            )
            return

        # 获取配置参数
        config = utils.load_config()
        log_level = config.get("AdvancedSettings", "log_level", fallback="INFO")
        custom_loader = config.get("AdvancedSettings", "custom_loader", fallback=None)
        loader_address = int(
            config.get("AdvancedSettings", "loader_address", fallback="0x80360000"), 0
        )
        auto_reboot = config.getboolean(
            "AdvancedSettings", "auto_reboot", fallback=False
        )

        # 收集参数
        params = {
            "auto_reboot": auto_reboot,
            "custom_loader": custom_loader,
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

        logger.info(f"开始批量烧录，设备: {ready_devices}")

        # 为每个处于ready状态的设备启动烧录线程
        for device_path in ready_devices:
            if device_path in self.flash_threads:
                logger.warning(f"设备 {device_path} 已在烧录中，跳过")
                continue

            # 更新设备状态为flashing
            self.set_device_state(device_path, "flashing")
            self.update_device_icon(device_path, "flashing")

            # 通知设备控件开始烧录
            if device_path in self.device_progress_bars:
                # 获取对应的设备控件（DeviceIconWidget）
                for i in range(self.device_progress_layout.count()):
                    item = self.device_progress_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if (
                            isinstance(widget, DeviceIconWidget)
                            and widget.device_path == device_path
                        ):
                            widget.start_flashing()
                            break

            # 创建并启动线程
            flash_thread = DeviceFlashThread(device_path, params)
            flash_thread.progress_signal.connect(self.update_device_progress)
            flash_thread.finished_signal.connect(self.handle_device_flash_result)
            flash_thread.start()

            # 保存线程引用
            self.flash_threads[device_path] = flash_thread

    def toggle_auto_flash_mode(self):
        """切换自动烧录模式"""
        self.auto_flash_mode = self.auto_flash_checkbox.isChecked()
        if self.auto_flash_mode:
            self.auto_flash_checkbox.setText(
                QCoreApplication.translate("BatchFlash", "取消自动烧录")
            )
            logger.info("已启用自动烧录模式")

            # 自动烧录模式下，开始按钮始终保持可用
            self.start_button.setEnabled(False)
            self.start_button.setText(
                QCoreApplication.translate("BatchFlash", "烧录中...")
            )

            # 自动开始当前 ready 设备
            self.start_batch_flash_for_new_devices()
        else:
            self.auto_flash_checkbox.setText(
                QCoreApplication.translate("BatchFlash", "自动烧录")
            )
            logger.info("已禁用自动烧录模式")

            # 检查是否所有设备都已完成烧录，如果完成直接恢复按钮，如果未完成，则在所有设备完成后恢复按钮
            if not self.flash_threads:
                # 全部完成烧录：所有设备完成后恢复按钮
                self.start_button.setEnabled(True)
                self.start_button.setText(
                    QCoreApplication.translate("BatchFlash", "开始烧录")
                )
                self.auto_flash_checkbox.setText(
                    QCoreApplication.translate("BatchFlash", "自动烧录")
                )

    def validate_inputs(self):
        """验证输入有效性"""
        if not self.file_path_edit.text():
            logger.error("错误：请先选择镜像文件！")
            return False

        # 对于 img 模式，需要检查是否选中了地址文件对
        # 对于 kdimg 模式，如果没有选中任何分区，则烧录所有分区
        if self.img_list_mode == "img" and len(self.get_addr_filename_pairs()) == 0:
            logger.error("错误：请配置烧录地址！")
            return False

        return True

    def get_selected_devices(self):
        """获取所有已知设备列表"""
        # 返回所有已知设备
        return list(self.known_devices)

    def get_media_type(self):
        """获取选择的介质类型"""
        media_map = {
            "eMMC": "EMMC",
            "SD Card": "SDCARD",
            "Nand Flash": "SPINAND",
            "NOR Flash": "SPINOR",
            "OTP": "OTP",
        }
        selected_media = self.get_selected_media()
        if selected_media is None:
            return None
        return media_map.get(selected_media, None)

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
            # 移除了复选框检查，现在获取所有行的数据
            address_item = self.table.item(row, 2)
            file_item = self.table.item(row, 1)
            if address_item is not None and file_item is not None:
                address = int(address_item.text(), 16)
                file_path = file_item.text()
                pairs.append((address, file_path))
        return pairs

    def get_selected_partition_names(self):
        """获取所有分区名列表（仅适用于kdimg模式，因为移除了复选框）"""
        partition_names = []
        for row in range(self.table.rowCount()):
            # 移除了复选框检查，现在获取所有行的数据
            name_item = self.table.item(row, 1)
            if name_item is not None:
                partition_names.append(name_item.text())
        return partition_names

    def update_device_progress(self, device_path, current, total, progress):
        """更新设备进度条"""
        if device_path in self.device_progress_bars:
            progress_bar = self.device_progress_bars[device_path]
            progress_bar.setValue(progress)

        # 同时更新设备控件的进度显示
        # 获取对应的设备控件（DeviceIconWidget）
        for i in range(self.device_progress_layout.count()):
            item = self.device_progress_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if (
                    isinstance(widget, DeviceIconWidget)
                    and widget.device_path == device_path
                ):
                    widget.update_progress(progress)
                    break

    def handle_device_flash_result(self, device_path, success, error_message):
        """处理设备烧录结果"""
        # 获取线程引用
        thread = self.flash_threads.get(device_path)

        # 等待线程结束并移除已完成的线程
        if thread is not None:
            # 等待线程结束，最多等待5秒
            thread.wait(5000)
            # 从字典中移除线程引用
            del self.flash_threads[device_path]
            logger.debug(f"设备 {device_path} 的烧录线程已结束并移除")

        # 更新设备状态
        if success:
            self.set_device_state(device_path, "success")
            logger.info(f"设备 {device_path} 烧录成功")
        else:
            self.set_device_state(device_path, "failed")
            logger.error(f"设备 {device_path} 烧录失败: {error_message}")

        # 通知设备控件完成烧录
        # 获取对应的设备控件（DeviceIconWidget）
        for i in range(self.device_progress_layout.count()):
            item = self.device_progress_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if (
                    isinstance(widget, DeviceIconWidget)
                    and widget.device_path == device_path
                ):
                    widget.finish_flashing(success)
                    break

        # 检查是否所有设备都已完成烧录
        if not self.flash_threads:
            if not self.auto_flash_mode:
                # 正常模式：所有设备完成后恢复按钮
                self.start_button.setEnabled(True)
                self.start_button.setText(
                    QCoreApplication.translate("BatchFlash", "开始烧录")
                )
                self.auto_flash_checkbox.setEnabled(True)
                self.auto_flash_checkbox.setText(
                    QCoreApplication.translate("BatchFlash", "自动烧录")
                )

    def add_device_to_ui(self, device_path):
        """添加新设备到界面"""
        # 使用从1开始的自然计数作为端口号
        port_number = str(len(self.known_devices))

        # 创建设备图标控件
        device_widget = DeviceIconWidget(device_path, port_number)

        # 保存设备控件引用
        self.device_progress_bars[device_path] = device_widget.progress_bar

        # 将设备控件添加到布局
        self.device_progress_layout.addWidget(device_widget)

        # 初始化设备状态为ready
        self.set_device_state(device_path, "ready")
        
    def update_device_icon(self, device_path, status):
        """更新设备图标状态"""
        # 获取对应的设备控件（DeviceIconWidget）
        for i in range(self.device_progress_layout.count()):
            item = self.device_progress_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if (
                    isinstance(widget, DeviceIconWidget)
                    and widget.device_path == device_path
                ):
                    if status == "disabled":
                        widget.set_disabled()
                    elif status == "ready":
                        widget.set_ready()
                    # 注意：flashing, success, failed 状态由DeviceIconWidget内部处理
                    break

    def refresh_device_list(self):
        """刷新设备列表"""
        try:
            device_list_json = list_devices()
            device_list = json.loads(device_list_json)
            devices = [dev["port_path"] for dev in device_list]
            logger.debug(f"检测到设备: {devices}")
        except Exception as e:
            logger.error(f"获取设备列表失败: {str(e)}")
            devices = []
            return None

        # 记录新添加的设备
        new_devices = []

        # 更新设备状态
        # 1. 标记当前在线的设备为ready状态
        for device in devices:
            if device not in self.known_devices:
                # 新设备，添加到已知设备集合
                self.known_devices.add(device)
                self.set_device_state(device, "ready")
                # 添加新设备到界面
                self.add_device_to_ui(device)
                new_devices.append(device)
                
            else:
                # 已存在的设备，如果之前是disabled状态，则更新为ready状态
                if self.is_device_in_state(device, "disabled"):
                    self.set_device_state(device, "ready")
                    self.update_device_icon(device, "ready")
                    # 如果设备重新连接并且处于烧录状态，标记为新设备以便自动烧录
                    if not self.start_button.isEnabled():
                        new_devices.append(device)
                

        # 2. 标记当前不在线的已知设备为disabled状态
        for device in self.known_devices:
            if device not in devices:
                # 设备已下线，更新状态为disabled
                if not self.is_device_in_state(device, "disabled"):
                    self.set_device_state(device, "disabled")
                    self.update_device_icon(device, "disabled")
                

        # 如果启用了自动烧录模式且当前正在烧录中，自动开始烧录新连接的设备
        if self.auto_flash_mode and not self.start_button.isEnabled():
            # 只处理新添加的设备或重新连接的设备
            for device in new_devices:
                if self.is_device_in_state(device, "ready"):
                    # 为新设备启动烧录
                    self.start_batch_flash_for_new_devices()
                    break  # 只需要调用一次，方法内部会处理所有ready状态的设备

    def show_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self)

        # 连接信号和slot，实现日志级别实时更新
        dialog.log_level_changed.connect(utils.update_log_level)

        if dialog.exec():
            logger.info("用户已修改高级设置")

    def get_translated_text(self, key):
        """获取翻译文本的辅助方法"""
        translations = {
            "start_flash": QCoreApplication.translate("BatchFlash", "开始烧录"),
            "auto_flash": QCoreApplication.translate("BatchFlash", "自动烧录"),
            "stop_auto_flash": QCoreApplication.translate("BatchFlash", "取消自动烧录"),
        }
        return translations.get(key, key)

    def start_batch_flash_for_new_devices(self):
        """为新连接的设备开始批量烧录（自动烧录模式专用）"""
        # 只处理当前处于ready状态的新设备
        ready_devices = [
            device
            for device in self.known_devices
            if self.is_device_in_state(device, "ready")
        ]

        # 如果没有设备需要烧录，直接返回
        if not ready_devices:
            return

        # 获取配置参数
        config = utils.load_config()
        log_level = config.get("AdvancedSettings", "log_level", fallback="INFO")
        custom_loader = config.get("AdvancedSettings", "custom_loader", fallback=None)
        loader_address = int(
            config.get("AdvancedSettings", "loader_address", fallback="0x80360000"), 0
        )
        auto_reboot = config.getboolean(
            "AdvancedSettings", "auto_reboot", fallback=False
        )

        # 收集参数
        params = {
            "auto_reboot": auto_reboot,
            "custom_loader": custom_loader,
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

        logger.info(f"自动烧录新设备，设备: {ready_devices}")

        # 为每个处于ready状态的设备启动烧录线程
        for device_path in ready_devices:
            # 检查设备是否已经在烧录中
            if device_path in self.flash_threads:
                logger.warning(f"设备 {device_path} 已在烧录中，跳过")
                continue

            # 更新设备状态为flashing
            self.set_device_state(device_path, "flashing")
            self.update_device_icon(device_path, "flashing")

            # 通知设备控件开始烧录
            if device_path in self.device_progress_bars:
                # 获取对应的设备控件（DeviceIconWidget）
                for i in range(self.device_progress_layout.count()):
                    item = self.device_progress_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if (
                            isinstance(widget, DeviceIconWidget)
                            and widget.device_path == device_path
                        ):
                            widget.start_flashing()
                            break

            # 创建并启动线程
            flash_thread = DeviceFlashThread(device_path, params)
            flash_thread.progress_signal.connect(self.update_device_progress)
            flash_thread.finished_signal.connect(self.handle_device_flash_result)
            flash_thread.start()

            # 保存线程引用
            self.flash_threads[device_path] = flash_thread


class FlowLayout(QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._spacing = 10

    def setSpacing(self, spacing):
        self._spacing = spacing
        self.update()

    def spacing(self):
        return self._spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Horizontal)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )
        return size

    def _doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self._items:
            wid = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()


class DeviceIconWidget(QWidget):
    def __init__(self, device_path, port_number, parent=None):
        super().__init__(parent)
        self.device_path = device_path
        self.port_number = port_number
        self.current_status = "ready"  # ready, flashing, success, failed, disabled

        # 设置固定大小为160x160
        self.setFixedSize(160, 160)

        # 创建端口号标签
        self.port_label = QLabel(str(port_number), self)
        self.port_label.setStyleSheet(
            "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
        )
        self.port_label.setAlignment(Qt.AlignCenter)
        self.port_label.setGeometry(5, 5, 20, 20)

        # 创建设备路径标签
        self.path_label = QLabel(device_path, self)
        self.path_label.setStyleSheet("color: black; font-size: 12px;")
        self.path_label.setAlignment(Qt.AlignCenter)
        self.path_label.setGeometry(5, 135, 150, 20)

        # 创建进度条（初始隐藏）
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setGeometry(31, 73, 98, 14)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 0px solid grey;
                text-align: center;
                background-color: rgba(255, 255, 255, 180);
            }
            QProgressBar::chunk {
                background-color: #3add36;
                border-radius: 20px;   /* 填充部分也圆角 */
                margin-left: 0px;
                margin-right: 0px;
            }
        """
        )

        # 添加闪烁定时器
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._toggle_blink)
        self.blink_visible = True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        try:
            # 根据状态选择图标
            icon_filename = ":/icons/assets/usb_type_c_ready.png"
            if self.current_status == "flashing":
                icon_filename = ":/icons/assets/usb_type_c_ready.png"
            elif self.current_status == "success":
                icon_filename = ":/icons/assets/usb_type_c_ready.png"
            elif self.current_status == "failed":
                icon_filename = ":/icons/assets/usb_type_c_failed.png"
            elif self.current_status == "disabled":
                icon_filename = ":/icons/assets/usb_type_c_disabled.png"

            # 加载图片
            pixmap = QPixmap()
            pixmap.load(str(icon_filename))
            # 如果设备已禁用，降低图片透明度
            if self.current_status == "disabled":
                painter.setOpacity(0.5)

            # 缩放并绘制图片
            scaled_pixmap = pixmap.scaled(
                160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.drawPixmap(0, 0, scaled_pixmap)
        finally:
            # 确保painter正确结束
            painter.end()

    def _toggle_blink(self):
        """切换端口号标签的可见性以实现闪烁效果"""
        self.blink_visible = not self.blink_visible
        if self.blink_visible:
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 128, 0, 128); border-radius: 2px;"
            )
        else:
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
            )

    def start_flashing(self):
        """开始烧录，显示进度条，更新图标状态"""
        # 停止可能正在运行的闪烁定时器
        if self.blink_timer.isActive():
            self.blink_timer.stop()
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
            )

        self.current_status = "flashing"
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.update()  # 触发重绘以更新图标

    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)

    def finish_flashing(self, success):
        """完成烧录，隐藏进度条，更新图标状态"""
        # 停止可能正在运行的闪烁定时器
        if self.blink_timer.isActive():
            self.blink_timer.stop()
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
            )

        if success:
            self.current_status = "success"
            # 启动闪烁定时器，实现缓慢闪烁效果（500ms间隔）
            self.blink_timer.start(500)
        else:
            self.progress_bar.setVisible(False)
            self.current_status = "failed"

        self.update()  # 触发重绘以更新图标

    def set_disabled(self):
        """设置设备为禁用状态"""
        # 停止可能正在运行的闪烁定时器
        if self.blink_timer.isActive():
            self.blink_timer.stop()
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
            )

        self.current_status = "disabled"
        self.progress_bar.setVisible(False)
        self.update()  # 触发重绘以更新图标

    def set_ready(self):
        """设置设备为就绪状态"""
        # 停止可能正在运行的闪烁定时器
        if self.blink_timer.isActive():
            self.blink_timer.stop()
            self.port_label.setStyleSheet(
                "color: white; font-weight: bold; background-color: rgba(0, 0, 0, 128); border-radius: 2px;"
            )

        self.current_status = "ready"
        self.update()  # 触发重绘以更新图标
