import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time
import subprocess
import sys
import unittest
import tempfile
import csv
import json
from pathlib import Path
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
        self.panel=ControlPanel(integrated=True, effect_text='遮挡')
        self.now=time.monotonic()
        p=self.panel
        p.started=self.now-40
        p.state=ProtectionState(restore_delay=0)
        p.camera=Mock(last={'owner_verified':True,'stranger_detected':False},error=None)
        p.camera.risk.return_value=(False,'机主独处且已确认')
        p.capture=Mock()
        p.capture.latest.return_value=None
        p.worker=Mock()
        p.worker.poll.return_value=[]
        p.worker.process.is_alive.return_value=True
        p.overlay=Mock()
        p.latest=Frame(1,self.now,{},np.zeros((64,64,3),dtype=np.uint8))
        p.content.observe(p.latest)
        self.lines=[{'text':'ordinary','confidence':.99,'polygon':[[10,10],[50,10],[50,25],[10,25]]}]
        p.content.accept({'frame_id':1,'captured_at':self.now,'image':p.latest.image,
                          'lines':self.lines,'unknown_regions':[]},self.now)
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

    def test_owner_pose_or_missing_face_does_not_emit_stranger_alert(self):
        self.panel.camera.risk.return_value=(True,'机主未确认')
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertIsNone(self.panel.alert_message)

    def test_detection_only_keeps_alert_without_shielding(self):
        self.panel.shield_enabled = False
        self.panel.camera.last['stranger_detected'] = True
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
                patch('pathlib.Path.open'), patch('capture_probe.verify_exclusion') as probe, \
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
        self.panel.latest.frame_id=2
        self.panel.content.observe(self.panel.latest)
        self.panel.worker.poll.return_value=[{'frame_id':2,'captured_at':self.now,'image':self.panel.latest.image,
                                             'lines':self.lines,'unknown_regions':[],'elapsed_ms':20}]
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertIsNone(self.panel.error)

    def test_empty_result_keeps_unknown_protected(self):
        self.panel.latest.frame_id=2
        self.panel.content.observe(self.panel.latest)
        self.panel.worker.poll.return_value=[{'frame_id':2,'captured_at':self.now,
            'image':self.panel.latest.image,'lines':[],'elapsed_ms':20}]
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertTrue(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_empty_mode_suppresses_exception_masks_without_stopping_detection(self):
        self.panel.apply_preferences({'effect_text':''})
        self.panel.camera.poll.side_effect=RuntimeError('synthetic failure')
        with patch('traceback.print_exc'):
            self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_latest_pending_frame_replaces_old_request_before_poll_dispatch(self):
        calls=[]
        self.panel.worker.submit.side_effect=lambda frame: calls.append(('submit',frame.frame_id)) or True
        self.panel.worker.poll.side_effect=lambda: calls.append(('poll',None)) or []
        self.tick()
        self.assertEqual(calls,[('submit',1),('poll',None)])
        calls.clear()
        self.now+=.11
        self.panel.latest=Frame(2,self.now,{},self.panel.latest.image.copy())
        self.panel.latest.image[3,3,0]=1
        self.panel.content.observe(self.panel.latest)
        self.tick()
        self.assertEqual(calls,[('submit',2),('poll',None)])

    def test_stable_screen_refreshes_without_duplicate_submission_each_tick(self):
        self.tick()
        self.assertEqual(self.panel.worker.submit.call_count,1)
        for _ in range(5):
            self.now+=.11
            self.panel.latest.captured_at=self.now
            self.tick()
        self.assertEqual(self.panel.worker.submit.call_count,1)
        self.now+=3
        self.panel.latest.captured_at=self.now
        self.tick()
        self.assertEqual(self.panel.worker.submit.call_count,2)

    def test_failed_submission_does_not_mark_frame_as_scheduled(self):
        self.panel.worker.submit.return_value=False
        self.tick()
        self.assertIsNone(self.panel.scheduler.image)
        self.panel.worker.submit.return_value=True
        self.tick()
        self.assertIs(self.panel.scheduler.image,self.panel.latest.image)

    def test_pause_discards_scheduler_state(self):
        self.tick()
        self.assertIsNotNone(self.panel.scheduler.image)
        self.panel.pause()
        self.assertIsNone(self.panel.scheduler.image)

    def test_enabled_performance_log_records_production_coverage_and_timings(self):
        from performance_log import PerformanceLog
        with tempfile.TemporaryDirectory() as directory:
            self.panel.diagnostics=PerformanceLog(directory)
            self.panel.worker.sent_frames=1
            self.panel.overlay.blur_ms=2
            self.panel.overlay.last_paint_ms=3
            self.panel.worker.poll.return_value=[{'ready':True,'providers':{'det':['CPUExecutionProvider']}}]
            self.tick()
            self.assertIsNone(self.panel.error)
            self.panel.diagnostics.close();self.panel.diagnostics=None
            with (Path(directory)/'heartbeat.csv').open(encoding='utf-8-sig') as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(rows[0]['unknown_regions'],'0')
            self.assertEqual(rows[0]['blur_ms'],'2')
            self.assertEqual(rows[0]['paint_ms'],'3')
            events=[json.loads(line) for line in (Path(directory)/'events.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(events[0]['event'],'ocr_ready')

    def test_empty_mode_stranger_alert_matches_detection_only_behavior(self):
        self.panel.apply_preferences({'effect_text':''})
        self.panel.camera.last['stranger_detected']=True
        self.panel.camera.risk.return_value=(True,'检测到旁人')
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertIn('遮蔽已关闭',self.panel.alert_message)

    def test_diagnostic_close_failure_resets_state_and_blocks_restart(self):
        self.panel.diagnostics=Mock()
        self.panel.diagnostics.close.side_effect=OSError('synthetic failure')
        self.tick()
        self.assertFalse(self.panel.pause())
        self.assertIsNone(self.panel.latest)
        self.assertIsNone(self.panel.scheduler.image)
        self.assertFalse(self.panel.ready)
        self.assertIn('diagnostics:OSError',self.panel.error)
        with patch('desktop_guard.ScreenCapture') as create_capture:
            self.panel.start()
            create_capture.assert_not_called()
        self.panel.diagnostics=None


if __name__=='__main__':unittest.main()
