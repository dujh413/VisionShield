"""验证角色顺序、丢失、交叉与过期后的保护回退。"""
import unittest

from owner_tracking import OwnerSession, ShortTracker


class OwnerTrackingTests(unittest.TestCase):
    def test_order_change_keeps_selected_person(self):
        tracker, owner = ShortTracker(), OwnerSession()
        tracks = tracker.update([(0.1, 0.2, 0.3, 0.5), (0.7, 0.2, 0.9, 0.5)], 0)
        owner.update(tracks)
        owner.select(tracks[0].track_id)
        selected = owner.owner_id
        tracks = tracker.update([(0.71, 0.2, 0.91, 0.5), (0.11, 0.2, 0.31, 0.5)], 30)
        owner.update(tracks)
        self.assertEqual(tracks[1].track_id, selected)
        self.assertEqual(owner.owner_id, selected)
        self.assertTrue(owner.protect_request)

    def test_owner_leave_does_not_transfer_to_remaining_face(self):
        tracker, owner = ShortTracker(), OwnerSession()
        tracks = tracker.update([(0.1, 0.2, 0.3, 0.5), (0.7, 0.2, 0.9, 0.5)], 0)
        owner.update(tracks)
        owner.select(tracks[0].track_id)
        owner.update(tracker.update([(0.7, 0.2, 0.9, 0.5)], 30))
        self.assertIsNone(owner.owner_id)
        self.assertEqual(owner.state, "LOST_RECONFIRM")
        self.assertTrue(owner.protect_request)

    def test_missing_and_return_requires_click(self):
        tracker, owner = ShortTracker(), OwnerSession()
        tracks = tracker.update([(0.1, 0.2, 0.3, 0.5)], 0)
        owner.update(tracks)
        owner.select(tracks[0].track_id)
        owner.update(tracker.update([], 30))
        owner.update(tracker.update([(0.1, 0.2, 0.3, 0.5)], 60))
        self.assertIsNone(owner.owner_id)
        self.assertTrue(owner.protect_request)
        self.assertTrue(owner.select(owner.tracks[0].track_id))
        self.assertFalse(owner.protect_request)

    def test_overlapping_faces_cannot_be_selected(self):
        tracker, owner = ShortTracker(), OwnerSession()
        tracks = tracker.update([(0.1, 0.2, 0.4, 0.5), (0.2, 0.2, 0.5, 0.5)], 0)
        owner.update(tracks)
        self.assertFalse(owner.select(tracks[0].track_id))
        self.assertTrue(owner.protect_request)

    def test_large_time_gap_invalidates_owner(self):
        tracker, owner = ShortTracker(), OwnerSession()
        tracks = tracker.update([(0.1, 0.2, 0.3, 0.5)], 0)
        owner.update(tracks)
        owner.select(tracks[0].track_id)
        owner.update(tracker.update([(0.1, 0.2, 0.3, 0.5)], 600))
        self.assertIsNone(owner.owner_id)
        self.assertTrue(owner.protect_request)


if __name__ == "__main__":
    unittest.main()
