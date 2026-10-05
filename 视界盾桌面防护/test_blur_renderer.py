import importlib.util
import threading
import time
import unittest

import numpy as np

from blur_renderer import (BlurCache, BlurRequest, BlurResult, BlurWorker,
                           box_obscure_bgr, mask_crops, obscure_bgr, physical_to_logical)


class ManualWorker:
    def __init__(self):
        self.requests = []
        self.completed = None
        self.closed = False

    def submit(self, request):
        self.requests.append(request)
        return not self.closed

    def poll(self):
        result, self.completed = self.completed, None
        return result

    def finish(self, request=None, error=None):
        request = request or self.requests[-1]
        crops = tuple((box, source, np.zeros_like(source)) for box, source in request.crops)
        self.completed = BlurResult(request.sequence, request.geometry, crops,
                                    error=error, radius=request.radius)

    def cancel(self):
        self.completed = None

    def close(self):
        self.closed = True


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.worker = ManualWorker()
        self.cache = BlurCache(self.worker)
        self.image = np.full((80, 120, 3), 255, dtype=np.uint8)
        self.boxes = ((10, 20, 30, 10),)

    def tearDown(self):
        self.cache.close()

    def ready(self):
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(ready, [])
        self.assertEqual(pending, list(self.boxes))
        self.worker.finish()
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(pending, [])
        return ready

    def test_same_image_call_polls_completion_and_reuses_region(self):
        first = self.ready()
        second, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(pending, [])
        self.assertIs(second[0][1], first[0][1])
        self.assertEqual(len(self.worker.requests), 1)

    def test_unrelated_changed_pixels_reuse_exact_cache(self):
        first = self.ready()
        new_frame = self.image.copy()
        new_frame[79, 119] = 0
        ready, pending = self.cache.update(self.boxes, new_frame)
        self.assertIs(ready[0][1], first[0][1])
        self.assertEqual(pending, [])
        self.assertEqual(len(self.worker.requests), 1)

    def test_single_changed_pixel_invalidates_even_same_image_object(self):
        self.ready()
        self.image[20, 10, 0] -= 1
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(ready, [])
        self.assertEqual(pending, list(self.boxes))
        self.assertEqual(len(self.worker.requests), 2)

    def test_stale_completion_is_never_displayed(self):
        self.cache.update(self.boxes, self.image)
        old = self.worker.requests[-1]
        self.image[20, 10] = 0
        self.cache.update(self.boxes, self.image)
        self.worker.finish(old)
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(ready, [])
        self.assertEqual(pending, list(self.boxes))
        self.worker.finish()
        self.assertEqual(self.cache.update(self.boxes, self.image)[1], [])

    def test_changed_geometry_rejects_prior_completion(self):
        self.cache.update(self.boxes, self.image)
        old = self.worker.requests[-1]
        new_boxes = self.boxes + ((70, 10, 20, 20),)
        self.cache.update(new_boxes, self.image)
        self.worker.finish(old)
        ready, pending = self.cache.update(new_boxes, self.image)
        self.assertEqual(ready, [])
        self.assertEqual(pending, list(new_boxes))

    def test_owned_small_crop_and_clear_release_cached_content(self):
        self.cache.update(self.boxes, self.image)
        source = self.worker.requests[-1].crops[0][1]
        self.assertEqual(source.shape, (10, 30, 3))
        self.assertFalse(np.shares_memory(source, self.image))
        self.assertFalse(source.flags.writeable)
        self.worker.finish()
        self.cache.update(self.boxes, self.image)
        self.cache.clear()
        self.assertEqual(self.cache._ready, {})
        self.assertIsNone(self.cache._submitted)
        self.assertIsNone(self.worker.completed)

    def test_missing_source_and_render_error_use_fallback(self):
        self.cache.update(self.boxes, self.image)
        self.worker.finish(error='SyntheticFailure')
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual(ready, [])
        self.assertEqual(pending, list(self.boxes))
        self.assertEqual(self.cache.last_error, 'SyntheticFailure')
        self.assertEqual(len(self.worker.requests), 1)  # bounded retry/backoff
        self.assertEqual(self.cache.update(self.boxes, None), ([], list(self.boxes)))

    def test_mixed_valid_and_changed_regions_keep_pending_fallback(self):
        self.boxes += ((70, 10, 20, 20),)
        self.ready()
        self.image[10, 70] = 0
        ready, pending = self.cache.update(self.boxes, self.image)
        self.assertEqual([box for box, _ in ready], [self.boxes[0]])
        self.assertEqual(pending, [self.boxes[1]])
        self.assertEqual([box for box, _ in self.worker.requests[-1].crops], [self.boxes[1]])


