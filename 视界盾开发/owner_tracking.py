"""第一阶段短期几何关联与手动机主状态，不进行生物身份验证。"""
from dataclasses import dataclass
from math import hypot


def overlap(a, b):
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1e-9)


def match_cost(a, b):
    width_a, height_a = a[2] - a[0], a[3] - a[1]
    width_b, height_b = b[2] - b[0], b[3] - b[1]
    area_a, area_b = width_a * height_a, width_b * height_b
    if min(area_a, area_b) <= 0 or max(area_a, area_b) / min(area_a, area_b) > 2.5:
        return None
    distance = hypot((a[0] + a[2] - b[0] - b[2]) / 2,
                     (a[1] + a[3] - b[1] - b[3]) / 2)
    scale = (hypot(width_a, height_a) + hypot(width_b, height_b)) / 2
    normalized_distance = distance / max(scale, 1e-9)
    if normalized_distance > 0.6:
        return None
    return 1 - overlap(a, b) + normalized_distance


@dataclass(frozen=True)
class Track:
    track_id: int
    bbox: tuple
    reliable: bool


class ShortTracker:
    """只关联连续帧；漏检或歧义后创建新轨迹，旧机主不自动续接。"""

    def __init__(self, max_gap_ms=500):
        self.previous = []
        self.last_ms = None
        self.next_id = 1
        self.max_gap_ms = max_gap_ms

    def update(self, boxes, timestamp_ms):
        boxes = [tuple(box) for box in boxes]
        if self.last_ms is not None and timestamp_ms - self.last_ms > self.max_gap_ms:
            self.previous = []
        self.last_ms = timestamp_ms
        ambiguous = set()
        for i, first in enumerate(boxes):
            for j in range(i + 1, len(boxes)):
                if overlap(first, boxes[j]) > 0.1:
                    ambiguous.update((i, j))
        candidates = []
        for current_index, box in enumerate(boxes):
            if current_index in ambiguous:
                continue
            for previous_index, track in enumerate(self.previous):
                if not track.reliable:
                    continue
                cost = match_cost(track.bbox, box)
                if cost is not None:
                    candidates.append((cost, previous_index, current_index))
        # 拒绝竞争匹配：同一目标的最优和次优候选过近时，不转移角色。
        for axis in (1, 2):
            groups = {}
            for candidate in candidates:
                groups.setdefault(candidate[axis], []).append(candidate)
            for group in groups.values():
                group.sort()
                if len(group) > 1 and group[1][0] - group[0][0] < 0.25:
                    ambiguous.update(item[2] for item in group)
        assignments, used_previous = {}, set()
        for _, previous_index, current_index in sorted(candidates):
            if (current_index in ambiguous or current_index in assignments
                    or previous_index in used_previous):
                continue
            assignments[current_index] = self.previous[previous_index].track_id
            used_previous.add(previous_index)
        tracks = []
        for index, box in enumerate(boxes):
            track_id = assignments.get(index)
            if track_id is None:
                track_id = self.next_id
                self.next_id += 1
            tracks.append(Track(track_id, box, index not in ambiguous))
        self.previous = tracks
        return tracks


class OwnerSession:
    def __init__(self):
        self.owner_id = None
        self.state = "UNSELECTED"
        self.tracks = []

    def update(self, tracks):
        self.tracks = tracks
        if self.owner_id is not None:
            owner = next((track for track in tracks if track.track_id == self.owner_id), None)
            if owner is None or not owner.reliable:
                self.owner_id = None
                self.state = "LOST_RECONFIRM"

    def select(self, track_id):
        track = next((item for item in self.tracks if item.track_id == track_id), None)
        if track is None or not track.reliable:
            return False
        self.owner_id = track_id
        self.state = "MANUAL_CONFIRMED"
        return True

    def reset(self):
        self.owner_id = None
        self.state = "UNSELECTED"

    @property
    def protect_request(self):
        # 仅为下一步集成的“第二张脸”基线信号，不是姿态风险算法。
        return self.owner_id is None or any(
            track.track_id != self.owner_id for track in self.tracks
        )
