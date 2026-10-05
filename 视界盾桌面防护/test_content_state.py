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

    def test_live_state_uses_one_exact_difference_and_cached_geometry(self):
        from unittest.mock import patch
        import content_state
        import content_index
        with patch('content_index.with_context', wraps=content_index.with_context) as geometry:
            self.state.accept(self.result(), 0.)
            for identifier in range(2, 5):
                timestamp = identifier * .1
                frame = SimpleNamespace(image=self.image.copy(), frame_id=identifier, captured_at=timestamp)
                with patch('content_state._ExactDifference', wraps=content_state._ExactDifference) as difference:
                    self.state.observe(frame)
                    self.assertEqual(difference.call_count, 1)
                # Only frame identity and text change; the geometry is reused,
                # while classification must read the fresh text.
                item = {**self.result([line('普通文字')]), 'frame_id':identifier,
                        'captured_at':timestamp, 'image':frame.image}
                with patch('content_state._ExactDifference', wraps=content_state._ExactDifference) as difference:
                    self.assertTrue(self.state.accept(item, timestamp))
                    self.assertEqual(difference.call_count, 1)
                self.assertFalse(self.state.view(timestamp)['hits'])
            self.assertEqual(geometry.call_count, 1)

    def test_missing_large_label_keeps_live_value_protected_until_complete_coverage(self):
        label = {'text':'验证码', 'confidence':.99,
                 'polygon':[[10,10],[200,10],[200,110],[10,110]]}
        value = line('246810', x=10, y=250)
        self.state.accept(self.result([label,value]), 0.)
        latest = self.image.copy(); latest[15,20] = 1
        for identifier in range(2, 102):
            timestamp = identifier * .1
            self.state.observe(SimpleNamespace(image=latest, frame_id=identifier, captured_at=timestamp))
            self.state.accept({'image':latest,'frame_id':identifier,'captured_at':timestamp,
                               'lines':[value],'unknown_regions':[(0,0,210,130)]}, timestamp)
            view = self.state.view(timestamp)
            self.assertEqual(view['hits'], [])
            self.assertEqual(view['valid_lines'], 0)
            self.assertTrue(any(x<=10 and y<=250 and x+w>=190 and y+h>=270
                                for x,y,w,h in view['rectangles']))
            self.assertLessEqual(len(self.state._dependencies), 3)
        self.state.observe(SimpleNamespace(image=latest, frame_id=102, captured_at=10.2))
        self.state.accept({'image':latest,'frame_id':102,'captured_at':10.2,
                           'lines':[label,value],'unknown_regions':[]}, 10.2)
        self.assertTrue(self.state.view(10.2)['coverage_complete'])
        self.assertEqual(len(self.state.view(10.2)['hits']), 2)

    def test_changed_tile_does_not_invalidate_unchanged_context(self):
        self.state.accept(self.result([line('13800138000',x=100,y=100)]), 0.)
        latest = self.image.copy(); latest[10,10] = 1
        self.state.observe(SimpleNamespace(image=latest, frame_id=2, captured_at=.1))
        view = self.state.view(.1)
        self.assertEqual(len(view['hits']), 1)
        self.assertEqual(view['valid_lines'], 1)
        self.assertFalse(view['coverage_complete'])

    def test_active_state_keeps_far_changes_separate(self):
        self.state.accept(self.result([line('13800138000',x=400,y=400)]), 0.)
        latest = self.image.copy(); latest[10,10] = 1; latest[900,900] = 1
        self.state.observe(SimpleNamespace(image=latest, frame_id=2, captured_at=.1))
        view = self.state.view(.1)
        self.assertFalse(view['full'])
        self.assertEqual(view['unknown_regions'], 2)
        self.assertEqual(len(view['hits']), 1)

    def test_invalid_result_does_not_replace_valid_live_state(self):
        self.state.accept(self.result(), 0.)
        self.state.observe(SimpleNamespace(image=self.image.copy(),frame_id=2,captured_at=.1))
        with self.assertRaises(ValueError):
            self.state.accept({**self.result([line('ordinary')]),'frame_id':2,
                               'captured_at':.1,'unknown_regions':[(0,0,float('nan'),20)]}, .1)
        self.assertEqual(self.state.result_frame_id, 1)
        self.assertEqual(len(self.state.view(.1)['hits']),1)


if __name__ == '__main__':
    unittest.main()
