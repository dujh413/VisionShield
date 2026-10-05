import unittest
import numpy as np
from content_index import ContentIndex, _ExactDifference


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
        self.assertTrue(self.index.unknown.all())

    def test_explicit_complete_empty_result_can_confirm_blank_screen(self):
        self.index.accept(self.image,[],unknown_regions=[])
        self.assertFalse(self.index.hits)
        self.assertFalse(self.index.unknown.any())

    def test_unknown_crop_remains_pending_on_unchanged_cached_frame(self):
        crop=(240,120,320,192)
        self.index.accept(self.image,[self.line],unknown_regions=[crop])
        self.assertEqual(len(self.index.hits),1)
        self.assertTrue(self.index.unknown[2,4])
        self.index.update(self.image.copy())
        self.index.accept(self.image,[self.line],unknown_regions=[crop])
        self.assertTrue(self.index.unknown[2,4])
        self.index.accept(self.image,[self.line],unknown_regions=[])
        self.assertFalse(self.index.unknown.any())

    def test_unknown_label_context_covers_entire_value_line(self):
        label={'text':'验证码','confidence':.99,'polygon':[[10,10],[90,10],[90,30],[10,30]]}
        value={'text':'246810','confidence':.99,'polygon':[[10,68],[190,68],[190,88],[10,88]]}
        self.index.accept(self.image,[label,value],unknown_regions=[(10,10,30,20)])
        self.assertTrue(self.index.unknown[1,0])
        self.assertTrue(self.index.unknown[1,2])
        self.assertFalse(self.index.hits)

    def test_unknown_crop_does_not_remove_newer_confirmed_hit(self):
        latest=self.image.copy();latest[15,20]=255
        self.index.update(latest)
        self.index.accept(latest,[self.line],unknown_regions=[])
        self.index.accept(self.image,[],unknown_regions=[(240,120,320,192)])
        self.assertEqual(len(self.index.hits),1)
        self.assertTrue(self.index.unknown[2,4])

    def test_empty_text_inside_detected_box_is_unknown(self):
        blank={**self.line,'text':'  '}
        self.index.accept(self.image,[blank],unknown_regions=[])
        self.assertTrue(self.index.unknown[0,2])

    def test_bad_unknown_crop_is_rejected_without_mutating_index(self):
        for crop in ((0,0,float('nan'),20),(-1,0,20,20),(0,0,321,20),(20,0,10,20),(0,0,20)):
            with self.subTest(crop=crop),self.assertRaises(ValueError):
                self.index.accept(self.image,[self.line],unknown_regions=[crop])
            self.assertFalse(self.index.unknown.any())
            self.assertEqual(len(self.index.hits),1)

    def test_cached_geometry_does_not_cache_old_text_or_mutate_source(self):
        ordinary={**self.line,'text':'普通聊天'}
        self.index.accept(self.image,[ordinary],unknown_regions=[])
        self.assertFalse(self.index.hits)
        self.index.accept(self.image,[self.line],unknown_regions=[])
        self.assertEqual(len(self.index.hits),1)
        self.assertNotIn('_context',self.line)
        self.assertFalse(self.image.any())

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

    def test_missing_large_label_keeps_value_pending_across_cached_results(self):
        image=np.zeros((512,320,3),dtype=np.uint8)
        label={'text':'验证码','confidence':.99,'polygon':[[10,10],[200,10],[200,110],[10,110]]}
        value={'text':'246810','confidence':.99,'polygon':[[10,250],[190,250],[190,270],[10,270]]}
        index=ContentIndex();index.update(image);index.accept(image,[label,value],unknown_regions=[])
        latest=image.copy();latest[15,20]=255
        index.update(latest)
        for _ in range(100):
            index.accept(latest,[value],unknown_regions=[(0,0,210,130)])
            self.assertTrue(index.unknown[3,0])
            self.assertTrue(index.unknown[4,2])
            self.assertLessEqual(len(index.lines),2)
        # 新结果重新覆盖标签后，旧的未知上下文才可移除。
        index.accept(latest,[label,value],unknown_regions=[])
        self.assertFalse(index.unknown.any())
        self.assertEqual(len(index.hits),2)


class ExactDifferenceTests(unittest.TestCase):
    def test_tile_integral_and_partial_edges_match_pixel_comparison(self):
        rng=np.random.default_rng(20261005)
        first=np.zeros((137,203,3),dtype=np.uint8)
        for dense in (False,True):
            second=first.copy()
            if dense:
                second[:]=rng.integers(0,3,size=second.shape,dtype=np.uint8)
            else:
                second[0,0,0]=1;second[136,202,2]=1
                second[63,64,1]=1;second[64,63,2]=1;second[90,160,0]=1
            index=ContentIndex()
            difference=_ExactDifference(first,second,index.tile,index.tiles)
            rectangles=[(0,0,1,1),(0,0,203,137),(64,64,128,128),(64,0,65,64),
                        (192,128,203,137),(0,0,0,0),(0,0,64,64)]
            for _ in range(300):
                xs=sorted(rng.integers(0,204,size=2).tolist())
                ys=sorted(rng.integers(0,138,size=2).tolist())
                rectangles.append((xs[0],ys[0],xs[1],ys[1]))
            for rectangle in rectangles:
                x1,y1,x2,y2=rectangle
                expected=not np.array_equal(first[y1:y2,x1:x2],second[y1:y2,x1:x2])
                with self.subTest(dense=dense,rectangle=rectangle):
                    self.assertEqual(difference.changed(rectangle),expected)

    def test_unchanged_pixel_in_changed_tile_does_not_invalidate_region(self):
        image=np.zeros((192,320,3),dtype=np.uint8)
        latest=image.copy();latest[63,63]=255
        index=ContentIndex()
        difference=_ExactDifference(image,latest,index.tile,index.tiles)
        self.assertTrue(difference.tiles[0,0])
        self.assertFalse(difference.changed((0,0,30,30)))


if __name__=='__main__':unittest.main()
