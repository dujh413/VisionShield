"""恢复须由连续新鲜的传感器观察证明，重复界面轮询不计入安全时长。"""
from math import isfinite


_OMITTED = object()


class ProtectionState:
    def __init__(self, restore_delay=1.0, observation_timeout=1.5):
        self.restore_delay = restore_delay
        self.observation_timeout = observation_timeout
        self.safe_since = None
        self.protecting = True
        self.last_observation = None
        self.evidence_error = None

    def _protect(self):
        self.safe_since = None
        self.protecting = True
        return True

    def _observation(self, now, value):
        if not isinstance(value, dict):
            self.evidence_error = 'missing'
            return None
        stamp = value.get('observed_at', value.get('received_at'))
        sequence = value.get('sequence')
        session = value.get('session')
        if (type(now) not in (int, float) or not isfinite(now)
                or type(stamp) not in (int, float) or not isfinite(stamp)
                or type(sequence) is not int or sequence < 0
                or session is not None and (not isinstance(session, str) or not 1 <= len(session) <= 80)):
            self.evidence_error = 'invalid'
            return None
        if stamp > now:
            self.evidence_error = 'future'
            return None
        if now-stamp > self.observation_timeout:
            self.evidence_error = 'stale'
            return None
        return session, sequence, stamp

    def update(self, now, risk, observation=_OMITTED):
        """产品必须传观察dict或None；仅旧非传感器调用可省略第三参数。

        相机传sequence/observed_at，可附session；旧身份接口传
        sequence/session/received_at（接收端单调时钟）。时间和序列须
        严格增加；丢包或会话切换重新证明安全，不推测缺失帧内容。
        """
        if observation is _OMITTED:
            self.evidence_error = None
            # 兼容原纯状态调用；产品路径使用下面的观察证明。
            if risk:
                return self._protect()
            if self.safe_since is None:
                self.safe_since = now
            if now-self.safe_since >= self.restore_delay:
                self.protecting = False
            return self.protecting

        current = self._observation(now, observation)
        if current is None:
            return self._protect()
        session, sequence, stamp = current
        restart = self.last_observation is None
        if self.last_observation is not None:
            previous_session, previous_sequence, previous_stamp = self.last_observation
            if current == self.last_observation:
                # 同一安全帧被界面重复读取，保持状态但不推进恢复。
                if risk:
                    self.evidence_error = None
                    return self._protect()
                return self.protecting
            if stamp <= previous_stamp or session == previous_session and sequence <= previous_sequence:
                self.evidence_error = 'out_of_order'
                return self._protect()
            restart = session != previous_session or sequence != previous_sequence+1
        previous = self.last_observation
        self.last_observation = current
        self.evidence_error = ('session_changed' if restart and previous and session != previous[0] else
                               'gap' if restart and previous else None)
        if risk:
            self.evidence_error = None
            return self._protect()
        if restart:
            self._protect()
        if self.safe_since is None:
            self.safe_since = stamp
        if stamp-self.safe_since >= self.restore_delay:
            self.protecting = False
        return self.protecting
