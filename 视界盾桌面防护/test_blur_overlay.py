import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import time
import threading
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from overlay_window import OverlayWindow
from mask_effect import parse_effect
from blur_renderer import BlurCache, BlurWorker, box_obscure_bgr


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def make_overlay(self, radius=2):
        with patch('overlay_window.exclude_capture'):
            overlay = OverlayWindow(self.app.primaryScreen())
        overlay.setGeometry(0, 0, 400, 200)
        overlay.set_effect(parse_effect(str(radius)))
        return overlay

    def finish_blur(self, overlay, masks, image, padding=8):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            overlay.set_masks(masks, frame_image=image, padding=padding)
            self.app.processEvents()
            if overlay.blurs and not overlay._fallback_boxes:
                return
            time.sleep(.005)
        self.fail('background blur did not complete')

    def test_unrelated_pixels_reuse_qimage_but_changed_roi_falls_back(self):
        overlay = self.make_overlay()
        image = np.full((200, 400, 3), 255, np.uint8)
        masks = [(30, 50, 170, 20)]
        try:
            self.finish_blur(overlay, masks, image)
            old = overlay.blurs[0][1]
            changed = image.copy()
            changed[180, 350] = 0
            overlay.set_masks(masks, image=changed)
            self.assertIs(overlay.blurs[0][1], old)
            changed[50, 30, 0] -= 1
            overlay.set_masks(masks, image=changed)
            self.assertEqual(overlay.blurs, [])
            self.assertEqual(overlay.grab().toImage().pixelColor(100, 60).getRgb(), (20, 24, 32, 255))
            self.assertIsNotNone(overlay.blur_ms)
            self.assertGreaterEqual(overlay.last_paint_ms, 0)
        finally:
            overlay.close()

    def test_stale_completion_and_radius_switch_cannot_draw_old_pixels(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def render(source):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(2)
            return box_obscure_bgr(source, 2)

        overlay = self.make_overlay()
        overlay._renderer = BlurCache(BlurWorker(render), radius=2)
        image = np.full((200, 400, 3), 255, np.uint8)
        masks = [(30, 50, 170, 20)]
        try:
            overlay.set_masks(masks, image=image)
            self.assertTrue(started.wait(1))
            image[50, 30] = 0
            overlay.set_masks(masks, image=image)
            self.assertEqual(overlay.blurs, [])
            release.set()
            self.finish_blur(overlay, masks, image)
            self.assertEqual(len(calls), 2)
            old_worker = overlay.blur_worker
            overlay.set_effect(parse_effect('0'))
            self.assertFalse(old_worker.alive)
            self.assertEqual(overlay.blurs, [])
            self.finish_blur(overlay, masks, image, padding=0)
            box, rendered = overlay.blurs[0]
            self.assertEqual(box, (30, 50, 170, 20))
            raw = np.frombuffer(rendered.bits(), np.uint8).reshape(rendered.height(), rendered.bytesPerLine())
            np.testing.assert_array_equal(raw[:, :rendered.width()*3].reshape(20, 170, 3), image[50:70, 30:200, ::-1])
        finally:
            release.set()
            overlay.close()

    def test_off_ignores_invalid_source_and_geometry(self):
        overlay = self.make_overlay()
        try:
            overlay.set_effect(parse_effect(''))
            overlay.set_masks([(float('nan'), 0, -1, 10)], full=True,
                              image=np.zeros((3, 4), np.float32), padding=-1)
            self.assertFalse(overlay.full)
            self.assertEqual(overlay.blurs, [])
            self.assertEqual(overlay.grab().toImage().pixelColor(20, 20).alpha(), 0)
        finally:
            overlay.close()

    def test_hide_geometry_and_close_release_cache_and_owned_worker(self):
        overlay = self.make_overlay()
        image = np.full((200, 400, 3), 255, np.uint8)
        masks = [(30, 50, 170, 20)]
        try:
            self.finish_blur(overlay, masks, image)
            worker = overlay.blur_worker
            overlay.hide()
            self.assertFalse(worker.alive)
            self.assertIsNone(overlay.mask_image)
            self.assertEqual(overlay.blurs, [])
            overlay.show()
            self.assertEqual(overlay.grab().toImage().pixelColor(20, 20).getRgb(), (20, 24, 32, 255))
            self.finish_blur(overlay, masks, image)
            worker = overlay.blur_worker
            overlay.screen_geometry_changed(overlay.geometry())
            self.assertFalse(worker.alive)
            self.assertTrue(overlay.full)
            self.assertIsNone(overlay.mask_image)
            self.assertEqual(overlay.blurs, [])
        finally:
            overlay.close()

    def test_close_timeout_reaches_controller_and_keeps_dark_fallback(self):
        started, release = threading.Event(), threading.Event()

        def render(source):
            started.set()
            release.wait(2)
            return source.copy()

        overlay = self.make_overlay()
        overlay._renderer = BlurCache(BlurWorker(render), radius=2)
        worker = overlay.blur_worker
        close_worker = worker.close
        try:
            overlay.set_masks([(30, 50, 170, 20)], image=np.zeros((200, 400, 3), np.uint8))
            self.assertTrue(started.wait(1))
            with patch.object(worker, 'close', side_effect=lambda: close_worker(timeout=.01)):
                with self.assertRaises(TimeoutError):
                    overlay.close()
            self.assertIs(overlay.blur_worker, worker)
            self.assertTrue(overlay.full)
            self.assertEqual(overlay.blurs, [])
            self.assertIsNone(overlay.mask_image)
            self.assertEqual(overlay.grab().toImage().pixelColor(100, 60).getRgb(), (20, 24, 32, 255))
            release.set()
            overlay.close()
            self.assertFalse(worker.alive)
        finally:
            release.set()
            overlay.close()

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
