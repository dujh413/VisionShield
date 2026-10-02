import ctypes
from ctypes import wintypes
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


def exclude_capture(widget):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowDisplayAffinity.restype = wintypes.BOOL
    handle = wintypes.HWND(int(widget.winId()))
    if not user.SetWindowDisplayAffinity(handle, 0x11):
        raise RuntimeError(f'无法排除遮罩采集，Win32错误{ctypes.get_last_error()}')
    actual = wintypes.DWORD()
    if not user.GetWindowDisplayAffinity(handle, ctypes.byref(actual)) or actual.value != 0x11:
        raise RuntimeError('系统不支持WDA_EXCLUDEFROMCAPTURE')


class OverlayWindow(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        self.rectangles = []
        self.full = False
        self.show()
        exclude_capture(self)

    def set_masks(self, rectangles, full=False):
        self.rectangles, self.full = rectangles, full
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 24, 32, 255))
        if self.full:
            painter.drawRect(self.rect())
        else:
            # mss为物理像素；Qt窗口内坐标为逻辑像素。
            ratio = self.devicePixelRatioF()
            for x, y, width, height in self.rectangles:
                painter.drawRect(QRectF((x-6)/ratio, (y-6)/ratio,
                                       (width+12)/ratio, (height+12)/ratio))
