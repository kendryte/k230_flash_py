import multiprocessing
import os
import sys
from pathlib import Path

import batch_flash
import PySide6.QtWidgets as QtWidgets
import resources_rc
import single_flash
import utils
from advanced_settings import AdvancedSettingsDialog
from loguru import logger
from PySide6.QtCore import QCoreApplication, Qt, QTranslator
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow

DEBUG = os.getenv("K230_FLASH_LOCAL_DEBUG_MODE", "0") == "1"
if DEBUG:
    # 调试模式下，直接从 src/cmd/main.py 导入
    import sys

    # 调试模式下，把 src 加到 sys.path
    src_path = Path(__file__).parent.parent
    sys.path.insert(0, str(src_path))

from utils import FULL_LOG_FILE_PATH


def setup_gui_logging():
    """
    为GUI应用配置日志系统
    根据PyInstaller GUI模式最佳实践进行配置
    """
    try:
        # 移除loguru的默认处理器
        logger.remove()

        # 在GUI模式下，通常不需要控制台输出（因为sys.stdout可能为None）
        # 但为了调试，可以检查sys.stdout是否可用
        if sys.stdout is not None:
            logger.add(
                sys.stdout,
                level="INFO",
                format="{time:HH:mm:ss.SSS} | {level:<8} | {message}",
            )

        # 添加文件日志处理器
        if FULL_LOG_FILE_PATH:
            logger.add(
                FULL_LOG_FILE_PATH,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name} | {message}",
                rotation="10 MB",
                retention="10 days",
                level="INFO",
                enqueue=True,  # 确保非阻塞文件写入
                encoding="utf-8",  # 确保中文字符正确显示
            )
            logger.info(f"GUI日志系统已初始化，日志文件路径: {FULL_LOG_FILE_PATH}")
        else:
            # 如果无法获取日志文件路径，至少记录警告
            if sys.stdout is not None:
                print("Warning: 无法获取日志文件路径，仅使用控制台输出")

    except Exception as e:
        # 在日志配置失败时，尝试使用print输出错误信息
        if sys.stdout is not None:
            print(f"Warning: GUI日志配置失败: {e}")
            print(f"日志文件路径: {FULL_LOG_FILE_PATH}")


