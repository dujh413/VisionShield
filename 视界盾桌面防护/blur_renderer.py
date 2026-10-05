"""Bounded, in-memory mask rendering. This module does not import Qt or models.

The caller owns the current immutable capture. Workers receive only owned mask
crops. Opaque blurred pixels may bridge the next capture for at most 250ms,
only while the complete mask geometry and effect remain identical.
"""
from dataclasses import dataclass
import math
import threading
import time

import numpy as np


def mask_crops(rectangles, image_shape, padding=8):
    """Clip padded physical-pixel rectangles and merge overlapping crops."""
    if type(padding) is not int or padding < 0:
        raise ValueError('invalid mask padding')
    height, width = int(image_shape[0]), int(image_shape[1])
    if height <= 0 or width <= 0:
        raise ValueError('invalid image bounds')
    boxes = []
    for rectangle in rectangles:
        if len(rectangle) != 4:
            raise ValueError('invalid mask rectangle')
        x, y, w, h = map(float, rectangle)
        if not all(math.isfinite(value) for value in (x, y, w, h)) or w < 0 or h < 0:
            raise ValueError('invalid mask rectangle')
        if w == 0 or h == 0:
            continue
        x1, y1 = max(0, math.floor(x)-padding), max(0, math.floor(y)-padding)
        x2 = min(width, math.ceil(x+w)+padding)
        y2 = min(height, math.ceil(y+h)+padding)
        if x2 > x1 and y2 > y1:
            boxes.append((x1, y1, x2, y2))
    if padding == 0:
        # Scoped masks can surround an excluded foreground window. Bounding-box
        # merging of an L-shaped union would fill its transparent hole.
        return tuple(sorted((x1, y1, x2-x1, y2-y1)
                            for x1, y1, x2, y2 in set(boxes)))
    # Repeat after a merge: its bounding box may intersect a previously separate
    # crop. Each physical pixel then has one deterministic rendering strength.
    merged = []
    while boxes:
        box = boxes.pop(0)
        changed = True
        while changed:
            changed = False
            remaining = []
            for other in boxes:
                if box[0] <= other[2] and other[0] <= box[2] and box[1] <= other[3] and other[1] <= box[3]:
                    box = (min(box[0], other[0]), min(box[1], other[1]),
                           max(box[2], other[2]), max(box[3], other[3]))
                    changed = True
                else:
                    remaining.append(other)
            boxes = remaining
        merged.append((box[0], box[1], box[2]-box[0], box[3]-box[1]))
    return tuple(sorted(merged))


def physical_to_logical(box, ratio):
    ratio = float(ratio)
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('invalid device pixel ratio')
    return tuple(value/ratio for value in box)


