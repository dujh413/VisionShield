import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from app_shell import Shell, Backend
from owner_presence import OwnerPresence
from app_scope import application_masks, valid_profiles


def observation(score=.7, x=.2, frontal=True, track=1, reliable=True):
    return {'score':score,'bbox':(x,.2,x+.3,.6),'frontal':frontal,'track_id':track,'reliable':reliable}


class ExperienceRegressions(unittest.TestCase):
    def confirmed(self):
        p=OwnerPresence()
        for n in range(5):result=p.update(n*.1,[observation()])
        self.assertTrue(result['owner_verified'])
        return p

    def test_short_head_down_retains_session_without_claiming_verified(self):
        p=self.confirmed()
        result=p.update(1.4,[])
        self.assertTrue(result['pose_grace']);self.assertFalse(result['protect_request'])
        self.assertFalse(result['owner_verified']);self.assertFalse(result['stranger_detected'])

    def test_sideways_low_quality_face_has_bounded_grace(self):
        p=self.confirmed()
        self.assertFalse(p.update(1,[observation(None,frontal=False)])['protect_request'])
        self.assertTrue(p.update(2.5,[observation(None,frontal=False)])['protect_request'])
        self.assertTrue(p.update(2.6,[])['protect_request'])

    def test_stranger_overrides_grace_immediately(self):
        for faces in ([observation(.1)], [observation(),observation(.1,x=.7)]):
            p=self.confirmed();result=p.update(.5,faces)
            self.assertTrue(result['protect_request']);self.assertTrue(result['stranger_detected'])

    def test_geometry_jump_cannot_inherit_grace(self):
        p=self.confirmed()
        self.assertTrue(p.update(.5,[observation(None,x=.7,frontal=False)])['protect_request'])

    def test_returning_owner_does_not_require_reenrollment(self):
        p=self.confirmed();p.update(.8,[])
        self.assertTrue(p.update(1,[observation(track=2)])['owner_verified'])

    def test_startup_and_unenrolled_do_not_have_grace(self):
        p=OwnerPresence()
        self.assertTrue(p.update(0,[observation()])['protect_request'])
        p=self.confirmed()
        result=p.update(.6,[observation()],enrolled=False)
        self.assertTrue(result['protect_request']);self.assertFalse(result['stranger_detected'])

    def test_live_choice_saves_and_sends_without_restart(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            backend=Backend();backend.peer=Mock()
            panel=Shell(QSettings(str(Path(folder)/'prefs.ini'),QSettings.IniFormat),backend,tray_available=False)
            panel.set_state('running','test')
            panel.effect_checks['shield_enabled'].setChecked(False)
            self.assertFalse(backend.shield_enabled)
            self.assertIn(b'"shield_enabled": false',backend.peer.write.call_args.args[0])
            self.assertFalse(panel.settings.value('shield_enabled',True,type=bool))
            panel.tray.hide();panel.deleteLater();app.processEvents()

    def window(self, mode='chat', rect=(100,100,600,500),client=(100,100,600,500),key='chat'):
        return {'key':key,'mode':mode,'rect':rect,'client':client}

    def test_chat_only_masks_calibrated_dialog_including_pending_tiles(self):
        profile={'chat':{'mode':'chat','region':[.4,.1,.6,.8],'size':[600,500]}}
        masks,full=application_masks([self.window()],[(0,0,1000,1000)],True,profile)
        self.assertEqual(masks,[(340,150,360,400)]);self.assertFalse(full)

    def test_chat_moves_with_client_and_resize_invalidates_calibration(self):
        profile={'chat':{'mode':'chat','region':[.4,.1,.6,.8],'size':[600,500]}}
        moved=self.window(rect=(200,200,600,500),client=(200,200,600,500))
        self.assertEqual(application_masks([moved],[],False,profile)[0],[(440,250,360,400)])
        resized=self.window(rect=(100,100,700,500),client=(100,100,700,500))
        self.assertEqual(application_masks([resized],[],False,profile)[0],[])

    def test_image_masks_entire_application_without_ocr_hits(self):
        window=self.window(mode='window')
        masks,full=application_masks([window],[],False)
        self.assertEqual(masks,[window['rect']]);self.assertFalse(full)

    def test_foreground_window_is_not_masked_by_background_application(self):
        front=self.window(mode='ignore',rect=(300,100,400,500),key='own-ui')
        back=self.window(mode='window')
        self.assertEqual(application_masks([front,back],[],False)[0],[(100,100,200,500)])

    def test_unknown_app_clips_sensitive_lines_to_window(self):
        window=self.window(mode='lines')
        self.assertEqual(application_masks([window],[(50,120,100,20)],False)[0],[(100,120,50,20)])

    def test_corrupt_calibration_and_inventory_failure_are_conservative(self):
        bad={'chat':{'mode':'chat','region':[0,0,float('nan'),1],'size':[600,500]}}
        self.assertEqual(valid_profiles(bad),{})
        self.assertEqual(application_masks([],[],True),([],False))


if __name__=='__main__':unittest.main()
