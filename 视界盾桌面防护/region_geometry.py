"""Exact image differences and physical-pixel rectangles."""
import math
import numpy as np


def bounds(line):
    points = np.asarray(line['polygon'], dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('Invalid text polygon')
    return tuple(float(v) for v in (points[:, 0].min(), points[:, 1].min(),
                                    points[:, 0].max(), points[:, 1].max()))


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def merge_boxes(boxes):
    merged = []
    for box in boxes:
        box, i = tuple(box), 0
        while i < len(merged):
            other = merged[i]
            if intersects(box, other):
                box = (min(box[0], other[0]), min(box[1], other[1]),
                       max(box[2], other[2]), max(box[3], other[3]))
                merged.pop(i)
                i = 0
            else:
                i += 1
        merged.append(box)
    return sorted(merged)


def padded(box, width, height, padding):
    return (max(0, math.floor(box[0]) - padding), max(0, math.floor(box[1]) - padding),
            min(width, math.ceil(box[2]) + padding), min(height, math.ceil(box[3]) + padding))


def changed_boxes(previous, current, lines=(), padding=64, tile=64):
    if previous is None or previous.shape != current.shape:
        return [(0, 0, current.shape[1], current.shape[0])]
    mask = np.any(previous != current, axis=2)
    height, width = mask.shape
    boxes = []
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            rows, cols = np.nonzero(mask[y:y + tile, x:x + tile])
            if len(rows):
                box = (x + int(cols.min()), y + int(rows.min()),
                       x + int(cols.max()) + 1, y + int(rows.max()) + 1)
                boxes.append(padded(box, width, height, padding))
    boxes = merge_boxes(boxes)
    old_lines = [bounds(line) for line in lines]
    while boxes:
        expanded = []
        for box in boxes:
            for rect in old_lines:
                if intersects(box, rect):
                    extra = padded(rect, width, height, padding)
                    box = (min(box[0], extra[0]), min(box[1], extra[1]),
                           max(box[2], extra[2]), max(box[3], extra[3]))
            expanded.append(box)
        expanded = merge_boxes(expanded)
        if expanded == boxes:
            break
        boxes = expanded
    return boxes


def area_ratio(boxes, image):
    return sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes) / (image.shape[0] * image.shape[1])


def rectangles(boxes):
    return [(x1, y1, x2 - x1, y2 - y1) for x1, y1, x2, y2 in boxes]
