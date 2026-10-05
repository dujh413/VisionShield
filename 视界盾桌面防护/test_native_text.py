import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from native_text import intersect,read_window,range_lines
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

    def test_partial_native_read_cannot_report_complete_coverage(self):
        def partial(handle,deadline,status):
            status['truncated']=True
            yield '虚构文字',(0,0,100,20)
        with patch('native_text.native_edit_lines',side_effect=partial):
            result=read_window(0,{'left':0,'top':0,'width':320,'height':240})
        self.assertTrue(result['truncated'])

    def test_all_disjoint_visible_ranges_are_read(self):
        visible=[]
        for text in ('虚构第一列','虚构第二列'):
            region,cursor,part=Mock(),Mock(),Mock()
            region.Clone.return_value=cursor
            cursor.Clone.return_value=part
            cursor.CompareEndpoints.side_effect=[-1,0]
            cursor.Move.return_value=1
            part.CompareEndpoints.return_value=0
            part.GetText.return_value=text
            part.GetBoundingRectangles.return_value=[SimpleNamespace(left=0,top=0,right=100,bottom=20)]
            visible.append(region)
        pattern=Mock();pattern.GetVisibleRanges.return_value=visible
        result=list(range_lines(pattern,Mock(),float('inf')))
        self.assertEqual([text for text,rect in result],['虚构第一列','虚构第二列'])


if __name__=='__main__':
    unittest.main()
