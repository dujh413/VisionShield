"""Optional offscreen Qt integration: synthetic content, no camera or real desktop."""
import importlib.util
import os
import time
import unittest
from unittest.mock import patch
import numpy as np

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication, QPushButton
    from overlay_window import OverlayWindow
    from desktop_guard import ControlPanel
    from mask_effect import parse_effect


@unittest.skipUnless(HAS_QT, 'PySide6 is unavailable')
class GuiEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.exclusion = patch('overlay_window.exclude_capture')
        self.exclusion.start()
        self.overlay = OverlayWindow(self.app.primaryScreen())

    def tearDown(self):
        self.overlay.close()
        self.app.processEvents()
        self.exclusion.stop()

    def test_empty_mode_suppresses_even_full_mask(self):
        self.overlay.set_effect(parse_effect(''))
        self.overlay.set_masks([(10,10,100,20)], full=True)
        self.assertFalse(self.overlay.full)
        self.assertEqual(self.overlay.rectangles, [])

    def test_text_mode_draws_opaque_dark_rectangle(self):
        self.overlay.set_effect(parse_effect('遮挡'))
        self.overlay.set_masks([(20,20,80,30)])
        self.app.processEvents()
        color = self.overlay.grab().toImage().pixelColor(30,30)
        self.assertEqual((color.red(),color.green(),color.blue(),color.alpha()), (20,24,32,255))

    def test_digit_mode_draws_filtered_pixels(self):
        image = np.zeros((400,400,3), dtype=np.uint8)
        image[::2,::2] = 255
        self.overlay.set_effect(parse_effect('2'))
        masks = [(20,20,80,30)]
        deadline = time.monotonic()+3
        while not self.overlay.blur_images and time.monotonic()<deadline:
            self.overlay.set_masks(masks, frame_image=image)
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(self.overlay.blur_images)
        color = self.overlay.grab().toImage().pixelColor(30,30)
        self.assertEqual((color.red(),color.green(),color.blue()), (92,92,92))

    def test_input_is_applied_only_when_start_is_clicked(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            panel = ControlPanel()
            panel.root = Path(directory)
            screen = self.app.primaryScreen()
            geo, ratio = screen.geometry(), screen.devicePixelRatio()
            width, height = round(geo.width()*ratio), round(geo.height()*ratio)
            image = np.zeros((height,width,3),dtype=np.uint8)
            source = SimpleNamespace(monitor={'width':width,'height':height},
                                     grab=lambda:SimpleNamespace(image=image),close=lambda:None)
            capture = SimpleNamespace(close=lambda:None,latest=lambda:None,
                                      thread=SimpleNamespace(is_alive=lambda:True))
            ocr = SimpleNamespace(close=lambda:None,process=SimpleNamespace(is_alive=lambda:True),
                                  poll=lambda:[],submit=lambda frame:True)
            bridge = SimpleNamespace(close=lambda:None,poll=lambda:None,risk=lambda now:(True,'fixture'))
            try:
                with patch('desktop_guard.ScreenCapture',return_value=source), \
                     patch('desktop_guard.CaptureWorker',return_value=capture), \
                     patch('desktop_guard.OCRWorker',return_value=ocr), \
                     patch('desktop_guard.IdentityBridge',return_value=bridge), \
                     patch('desktop_guard.exclude_capture'), \
                     patch('capture_probe.verify_exclusion',return_value=True):
                    button = next(b for b in panel.findChildren(QPushButton) if b.text().startswith('启动'))
                    button.click()
                    self.assertEqual(panel.effect.mode,'off')
                    panel.effect_input.setText('8')
                    self.assertEqual(panel.effect.mode,'off')
                    button.click()
                    self.assertEqual((panel.effect.mode,panel.effect.radius),('blur',8))
                    panel.effect_input.setText('遮挡')
                    button.click()
                    self.assertEqual(panel.effect.mode,'block')
            finally:
                panel.pause()
                panel.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
