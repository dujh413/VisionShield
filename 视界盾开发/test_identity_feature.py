import unittest
from unittest.mock import Mock,patch
import numpy as np
from identity_test import extract


class FeatureTests(unittest.TestCase):
    def test_invalid_embedding_is_rejected_before_template_storage(self):
        recognizer=Mock()
        image=np.full((112,112,3),128,dtype=np.uint8)
        recognizer.alignCrop.return_value=image
        for value in (0,float('nan'),float('inf')):
            recognizer.feature.return_value=np.full((1,128),value,dtype=np.float32)
            recognizer.feature.reset_mock()
            with patch('identity_test.cv2.Laplacian') as sharpness:
                sharpness.return_value.var.return_value=100
                self.assertIsNone(extract(image,(0,0,100,100),recognizer))
            recognizer.feature.assert_called_once()

    def test_valid_embedding_is_normalized(self):
        recognizer=Mock()
        image=np.full((112,112,3),128,dtype=np.uint8)
        recognizer.alignCrop.return_value=image
        recognizer.feature.return_value=np.ones((1,128),dtype=np.float32)
        with patch('identity_test.cv2.Laplacian') as sharpness:
            sharpness.return_value.var.return_value=100
            feature=extract(image,(0,0,100,100),recognizer)
        self.assertAlmostEqual(float(np.linalg.norm(feature)),1,places=6)


if __name__=='__main__':unittest.main()
