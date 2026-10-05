import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import camera_acceptance


class FakeClock:
    def __init__(self):self.value=0
    def now(self):return self.value
    def sleep(self,seconds):self.value+=seconds


class FakeWorker:
    def __init__(self,clock,ready_after):
        self.clock,self.ready_after=clock,ready_after
        self.error=None;self.last=None;self.closed=False;self.sequence=0
    def poll(self):
        if self.clock.value >= self.ready_after:
            self.sequence+=1
            self.last={'sequence':self.sequence,'enrolled':True,'faces_count':1,
                       'stranger_detected':False,'owner_verified':True,'protect_request':False,
                       'frame_size':[1280,720],'preview':b'RAM-only-JPEG'}
    def close(self):self.closed=True


class CameraAcceptanceTests(unittest.TestCase):
    def run_case(self,ready_after,extra_args=()):
        clock=FakeClock();worker=FakeWorker(clock,ready_after)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'report.json'
            with patch('camera_acceptance.CameraWorker',return_value=worker),\
                 patch('camera_acceptance.time.monotonic',side_effect=clock.now),\
                 patch('camera_acceptance.time.sleep',side_effect=clock.sleep),\
                 patch('sys.argv',['camera_acceptance.py','--seconds','5','--output',str(output),*extra_args]),\
                 patch('builtins.print') as printed:
                result=camera_acceptance.main()
            report=json.loads(output.read_text(encoding='utf-8'))
            persisted=[json.loads(line) for line in output.with_suffix('.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(persisted,report['samples'])
            return result,report,printed,worker

    def test_cold_start_does_not_consume_the_human_test_period(self):
        result,report,printed,worker=self.run_case(8.5)
        self.assertEqual(result,0)
        self.assertGreaterEqual(report['startup_seconds'],8.5)
        self.assertGreaterEqual(report['duration_seconds'],5)
        self.assertEqual(report['samples'][0]['elapsed'],0)
        self.assertEqual(json.loads(printed.call_args_list[0].args[0])['event'],'camera_ready')
        self.assertTrue(printed.call_args_list[0].kwargs['flush'])
        self.assertTrue(worker.closed)

    def test_guided_prompts_are_recorded_but_no_image_or_claimed_human_action_is_saved(self):
        app,window=Mock(),Mock();window.canceled=False
        with patch('camera_acceptance.preview_window',return_value=(app,window)):
            result,report,_,worker=self.run_case(0,('--guided','--preview'))
        self.assertEqual(result,0)
        self.assertEqual({i['planned_phase'] for i in report['samples']},
                         {'owner_only','bystander_present','recovery'})
        self.assertFalse(report['human_actions_confirmed'])
        self.assertTrue(report['preview_in_memory'])
        self.assertTrue(window.show_sample.called)
        self.assertTrue(worker.closed)
        self.assertNotIn('preview',report['samples'][0])

    def test_camera_without_first_frame_has_a_separate_bounded_timeout(self):
        result,report,_,worker=self.run_case(100)
        self.assertEqual(result,1)
        self.assertEqual(report['error'],'Camera startup timed out')
        self.assertEqual(report['duration_seconds'],0)
        self.assertEqual(report['samples'],[])
        self.assertTrue(worker.closed)

    def test_real_qt_preview_displays_only_a_ram_fixture_and_clears_on_close(self):
        from PySide6.QtCore import QBuffer,QIODevice
        from PySide6.QtGui import QImage
        app,window=camera_acceptance.preview_window()
        try:
            image=QImage(64,64,QImage.Format_RGB32);image.fill(0xff999999)
            buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'JPG')
            item={'preview':bytes(buffer.data()),'faces_count':2,'owner_verified':False,'stranger_detected':True}
            for elapsed,text in ((0,'仅机主'),(8,'另一人站在身后'),(24,'另一人离开画面')):
                window.show_sample(item,elapsed,30,True);app.processEvents()
                self.assertIn(text,window.instructions.text())
                self.assertFalse(window.image.pixmap().isNull())
        finally:window.close();app.processEvents()
        self.assertTrue(window.canceled)
        self.assertTrue(window.image.pixmap().isNull())

    def test_bystander_warning_does_not_tell_the_owner_to_register_the_other_person(self):
        text=camera_acceptance.quality_hint({'enrolled':True,'faces_count':2,'stranger_detected':True,
                    'identity_diagnostics':[{'owner_score':.7,'frontal':True},{'owner_score':.1,'frontal':True}]})
        self.assertIn('旁人',text)
        self.assertNotIn('模板未匹配',text)


if __name__=='__main__':unittest.main()
