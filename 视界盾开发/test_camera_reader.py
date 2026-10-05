import queue
import unittest

from camera_test import LatestCameraFrame


class FakeCamera:
    def __init__(self):
        self.frames=queue.Queue()
        self.released=False

    def read(self):
        frame=self.frames.get(timeout=2)
        return frame is not None,frame

    def release(self):
        self.released=True
        self.frames.put(None)


class CameraReaderTests(unittest.TestCase):
    def test_slow_consumer_receives_latest_frame_without_growing_queue(self):
        camera=FakeCamera();reader=LatestCameraFrame(camera)
        try:
            for frame in range(20):camera.frames.put(frame)
            with reader.condition:
                self.assertTrue(reader.condition.wait_for(lambda:reader.sequence==20,timeout=2))
            ok,frame=reader.read()
            self.assertTrue(ok);self.assertEqual(frame,19)
            self.assertEqual(reader.consumed,20)
            self.assertIsNotNone(reader.last_consumed_at)
            self.assertFalse(reader.read(timeout=.01)[0])
        finally:reader.close()
        self.assertTrue(camera.released)
        self.assertFalse(reader.thread.is_alive())
        self.assertIsNone(reader.frame)

    def test_device_failure_wakes_waiting_consumer_and_cannot_reuse_old_frame(self):
        camera=FakeCamera();reader=LatestCameraFrame(camera)
        try:
            camera.frames.put(None)
            self.assertEqual(reader.read(timeout=2),(False,None))
        finally:reader.close()


if __name__=='__main__':unittest.main()