class FlashTool(QMainWindow):
    def __init__(self):
        super().__init__()

        # 初始化日志系统
        # setup_gui_logging()

        # 打包后的资源文件准备
        utils.extract_resource("config.ini")

        # 加载配置
        self.config = utils.load_config()
        log_level = self.config.get("AdvancedSettings", "log_level", fallback="INFO")

        # 根据配置调整日志级别
        utils.update_log_level(log_level)

        logger.info(f"K230 Flash GUI 应用启动，日志级别: {log_level}")

        self.current_mode = "single"
        self.version = utils.get_version()
        self.translator = QTranslator()

        # 读取当前的语言设置
        self.current_language = self.config.get("General", "language", fallback="zh")

        # 设置启动时窗口最大化
        # self.setWindowState(Qt.WindowMaximized)
        # 设置窗口大小
        self.resize(1080, 960)

        self.init_ui()
        self.show_single_flash()

        self.load_language(self.current_language)

    def init_ui(self):
        # 创建菜单栏
        self.create_menu_bar()

        # 设置窗口图标
        icon_path = ":/icons/assets/k230_flash_gui_logo.png"
        self.setWindowIcon(QIcon(str(icon_path)))

        # 设置窗口标题
        self.setWindowTitle(self.tr(f"K230 Flash GUI-{self.version}"))

    def create_menu_bar(self):
        # 创建菜单栏
        menu_bar = self.menuBar()

        # 创建文件菜单
        self.file_menu = menu_bar.addMenu("文件(&F)")

        # 创建退出菜单项
        self.exit_action = QAction("退出", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # 创建设置菜单
        self.setting_menu = menu_bar.addMenu("设置(&S)")

        # 创建烧录模式切换二级菜单
        self.flash_mode_menu = self.setting_menu.addMenu("烧录模式(&M)")

        self.action_single_flash = QAction("单机烧录模式", self, checkable=True)
        self.action_batch_flash = QAction("批量烧录模式", self, checkable=True)

        self.flash_mode_menu.addAction(self.action_single_flash)
        self.flash_mode_menu.addAction(self.action_batch_flash)

        # 绑定模式切换
        self.action_single_flash.triggered.connect(lambda: self.set_flash_mode("single"))
        self.action_batch_flash.triggered.connect(lambda: self.set_flash_mode("batch"))

        # 默认选中单机烧录模式
        self.action_single_flash.setChecked(True)

        # 创建高级设置菜单
        self.advanced_setting_action = QAction("高级设置(&A)", self)
        self.setting_menu.addAction(self.advanced_setting_action)
        self.advanced_setting_action.triggered.connect(self.show_advanced_settings)

        # 创建语言选择菜单
        self.language_menu = menu_bar.addMenu("语言/Language(&L)")
        # 创建中文菜单项
        self.action_lang_chinese = QAction("中文(&C)", self, checkable=True)
        self.language_menu.addAction(self.action_lang_chinese)
        # 创建英文菜单项
        self.action_lang_english = QAction("English(&E)", self, checkable=True)
        self.language_menu.addAction(self.action_lang_english)
        # 绑定语言切换
        self.action_lang_chinese.triggered.connect(lambda: self.load_language("zh"))
        self.action_lang_english.triggered.connect(lambda: self.load_language("en"))
        # 设置菜单默认选中状态
        self.action_lang_chinese.setChecked(self.current_language == "zh")
        self.action_lang_english.setChecked(self.current_language == "en")

        # 创建帮助菜单
        self.help_menu = menu_bar.addMenu("帮助(&H)")

        # 创建关于菜单项
        self.about_action = QAction("关于(&A)", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)
        self.about_action.setShortcut("F1")

        # 创建帮助菜单项
        self.user_manual_action = self.help_menu.addAction("使用说明文档")
        self.user_manual_action.triggered.connect(self.open_user_manual)

    def set_flash_mode(self, mode):
        if mode == "single":
            self.show_single_flash()
            self.action_single_flash.setChecked(True)
            self.action_batch_flash.setChecked(False)
        else:
            self.show_batch_flash()
            self.action_single_flash.setChecked(False)
            self.action_batch_flash.setChecked(True)

    def show_single_flash(self):
        self.single_flash_window = single_flash.SingleFlash()
        self.centralwidget = self.single_flash_window
        self.setCentralWidget(self.centralwidget)
        self.current_mode = "single"
        # Call the new method to initialize logging display
        self.single_flash_window.init_logging_display()

    def show_batch_flash(self):
        self.batch_flash_window = batch_flash.BatchFlash()
        self.centralwidget = self.batch_flash_window
        self.setCentralWidget(self.centralwidget)
        self.current_mode = "batch"

    def toggle_mode(self):
        if self.current_mode == "single":
            self.show_batch_flash()
        else:
            self.show_single_flash()

    def load_language(self, language):
        """加载指定语言的翻译文件"""
        if language == "en":
            qm_path = ":/translations/english.qm"
            success = self.translator.load(str(qm_path))  # 确保路径正确
            logger.debug(f"加载英文翻译文件 {qm_path} 结果：{success}")
        else:
            self.translator.load("")  # 清空翻译器，恢复为默认

        QApplication.instance().installTranslator(self.translator)
        self.current_language = language

        # 更新菜单选中状态
        self.action_lang_chinese.setChecked(language == "zh")
        self.action_lang_english.setChecked(language == "en")

        # **更新所有窗口 UI 语言**
        self.update_ui_text()
        if hasattr(self, "single_flash_window"):
            self.single_flash_window.ui.update_ui_text()
        if hasattr(self, "batch_flash_window"):
            self.batch_flash_window.ui.update_ui_text()
        if hasattr(self, "advanced_settings_dialog"):
            self.advanced_settings_dialog.update_ui_text()

        # 保存语言设置
        self.config.set("General", "language", language)
        utils.save_config(self.config)

    def update_ui_text(self):
        """更新界面文本"""
        """更新整个 UI 的文本"""
        self.setWindowTitle(QCoreApplication.translate("FlashTool", f"K230 Flash Tool-{self.version}"))

        # 更新菜单栏
        self.file_menu.setTitle(QCoreApplication.translate("FlashTool", "文件(&F)"))
        self.exit_action.setText(QCoreApplication.translate("FlashTool", "退出"))

        self.setting_menu.setTitle(QCoreApplication.translate("FlashTool", "设置(&S)"))
        # 更新模式切换文本
        self.flash_mode_menu.setTitle(QCoreApplication.translate("FlashTool", "烧录模式(&M)"))
        self.action_single_flash.setText(QCoreApplication.translate("FlashTool", "单机烧录模式"))
        self.action_batch_flash.setText(QCoreApplication.translate("FlashTool", "批量烧录模式"))
        self.advanced_setting_action.setText(QCoreApplication.translate("FlashTool", "高级设置(&A)"))

        self.language_menu.setTitle(QCoreApplication.translate("FlashTool", "语言/Language(&L)"))
        self.action_lang_chinese.setText(QCoreApplication.translate("FlashTool", "中文(&C)"))
        self.action_lang_english.setText(QCoreApplication.translate("FlashTool", "English(&E)"))

        self.help_menu.setTitle(QCoreApplication.translate("FlashTool", "帮助(&H)"))
        self.about_action.setText(QCoreApplication.translate("FlashTool", "关于(&A)"))
        self.user_manual_action.setText(QCoreApplication.translate("FlashTool", "使用说明文档"))

    def show_about_dialog(self):
        """显示关于对话框"""
        QtWidgets.QMessageBox.about(
            self.centralwidget,
            "关于 K230 Flash GUI Tool",
            f"<h1>K230 Flash GUI Tool</h1><p>版本：{self.version}</p><p>作者：huangzhenming@canaan-creative.com</p><p>描述：这是一个用于烧录镜像文件到 K230 开发板的工具。</p>",
        )

    def open_user_manual(self):
        """打开使用说明文档"""
        try:
            # 根据当前语言设置选择相应的PDF文件
            if self.current_language == "en":
                pdf_filename = "k230_flash_gui_en.pdf"
            else:
                pdf_filename = "k230_flash_gui_zh.pdf"
            
            logger.info(f"开始查找PDF文件: {pdf_filename}")
            logger.info(f"sys.frozen: {getattr(sys, 'frozen', False)}")
            
            # 检查多个可能的PDF文件位置（参照get_version_from_file的逻辑）
            if getattr(sys, "frozen", False):
                # PyInstaller打包后的环境
                logger.info(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'None')}")
                logger.info(f"sys.executable: {sys.executable}")
                
                pdf_paths = [
                    Path(sys._MEIPASS) / pdf_filename,  # _internal目录中的资源文件（优先）
                    Path(sys.executable).parent / pdf_filename,  # 与可执行文件同级（备用）
                    Path(sys.executable).parent / ".." / pdf_filename,  # 上一级目录（备用）
                ]
            else:
                # 开发环境，检查多个可能的位置
                current_dir = Path(__file__).parent
                logger.info(f"开发环境当前目录: {current_dir}")
                
                pdf_paths = [
                    current_dir / pdf_filename,  # 当前目录
                    current_dir / ".." / ".." / pdf_filename,  # 项目根目录
                    utils.get_app_config_dir() / pdf_filename,  # 配置目录
                ]
            
            # 按优先级查找PDF文件
            pdf_path = None
            for path in pdf_paths:
                if path.exists():
                    pdf_path = path
                    logger.info(f"找到PDF文件: {pdf_path}")
                    break
            
            if pdf_path:
                if sys.platform == "win32":
                    os.startfile(pdf_path)  # Windows
                elif sys.platform == "darwin":
                    os.system(f"open '{pdf_path}'")  # macOS
                else:
                    os.system(f"xdg-open '{pdf_path}'")  # Linux
                logger.info(f"已打开使用说明文档: {pdf_path}")
            else:
                # 生成详细的错误信息，显示查找的所有路径
                search_paths = "\n".join([f"- {path} (存在: {path.exists()})" for path in pdf_paths])
                
                # 添加环境信息
                env_info = f"\n\n环境信息:\n"
                env_info += f"- sys.frozen: {getattr(sys, 'frozen', False)}\n"
                if hasattr(sys, '_MEIPASS'):
                    env_info += f"- sys._MEIPASS: {sys._MEIPASS}\n"
                env_info += f"- sys.executable: {sys.executable}\n"
                env_info += f"- 当前工作目录: {Path.cwd()}"
                
                QtWidgets.QMessageBox.warning(
                    self, 
                    "文件未找到", 
                    f"无法找到使用说明文档 ({pdf_filename})。\n\n已查找以下位置：\n{search_paths}{env_info}\n\n请检查日志获取更多详细信息。"
                )
                logger.warning(f"找不到PDF文件 {pdf_filename}，已查找路径: {[str(p) for p in pdf_paths]}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "打开文件失败", f"无法打开使用说明文档：{e}")
            logger.error(f"打开PDF文件时出错: {e}", exc_info=True)

    def show_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self)

        # 连接信号和slot，实现日志级别实时更新
        dialog.log_level_changed.connect(utils.update_log_level)

        if dialog.exec():
            logger.debug(f"用户已修改高级设置")
            # 重新加载配置（主要用于其他设置的同步）
            self.config = utils.load_config()
            new_log_level = self.config.get("AdvancedSettings", "log_level", fallback="INFO")
            logger.debug(f"高级设置对话框关闭，当前日志级别: {new_log_level}")


if __name__ == "__main__":
    # PyInstaller多进程保护 - 防止fork bomb现象
    multiprocessing.freeze_support()
    
    # 在应用启动时初始化日志系统
    setup_gui_logging()
    logger.info("K230 Flash GUI 应用正在启动...")

    # macOS 上过滤系统输入法相关的日志输出
    # 注意: 在macOS上运行Qt/PySide6应用时，可能会看到IMKClient相关的系统日志
    # 这是苹果系统输入法框架的正常初始化过程，不是应用程序错误
    if sys.platform == "darwin":
        import os
        # 重定向stderr以减少IMKClient等系统日志
        os.environ['QT_LOGGING_RULES'] = 'qt.qpa.input.methods.debug=false'

    app = QApplication(sys.argv)
    main_window = FlashTool()
    main_window.show()

    logger.info("GUI 主窗口已显示")

    try:
        exit_code = app.exec()
        logger.info(f"K230 Flash GUI 应用正常退出，退出码: {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"GUI 应用遇到错误: {e}")
        sys.exit(1)
