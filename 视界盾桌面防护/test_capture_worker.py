import time
import unittest
from unittest.mock import Mock,patch
import numpy as np
from screen_capture import CaptureWorker,Frame,ScreenCapture


class FakeCapture:
    def grab(self):
        time.sleep(.08)
        return Frame(1,time.monotonic(),{},np.zeros((2,2,3),dtype=np.uint8))
    def close(self):
        pass


class CaptureTests(unittest.TestCase):
    def test_capture_publishes_independent_owned_readonly_pixels(self):
        pixels=np.full((3,4,4),120,np.uint8)
        source=Mock(monitors=[{}, {'left':0,'top':0,'width':4,'height':3}])
        source.grab.return_value=pixels
        with patch('screen_capture.mss.mss',return_value=source):
            capture=ScreenCapture()
            try:
                first=capture.grab()
                self.assertEqual(first.image.shape,(3,4,3))
                self.assertTrue(first.image.flags.owndata)
                self.assertTrue(first.image.flags.c_contiguous)
                self.assertFalse(first.image.flags.writeable)
                self.assertIsNone(first.image.base)
                with self.assertRaises(ValueError):first.image[0,0,0]=0
                pixels[0,0,0]=99
                second=capture.grab()
                self.assertEqual(first.image[0,0,0],120)
                self.assertEqual(second.image[0,0,0],99)
                self.assertIsNot(first.image,second.image)
                self.assertEqual((first.frame_id,second.frame_id),(1,2))
            finally:capture.close()
        source.close.assert_called_once()

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
