import unittest
import numpy as np
from content_state import ContentState
from local_ocr_motion import LocalOcrMotion
from app_scope import application_masks
from screen_capture import Frame


class LocalOcrMotionTests(unittest.TestCase):
    def setUp(self):
        self.motion = LocalOcrMotion()
        self.profiles = {'test':{'mode':'region','region':[0,0,1,1],
                                 'binding':{'handle':1,'pid':2}}}
        self.window = {'key':'test','mode':'lines','handle':1,'pid':2,
                       'client':(0,0,100,80),'rect':(0,0,100,80)}
        self.image = np.zeros((200,400,3),np.uint8)
        self.image[10:25,10:70] = 210
        self.frame = Frame(1,10,{},self.image)
        self.content = ContentState(capture_timeout=1.5)
        self.content.observe(self.frame)
        self.content.accept({'frame_id':1,'captured_at':10,'image':self.image,
            'lines':[{'text':'demo@example.com','confidence':.99,
                      'polygon':[[10,10],[70,10],[70,25],[10,25]]}],
            'unknown_regions':[]},10)
        self.locate(0,10)
        self.motion.remember(self.content,10)

    def locate(self,x,now,**overrides):
        self.window.update(client=(x,0,100,80),rect=(x,0,100,80),**overrides)
        self.motion.locate([self.window],self.profiles,True,now)

    def test_sixty_moves_follow_native_coordinates_without_waiting_for_ocr(self):
        for step in range(1,61):
            now=10+step*.02
            self.locate(step*3,now)
            self.assertFalse(self.motion.allows(self.frame.captured_at))
            # Capture intentionally lags the current native window geometry.
            self.frame.captured_at=now-.1
            self.assertEqual(self.motion.rectangles(self.frame,now),[(10+step*3,10,60,15)])
            bindings={};renders=[]
            masks,_=application_masks([self.window],[],False,self.profiles,
                local_ocr_enabled=True,sensitive_rectangles=self.motion.rectangles(self.frame,now),
                render_bindings=bindings,render_scopes=renders)
            self.assertEqual(masks,[(10+step*3,10,60,15)])
            token=next(iter(bindings.values()))
            if step==1:first=token
            self.assertEqual(token,first)

    def test_settled_pixels_validate_translation_and_edit_invalidates_it(self):
        self.locate(100,10.1)
        moved=np.zeros_like(self.image);moved[10:25,110:170]=210
        frame=Frame(2,10.2,{},moved)
        self.assertTrue(self.motion.allows(frame.captured_at))
        self.assertEqual(self.motion.rectangles(frame,10.2),[(110,10,60,15)])
        moved[12,112]=0
        self.assertEqual(self.motion.rectangles(frame,10.21),[])
        moved[12,112]=210
        self.assertEqual(self.motion.rectangles(frame,10.22),[])

    def test_invalidated_text_before_motion_is_not_revived(self):
        changed=self.image.copy();changed[12,12]=0
        self.content.observe(Frame(2,10.05,{},changed))
        self.motion.remember(self.content,10.05)
        self.locate(100,10.1)
        self.assertEqual(self.motion.rectangles(self.frame,10.1),[])

    def test_expired_result_and_stale_capture_drop_old_boxes(self):
        self.locate(100,10.1)
        self.assertEqual(self.motion.rectangles(self.frame,12),[])
        self.frame.captured_at=20.1
        self.locate(103,20.1)
        self.assertEqual(self.motion.rectangles(self.frame,20.1),[])

    def test_resize_rebinding_removal_or_toggle_clears_cached_coordinates(self):
        for change in ('resize','pid','remove','off','profile'):
            self.setUp()
            if change=='resize':self.window['client']=(50,0,110,80)
            if change=='pid':self.window['pid']=99
            if change=='profile':self.profiles['test']['region']=[.2,0,.8,1]
            self.motion.locate([] if change=='remove' else [self.window],
                               self.profiles,change!='off',10.1)
            self.assertEqual(self.motion.rectangles(self.frame,10.1),[])

    def test_new_result_replaces_motion_cache_even_when_no_sensitive_text(self):
        self.locate(100,10.1)
        self.content.observe(Frame(2,10.2,{},np.zeros_like(self.image)))
        self.content.accept({'frame_id':2,'captured_at':10.2,'image':self.content.latest.image,
            'lines':[],'unknown_regions':[],'analysis_regions':[(100,0,200,80)]},10.2)
        self.motion.remember(self.content,10.2)
        self.locate(103,10.22)
        self.assertEqual(self.motion.rectangles(self.content.latest,10.22),[])

    def test_label_dependency_is_checked_after_motion(self):
        lines=[{'text':'验证码：','confidence':.99,'polygon':[[10,5],[50,5],[50,15],[10,15]]},
               {'text':'246810','confidence':.99,'polygon':[[10,20],[50,20],[50,30],[10,30]]}]
        self.content.observe(Frame(2,10.01,{},self.image))
        self.content.accept({'frame_id':2,'captured_at':10.01,'image':self.image,
                             'lines':lines,'unknown_regions':[]},10.01)
        self.motion.remember(self.content,10.01)
        self.locate(100,10.1)
        moved=np.zeros_like(self.image);moved[:,100:200]=self.image[:,:100]
        frame=Frame(3,10.2,{},moved)
        self.assertEqual(len(self.motion.rectangles(frame,10.2)),2)
        moved[6,112]=255
        self.assertEqual(self.motion.rectangles(frame,10.21),[])


if __name__=='__main__':unittest.main()
