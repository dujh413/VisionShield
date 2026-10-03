import json
from pathlib import Path
import tempfile
import unittest
from diagnostics import Diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_only_metadata_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            diag = Diagnostics(directory)
            diag.event(2.,0.,{'event':'ocr_result','frame_id':1,'accepted':False,
                             'image':'DO_NOT_SAVE_IMAGE','lines':'DO_NOT_SAVE_TEXT'})
            diag.heartbeat(2.,0.,{'frame_id':1,'text':'DO_NOT_SAVE_TEXT'})
            diag.heartbeat(2.1,0.,{'frame_id':2})
            diag.close()
            event = json.loads((Path(directory)/'ocr_events.jsonl').read_text())
            self.assertNotIn('image',event)
            self.assertNotIn('lines',event)
            self.assertEqual(len((Path(directory)/'heartbeat.csv').read_text(encoding='utf-8-sig').splitlines()),2)


if __name__ == '__main__':
    unittest.main()
