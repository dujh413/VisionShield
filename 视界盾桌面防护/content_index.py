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


def context_rect(polygon, shape):
    # 标签和值可能分行。文字本身不变，也必须检查邻近上下文的时效。
    x,y,w,h = rect_of(polygon)
    horizontal,vertical = max(64,math.ceil(h*4)),max(64,math.ceil(h*3.5))
    return (max(0,math.floor(x)-horizontal),max(0,math.floor(y)-vertical),
            min(shape[1],math.ceil(x+w)+horizontal),min(shape[0],math.ceil(y+h)+vertical))


def with_context(lines, shape):
    if not lines:
        return []
    boxes = np.asarray([rect_of(line['polygon']) for line in lines])
    xs,ys,ws,hs = boxes.T
    result = []
    for line,(x,y,w,h) in zip(lines,boxes):
        heights = np.maximum(h,hs)
        linked = ((np.maximum(x,xs)-np.minimum(x+w,xs+ws)<=heights*4) &
                  (np.maximum(y,ys)-np.minimum(y+h,ys+hs)<=heights*2.5))
        x1,y1,x2,y2 = context_rect(line['polygon'],shape)
        # 使用与敏感规则相同的邻近关系，覆盖字号不同的标签和值。
        rectangle = (max(0,min(x1,math.floor(xs[linked].min())-8)),
                     max(0,min(y1,math.floor(ys[linked].min())-8)),
                     min(shape[1],max(x2,math.ceil((xs+ws)[linked].max())+8)),
                     min(shape[0],max(y2,math.ceil((ys+hs)[linked].max())+8)))
        result.append({**line,'_context':rectangle})
    return result


def line_context(line,shape):
    # dict.get 的默认参数也会执行，避免每次查询重新计算几何。
    rectangle = line.get('_context')
    return rectangle if rectangle is not None else context_rect(line['polygon'],shape)


