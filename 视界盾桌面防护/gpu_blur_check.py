"""Strict synthetic OpenCL blur check; no screenshot, OCR, camera or Qt."""
import argparse
import json
import statistics
import time

import numpy as np

from gpu_blur import MAX_GPU_RADIUS, OpenClBoxBlur
from mask_effect import box_blur


def run(radius, samples):
    start = time.perf_counter()
    gpu = OpenClBoxBlur()
    initialization_ms = (time.perf_counter()-start)*1000
    try:
        rng = np.random.default_rng(971)
        for shape in ((1, 1, 3), (1, 7, 3), (5, 1, 3), (19, 31, 3)):
            image = rng.integers(0, 256, shape, dtype=np.uint8)
            original = image.copy()
            image.flags.writeable = False
            for checked_radius in sorted({1, 2, 8, radius}):
                actual = gpu.blur_bgr(image, checked_radius)
                np.testing.assert_array_equal(actual, box_blur(image, checked_radius)[:, :, ::-1])
                np.testing.assert_array_equal(image, original)
                if gpu.last_kernel_events != 2:
                    raise RuntimeError('GPU kernel execution was not verified')
        image = rng.integers(0, 256, (1600, 2560, 3), dtype=np.uint8)
        image.flags.writeable = False
        # Reference comparison stays outside the timed measurement.
        np.testing.assert_array_equal(gpu.blur_bgr(image, radius), box_blur(image, radius)[:, :, ::-1])
        elapsed, kernels = [], []
        for number in range(samples+2):
            start = time.perf_counter()
            gpu.blur_bgr(image, radius)
            duration = (time.perf_counter()-start)*1000
            if gpu.last_kernel_events != 2:
                raise RuntimeError('GPU kernel execution was not verified')
            if number >= 2:
                elapsed.append(duration)
                kernels.append(gpu.last_gpu_ms)
        return {'passed':True, 'backend':'opencl-gpu', 'device':gpu.device,
                'radius':radius, 'resolution':[2560,1600], 'samples':samples,
                'initialization_ms':round(initialization_ms,3),
                'render_including_transfers_median_ms':round(statistics.median(elapsed),3),
                'render_including_transfers_p95_ms':round(float(np.percentile(elapsed,95)),3),
                'gpu_kernel_median_ms':round(statistics.median(kernels),3),
                'profiled_kernel_events_per_render':2,
                'synthetic_pixels_correct':True, 'source_unchanged':True}
    finally:
        gpu.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radius', type=int, default=8)
    parser.add_argument('--samples', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.radius <= MAX_GPU_RADIUS:
        parser.error(f'radius must be between 1 and {MAX_GPU_RADIUS}')
    if not 2 <= args.samples <= 200:
        parser.error('samples must be between 2 and 200')
    try:
        result = run(args.radius, args.samples)
    except Exception as error:
        # GPU selfcheck deliberately fails instead of presenting CPU as GPU.
        print(json.dumps({'passed':False, 'error':type(error).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
