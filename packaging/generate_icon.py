"""Generate Windows ICO sizes from the runtime SVG brand source."""
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'视界盾桌面防护'))
from PySide6.QtWidgets import QApplication
from branding import app_icon
from PIL import Image


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary)/'icon.png'
        if not app_icon().pixmap(256, 256).save(str(source), 'PNG'):
            raise RuntimeError('Cannot render brand icon')
        with Image.open(source) as image:
            image.save(root/'assets'/'VisionShield.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 48, 64, 128, 256)])
    print('Generated assets/VisionShield.ico from the application SVG')


if __name__ == '__main__':
    main()
