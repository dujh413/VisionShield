"""Failure/lifecycle tests without a GPU, driver, real capture or model."""
import threading
import time
import unittest

import numpy as np

from blur_renderer import BoxBlurEngine, BlurRequest, BlurWorker, box_obscure_bgr


class SyntheticGpu:
    device = 'Synthetic GPU'
    last_gpu_ms = .25

    def __init__(self, fail=False, started=None, release=None, bad_output=False):
        self.fail, self.bad_output = fail, bad_output
        self.started, self.release = started, release
        self.calls, self.closes, self.threads = [], 0, [threading.get_ident()]

    def blur_bgr(self, image, radius):
        self.threads.append(threading.get_ident())
        self.calls.append(radius)
        if self.started is not None:
            self.started.set()
            if not self.release.wait(2):
                raise TimeoutError('synthetic timeout')
        if self.fail:
            raise RuntimeError('private image text must not be logged')
        if self.bad_output:
            return np.zeros(image.shape, dtype=np.float64)
        return box_obscure_bgr(image, radius)

    def close(self):
        self.threads.append(threading.get_ident())
        self.closes += 1


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.image = np.random.default_rng(971).integers(0, 256, (19, 31, 3), dtype=np.uint8)
        self.image.flags.writeable = False

    def test_radius_changes_reuse_session_and_actual_metadata(self):
        created = []

        def factory():
            gpu = SyntheticGpu()
            created.append(gpu)
            return gpu

        engine = BoxBlurEngine(factory)
        original = self.image.copy()
        try:
            for radius in (1, 8, 32):
                np.testing.assert_array_equal(engine.render_bgr(self.image, radius),
                                              box_obscure_bgr(self.image, radius))
                self.assertEqual(engine.backend, 'opencl-gpu')
                self.assertEqual(engine.device, 'Synthetic GPU')
                self.assertEqual(engine.gpu_ms, .25)
                self.assertIsNone(engine.fallback)
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].calls, [1, 8, 32])
            np.testing.assert_array_equal(self.image, original)
        finally:
            engine.close()
        self.assertEqual(created[0].closes, 1)

    def test_zero_empty_and_huge_radius_do_not_initialize_gpu_or_truncate(self):
        def forbidden():
            self.fail('GPU initialized for unsupported work')

        engine = BoxBlurEngine(forbidden)
        for image, radius in ((self.image, 0), (self.image[:0], 8),
                              (self.image, 129), (self.image, 10**100)):
            result = engine.render_bgr(image, radius)
            np.testing.assert_array_equal(result, box_obscure_bgr(image, radius))
            self.assertFalse(np.shares_memory(result, image))
            self.assertEqual(engine.backend, 'copy' if radius == 0 or not image.size else 'cpu')
        self.assertEqual(engine.fallback, 'radius-out-of-range')
        engine.close()

    def test_initialization_failure_is_private_and_not_retried(self):
        attempts = []

        def unavailable():
            attempts.append(1)
            raise OSError('private path must not be logged')

        engine = BoxBlurEngine(unavailable)
        for radius in (2, 8):
            np.testing.assert_array_equal(engine.render_bgr(self.image, radius),
                                          box_obscure_bgr(self.image, radius))
            self.assertEqual(engine.backend, 'cpu')
            self.assertEqual(engine.fallback, 'init-OSError')
            self.assertEqual(engine.device, '')
            self.assertEqual(engine.gpu_ms, 0)
        self.assertEqual(len(attempts), 1)
        engine.close()

    def test_execution_failure_closes_session_and_preserves_cpu_output(self):
        gpu = SyntheticGpu(fail=True)
        engine = BoxBlurEngine(lambda: gpu)
        for radius in (1, 8):
            np.testing.assert_array_equal(engine.render_bgr(self.image, radius),
                                          box_obscure_bgr(self.image, radius))
            self.assertEqual(engine.fallback, 'render-RuntimeError')
        self.assertEqual(gpu.calls, [1])
        self.assertEqual(gpu.closes, 1)
        engine.close()
        self.assertEqual(gpu.closes, 1)

    def test_invalid_gpu_output_is_not_published(self):
        gpu = SyntheticGpu(bad_output=True)
        engine = BoxBlurEngine(lambda: gpu)
        np.testing.assert_array_equal(engine.render_bgr(self.image, 2),
                                      box_obscure_bgr(self.image, 2))
        self.assertEqual(engine.backend, 'cpu')
        self.assertEqual(engine.fallback, 'render-ValueError')
        self.assertEqual(gpu.closes, 1)
        engine.close()

    def test_failed_release_retains_handles_for_owner_thread_retry(self):
        class RetryRelease(SyntheticGpu):
            def close(self):
                super().close()
                if self.closes == 1:
                    raise OSError('synthetic transient release failure')

        gpu = RetryRelease(fail=True)
        engine = BoxBlurEngine(lambda: gpu)
        for radius in (2, 8):
            np.testing.assert_array_equal(engine.render_bgr(self.image, radius),
                                          box_obscure_bgr(self.image, radius))
        self.assertEqual(gpu.calls, [2])
        self.assertIs(engine._gpu, gpu)
        engine.close()
        self.assertEqual(gpu.closes, 2)
        self.assertIsNone(engine._gpu)
        self.assertIsNone(engine._close_error)


