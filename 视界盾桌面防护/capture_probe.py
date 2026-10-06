"""仅在已许可范围内显示小探针，内存检验遮罩排除，不显示整屏遮挡。"""
import sys
import math
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget


class ProbeScopeChanged(RuntimeError):
    """The requested scope changed while the native exclusion probe settled."""


def settle(check_scope=None):
    loop = QEventLoop()
    timer = QTimer()
    if check_scope is not None:
        timer.timeout.connect(lambda: loop.quit() if not check_scope() else None)
        timer.start(20)
    QTimer.singleShot(350, loop.quit)
    try:
        loop.exec()
    finally:
        timer.stop()


def verify_exclusion(capture, overlay, rectangles=None, scope_is_current=None):
    screen = QApplication.primaryScreen()
    geo = screen.geometry()
    ratio = screen.devicePixelRatio()
    candidates=rectangles if rectangles is not None else [(80*ratio,300*ratio,24*ratio,24*ratio)]
    # 小字号文字行也必须可验证。向内取整，确保高DPI下探针不越界。
    probe=None
    for x,y,width,height in candidates:
        left=math.ceil(x/ratio);top=math.ceil(y/ratio)
        right=math.floor((x+width)/ratio);bottom=math.floor((y+height)/ratio)
        if right-left>=4 and bottom-top>=4:
            probe=(left,top)
            break
    if probe is None:return False
    left,top=probe
    background = QWidget()
    background.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    background.setAttribute(Qt.WA_ShowWithoutActivating)
    background.setStyleSheet('background-color: rgb(0,255,255);')
    background.setGeometry(geo.x()+left,geo.y()+top,4,4)
    box=(left*ratio,top*ratio,4*ratio,4*ratio)
    scope_changed=False
    def check_scope():
        nonlocal scope_changed
        if scope_changed:return False
        try:
            valid=(scope_is_current is None or scope_is_current(
                box if background.isVisible() else None,int(background.winId())))
        except Exception:
            valid=False
        if not valid:
            scope_changed=True
            overlay.set_masks([],full=False,padding=0)
            overlay.hide()
            background.hide()
        return valid
    try:
        if not check_scope():raise ProbeScopeChanged('保护范围已变化，请重试')
        # 风险已发生：验证期间也保持全部已确认范围被保护，不能只盖探针。
        overlay.set_masks(candidates, full=False, padding=0)
        overlay.show()
        background.show()
        overlay.raise_()
        settle(check_scope if scope_is_current is not None else None)
        if not check_scope():raise ProbeScopeChanged('保护范围已变化，请重试')
        x, y = int(box[0]+box[2]/2)-1, int(box[1]+box[3]/2)-1
        before = capture.grab().image[y:y+2, x:x+2]
        if before.shape != (2,2,3) or not np.all(before == [255,255,0]):
            return False
        return True
    finally:
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
