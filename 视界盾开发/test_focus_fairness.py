"""用几何候选复现前景占用背景轮转；不访问模型或设备。"""
import unittest

import numpy as np

from face_detection import FaceScanner
from test_face_detection import face


class InjectedScanner(FaceScanner):
    def __init__(self, target):
        super().__init__(None)
        self.target=target
        self.calls=[]

    def _detect(self,image,origin=(0,0),enlarge=False,max_edge=None,frame_size=None,label='full'):
        self.calls.append(label)
        return [self.target.copy()] if label in ('full','focus','focus_contrast') else []

    @staticmethod
    def _contrast(image):return image


class FocusFairnessTests(unittest.TestCase):
    def scan(self, scanner, count=12):
        image=np.zeros((720,1280,3),np.uint8)
        frames=[]
        for index in range(count):
            scanner.calls=[]
            rows=scanner.detect(image,index*.2)
            frames.append((scanner.calls.copy(),len(rows)))
        return frames

    def test_strong_foreground_keeps_contrast_and_background_visits_all_tiles_in_three_frames(self):
        scanner=InjectedScanner(face(500,150,197,261))
        frames=self.scan(scanner)
        self.assertIsNotNone(scanner.focus)
        self.assertTrue(all(count==1 and 'focus' not in calls for calls,count in frames))
        self.assertTrue(all('focus_contrast' in calls for calls,_ in frames[1:]))
        self.assertEqual([call for calls,_ in frames[:3] for call in calls if call.startswith('tile_')],
                         ['tile_0','tile_1','tile_2','tile_3','tile_4','tile_5'])

    def test_invalid_weak_landmarks_neither_protect_nor_lock_focus(self):
        target=face(500,150,20,24,.65);target[4]=490
        scanner=InjectedScanner(target)
        frames=self.scan(scanner)
        self.assertIsNone(scanner.focus)
        self.assertTrue(all(count==0 and 'focus' not in calls for calls,count in frames))
        self.assertEqual(scanner.current_unconfirmed_count,0)

    def test_real_small_and_weak_foreground_still_get_original_and_contrast_recheck(self):
        for target in (face(500,150,24,32),face(500,150,197,261,.72)):
            with self.subTest(target=target[:4]):
                scanner=InjectedScanner(target)
                frames=self.scan(scanner)
                self.assertIsNotNone(scanner.focus)
                self.assertIn('focus',frames[1][0])
                self.assertIn('focus_contrast',frames[1][0])
                self.assertEqual(frames[-1][1],1)

    def test_prior_weak_focus_uses_only_contrast_when_same_face_is_now_strong_full(self):
        scanner=InjectedScanner(face(500,150,197,261,.72))
        self.scan(scanner,1)
        self.assertIsNotNone(scanner.focus)
        scanner.target[14]=.95
        scanner.calls=[]
        scanner.detect(np.zeros((720,1280,3),np.uint8),.2)
        self.assertIsNotNone(scanner.focus)
        self.assertNotIn('focus',scanner.calls)
        self.assertIn('focus_contrast',scanner.calls)
        self.assertEqual(sum(call.startswith('tile_') for call in scanner.calls),2)

    def test_nearby_different_face_cannot_release_small_face_focus(self):
        scanner=InjectedScanner(face(500,150,90,110,.72))
        self.scan(scanner,1)
        scanner.target=face(565,150,197,261)
        scanner.calls=[]
        scanner.detect(np.zeros((720,1280,3),np.uint8),.2)
        self.assertIn('focus',scanner.calls)

    def test_wide_contrast_finds_weak_background_and_small_contrast_confirms_it(self):
        class HistoricalScanner(InjectedScanner):
            def _detect(self,image,origin=(0,0),enlarge=False,max_edge=None,frame_size=None,label='full'):
                self.calls.append(label)
                if label=='full':return [face(486,270,213,273,.956)]
                if label=='focus_contrast' and self.frame>=1:
                    return [face(610,40,40,40,.601 if self.frame==1 else .764)]
                return []
        scanner=HistoricalScanner(None)
        image=np.zeros((720,1280,3),np.uint8)
        scanner.frame=0;scanner.detect(image,0)
        scanner.frame=1;scanner.calls=[]
        self.assertEqual(len(scanner.detect(image,.2)),1)
        self.assertNotIn('focus',scanner.calls)
        self.assertIn('focus_contrast',scanner.calls)
        self.assertEqual(scanner.current_unconfirmed_count,1)
        self.assertLess(float(scanner.focus['face'][2]),50)
        scanner.frame=2;scanner.calls=[]
        self.assertEqual(len(scanner.detect(image,.4)),2)
        self.assertIn('focus',scanner.calls)
        self.assertIn('focus_contrast',scanner.calls)
        self.assertEqual(scanner.current_unconfirmed_count,0)


if __name__=='__main__':unittest.main()
