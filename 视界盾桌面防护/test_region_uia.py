import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import numpy as np
from region_tracker import RegionTracker,client_signature
from region_worker import locate_regions


class ManualRegionWorker:
    def __init__(self):
        self.ready=True;self.requested_at=None;self.created_at=100
        self.process=SimpleNamespace(is_alive=lambda:True)
        self.requests=[];self.outputs=[];self.closed=False
    def submit(self,value):
        self.requests.append(value);self.requested_at=value['requested_at']
    def poll(self):
        items,self.outputs=self.outputs,[]
        if items:self.requested_at=None
        return items
    def finish(self,rect,request=None):
        request=request or self.requests[-1]
        self.outputs=[{'regions':{key:rect for key in request['tasks']},
                       'clients':request['clients'],'signatures':request['signatures'],
                       'requested_at':request['requested_at'],'sequence':request['sequence']}]
    def close(self):self.closed=True


class UIATrackerTests(unittest.TestCase):
    def setUp(self):
        self.image=np.full((300,400,3),235,np.uint8)
        self.image[70:130,60:140]=120
        self.window={'key':'synthetic.exe|Frame','handle':20,'pid':30,'mode':'lines',
                     'client':(20,30,200,160),'rect':(20,30,200,160)}
        self.profile={'mode':'tracked','binding':{'handle':20,'pid':30},
                      'anchor':{'type':'uia','path':[{'kind':50033,'class':'Pane','id':'pane'}],
                                'fraction':[0,0,1,1]}}
        self.tracker=RegionTracker();self.worker=ManualRegionWorker();self.tracker.worker=self.worker
        self.rect=(60,70,80,60)
    def tearDown(self):self.tracker.close()
    def resolve(self,image=None,window=None,profile=None,now=100):
        window=window or self.window
        return self.tracker.resolve({window['key']:profile or self.profile},[window],
                                    self.image if image is None else image,now=now)[window['key']]['rect']
    def prime(self):
        self.assertIsNone(self.resolve())
        self.worker.finish(self.rect)
        self.assertEqual(self.resolve(now=100.1),self.rect)

    def test_static_pixels_reuse_valid_uia_bounds_without_main_thread_com(self):
        self.prime()
        with patch('region_anchor.locate_anchor') as com:
            self.assertEqual(self.resolve(now=100.2),self.rect)
        com.assert_not_called()

    def test_any_internal_pixel_change_invalidates_cached_box_immediately(self):
        self.prime()
        self.image[70,60,0]-=1  # Same ndarray object must not hide a changed layout.
        self.assertIsNone(self.resolve(now=100.2))
        self.assertEqual(self.tracker.results,{})

    def test_pixels_outside_client_do_not_invalidate_static_bound_control(self):
        self.prime()
        changed=self.image.copy();changed[299,399]=0
        self.assertEqual(self.resolve(changed,now=100.2),self.rect)

    def test_window_translation_uses_equal_relative_pixels_and_live_origin(self):
        self.prime()
        moved=dict(self.window,client=(100,110,200,160),rect=(100,110,200,160))
        scene=np.full_like(self.image,235)
        scene[110:270,100:300]=self.image[30:190,20:220]
        self.assertEqual(self.resolve(scene,moved,now=100.2),(140,150,80,60))

    def test_internal_move_same_window_size_rejects_old_async_completion(self):
        self.resolve();old=self.worker.requests[-1]
        scene=np.full_like(self.image,235);scene[110:170,130:210]=120
        self.assertIsNone(self.resolve(scene,now=100.1))
        self.worker.finish(self.rect,old)
        self.assertIsNone(self.resolve(scene,now=100.2))
        self.worker.finish((130,110,80,60))
        self.assertEqual(self.resolve(scene,now=100.3),(130,110,80,60))

    def test_old_profile_response_cannot_rebind_same_pixels_to_other_selection(self):
        self.resolve();old=self.worker.requests[-1]
        changed=copy.deepcopy(self.profile);changed['anchor']['fraction']=[.2,.2,.5,.5]
        self.assertIsNone(self.resolve(profile=changed,now=100.1))
        self.worker.finish(self.rect,old)
        self.assertIsNone(self.resolve(profile=changed,now=100.2))

    def test_partial_out_of_screen_client_or_resized_client_drops_cached_scope(self):
        self.prime()
        self.assertIsNone(self.resolve(window=dict(self.window,client=(20,30,210,160)),now=100.2))
        self.assertIsNone(self.resolve(window=dict(self.window,client=(-5,30,200,160)),now=100.3))

    def test_worker_failure_unknown_location_clears_old_box(self):
        self.prime();self.worker.outputs=[{'error':'SyntheticFailure'}]
        self.assertIsNone(self.resolve(now=100.2))

    def test_expired_or_future_result_never_counts_as_fresh_location(self):
        self.resolve();old=self.worker.requests[-1]
        self.worker.finish(self.rect,dict(old,requested_at=101))
        self.assertIsNone(self.resolve(now=100.2))
        self.worker.finish(self.rect,dict(old,requested_at=99))
        self.assertIsNone(self.resolve(now=100.3))

    def test_removed_profiles_drop_all_layout_caches(self):
        self.prime()
        self.assertEqual(self.tracker.resolve({},[],self.image,now=100.2),{})
        self.assertEqual(self.tracker.results,{})
        self.assertEqual(self.tracker.profile_tokens,{})


