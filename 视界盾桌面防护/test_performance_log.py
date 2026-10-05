import csv
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from performance_log import PerformanceLog


class PerformanceLogTests(unittest.TestCase):
    def test_render_backend_and_exact_committed_radius_survive_both_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            log=PerformanceLog(folder)
            item={'effect':'blur','radius':10**100,'blur_backend':'opencl-gpu',
                  'blur_device':'Synthetic GPU','blur_gpu_ms':2.75,
                  'blur_fallback':'RadiusUnsupported','text':'PRIVATE_FIXTURE',
                  'image':np.zeros((2,2,3),np.uint8)}
            log.event(1,0,item)
            log.heartbeat(1,0,item)
            log.close()
            raw=(Path(folder)/'events.jsonl').read_text(encoding='utf-8')
            event=json.loads(raw)
            for key in ('effect','radius','blur_backend','blur_device','blur_gpu_ms','blur_fallback'):
                self.assertEqual(event[key],item[key])
            self.assertNotIn('PRIVATE_FIXTURE',raw)
            self.assertNotIn('image',event)
            with (Path(folder)/'heartbeat.csv').open(encoding='utf-8-sig',newline='') as source:
                row=next(csv.DictReader(source))
            self.assertEqual(int(row['radius']),10**100)
            self.assertEqual(row['effect'],'blur')
            self.assertEqual(row['blur_backend'],'opencl-gpu')
            self.assertEqual(row['blur_device'],'Synthetic GPU')
            self.assertEqual(float(row['blur_gpu_ms']),2.75)
            self.assertEqual(row['blur_fallback'],'RadiusUnsupported')

    def test_invalid_render_metadata_stays_bounded_and_serializable(self):
        cases=[
            {'effect':{'text':'PRIVATE_FIXTURE'},'radius':True,
             'blur_backend':['opencl-gpu'],'blur_device':np.zeros((2,2,3)),
             'blur_gpu_ms':float('nan'),'blur_fallback':'PRIVATE_FIXTURE traceback message'},
            {'effect':'PRIVATE_FIXTURE','radius':10**128,'blur_backend':'PRIVATE_FIXTURE',
             'blur_device':'PRIVATE_FIXTURE'*100,'blur_gpu_ms':float('inf'),
             'blur_fallback':'Error'+'x'*128},
            {'radius':-1,'blur_device':'Synthetic GPU\nPRIVATE_FIXTURE','blur_gpu_ms':-1},
            {'blur_gpu_ms':10**5000},
        ]
        with tempfile.TemporaryDirectory() as folder:
            log=PerformanceLog(folder)
            for index,item in enumerate(cases):
                log.event(index,0,item)
                log.heartbeat(index,0,item)
            log.close()
            raw=(Path(folder)/'events.jsonl').read_text(encoding='utf-8')
            events=[json.loads(line) for line in raw.splitlines()]
            self.assertEqual(len(events),len(cases))
            self.assertNotIn('PRIVATE_FIXTURE',raw)
            for event,item in zip(events,cases):
                for key in item:
                    self.assertIsNone(event[key])
            with (Path(folder)/'heartbeat.csv').open(encoding='utf-8-sig',newline='') as source:
                rows=list(csv.DictReader(source))
            self.assertEqual(len(rows),len(cases))
            for row,item in zip(rows,cases):
                for key in item:
                    self.assertEqual(row[key],'')

    def test_no_pixels_or_recognized_text_and_heartbeat_is_throttled(self):
        with tempfile.TemporaryDirectory() as folder:
            log=PerformanceLog(folder)
            item={'frame_id':1,'image':np.zeros((2,2,3)), 'text':'PRIVATE_FIXTURE',
                  'lines':[{'text':'PRIVATE_FIXTURE'}],'stage_ms':{'detection_ms':5}}
            log.event(1,0,item)
            log.heartbeat(1,0,item);log.heartbeat(1.1,0,item);log.heartbeat(2,0,item)
            log.close()
            text=(Path(folder)/'events.jsonl').read_text(encoding='utf-8')
            self.assertNotIn('PRIVATE_FIXTURE',text)
            self.assertNotIn('image',text)
            self.assertEqual(json.loads(text)['stage_ms'],{'detection_ms':5})
            with (Path(folder)/'heartbeat.csv').open(encoding='utf-8-sig',newline='') as source:
                self.assertEqual(len(list(csv.DictReader(source))),2)


if __name__=='__main__':unittest.main()
