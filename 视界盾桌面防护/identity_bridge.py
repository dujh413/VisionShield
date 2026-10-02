"""只监听本机UDP；这是原型进程接口，非安全认证边界。"""
import json
import socket
import time


class IdentityBridge:
    def __init__(self, port=47831, timeout=1.5):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', port))
        self.socket.setblocking(False)
        self.timeout = timeout
        self.last = None
        self.received_at = None
        self.session = None
        self.sequence = -1

    def poll(self):
        for _ in range(200):
            try:
                data, address = self.socket.recvfrom(4096)
            except BlockingIOError:
                break
            try:
                item = json.loads(data)
                if (type(item['owner_verified']) is not bool or type(item['protect_request']) is not bool
                        or type(item['faces_count']) is not int or not 0 <= item['faces_count'] <= 100
                        or type(item['sequence']) is not int or item['sequence'] < 0
                        or not isinstance(item['session'], str) or len(item['session']) > 80):
                    continue
                if item['session'] == self.session and item['sequence'] <= self.sequence:
                    continue
                self.session, self.sequence = item['session'], item['sequence']
                self.last, self.received_at = item, time.monotonic()
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
