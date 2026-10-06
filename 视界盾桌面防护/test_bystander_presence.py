import unittest

from owner_presence import OwnerPresence


def owner():
    return {'score':.7,'bbox':(.35,.2,.65,.7),'frontal':True,'track_id':1,'reliable':True}


class BystanderPresenceTests(unittest.TestCase):
    def test_background_face_without_identity_features_still_overrides_pose_grace(self):
        presence=OwnerPresence()
        for index in range(5):result=presence.update(index*.1,[owner()])
        self.assertTrue(result['owner_verified'])
        small={'score':None,'bbox':(.7,.12,.74,.17),'frontal':False,'track_id':2,'reliable':True}
        result=presence.update(.5,[owner(),small])
        self.assertTrue(result['stranger_detected'])
        self.assertTrue(result['protect_request'])
        self.assertFalse(result['pose_grace'])
        self.assertFalse(presence.update(.6,[])['pose_grace'])

    def test_single_unidentifiable_small_face_cannot_become_the_owner(self):
        presence=OwnerPresence()
        small={'score':None,'bbox':(.7,.12,.74,.17),'frontal':False,'track_id':2,'reliable':True}
        for index in range(12):result=presence.update(index*.1,[small])
        self.assertFalse(result['owner_verified'])
        self.assertTrue(result['protect_request'])

    def test_tiny_replacement_at_owner_center_cannot_inherit_pose_grace(self):
        presence=OwnerPresence()
        for index in range(5):presence.update(index*.1,[owner()])
        small={'score':None,'bbox':(.48,.425,.52,.475),'frontal':False,'track_id':2,'reliable':True}
        result=presence.update(.5,[small])
        self.assertTrue(result['protect_request'])
        self.assertFalse(result['owner_verified'])
        self.assertFalse(result['pose_grace'])
        self.assertFalse(result['stranger_detected'])
        self.assertTrue(presence.update(.6,[])['protect_request'])
        for index in range(4):
            self.assertTrue(presence.update(.7+index*.1,[owner()])['protect_request'])
        self.assertTrue(presence.update(1.1,[owner()])['owner_verified'])

    def test_large_replacement_at_owner_center_cannot_inherit_pose_grace(self):
        presence=OwnerPresence()
        for index in range(5):presence.update(index*.1,[owner()])
        large={'score':None,'bbox':(.05,0,.95,.9),'frontal':False,'track_id':2,'reliable':True}
        result=presence.update(.5,[large])
        self.assertTrue(result['protect_request'])
        self.assertFalse(result['pose_grace'])

    def test_normal_head_turn_keeps_bounded_pose_grace(self):
        presence=OwnerPresence()
        for index in range(5):presence.update(index*.1,[owner()])
        turned={'score':None,'bbox':(.41,.2,.59,.7),'frontal':False,'track_id':1,'reliable':True}
        result=presence.update(.5,[turned])
        self.assertFalse(result['protect_request'])
        self.assertTrue(result['pose_grace'])
        self.assertFalse(result['owner_verified'])
        self.assertTrue(presence.update(2.41,[turned])['protect_request'])

    def test_expired_session_requires_five_new_owner_matches(self):
        for track_id in (1,2):
            with self.subTest(track_id=track_id):
                presence=OwnerPresence()
                for index in range(5):presence.update(index*.1,[owner()])
                returned={**owner(),'track_id':track_id}
                for index in range(5):
                    result=presence.update(10+index*.1,[returned])
                    self.assertEqual(result['owner_verified'],index==4)
                    self.assertEqual(result['protect_request'],index<4)
                    self.assertFalse(result['stranger_detected'])

    def test_return_within_grace_can_reacquire_a_new_track(self):
        presence=OwnerPresence()
        for index in range(5):presence.update(index*.1,[owner()])
        self.assertTrue(presence.update(1,[])['pose_grace'])
        returned={**owner(),'track_id':2}
        result=presence.update(1.8,[returned])
        self.assertTrue(result['owner_verified'])
        self.assertFalse(result['protect_request'])
        self.assertFalse(result['pose_grace'])

    def test_backward_time_cannot_renew_a_confirmed_session(self):
        presence=OwnerPresence()
        for index in range(5):presence.update(index*.1,[owner()])
        result=presence.update(.3,[{**owner(),'track_id':2}])
        self.assertFalse(result['owner_verified'])
        self.assertTrue(result['protect_request'])
        self.assertFalse(result['pose_grace'])


if __name__=='__main__':unittest.main()
