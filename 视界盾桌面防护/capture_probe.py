"""在实际主屏显示临时色块，仅在内存检验遮罩是否进入截图。"""
import sys
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget


def settle():
    loop = QEventLoop()
    QTimer.singleShot(350, loop.quit)
    loop.exec()


def verify_exclusion(capture, overlay):
    background = QWidget()
    background.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    background.setStyleSheet('background-color: rgb(0,255,255);')
    screen = QApplication.primaryScreen()
    geo = screen.geometry()
    background.setGeometry(geo.x()+80, geo.y()+300, 240, 120)
    try:
        overlay.set_masks([], full=False)
        background.show()
        background.raise_()
        settle()
        ratio = screen.devicePixelRatio()
        x, y = int(160*ratio), int(350*ratio)
        before = capture.grab().image[y:y+10, x:x+10]
        if before.shape != (10,10,3) or not np.all(before == [255,255,0]):
            return False
        overlay.set_masks([(80*ratio,300*ratio,240*ratio,120*ratio)])
        overlay.raise_()
        settle()
        after = capture.grab().image[y:y+10, x:x+10]
        return np.array_equal(before, after)
    finally:
        overlay.set_masks([], full=False)
        background.close()


if __name__ == '__main__':
    from screen_capture import ScreenCapture, enable_dpi
    from overlay_window import OverlayWindow
    enable_dpi()
    app = QApplication(sys.argv)
    capture = ScreenCapture()
    overlay = OverlayWindow(app.primaryScreen())
    try:
        passed = verify_exclusion(capture, overlay)
        print('Capture exclusion:', 'PASS' if passed else 'FAIL')
        sys.exit(0 if passed else 1)
    finally:
        overlay.close()
        capture.close()
