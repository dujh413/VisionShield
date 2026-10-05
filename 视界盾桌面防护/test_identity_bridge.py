import json
import unittest
from unittest.mock import patch
from identity_bridge import IdentityBridge


class FakeSocket:
    def __init__(self):
        self.packets = []
    def bind(self, address):
        pass
    def setblocking(self, value):
        pass
    def recvfrom(self, size):
        if not self.packets:
            raise BlockingIOError
        return json.dumps(self.packets.pop(0)).encode(), ('127.0.0.1',1234)
    def close(self):
        pass


def message(session='a', sequence=1, protect=False, stamp=1000.):
    return {'session':session,'sequence':sequence,'owner_verified':not protect,
            'protect_request':protect,'faces_count':2 if protect else 1,'updated_at':stamp}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.socket = FakeSocket()
        with patch('identity_bridge.socket.socket',return_value=self.socket):
            self.bridge = IdentityBridge()

    def poll(self, items, now=0., wall=1000.):
        self.socket.packets.extend(items)
        with patch('identity_bridge.time.monotonic',return_value=now), patch('identity_bridge.time.time',return_value=wall):
            self.bridge.poll()

    def test_stale_future_and_missing_timestamps_do_not_release_protection(self):
        missing = message()
        missing.pop('updated_at')
        self.poll([message(stamp=0),message(stamp=1001),message(stamp=float('nan')),missing])
        self.assertTrue(self.bridge.risk(0.)[0])

    def test_fresh_message_and_same_session_sequence(self):
        self.poll([message(sequence=2),message(sequence=1,protect=True)])
        self.assertFalse(self.bridge.risk(0.)[0])
        self.assertTrue(self.bridge.risk(2.)[0])

    def test_other_session_cannot_override_active_risk_sender(self):
        self.poll([message(protect=True),message(session='b')])
        self.assertTrue(self.bridge.risk(0.)[0])
        self.assertEqual(self.bridge.session,'a')

    def test_restart_after_timeout_and_retired_session_rejection(self):
        self.poll([message()], now=0.)
        self.poll([message(session='b',protect=True)], now=2.)
        self.poll([message(sequence=50)], now=4.)
        self.assertEqual(self.bridge.session,'b')
        self.assertTrue(self.bridge.risk(4.)[0])


if __name__ == '__main__':
    unittest.main()
