import unittest
import numpy as np
from mask_effect import parse_effect, box_blur
from blur_worker import crop_boxes, render_blur, BlurWorker


class EffectTests(unittest.TestCase):
    def test_empty_and_whitespace_disable_processing(self):
        for text in ('', '  ', '\t\n'):
            self.assertEqual(parse_effect(text).mode, 'off')

    def test_digits_select_exact_radius(self):
        for text, radius in [('12', 12), (' 08 ', 8), ('１２', 12), ('0', 0)]:
            effect = parse_effect(text)
            self.assertEqual((effect.mode, effect.radius), ('blur', radius))

    def test_other_characters_select_dark_mask(self):
        for text in ('遮挡', 'abc', '12a', '-3', '1.5'):
            self.assertEqual(parse_effect(text).mode, 'block')

    def test_box_mean_matches_uniform_kernel(self):
        image = np.arange(5*7*3, dtype=np.uint8).reshape(5, 7, 3)
        for radius in (1, 2, 8):
            padded = np.pad(image, ((radius,radius),(radius,radius),(0,0)), mode='edge')
            expected = np.empty_like(image)
            for y in range(5):
                for x in range(7):
                    expected[y,x] = np.rint(padded[y:y+2*radius+1, x:x+2*radius+1].mean(axis=(0,1)))
            np.testing.assert_array_equal(box_blur(image, radius), expected)

    def test_zero_radius_and_input_immutability(self):
        image = np.arange(48, dtype=np.uint8).reshape(4, 4, 3)
        before = image.copy()
        np.testing.assert_array_equal(box_blur(image, 0), image)
        box_blur(image, 2)
        np.testing.assert_array_equal(image, before)

    def test_large_radius_uses_bounded_memory(self):
        image = np.full((3,4,3), 100, dtype=np.uint8)
        np.testing.assert_array_equal(box_blur(image, 10**100), image)

    def test_sensitive_crops_clip_and_merge(self):
        image = np.zeros((100,100,3), dtype=np.uint8)
        boxes = crop_boxes(image, [(-5,-5,20,20), (10,10,20,20), (200,200,5,5)])
        self.assertEqual(boxes, [(0,0,36,36)])
        patches = render_blur(image, boxes, 3)
        self.assertEqual(patches[0][1].shape, (36,36,3))

    def test_worker_filter_finishes_and_closes(self):
        import time
        image = np.zeros((16,16,3), dtype=np.uint8)
        worker = BlurWorker()
        try:
            worker.submit(image, [(0,0,16,16)], 2)
            deadline = time.monotonic()+2
            item = None
            while item is None and time.monotonic()<deadline:
                item = worker.poll()
                time.sleep(.01)
            self.assertIsNotNone(item)
            self.assertEqual(item['radius'], 2)
        finally:
            worker.close()
        self.assertFalse(worker.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
