import unittest
from native_text import intersect
from hybrid_text_test import report


class NativeTextTests(unittest.TestCase):
    def test_clip_and_invisible_area(self):
        self.assertEqual(intersect((-20,10,40,50),(0,0,100,100)),(0,10,40,50))
        self.assertIsNone(intersect((0,0,10,10),(20,20,30,30)))

    def test_same_rules_for_direct_text(self):
        lines=[{'text':'手机号：13800138000','confidence':1.0,'source':'uia_text',
                'polygon':[[10,10],[300,10],[300,40],[10,40]]}]
        text=report(lines,True)
        self.assertIn('手机号',text)
        self.assertIn('uia_text',text)


if __name__=='__main__':
    unittest.main()