def obscure_bgr(roi):
    """Keep the existing pixelation -> Gaussian blur -> 0.45 darkening."""
    import cv2
    height, width = roi.shape[:2]
    small = cv2.resize(roi, (max(1, width//32), max(1, height//32)),
                       interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (3, 3), 0)
    obscured = cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)
    obscured = (obscured*.45).astype(np.uint8)
    return cv2.cvtColor(obscured, cv2.COLOR_BGR2RGB)


def box_obscure_bgr(roi, radius):
    """Exact user-selected box radius; no pixelation or implicit darkening."""
    from mask_effect import box_blur
    return np.ascontiguousarray(box_blur(roi, radius)[:, :, ::-1])


class BoxBlurEngine:
    """Lazy, owned GPU session with the original CPU algorithm as fallback.

    A session is created only for a supported, nonzero numeric radius. Metadata
    describes completed work, never just the presence of a GPU or a driver.
    """
    GPU_RADIUS_LIMIT = 128

    def __init__(self, gpu_factory=None):
        self._gpu_factory = gpu_factory
        self._gpu = None
        self._disabled = None
        self._close_error = None
        self.backend, self.device = 'none', ''
        self.gpu_ms, self.fallback = 0.0, None

    def render_bgr(self, image, radius):
        if type(radius) is not int or radius < 0:
            raise ValueError('invalid box radius')
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError('mask image must be uint8 BGR')
        self.backend, self.device = 'cpu', ''
        self.gpu_ms, self.fallback = 0.0, None
        if radius == 0 or not image.size:
            self.backend = 'copy'
            return np.ascontiguousarray(image[:, :, ::-1]).copy()
        if radius > self.GPU_RADIUS_LIMIT:
            self.fallback = 'radius-out-of-range'
        else:
            if self._gpu is None and self._disabled is None:
                try:
                    if self._gpu_factory is None:
                        from gpu_blur import OpenClBoxBlur
                        self._gpu = OpenClBoxBlur()
                    else:
                        self._gpu = self._gpu_factory()
                except Exception as error:
                    self._disabled = 'init-' + type(error).__name__
            if self._gpu is not None and self._disabled is None:
                try:
                    rgb = self._gpu.blur_bgr(image, radius)
                    if rgb.shape != image.shape or rgb.dtype != np.uint8:
                        raise ValueError('invalid GPU render')
                    gpu_ms = float(self._gpu.last_gpu_ms)
                    if not math.isfinite(gpu_ms) or gpu_ms < 0:
                        raise ValueError('invalid GPU timing')
                    self.backend, self.device = 'opencl-gpu', self._gpu.device
                    self.gpu_ms = gpu_ms
                    return np.ascontiguousarray(rgb)
                except Exception as error:
                    self._disabled = 'render-' + type(error).__name__
                    self._release_gpu()
            self.fallback = self._disabled
        return box_obscure_bgr(image, radius)

    def _release_gpu(self):
        gpu = self._gpu
        if gpu is not None:
            try:
                gpu.close()
            except Exception as error:
                self._close_error = type(error).__name__
                self._disabled = self._disabled or 'release-' + self._close_error
            else:
                self._gpu = None
                self._close_error = None

    def close(self):
        self._release_gpu()
        if self._close_error is not None:
            raise RuntimeError('GPU release failed: ' + self._close_error)


@dataclass(frozen=True)
class BlurRequest:
    sequence: int
    geometry: tuple
    crops: tuple  # (physical xywh, owned BGR source) pairs
    radius: int | None = None
    created_at: float | None = None


@dataclass(frozen=True)
class BlurResult:
    sequence: int
    geometry: tuple
    crops: tuple  # (physical xywh, owned source, rendered RGB) triples
    elapsed_ms: float = 0.0
    error: str | None = None
    radius: int | None = None
    backend: str = 'none'
    device: str = ''
    gpu_ms: float = 0.0
    fallback: str | None = None
    created_at: float | None = None


class BlurWorker:
    """One active request, one replacement pending request and one result."""
    def __init__(self, render=None, engine_factory=BoxBlurEngine):
        self._render = render
        self._engine_factory = engine_factory
        self._close_error = None
        self._condition = threading.Condition()
        self._pending = None
        self._completed = None
        self._generation = 0
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name='mask-blur', daemon=True)
        self._thread.start()

    @property
    def queued_count(self):
        with self._condition:
            return int(self._pending is not None)

    @property
    def alive(self):
        return self._thread.is_alive()

    def submit(self, request):
        with self._condition:
            if self._stopped:
                return False
            self._pending = (self._generation, request)
            self._condition.notify()
            return True

    def poll(self):
        with self._condition:
            result, self._completed = self._completed, None
            return result

    def cancel(self):
        with self._condition:
            self._generation += 1
            self._pending = self._completed = None

    def close(self, timeout=2.0):
        with self._condition:
            self._stopped = True
            self._generation += 1
            self._pending = self._completed = None
            self._condition.notify_all()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError('mask worker did not stop')
        if self._close_error is not None:
            raise RuntimeError('mask GPU release failed: ' + self._close_error)

    def _run(self):
        try:
            self._run_requests()
        finally:
            # _run_requests sets the session only on the owned worker thread.
            engine = getattr(self, '_engine', None)
            if engine is not None:
                # A driver may report a transient release error. Both attempts
                # stay on the owner thread; persistent failure blocks restart.
                for attempt in range(2):
                    try:
                        engine.close()
                    except Exception as error:
                        self._close_error = type(error).__name__
                    else:
                        self._engine = None
                        self._close_error = None
                        break

    def _run_requests(self):
        self._engine = None
        while True:
            with self._condition:
                while self._pending is None and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                generation, request = self._pending
                self._pending = None
            start = time.perf_counter()
            try:
                crops, abandoned = [], False
                backends, devices, fallbacks, gpu_ms = set(), set(), set(), 0.0
                for box, source in request.crops:
                    with self._condition:
                        abandoned = self._stopped or generation != self._generation
                    if abandoned:
                        break
                    if self._render is not None:
                        rendered = self._render(source)
                        backends.add('custom')
                    elif request.radius is not None:
                        if self._engine is None:
                            self._engine = self._engine_factory()
                        rendered = self._engine.render_bgr(source, request.radius)
                        backends.add(self._engine.backend)
                        if self._engine.device:
                            devices.add(self._engine.device)
                        if self._engine.fallback:
                            fallbacks.add(self._engine.fallback)
                        gpu_ms += self._engine.gpu_ms
                    else:
                        rendered = obscure_bgr(source)
                        backends.add('cpu-legacy')
                    crops.append((box, source, rendered))
                result = None if abandoned else BlurResult(
                    request.sequence, request.geometry, tuple(crops),
                    (time.perf_counter()-start)*1000, radius=request.radius,
                    backend=next(iter(backends)) if len(backends) == 1 else 'mixed',
                    device='; '.join(sorted(devices)), gpu_ms=gpu_ms,
                    fallback='; '.join(sorted(fallbacks)) or None,
                    created_at=request.created_at)
            except Exception as error:
                # Never retain traceback/image data or put content into messages.
                result = BlurResult(request.sequence, request.geometry, (),
                                    (time.perf_counter()-start)*1000, type(error).__name__,
                                    request.radius, created_at=request.created_at)
            with self._condition:
                if result is not None and not self._stopped and generation == self._generation:
                    self._completed = result
            # An idle worker must not retain its last screenshot crops.
            del request, result
            if 'crops' in locals():
                del crops
            # Loop targets otherwise retain the final crop while waiting.
            if 'source' in locals():
                del source
            if 'rendered' in locals():
                del rendered


