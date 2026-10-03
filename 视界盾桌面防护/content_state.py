"""Region-valid OCR cache and capture freshness, independent of Qt."""
import math
import numpy as np
from region_geometry import bounds, changed_boxes, intersects, merge_boxes, rectangles, area_ratio
from sensitive_rules import detect, nearby, rect_of


class ContentState:
    def __init__(self, capture_timeout=1.0, result_timeout=10.0, refresh_interval=5.0):
        self.capture_timeout, self.result_timeout = capture_timeout, result_timeout
        self.refresh_interval = refresh_interval
        self.latest = self.result = None
        self.result_frame_id = -1
        self.hits, self.unknown, self.valid_lines = [], [], 0
        self.full_unknown = True
        self.last_submitted_image = self.last_submitted_at = None

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
                or image.shape != self.latest.image.shape):
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
        self.result = {**item, 'unknown_regions': unknown, 'hits': detect(lines, semantic)}
        self.result_frame_id = frame_id
        self._revalidate()
        return True

    def _revalidate(self):
        self.hits, self.unknown, self.valid_lines = [], [], 0
        self.full_unknown = True
        if self.latest is None or self.result is None or self.result['image'].shape != self.latest.image.shape:
            return
        changes = changed_boxes(self.result['image'], self.latest.image, padding=6)
        lines = self.result['lines']
        unresolved = self.result['unknown_regions'] + changes
        affected = [i for i, line in enumerate(lines) if any(intersects(bounds(line), b) for b in unresolved)]
        dependent = set(affected)
        change_lines = [{'polygon': [[a, b], [c, b], [c, d], [a, d]]} for a, b, c, d in changes]
        for i, line in enumerate(lines):
            if (any(nearby(line, lines[j]) for j in affected)
                    or any(nearby(line, region) for region in change_lines)):
                dependent.add(i)
        self.unknown = merge_boxes(self.result['unknown_regions'] + changes
                                   + [bounds(lines[i]) for i in dependent])
        # Merged rectangles can touch more lines. Cover each entire discarded line,
        # rather than removing its sensitive hit while exposing the remaining text.
        while True:
            additional = {i for i, line in enumerate(lines) if i not in dependent
                          and any(intersects(bounds(line), box) for box in self.unknown)}
            if not additional:
                break
            dependent.update(additional)
            self.unknown = merge_boxes(self.unknown + [bounds(lines[i]) for i in additional])
        self.hits = [hit for hit in self.result['hits'] if hit['line_index'] not in dependent
                     and not any(intersects(bounds(hit), b) for b in self.unknown)]
        self.valid_lines = sum(i not in dependent and not any(intersects(bounds(line), b) for b in self.unknown)
                               for i, line in enumerate(lines))
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
