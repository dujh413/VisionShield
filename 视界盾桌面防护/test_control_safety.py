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
from PySide6.QtCore import QTimer
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
        p.camera=Mock(last={'owner_verified':True,'stranger_detected':False,'sequence':1,'observed_at':self.now},error=None)
        p.camera.risk.return_value=(False,'机主独处且已确认')
        p.capture=Mock()
        p.capture.latest.return_value=None
        p.worker=Mock()
        p.worker.poll.return_value=[]
        p.worker.process.is_alive.return_value=True
        p.overlay=Mock()
        p.exclusion_verified=True
        p.latest=Frame(1,self.now,{'left':0,'top':0,'width':64,'height':64},np.zeros((64,64,3),dtype=np.uint8))
        inventory=patch('app_scope.window_inventory',return_value=[{'key':'test','handle':1,'pid':1,
            'mode':'window','rect':(0,0,64,64),'client':(0,0,64,64)}])
        inventory.start();self.addCleanup(inventory.stop)
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
        self.now+=.001
        self.panel.camera.last['sequence']+=1
        self.panel.camera.last['observed_at']=self.now
        with patch('desktop_guard.time.monotonic',return_value=self.now):
            self.panel.tick()

    def test_capture_stall_forces_full_protection_even_when_owner_safe(self):
        self.panel.latest.captured_at=self.now-2
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])
        self.assertEqual(self.panel.overlay.set_masks.call_args.args[0],[(0,0,64,64)])

    def test_future_or_nonfinite_capture_keeps_protection_when_owner_safe(self):
        for stamp in (self.now+2,float('nan'),float('inf')):
            with self.subTest(stamp=stamp):
                self.panel.latest.captured_at=stamp
                self.tick()
                self.assertTrue(self.panel.protecting)
                self.assertIn('桌面采集未及时更新',self.panel.status.text())
                self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_stale_ocr_forces_full_protection_even_when_owner_safe(self):
        self.panel.last_ocr_finished=self.now-20
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def test_camera_risk_cannot_be_overridden_by_fresh_ocr(self):
        self.panel.camera.risk.return_value=(True,'检测到旁人')
        self.tick()
        self.assertTrue(self.panel.protecting)

    def test_same_safe_camera_packet_does_not_restore_after_ui_wait(self):
        self.panel.state=ProtectionState(restore_delay=1)
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.now+=1.1
        self.panel.latest.captured_at=self.now
        with patch('desktop_guard.time.monotonic',return_value=self.now):
            self.panel.tick()
        self.assertTrue(self.panel.protecting)
        self.tick()
        self.assertFalse(self.panel.protecting)

    def test_lost_camera_packet_resets_recovery_without_stranger_alert(self):
        self.panel.state=ProtectionState(restore_delay=1)
        self.tick()
        self.now+=1.1
        self.panel.latest.captured_at=self.now
        self.panel.camera.last['sequence']+=2
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertIsNone(self.panel.alert_message)
        self.assertIn('相机观察未连续确认',self.panel.status.text())

    def test_carried_stranger_event_alerts_even_when_latest_face_packet_is_safe(self):
        self.panel.camera.new_stranger_event=True
        self.panel.camera.risk.return_value=(True,'近期检测到旁人')
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertIsNotNone(self.panel.alert_message)

    def test_missing_selection_is_visible_even_while_owner_is_safe(self):
        self.panel.app_profiles={'missing':{'mode':'window','binding':{'handle':99,'pid':99}}}
        self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertIn('已定位0/1',self.panel.status.text())
        self.assertIn('不会扩大保护',self.panel.status.text())

    def test_partial_scope_resolution_does_not_claim_all_scopes_are_ready(self):
        self.panel.app_profiles={'test':{'mode':'window','binding':{'handle':1,'pid':1}},
                                 'missing':{'mode':'window','binding':{'handle':99,'pid':99}}}
        self.tick()
        self.assertIn('已定位1/2',self.panel.status.text())

    def test_pause_during_capture_probe_does_not_reopen_overlay_or_leak_capture(self):
        self.panel.exclusion_verified=False
        capture=Mock()
        with patch('desktop_guard.ScreenCapture',return_value=capture), \
                patch('capture_probe.verify_exclusion',side_effect=lambda *args:self.panel.pause()):
            self.assertFalse(self.panel.verify_range_capture([(0,0,64,64)]))
        self.assertIsNone(self.panel.overlay)
        self.assertFalse(self.panel.probe_active)
        self.assertFalse(self.panel.exclusion_verified)
        capture.close.assert_called_once()

    def test_probe_cancels_on_window_move_frontend_overlap_or_window_loss(self):
        original={'key':'test','handle':1,'pid':1,'mode':'lines',
                  'rect':(0,0,64,64),'client':(0,0,64,64)}
        changes=([dict(original,rect=(100,0,64,64),client=(100,0,64,64))],
                 [dict(original),{'key':'own','handle':2,'pid':2,'mode':'ignore','own_ui':True,
                                  'rect':(0,0,30,30),'client':(0,0,30,30)}],[])
        for changed in changes:
            with self.subTest(windows=changed):
                p=self.panel;p.exclusion_verified=False;p.error=None;p.overlay=Mock()
                p.app_profiles={'test':{'mode':'window','binding':{'handle':1,'pid':1}}}
                p.region_tracker=Mock();p.region_tracker.resolve.return_value={}
                inventory=[dict(original)];capture=Mock()
                capture.grab.return_value=type('Frame',(),{'image':np.full((1000,1000,3),[255,255,0],dtype=np.uint8)})()
                QTimer.singleShot(40,lambda changed=changed:inventory.__setitem__(slice(None),changed))
                with patch('desktop_guard.ScreenCapture',return_value=capture), \
                        patch('app_scope.window_inventory',side_effect=lambda monitor:list(inventory)):
                    self.assertFalse(p.verify_range_capture([(0,0,64,64)],list(inventory)))
                self.assertIsNone(p.error)
                self.assertFalse(p.exclusion_verified)
                self.assertEqual(p.overlay.set_masks.call_args.args[0],[])
                capture.grab.assert_not_called();capture.close.assert_called_once()

    def test_probe_cancels_on_internal_native_anchor_move(self):
        p=self.panel;p.exclusion_verified=False;p.error=None
        p.app_profiles={'test':{'mode':'tracked','binding':{'handle':1,'pid':1},
            'anchor':{'type':'native','class':'Pane','id':12,'fraction':[0,0,1,1]}}}
        resolved={'test':{'handle':1,'rect':(0,0,30,30)}}
        p.region_tracker=Mock();p.region_tracker.resolve.side_effect=lambda *args,**kwargs:resolved
        capture=Mock()
        QTimer.singleShot(40,lambda:resolved['test'].__setitem__('rect',(30,30,30,30)))
        with patch('desktop_guard.ScreenCapture',return_value=capture):
            self.assertFalse(p.verify_range_capture([(0,0,30,30)]))
        self.assertIsNone(p.error);self.assertFalse(p.exclusion_verified)
        self.assertEqual(p.overlay.set_masks.call_args.args[0],[])
        capture.grab.assert_not_called();capture.close.assert_called_once()

    def test_irrelevant_background_z_order_change_still_allows_native_verification(self):
        p=self.panel;p.exclusion_verified=False;p.error=None
        p.app_profiles={'test':{'mode':'window','binding':{'handle':1,'pid':1}}}
        p.region_tracker=Mock();p.region_tracker.resolve.return_value={}
        target={'key':'test','handle':1,'pid':1,'mode':'lines','rect':(0,0,64,64),'client':(0,0,64,64)}
        tray={'key':'tray','handle':2,'pid':2,'mode':'ignore','rect':(0,100,64,10),'client':(0,100,64,10)}
        inventory=[tray,target];capture=Mock()
        capture.grab.return_value=type('Frame',(),{'image':np.full((1000,1000,3),[255,255,0],dtype=np.uint8)})()
        QTimer.singleShot(40,inventory.reverse)
        with patch('desktop_guard.ScreenCapture',return_value=capture), \
                patch('app_scope.window_inventory',side_effect=lambda monitor:list(inventory)):
            self.assertTrue(p.verify_range_capture([(0,0,64,64)],list(inventory)))
        self.assertTrue(p.exclusion_verified);self.assertIsNone(p.error)
        capture.grab.assert_called_once();capture.close.assert_called_once()

    def test_probe_cancels_on_uia_client_change_without_reusing_cached_rect(self):
        p=self.panel;p.exclusion_verified=False;p.error=None
        p.app_profiles={'test':{'mode':'tracked','binding':{'handle':1,'pid':1},
            'anchor':{'type':'uia','path':[{'kind':1,'class':'Pane','id':'pane'}],'fraction':[0,0,1,1]}}}
        p.region_tracker=Mock();p.region_tracker.resolve.return_value={'test':{'handle':1,'rect':(0,0,30,30)}}
        capture=Mock();image=p.latest.image.copy()
        capture.grab.side_effect=lambda:type('Frame',(),{'image':image.copy()})()
        QTimer.singleShot(40,lambda:image.__setitem__((slice(20,25),slice(20,25)),255))
        with patch('desktop_guard.ScreenCapture',return_value=capture):
            self.assertFalse(p.verify_range_capture([(0,0,30,30)]))
        self.assertIsNone(p.error);self.assertFalse(p.exclusion_verified)
        self.assertEqual(p.overlay.set_masks.call_args.args[0],[])
        self.assertGreater(capture.grab.call_count,1);capture.close.assert_called_once()

    def test_owner_pose_or_missing_face_does_not_emit_stranger_alert(self):
        self.panel.camera.risk.return_value=(True,'机主未确认')
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertIsNone(self.panel.alert_message)

    def test_pending_candidate_protects_without_stranger_alert(self):
        self.panel.camera.last['candidate_pending']=True
        self.panel.camera.risk.return_value=(True,'候选人脸待确认，暂时保护')
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
        self.assertFalse(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])
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

    def test_empty_result_keeps_unknown_protected_when_camera_reports_risk(self):
        self.panel.camera.risk.return_value=(True,'检测到旁人')
        self.panel.latest.frame_id=2
        self.panel.content.observe(self.panel.latest)
        self.panel.worker.poll.return_value=[{'frame_id':2,'captured_at':self.now,
            'image':self.panel.latest.image,'lines':[],'elapsed_ms':20}]
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertFalse(self.panel.overlay.set_masks.call_args.kwargs['full'])

    def confirm_owner(self):
        self.panel.state=ProtectionState(restore_delay=1)
        for advance in (0,.4,.7):
            self.now+=advance
            self.panel.latest.captured_at=self.now
            self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertEqual(self.panel.overlay.set_masks.call_args.args[0],[])
        self.assertIn('正常显示',self.panel.status.text())

    def test_owner_alone_recovers_with_empty_ocr_in_both_display_modes(self):
        for effect in ('遮挡','16'):
            with self.subTest(effect=effect):
                self.panel.apply_preferences({'effect_text':effect})
                self.panel.latest.frame_id+=1
                self.panel.content.observe(self.panel.latest)
                self.panel.content.accept({'frame_id':self.panel.latest.frame_id,
                    'captured_at':self.now,'image':self.panel.latest.image,
                    'lines':[],'unknown_regions':[]},self.now)
                self.assertTrue(self.panel.content.view(self.now)['full'])
                self.confirm_owner()

    def test_owner_alone_recovers_while_first_ocr_is_loading(self):
        self.panel.content.result=None
        self.panel.last_ocr_finished=None
        self.panel.started=self.now
        self.panel.ready=False
        self.assertTrue(self.panel.content.view(self.now)['full'])
        self.confirm_owner()
        self.assertIn('OCR：加载中',self.panel.status.text())

    def test_owner_alone_recovers_on_large_dynamic_content_changes(self):
        self.panel.latest=Frame(2,self.now,self.panel.latest.monitor_rect,
                                np.full((64,64,3),255,dtype=np.uint8))
        self.panel.content.observe(self.panel.latest)
        self.assertTrue(self.panel.content.view(self.now)['full'])
        self.confirm_owner()

    def test_expired_ocr_still_protects_before_legacy_fifteen_second_timeout(self):
        self.now+=10.1
        self.panel.latest.captured_at=self.now
        self.tick()
        self.assertTrue(self.panel.protecting)
        self.assertIn('OCR结果未及时更新',self.panel.status.text())

    def test_complete_camera_history_allows_latest_only_queue_recovery(self):
        self.panel.state=ProtectionState(restore_delay=1)
        self.panel.camera.last.update(last_risk_sequence=0,last_risk_observed_at=None)
        for advance in (0,.4,.7):
            self.now+=advance
            self.panel.latest.captured_at=self.now
            self.panel.camera.last['sequence']+=2
            self.tick()
        self.assertFalse(self.panel.protecting)
        self.assertNotIn('相机观察未连续确认',self.panel.status.text())

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
