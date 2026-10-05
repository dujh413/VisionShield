import ctypes as ct
import os
import threading
import unittest
from unittest.mock import patch

import numpy as np

import gpu_blur
from gpu_blur import MAX_GPU_RADIUS, OpenClBoxBlur, OpenClError, OpenClUnavailable
from mask_effect import box_blur


def _put(pointer, value, value_type=ct.c_int32):
    ct.cast(pointer, ct.POINTER(value_type))[0] = value


class FakeApi:
    """Record owned native resources without requiring a GPU in lifecycle tests."""

    def __init__(self, failure=None):
        self.failure = failure
        self.created_buffers = []
        self.released_buffers = []
        self.released_events = []
        self.released_kernels = []
        self.released_other = []
        self.submissions = 0
        self.finishes = 0
        self._next_handle = 100

    def _create(self, stage, status):
        if stage == self.failure:
            _put(status, -5)
            return None
        _put(status, 0)
        self._next_handle += 1
        return self._next_handle

    def clCreateContext(self, *args):
        return self._create('context', args[-1])

    def clCreateCommandQueue(self, *args):
        return self._create('queue', args[-1])

    def clCreateProgramWithSource(self, *args):
        return self._create('program', args[-1])

    def clBuildProgram(self, *args):
        return -5 if self.failure == 'build' else 0

    def clCreateKernel(self, *args):
        return self._create('kernel', args[-1])

    def clCreateBuffer(self, *args):
        stage = 'second buffer' if len(self.created_buffers) == 1 else 'buffer'
        value = self._create(stage, args[-1])
        if value:
            self.created_buffers.append(value)
        return value

    def clSetKernelArg(self, *args):
        return 0

    def clEnqueueNDRangeKernel(self, *args):
        self.submissions += 1
        if self.failure == 'second kernel' and self.submissions == 2:
            return -5
        self._next_handle += 1
        _put(args[-1], self._next_handle, ct.c_void_p)
        return 0

    def clEnqueueReadBuffer(self, queue, buffer, blocking, offset, size, destination, *args):
        if self.failure == 'read':
            return -5
        ct.memset(destination, 0, size)
        return 0

    def clGetEventProfilingInfo(self, event, field, size, destination, returned_size):
        if self.failure == 'profile':
            return -5
        _put(destination, 100 if field == 0x1282 else 2100, ct.c_uint64)
        return 0

    def clFinish(self, queue):
        self.finishes += 1
        return -5 if self.failure == 'finish' else 0

    def clReleaseMemObject(self, value):
        self.released_buffers.append(value)
        return -5 if self.failure == 'buffer release' else 0

    def clReleaseEvent(self, value):
        self.released_events.append(value.value)
        return 0

    def clReleaseKernel(self, value):
        self.released_kernels.append(value)
        return -5 if self.failure == 'kernel release' else 0

    def clReleaseProgram(self, value):
        self.released_other.append(('program', value))
        return 0

    def clReleaseCommandQueue(self, value):
        self.released_other.append(('queue', value))
        return 0

    def clReleaseContext(self, value):
        self.released_other.append(('context', value))
        return 0


