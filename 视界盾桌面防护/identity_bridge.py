"""只监听本机UDP；这是原型进程接口，非安全认证边界。"""
import json
import math
import socket
import time


class IdentityBridge:
    def __init__(self, port=47831, timeout=1.5, message_max_age=3.0):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', port))
        self.socket.setblocking(False)
        self.timeout = timeout
        self.last = None
        self.received_at = None
        self.session = None
        self.sequence = -1
        self.message_max_age = message_max_age
        self.retired_sessions = set()

    def poll(self):
        for _ in range(200):
            try:
                data, address = self.socket.recvfrom(4096)
            except BlockingIOError:
                break
            try:
                item = json.loads(data)
                if address[0] != '127.0.0.1':
                    continue
                if (type(item['owner_verified']) is not bool or type(item['protect_request']) is not bool
                        or type(item['faces_count']) is not int or not 0 <= item['faces_count'] <= 100
                        or type(item['sequence']) is not int or item['sequence'] < 0
                        or not isinstance(item['session'], str) or not 1 <= len(item['session']) <= 80
                        or type(item['updated_at']) not in (int, float)
                        or not math.isfinite(item['updated_at'])
                        or not -.5 <= time.time()-item['updated_at'] <= self.message_max_age):
                    continue
                now = time.monotonic()
                if item['session'] in self.retired_sessions:
                    continue
                if self.session is not None and item['session'] != self.session:
                    # New senders may take over only after the current sender has timed out.
                    if self.received_at is not None and now-self.received_at <= self.timeout:
                        continue
                    self.retired_sessions.add(self.session)
                    if len(self.retired_sessions) > 128:
                        raise RuntimeError('Too many identity sessions; restart receiver')
                if item['session'] == self.session and item['sequence'] <= self.sequence:
                    continue
                self.session, self.sequence = item['session'], item['sequence']
                self.last, self.received_at = item, now
            except (ValueError, KeyError, TypeError):
                continue

    def risk(self, now):
        if self.received_at is None or now-self.received_at > self.timeout:
            return True, '机主识别未连接或已失联'
        risk = (self.last['protect_request'] or not self.last['owner_verified']
                or self.last['faces_count'] != 1)
        return risk, '旁观风险或机主未确认' if risk else '机主独处且已确认'

    def close(self):
        self.socket.close()

