import unittest
from types import SimpleNamespace
from guard_service import status_payload


class DisplayStatusTests(unittest.TestCase):
    def panel(self, visible):
        return SimpleNamespace(error=None, camera=None,
            timer=SimpleNamespace(isActive=lambda: True),
            status=SimpleNamespace(text=lambda: 'running'),
            alert_message='', hits=[], protecting=False, shield_enabled=False,
            overlay=SimpleNamespace(isVisible=lambda: visible, full=True, blurs=[object()]))

    def test_hidden_overlay_does_not_report_retained_safety_mask(self):
        status = status_payload(self.panel(False))
        self.assertFalse(status['full_mask'])
        self.assertEqual(status['blur_regions'], 0)

    def test_visible_overlay_reports_active_masks(self):
        status = status_payload(self.panel(True))
        self.assertTrue(status['full_mask'])
        self.assertEqual(status['blur_regions'], 1)


if __name__ == '__main__':
    unittest.main()
