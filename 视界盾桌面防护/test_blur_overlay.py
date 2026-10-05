import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import time
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from overlay_window import OverlayWindow
from mask_effect import parse_effect


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_sensitive_roi_is_obscured_and_outside_is_transparent(self):
        pattern=((np.indices((200,400)).sum(axis=0)%2)*255).astype(np.uint8)
        image=np.repeat(pattern[:,:,None],3,axis=2)
        with patch('overlay_window.exclude_capture'):
            overlay=OverlayWindow(self.app.primaryScreen())
        try:
            overlay.setGeometry(0,0,400,200)
            overlay.set_effect(parse_effect('8'))
            deadline=time.monotonic()+3
            while not overlay.blurs and time.monotonic()<deadline:
                overlay.set_masks([(30,50,170,20)],image=image)
                self.app.processEvents()
                time.sleep(.01)
            self.assertEqual(len(overlay.blurs),1)
            _,obscured=overlay.blurs[0]
            raw=np.frombuffer(obscured.bits(),dtype=np.uint8).reshape(obscured.height(),obscured.bytesPerLine())
            values=raw[:,:obscured.width()*3].copy()
            self.assertGreater(float(np.median(values)),110)
            self.assertLess(float(np.median(values)),145)
            self.assertLess(float(values.std()),20)
            snapshot=overlay.grab().toImage()
            self.assertEqual(snapshot.pixelColor(300,150).alpha(),0)
            self.assertEqual(snapshot.pixelColor(100,60).alpha(),255)
            previous=overlay.blurs[0][1]
            overlay.set_masks([(30,50,170,20)],image=image)
            self.assertIs(overlay.blurs[0][1],previous)
        finally:overlay.close()

    def test_zero_scope_padding_does_not_cover_outside_application_region(self):
        with patch('overlay_window.exclude_capture'):
            overlay=OverlayWindow(self.app.primaryScreen())
        try:
            overlay.setGeometry(0,0,400,200)
            overlay.set_effect(parse_effect('遮挡'))
            overlay.set_masks([(30,50,170,20)],padding=0)
            snapshot=overlay.grab().toImage()
            self.assertEqual(snapshot.pixelColor(29,60).alpha(),0)
            self.assertEqual(snapshot.pixelColor(30,60).alpha(),255)
            self.assertEqual(snapshot.pixelColor(201,60).alpha(),0)
        finally:overlay.close()

    def test_old_blur_result_is_not_drawn_on_changed_pixels(self):
        with patch('overlay_window.exclude_capture'):
            overlay=OverlayWindow(self.app.primaryScreen())
        try:
            overlay.setGeometry(0,0,100,100)
            overlay.set_effect(parse_effect('2'))
            source=np.full((100,100,3),255,dtype=np.uint8)
            mask=[(10,10,30,20)]
            deadline=time.monotonic()+3
            while not overlay.blurs and time.monotonic()<deadline:
                overlay.set_masks(mask,image=source,padding=0)
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(overlay.blurs)
            changed=np.zeros_like(source)
            with patch.object(overlay.blur_worker,'poll',return_value=None):
                overlay.set_masks(mask,image=changed,padding=0)
            self.assertFalse(overlay.blurs)
            color=overlay.grab().toImage().pixelColor(20,20)
            self.assertEqual((color.red(),color.green(),color.blue(),color.alpha()),(20,24,32,255))
        finally:overlay.close()

    def test_scoped_blur_keeps_excluded_foreground_hole_transparent(self):
        with patch('overlay_window.exclude_capture'):
            overlay=OverlayWindow(self.app.primaryScreen())
        try:
            overlay.setGeometry(0,0,100,100)
            overlay.set_effect(parse_effect('2'))
            image=np.full((100,100,3),255,dtype=np.uint8)
            masks=[(0,0,100,40),(0,40,40,60)]
            deadline=time.monotonic()+3
            while not overlay.blurs and time.monotonic()<deadline:
                overlay.set_masks(masks,image=image,padding=0)
                self.app.processEvents()
                time.sleep(.01)
            self.assertEqual(len(overlay.blurs),2)
            snapshot=overlay.grab().toImage()
            self.assertEqual(snapshot.pixelColor(75,75).alpha(),0)
            self.assertEqual(snapshot.pixelColor(20,75).alpha(),255)
        finally:overlay.close()


if __name__=='__main__':unittest.main()
