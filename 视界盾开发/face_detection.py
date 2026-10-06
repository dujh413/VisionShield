"""整帧和重叠分区的人脸检测；分区用于找出机主身后的小脸。"""
import time

import cv2
import numpy as np


def map_faces(faces, scale, origin=(0, 0)):
    """YuNet 的框和五组关键点均映射回原始摄像头图像。"""
    if faces is None or not len(faces):
        return np.empty((0, 15), dtype=np.float32)
    mapped = np.asarray(faces, dtype=np.float32).copy()
    mapped[:, :14] /= scale
    mapped[:, [0, 4, 6, 8, 10, 12]] += origin[0]
    mapped[:, [1, 5, 7, 9, 11, 13]] += origin[1]
    return mapped


def unmirror_faces(faces, width):
    """镜像检测映回原画面；交换双眼和嘴角以保持SFace五点顺序。"""
    mapped=map_faces(faces,1)
    mapped[:,0]=width-mapped[:,0]-mapped[:,2]
    points=mapped[:,4:14].reshape(-1,5,2)
    points[:,:,0]=width-1-points[:,:,0]
    mapped[:,4:14]=points[:,[1,0,2,4,3],:].reshape(-1,10)
    return mapped


def merge_faces(candidates, image_size, confidence=.6, full_count=0):
    """去除整帧/分区对同一张脸的重复检测，保留相邻的真实小脸。"""
    width, height = image_size
    valid = []
    for index,face in enumerate(candidates):
        face = np.asarray(face, dtype=np.float32)
        if face.shape != (15,) or not np.isfinite(face).all():
            continue
        x, y, w, h = map(float, face[:4])
        if (min(w, h) < 10 or face[14] < confidence or not .35 <= w/h <= 2.5
                or not 0 <= x+w/2 < width or not 0 <= y+h/2 < height):
            continue
        preferred=index<full_count and min(w,h)>=80 and float(face[14])>=.78
        valid.append((preferred,index<full_count,face))
    kept,kept_full = [],[]
    for preferred,is_full,face in sorted(valid, key=lambda item:(item[0],float(item[2][14])),reverse=True):
        x, y, w, h = map(float, face[:4])
        duplicate = False
        for previous,previous_full in zip(kept,kept_full):
            a, b, c, d = map(float, previous[:4])
            intersection = max(0, min(x+w, a+c)-max(x, a))*max(0, min(y+h, b+d)-max(y, b))
            iou = intersection/max(w*h+c*d-intersection, 1e-9)
            # 相同脸的检测框可能大小不同；中心须足够近，不能合并身后相邻的人脸。
            near_center = abs(x+w/2-a-c/2) < min(w, c)*.25 and abs(y+h/2-b-d/2) < min(h, d)*.25
            similar_size = min(w/c, c/w, h/d, d/h) >= .65
            landmark_distance=np.linalg.norm(face[4:14].reshape(5,2)-previous[4:14].reshape(5,2),axis=1)
            same_landmarks=float(landmark_distance.mean()) < min(w,c)*.15 and float(landmark_distance.max()) < min(w,c)*.3
            # 分区生成的大“子脸”全部落在整帧脸的中央，属于同一张脸的局部幻检。
            # 限制来源/包含/大小/位置；小远脸及位于头部边缘的旁人不会按此条件合并。
            nested_roi=(not is_full and previous_full and .25 <= w*h/(c*d) <= .75
                        and intersection/(w*h) >= .95
                        and abs(x+w/2-a-c/2) < c*.25 and abs(y+h/2-b-d/2) < d*.25)
            # A partition can trim one side of the same face just outside its
            # full-frame box. Three matching landmarks on that side provide
            # stronger evidence than merely relaxing box containment.
            partial_roi=(not is_full and previous_full and .25 <= w*h/(c*d) <= .75
                         and intersection/(w*h) >= .9
                         and abs(x+w/2-a-c/2) < c*.25 and abs(y+h/2-b-d/2) < d*.25
                         and (np.all(landmark_distance[[0,2,3]] < min(w,c)*.12)
                              or np.all(landmark_distance[[1,2,4]] < min(w,c)*.12)))
            if nested_roi or partial_roi or same_landmarks or (similar_size and near_center and (iou >= .35 or intersection/max(min(w*h, c*d), 1e-9) >= .75)):
                duplicate = True
                break
        if not duplicate:
            kept.append(face)
            kept_full.append(is_full)
    return kept