class NativeLifecycleTests(unittest.TestCase):
    def engine(self, api):
        with patch('gpu_blur._load_api', return_value=api), patch(
                'gpu_blur._select_device', return_value=(7, 'Synthetic GPU')):
            return OpenClBoxBlur()

    def test_success_profiles_real_commands_and_releases_each_image_buffer(self):
        api = FakeApi()
        with self.engine(api) as engine:
            output = engine.blur_bgr(np.ones((3, 7, 3), np.uint8), 2)
            self.assertTrue(output.flags.c_contiguous)
            self.assertEqual(engine.last_kernel_events, 2)
            self.assertAlmostEqual(engine.last_gpu_ms, 0.004)
            self.assertEqual(api.released_buffers, list(reversed(api.created_buffers)))
            self.assertEqual(len(api.released_events), 2)
            self.assertFalse(api.released_other)
        self.assertEqual(len(api.released_kernels), 2)
        self.assertEqual([kind for kind, _ in api.released_other], ['program', 'queue', 'context'])
        engine.close()
        self.assertEqual(len(api.released_other), 3)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            engine.blur_bgr(np.ones((3, 7, 3), np.uint8), 2)

    def test_partial_initialization_is_released(self):
        for failure, kinds in [('queue', ['context']), ('build', ['program', 'queue', 'context'])]:
            with self.subTest(failure=failure):
                api = FakeApi(failure)
                with self.assertRaises(OpenClError):
                    self.engine(api)
                self.assertEqual([kind for kind, _ in api.released_other], kinds)

    def test_every_failure_releases_buffers_and_submitted_events(self):
        for failure, expected_events in [('second buffer', 0), ('second kernel', 1),
                                         ('read', 2), ('profile', 2)]:
            with self.subTest(failure=failure):
                api = FakeApi(failure)
                with self.engine(api) as engine:
                    with self.assertRaisesRegex(OpenClError, 'OpenCL status -5'):
                        engine.blur_bgr(np.ones((3, 7, 3), np.uint8), 2)
                    self.assertEqual(engine.last_kernel_events, 0)
                    self.assertEqual(engine.last_gpu_ms, 0)
                    self.assertEqual(api.released_buffers, list(reversed(api.created_buffers)))
                    self.assertEqual(len(api.released_events), expected_events)
                    if expected_events:
                        self.assertGreaterEqual(api.finishes, 1)

    def test_foreign_thread_cannot_execute_or_close_native_resources(self):
        api = FakeApi()
        errors = []
        with self.engine(api) as engine:
            def foreign():
                for operation in (lambda: engine.blur_bgr(np.ones((1, 1, 3), np.uint8), 1), engine.close):
                    try:
                        operation()
                    except RuntimeError as exc:
                        errors.append(str(exc))
            thread = threading.Thread(target=foreign)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 2)
            self.assertFalse(api.released_other)

    def test_release_failure_invalidates_result_and_close_retries_owned_buffers(self):
        api = FakeApi('buffer release')
        engine = self.engine(api)
        with self.assertRaisesRegex(OpenClError, 'image buffer release'):
            engine.blur_bgr(np.ones((3, 7, 3), np.uint8), 2)
        self.assertEqual(len(api.released_buffers), 3)
        self.assertEqual(len(api.released_events), 2)
        self.assertEqual(engine.last_kernel_events, 0)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            engine.blur_bgr(np.ones((3, 7, 3), np.uint8), 2)
        with self.assertRaisesRegex(OpenClError, 'image buffer release'):
            engine.close()
        self.assertEqual(len(api.released_buffers), 6)
        self.assertEqual(len(api.released_kernels), 2)
        self.assertEqual(len(api.released_other), 3)
        self.assertFalse(engine._released)
        api.failure = None
        engine.close()
        self.assertEqual(len(api.released_buffers), 9)
        self.assertTrue(engine._released)

    def test_close_reports_failure_after_attempting_all_releases(self):
        api = FakeApi('kernel release')
        engine = self.engine(api)
        with self.assertRaisesRegex(OpenClError, 'kernel release'):
            engine.close()
        self.assertEqual(len(api.released_kernels), 2)
        self.assertEqual(len(api.released_other), 3)
        self.assertFalse(engine._released)
        api.failure = None
        engine.close()
        self.assertEqual(len(api.released_kernels), 4)
        self.assertTrue(engine._released)

    def test_radius_is_never_clamped_or_truncated(self):
        image = np.ones((2, 3, 3), np.uint8)
        api = FakeApi()
        with self.engine(api) as engine:
            for radius in (0, -1, True, 1.0, MAX_GPU_RADIUS + 1, 10 ** 100):
                with self.subTest(radius=radius):
                    self.assertFalse(engine.supports(image, radius))
                    with self.assertRaises(ValueError):
                        engine.blur_bgr(image, radius)
            self.assertFalse(api.created_buffers)
        for image in (np.zeros((0, 1, 3), np.uint8), np.zeros((2, 3), np.uint8),
                      np.zeros((2, 3, 4), np.uint8), np.zeros((2, 3, 3), np.float32)):
            self.assertFalse(OpenClBoxBlur.supports(image, 1))


@unittest.skipUnless(os.environ.get('VISIONSHIELD_TEST_GPU_BLUR') == '1',
                     'Set VISIONSHIELD_TEST_GPU_BLUR=1 for installed-driver tests')
class RealGpuPixelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Explicit opt-in requires a working GPU; a broken driver must fail.
        cls.engine = OpenClBoxBlur()

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_edges_small_rois_and_supported_radii_match_cpu_exactly(self):
        rng = np.random.default_rng(971)
        for shape in ((1, 1, 3), (1, 7, 3), (5, 1, 3), (5, 7, 3), (17, 31, 3)):
            image = rng.integers(0, 256, shape, dtype=np.uint8)
            original = image.copy()
            image.flags.writeable = False
            for radius in (1, 2, 8, 16, 32, MAX_GPU_RADIUS):
                with self.subTest(shape=shape, radius=radius):
                    output = self.engine.blur_bgr(image, radius)
                    expected = box_blur(image, radius)[:, :, ::-1]
                    np.testing.assert_array_equal(output, expected)
                    np.testing.assert_array_equal(image, original)
                    self.assertTrue(output.flags.c_contiguous)
                    self.assertEqual(self.engine.last_kernel_events, 2)
                    self.assertGreaterEqual(self.engine.last_gpu_ms, 0)

    def test_noncontiguous_input_constant_color_and_rgb_order(self):
        image = np.full((13, 29, 3), (13, 67, 211), np.uint8)[:, ::2]
        self.assertFalse(image.flags.c_contiguous)
        output = self.engine.blur_bgr(image, 8)
        np.testing.assert_array_equal(output, np.full(image.shape, (211, 67, 13), np.uint8))


if __name__ == '__main__':
    unittest.main()
