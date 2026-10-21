"""Brief, finite startup visual; does not load models or imply active protection."""
from PySide6.QtCore import QEasingCurve, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from branding import app_icon


class StartupSplash(QWidget):
    ready = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('视界盾 · 正在打开')
        self.setWindowIcon(app_icon())
        self.setFixedSize(600, 360)
        self.phase = 0.0
        self.finished = False
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(1000)
        self.animation.setEasingCurve(QEasingCurve.Linear)
        self.animation.valueChanged.connect(self.advance)
        self.animation.finished.connect(self.finish)

    def start(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center()-self.rect().center())
        self.show()
        self.animation.start()

    def advance(self, value):
        self.phase = float(value)
        self.update()

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.animation.stop()
        self.hide()
        self.ready.emit()
        self.deleteLater()

    def mousePressEvent(self, event):
        self.finish()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Space):
            self.finish()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fade = min(1.0, self.phase/.18, (1-self.phase)/.16)
        painter.setOpacity(max(0.0, fade))
        painter.setPen(Qt.NoPen)
        for spread in range(12, 0, -2):
            painter.setBrush(QColor(13, 35, 23, 3))
            painter.drawRoundedRect(QRectF(18-spread/2, 20, 564+spread, 322+spread/2), 21, 21)
        painter.setBrush(QColor('#f7f9f6'))
        painter.drawRoundedRect(QRectF(18, 14, 564, 324), 18, 18)
        app_icon().paint(painter, QRect(264, 48, 72, 72))
        face = QFont('Segoe UI')
        face.setPixelSize(33)
        face.setWeight(QFont.DemiBold)
        painter.setFont(face)
        painter.setPen(QColor('#203f30'))
        painter.drawText(QRectF(60, 143, 480, 46), Qt.AlignCenter, 'VisionShield')
        face = QFont('Microsoft YaHei UI')
        face.setPixelSize(16)
        painter.setFont(face)
        painter.setPen(QColor('#627168'))
        painter.drawText(QRectF(60, 198, 480, 28), Qt.AlignCenter, '视界盾 · 屏幕隐私防护')
        face.setPixelSize(12)
        painter.setFont(face)
        painter.setPen(QColor('#7b8980'))
        painter.drawText(QRectF(60, 254, 480, 24), Qt.AlignCenter, '正在打开')
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#dfe7df'))
        painter.drawRoundedRect(QRectF(104, 296, 392, 3), 1.5, 1.5)
        painter.setClipRect(QRectF(104, 296, 392, 3))
        painter.setBrush(QColor('#367855'))
        painter.drawRoundedRect(QRectF(24+472*self.phase, 296, 80, 3), 1.5, 1.5)
        painter.end()
