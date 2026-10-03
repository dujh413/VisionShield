"""Exact differences, multiple crops and conservative empty-result coverage."""
import time
from region_geometry import bounds, intersects, changed_boxes, area_ratio


def changed_box(previous, current, lines, padding=64):
    boxes = changed_boxes(previous, current, lines, padding)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


class IncrementalOCR:
    def __init__(self, max_area=0.35, max_partial=8, max_regions=4, full_refresh_s=15.0):
        self.image, self.lines, self.unknown_regions = None, [], []
        self.partial_updates = 0
        self.max_area, self.max_partial = max_area, max_partial
        self.max_regions, self.full_refresh_s = max_regions, full_refresh_s
        self.last_full_at = None

    def run(self, image, recognize):
        started = time.monotonic()
        compatible = self.image is not None and self.image.shape == image.shape
        boxes = changed_boxes(self.image, image, self.lines) if compatible else []
        diff_ms = (time.monotonic() - started) * 1000
        refresh_due = self.last_full_at is None or started - self.last_full_at >= self.full_refresh_s
        if compatible and not boxes and not refresh_due:
            return self.lines, {'mode': 'cached', 'area_ratio': 0.0, 'regions_count': 0,
                                'diff_ms': diff_ms, 'unknown_regions': self.unknown_regions}
        ratio = area_ratio(boxes, image) if boxes else 1.0
        partial = (compatible and bool(boxes) and not refresh_due and ratio <= self.max_area
                   and len(boxes) <= self.max_regions and self.partial_updates < self.max_partial)
        if partial:
            lines = [line for line in self.lines if not any(intersects(bounds(line), b) for b in boxes)]
            unknown = [b for b in self.unknown_regions if not any(
                crop[0] <= b[0] and crop[1] <= b[1] and crop[2] >= b[2] and crop[3] >= b[3] for crop in boxes)]
            for x1, y1, x2, y2 in boxes:
                fresh = recognize(image[y1:y2, x1:x2].copy(), True)
                lines.extend({**line, 'polygon': [[float(x) + x1, float(y) + y1]
                                                  for x, y in line['polygon']]} for line in fresh)
                if not fresh:
                    unknown.append((x1, y1, x2, y2))
            mode, next_partial = 'partial', self.partial_updates + 1
        else:
            lines = recognize(image, False)
            unknown = [] if lines else [(0, 0, image.shape[1], image.shape[0])]
            mode, ratio, next_partial = 'full', 1.0, 0
        self.image, self.lines, self.unknown_regions = image, lines, unknown
        self.partial_updates = next_partial
        if mode == 'full':
            self.last_full_at = started
        return lines, {'mode': mode, 'area_ratio': ratio, 'regions_count': len(boxes) if partial else 1,
                       'diff_ms': diff_ms, 'unknown_regions': unknown}

