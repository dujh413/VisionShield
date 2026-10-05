import ctypes
from ctypes import wintypes
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QImage
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
        screen.geometryChanged.connect(self.screen_geometry_changed)
        self.rectangles = []
        self.full = False
        self.blurs = []
        self.mask_image = None
        self.padding = 8
        self.show()
        exclude_capture(self)

    def screen_geometry_changed(self,geometry):
        self.setGeometry(geometry)
        self.set_masks([],full=True)

    def set_masks(self, rectangles, full=False, image=None, padding=8):
        if self.mask_image is image and self.rectangles == rectangles and self.full == full and self.padding == padding:
            return
        self.padding = padding
        self.mask_image = image
        self.rectangles, self.full = rectangles, full
        self.blurs = []
        if image is not None and not full:
            import cv2
            height,width = image.shape[:2]
            for x,y,w,h in rectangles:
                x1,y1 = max(0,int(x)-padding),max(0,int(y)-padding)
                x2,y2 = min(width,int(x+w)+padding),min(height,int(y+h)+padding)
                if x2<=x1 or y2<=y1:
                    continue
                roi = image[y1:y2,x1:x2]
                # 强像素化后模糊，再压暗；绘制不透明图像，避免透出原字形。
                small = cv2.resize(roi,(max(1,(x2-x1)//32),max(1,(y2-y1)//32)),interpolation=cv2.INTER_AREA)
                small = cv2.GaussianBlur(small,(3,3),0)
                obscured = cv2.resize(small,(x2-x1,y2-y1),interpolation=cv2.INTER_LINEAR)
                obscured = (obscured*.45).astype('uint8')
                rgb = cv2.cvtColor(obscured,cv2.COLOR_BGR2RGB)
                qimage = QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()
                self.blurs.append(((x1,y1,x2-x1,y2-y1),qimage))
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
            if self.blurs:
                for (x,y,width,height),image in self.blurs:
                    painter.drawImage(QRectF(x/ratio,y/ratio,width/ratio,height/ratio),image)
                return
            for x, y, width, height in self.rectangles:
                painter.drawRect(QRectF((x-self.padding)/ratio, (y-self.padding)/ratio,
                                       (width+self.padding*2)/ratio, (height+self.padding*2)/ratio))
