import queue
import unittest
from unittest.mock import Mock
import numpy as np
from ocr_worker import OCRWorker
from screen_capture import Frame


class SchedulingTests(unittest.TestCase):
    def worker(self):
        worker=OCRWorker.__new__(OCRWorker)
        worker.inputs,worker.outputs=queue.Queue(1),queue.Queue(2)
        worker.process=Mock()
        worker.busy=worker.failed=worker.closed=False
        worker.pending=None
        worker.sent_frames=0
        return worker

    def frame(self, number):
        return Frame(number,0,{},np.zeros((10,10,3),dtype=np.uint8))

    def test_busy_worker_serializes_only_newest_pending_when_result_arrives(self):
        worker=self.worker()
        self.assertTrue(worker.submit(self.frame(1)))
        self.assertEqual(worker.inputs.get_nowait().frame_id,1)
        for number in range(2,101):
            worker.submit(self.frame(number))
        self.assertTrue(worker.inputs.empty())
        self.assertEqual(worker.pending.frame_id,100)
        self.assertEqual(worker.sent_frames,1)
        worker.outputs.put({'lines':[],'frame_id':1})
        self.assertEqual(len(worker.poll()),1)
        self.assertEqual(worker.inputs.get_nowait().frame_id,100)
        self.assertEqual(worker.sent_frames,2)
        self.assertIsNone(worker.pending)

    def test_ready_does_not_dispatch_pending_before_active_frame_finishes(self):
        worker=self.worker();worker.submit(self.frame(1));worker.inputs.get_nowait()
        worker.submit(self.frame(2));worker.outputs.put({'ready':True})
        worker.poll()
        self.assertTrue(worker.inputs.empty())
        self.assertTrue(worker.busy)

    def test_failure_drops_pending_and_refuses_new_submissions(self):
        worker=self.worker();worker.submit(self.frame(1));worker.inputs.get_nowait()
        worker.submit(self.frame(2));worker.outputs.put({'error':'synthetic'})
        worker.poll()
        self.assertTrue(worker.inputs.empty())
        self.assertIsNone(worker.pending)
        self.assertFalse(worker.submit(self.frame(3)))

    def test_closed_worker_refuses_new_submissions(self):
        worker=self.worker();worker.closed=True
        self.assertFalse(worker.submit(self.frame(1)))
        self.assertTrue(worker.inputs.empty())

    def test_failed_process_cleanup_raises_for_controller_retry(self):
        worker=self.worker();worker.process.is_alive.return_value=True
        with self.assertRaises(TimeoutError):worker.close()
        self.assertTrue(worker.closed)
        self.assertIsNone(worker.pending)


if __name__=='__main__':unittest.main()
