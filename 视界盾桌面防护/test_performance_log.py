import csv
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from performance_log import PerformanceLog


class PerformanceLogTests(unittest.TestCase):
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
