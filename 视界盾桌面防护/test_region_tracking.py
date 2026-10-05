import unittest
from unittest.mock import patch
import numpy as np
import cv2
from region_features import extract_features,locate_features,valid_features
from region_tracker import RegionTracker
from app_scope import valid_profiles,stored_profiles,application_masks


def feature_image():
    random=np.random.default_rng(84)
    patch_image=np.full((220,300,3),235,np.uint8)
    for _ in range(100):
        x,y=random.integers([10,10],[290,210]);color=tuple(map(int,random.integers(0,220,3)))
        cv2.circle(patch_image,(int(x),int(y)),int(random.integers(3,12)),color,-1)
    cv2.putText(patch_image,'FICTIONAL REGION',(12,110),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),2)
    return patch_image


class RegionTrackingTests(unittest.TestCase):
    def setUp(self):
        self.patch=feature_image()
        self.image=np.full((700,1000,3),255,np.uint8)
        self.image[150:370,120:420]=self.patch
        self.features=extract_features(self.image,(120,150,300,220))

    def assertRectNear(self,a,b,tolerance=7):
        self.assertIsNotNone(a)
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,delta=tolerance)

    def test_visual_anchor_tracks_region_moved_inside_same_window(self):
        moved=np.full_like(self.image,255);moved[320:540,510:810]=self.patch
        self.assertRectNear(locate_features(moved,(0,0,1000,700),self.features),(510,320,300,220))

    def test_visual_anchor_tracks_scaled_region(self):
        moved=np.full_like(self.image,255);scaled=cv2.resize(self.patch,(450,330))
        moved[250:580,400:850]=scaled
        self.assertRectNear(locate_features(moved,(0,0,1000,700),self.features),(400,250,450,330),12)

    def test_visual_loss_does_not_return_previous_fixed_coordinates(self):
        self.assertIsNone(locate_features(np.full_like(self.image,255),(0,0,1000,700),self.features))

    def test_visual_tracker_clears_prior_scope_when_current_frame_loses_features(self):
        tracker=RegionTracker();window=self.window()
        profile={'mode':'tracked','anchor':{'type':'visual'},'features':self.features,
                 'binding':{'handle':20,'pid':30}}
        try:
            first=tracker.resolve({window['key']:profile},[window],self.image,now=1)
            self.assertIsNotNone(first[window['key']]['rect'])
            scopes=tracker.resolve({window['key']:profile},[window],np.full_like(self.image,255),now=2)
            self.assertIsNone(scopes[window['key']]['rect'])
            self.assertEqual(application_masks([window],[],False,{window['key']:profile},scopes)[0],[])
        finally:tracker.close()

    def test_repeated_ambiguous_pattern_is_rejected(self):
        image=np.full_like(self.image,255);image[50:270,50:350]=self.patch;image[400:620,550:850]=self.patch
        self.assertIsNone(locate_features(image,(0,0,1000,700),self.features))

    def test_malformed_descriptors_are_rejected(self):
        bad=dict(self.features,descriptors='not base64')
        self.assertIsNone(valid_features(bad))

    def profile(self):
        return {'mode':'tracked','anchor':{'type':'native','class':'Pane','id':32,'fraction':[0,0,1,1]},
                'binding':{'handle':20,'pid':30},'features':self.features}

    def window(self,handle=20,client=(100,100,600,500)):
        return {'key':'demo.exe|Demo','handle':handle,'pid':30,'mode':'lines','client':client,'rect':client}

    def test_native_anchor_tracks_internal_pane_not_window_fixed_fraction(self):
        tracker=RegionTracker();profile=self.profile();window=self.window()
        with patch('region_anchor.locate_anchor',return_value=(200,250,200,150)):
            scopes=tracker.resolve({window['key']:profile},[window],self.image,now=1)
        self.assertEqual(scopes[window['key']]['rect'],(200,250,200,150))
        with patch('region_anchor.locate_anchor',return_value=(400,350,150,250)):
            scopes=tracker.resolve({window['key']:profile},[window],self.image,now=2)
        masks,full=application_masks([window],[],False,{window['key']:profile},scopes)
        self.assertEqual(masks,[(400,350,150,250)]);self.assertFalse(full)
        tracker.close()

    def test_other_window_cannot_inherit_calibration(self):
        profile=self.profile();other=self.window(handle=99)
        tracker=RegionTracker()
        with patch('region_anchor.locate_anchor') as locate:
            scopes=tracker.resolve({other['key']:profile},[other],self.image,now=1)
        self.assertEqual(scopes,{});locate.assert_not_called()
        self.assertEqual(application_masks([other],[],False,{other['key']:profile},scopes)[0],[])

    def test_lost_anchor_never_expands_outside_selection(self):
        profile=self.profile();profile.pop('features');window=self.window()
        tracker=RegionTracker()
        with patch('region_anchor.locate_anchor',return_value=None):
            scopes=tracker.resolve({window['key']:profile},[window],self.image,now=1)
        self.assertEqual(application_masks([window],[],False,{window['key']:profile},scopes)[0],[])

    def test_features_and_window_handle_are_not_persisted(self):
        stored=stored_profiles({'app':self.profile()})['app']
        self.assertNotIn('features',stored);self.assertNotIn('binding',stored)
        self.assertEqual(stored['anchor']['id'],32)

    def test_legacy_coordinate_profile_is_not_trusted_in_running_tracker(self):
        profile={'mode':'chat','region':[.4,0,.6,1],'size':[600,500]};window=self.window()
        masks,full=application_masks([window],[],False,{window['key']:profile},{})
        self.assertEqual(masks,[])


if __name__=='__main__':unittest.main()
