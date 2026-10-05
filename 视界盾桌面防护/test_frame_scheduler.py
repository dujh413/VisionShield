import unittest
from types import SimpleNamespace
import numpy as np
from frame_scheduler import FrameScheduler


class FrameSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.policy=FrameScheduler()
        self.image=np.zeros((32,64,3),dtype=np.uint8)

    def frame(self, image=None, captured_at=0):
        return SimpleNamespace(image=self.image if image is None else image,captured_at=captured_at)

    def test_stable_frames_refresh_periodically(self):
        frame=self.frame()
        self.assertTrue(self.policy.due(frame,0))
        self.policy.submitted(frame,0)
        self.assertFalse(self.policy.due(self.frame(self.image.copy(),.5),.5))
        self.assertTrue(self.policy.due(self.frame(self.image.copy(),3),3))

    def test_single_channel_single_pixel_is_not_ignored(self):
        self.policy.submitted(self.frame(),0)
        changed=self.image.copy();changed[12,13,2]=1
        self.assertTrue(self.policy.due(self.frame(changed,.2),.2))

    def test_expired_or_future_capture_is_not_submitted(self):
        self.assertFalse(self.policy.due(self.frame(captured_at=2),1))
        self.assertFalse(self.policy.due(self.frame(),2))

    def test_resolution_change_is_submitted(self):
        self.policy.submitted(self.frame(),0)
        self.assertTrue(self.policy.due(self.frame(np.zeros((16,32,3),dtype=np.uint8),.2),.2))

    def test_minimum_interval_does_not_mutate_submission_state(self):
        self.policy.submitted(self.frame(),0)
        self.assertFalse(self.policy.due(self.frame(np.ones_like(self.image),.01),.01))
        self.assertIs(self.policy.image,self.image)


if __name__=='__main__':unittest.main()
