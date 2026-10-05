"""精确多区域差分；完整文字行重新识别，失败不提交半成品缓存。"""
import time

from incremental_regions import (area_ratio, bounds, changed_regions, contains,
                                 intersects, merge_boxes, padded)


def changed_box(previous, current, lines, padding=64):
    """兼容单框调用方；新识别流程使用 changed_regions，None表示相同。"""
    boxes = changed_regions(previous, current, lines, padding=padding)
    if not boxes:
        return None
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def uncertain_regions(lines, shape):
    """Empty/low-confidence OCR must retain explicit unknown coverage."""
    uncertain = []
    for line in lines:
        rectangle = bounds(line)
        clipped = padded(rectangle, shape, 0)
        if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
            raise ValueError('OCR polygon outside image')
        text, confidence = line.get('text', ''), float(line.get('confidence', 0.0))
        if not isinstance(text, str) or not 0.0 <= confidence <= 1.0:
            raise ValueError('invalid OCR text or confidence')
        if not text.strip() or confidence < 0.65:
            uncertain.append(padded(rectangle, shape, 4))
    return uncertain


def has_readable_text(lines):
    return any(line.get('text', '').strip() and float(line.get('confidence', 0.0)) >= 0.65
               for line in lines)


class IncrementalOCR:
    def __init__(self, max_area=0.35, max_partial=8, max_regions=4,
                 full_refresh_s=15.0, clock=None):
        self.image, self.lines = None, []
        self.unknown_regions = []
        self.partial_updates = 0
        self.max_area, self.max_partial = max_area, max_partial
        self.max_regions, self.full_refresh_s = max_regions, full_refresh_s
        self.clock = clock or time.monotonic
        self.last_full_at = None

    def run(self, image, recognize):
        """recognize(image,preserve_scale)返回文字框；调用方不得修改帧数组。"""
        if image.ndim != 3 or image.shape[2] != 3 or not image.shape[0] or not image.shape[1]:
            raise ValueError('expected a nonempty three-channel image')
        started = self.clock()
        mode, ratio, regions_count = 'full', 1.0, 1
        compatible = self.image is not None and self.image.shape == image.shape
        refresh_due = (self.last_full_at is None or
                       started - self.last_full_at >= self.full_refresh_s)
        boxes = changed_regions(self.image, image, self.lines) if compatible and not refresh_due else []
        diff_ms = (self.clock() - started) * 1000
        if compatible and not refresh_due:
            if not boxes:
                self.image = image
                return self.lines, {'mode': 'cached', 'area_ratio': 0.0,
                                    'regions_count': 0, 'diff_ms': diff_ms,
                                    'unknown_regions': list(self.unknown_regions)}
            ratio = area_ratio(boxes, image.shape)
            if (ratio <= self.max_area and len(boxes) <= self.max_regions and
                    self.partial_updates < self.max_partial):
                lines = [line for line in self.lines
                         if not any(intersects(bounds(line), box) for box in boxes)]
                unknown = list(self.unknown_regions)
                for x1, y1, x2, y2 in boxes:
                    box = (x1, y1, x2, y2)
                    fresh = list(recognize(image[y1:y2, x1:x2].copy(), True))
                    # Validate all crops before committing any state. A failure
                    # on the second crop must not retain the first crop result.
                    uncertain = uncertain_regions(fresh, (y2 - y1, x2 - x1))
                    if has_readable_text(fresh):
                        unknown = [old for old in unknown if not contains(box, old)]
                    else:
                        unknown.append(box)
                    unknown.extend((ux1 + x1, uy1 + y1, ux2 + x1, uy2 + y1)
                                   for ux1, uy1, ux2, uy2 in uncertain)
                    lines.extend({**line, 'polygon': [[float(x) + x1, float(y) + y1]
                                                     for x, y in line['polygon']]}
                                 for line in fresh)
                mode = 'partial'
                regions_count = len(boxes)
                partial_updates = self.partial_updates + 1
            else:
                lines = list(recognize(image, False))
                unknown = uncertain_regions(lines, image.shape)
                if not has_readable_text(lines):
                    unknown.append((0, 0, image.shape[1], image.shape[0]))
                partial_updates = 0
                ratio = 1.0
        else:
            lines = list(recognize(image, False))
            unknown = uncertain_regions(lines, image.shape)
            if not has_readable_text(lines):
                unknown.append((0, 0, image.shape[1], image.shape[0]))
            partial_updates = 0
        # 更新成功后才替换缓存，避免半成品结果被复用。
        self.image, self.lines = image, lines
        self.partial_updates = partial_updates
        self.unknown_regions = merge_boxes(unknown)
        if mode == 'full':
            self.last_full_at = self.clock()
        return lines, {'mode': mode, 'area_ratio': ratio,
                       'regions_count': regions_count, 'diff_ms': diff_ms,
                       'unknown_regions': list(self.unknown_regions)}
