import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from onnx_yunet import OnnxYuNet
from prepare_face_model import prepare_model


def predictions():
    result = []
    for prefix in ('cls','obj','bbox','kps'):
        for stride in (8,16,32):
            count = (32//stride)**2
            channels = {'cls':1,'obj':1,'bbox':4,'kps':10}[prefix]
            result.append(np.zeros((1,count,channels),np.float32))
    return result


class DecodeTests(unittest.TestCase):
    def detector(self, values):
        detector = OnnxYuNet.__new__(OnnxYuNet)
        detector.input_name = 'input'
        detector.size = (31,29)
        detector.names = [prefix+'_'+str(stride) for prefix in ('cls','obj','bbox','kps') for stride in (8,16,32)]
        detector.session = Mock()
        detector.session.run.return_value = values
        return detector

    def test_padding_bgr_and_five_points_match_opencv_convention(self):
        values = predictions()
        values[0][0,5,0] = .8
        values[3][0,5,0] = .9
        values[6][0,5] = [.5,-.25,np.log(2),np.log(3)]
        values[9][0,5] = np.arange(10)/10
        detector = self.detector(values)
        image = np.full((29,31,3),[11,22,33],np.uint8)
        original = image.copy()
        status,faces = detector.detect(image)
        self.assertEqual(status, 1)
        self.assertEqual(faces.shape, (1,15))
        np.testing.assert_allclose(faces[0,:4], [4,-6,16,24], atol=1e-5)
        np.testing.assert_allclose(faces[0,4:14], (1+np.arange(10)/10)*8, atol=1e-5)
        self.assertAlmostEqual(float(faces[0,14]), np.sqrt(.8*.9), places=6)
        blob = detector.session.run.call_args.args[1]['input']
        self.assertEqual(blob.shape, (1,3,32,32))
        np.testing.assert_array_equal(blob[0,:,0,0], [11,22,33])
        self.assertFalse(blob[0,:,-1,:].any())
        self.assertFalse(blob[0,:,:,-1].any())
        np.testing.assert_array_equal(image, original)

    def test_no_detections_preserve_none_contract(self):
        detector = self.detector(predictions())
        status,faces = detector.detect(np.zeros((29,31,3),np.uint8))
        self.assertEqual(status,1)
        self.assertIsNone(faces)

    def test_multiple_stride_duplicates_use_same_integer_box_nms(self):
        values = predictions()
        # Same box at two strides, with different confidence; keep the best.
        for index,cell,score in ((0,5,.9),(1,0,.8)):
            stride = (8,16,32)[index]
            cols = 32//stride
            values[index][0,cell,0] = score
            values[index+3][0,cell,0] = score
            values[index+6][0,cell] = [16/stride-cell%cols,16/stride-cell//cols,
                                     np.log(16/stride),np.log(16/stride)]
        detector = self.detector(values)
        _,faces = detector.detect(np.zeros((29,31,3),np.uint8))
        self.assertEqual(len(faces),1)
        np.testing.assert_allclose(faces[0,:4],[8,8,16,16],atol=1e-5)
        self.assertAlmostEqual(float(faces[0,14]),.9,places=6)

    def test_invalid_prediction_cannot_produce_safe_face(self):
        values = predictions()
        values[0][0,5,0] = values[3][0,5,0] = .8
        values[6][0,5,0] = np.nan
        detector = self.detector(values)
        with self.assertRaises(ValueError):
            detector.detect(np.zeros((29,31,3),np.uint8))

    def test_nms_rejecting_threshold_equality_preserves_no_face_contract(self):
        values = predictions()
        for cell in (0,15):
            values[0][0,cell,0] = values[3][0,cell,0] = .6
        detector = self.detector(values)
        _,faces = detector.detect(np.zeros((29,31,3),np.uint8))
        self.assertIsNone(faces)

    def test_input_size_must_match_each_request(self):
        detector = self.detector(predictions())
        with self.assertRaises(ValueError):
            detector.detect(np.zeros((30,31,3),np.uint8))
        detector.session.run.assert_not_called()

    def test_nonfinite_scores_cannot_be_silently_treated_as_no_face(self):
        for output_index in (0,3):
            for invalid in (np.nan,np.inf,-np.inf):
                with self.subTest(output_index=output_index,invalid=invalid):
                    values = predictions()
                    values[output_index][0,0,0] = invalid
                    detector = self.detector(values)
                    with self.assertRaises(ValueError):
                        detector.detect(np.zeros((29,31,3),np.uint8))


class ModelBoundaryTests(unittest.TestCase):
    def test_optional_engine_failure_uses_existing_detector_without_loading_template(self):
        from identity_test import load_models
        class SessionFailure(Exception):
            pass
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'models').mkdir()
            (root/'models/face_detection_yunet_2023mar.onnx').write_bytes(b'detector fixture')
            (root/'models/face_recognition_sface_2021dec.onnx').write_bytes(b'recognizer fixture')
            old,recognizer = Mock(),Mock()
            with patch('onnx_yunet.OnnxYuNet',side_effect=SessionFailure('fixture')), \
                    patch('identity_test.cv2.FaceDetectorYN.create',return_value=old) as create, \
                    patch('identity_test.cv2.FaceRecognizerSF.create',return_value=recognizer), \
                    patch('identity_test.np.load') as template:
                actual = load_models(root)
            self.assertEqual(actual,(old,recognizer))
            create.assert_called_once()
            template.assert_not_called()

    def test_bad_model_rejected_before_onnx_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.onnx'
            path.write_bytes(b'invalid fictional model')
            with patch('onnxruntime.InferenceSession') as session:
                with self.assertRaises(ValueError):
                    OnnxYuNet(path)
                session.assert_not_called()

    def test_verified_model_selects_cpu_only_and_two_threads(self):
        data = b'fictional model session fixture'
        digest = hashlib.sha256(data).hexdigest()
        session = Mock()
        session.get_inputs.return_value = [SimpleNamespace(name='input',shape=[1,3,'height','width'])]
        session.get_outputs.return_value = [SimpleNamespace(name=prefix+'_'+str(stride))
            for prefix in ('cls','obj','bbox','kps') for stride in (8,16,32)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.onnx'
            path.write_bytes(data)
            with patch('onnx_yunet.MODEL_SHA256',digest), patch('onnxruntime.InferenceSession',return_value=session) as factory:
                detector = OnnxYuNet(path)
            self.assertEqual(detector.backend,'onnxruntime-cpu')
            self.assertEqual(factory.call_args.kwargs['providers'],['CPUExecutionProvider'])
            options = factory.call_args.args[1]
            self.assertEqual(options.intra_op_num_threads,2)
            self.assertEqual(options.inter_op_num_threads,1)
            self.assertFalse(options.enable_cpu_mem_arena)
            self.assertFalse(options.enable_mem_pattern)
            self.assertEqual(options.get_session_config_entry('session.intra_op.allow_spinning'),'0')

    def test_wrong_download_keeps_existing_file_and_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            from prepare_face_model import MODEL_NAME
            path = Path(folder)/MODEL_NAME
            path.write_bytes(b'old fixture')
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b'wrong download'
            with patch('prepare_face_model.urllib.request.urlopen',return_value=response):
                with self.assertRaises(ValueError):
                    prepare_model(folder)
            self.assertEqual(path.read_bytes(),b'old fixture')
            self.assertEqual(list(Path(folder).iterdir()),[path])


if __name__ == '__main__':
    unittest.main()
