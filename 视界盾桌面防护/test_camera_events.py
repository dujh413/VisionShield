"""状态队列边沿与恢复验证；不访问摄像头、图片或机主模板。"""
import queue
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'视界盾开发'))

from camera_worker import CameraWorker, StrangerJournal, camera_main


def packet(sequence, stamp, event=0, event_at=None, stranger=False):
    return {'sequence':sequence,'observed_at':stamp,'enrolled':True,
            'protect_request':stranger,'stranger_detected':stranger,
            'last_stranger_sequence':event,'last_stranger_observed_at':event_at}


class CameraEventTests(unittest.TestCase):
    def worker(self):
        worker=CameraWorker.__new__(CameraWorker)
        worker.outputs=queue.Queue(2)
        worker.process=Mock();worker.process.is_alive.return_value=True
        worker.last=worker.error=None
        worker.last_stranger_sequence=0
        worker.new_stranger_event=False
        return worker

    def test_journal_retains_real_observation_without_refreshing_from_hold(self):
        journal=StrangerJournal()
        self.assertEqual(journal.record(1,10,False)['last_stranger_sequence'],0)
        first=journal.record(2,10.2,True)
        self.assertEqual(journal.record(3,10.4,False),first)
        self.assertEqual(journal.record(4,10.6,False),first)
        self.assertEqual(journal.record(5,10.8,True)['last_stranger_sequence'],5)

    def test_latest_safe_packet_carries_dropped_stranger_event_and_consumes_once(self):
        worker=self.worker()
        worker.outputs.put(packet(4,10.6,2,10.2))
        worker.poll()
        self.assertTrue(worker.new_stranger_event)
        self.assertTrue(worker.risk(10.7)[0])
        self.assertFalse(worker.last['stranger_detected'])
        worker.poll()
        self.assertFalse(worker.new_stranger_event)
        self.assertFalse(worker.risk(10.8)[0])
        worker.outputs.put(packet(5,10.9,2,10.2))
        worker.poll()
        self.assertFalse(worker.new_stranger_event)
        self.assertFalse(worker.risk(11)[0])

    def test_draining_stranger_then_safe_does_not_erase_event(self):
        worker=self.worker()
        worker.outputs.put(packet(2,10.2,2,10.2,True))
        worker.outputs.put(packet(3,10.4,2,10.2))
        worker.poll()
        self.assertTrue(worker.new_stranger_event)
        self.assertEqual(worker.last['sequence'],3)
        self.assertTrue(worker.risk(10.5)[0])

    def test_reordered_packet_cannot_lower_status_or_event_watermark(self):
        worker=self.worker()
        self.assertTrue(worker.accept_status(packet(4,10.6,2,10.2)))
        self.assertFalse(worker.accept_status(packet(3,10.4)))
        self.assertFalse(worker.accept_status(packet(5,10.5)))
        self.assertEqual(worker.last['sequence'],4)
        self.assertEqual(worker.last_stranger_sequence,2)

    def test_invalid_status_fails_closed(self):
        invalid=(None,[],packet(True,10),packet(1,float('nan')),
                 packet(1,10,2,10),packet(1,10,1,None),packet(1,10,1,11))
        for value in invalid:
            with self.subTest(value=value):
                worker=self.worker()
                self.assertFalse(worker.accept_status(value))
                self.assertTrue(worker.risk(10)[0])

    def test_future_stale_and_exited_camera_cannot_claim_safe(self):
        worker=self.worker();worker.accept_status(packet(1,10))
        self.assertTrue(worker.risk(9)[0])
        self.assertTrue(worker.risk(11.6)[0])
        worker.process.is_alive.return_value=False
        worker.poll()
        self.assertTrue(worker.risk(10)[0])

    def test_missing_or_non_boolean_risk_fields_fail_closed_without_exception(self):
        for key in ('enrolled','protect_request','stranger_detected'):
            for value in (None,0,'false'):
                with self.subTest(key=key,value=value):
                    worker=self.worker();status=packet(1,10);status[key]=value
                    self.assertFalse(worker.accept_status(status))
                    self.assertTrue(worker.risk(10)[0])
            worker=self.worker();status=packet(1,10);del status[key]
            self.assertFalse(worker.accept_status(status))
            self.assertTrue(worker.risk(10)[0])

    def test_stranger_flag_cannot_be_overridden_by_false_protect_request(self):
        worker=self.worker();status=packet(1,10,stranger=True)
        status['protect_request']=False
        self.assertTrue(worker.accept_status(status))
        self.assertTrue(worker.risk(10)[0])

    def test_capture_time_and_uncertain_candidate_do_not_fake_stranger(self):
        stop=Mock();stop.is_set.side_effect=[False,True]
        reader=Mock(last_consumed_at=11.3)
        reader.read.return_value=(True,np.zeros((72,128,3),np.uint8))
        scanner=Mock(last_metrics={},current_unconfirmed_count=1);scanner.detect.return_value=[]
        tracker=Mock();tracker.update.return_value=[]
        presence=Mock();presence.update.return_value={
            'owner_verified':True,'owner_session_active':True,'pose_grace':False,
            'stranger_detected':False,'protect_request':False}
        with patch('identity_test.load_models',return_value=(Mock(),Mock())), \
             patch('camera_test.open_camera') as open_camera, \
             patch('camera_test.LatestCameraFrame',return_value=reader), \
             patch('face_detection.FaceScanner',return_value=scanner), \
             patch('owner_tracking.ShortTracker',return_value=tracker), \
             patch('owner_presence.OwnerPresence',return_value=presence), \
             patch('ocr_worker.put_latest') as publish, \
             patch('camera_worker.owner_file') as owner_path, \
             patch('numpy.load') as template, \
             patch('camera_worker.time.monotonic',side_effect=[10,11,11.5,11.6]):
            owner_path.return_value.exists.return_value=True
            template.return_value.__enter__.return_value={'features':np.ones((1,2))}
            camera_main(Path('.'),stop,Mock())
        open_camera.assert_called_once()
        scanner.detect.assert_called_once_with(reader.read.return_value[1],11.3)
        self.assertEqual(presence.update.call_args.args[0],11.3)
        self.assertEqual(publish.call_args.args[1]['observed_at'],11.3)
        self.assertEqual(publish.call_args.args[1]['frame_age_ms'],200.)
        status=publish.call_args.args[1]
        self.assertTrue(status['candidate_pending'])
        self.assertTrue(status['protect_request'])
        self.assertTrue(status['owner_verified'])
        self.assertFalse(status['stranger_detected'])
        self.assertEqual(status['last_stranger_sequence'],0)
        worker=self.worker();worker.accept_status(status)
        self.assertFalse(worker.new_stranger_event)
        self.assertEqual(worker.risk(11.6),(True,'候选人脸待确认，暂时保护'))
        reader.close.assert_called_once()


if __name__=='__main__':unittest.main()
