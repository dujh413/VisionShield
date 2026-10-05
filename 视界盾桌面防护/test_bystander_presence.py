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


if __name__=='__main__':unittest.main()
