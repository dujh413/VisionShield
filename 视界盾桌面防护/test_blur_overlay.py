import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from overlay_window import OverlayWindow


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_sensitive_roi_is_obscured_and_outside_is_transparent(self):
        image=np.full((200,400,3),255,dtype=np.uint8)
        image[50:70,30:200:4]=0
        with patch('overlay_window.exclude_capture'):
            overlay=OverlayWindow(self.app.primaryScreen())
        try:
            overlay.setGeometry(0,0,400,200)
            overlay.set_masks([(30,50,170,20)],image=image)
            self.assertEqual(len(overlay.blurs),1)
            _,obscured=overlay.blurs[0]
            raw=np.frombuffer(obscured.bits(),dtype=np.uint8).reshape(obscured.height(),obscured.bytesPerLine())
            values=raw[:,:obscured.width()*3].copy()
            self.assertLess(int(values.max()),130)
            self.assertLess(float(values.std()),10)
            snapshot=overlay.grab().toImage()
            self.assertEqual(snapshot.pixelColor(300,150).alpha(),0)
            self.assertEqual(snapshot.pixelColor(100,60).alpha(),255)
            previous=overlay.blurs[0][1]
            overlay.set_masks([(30,50,170,20)],image=image)
            self.assertIs(overlay.blurs[0][1],previous)
        finally:overlay.close()


if __name__=='__main__':unittest.main()
