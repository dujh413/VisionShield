import unittest
from types import SimpleNamespace
import numpy as np
from content_state import ContentState


def line(text, x=800, y=800):
    return {'text':text, 'confidence':.99,
            'polygon':[[x,y],[x+180,y],[x+180,y+20],[x,y+20]]}


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((1000,1000,3), dtype=np.uint8)
        self.state = ContentState()
        self.frame = SimpleNamespace(image=self.image, frame_id=1, captured_at=0.)
        self.state.observe(self.frame)

    def result(self, lines=None, **extra):
        return {'image':self.image, 'frame_id':1, 'captured_at':0.,
                'lines':[line('13800138000')] if lines is None else lines, **extra}

    def test_late_result_keeps_unchanged_text_with_partial_protection(self):
        moved = self.image.copy()
        moved[10,10] = 255
        self.state.observe(SimpleNamespace(image=moved, frame_id=30, captured_at=3.))
        self.assertTrue(self.state.accept(self.result(), 3.))
        view = self.state.view(3.)
        self.assertTrue(view['coordinates_valid'])
        self.assertFalse(view['full'])
        self.assertEqual(len(view['hits']), 1)
        self.assertFalse(view['coverage_complete'])

    def test_changed_sensitive_character_invalidates_old_line(self):
        self.state.accept(self.result(), 0.)
        changed = self.image.copy()
        changed[810,820] = 1
        self.state.observe(SimpleNamespace(image=changed, frame_id=2, captured_at=.1))
        view = self.state.view(.1)
        self.assertEqual(view['hits'], [])
        self.assertTrue(any(x<=800 and y<=800 and x+w>=980 and y+h>=820 for x,y,w,h in view['rectangles']))

    def test_label_change_invalidates_neighbouring_value(self):
        lines = [line('普通标签', x=100, y=100), line('246810', x=100, y=130)]
        self.state.accept(self.result(lines), 0.)
        changed = self.image.copy()
        changed[110,150] = 255
        self.state.observe(SimpleNamespace(image=changed, frame_id=2, captured_at=.1))
        self.assertEqual(self.state.view(.1)['valid_lines'], 0)

    def test_capture_stall_expires_cached_result(self):
        self.state.accept(self.result(), 0.)
        view = self.state.view(120.)
        self.assertTrue(view['full'])
        self.assertTrue(view['capture_failed'])
        self.assertFalse(view['coordinates_valid'])

    def test_partial_unknown_region_covers_entire_sensitive_line(self):
        self.state.accept(self.result(unknown_regions=[(850,800,870,820)]), 0.)
        view = self.state.view(0.)
        self.assertEqual(view['hits'], [])
        self.assertTrue(any(x<=800 and y<=800 and x+w>=980 and y+h>=820
                            for x,y,w,h in view['rectangles']))

    def test_result_ttl_expires_even_with_fresh_capture(self):
        self.state.accept(self.result(), 0.)
        self.state.observe(SimpleNamespace(image=self.image.copy(), frame_id=100, captured_at=11.))
        self.assertFalse(self.state.view(11.)['coordinates_valid'])

    def test_empty_result_is_unknown(self):
        self.state.accept(self.result([]), 0.)
        view = self.state.view(0.)
        self.assertTrue(view['full'])
        self.assertFalse(view['coverage_complete'])

    def test_stale_future_and_out_of_order_results_are_rejected(self):
        self.assertFalse(self.state.accept(self.result(captured_at=1.), 0.))
        self.assertFalse(self.state.accept(self.result(), 11.))
        self.assertTrue(self.state.accept(self.result(), 0.))
        self.assertFalse(self.state.accept(self.result(), 0.))

    def test_bad_geometry_and_confidence_are_rejected(self):
        for item in (line('x', x=-1), {**line('x'), 'confidence':float('nan')}):
            with self.assertRaises(ValueError):
                self.state.accept(self.result([item]), 0.)

    def test_identical_frames_are_not_resubmitted_until_refresh(self):
        self.assertTrue(self.state.should_submit(0.))
        self.state.mark_submitted(0.)
        self.state.observe(SimpleNamespace(image=self.image.copy(), frame_id=2, captured_at=.5))
        self.assertFalse(self.state.should_submit(.5))
        self.state.observe(SimpleNamespace(image=self.image.copy(), frame_id=50, captured_at=5.))
        self.assertTrue(self.state.should_submit(5.))

    def test_resolution_change_removes_old_coordinates(self):
        self.state.accept(self.result(), 0.)
        self.state.observe(SimpleNamespace(image=np.zeros((500,500,3),dtype=np.uint8), frame_id=2, captured_at=.1))
        self.assertTrue(self.state.view(.1)['full'])


if __name__ == '__main__':
    unittest.main()
