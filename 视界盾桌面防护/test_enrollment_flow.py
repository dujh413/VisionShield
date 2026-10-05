import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'视界盾开发'))
from owner_enrollment import enroll_main


class EnrollmentFlowTests(unittest.TestCase):
    def run_flow(self,switch_person):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            target=root/'private/owner_templates.npz'
            original=None
            if switch_person:
                target.parent.mkdir()
                np.savez_compressed(target,features=np.ones((1,128),dtype=np.float32))
                original=target.read_bytes()
            stop,enroll=threading.Event(),threading.Event();enroll.set()
            output=Mock();camera=Mock();frame_count=[0];clock=[0.0]
            image=np.zeros((480,640,3),dtype=np.uint8)
            face=np.array([100,100,100,100]+[0]*11,dtype=np.float32)
            detector=Mock();detector.detect.return_value=(None,np.array([face]))
            def read():
                frame_count[0]+=1
                if frame_count[0]>=32:stop.set()
                return True,image.copy()
            def feature(*args):
                value=np.zeros(128,dtype=np.float32)
                value[0]=-1 if switch_person and frame_count[0]>6 else 1
                return value
            def now():
                clock[0]+=.12
                return clock[0]
            camera.read.side_effect=read
            with patch('camera_test.open_camera',return_value=camera),\
                 patch('identity_test.load_models',return_value=(detector,Mock())),\
                 patch('identity_test.extract',side_effect=feature),\
                 patch('owner_enrollment.time.monotonic',side_effect=now):
                enroll_main(root,stop,enroll,output)
            saved=target
            result=bool(output.put.call_args and output.put.call_args.args[0].get('saved'))
            if result:
                with np.load(saved) as data:self.assertEqual(data['features'].shape,(12,128))
            elif original is not None:
                self.assertEqual(target.read_bytes(),original)
            camera.release.assert_called_once()
            return result,enroll.is_set()

    def test_same_virtual_person_completes_registration(self):
        saved,_=self.run_flow(False)
        self.assertTrue(saved)

    def test_person_swap_requires_another_explicit_registration_click(self):
        saved,requested=self.run_flow(True)
        self.assertFalse(saved)
        self.assertFalse(requested)


if __name__=='__main__':unittest.main()
