import time
import unittest
from unittest.mock import patch
import numpy as np
from screen_capture import CaptureWorker,Frame


class FakeCapture:
    def grab(self):
        time.sleep(.08)
        return Frame(1,time.monotonic(),{},np.zeros((2,2,3),dtype=np.uint8))
    def close(self):
        pass


class CaptureTests(unittest.TestCase):
    def test_slow_capture_does_not_block_consumer(self):
        with patch('screen_capture.ScreenCapture',FakeCapture):
            worker=CaptureWorker()
            try:
                start=time.perf_counter()
                for _ in range(100): worker.latest()
                self.assertLess(time.perf_counter()-start,.05)
                time.sleep(.12)
                self.assertIsNotNone(worker.latest())
            finally:
                worker.close()
            self.assertFalse(worker.thread.is_alive())

    def test_capture_failure_is_visible(self):
        with patch('screen_capture.ScreenCapture',side_effect=RuntimeError('fake')):
            worker=CaptureWorker()
            try:
                worker.thread.join(timeout=1)
                with self.assertRaises(RuntimeError): worker.latest()
            finally: worker.close()


if __name__=='__main__':
    unittest.main()
