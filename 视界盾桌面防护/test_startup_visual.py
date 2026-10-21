"""Finite startup lifecycle; the visual never starts a protection backend."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from pathlib import Path
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from startup_visual import StartupSplash


class StartupVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_skip_emits_ready_once_and_stops_animation(self):
        splash = StartupSplash()
        events = []
        splash.ready.connect(lambda: events.append('ready'))
        splash.start()
        splash.finish()
        splash.finish()
        self.assertEqual(events, ['ready'])
        self.assertFalse(splash.isVisible())
        self.assertEqual(splash.animation.state(), QAbstractAnimation.Stopped)
        self.app.processEvents()

    def test_animation_finishes_without_user_interaction(self):
        splash = StartupSplash()
        events = []
        splash.ready.connect(lambda: events.append('ready'))
        splash.animation.setDuration(50)
        splash.start()
        QTest.qWait(120)
        self.assertEqual(events, ['ready'])

    def test_startup_import_does_not_load_camera_or_ocr_models(self):
        import subprocess
        import sys
        result = subprocess.check_output([sys.executable, '-c',
            "import sys,startup_visual; print(any(n in sys.modules for n in ('cv2','numpy','camera_worker','fast_ocr','desktop_guard')))"] ,
            cwd=Path(__file__).resolve().parent)
        self.assertEqual(result.strip(), b'False')


if __name__ == '__main__':
    unittest.main()
