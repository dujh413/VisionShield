"""Single vector brand source for windows, tray, startup and the packaged EXE."""
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from runtime_paths import resource_root


@lru_cache(maxsize=1)
def app_icon():
    renderer = QSvgRenderer(str(resource_root()/'assets'/'VisionShield.svg'))
    if not renderer.isValid():
        raise RuntimeError('VisionShield brand resource is missing or invalid')
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon
