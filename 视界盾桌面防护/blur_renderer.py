"""Bounded, in-memory mask rendering. This module does not import Qt or models.

The caller owns the current immutable capture. Workers receive only owned mask
crops; completed crops are usable only after exact source/geometry validation.
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


@dataclass(frozen=True)
class BlurRequest:
    sequence: int
    geometry: tuple
    crops: tuple  # (physical xywh, owned BGR source) pairs
    radius: int | None = None


@dataclass(frozen=True)
class BlurResult:
    sequence: int
    geometry: tuple
    crops: tuple  # (physical xywh, owned source, rendered RGB) triples
    elapsed_ms: float = 0.0
    error: str | None = None
    radius: int | None = None


class BlurWorker:
    """One active request, one replacement pending request and one result."""
    def __init__(self, render=None):
        self._render = render
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

    def _run(self):
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
                for box, source in request.crops:
                    with self._condition:
                        abandoned = self._stopped or generation != self._generation
                    if abandoned:
                        break
                    if self._render is not None:
                        rendered = self._render(source)
                    elif request.radius is not None:
                        rendered = box_obscure_bgr(source, request.radius)
                    else:
                        rendered = obscure_bgr(source)
                    crops.append((box, source, rendered))
                result = None if abandoned else BlurResult(
                    request.sequence, request.geometry, tuple(crops),
                    (time.perf_counter()-start)*1000, radius=request.radius)
            except Exception as error:
                # Never retain traceback/image data or put content into messages.
                result = BlurResult(request.sequence, request.geometry, (),
                                    (time.perf_counter()-start)*1000, type(error).__name__,
                                    request.radius)
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
    def __init__(self, worker=None, clock=time.monotonic, radius=None):
        if radius is not None and (type(radius) is not int or radius < 0):
            raise ValueError('invalid box radius')
        self.worker = worker or BlurWorker()
        self.radius = radius
        self._clock = clock
        self._ready = {}
        self._submitted = None
        self._sequence = 0
        self._closed = False
        self._retry_at = 0.0
        self.last_error = None
        self.last_elapsed_ms = None
        self._image_shape = None

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
        self._image_shape = None

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
        self._image_shape = image.shape
        result = self.worker.poll()
        if result is not None:
            if self._submitted is not None and result.sequence == self._submitted.sequence:
                self._submitted = None
            if result.geometry == boxes and result.radius == self.radius:
                self.last_elapsed_ms = result.elapsed_ms
                self.last_error = result.error
                if result.error is not None:
                    self._retry_at = self._clock()+1.0
                else:
                    self._retry_at = 0.0
                    for box, source, rendered in result.crops:
                        if box in boxes and self._matches(image, box, source):
                            if rendered.shape != source.shape or rendered.dtype != np.uint8:
                                self.last_error = 'InvalidRender'
                                self._retry_at = self._clock()+1.0
                                continue
                            self._ready[box] = (source, rendered)
        # Image-object equality is deliberately insufficient: even one changed
        # pixel invalidates that region, and unrelated changes keep it reusable.
        self._ready = {box: cached for box, cached in self._ready.items()
                       if box in boxes and self._matches(image, box, cached[0])}
        ready = [(box, self._ready[box][1]) for box in boxes if box in self._ready]
        pending = [box for box in boxes if box not in self._ready]
        if not pending:
            if self._submitted is not None:
                self.worker.cancel()
                self._submitted = None
            return ready, []
        same_pending = (self._submitted is not None and self._submitted.geometry == boxes
                        and tuple(box for box, _ in self._submitted.crops) == tuple(pending)
                        and all(self._matches(image, box, source)
                                for box, source in self._submitted.crops))
        if not same_pending and self._clock() >= self._retry_at:
            # Copy only protected crops, never the full capture for a small mask.
            crops = []
            for box in pending:
                source = np.array(image[box[1]:box[1]+box[3], box[0]:box[0]+box[2]],
                                  copy=True, order='C')
                source.flags.writeable = False
                crops.append((box, source))
            self._sequence += 1
            request = BlurRequest(self._sequence, boxes, tuple(crops), self.radius)
            if self.worker.submit(request):
                self._submitted = request
        return ready, pending
