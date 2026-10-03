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


if __name__=='__main__':unittest.main()
