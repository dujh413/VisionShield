import unittest
from identity_state import IdentityGate


class IdentityTests(unittest.TestCase):
    def test_loss_requires_new_confirmation(self):
        gate = IdentityGate(3)
        self.assertFalse(gate.update(1))
        self.assertFalse(gate.update(1))
        self.assertTrue(gate.update(1))
        self.assertFalse(gate.update(None))
        self.assertFalse(gate.update(2))
        self.assertFalse(gate.update(2))
        self.assertTrue(gate.update(2))

    def test_switch_does_not_inherit_confirmation(self):
        gate = IdentityGate(2)
        gate.update(1)
        self.assertTrue(gate.update(1))
        self.assertFalse(gate.update(2))
        self.assertFalse(gate.update(1))


if __name__ == '__main__':
    unittest.main()
