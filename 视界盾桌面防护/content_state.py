"""Region-valid OCR cache and capture freshness, independent of Qt."""
import math
import numpy as np
from content_index import ContentIndex, _ExactDifference, line_context
from incremental_regions import bounds, intersects, merge_boxes, regions_from_mask
from region_geometry import rectangles, area_ratio
from sensitive_rules import detect, rect_of


class ContentState:
    def __init__(self, capture_timeout=1.0, result_timeout=10.0, refresh_interval=5.0):
        self.capture_timeout, self.result_timeout = capture_timeout, result_timeout
        self.refresh_interval = refresh_interval
        self.latest = self.result = None
        self.result_frame_id = -1
        self.hits, self.unknown, self.valid_lines = [], [], 0
        self.full_unknown = True
        self.last_submitted_image = self.last_submitted_at = None
        self._geometry = ContentIndex()
        self._line_bounds, self._contexts, self._dependencies = [], [], []

    def observe(self, frame):
        if self.latest is None or frame.frame_id > self.latest.frame_id:
            self.latest = frame
            self._revalidate()

    def accept(self, item, now, semantic=None):
        if self.latest is None:
            return False
        captured, frame_id, image = item.get('captured_at'), item.get('frame_id'), item.get('image')
        if (not isinstance(captured, (int, float)) or not math.isfinite(captured)
                or not 0 <= now - captured <= self.result_timeout
                or type(frame_id) is not int or frame_id <= self.result_frame_id
                or frame_id > self.latest.frame_id or not isinstance(image, np.ndarray)
                or image.shape != self.latest.image.shape or image.ndim != 3
                or image.shape[2] != 3 or not image.shape[0] or not image.shape[1]):
            return False
        height, width = image.shape[:2]
        lines = item['lines']
        for line in lines:
            x1, y1, x2, y2 = bounds(line)
            score = line.get('confidence')
            if (not isinstance(line.get('text'), str) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or not 0 <= score <= 1
                    or not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height):
                raise ValueError('Invalid OCR text item')
        unknown = list(item.get('unknown_regions', []))
        for box in unknown:
            if (len(box) != 4 or not all(math.isfinite(float(v)) for v in box)
                    or not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
                raise ValueError('Invalid OCR coverage rectangle')
        if not lines and not unknown:
            unknown = [(0, 0, width, height)]
        # Geometry is stable across cached OCR results; classification always
        # uses the new text. One precise difference serves all ROI checks.
        contextual = self._geometry._with_context(lines, image.shape)
        line_bounds = [bounds(line) for line in contextual]
        contexts = [line_context(line, image.shape) for line in contextual]
        difference = _ExactDifference(image, self.latest.image, self._geometry.tile, self._geometry.tiles)
        dependencies = list(zip(line_bounds, contexts))
        if self.result is not None and self.result['image'].shape == image.shape:
            # A missed large label must not shrink the neighbouring value's
            # dependency in later cached results. Remove an old dependency only
            # when its source pixels and its complete coverage are confirmed.
            dependencies.extend((rectangle, context) for rectangle, context in self._dependencies
                                if difference.changed(context)
                                or any(intersects(context, box) for box in unknown))
        dependencies = list(dict.fromkeys(dependencies))
        hits = detect(contextual, semantic)
        self.result = {**item, 'lines': contextual, 'unknown_regions': unknown, 'hits': hits}
        self.result_frame_id = frame_id
        self._line_bounds, self._contexts, self._dependencies = line_bounds, contexts, dependencies
        self._revalidate(difference)
        return True

    def _revalidate(self, difference=None):
        self.hits, self.unknown, self.valid_lines = [], [], 0
        self.full_unknown = True
        if self.latest is None or self.result is None or self.result['image'].shape != self.latest.image.shape:
            return
        if difference is None:
            difference = _ExactDifference(self.result['image'], self.latest.image,
                                          self._geometry.tile, self._geometry.tiles)
        changes = (regions_from_mask(difference.mask, self.latest.image.shape, padding=6)
                   if difference.mask is not None else [])
        lines = self.result['lines']
        unresolved = self.result['unknown_regions'] + changes
        dependent = {i for i, context in enumerate(self._contexts)
                     if difference.changed(context) or any(intersects(context, box) for box in unresolved)}
        old_unknown = [rectangle for rectangle, context in self._dependencies
                       if difference.changed(context) or any(intersects(context, box) for box in unresolved)]
        self.unknown = merge_boxes(unresolved + old_unknown
                                   + [self._line_bounds[i] for i in dependent])
        # Merged rectangles can touch more lines. Cover each entire discarded line,
        # rather than removing its sensitive hit while exposing the remaining text.
        while True:
            additional = {i for i, rectangle in enumerate(self._line_bounds) if i not in dependent
                          and any(intersects(rectangle, box) for box in self.unknown)}
            if not additional:
                break
            dependent.update(additional)
            self.unknown = merge_boxes(self.unknown + [self._line_bounds[i] for i in additional])
        self.hits = [hit for hit in self.result['hits'] if hit['line_index'] not in dependent
                     and not any(intersects(self._line_bounds[hit['line_index']], b) for b in self.unknown)]
        self.valid_lines = sum(i not in dependent for i in range(len(lines)))
        self.full_unknown = area_ratio(self.unknown, self.latest.image) >= .6 or len(self.unknown) > 32

    def view(self, now):
        if self.latest is None or not 0 <= now - self.latest.captured_at <= self.capture_timeout:
            return {'full': True, 'rectangles': [], 'hits': [], 'coordinates_valid': False,
                    'coverage_complete': False, 'reason': '采集未就绪或已超时', 'capture_failed': True}
        if self.result is None or not 0 <= now - self.result['captured_at'] <= self.result_timeout:
            return {'full': True, 'rectangles': [], 'hits': [], 'coordinates_valid': False,
                    'coverage_complete': False, 'reason': '文字分析未完成或结果已过期', 'capture_failed': False}
        return {'full': self.full_unknown,
                'rectangles': [rect_of(h['polygon']) for h in self.hits] + rectangles(self.unknown),
                'hits': self.hits, 'coordinates_valid': not self.full_unknown,
                'coverage_complete': not self.unknown, 'unknown_regions': len(self.unknown),
                'valid_lines': self.valid_lines, 'reason': '变化区域临时保护' if self.unknown else '文字区域已分析',
                'capture_failed': False}

    def should_submit(self, now):
        if self.latest is None or not 0 <= now - self.latest.captured_at <= self.capture_timeout:
            return False
        if self.last_submitted_at is None:
            return True
        if now - self.last_submitted_at < .25:
            return False
        return (now - self.last_submitted_at >= self.refresh_interval
                or self.last_submitted_image.shape != self.latest.image.shape
                or not np.array_equal(self.last_submitted_image, self.latest.image))

    def mark_submitted(self, now):
        self.last_submitted_image, self.last_submitted_at = self.latest.image, now
