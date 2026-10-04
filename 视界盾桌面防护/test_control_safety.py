import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import numpy as np
from PySide6.QtWidgets import QApplication
from desktop_guard import ControlPanel
from screen_capture import Frame
from protection_state import ProtectionState


class ControlSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel=ControlPanel(integrated=True)
        self.now=time.monotonic()
        p=self.panel
        p.started=self.now-40
        p.state=ProtectionState(restore_delay=0)
        p.camera=Mock(last={'owner_verified':True},error=None)
        p.camera.risk.return_value=(False,'机主独处且已确认')
        p.capture=Mock()
        p.capture.latest.return_value=None
        p.worker=Mock()
        p.worker.poll.return_value=[]
        p.worker.process.is_alive.return_value=True
        p.overlay=Mock()
        p.latest=Frame(1,self.now,{},np.zeros((64,64,3),dtype=np.uint8))
        p.content.update(p.latest.image)
        p.content.accept(p.latest.image,[])
        p.last_ocr_finished=self.now
        p.ready=True
        p.writer=Mock();p.log=Mock()

    def tearDown(self):
        self.panel.pause()
        self.panel.deleteLater()
        self.app.processEvents()

    def tick(self):
        with patch('desktop_guard.time.monotonic',return_value=self.now):
            self.panel.tick()

    def test_capture_stall_forces_full_protection_even_when_owner_safe(self):
        self.panel.latest.captured_at=self.now-2
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertTrue(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_stale_ocr_forces_full_protection_even_when_owner_safe(self):
        self.panel.last_ocr_finished=self.now-20
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertTrue(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_camera_risk_cannot_be_overridden_by_fresh_ocr(self):
        self.panel.camera.risk.return_value=(True,'检测到旁人')
        self.tick()
        self.assertTrue(self.panel.protecting)

    def test_detection_only_keeps_alert_without_shielding(self):
        self.panel.shield_enabled = False
        self.panel.camera.risk.return_value = (True, '检测到旁人')
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])
        self.assertEqual(self.panel.overlay.set_masks.call_args.args[0], [])
        self.assertIn('遮蔽已关闭', self.panel.alert_message)
        self.assertIn('不遮蔽', self.panel.status.text())

    def test_detection_only_does_not_shield_on_capture_or_ocr_stall(self):
        self.panel.shield_enabled = False
        self.panel.latest.captured_at = self.now-2
        self.panel.last_ocr_finished = self.now-20
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_detection_only_does_not_shield_on_exception(self):
        self.panel.shield_enabled = False
        self.panel.camera.poll.side_effect = RuntimeError('synthetic error')
        with patch('traceback.print_exc'):
            self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])
        self.assertIn('遮蔽已关闭', self.panel.status.text())

    def test_detection_only_start_skips_visible_capture_probe(self):
        self.panel.shield_enabled = False
        screen = self.app.primaryScreen()
        capture = Mock(monitor={'width':screen.geometry().width()*screen.devicePixelRatio(),
                                'height':screen.geometry().height()*screen.devicePixelRatio()})
        with patch('desktop_guard.ScreenCapture', return_value=capture), \
                patch('desktop_guard.CaptureWorker'), patch('desktop_guard.OCRWorker'), \
                patch('camera_worker.CameraWorker'), patch('desktop_guard.OverlayWindow') as overlay, \
                patch('desktop_guard.Path.open'), patch('capture_probe.verify_exclusion') as probe, \
                patch('desktop_guard.exclude_capture'):
            self.panel.start()
        probe.assert_not_called()
        overlay.return_value.hide.assert_called_once()
        overlay.return_value.set_masks.assert_not_called()
        self.assertTrue(self.panel.timer.isActive())
        self.assertIn('不遮蔽', self.panel.status.text())

    def test_pause_attempts_all_resources_when_one_close_fails(self):
        self.panel.overlay.close.side_effect=RuntimeError('test close failure')
        worker,camera=self.panel.worker,self.panel.camera
        self.panel.pause()
        worker.close.assert_called_once()
        camera.close.assert_called_once()
        self.assertIsNone(self.panel.log)

    def test_display_resize_rejects_old_capture_coordinates(self):
        self.panel.capture.latest.return_value=self.panel.latest
        with patch('traceback.print_exc'):
            self.tick()
        self.assertIsNotNone(self.panel.error)
        self.assertTrue(self.panel.protecting)
        self.assertTrue(self.panel.overlay.set_masks.call_args.kwargs['full'])
        self.panel.overlay.setGeometry.assert_called_once()
        self.assertIn('尺寸已变化',self.panel.status.text())

    def test_unavailable_semantic_option_reports_usage_error(self):
        result=subprocess.run([sys.executable,'desktop_guard.py','--semantic'],capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertNotIn(b'Traceback',result.stderr)

    def test_restart_does_not_duplicate_resources_after_failed_cleanup(self):
        self.panel.capture.close.side_effect=TimeoutError('blocked capture')
        with patch('desktop_guard.ScreenCapture') as create_capture:
            self.panel.start()
            create_capture.assert_not_called()
        self.assertIn('资源清理未完成',self.panel.status.text())

    def test_new_ocr_result_recovers_from_temporary_staleness(self):
        self.panel.last_ocr_finished=self.now-20
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.panel.worker.poll.return_value=[{'captured_at':self.now,'image':self.panel.latest.image,
                                             'lines':[],'elapsed_ms':20}]
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertIsNone(self.panel.error)


if __name__=='__main__':unittest.main()
