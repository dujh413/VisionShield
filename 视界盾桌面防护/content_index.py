"""按区域验证结果时效；画面局部变化不会抹掉其他稳定区域的敏感框。"""
import math
import numpy as np
from sensitive_rules import detect, rect_of


def padded_rect(polygon, shape, padding=8):
    x,y,w,h = rect_of(polygon)
    return (max(0,math.floor(x)-padding), max(0,math.floor(y)-padding),
            min(shape[1],math.ceil(x+w)+padding), min(shape[0],math.ceil(y+h)+padding))


def same_region(first, second, rectangle):
    x1,y1,x2,y2 = rectangle
    return first.shape==second.shape and np.array_equal(first[y1:y2,x1:x2],second[y1:y2,x1:x2])


class ContentIndex:
    def __init__(self, tile=64):
        self.tile = tile
        self.image, self.unknown = None, None
        self.hits = []

    def tiles(self, mask):
        h,w = mask.shape
        t = self.tile
        padded = np.pad(mask, ((0,(-h)%t),(0,(-w)%t)))
        return padded.reshape(padded.shape[0]//t,t,padded.shape[1]//t,t).any(axis=(1,3))

    def dirty_rect(self, rectangle):
        x1,y1,x2,y2 = rectangle
        self.unknown[y1//self.tile:math.ceil(y2/self.tile),x1//self.tile:math.ceil(x2/self.tile)] = True

    def update(self, image):
        if self.image is None or self.image.shape != image.shape:
            self.unknown = self.tiles(np.ones(image.shape[:2], dtype=bool))
            self.hits = []
        else:
            self.unknown |= self.tiles(np.any(self.image!=image, axis=2))
            kept = []
            for hit in self.hits:
                rect = padded_rect(hit['polygon'],image.shape)
                if same_region(self.image,image,rect):
                    kept.append(hit)
                else:
                    # 单个数字改变时，整条原敏感行临时覆盖，避免露出旧前缀。
                    self.dirty_rect(rect)
            self.hits = kept
        self.image = image

    def accept(self, source, lines, semantic=None):
        if self.image is None or source.shape != self.image.shape:
            return False
        changed = self.tiles(np.any(source!=self.image, axis=2))
        self.unknown &= changed
        accepted = []
        for hit in detect(lines,semantic):
            rect = padded_rect(hit['polygon'],self.image.shape)
            if same_region(source,self.image,rect):
                accepted.append(hit)
            else:
                self.dirty_rect(rect)
        self.hits = accepted
        return bool((~changed).any())

    def pending_rectangles(self):
        if self.unknown is None:
            return []
        height,width = self.image.shape[:2]
        rectangles = []
        active = {}
        for row in range(self.unknown.shape[0]):
            columns = np.flatnonzero(self.unknown[row])
            if not len(columns):
                active = {}
                continue
            runs = np.split(columns,np.flatnonzero(np.diff(columns)>1)+1)
            next_active = {}
            for run in runs:
                x,y = int(run[0])*self.tile,row*self.tile
                w,h = min(width-x,(int(run[-1])-int(run[0])+1)*self.tile),min(self.tile,height-y)
                key = (x,w)
                if key in active:
                    index = active[key]
                    ox,oy,ow,oh = rectangles[index]
                    rectangles[index] = (ox,oy,ow,oh+h)
                else:
                    index = len(rectangles)
                    rectangles.append((x,y,w,h))
                next_active[key] = index
            active = next_active
        return rectangles
