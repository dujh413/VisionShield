import unittest

import numpy as np

from incremental_regions import changed_regions, contains, difference_mask, intersects, merge_boxes


def line(x,y,width=100,height=20):
    return {'text':'synthetic','confidence':1.,
            'polygon':[[x,y],[x+width,y],[x+width,y+height],[x,y+height]]}


class RegionTests(unittest.TestCase):
    def test_fast_difference_equals_all_channel_comparison(self):
        rng = np.random.default_rng(42)
        previous = rng.integers(0,256,(60,80,3),dtype=np.uint8)
        current = previous.copy()
        current[12,13,0] ^= 1
        current[20,30,1] ^= 1
        current[45,60,2] ^= 1
        for first,second in ((previous,current),(previous[::-1,::2],current[::-1,::2])):
            np.testing.assert_array_equal(difference_mask(first,second),
                                          np.any(first!=second,axis=2))

    def test_no_change_and_subtle_one_channel_change(self):
        previous = np.zeros((300,500,3),dtype=np.uint8)
        self.assertEqual(changed_regions(previous,previous.copy(),[]),[])
        current = previous.copy()
        current[140,220,2] = 1
        boxes = changed_regions(previous,current,[])
        self.assertEqual(boxes,[(156,76,285,205)])

    def test_regions_are_clipped_at_image_edges(self):
        previous = np.zeros((130,270,3),dtype=np.uint8)
        current = previous.copy()
        current[0,0] = 1
        current[-1,-1] = 1
        boxes = changed_regions(previous,current,[])
        self.assertEqual(boxes,[(0,0,65,65),(205,65,270,130)])
        for x1,y1,x2,y2 in boxes:
            self.assertTrue(0<=x1<x2<=270 and 0<=y1<y2<=130)

    def test_complete_intersecting_long_line_and_context_included(self):
        previous = np.zeros((600,1200,3),dtype=np.uint8)
        current = previous.copy()
        current[210,550,0] = 1
        lines = [line(100,200,800),line(105,170,100)]
        boxes = changed_regions(previous,current,lines)
        self.assertEqual(len(boxes),1)
        self.assertTrue(contains(boxes[0],(100,200,900,220)))
        self.assertTrue(contains(boxes[0],(105,170,205,190)))
        self.assertLess(boxes[0][2]-boxes[0][0],1000)

    def test_context_padding_does_not_cascade_through_document(self):
        previous = np.zeros((1000,1000,3),dtype=np.uint8)
        current = previous.copy()
        lines = [line(100,y,500) for y in range(100,901,30)]
        current[110,500,0] = 1
        boxes = changed_regions(previous,current,lines)
        self.assertEqual(len(boxes),1)
        self.assertLess(boxes[0][3],250)
        self.assertFalse(intersects(boxes[0],(100,900,600,920)))

    def test_four_pixel_row_gaps_do_not_join_complete_column(self):
        previous = np.zeros((1600,2560,3),dtype=np.uint8)
        current = previous.copy()
        lines = [line(x,20+row*22,900,18) for x in (50,1300) for row in range(70)]
        current[911,500,0] = 1
        current[1450,2450,2] = 1
        boxes = changed_regions(previous,current,lines)
        self.assertEqual(len(boxes),2)
        self.assertLess(sum((x2-x1)*(y2-y1) for x1,y1,x2,y2 in boxes)/(1600*2560),.1)
        self.assertLess(boxes[0][3]-boxes[0][1],250)
        for old in lines:
            x,y = old['polygon'][0]
            rectangle = (x,y,x+900,y+18)
            for box in boxes:
                if intersects(box,rectangle):
                    self.assertTrue(contains(box,rectangle), 'crop must contain each intersected glyph row')

    def test_shared_crop_edge_does_not_intersect_text(self):
        self.assertFalse(intersects((0,0,100,100),(0,100,100,120)))
        self.assertFalse(intersects((0,0,100,100),(100,0,120,100)))
        self.assertTrue(intersects((0,0,100,100),(99,99,120,120)))
        self.assertEqual(merge_boxes([(0,0,100,100),(0,100,100,120)]),[(0,0,100,120)])

    def test_merging_expanded_rectangles_reaches_fixed_point(self):
        merged = merge_boxes([(0,0,4,4),(8,0,12,4),(3,3,9,7)])
        self.assertEqual(merged,[(0,0,12,7)])

    def test_busy_frame_bounds_geometry_work_and_falls_back(self):
        previous = np.zeros((1000,1000,3),dtype=np.uint8)
        current = previous.copy()
        current[::64,::64,0] = 1
        self.assertEqual(changed_regions(previous,current,[],max_tiles=4),[(0,0,1000,1000)])

    def test_resolution_change_and_invalid_geometry(self):
        original = np.zeros((100,100,3),dtype=np.uint8)
        current = np.zeros((80,120,3),dtype=np.uint8)
        self.assertEqual(changed_regions(original,current,[]),[(0,0,120,80)])
        current = original.copy()
        current[50,50] = 1
        bad = line(0,0)
        bad['polygon'][0][1] = float('inf')
        with self.assertRaises(ValueError):
            changed_regions(original,current,[bad])


if __name__=='__main__':
    unittest.main()