class BlurCache:
    """Qt-thread coordinator; returns validated RGB regions and dark fallbacks."""
    MAX_BRIDGE_SECONDS = .250
    def __init__(self, worker=None, clock=time.monotonic, radius=None):
        if radius is not None and (type(radius) is not int or radius < 0):
            raise ValueError('invalid box radius')
        self.worker = worker or BlurWorker()
        self.radius = radius
        self._clock = clock
        self._ready = {}
        self._submitted = None
        self._sequence = 0
        self._minimum_sequence = 1
        self._closed = False
        self._retry_at = 0.0
        self.last_error = None
        self.last_elapsed_ms = None
        self.backend, self.device = 'none', ''
        self.gpu_ms, self.fallback = 0.0, None
        self._image_shape = None
        self._geometry = None

    @staticmethod
    def _matches(image, box, source):
        x, y, width, height = box
        current = image[y:y+height, x:x+width]
        return source.shape == current.shape and np.array_equal(source, current)

    def clear(self):
        self.worker.cancel()
        self._ready.clear()
        self._submitted = None
        self._retry_at = 0.0
        self.last_error = None
        self.last_elapsed_ms = None
        self.backend, self.device = 'none', ''
        self.gpu_ms, self.fallback = 0.0, None
        self._image_shape = None
        self._geometry = None
        self._minimum_sequence = self._sequence+1

    def set_radius(self, radius):
        if radius is not None and (type(radius) is not int or radius < 0):
            raise ValueError('invalid box radius')
        if radius != self.radius:
            # Keep the worker's GPU session, but never reuse weaker/older pixels
            # after changing the requested strength.
            self.clear()
            self.radius = radius

    def close(self):
        self._closed = True
        self.clear()
        self.worker.close()

    def update(self, boxes, image):
        """Always poll, including when geometry and capture identity repeat."""
        boxes = tuple(boxes)
        if self._closed or image is None or not boxes:
            self.clear()
            return [], list(boxes)
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            self.clear()
            raise ValueError('mask image must be uint8 BGR')
        height, width = image.shape[:2]
        if any(len(box) != 4 or any(type(v) is not int for v in box)
               or box[0] < 0 or box[1] < 0 or box[2] <= 0 or box[3] <= 0
               or box[0]+box[2] > width or box[1]+box[3] > height
               for box in boxes):
            self.clear()
            raise ValueError('invalid mask crop')
        if self._image_shape is not None and self._image_shape != image.shape:
            self.clear()
        if self._geometry is not None and self._geometry != boxes:
            self.clear()
        self._image_shape = image.shape
        self._geometry = boxes
        now = self._clock()
        result = self.worker.poll()
        if result is not None:
            if self._submitted is not None and result.sequence == self._submitted.sequence:
                self._submitted = None
            if (self._minimum_sequence <= result.sequence <= self._sequence
                    and result.geometry == boxes and result.radius == self.radius):
                self.last_elapsed_ms = result.elapsed_ms
                self.last_error = result.error
                self.backend, self.device = result.backend, result.device
                self.gpu_ms, self.fallback = result.gpu_ms, result.fallback
                if result.error is not None:
                    self._retry_at = self._clock()+1.0
                else:
                    self._retry_at = 0.0
                    for box, source, rendered in result.crops:
                        fresh = (result.created_at is not None
                                 and 0 <= now-result.created_at <= self.MAX_BRIDGE_SECONDS)
                        matches = box in boxes and self._matches(image, box, source)
                        if box in boxes and (matches or fresh):
                            if rendered.shape != source.shape or rendered.dtype != np.uint8:
                                self.last_error = 'InvalidRender'
                                self._retry_at = self._clock()+1.0
                                continue
                            self._ready[box] = (source, rendered, now if matches else result.created_at)
        # A completed RGB patch is completely opaque: while its next frame is
        # rendered it covers, rather than reveals, the changed underlying text.
        # Never bridge different geometry, strength, or older captured content.
        validated = {}
        for box, cached in self._ready.items():
            if box not in boxes:
                continue
            if self._matches(image, box, cached[0]):
                validated[box] = (cached[0], cached[1], now)
            elif (cached[2] is not None
                  and 0 <= now-cached[2] <= self.MAX_BRIDGE_SECONDS):
                validated[box] = cached
        self._ready = validated
        ready = [(box, self._ready[box][1]) for box in boxes if box in self._ready]
        pending = [box for box in boxes if box not in self._ready]
        dirty = [box for box in boxes if box not in self._ready
                 or not self._matches(image, box, self._ready[box][0])]
        if not dirty:
            if self._submitted is not None:
                self.worker.cancel()
                self._submitted = None
            return ready, []
        same_pending = (self._submitted is not None and self._submitted.geometry == boxes
                        and tuple(box for box, _ in self._submitted.crops) == tuple(dirty)
                        and all(self._matches(image, box, source)
                                for box, source in self._submitted.crops))
        if not same_pending and self._clock() >= self._retry_at:
            # Copy only protected crops, never the full capture for a small mask.
            crops = []
            for box in dirty:
                source = np.array(image[box[1]:box[1]+box[3], box[0]:box[0]+box[2]],
                                  copy=True, order='C')
                source.flags.writeable = False
                crops.append((box, source))
            self._sequence += 1
            request = BlurRequest(self._sequence, boxes, tuple(crops), self.radius, now)
            if self.worker.submit(request):
                self._submitted = request
        return ready, pending