class WorkerGpuTests(unittest.TestCase):
    @staticmethod
    def request():
        box = (0, 0, 7, 5)
        image = np.full((5, 7, 3), [17, 91, 240], np.uint8)
        image.flags.writeable = False
        return BlurRequest(1, (box,), ((box, image),), radius=8)

    def test_create_render_and_release_on_worker_thread(self):
        created = []

        def factory():
            gpu = SyntheticGpu()
            created.append(gpu)
            return gpu

        worker = BlurWorker(engine_factory=lambda: BoxBlurEngine(factory))
        try:
            worker.submit(self.request())
            deadline, result = time.monotonic()+2, None
            while time.monotonic() < deadline and result is None:
                result = worker.poll()
                time.sleep(.002)
            self.assertIsNotNone(result)
            self.assertIsNone(result.error)
            self.assertEqual(result.backend, 'opencl-gpu')
            self.assertEqual(result.gpu_ms, .25)
            self.assertEqual(result.device, 'Synthetic GPU')
        finally:
            worker.close()
        self.assertEqual(created[0].closes, 1)
        self.assertEqual(len(set(created[0].threads)), 1)
        self.assertNotEqual(created[0].threads[0], threading.get_ident())

    def test_cancel_gpu_inflight_never_publishes_and_close_releases(self):
        started, release = threading.Event(), threading.Event()
        gpu = SyntheticGpu(started=started, release=release)
        worker = BlurWorker(engine_factory=lambda: BoxBlurEngine(lambda: gpu))
        try:
            worker.submit(self.request())
            self.assertTrue(started.wait(1))
            worker.cancel()
            release.set()
            worker.close()
            self.assertIsNone(worker.poll())
            self.assertFalse(worker.alive)
            self.assertEqual(gpu.closes, 1)
        finally:
            release.set()
            worker.close()

    def test_gpu_release_failure_is_reported_to_pause_caller(self):
        class Unreleasable(SyntheticGpu):
            def close(self):
                super().close()
                raise OSError('synthetic release failure')

        worker = BlurWorker(engine_factory=lambda: BoxBlurEngine(Unreleasable))
        worker.submit(self.request())
        deadline = time.monotonic()+2
        while worker.poll() is None and time.monotonic() < deadline:
            time.sleep(.002)
        with self.assertRaisesRegex(RuntimeError, 'release failed'):
            worker.close()
        self.assertFalse(worker.alive)


if __name__ == '__main__':
    unittest.main()
