import ctypes
import time
from ctypes import wintypes
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QImage
from PySide6.QtWidgets import QWidget
from blur_renderer import BlurCache, mask_crops, physical_to_logical


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
        screen.geometryChanged.connect(self.screen_geometry_changed)
        self.rectangles = []
        self.full = False
        self.blurs = []
        self.mask_image = None
        self._renderer = None
        self._fallback_boxes = []
        self._qimages = {}
        self._closed = False
        self._last_paint_ms = None
        self._last_painted_at = None
        self.show()
        exclude_capture(self)

    def screen_geometry_changed(self,geometry):
        self.setGeometry(geometry)
        self.set_masks([],full=True)

    @property
    def last_render_ms(self):
        return self._renderer.last_elapsed_ms if self._renderer is not None else None

    @property
    def last_render_error(self):
        return self._renderer.last_error if self._renderer is not None else None

    @property
    def last_paint_ms(self):
        """Time inside the paint callback; not compositor/monitor latency."""
        return self._last_paint_ms

    @property
    def last_painted_at(self):
        return self._last_painted_at

    def set_masks(self, rectangles, full=False, image=None):
        if self._closed:
            return
        self.mask_image = image
        previous = (self.rectangles, self.full, tuple(self._fallback_boxes),
                    tuple((box, id(qimage)) for box, qimage in self.blurs))
        self.rectangles, self.full = list(rectangles), bool(full)
        try:
            ratio = self.devicePixelRatioF()
            shape = image.shape if image is not None else (round(self.height()*ratio), round(self.width()*ratio))
            boxes = mask_crops(self.rectangles, shape)
            if self.full or not boxes:
                if self._renderer is not None:
                    self._renderer.clear()
                ready, pending = [], []
            elif image is None:
                if self._renderer is not None:
                    self._renderer.clear()
                ready, pending = [], list(boxes)
            else:
                if self._renderer is None:
                    self._renderer = BlurCache()
                ready, pending = self._renderer.update(boxes, image)
            blurs, qimages = [], {}
            for box, rgb in ready:
                cached = self._qimages.get(box)
                if cached is not None and cached[0] is rgb:
                    qimage = cached[1]
                else:
                    # Qt image creation is restricted to this control/UI thread.
                    qimage = QImage(rgb.data, rgb.shape[1], rgb.shape[0],
                                    rgb.strides[0], QImage.Format_RGB888).copy()
                qimages[box] = (rgb, qimage)
                blurs.append((box, qimage))
            self.blurs, self._qimages = blurs, qimages
            self._fallback_boxes = list(pending)
        except Exception:
            # Invalid source/geometry cannot cause an unmasked interval.
            self.full = True
            self.blurs, self._fallback_boxes, self._qimages = [], [], {}
            if self._renderer is not None:
                self._renderer.clear()
        current = (self.rectangles, self.full, tuple(self._fallback_boxes),
                   tuple((box, id(qimage)) for box, qimage in self.blurs))
        if current != previous:
            self.update()

    def _release_renderer(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self.mask_image = None
        self.blurs, self._qimages, self._fallback_boxes = [], {}, []

    def hideEvent(self, event):
        self._release_renderer()
        # If reused after hiding, protect until the controller supplies a fresh
        # mask decision instead of revealing content with an empty old cache.
        self.full = True
        super().hideEvent(event)

    def closeEvent(self, event):
        self._closed = True
        self._release_renderer()
        super().closeEvent(event)

    def paintEvent(self, event):
        started = time.perf_counter()
        painter = QPainter(self)
        try:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(20, 24, 32, 255))
            if self.full:
                painter.drawRect(self.rect())
            else:
                # mss为物理像素；Qt窗口内坐标为逻辑像素。
                ratio = self.devicePixelRatioF()
                # Every pending/stale/error region is opaque immediately; validated
                # regions can independently switch to the original strong blur.
                for box in self._fallback_boxes:
                    painter.drawRect(QRectF(*physical_to_logical(box, ratio)))
                for box, image in self.blurs:
                    painter.drawImage(QRectF(*physical_to_logical(box, ratio)), image)
        finally:
            painter.end()
            self._last_paint_ms = (time.perf_counter()-started)*1000
            self._last_painted_at = time.monotonic()
