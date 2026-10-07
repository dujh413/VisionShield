"""原生Qt界面配色与开关；不加载图像库或防护模型。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox


STYLE = '''
    QWidget { background: #f7f9f8; color: #182620; font: 14px "Microsoft YaHei UI"; }
    QLabel { background: transparent; }
    QLabel#title { font-size: 24px; font-weight: 600; }
    QLabel#caption, QLabel#detail, QLabel#optionDescription { color: #53645d; }
    QLabel#state { font-size: 28px; font-weight: 600; }
    QLabel#section { font-size: 18px; font-weight: 600; }
    QLabel#optionTitle { font-size: 15px; font-weight: 600; }
    QLabel#summaryLabel { font-weight: 600; }
    QLabel#caption, QLabel#optionDescription { font-size: 12px; }
    QFrame#separator { background: #dde4e0; border: none; }
    QPushButton { border: 1px solid #a7b4ad; border-radius: 6px; padding: 8px 14px; background: #f7f9f8; }
    QPushButton:hover { background: #edf2ef; border-color: #53645d; }
    QPushButton:pressed { background: #dce7e0; }
    QPushButton:focus { border: 2px solid #24724f; padding: 7px 13px; }
    QPushButton#primary, QPushButton#save { background: #203a2d; border-color: #203a2d; color: white; font-weight: 600; }
    QPushButton#primary:hover, QPushButton#save:hover { background: #28513b; }
    QPushButton#segment { padding: 6px 20px; }
    QPushButton#segment:checked { background: #dcebe2; color: #1e6243; border-color: #24724f; font-weight: 600; }
    QPushButton#textAction { border: none; padding: 4px 0; color: #24724f; text-align: left; }
    QPushButton#textAction:focus { border: 1px solid #24724f; padding: 3px 0; }
    QPushButton:disabled { background: #edf0ee; border-color: #d5ded8; color: #65756c; }
    QPushButton#textAction:disabled { color: #65756c; background: transparent; }
    QCheckBox { spacing: 10px; }
    QCheckBox:disabled { color: #65756c; }
    QCheckBox::indicator { width: 18px; height: 18px; }
    QSlider::groove:horizontal { height: 7px; border: none; border-radius: 3px; background: #d2dbd6; }
    QSlider::sub-page:horizontal { background: #24724f; border-radius: 3px; }
    QSlider::handle:horizontal { width: 18px; margin: -8px 0; background: #ffffff; border: 2px solid #24724f; border-radius: 10px; }
    QSlider::handle:horizontal:hover, QSlider::handle:horizontal:focus { background: #dcebe2; }
    QSlider::sub-page:horizontal:disabled { background: #a7b4ad; }
    QSlider::handle:horizontal:disabled { border-color: #a7b4ad; background: #edf0ee; }
    QScrollArea { border: none; }
    QScrollBar:vertical { width: 10px; background: #f7f9f8; margin: 2px; }
    QScrollBar::handle:vertical { background: #a7b4ad; border-radius: 3px; min-height: 28px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
'''


class Switch(QCheckBox):
    """保留原生复选框的键盘、信号与可访问性，绘制开关外观。"""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setFixedSize(58, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(text)

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(3, 4, 52, 26)
        color = '#24724f' if self.isChecked() else '#a7b4ad'
        if not self.isEnabled():
            color = '#8b9d92' if self.isChecked() else '#c8d1cc'
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(track, 13, 13)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(QRectF(31 if self.isChecked() else 5, 6, 22, 22))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#24724f'), 1, Qt.DashLine))
            painter.drawRoundedRect(QRectF(1, 1, 56, 32), 15, 15)
        painter.end()
