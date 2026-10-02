"""精确像素差分；仅保留变化区之外的文字，变化过大回退整屏。"""
import math
import numpy as np


def bounds(line):
    points = line['polygon']
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def changed_box(previous, current, lines, padding=64):
    """返回覆盖全部变化及相交旧文字行的框；None表示完全相同。"""
    mask = np.any(previous != current, axis=2)
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(rows):
        return None
    columns = np.flatnonzero(mask.any(axis=0))
    height, width = current.shape[:2]
    box = (max(0,int(columns[0])-padding), max(0,int(rows[0])-padding),
           min(width,int(columns[-1])+1+padding), min(height,int(rows[-1])+1+padding))
    # 一个改变字符可能属于长行：将整行纳入重新识别，不沿用旧前缀。
    while True:
        expanded = box
        for line in lines:
            rect = bounds(line)
            if intersects(box, rect):
                expanded = (max(0,min(expanded[0],math.floor(rect[0])-padding)),
                            max(0,min(expanded[1],math.floor(rect[1])-padding)),
                            min(width,max(expanded[2],math.ceil(rect[2])+padding)),
                            min(height,max(expanded[3],math.ceil(rect[3])+padding)))
        if expanded == box:
            return box
        box = expanded


class IncrementalOCR:
    def __init__(self, max_area=0.35, max_partial=8):
        self.image, self.lines = None, []
        self.partial_updates = 0
        self.max_area, self.max_partial = max_area, max_partial

    def run(self, image, recognize):
        """recognize(image,preserve_scale)返回图像内文字框；不缓存历史帧。"""
        mode, ratio = 'full', 1.0
        compatible = self.image is not None and self.image.shape == image.shape
        if compatible:
            box = changed_box(self.image, image, self.lines)
            if box is None:
                self.image = image
                return self.lines, {'mode':'cached', 'area_ratio':0.0}
            x1,y1,x2,y2 = box
            ratio = (x2-x1)*(y2-y1)/(image.shape[0]*image.shape[1])
            if ratio <= self.max_area and self.partial_updates < self.max_partial:
                kept = [line for line in self.lines if not intersects(bounds(line),box)]
                fresh = recognize(image[y1:y2,x1:x2].copy(), True)
                shifted = [{**line,'polygon':[[float(x)+x1,float(y)+y1] for x,y in line['polygon']]}
                           for line in fresh]
                lines = kept+shifted
                mode = 'partial'
                self.partial_updates += 1
            else:
                lines = recognize(image, False)
                self.partial_updates = 0
                ratio = 1.0
        else:
            lines = recognize(image, False)
            self.partial_updates = 0
        # 更新成功后才替换缓存，避免半成品结果被复用。
        self.image, self.lines = image, lines
        return lines, {'mode':mode,'area_ratio':ratio}
