from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class BatchFlash(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(QCoreApplication.translate("BatchFlash", "批量烧录"))
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        self.button = QPushButton(QCoreApplication.translate("BatchFlash", "正在建设中..."), self)
        self.button.setEnabled(False)  # 禁用按钮，仅用于显示

        layout.addWidget(self.button, alignment=Qt.AlignCenter)
        self.setLayout(layout)