class _ExactDifference:
    """一次精确差分，复用小型分块积分表和精确边缘查询。

    对整个 RGB 数组沿第三轴归约较慢；逐通道 OR 保持相同的逐像素语义。
    完整分块用积分表查询，边缘仅扫描差分掩码，不再反复比较源图。
    """
    def __init__(self, first, second, tile, tile_mask):
        self.height, self.width = second.shape[:2]
        self.tile = tile
        self.cache = {}
        self.mask = None
        if first is not second:
            mask = first[:, :, 0] != second[:, :, 0]
            for channel in range(1,second.shape[2]):
                np.logical_or(mask,first[:, :, channel] != second[:, :, channel],out=mask)
            self.tiles = tile_mask(mask)
            if self.tiles.any():
                self.mask = mask
        else:
            self.tiles = np.zeros((math.ceil(self.height/tile),math.ceil(self.width/tile)),dtype=bool)
        self.integral = np.zeros((self.tiles.shape[0]+1,self.tiles.shape[1]+1),dtype=np.int64)
        if self.mask is not None:
            np.cumsum(self.tiles,axis=0,dtype=np.int64,out=self.integral[1:,1:])
            np.cumsum(self.integral[1:,1:],axis=1,dtype=np.int64,out=self.integral[1:,1:])

    def _tile_count(self,x1,y1,x2,y2):
        table = self.integral
        return table[y2,x2]-table[y1,x2]-table[y2,x1]+table[y1,x1]

    def changed(self,rectangle):
        key = tuple(rectangle)
        if key in self.cache:
            return self.cache[key]
        result = self._changed(key)
        self.cache[key] = result
        return result

    def _changed(self,rectangle):
        if self.mask is None:
            return False
        x1,y1,x2,y2 = rectangle
        x1,y1 = max(0,int(x1)),max(0,int(y1))
        x2,y2 = min(self.width,int(x2)),min(self.height,int(y2))
        if x1>=x2 or y1>=y2:
            return False
        t = self.tile
        if not self._tile_count(x1//t,y1//t,math.ceil(x2/t),math.ceil(y2/t)):
            return False
        left,top = math.ceil(x1/t)*t,math.ceil(y1/t)*t
        right,bottom = (x2//t)*t,(y2//t)*t
        if left>=right or top>=bottom:
            return bool(self.mask[y1:y2,x1:x2].any())
        if self._tile_count(left//t,top//t,right//t,bottom//t):
            return True
        return bool(self.mask[y1:top,x1:x2].any() or
                    self.mask[bottom:y2,x1:x2].any() or
                    self.mask[top:bottom,x1:left].any() or
                    self.mask[top:bottom,right:x2].any())


def _unknown_rectangles(regions,shape):
    """OCR 提供的未完成覆盖为物理像素 xyxy，不能默默接受非法坐标。"""
    result = []
    for region in regions:
        if len(region)!=4:
            raise ValueError('unknown region must contain four coordinates')
        x1,y1,x2,y2 = (float(value) for value in region)
        if (not all(math.isfinite(value) for value in (x1,y1,x2,y2)) or
                not 0<=x1<x2<=shape[1] or not 0<=y1<y2<=shape[0]):
            raise ValueError('unknown region must be finite and inside the image')
        result.append((math.floor(x1),math.floor(y1),math.ceil(x2),math.ceil(y2)))
    return result


def _intersects_unknown(rectangle,regions):
    x1,y1,x2,y2 = rectangle
    return any(x1<rx2 and rx1<x2 and y1<ry2 and ry1<y2 for rx1,ry1,rx2,ry2 in regions)


class ContentIndex:
    def __init__(self, tile=64):
        if not isinstance(tile,int) or isinstance(tile,bool) or tile<=0:
            raise ValueError('tile must be a positive integer')
        self.tile = tile
        self.image, self.unknown = None, None
        self.hits = []
        self.lines = []
        self._context_key, self._contexts = None, []

    def _with_context(self,lines,shape):
        # 邻近关系只取决于几何；文字仍使用本次结果，不能复用分类。
        key = (shape[:2],tuple(tuple((float(x),float(y)) for x,y in line['polygon']) for line in lines))
        if key!=self._context_key:
            contexts = with_context(lines,shape)
            self._contexts = [line['_context'] for line in contexts]
            self._context_key = key
            return contexts
        return [{**line,'_context':rectangle} for line,rectangle in zip(lines,self._contexts)]

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
            self.lines = []
        else:
            difference = _ExactDifference(self.image,image,self.tile,self.tiles)
            self.unknown |= difference.tiles
            kept = []
            for hit in self.hits:
                rect = padded_rect(hit['polygon'],image.shape)
                if not difference.changed(rect):
                    kept.append(hit)
                else:
                    # 单个数字改变时，整条原敏感行临时覆盖，避免露出旧前缀。
                    self.dirty_rect(rect)
            self.hits = kept
            kept_lines = []
            for line in self.lines:
                rect = padded_rect(line['polygon'],image.shape)
                if difference.changed(line_context(line,image.shape)):
                    self.dirty_rect(rect)
                if not difference.changed(rect):
                    kept_lines.append(line)
            self.lines = kept_lines
        self.image = image

    def accept(self, source, lines, semantic=None, unknown_regions=None):
        if self.image is None or source.shape != self.image.shape:
            return False
        # 缺少覆盖信息的空结果不等于整个屏幕安全；明确 [] 才表示完整覆盖。
        regions = (_unknown_rectangles(unknown_regions,self.image.shape) if unknown_regions is not None
                   else [(0,0,self.image.shape[1],self.image.shape[0])] if not lines else [])
        lines = self._with_context(lines,self.image.shape)
        # 文字检测到框、但没有可判别的文字，也不能清除该行的保护。
        regions += [padded_rect(line['polygon'],self.image.shape) for line in lines if not str(line['text']).strip()]
        difference = _ExactDifference(source,self.image,self.tile,self.tiles)
        changed = difference.tiles
        self.unknown &= changed
        for rectangle in regions:
            self.dirty_rect(rectangle)
        # 迟到结果只替换仍与其源画面一致的区域，不能删除新帧已确认的敏感行。
        accepted = [hit for hit in self.hits
                    if difference.changed(line_context(hit,self.image.shape))]
        validity = {}
        def valid(line):
            rectangle = line_context(line,self.image.shape)
            if rectangle not in validity:
                validity[rectangle] = not difference.changed(rectangle) and not _intersects_unknown(rectangle,regions)
            return validity[rectangle]
        # 未识别的标签可能比值行大、离值更远。保留旧的依赖范围，不能让
        # 缺失标签后的较小新上下文在下一次缓存结果中清掉整条值行的保护。
        kept_lines = [line for line in self.lines if not valid(line)]
        for line in self.lines+lines:
            if not valid(line):
                self.dirty_rect(padded_rect(line['polygon'],self.image.shape))
        combined = kept_lines+[line for line in lines if valid(line)]
        # Cached/late results can retain unresolved geometry; keep each exact
        # dependency once so repeated results never accumulate duplicate lines.
        unique = {}
        for line in combined:
            key = (tuple(tuple(point) for point in line['polygon']),
                   tuple(line_context(line,self.image.shape)))
            unique[key] = line
        self.lines = list(unique.values())
        for hit in detect(lines,semantic):
            hit['_context'] = lines[hit['line_index']]['_context']
            rect = padded_rect(hit['polygon'],self.image.shape)
            if valid(hit):
                accepted.append(hit)
            else:
                self.dirty_rect(rect)
        self.hits = accepted
        return bool((~self.unknown).any())

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
