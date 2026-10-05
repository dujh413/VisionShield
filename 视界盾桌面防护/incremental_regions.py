"""Bounded exact pixel differences and complete-line OCR crop geometry."""
import math

import numpy as np


def difference_mask(previous, current):
    """Exact BGR pixel comparison without a full H×W×3 boolean temporary."""
    if previous.shape != current.shape or current.ndim != 3 or current.shape[2] != 3:
        raise ValueError('expected matching three-channel images')
    mask = np.not_equal(previous[:, :, 0], current[:, :, 0])
    scratch = np.empty_like(mask)
    for channel in (1, 2):
        np.not_equal(previous[:, :, channel], current[:, :, channel], out=scratch)
        np.logical_or(mask, scratch, out=mask)
    return mask


def bounds(line):
    points = np.asarray(line['polygon'], dtype=float)
    if points.ndim != 2 or points.shape[0] < 3 or points.shape[1] != 2:
        raise ValueError('invalid OCR polygon')
    if not np.isfinite(points).all():
        raise ValueError('nonfinite OCR polygon')
    rectangle = (float(points[:, 0].min()), float(points[:, 1].min()),
                 float(points[:, 0].max()), float(points[:, 1].max()))
    if rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]:
        raise ValueError('empty OCR polygon')
    return rectangle


def intersects(first, second):
    """Positive-area intersection of half-open physical-pixel rectangles."""
    return (first[0] < second[2] and second[0] < first[2] and
            first[1] < second[3] and second[1] < first[3])


def touches(first, second):
    """Crop merging may include shared edges without invalidating text there."""
    return (first[0] <= second[2] and second[0] <= first[2] and
            first[1] <= second[3] and second[1] <= first[3])


def contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1] and
            outer[2] >= inner[2] and outer[3] >= inner[3])


def padded(rectangle, shape, padding):
    height, width = shape[:2]
    return (max(0, math.floor(rectangle[0]) - padding),
            max(0, math.floor(rectangle[1]) - padding),
            min(width, math.ceil(rectangle[2]) + padding),
            min(height, math.ceil(rectangle[3]) + padding))


def merge_boxes(boxes):
    """Merge touching rectangles to a fixed point; outputs never overlap."""
    merged = []
    for rectangle in sorted(set(boxes)):
        if rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]:
            continue
        pending = rectangle
        while True:
            remaining = []
            grew = False
            for other in merged:
                if touches(pending, other):
                    pending = (min(pending[0], other[0]), min(pending[1], other[1]),
                               max(pending[2], other[2]), max(pending[3], other[3]))
                    grew = True
                else:
                    remaining.append(other)
            merged = remaining
            if not grew:
                break
        merged.append(pending)
    return sorted(merged)


def area_ratio(boxes, shape):
    return sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in boxes) / (shape[0] * shape[1])


def changed_regions(previous, current, lines, padding=64, tile_size=64, max_tiles=256):
    """Return bounded exact changes in physical-pixel xyxy coordinates.

    No downsampling or intensity threshold is used, including for one changed
    character. A busy screen falls back to the full image before unbounded crop
    construction. Crops contain entire intersecting old lines. Only directly
    changed lines receive the full context padding: applying it recursively to
    every adjacent line would join an otherwise unchanged whole document.
    """
    if current.ndim != 3 or current.shape[2] != 3 or not current.shape[0] or not current.shape[1]:
        raise ValueError('expected a nonempty three-channel image')
    height, width = current.shape[:2]
    if previous.shape != current.shape:
        return [(0, 0, width, height)]
    if tile_size <= 0 or max_tiles <= 0 or padding < 0:
        raise ValueError('invalid crop bounds')
    mask = difference_mask(previous, current)
    occupied = np.logical_or.reduceat(mask, np.arange(0, height, tile_size), axis=0)
    occupied = np.logical_or.reduceat(occupied, np.arange(0, width, tile_size), axis=1)
    cells = np.argwhere(occupied)
    if not len(cells):
        return []
    if len(cells) > max_tiles:
        return [(0, 0, width, height)]

    boxes = []
    for tile_y, tile_x in cells:
        x, y = int(tile_x) * tile_size, int(tile_y) * tile_size
        rows, columns = np.nonzero(mask[y:y + tile_size, x:x + tile_size])
        rectangle = (x + int(columns.min()), y + int(rows.min()),
                     x + int(columns.max()) + 1, y + int(rows.max()) + 1)
        boxes.append(padded(rectangle, current.shape, padding))

    line_boxes = [bounds(line) for line in lines]
    for rectangle in line_boxes:
        x1, y1, x2, y2 = padded(rectangle, current.shape, 0)
        if x1 < x2 and y1 < y2 and mask[y1:y2, x1:x2].any():
            boxes.append(padded(rectangle, current.shape, padding))

    boxes = merge_boxes(boxes)
    # Four pixels around indirectly intersecting lines preserve their complete
    # glyphs without repeatedly growing a 64-pixel halo through nearby rows.
    contexts = [padded(rectangle, current.shape, 4) for rectangle in line_boxes]
    while True:
        expanded = []
        for box in boxes:
            result = box
            for rectangle, context in zip(line_boxes, contexts):
                if intersects(box, rectangle):
                    result = (min(result[0], context[0]), min(result[1], context[1]),
                              max(result[2], context[2]), max(result[3], context[3]))
            expanded.append(result)
        expanded = merge_boxes(expanded)
        if expanded == boxes:
            return boxes
        boxes = expanded