class GeometryTests(unittest.TestCase):
    def test_zero_padding_does_not_merge_scoped_l_shape(self):
        boxes = mask_crops([(0, 0, 100, 40), (0, 40, 40, 60)], (100, 100, 3), padding=0)
        self.assertEqual(boxes, ((0, 0, 100, 40), (0, 40, 40, 60)))

    def test_clipping_outward_rounding_and_overlap_merge(self):
        boxes = mask_crops([(-4.5, 2.2, 20, 10), (12, 10, 10, 10), (80, 40, 8, 6)], (60, 100, 3))
        self.assertEqual(boxes, ((0, 0, 30, 28), (72, 32, 24, 22)))

    def test_invalid_geometry_is_rejected_and_dpi_is_exact(self):
        for invalid in ((1, 2, float('nan'), 4), (0, 0, -1, 4)):
            with self.assertRaises(ValueError):
                mask_crops([invalid], (30, 30, 3))
        self.assertEqual(physical_to_logical((15, 30, 45, 60), 1.5), (10, 20, 30, 40))
        with self.assertRaises(ValueError):
            physical_to_logical((1, 2, 3, 4), 0)


class WorkerTests(unittest.TestCase):
    def test_box_radius_keeps_exact_colors_without_legacy_darkening(self):
        from mask_effect import box_blur
        image = np.random.default_rng(2).integers(0, 256, (21, 33, 3), dtype=np.uint8)
        for radius in (0, 1, 2, 8, 10**100):
            np.testing.assert_array_equal(box_obscure_bgr(image, radius),
                                          box_blur(image, radius)[:, :, ::-1])

    def test_close_timeout_reports_live_worker_and_discards_completed_content(self):
        started, release = threading.Event(), threading.Event()

        def render(source):
            started.set()
            release.wait(2)
            return source.copy()

        worker = BlurWorker(render)
        box = (0, 0, 2, 2)
        try:
            worker.submit(BlurRequest(1, (box,), ((box, np.zeros((2, 2, 3), np.uint8)),)))
            self.assertTrue(started.wait(1))
            with self.assertRaises(TimeoutError):
                worker.close(timeout=.01)
            self.assertTrue(worker.alive)
            self.assertFalse(worker.submit(BlurRequest(2, (), ())))
            self.assertIsNone(worker.poll())
            release.set()
            worker.close()
            self.assertFalse(worker.alive)
            self.assertIsNone(worker.poll())
        finally:
            release.set()
            worker.close()

    def test_pending_queue_replaces_intermediate_work_and_close_clears(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def render(source):
            calls.append(int(source[0, 0, 0]))
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError('test timeout')
            return np.zeros_like(source)

        worker = BlurWorker(render)
        box = (0, 0, 2, 2)
        try:
            worker.submit(BlurRequest(1, (box,), ((box, np.full((2, 2, 3), 1, np.uint8)),)))
            self.assertTrue(started.wait(1))
            for number in range(2, 21):
                worker.submit(BlurRequest(number, (box,), ((box, np.full((2, 2, 3), number, np.uint8)),)))
                self.assertEqual(worker.queued_count, 1)
            release.set()
            deadline, latest = time.monotonic()+2, None
            while time.monotonic() < deadline:
                result = worker.poll()
                if result is not None:
                    latest = result
                    if result.sequence == 20:
                        break
                time.sleep(.005)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.sequence, 20)
            self.assertEqual(calls, [1, 20])
        finally:
            release.set()
            worker.close()
        self.assertFalse(worker.alive)
        self.assertEqual(worker.queued_count, 0)
        self.assertIsNone(worker.poll())
        self.assertFalse(worker.submit(BlurRequest(21, (), ())))

    def test_cancel_discards_inflight_result(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()

        def render(source):
            started.set()
            release.wait(2)
            done.set()
            return source.copy()

        worker = BlurWorker(render)
        box = (0, 0, 2, 2)
        try:
            worker.submit(BlurRequest(1, (box,), ((box, np.zeros((2, 2, 3), np.uint8)),)))
            self.assertTrue(started.wait(1))
            worker.cancel()
            release.set()
            self.assertTrue(done.wait(1))
            worker.close()
            self.assertIsNone(worker.poll())
        finally:
            release.set()
            worker.close()

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV unavailable')
    def test_render_retains_original_strength_exactly(self):
        import cv2
        roi = np.random.default_rng(8).integers(0, 256, (75, 181, 3), dtype=np.uint8)
        small = cv2.resize(roi, (5, 2), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        expected = cv2.resize(small, (181, 75), interpolation=cv2.INTER_LINEAR)
        expected = cv2.cvtColor((expected*.45).astype('uint8'), cv2.COLOR_BGR2RGB)
        rendered = obscure_bgr(roi)
        self.assertTrue(np.array_equal(rendered, expected))
        self.assertLessEqual(int(rendered.max()), 114)


if __name__ == '__main__':
    unittest.main()
