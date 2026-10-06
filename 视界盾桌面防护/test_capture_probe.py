import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from capture_probe import ProbeScopeChanged, verify_exclusion


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_probe_never_paints_outside_allowed_region(self):
        capture,overlay=Mock(),Mock()
        image=np.full((1000,1000,3),[255,255,0],dtype=np.uint8)
        capture.grab.return_value=SimpleNamespace(image=image)
        with patch('capture_probe.settle'):
            self.assertTrue(verify_exclusion(capture,overlay,[(80,300,30,30)]))
        self.assertTrue(all(c.kwargs.get('full') is False for c in overlay.set_masks.call_args_list))
        box=overlay.set_masks.call_args.args[0][0]
        self.assertGreaterEqual(box[0],80);self.assertGreaterEqual(box[1],300)
        self.assertLessEqual(box[0]+box[2],110);self.assertLessEqual(box[1]+box[3],330)

    def test_failed_probe_never_escalates_to_full_screen(self):
        capture,overlay=Mock(),Mock()
        capture.grab.return_value=SimpleNamespace(image=np.zeros((1000,1000,3),dtype=np.uint8))
        with patch('capture_probe.settle'):
            self.assertFalse(verify_exclusion(capture,overlay))
        self.assertTrue(all(c.kwargs.get('full') is False for c in overlay.set_masks.call_args_list))

    def test_empty_scope_does_not_show_a_probe(self):
        capture,overlay=Mock(),Mock()
        self.assertFalse(verify_exclusion(capture,overlay,[]))
        overlay.show.assert_not_called();capture.grab.assert_not_called()

    def test_small_text_row_on_scaled_screen_stays_inside_scope(self):
        capture,overlay=Mock(),Mock()
        capture.grab.return_value=SimpleNamespace(image=np.full((1000,1000,3),[255,255,0],dtype=np.uint8))
        screen=Mock()
        screen.devicePixelRatio.return_value=1.5
        screen.geometry.return_value=SimpleNamespace(x=lambda:0,y=lambda:0)
        allowed=(80.2,300.2,25,9)
        with patch('capture_probe.QApplication.primaryScreen',return_value=screen),patch('capture_probe.settle'):
            self.assertTrue(verify_exclusion(capture,overlay,[allowed]))
        box=overlay.set_masks.call_args.args[0][0]
        self.assertGreaterEqual(box[0],allowed[0]);self.assertGreaterEqual(box[1],allowed[1])
        self.assertLessEqual(box[0]+box[2],allowed[0]+allowed[2]);self.assertLessEqual(box[1]+box[3],allowed[1]+allowed[3])

    def test_verification_keeps_all_confirmed_ranges_covered(self):
        capture,overlay=Mock(),Mock()
        capture.grab.return_value=SimpleNamespace(image=np.full((1000,1000,3),[255,255,0],dtype=np.uint8))
        ranges=[(80,300,30,30),(160,300,30,30)]
        with patch('capture_probe.settle'):
            self.assertTrue(verify_exclusion(capture,overlay,ranges))
        self.assertEqual(overlay.set_masks.call_args.args[0],ranges)

    def test_too_thin_region_does_not_probe_outside_it(self):
        capture,overlay=Mock(),Mock()
        self.assertFalse(verify_exclusion(capture,overlay,[(80,300,30,1)]))
        overlay.show.assert_not_called();capture.grab.assert_not_called()

    def test_scope_change_during_native_settle_clears_old_masks_and_cancels(self):
        capture,overlay=Mock(),Mock()
        current=[True]
        QTimer.singleShot(40,lambda:current.__setitem__(0,False))
        started=time.monotonic()
        with self.assertRaises(ProbeScopeChanged):
            verify_exclusion(capture,overlay,[(80,300,30,30)],lambda *args:current[0])
        self.assertLess(time.monotonic()-started,.25)
        self.assertEqual(overlay.set_masks.call_args.args[0],[])
        overlay.hide.assert_called();capture.grab.assert_not_called()

    def test_stable_scope_still_requires_actual_capture_pixel_check(self):
        capture,overlay=Mock(),Mock()
        capture.grab.return_value=SimpleNamespace(image=np.zeros((1000,1000,3),dtype=np.uint8))
        checked=[]
        with patch('capture_probe.settle'):
            self.assertFalse(verify_exclusion(capture,overlay,[(80,300,30,30)],
                lambda box,handle:checked.append((box,handle)) or True))
        self.assertGreaterEqual(len(checked),2)
        self.assertIsNone(checked[0][0]);self.assertIsNotNone(checked[-1][0])
        capture.grab.assert_called_once()


if __name__=='__main__':unittest.main()
