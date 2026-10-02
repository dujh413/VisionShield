import json
import socket
import time
import uuid


class IdentitySender:
    def __init__(self, port=47831):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.port = port
        self.session = str(uuid.uuid4())
        self.sequence = 0

    def send(self, verified, protect, faces):
        self.sequence += 1
        item = {'owner_verified': bool(verified), 'protect_request': bool(protect),
                'faces_count': int(faces), 'sequence': self.sequence,
                'session': self.session, 'updated_at': time.time()}
        self.socket.sendto(json.dumps(item).encode('utf-8'), ('127.0.0.1', self.port))

    def close(self):
        try:
            self.send(False, True, 0)
        finally:
            self.socket.close()
