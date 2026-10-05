"""当前帧身份与短时机主会话分开；宽限仅用于已确认机主的姿态丢失。"""
from math import hypot


class OwnerPresence:
    def __init__(self, grace=2.0, required=5):
        self.grace, self.required = grace, required
        self.last_owner_at = None
        self.last_box = None
        self.count = 0
        self.candidate = None
        self.confirmed = False

    def update(self, now, observations, enrolled=True):
        # observations: track_id, reliable, bbox(normalized), score, frontal.
        owner = [o for o in observations if o['reliable'] and o['score'] is not None and o['score'] >= .45]
        stranger = len(observations) > 1 or any(
            o['frontal'] and o['score'] is not None and o['score'] < .25 for o in observations)
        if not enrolled or stranger:
            self.confirmed = False
            self.count, self.candidate = 0, None
            self.last_owner_at = None
        elif len(owner) == 1 and len(observations) == 1:
            face = owner[0]
            if face['track_id'] != self.candidate:
                self.count, self.candidate = 1, face['track_id']
            else:
                self.count += 1
            if self.confirmed or self.count >= self.required:
                self.confirmed = True
                self.last_owner_at, self.last_box = now, face['bbox']
        else:
            self.count, self.candidate = 0, None
        verified = self.confirmed and len(owner) == 1 and len(observations) == 1 and not stranger
        grace = self.confirmed and self.last_owner_at is not None and 0 <= now-self.last_owner_at <= self.grace
        if grace and observations and not verified:
            a, b = self.last_box, observations[0]['bbox']
            # 位置明显改变不能借用上一位机主的宽限。
            distance = hypot((a[0]+a[2]-b[0]-b[2])/2, (a[1]+a[3]-b[1]-b[3])/2)
            grace = distance <= max(a[2]-a[0], a[3]-a[1])*.6 and observations[0]['reliable']
        active = enrolled and not stranger and (verified or grace)
        if not active:
            self.confirmed = False
        return {'owner_verified':bool(verified), 'owner_session_active':bool(active),
                'pose_grace':bool(active and not verified), 'stranger_detected':bool(enrolled and stranger),
                'protect_request':not active}


def frontal_face(face):
    width = float(face[2])
    if width <= 0:
        return False
    left, right = sorted((float(face[4]), float(face[6])))
    nose_x, nose_y = float(face[8]), float(face[9])
    eyes_y = (float(face[5])+float(face[7]))/2
    return (right-left)/width >= .30 and left < nose_x < right and 0 < (nose_y-eyes_y)/float(face[3]) < .35
