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
        self.last_risk_history = None
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

    def _risk_history(self, value, current):
        """完整累计风险记录才可证明被最新帧队列淘汰的观察仍安全。"""
        keys = ('last_risk_sequence', 'last_risk_observed_at')
        if not any(key in value for key in keys):
            return None
        marker, event_at = (value.get(key) for key in keys)
        if (not all(key in value for key in keys)
                or type(marker) is not int or not 0 <= marker <= current[1]
                or marker == 0 and event_at is not None
                or marker > 0 and (type(event_at) not in (int, float)
                    or not isfinite(event_at) or event_at > current[2])):
            raise ValueError('invalid_history')
        return marker, event_at

    def update(self, now, risk, observation=_OMITTED):
        """产品必须传观察dict或None；仅旧非传感器调用可省略第三参数。

        相机传sequence/observed_at，可附session；旧身份接口传
        sequence/session/received_at（接收端单调时钟）。时间和序列须
        严格增加；带完整累计风险记录的相机允许最新帧队列正常跳号。
        无风险记录、观察中断或会话切换仍重新证明安全。
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
        try:
            history = self._risk_history(observation, current)
        except ValueError:
            self.evidence_error = 'invalid_history'
            return self._protect()
        restart = self.last_observation is None
        history_risk = False
        if self.last_observation is not None:
            previous_session, previous_sequence, previous_stamp = self.last_observation
            if session == previous_session and self.last_risk_history is not None:
                if history is None:
                    self.evidence_error = 'missing_history'
                    return self._protect()
                previous_marker, previous_event_at = self.last_risk_history
                if (history[0] < previous_marker
                        or history[0] == previous_marker and history[1] != previous_event_at
                        or history[0] > previous_marker and (history[0] <= previous_sequence
                            or previous_event_at is not None and history[1] <= previous_event_at
                            or history[1] <= previous_stamp)):
                    self.evidence_error = 'invalid_history'
                    return self._protect()
                history_risk = history[0] > previous_sequence
            if current == self.last_observation:
                # 同一安全帧被界面重复读取，保持状态但不推进恢复。
                if risk:
                    self.evidence_error = None
                    return self._protect()
                return self.protecting
            if stamp <= previous_stamp or session == previous_session and sequence <= previous_sequence:
                self.evidence_error = 'out_of_order'
                return self._protect()
            complete_safe_history = (history is not None and self.last_risk_history is not None
                                     and history[0] <= previous_sequence)
            restart = (session != previous_session or stamp-previous_stamp > self.observation_timeout
                       or sequence != previous_sequence+1 and not complete_safe_history
                       or (history is None) != (self.last_risk_history is None))
        previous = self.last_observation
        self.last_observation = current
        self.last_risk_history = history
        self.evidence_error = ('session_changed' if restart and previous and session != previous[0] else
                               'gap' if restart and previous else None)
        if risk or history_risk:
            self.evidence_error = None
            return self._protect()
        if restart:
            self._protect()
        if self.safe_since is None:
            self.safe_since = stamp
        if stamp-self.safe_since >= self.restore_delay:
            self.protecting = False
        return self.protecting