class UIAWorkerTests(unittest.TestCase):
    def setUp(self):
        self.image=np.full((300,400,3),235,np.uint8)
        self.window={'handle':20,'pid':30,'client':(20,30,200,160)}
        signature={'layout':client_signature(self.image,self.window['client']),
                   'size':(200,160),'handle':20,'pid':30,'profile':'test-profile'}
        self.request={'tasks':{'app':{'handle':20,'anchor':{'type':'uia'}}},'origin':(0,0),
                      'clients':{'app':self.window['client']},'signatures':{'app':signature},
                      'requested_at':100,'sequence':1}
        self.capture=Mock(monitor={'left':0,'top':0,'width':400,'height':300})
        self.rect=(60,70,80,60)
    def run_worker(self,after=None,after_window=None,bounds=None,before=None):
        self.capture.grab.side_effect=[SimpleNamespace(image=self.image if before is None else before),
                                       SimpleNamespace(image=self.image if after is None else after)]
        with patch('screen_capture.ScreenCapture',return_value=self.capture),\
             patch('app_scope.window_inventory',side_effect=[[self.window],[after_window or self.window]]),\
             patch('region_anchor.locate_anchor',side_effect=bounds or [self.rect,self.rect]) as locate:
            result=locate_regions(self.request)
        self.capture.close.assert_called_once()
        return result,locate
    def test_stable_structural_reads_and_matching_frames_return_only_metadata(self):
        result,locate=self.run_worker()
        self.assertEqual(result['regions'],{'app':self.rect});self.assertEqual(locate.call_count,2)
        self.assertEqual(result['signatures'],self.request['signatures'])
        self.assertNotIn('image',result)
    def test_changed_before_com_discards_request_without_reading_structure(self):
        changed=self.image.copy();changed[60,50]=0
        result,locate=self.run_worker(before=changed)
        self.assertIsNone(result['regions']['app']);locate.assert_not_called()
    def test_changed_during_com_discards_even_correct_old_bounds(self):
        changed=self.image.copy();changed[60,50]=0
        result,locate=self.run_worker(after=changed)
        self.assertIsNone(result['regions']['app']);self.assertEqual(locate.call_count,1)
    def test_window_moved_during_com_cannot_mix_origins(self):
        result,_=self.run_worker(after_window=dict(self.window,client=(40,50,200,160)))
        self.assertIsNone(result['regions']['app'])
    def test_bounds_changed_between_com_reads_reject_unchanged_pixels(self):
        result,_=self.run_worker(bounds=[self.rect,(90,100,80,60)])
        self.assertIsNone(result['regions']['app'])


if __name__=='__main__':unittest.main()