class FaceScanner:
    """整帧＋两块轮转分区；小脸候选优先在局部图像中重新检测。"""
    def __init__(self, detector, detail_interval=.1, max_edge=960, diagnostics=False, focus_tile_count=1, mirror_scan=False):
        if focus_tile_count not in (1,2):
            raise ValueError('focus_tile_count must be 1 or 2')
        self.detector = detector
        self.detail_interval = detail_interval
        self.max_edge = max_edge
        self.last_detail_at = None
        self.last_metrics = {}
        self.weak_candidates = []
        self.previous_confirmed = []
        self.current_unconfirmed_count = 0
        self.tile_index = 0
        self.focus_tile_count = focus_tile_count
        self.mirror_scan = mirror_scan
        self.mirror_turn = 0
        self.focus = None
        self.focus_misses = 0
        self.diagnostics = diagnostics
        self.scan_metrics = []

    def _confirm_candidates(self, faces, now):
        self.current_unconfirmed_count = 0
        pending = [item for item in self.weak_candidates if 0 <= now-item['at'] <= .95]
        # Strong observations provide spatial evidence for a weaker next frame.
        # Consolidate with weak history so each prior face can be used only once.
        for item in self.previous_confirmed:
            if not 0 <= now-item['at'] <= .95:continue
            old=next((p for p in pending if self._same_candidate(item['face'],p['face'])),None)
            if old is None:pending.append(dict(item,hits=1))
            elif item['at'] >= old['at']:old.update(face=item['face'],at=item['at'])
        accepted, seen = [], set()
        for face in faces:
            if face[14] >= .78:
                accepted.append(face)
                continue
            x,y,w,h=map(float,face[:4])
            # 低分候选的五组关键点须落在框内，避免只凭一个模糊色块触发。
            if not (np.all((face[[4,6,8,10,12]] >= x) & (face[[4,6,8,10,12]] <= x+w))
                    and np.all((face[[5,7,9,11,13]] >= y) & (face[[5,7,9,11,13]] <= y+h))):
                continue
            match=None
            for index,item in enumerate(pending):
                if index in seen or now-item['at'] < .025:continue
                if self._same_candidate(face,item['face']):
                    match=index
                    break
            if match is None:
                pending.append({'face':face,'at':now,'hits':1})
                self.current_unconfirmed_count += 1
            else:
                seen.add(match)
                item=pending[match]
                item.update(face=face,at=now,hits=item['hits']+1)
                if item['hits'] >= 2:accepted.append(face)
        # 只保存少量几何候选，不保留任何原图或人物特征。
        self.weak_candidates=sorted((p for p in pending if p['face'][14] < .78),key=lambda item:item['at'],reverse=True)[:16]
        self.previous_confirmed=[{'face':face.copy(),'at':now} for face in accepted if face[14] >= .78][:16]
        return accepted

    @staticmethod
    def _same_candidate(first,second):
        x,y,w,h=map(float,first[:4]);a,b,c,d=map(float,second[:4])
        return (min(w/c,c/w,h/d,d/h) >= .65
                and abs(x+w/2-a-c/2) < min(w,c)*.5
                and abs(y+h/2-b-d/2) < min(h,d)*.5)

    def _detect(self, image, origin=(0, 0), enlarge=False, max_edge=None, frame_size=None, label='full'):
        height, width = image.shape[:2]
        scale = (self.max_edge if max_edge is None else max_edge)/max(width, height)
        if not enlarge:
            scale = min(1.0, scale)
        target_width, target_height = round(width*scale), round(height*scale)
        resized = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LINEAR) if scale != 1 else image
        self.detector.setInputSize((target_width, target_height))
        _, faces = self.detector.detect(resized)
        rows=[] if faces is None else list(faces)
        rejected=0
        if frame_size is not None:
            # 内部分区边缘截断机主脸时会制造第二张“半脸”；由重叠分区检测完整脸。
            internal=(origin[0]>0,origin[1]>0,origin[0]+width<frame_size[0],origin[1]+height<frame_size[1])
            rows=[face for face in rows if not (
                (internal[0] and face[0] <= 3) or (internal[1] and face[1] <= 3)
                or (internal[2] and face[0]+face[2] >= target_width-3)
                or (internal[3] and face[1]+face[3] >= target_height-3))]
            rejected=0 if faces is None else len(faces)-len(rows)
        if self.diagnostics:
            self.scan_metrics.append({'scan':label,'input_size':[int(target_width),int(target_height)],
                                      'raw_faces':0 if faces is None else int(len(faces)),
                                      'scores':sorted([round(float(face[14]),3) for face in ([] if faces is None else faces)],reverse=True)[:8],
                                      'border_rejected':int(rejected)})
        # 实际四舍五入可能使 x、y 的缩放相差半个像素；分别映射，避免关键点错位。
        mapped = map_faces(rows, 1.0)
        mapped[:, [0, 2, 4, 6, 8, 10, 12]] *= width/target_width
        mapped[:, [1, 3, 5, 7, 9, 11, 13]] *= height/target_height
        mapped[:, [0, 4, 6, 8, 10, 12]] += origin[0]
        mapped[:, [1, 5, 7, 9, 11, 13]] += origin[1]
        return list(mapped)

    @staticmethod
    def _near(first,second):
        x,y,w,h=map(float,first[:4]);a,b,c,d=map(float,second[:4])
        return (min(w/c,c/w,h/d,d/h) >= .5
                and abs(x+w/2-a-c/2) <= max(w,c)*.6
                and abs(y+h/2-b-d/2) <= max(h,d)*.6)

    def _focus_crop(self,image):
        height,width=image.shape[:2]
        x,y,w,h=map(float,self.focus['face'][:4])
        half_w,half_h=max(96,w*1.6),max(96,h*1.6)
        center_x,center_y=x+w/2,y+h/2
        left,top=max(0,int(center_x-half_w)),max(0,int(center_y-half_h))
        right,bottom=min(width,int(center_x+half_w)),min(height,int(center_y+half_h))
        return image[top:bottom,left:right],(left,top)

    @staticmethod
    def _contrast(image):
        lab=cv2.cvtColor(image,cv2.COLOR_BGR2LAB)
        lab[:,:,0]=cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(lab[:,:,0])
        return cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)

    def detect(self, image, now=None):
        now = time.monotonic() if now is None else now
        before = time.perf_counter()
        height, width = image.shape[:2]
        self.scan_metrics=[]
        faces = self._detect(image)
        full_count=len(faces)
        strong_full=[face for face in faces if min(float(face[2]),float(face[3]))>=80 and float(face[14])>=.78]
        focus_is_full=False
        if self.focus is not None:
            target=self.focus['face']
            x,y,w,h=map(float,target[:4])
            for face in strong_full:
                a,b,c,d=map(float,face[:4])
                intersection=max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b))
                iou=intersection/max(w*h+c*d-intersection,1e-9)
                landmark_distance=np.linalg.norm(face[4:14].reshape(5,2)-target[4:14].reshape(5,2),axis=1)
                if iou>=.55 and float(landmark_distance.mean())<min(w,c)*.2:
                    focus_is_full=True
                    break
        detailed = self.last_detail_at is None or now-self.last_detail_at >= self.detail_interval
        focus_attempted=False
        if detailed:
            # Alternate enhancement with the normal path so frequent camera
            # observations are not all delayed by the larger full-frame pass.
            if self.mirror_scan and self.mirror_turn%2==0:
                enhanced=cv2.flip(self._contrast(image),1)
                rows=self._detect(enhanced,enlarge=True,max_edge=min(1920,max(width,height)*1.5),label='background_mirror')
                faces.extend(unmirror_faces(rows,width))
            self.mirror_turn+=1
            count=2
            if self.focus is not None and 0 <= now-self.focus['at'] <= .95:
                crop,origin=self._focus_crop(image)
                patches=((self._contrast(crop),'focus_contrast'),) if focus_is_full else (
                    (crop,'focus'),(self._contrast(crop),'focus_contrast'))
                for patch,label in patches:
                    faces.extend(self._detect(patch,origin,True,max_edge=640,frame_size=(width,height),label=label))
                focus_attempted=True
                count=2 if focus_is_full else self.focus_tile_count
            # 六块重叠分区：1280×720摄像头中640×432→1280×864，实现2倍放大。
            tile_width,tile_height=max(1,round(width*.5)),max(1,round(height*.6))
            tiles=[(x,y) for y in (0,height-tile_height)
                   for x in (0,(width-tile_width)//2,width-tile_width)]
            for _ in range(count):
                index=self.tile_index%len(tiles)
                x,y=tiles[index]
                faces.extend(self._detect(image[y:y+tile_height,x:x+tile_width],(x,y),True,
                                          max_edge=min(1280,max(tile_width,tile_height)*2),
                                          frame_size=(width,height),label='tile_'+str(index)))
                self.tile_index=(index+1)%len(tiles)
            self.last_detail_at = now
        candidates=merge_faces(faces, (width, height),full_count=full_count)
        result = self._confirm_candidates(candidates,now)
        small=[face for face in candidates if float(face[2]) <= width*.2 and float(face[3]) <= height*.45
               and (face[14]>=.78 or
                    np.all((face[[4,6,8,10,12]]>=face[0]) & (face[[4,6,8,10,12]]<=face[0]+face[2]))
                    and np.all((face[[5,7,9,11,13]]>=face[1]) & (face[[5,7,9,11,13]]<=face[1]+face[3])))]
        match=next((face for face in small if self.focus is not None and self._near(face,self.focus['face'])),None)
        if match is not None:
            self.focus={'face':match,'at':now};self.focus_misses=0
        elif self.focus is not None and focus_attempted:
            self.focus_misses+=1
        if self.focus is None or self.focus_misses >= 3 or now-self.focus['at'] > .95:
            self.focus={'face':min(small,key=lambda face:float(face[2]*face[3])),'at':now} if small else None
            self.focus_misses=0
        # 新发现更小的脸优先复检，避免把近处机主作为唯一局部目标。
        if small and self.focus is not None:
            smallest=min(small,key=lambda face:float(face[2]*face[3]))
            if float(smallest[2]*smallest[3]) < float(self.focus['face'][2]*self.focus['face'][3])*.7:
                self.focus={'face':smallest,'at':now};self.focus_misses=0
        self.last_metrics = {'detection_ms':round((time.perf_counter()-before)*1000, 2),
                             'detail_scan':bool(detailed), 'frame_size':[int(width), int(height)],
                             'unconfirmed_faces':int(self.current_unconfirmed_count),
                             'weak_candidates':int(sum(int(.6 <= face[14] < .78) for face in candidates))}
        if self.diagnostics:self.last_metrics['scans']=self.scan_metrics
        return result


class BystanderHold:
    """分区限频期间短时保留已检测到的旁人风险，不复用其坐标或身份。"""
    def __init__(self, seconds=.5):
        self.seconds = seconds
        self.last_seen_at = None

    def update(self, now, detected):
        if detected:
            self.last_seen_at = now
        return self.last_seen_at is not None and 0 <= now-self.last_seen_at <= self.seconds
