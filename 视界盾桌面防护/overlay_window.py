import ctypes
from ctypes import wintypes
import numpy as np
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QImage
from PySide6.QtWidgets import QWidget
from mask_effect import MaskEffect
from blur_worker import BlurWorker, crop_boxes


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
        self.effect = MaskEffect('block')
        self.blur_worker = None
        self.blur_packet = None
        self.blur_images = []
        self.last_blur_request = None
        self.blur_validated_image = None
        self.blur_ms = None
        self.show()
        exclude_capture(self)

    def set_effect(self, effect):
        self.effect = effect
        self.blur_packet, self.blur_images = None, []
        self.last_blur_request = self.blur_validated_image = None
        if self.blur_worker:
            self.blur_worker.close()
            self.blur_worker = None
        if effect.mode == 'blur':
            self.blur_worker = BlurWorker()
        self.set_masks([], full=False)

    def set_masks(self, rectangles, full=False, frame_image=None):
        if self.effect.mode == 'off':
            rectangles, full = [], False
        changed = self.rectangles != rectangles or self.full != full
        self.rectangles, self.full = list(rectangles), bool(full)
        if self.effect.mode == 'blur':
            boxes = ([(0, 0, frame_image.shape[1], frame_image.shape[0])] if full and frame_image is not None
                     else crop_boxes(frame_image, rectangles) if frame_image is not None else [])
            packet = self.blur_worker.poll()
            if packet is not None:
                self.blur_packet = packet if 'error' not in packet else None
                self.blur_validated_image = None
            if (self.blur_packet is not None and frame_image is not None
                    and self.blur_packet['boxes'] == boxes and self.blur_packet['radius'] == self.effect.radius):
                if self.blur_validated_image is not frame_image:
                    source = self.blur_packet['image']
                    valid = source.shape == frame_image.shape and all(
                        np.array_equal(source[y1:y2, x1:x2], frame_image[y1:y2, x1:x2])
                        for x1, y1, x2, y2 in boxes)
                    self.blur_validated_image = frame_image
                    self.blur_images = []
                    if valid:
                        for box, bgr in self.blur_packet['patches']:
                            rgb = np.ascontiguousarray(bgr[:, :, ::-1])
                            height, width = rgb.shape[:2]
                            qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888).copy()
                            self.blur_images.append((box, qimage))
                        self.blur_ms = self.blur_packet['blur_ms']
                    changed = True
            else:
                if self.blur_images:
                    changed = True
                self.blur_images = []
                self.blur_validated_image = None
            key = (id(frame_image), tuple(boxes), self.effect.radius)
            if frame_image is not None and boxes and key != self.last_blur_request:
                self.blur_worker.submit(frame_image, boxes, self.effect.radius)
                self.last_blur_request = key
        if changed:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 24, 32, 255))
        if self.effect.mode == 'off':
            return
        if self.effect.mode == 'blur' and self.blur_images:
            ratio = self.devicePixelRatioF()
            for (x1, y1, x2, y2), image in self.blur_images:
                painter.drawImage(QRectF(x1/ratio, y1/ratio, (x2-x1)/ratio, (y2-y1)/ratio), image)
        elif self.full:
            painter.drawRect(self.rect())
        else:
            # mss为物理像素；Qt窗口内坐标为逻辑像素。
            ratio = self.devicePixelRatioF()
            for x, y, width, height in self.rectangles:
                painter.drawRect(QRectF((x-6)/ratio, (y-6)/ratio,
                                       (width+12)/ratio, (height+12)/ratio))

    def closeEvent(self, event):
        if self.blur_worker:
            self.blur_worker.close()
            self.blur_worker = None
        self.blur_packet, self.blur_images = None, []
        event.accept()

