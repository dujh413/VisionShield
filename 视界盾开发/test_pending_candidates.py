"""仅用模拟几何验证待确认计数；不加载模型或访问摄像头。"""
import unittest
from unittest.mock import Mock

import numpy as np

from face_detection import FaceScanner


def face(x=100, y=100, w=100, h=120, score=.7):
    return np.array([x,y,w,h,x+w*.3,y+h*.3,x+w*.7,y+h*.3,
                     x+w*.5,y+h*.5,x+w*.3,y+h*.75,x+w*.7,y+h*.75,score],
                    dtype=np.float32)


class PendingCandidateTests(unittest.TestCase):
    def setUp(self):
        self.detector = Mock()
        self.scanner = FaceScanner(self.detector)

    def tearDown(self):
        self.detector.detect.assert_not_called()

    def test_count_starts_at_zero(self):
        self.assertEqual(self.scanner.current_unconfirmed_count,0)

    def test_confirmed_weak_owner_does_not_remain_pending(self):
        self.assertEqual(self.scanner._confirm_candidates([face()],0),[])
        self.assertEqual(self.scanner.current_unconfirmed_count,1)
        for index in range(1,5):
            with self.subTest(frame=index):
                result=self.scanner._confirm_candidates([face(100+index,100)],index*.1)
                self.assertEqual(len(result),1)
                self.assertEqual(self.scanner.current_unconfirmed_count,0)

    def test_weak_bystander_is_pending_only_until_spatial_confirmation(self):
        owner=face(score=.95)
        result=self.scanner._confirm_candidates([owner,face(400,120,40,50)],0)
        self.assertEqual(len(result),1)
        self.assertEqual(self.scanner.current_unconfirmed_count,1)
        result=self.scanner._confirm_candidates([owner,face(402,121,40,50)],.1)
        self.assertEqual(len(result),2)
        self.assertEqual(self.scanner.current_unconfirmed_count,0)

    def test_bad_landmarks_are_not_pending(self):
        invalid=face();invalid[4]=-100
        self.assertEqual(self.scanner._confirm_candidates([invalid],0),[])
        self.assertEqual(self.scanner.current_unconfirmed_count,0)
        self.assertEqual(self.scanner.weak_candidates,[])

    def test_disappeared_cached_candidate_does_not_count_in_current_frame(self):
        self.scanner._confirm_candidates([face()],0)
        self.assertEqual(self.scanner.current_unconfirmed_count,1)
        self.assertEqual(self.scanner._confirm_candidates([],.1),[])
        self.assertEqual(self.scanner.current_unconfirmed_count,0)
        self.assertEqual(len(self.scanner.weak_candidates),1)

    def test_strong_candidate_is_not_pending_even_with_old_weak_cache(self):
        self.scanner._confirm_candidates([face()],0)
        self.assertEqual(self.scanner.current_unconfirmed_count,1)
        self.assertEqual(len(self.scanner._confirm_candidates([face(score=.95)],.1)),1)
        self.assertEqual(self.scanner.current_unconfirmed_count,0)

    def test_same_frame_repeat_does_not_confirm_a_candidate(self):
        self.scanner._confirm_candidates([face()],0)
        self.assertEqual(self.scanner._confirm_candidates([face()],0),[])
        self.assertEqual(self.scanner.current_unconfirmed_count,1)


if __name__=='__main__':unittest.main()
