import unittest
import numpy as np
from content_index import ContentIndex


class ContentIndexTests(unittest.TestCase):
    def setUp(self):
        self.image=np.zeros((192,320,3),dtype=np.uint8)
        self.line={'text':'13800138000','confidence':.99,'polygon':[[10,10],[180,10],[180,30],[10,30]]}
        self.index=ContentIndex()
        self.index.update(self.image)
        self.index.accept(self.image,[self.line])

    def test_animation_elsewhere_keeps_sensitive_line(self):
        latest=self.image.copy();latest[150:160,280:290]=255
        self.index.update(latest)
        self.assertEqual(len(self.index.hits),1)
        self.assertTrue(self.index.accept(self.image,[self.line]))
        self.assertEqual(len(self.index.hits),1)
        self.assertTrue(self.index.unknown[2,4])
        self.assertFalse(self.index.unknown[0,0])

    def test_one_digit_change_temporarily_covers_entire_old_line(self):
        latest=self.image.copy();latest[15,20]=255
        self.index.update(latest)
        self.assertFalse(self.index.hits)
        self.assertTrue(self.index.unknown[0,2])
        self.index.accept(self.image,[self.line])
        self.assertFalse(self.index.hits)
        self.assertTrue(self.index.unknown[0,2])

    def test_fresh_ocr_resolves_unknown_and_updates_hit(self):
        latest=self.image.copy();latest[15,20]=255
        self.index.update(latest)
        self.index.accept(latest,[self.line])
        self.assertEqual(len(self.index.hits),1)
        self.assertFalse(self.index.unknown.any())

    def test_initial_pending_tiles_merge_to_single_screen_region(self):
        index=ContentIndex();index.update(self.image)
        self.assertEqual(index.pending_rectangles(),[(0,0,320,192)])

    def test_size_change_rejects_previous_coordinates(self):
        self.index.update(np.zeros((96,160,3),dtype=np.uint8))
        self.assertFalse(self.index.hits)
        self.assertFalse(self.index.accept(self.image,[self.line]))
        self.assertTrue(self.index.unknown.all())

    def test_old_empty_result_cannot_erase_new_sensitive_line(self):
        latest=self.image.copy();latest[15,20]=255
        self.index.update(latest)
        self.index.accept(latest,[self.line])
        self.index.accept(self.image,[])
        self.assertEqual(len(self.index.hits),1)

    def test_fresh_empty_result_removes_disappeared_sensitive_line(self):
        self.index.accept(self.image,[])
        self.assertFalse(self.index.hits)

    def test_changed_label_keeps_unchanged_neighbor_value_pending(self):
        label={'text':'普通说明','confidence':.99,'polygon':[[10,10],[90,10],[90,30],[10,30]]}
        value={'text':'246810','confidence':.99,'polygon':[[10,68],[90,68],[90,88],[10,88]]}
        self.index.accept(self.image,[label,value])
        latest=self.image.copy();latest[15,20]=255
        self.index.update(latest)
        self.assertTrue(self.index.unknown[1,0])
        # 旧画面中的标签已过期，其普通数字判断也不能清除邻近值的保护。
        self.index.accept(self.image,[label,value])
        self.assertTrue(self.index.unknown[1,0])

    def test_large_label_change_invalidates_smaller_nearby_value(self):
        image=np.zeros((512,320,3),dtype=np.uint8)
        label={'text':'普通说明','confidence':.99,'polygon':[[10,10],[200,10],[200,110],[10,110]]}
        value={'text':'246810','confidence':.99,'polygon':[[10,250],[90,250],[90,270],[10,270]]}
        index=ContentIndex();index.update(image);index.accept(image,[label,value])
        latest=image.copy();latest[15,20]=255
        index.update(latest)
        self.assertTrue(index.unknown[3,0])
        index.accept(image,[label,value])
        self.assertTrue(index.unknown[3,0])


if __name__=='__main__':unittest.main()
