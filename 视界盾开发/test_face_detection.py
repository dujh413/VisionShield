import unittest
from unittest.mock import Mock

import numpy as np

from face_detection import BystanderHold, FaceScanner, map_faces, merge_faces, unmirror_faces


def face(x=100, y=100, w=100, h=100, score=.95):
    return np.array([x,y,w,h,x+w*.3,y+h*.3,x+w*.7,y+h*.3,
                     x+w*.5,y+h*.5,x+w*.3,y+h*.75,x+w*.7,y+h*.75,score],dtype=np.float32)


class FaceDetectionTests(unittest.TestCase):
    def test_background_enhancement_alternates_without_skipping_normal_observations(self):
        detector=Mock();detector.detect.return_value=(None,None)
        scanner=FaceScanner(detector,detail_interval=0,mirror_scan=True,diagnostics=True)
        image=np.zeros((64,96,3),np.uint8)
        enhanced=[]
        for stamp in (0,.09375,.203125,.296875):
            scanner.detect(image,stamp)
            scans=[item['scan'] for item in scanner.last_metrics['scans']]
            self.assertEqual(scans.count('full'),1)
            self.assertEqual(len([name for name in scans if name.startswith('tile_')]),2)
            enhanced.append('background_mirror' in scans)
        self.assertEqual(enhanced,[True,False,True,False])
        self.assertEqual(detector.detect.call_count,14)

    def test_mirror_inverse_preserves_original_eye_mouth_order_and_input(self):
        original=face(20,30,40,60)
        mirrored=original.copy()
        mirrored[0]=200-original[0]-original[2]
        points=original[4:14].reshape(5,2).copy()
        points[:,0]=199-points[:,0]
        mirrored[4:14]=points[[1,0,2,4,3]].reshape(10)
        before=mirrored.copy()
        np.testing.assert_array_equal(unmirror_faces([mirrored],200)[0],original)
        np.testing.assert_array_equal(mirrored,before)
        self.assertEqual(unmirror_faces(None,200).shape,(0,15))

    def test_mirror_scan_candidate_maps_to_actual_background_and_keeps_owner_coordinates(self):
        detector=Mock()
        owner=face(110,30,40,60,.95)
        background=face(105,20,20,25,.7)
        detector.detect.side_effect=[(None,np.array([owner])),(None,np.array([background])),
                                     (None,None),(None,None)]
        scanner=FaceScanner(detector,max_edge=200,mirror_scan=True,diagnostics=True)
        image=np.zeros((100,200,3),np.uint8)
        # Keep the mock inverse at camera scale while testing the state machine.
        detect=scanner._detect
        def stage(patch,*args,**kwargs):
            if kwargs.get('label')=='background_mirror':kwargs['max_edge']=200
            return detect(patch,*args,**kwargs)
        scanner._detect=stage
        result=scanner.detect(image,0)
        self.assertEqual(len(result),1)
        np.testing.assert_array_equal(result[0],owner)
        self.assertEqual(scanner.current_unconfirmed_count,1)
        candidate=scanner.weak_candidates[0]['face']
        self.assertEqual(float(candidate[0]),75)
        self.assertIn('background_mirror',[item['scan'] for item in scanner.last_metrics['scans']])

    def test_crop_mapping_includes_box_landmarks_and_preserves_score(self):
        original=face(20,40,60,80)
        result=map_faces([original],2,(300,100))[0]
        np.testing.assert_allclose(result[:4],[310,120,30,40])
        np.testing.assert_allclose(result[[4,6,8,10,12]],original[[4,6,8,10,12]]/2+300)
        np.testing.assert_allclose(result[[5,7,9,11,13]],original[[5,7,9,11,13]]/2+100)
        self.assertEqual(result[14],original[14])
        np.testing.assert_array_equal(original,face(20,40,60,80))

    def test_none_results_map_to_empty_consistent_shape(self):
        self.assertEqual(map_faces(None,2).shape,(0,15))

    def test_multi_scale_duplicates_do_not_fabricate_bystanders(self):
        kept=merge_faces([face(score=.85),face(103,102,99,98,.96),face(300,100,24,28)],(640,480))
        self.assertEqual(len(kept),2)
        self.assertAlmostEqual(float(kept[0][14]),.96,places=5)

    def test_overlapping_different_faces_and_small_background_face_remain(self):
        kept=merge_faces([face(),face(140,100),face(130,130,20,20)],(640,480))
        self.assertEqual(len(kept),3)

    def test_partial_box_for_the_same_landmarks_does_not_fabricate_a_bystander(self):
        complete=face(100,100,260,360,.93)
        partial=face(100,220,272,242,.83)
        partial[4:14]=complete[4:14]
        self.assertEqual(len(merge_faces([complete,partial],(1280,720))),1)

    def test_strong_full_frame_face_keeps_its_landmarks_over_higher_crop_confidence(self):
        full=face(100,100,180,240,.91);crop=face(103,102,183,241,.95)
        kept=merge_faces([full,crop],(1280,720),full_count=1)
        self.assertEqual(len(kept),1)
        np.testing.assert_array_equal(kept[0],full)

    def test_large_nested_roi_subface_is_ignored_but_small_far_and_adjacent_faces_remain(self):
        full=face(100,100,200,260,.91)
        false_subface=face(135,160,130,146,.87)
        far=face(105,105,20,24,.9)
        neighbor=face(270,130,90,120,.85)
        kept=merge_faces([full,false_subface,far,neighbor],(1280,720),full_count=1)
        self.assertEqual(len(kept),3)
        self.assertTrue(any(np.array_equal(item,far) for item in kept))
        self.assertTrue(any(np.array_equal(item,neighbor) for item in kept))

    def test_two_full_frame_faces_cannot_be_rejected_by_nested_roi_heuristic(self):
        full=face(100,100,200,260,.91);other=face(135,160,130,146,.87)
        self.assertEqual(len(merge_faces([full,other],(1280,720),full_count=2)),2)

    def test_partial_roi_outside_full_box_needs_matching_side_landmarks_to_deduplicate(self):
        full=face(100,100,200,260,.95)
        partial=face(93,130,120,220,.86)
        points=partial[4:14].reshape(5,2)
        points[[0,2,3]]=full[4:14].reshape(5,2)[[0,2,3]]
        self.assertEqual(len(merge_faces([full,partial],(800,600),full_count=1)),1)
        # A second real face in similar geometry has its own landmarks.
        other=face(93,130,120,220,.86)
        self.assertEqual(len(merge_faces([full,other],(800,600),full_count=1)),2)
        self.assertEqual(len(merge_faces([full,partial],(800,600),full_count=2)),2)

    def test_invalid_faces_and_outside_centers_rejected(self):
        invalid=face();invalid[4]=float('nan')
        self.assertEqual(merge_faces([invalid,face(w=0),face(x=700),face(score=.5)],(640,480)),[])

    def test_rounding_uses_independent_x_y_scale(self):
        detector=Mock();detector.detect.return_value=(None,np.array([face(100,100)]))
        scanner=FaceScanner(detector,max_edge=960)
        result=scanner._detect(np.zeros((721,1280,3),dtype=np.uint8))[0]
        self.assertAlmostEqual(float(result[0]),100*1280/960,places=4)
        self.assertAlmostEqual(float(result[1]),100*721/541,places=4)

    def test_full_frame_and_overlapping_tiles_cover_small_background_face(self):
        detector=Mock()
        # 第二个重叠分区中识别到了整帧漏掉的小脸。
        detector.detect.side_effect=[(None,None),(None,None),(None,np.array([face(100,80,30,36)]))]
        scanner=FaceScanner(detector)
        image=np.zeros((720,1280,3),dtype=np.uint8)
        result=scanner.detect(image,0)
        self.assertEqual(len(result),1)
        self.assertAlmostEqual(float(result[0][0]),320+100/2,places=4)
        self.assertAlmostEqual(float(result[0][1]),80/2,places=4)
        self.assertEqual(detector.detect.call_count,3)
        self.assertTrue(scanner.last_metrics['detail_scan'])
        self.assertEqual(scanner.last_metrics['frame_size'],[1280,720])

    def test_detailed_scan_has_bounded_frequency_and_keeps_current_full_frame(self):
        detector=Mock();detector.detect.return_value=(None,None)
        scanner=FaceScanner(detector,detail_interval=.25)
        image=np.zeros((480,640,3),dtype=np.uint8)
        scanner.detect(image,0)
        scanner.detect(image,.1)
        self.assertEqual(detector.detect.call_count,4)
        self.assertFalse(scanner.last_metrics['detail_scan'])
        scanner.detect(image,.25)
        self.assertEqual(detector.detect.call_count,7)

    def test_fresh_quantized_camera_timestamps_do_not_skip_product_background_scan(self):
        detector = Mock()
        detector.detect.return_value = (None,None)
        scanner = FaceScanner(detector,detail_interval=0)
        image = np.zeros((64,96,3),np.uint8)
        # GetTickCount64 samples around a100ms camera loop alternate below and
        # above100ms; a second .1s gate would skip half these new observations.
        for stamp in (0,.09375,.203125,.296875,.40625,.5):
            scanner.detect(image,stamp)
            self.assertTrue(scanner.last_metrics['detail_scan'])
        self.assertEqual(detector.detect.call_count,18)

    def test_low_confidence_candidate_requires_repeated_spatial_evidence(self):
        scanner=FaceScanner(Mock())
        self.assertEqual(scanner._confirm_candidates([face(score=.7)],0),[])
        self.assertEqual(len(scanner._confirm_candidates([face(104,102,score=.72)],.1)),1)

    def test_strong_then_weaker_fresh_observation_confirms_current_face(self):
        scanner=FaceScanner(Mock())
        first=face(100,100,40,50,.81)
        next_face=face(109,105,42,52,.68)
        scanner._confirm_candidates([first],0)
        result=scanner._confirm_candidates([next_face],.3)
        self.assertEqual(len(result),1)
        np.testing.assert_array_equal(result[0],next_face)
        self.assertEqual(scanner.current_unconfirmed_count,0)
        # No face in the new frame means no box can be replayed.
        self.assertEqual(scanner._confirm_candidates([],.4),[])
        self.assertEqual(scanner.previous_confirmed,[])

    def test_strong_history_cannot_confirm_stale_same_frame_or_other_face(self):
        for stamp,candidate in ((0,face(score=.68)),(.01,face(score=.68)),(-.1,face(score=.68)),(1.1,face(score=.68)),
                                (.3,face(400,100,score=.68)),(.3,face(w=30,h=30,score=.68))):
            with self.subTest(stamp=stamp,candidate=candidate[:4]):
                scanner=FaceScanner(Mock())
                scanner._confirm_candidates([face(score=.81)],0)
                self.assertEqual(scanner._confirm_candidates([candidate],stamp),[])
                self.assertEqual(scanner.current_unconfirmed_count,1)

    def test_strong_history_does_not_bypass_weak_landmark_validation(self):
        scanner=FaceScanner(Mock());scanner._confirm_candidates([face(score=.81)],0)
        bad=face(score=.68);bad[4]=-100
        self.assertEqual(scanner._confirm_candidates([bad],.3),[])
        self.assertEqual(scanner.weak_candidates,[])

    def test_one_previous_face_cannot_confirm_two_current_weak_faces(self):
        scanner=FaceScanner(Mock());scanner._confirm_candidates([face(score=.81)],0)
        first,second=face(60,100,score=.68),face(140,100,score=.69)
        result=scanner._confirm_candidates([first,second],.3)
        self.assertEqual(len(result),1)
        np.testing.assert_array_equal(result[0],first)
        self.assertEqual(scanner.current_unconfirmed_count,1)

    def test_accepted_weak_evidence_is_not_duplicated_in_strong_history(self):
        scanner=FaceScanner(Mock())
        scanner._confirm_candidates([face(score=.7)],0)
        self.assertEqual(len(scanner._confirm_candidates([face(score=.7)],.1)),1)
        self.assertEqual(scanner.previous_confirmed,[])
        result=scanner._confirm_candidates([face(60,100,score=.68),face(140,100,score=.69)],.2)
        self.assertEqual(len(result),1)

    def test_strong_and_weak_histories_for_same_face_are_consumed_together(self):
        scanner=FaceScanner(Mock())
        scanner._confirm_candidates([face(score=.7)],0)
        scanner._confirm_candidates([face(score=.9)],.1)
        result=scanner._confirm_candidates([face(60,100,score=.68),face(140,100,score=.69)],.2)
        self.assertEqual(len(result),1)

    def test_weak_focus_does_not_delay_six_background_tiles_on_accelerated_path(self):
        detector = Mock()
        detector.detect.return_value = (None,None)
        scanner = FaceScanner(detector,detail_interval=0,diagnostics=True,focus_tile_count=2)
        scanner.focus = {'face':face(35,25,12,15,.7),'at':0}
        image = np.zeros((100,160,3),np.uint8)
        scanned = []
        for stamp in (0,.09375,.203125):
            scanner.detect(image,stamp)
            labels = [item['scan'] for item in scanner.last_metrics['scans']]
            self.assertIn('focus',labels)
            self.assertIn('focus_contrast',labels)
            scanned.extend(label for label in labels if label.startswith('tile_'))
        self.assertEqual(scanned,['tile_'+str(i) for i in range(6)])
        self.assertEqual(detector.detect.call_count,15)

    def test_low_confidence_single_frame_or_different_location_is_not_a_person(self):
        scanner=FaceScanner(Mock())
        self.assertEqual(scanner._confirm_candidates([face(score=.7)],0),[])
        self.assertEqual(scanner._confirm_candidates([face(400,100,score=.7)],.1),[])
        self.assertEqual(scanner._confirm_candidates([face(score=.7)],1.1),[])

    def test_low_candidate_bad_landmarks_and_same_frame_repeat_cannot_confirm(self):
        scanner=FaceScanner(Mock());bad=face(score=.7);bad[4]=-100
        self.assertEqual(scanner._confirm_candidates([bad],0),[])
        self.assertEqual(scanner.weak_candidates,[])
        self.assertEqual(scanner._confirm_candidates([face(score=.7)],0),[])
        self.assertEqual(scanner._confirm_candidates([face(score=.7)],0),[])

    def test_all_six_tiles_rotate_with_two_times_magnification(self):
        detector=Mock();detector.detect.return_value=(None,None)
        scanner=FaceScanner(detector,diagnostics=True)
        image=np.zeros((720,1280,3),dtype=np.uint8)
        labels=[]
        for now in (0,.2,.4):
            scanner.detect(image,now)
            labels.extend(scan['scan'] for scan in scanner.last_metrics['scans'] if scan['scan'].startswith('tile_'))
            self.assertEqual(scanner.last_metrics['scans'][1]['input_size'],[1280,864])
        self.assertEqual(labels,['tile_0','tile_1','tile_2','tile_3','tile_4','tile_5'])

    def test_internal_crop_border_truncation_does_not_create_a_second_half_face(self):
        detector=Mock()
        detector.detect.return_value=(None,np.array([face(0,100),face(1200,100),face(100,800),face(100,100)]))
        scanner=FaceScanner(detector,diagnostics=True)
        result=scanner._detect(np.zeros((432,640,3),dtype=np.uint8),(320,0),True,
                               max_edge=1280,frame_size=(1280,720),label='tile_1')
        self.assertEqual(len(result),1)
        self.assertEqual(scanner.scan_metrics[0]['border_rejected'],3)
        self.assertAlmostEqual(float(result[0][0]),370)

    def test_small_weak_background_face_is_refocused_and_rechecked_next_frame(self):
        detector=Mock();owner=face(200*.75,160*.75,300*.75,360*.75)
        weak=face(760,200,120,160,.72)
        strong=face(165,220,150,200,.91)
        detector.detect.side_effect=[(None,np.array([owner])),(None,None),(None,np.array([weak])),
                                     (None,np.array([owner])),(None,np.array([strong])),
                                     (None,np.array([strong])),(None,None)]
        scanner=FaceScanner(detector,diagnostics=True)
        image=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertEqual(len(scanner.detect(image,0)),1)
        result=scanner.detect(image,.2)
        self.assertEqual(len(result),2)
        background=min(result,key=lambda item:float(item[2]*item[3]))
        np.testing.assert_allclose(background[:4],[700,100,60,80],atol=.01)
        self.assertIn('focus_contrast',[scan['scan'] for scan in scanner.last_metrics['scans']])

    def test_bystander_risk_does_not_disappear_between_detail_scans(self):
        hold=BystanderHold()
        self.assertFalse(hold.update(0,False))
        self.assertTrue(hold.update(.1,True))
        self.assertTrue(hold.update(.35,False))
        self.assertFalse(hold.update(.61,False))
        self.assertFalse(hold.update(-1,False))


if __name__=='__main__':unittest.main()
