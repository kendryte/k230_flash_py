class CommonWidgetStyles:
    """统一管理常用 Qt Widgets 的 CSS 样式"""

    @staticmethod
    def QLineEdit_css():
        return """
            QLineEdit {
                border: 2px solid #3A3A3A;
                border-radius: 6px;
                padding: 5px;
                font-size: 16px;
            }
        """

    @staticmethod
    def QPushButton_css():
        return """
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """

    @staticmethod
    def QProgressBar_css():
        return """
            QProgressBar {
                border: 2px solid #CCCCCC;
                border-radius: 8px;
                background-color: #CCCCCC;
                text-align: center;
                font-weight: bold;
                color: #FFFFFF;
                min-height: 25px;
            }

            QProgressBar::chunk {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x1:1, y1:0,
                    stop:0 #00CC66, 
                    stop:1 #00994D
                );
                border-radius: 6px;
                border: 1px solid #007A3D;
                margin: 1px;
                border-bottom: 2px solid #008040;
            }
        """

    @staticmethod
    def QProgressBar_css_error():
        return """
            QProgressBar {
                border: 2px solid #3A3A3A;
                border-radius: 8px;
                background-color: #F0F0F0;
                text-align: center;
                font-weight: bold;
                color: #FFFFFF;
                min-height: 25px;
            }

            QProgressBar::chunk {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x1:1, y1:0,
                    stop:0 #FF3333, 
                    stop:1 #CC0000
                );
                border-radius: 6px;
                border: 1px solid #990000;
                margin: 1px;
                border-bottom: 2px solid #800000;
            }
        """

    @staticmethod
    def QCheckBox_css():
        return """
            QCheckBox {
                color: white;               /* 复选框文字颜色 */
                font-size: 14px;            /* 复选框文字大小 */
            }
            QCheckBox::indicator {
                width: 16px;                /* 复选框宽度 */
                height: 16px;               /* 复选框高度 */
            }
        """

    @staticmethod
    def QTableWidgetItem_css():
        return """
            QTableWidget {
                background-color: #f0f0f0;  /* 表格背景色 */
                gridline-color: #c0c0c0;    /* 网格线颜色 */
                font-size: 14px;            /* 字体大小 */
                border: 0px solid #404040;  /* 表格边框 */
                border-radius: 10px;        /* 表格圆角 */
                padding: 5px;               /* 表格内边距 */
            }
            QTableWidget::item {
                padding: 5px;               /* 单元格内边距 */
            }
            QTableWidget::item:selected {
                background-color: #a0a0a0;  /* 选中单元格的背景色 */
                color: white;               /* 选中单元格的字体颜色 */
            }
            QHeaderView::section {
                background-color: #404040;  /* 表头背景色 */
                color: white;               /* 表头字体颜色 */
                padding: 5px;               /* 表头内边距 */
                border: 1px solid #606060;  /* 表头边框 */
                font-size: 14px;            /* 表头字体大小 */
            }
            QHeaderView::section:hover {
                background-color: #505050;  /* 表头悬停背景色 */
            }
        """

    @staticmethod
    def QRadioButton_css():
        return """
            QRadioButton {
                padding: 8px 16px;
                border-radius: 6px;
                color: #505050;
                font-weight: 500;
                min-width: 100px;
                min-height: 36px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #808080;
            }
            QRadioButton::indicator:hover {
                border-color: #4CAF50;
            }
            QRadioButton::indicator:checked {
                border-color: #4CAF50;
                background-color: qradialgradient(
                    cx:0.5, cy:0.5, radius:0.4,
                    fx:0.5, fy:0.5,
                    stop:0 #4CAF50,
                    stop:0.5 #4CAF50,
                    stop:0.6 transparent
                );
            }
            QRadioButton:hover {
                background-color: #F5F5F5;
            }
            QRadioButton:checked {
                color: #4CAF50;
                background-color: #E8F5E9;
                border: 1px solid #C8E6C9;
            }
        """
