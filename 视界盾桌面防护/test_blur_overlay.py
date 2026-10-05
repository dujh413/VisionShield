import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from overlay_window import OverlayWindow
from blur_renderer import BlurCache, BlurWorker, obscure_bgr


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def make_overlay(self):
        with patch('overlay_window.exclude_capture'):
            overlay = OverlayWindow(self.app.primaryScreen())
        overlay.setGeometry(0, 0, 400, 200)
        return overlay

    def finish_blur(self, overlay, rectangles, image):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            overlay.set_masks(rectangles, image=image)
            self.app.processEvents()
            if overlay.blurs and not overlay._fallback_boxes:
                return
            time.sleep(.005)
        self.fail('background blur did not complete')

    def test_sensitive_roi_is_obscured_and_outside_is_transparent(self):
        image=np.full((200,400,3),255,dtype=np.uint8)
        image[50:70,30:200:4]=0
        overlay=self.make_overlay()
        try:
            overlay.set_masks([(30,50,170,20)],image=image)
            # Initial/pending content is opaque before any worker completion.
            self.assertEqual(overlay.blurs, [])
            pending=overlay.grab().toImage()
            ratio=overlay.devicePixelRatioF()
            self.assertEqual(pending.pixelColor(round(100*ratio),round(60*ratio)).getRgb(),(20,24,32,255))
            self.finish_blur(overlay, [(30,50,170,20)], image)
            self.assertEqual(len(overlay.blurs),1)
            self.assertIsNotNone(overlay.last_render_ms)
            self.assertIsNone(overlay.last_render_error)
            _,obscured=overlay.blurs[0]
            raw=np.frombuffer(obscured.bits(),dtype=np.uint8).reshape(obscured.height(),obscured.bytesPerLine())
            values=raw[:,:obscured.width()*3].copy()
            self.assertLess(int(values.max()),130)
            self.assertLess(float(values.std()),10)
            snapshot=overlay.grab().toImage()
            self.assertGreaterEqual(overlay.last_paint_ms,0)
            self.assertLessEqual(overlay.last_painted_at,time.monotonic())
            self.assertEqual(snapshot.pixelColor(round(300*ratio),round(150*ratio)).alpha(),0)
            self.assertEqual(snapshot.pixelColor(round(100*ratio),round(60*ratio)).alpha(),255)
            previous=overlay.blurs[0][1]
            overlay.set_masks([(30,50,170,20)],image=image)
            self.assertIs(overlay.blurs[0][1],previous)
        finally:overlay.close()

    def test_unrelated_frame_change_reuses_qimage_but_one_roi_pixel_falls_back(self):
        image=np.full((200,400,3),255,dtype=np.uint8)
        rectangles=[(30,50,170,20)]
        overlay=self.make_overlay()
        try:
            self.finish_blur(overlay,rectangles,image)
            previous=overlay.blurs[0][1]
            image=image.copy()
            image[180,350]=0
            overlay.set_masks(rectangles,image=image)
            self.assertIs(overlay.blurs[0][1],previous)
            image[50,30,0]-=1
            overlay.set_masks(rectangles,image=image)
            self.assertEqual(overlay.blurs,[])
            ratio=overlay.devicePixelRatioF()
            self.assertEqual(overlay.grab().toImage().pixelColor(round(100*ratio),round(60*ratio)).getRgb(),(20,24,32,255))
        finally:overlay.close()

    def test_stale_background_result_never_replaces_current_dark_fallback(self):
        started,release=threading.Event(),threading.Event()
        calls=[]

        def blocked_render(source):
            calls.append(1)
            if len(calls)==1:
                started.set()
                release.wait(2)
            return obscure_bgr(source)

        image=np.full((200,400,3),255,dtype=np.uint8)
        rectangles=[(30,50,170,20)]
        overlay=self.make_overlay()
        overlay._renderer=BlurCache(BlurWorker(blocked_render))
        try:
            overlay.set_masks(rectangles,image=image)
            self.assertTrue(started.wait(1))
            image[50,30]=0
            overlay.set_masks(rectangles,image=image)
            self.assertEqual(overlay.blurs,[])
            release.set()
            self.finish_blur(overlay,rectangles,image)
            self.assertEqual(len(calls),2)
            # Full/clear operations cancel content and cannot keep old blurs.
            overlay.set_masks([],full=True,image=image)
            self.assertEqual(overlay.blurs,[])
            self.assertEqual(overlay.grab().toImage().pixelColor(20,20).getRgb(),(20,24,32,255))
            overlay.set_masks([],image=image)
            self.assertEqual(overlay.grab().toImage().pixelColor(20,20).alpha(),0)
            self.assertIsNone(overlay.last_render_ms)
            # Clearing cannot starve a resubmission with the same source object.
            overlay.set_masks(rectangles,image=image)
            self.assertEqual(overlay.blurs,[])
            self.finish_blur(overlay,rectangles,image)
            overlay.screen_geometry_changed(overlay.geometry())
            self.assertTrue(overlay.full)
            self.assertEqual(overlay.blurs,[])
            self.assertIsNone(overlay.mask_image)
        finally:
            release.set()
            overlay.close()

    def test_hide_and_close_release_worker_and_cached_sources(self):
        image=np.full((200,400,3),255,dtype=np.uint8)
        overlay=self.make_overlay()
        try:
            self.finish_blur(overlay,[(30,50,170,20)],image)
            worker=overlay._renderer.worker
            overlay.hide()
            self.assertFalse(worker.alive)
            self.assertIsNone(overlay.mask_image)
            self.assertIsNone(overlay._renderer)
            self.assertEqual(overlay.blurs,[])
            overlay.show()
            self.assertEqual(overlay.grab().toImage().pixelColor(20,20).getRgb(),(20,24,32,255))
            self.finish_blur(overlay,[(30,50,170,20)],image)
            worker=overlay._renderer.worker
            overlay.close()
            self.assertFalse(worker.alive)
            self.assertIsNone(overlay.mask_image)
        finally:overlay.close()


if __name__=='__main__':unittest.main()
