import unittest
from unittest.mock import Mock
from ocr_worker import recognize
from sensitive_rules import detect


class OCRSafetyTests(unittest.TestCase):
    def test_unrecognized_detection_is_protected_even_with_other_good_text(self):
        first=[[0,0],[100,0],[100,20],[0,20]]
        missing=[[0,40],[100,40],[100,60],[0,60]]
        ocr=Mock()
        ocr.predict.return_value=[{'rec_texts':['普通文字'],'rec_scores':[.99],
                                  'rec_polys':[first],'dt_polys':[first,missing]}]
        lines=recognize(ocr,None)
        self.assertEqual(len(lines),2)
        hits=detect(lines)
        self.assertEqual(hits[0]['polygon'],missing)
        self.assertEqual(hits[0]['categories'],['无法确定'])


if __name__=='__main__':unittest.main()
