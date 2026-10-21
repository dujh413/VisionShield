"""Carry confirmed text boxes through native window translation, without OCR per move."""
import math
import numpy as np
from app_scope import intersect, region_scope
from sensitive_rules import rect_of
from content_index import line_context


class LocalOcrMotion:
    SETTLE_SECONDS = .05

    def __init__(self):
        self.entries = {}

    def locate(self, windows, profiles, enabled, now):
        if not enabled:
            self.entries.clear()
            return
        current = {}
        for window in windows:
            key = window['key'];profile = profiles.get(key, {})
            if (profile.get('mode') != 'region' or window['mode'] == 'ignore'
                    or profile.get('binding') != {'handle':window['handle'], 'pid':window['pid']}):continue
            scope = region_scope(profile, window)
            if scope is None:continue
            token = (repr(profile), tuple(window['client'][2:]), scope[2:])
            previous = self.entries.get(key)
            entry = previous if previous and previous['token'] == token else {
                'token':token, 'scope':scope, 'moved_at':-math.inf,
                'translated':False, 'frame_id':-1, 'proofs':[]}
            if entry['scope'] != scope:
                entry['moved_at'] = now
                entry['translated'] = True
                entry['scope'] = scope
            current[key] = entry
        self.entries = current

    def allows(self, captured_at):
        return all(captured_at > entry['moved_at'] + self.SETTLE_SECONDS
                   for entry in self.entries.values())

    def remember(self, content, now):
        item = content.result
        if item is None or not self.allows(item['captured_at']):return
        hits = content.view(now)['hits']
        for entry in self.entries.values():
            if entry['frame_id'] == item['frame_id']:
                # A scroll/edit invalidated before the drag must not revive a
                # previous hit merely because its window starts moving later.
                if not entry['translated']:
                    sx,sy,*_ = entry['scope']
                    active = {intersect(rect_of(hit['polygon']),entry['scope']) for hit in hits}
                    entry['proofs'] = [proof for proof in entry['proofs']
                        if (proof[0][0]+sx,proof[0][1]+sy,*proof[0][2:]) in active]
                continue
            entry['frame_id'] = item['frame_id']
            entry['captured_at'] = item['captured_at']
            entry['timeout'] = content.result_timeout
            entry['translated'] = False
            entry['proofs'] = []
            sx,sy,*_ = entry['scope']
            for hit in hits:
                if not any(category != '无法确定' for category in hit['categories']):continue
                box = intersect(rect_of(hit['polygon']), entry['scope'])
                if box is None:continue
                if hit.get('standalone'):
                    context = rect_of(hit['polygon'])
                else:
                    b = line_context(item['lines'][hit['line_index']],item['image'].shape)
                    context = (b[0],b[1],b[2]-b[0],b[3]-b[1])
                proof = intersect(context, entry['scope'])
                x,y,w,h = proof
                x1,y1,x2,y2 = math.floor(x),math.floor(y),math.ceil(x+w),math.ceil(y+h)
                # Only small in-memory text/context patches are retained.
                entry['proofs'].append(((box[0]-sx,box[1]-sy,*box[2:]),
                    (x1-sx,y1-sy,x2-sx,y2-sy), item['image'][y1:y2,x1:x2].copy()))

    def rectangles(self, frame, now):
        if frame is None or not 0 <= now-frame.captured_at <= 1.5:return []
        result = []
        for entry in self.entries.values():
            if not entry['translated']:continue
            if not 0 <= now-entry.get('captured_at',-math.inf) <= entry.get('timeout',0):
                entry['proofs'] = []
                continue
            sx,sy,*_ = entry['scope']
            valid = []
            for box,proof,pixels in entry['proofs']:
                if frame.captured_at > entry['moved_at'] + self.SETTLE_SECONDS:
                    x1,y1,x2,y2 = (int(proof[0]+sx),int(proof[1]+sy),
                                   int(proof[2]+sx),int(proof[3]+sy))
                    if (x1<0 or y1<0 or x2>frame.image.shape[1] or y2>frame.image.shape[0]
                            or not np.array_equal(pixels,frame.image[y1:y2,x1:x2])):continue
                valid.append((box,proof,pixels))
                result.append((box[0]+sx,box[1]+sy,*box[2:]))
            entry['proofs'] = valid
        return result
