import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'视界盾开发'))
from camera_worker import identity_metadata,identity_score_for_quality
from face_detection import FaceScanner
from identity_test import extract
from owner_presence import frontal_face


class CameraMetadataTests(unittest.TestCase):
    def test_actual_scanner_and_quality_diagnostics_serialize_as_native_json(self):
        face=np.array([100,100,100,100,130,130,170,130,150,150,130,175,170,175,.7],dtype=np.float32)
        detector=Mock();detector.detect.return_value=(None,np.array([face]))
        scanner=FaceScanner(detector)
        image=np.full((480,640,3),128,dtype=np.uint8)
        scanner.detect(image,0)
        scanner.detect(image,.1)
        recognizer=Mock();recognizer.alignCrop.return_value=np.full((112,112,3),128,dtype=np.uint8)
        recognizer.feature.return_value=np.ones((1,128),dtype=np.float32)
        details={}
        with patch('identity_test.cv2.Laplacian') as sharpness:
            sharpness.return_value.var.return_value=np.float64(100)
            extract(image,face,recognizer,details)
        metadata=identity_metadata(details,np.float32(.7),frontal_face(face),np.bool_(True))
        payload={**scanner.last_metrics,'identity_diagnostics':[metadata]}
        decoded=json.loads(json.dumps(payload))
        self.assertIs(type(payload['weak_candidates']),int)
        self.assertIs(type(metadata['frontal']),bool)
        self.assertIs(type(metadata['reliable']),bool)
        self.assertIs(type(metadata['owner_score']),float)
        self.assertEqual(decoded['identity_diagnostics'][0]['quality_reason'],'accepted')

    def test_moderate_blur_requires_stronger_match_and_severe_blur_never_verifies(self):
        self.assertIsNone(identity_score_for_quality(.59,40))
        self.assertEqual(identity_score_for_quality(.60,40),.60)
        self.assertEqual(identity_score_for_quality(.45,70),.45)
        self.assertIsNone(identity_score_for_quality(.99,19))
        self.assertIsNone(identity_score_for_quality(float('nan'),80))
        self.assertIsNone(identity_score_for_quality(.99,float('nan')))

    def test_quality_policy_boundaries_use_original_precision(self):
        self.assertIsNone(identity_score_for_quality(.59,59.999))
        self.assertEqual(identity_score_for_quality(.59,60.0),.59)
        self.assertEqual(identity_score_for_quality(.60,20.0),.60)
        self.assertIsNone(identity_score_for_quality(.99,19.999))

    def test_extract_policy_value_is_not_the_rounded_display_value(self):
        recognizer=Mock();image=np.full((112,112,3),128,dtype=np.uint8)
        recognizer.alignCrop.return_value=image;recognizer.feature.return_value=np.ones((1,128),dtype=np.float32)
        details={}
        with patch('identity_test.cv2.Laplacian') as sharpness:
            sharpness.return_value.var.return_value=59.999
            self.assertIsNotNone(extract(image,(0,0,100,100),recognizer,details,min_sharpness=20))
        self.assertEqual(details['sharpness'],59.999)
        self.assertIsNone(identity_score_for_quality(.59,details['sharpness']))
        displayed=identity_metadata(details,.59,True,True)
        self.assertEqual(displayed['sharpness'],60.)
        self.assertEqual(displayed['quality_level'],'moderate_blur')


if __name__=='__main__':unittest.main()
