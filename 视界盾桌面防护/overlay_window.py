import ctypes
import time
from ctypes import wintypes
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QImage
from PySide6.QtWidgets import QWidget
from mask_effect import MaskEffect
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
        self.padding = 8
        self.effect = MaskEffect('block')
        self.blurs = []
        self.mask_image = None
        self._renderer = None
        self._fallback_boxes = []
        self._mask_error = None
        self._qimages = {}
        self._closed = False
        self._last_paint_ms = None
        self._last_painted_at = None
        self.show()
        exclude_capture(self)

    @property
    def blur_worker(self):
        return self._renderer.worker if self._renderer is not None else None

    @property
    def blur_images(self):
        """Legacy xyxy view used by native mode/status integration."""
        return [((x, y, x+w, y+h), image) for (x, y, w, h), image in self.blurs]

    @property
    def blur_ms(self):
        return self.last_render_ms

    @property
    def last_render_ms(self):
        return self._renderer.last_elapsed_ms if self._renderer is not None else None

    @property
    def last_render_error(self):
        return self._mask_error or (self._renderer.last_error if self._renderer is not None else None)

    @property
    def blur_backend(self):
        return self._renderer.backend if self._renderer is not None else 'none'

    @property
    def blur_device(self):
        return self._renderer.device if self._renderer is not None else ''

    @property
    def blur_gpu_ms(self):
        return self._renderer.gpu_ms if self._renderer is not None else 0.0

    @property
    def blur_fallback(self):
        return self._renderer.fallback if self._renderer is not None else None

    @property
    def last_paint_ms(self):
        """Paint callback duration, excluding compositor/monitor latency."""
        return self._last_paint_ms

    @property
    def last_painted_at(self):
        return self._last_painted_at

    def screen_geometry_changed(self, geometry):
        self.setGeometry(geometry)
        self._release_renderer()
        # Screen scaling invalidates physical coordinates. Wait for a fresh
        # controller decision instead of inventing a full-screen black mask.
        self.set_masks([], full=False)

    def set_effect(self, effect):
        if effect.mode not in ('off', 'block', 'blur'):
            raise ValueError('invalid mask effect')
        if effect == self.effect:
            return
        rectangles, full, padding, image = (self.rectangles, self.full,
                                            self.padding, self.mask_image)
        if self.effect.mode == 'blur' and effect.mode == 'blur' and self._renderer is not None:
            self._renderer.set_radius(effect.radius)
        else:
            self._release_renderer()
        self.effect = effect
        # A live strength/mode change keeps exactly the current scope. Clearing
        # it first causes a transparent frame; expanding it causes black flashes.
        self.set_masks(rectangles, full=full, image=image, padding=padding)

    def set_masks(self, rectangles, full=False, image=None, padding=8, frame_image=None):
        if self._closed:
            return
        if frame_image is None:
            frame_image = image
        previous = (self.rectangles, self.full, self.padding,
                    tuple(self._fallback_boxes),
                    tuple((box, id(qimage)) for box, qimage in self.blurs))
        self.mask_image = frame_image
        self.padding = padding
        self.rectangles, self.full = list(rectangles), bool(full)
        self._mask_error = None
        if self.effect.mode == 'off':
            self.mask_image = None
            self.rectangles, self.full = [], False
            if self._renderer is not None:
                self._renderer.clear()
            self.blurs, self._fallback_boxes, self._qimages = [], [], {}
        else:
            # Derive protection bounds from the window, independently of a bad
            # or missing capture. Failure must never enlarge a selected scope.
            ratio = self.devicePixelRatioF()
            shape = (round(self.height()*ratio), round(self.width()*ratio))
            boxes = ((0, 0, int(shape[1]), int(shape[0])),) if self.full else ()
            try:
                if not self.full:
                    boxes = mask_crops(self.rectangles, shape, padding)
                if not boxes or self.effect.mode != 'blur' or frame_image is None:
                    if self._renderer is not None:
                        self._renderer.clear()
                    ready, pending = [], list(boxes)
                else:
                    if self._renderer is None:
                        self._renderer = BlurCache(radius=self.effect.radius)
                    ready, pending = self._renderer.update(boxes, frame_image)
                blurs, qimages = [], {}
                for box, rgb in ready:
                    cached = self._qimages.get(box)
                    if cached is not None and cached[0] is rgb:
                        qimage = cached[1]
                    else:
                        # QImage creation stays on the Qt/UI thread.
                        qimage = QImage(rgb.data, rgb.shape[1], rgb.shape[0],
                                        rgb.strides[0], QImage.Format_RGB888).copy()
                    qimages[box] = (rgb, qimage)
                    blurs.append((box, qimage))
                self.blurs, self._qimages = blurs, qimages
                self._fallback_boxes = list(pending)
            except Exception as error:
                self._mask_error = type(error).__name__
                # Invalid source/rendering retains only valid requested boxes.
                # An invalid rectangle cannot justify covering unrelated pixels.
                if not self.full:
                    valid = []
                    for rectangle in self.rectangles:
                        try:
                            valid.extend(mask_crops([rectangle], shape, padding))
                        except (TypeError, ValueError, OverflowError):
                            continue
                    boxes = tuple(sorted(set(valid)))
                self.blurs, self._fallback_boxes, self._qimages = [], [], {}
                self._fallback_boxes = list(boxes)
                if self._renderer is not None:
                    self._renderer.clear()
        current = (self.rectangles, self.full, self.padding,
                   tuple(self._fallback_boxes),
                   tuple((box, id(qimage)) for box, qimage in self.blurs))
        if current != previous:
            self.update()

    def _release_renderer(self):
        self.mask_image = None
        # During a slow/failed release, preserve only the already validated
        # physical scope as opaque placeholders; never turn it into full-screen.
        self._fallback_boxes = list(dict.fromkeys(
            [box for box, _ in self.blurs] + self._fallback_boxes))
        self.blurs, self._qimages = [], {}
        if self._renderer is not None:
            try:
                self._renderer.close()
            except Exception:
                self.update()
                raise
            self._renderer = None

    def close(self):
        # Qt event callbacks do not reliably propagate Python exceptions to the
        # caller. Release explicitly so pause can block restart after a timeout.
        self._release_renderer()
        return super().close()

    def hideEvent(self, event):
        self._release_renderer()
        # A reused protected overlay waits for a fresh controller decision.
        self.rectangles, self.full, self._fallback_boxes = [], False, []
        super().hideEvent(event)

    def closeEvent(self, event):
        self._closed = True
        self._release_renderer()
        super().closeEvent(event)

    def paintEvent(self, event):
        started = time.perf_counter()
        painter = QPainter(self)
        try:
            # One backing-store paint replaces the previous mask atomically.
            # Explicitly erase vacated regions after a window/selection moves.
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(20, 24, 32, 255))
            if self.effect.mode == 'off':
                return
            if self.full and not self.blurs:
                painter.drawRect(self.rect())
            else:
                # mss uses physical pixels; Qt window coordinates are logical.
                ratio = self.devicePixelRatioF()
                for box in self._fallback_boxes:
                    painter.drawRect(QRectF(*physical_to_logical(box, ratio)))
                for box, image in self.blurs:
                    painter.drawImage(QRectF(*physical_to_logical(box, ratio)), image)
        finally:
            painter.end()
            self._last_paint_ms = (time.perf_counter()-started)*1000
            self._last_painted_at = time.monotonic()
