import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from PySide6.QtWidgets import QApplication
from capture_probe import verify_exclusion


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_probe_never_removes_full_protection(self):
        capture,overlay=Mock(),Mock()
        image=np.full((1000,1000,3),[255,255,0],dtype=np.uint8)
        capture.grab.return_value=SimpleNamespace(image=image)
        with patch('capture_probe.settle'):
            self.assertTrue(verify_exclusion(capture,overlay))
        self.assertTrue(all(c.kwargs.get('full') for c in overlay.set_masks.call_args_list))

    def test_failed_probe_keeps_protection_until_caller_stops(self):
        capture,overlay=Mock(),Mock()
        capture.grab.return_value=SimpleNamespace(image=np.zeros((1000,1000,3),dtype=np.uint8))
        with patch('capture_probe.settle'):
            self.assertFalse(verify_exclusion(capture,overlay))
        self.assertTrue(all(c.kwargs.get('full') for c in overlay.set_masks.call_args_list))


if __name__=='__main__':unittest.main()
