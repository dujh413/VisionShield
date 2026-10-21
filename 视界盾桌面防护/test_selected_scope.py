import unittest
from app_scope import application_masks, profile_status, stored_profiles, valid_profiles


def window(handle, key='demo', rect=(100, 100, 500, 400), mode='lines'):
    return {'handle':handle,'pid':10,'key':key,'rect':rect,'client':rect,'mode':mode}


class SelectedScopeTests(unittest.TestCase):
    def region_profile(self):
        return {'demo':{'mode':'region','region':[.1,.1,.4,.5],
                        'binding':{'handle':1,'pid':10}}}

    def test_region_needs_no_image_features_and_follows_same_window_move_resize(self):
        profile=self.region_profile()
        for rect,expected in (((100,100,500,400),(150,140,200,200)),
                              ((300,200,1000,800),(400,280,400,400))):
            target=window(1,rect=rect)
            self.assertEqual(application_masks([target],[],False,profile,{}),([expected],False))
            self.assertIn('已定位1/1',profile_status(profile,[target],{}))

    def test_region_never_rebinds_on_restart_or_pid_reuse(self):
        profile=self.region_profile()
        self.assertEqual(application_masks([window(2)],[],True,profile,{}),([],False))
        reused=window(1);reused['pid']=11
        self.assertEqual(application_masks([reused],[],True,profile,{}),([],False))
        saved=stored_profiles(profile)
        self.assertEqual(application_masks([window(1)],[],True,saved,{}),([],False))
        self.assertIn('局部配置需暂停后重新框选',profile_status(saved,[window(1)],{}))

    def test_region_ocr_only_masks_sensitive_intersections_even_when_uncertain(self):
        profile=self.region_profile();target=window(1)
        hits=[(140,150,40,20),(200,200,40,20),(500,350,50,20)]
        self.assertEqual(application_masks([target],hits,False,profile,{},True),
                         ([(150,150,30,20),(200,200,40,20)],False))
        self.assertEqual(application_masks([target],[],False,profile,{},True),([],False))
        self.assertEqual(application_masks([target],[],True,profile,{},True),([],False))
        self.assertEqual(application_masks([target],[(100,100,500,400)],True,profile,{},True,
                                          sensitive_rectangles=[(200,200,40,20)]),([(200,200,40,20)],False))
        self.assertEqual(application_masks([target],hits,False,profile,{},False),([(150,140,200,200)],False))

    def test_ocr_switch_keeps_whole_window_policy_and_legacy_local_scope(self):
        target=window(1)
        whole={'demo':{'mode':'window','binding':{'handle':1,'pid':10}}}
        self.assertEqual(application_masks([target],[],False,whole,{},True),([target['rect']],False))
        resolved={'demo':{'handle':1,'rect':(180,190,200,150)}}
        self.assertEqual(application_masks([target],[(190,200,30,20)],False,self.profile(),resolved,True),
                         ([(190,200,30,20)],False))

    def test_moving_occluder_changes_visible_clip_not_render_geometry(self):
        target=window(1);profile=self.region_profile()
        for x in range(170,350,10):
            cover=window(2,'other',(x,140,50,200))
            render=[]
            masks,_=application_masks([cover,target],[],False,profile,{},render_scopes=render)
            self.assertEqual(render,[(150,140,200,200)])
            self.assertTrue(all(not (r[0]<x+50 and r[0]+r[2]>x) for r in masks))

    def test_region_validation_rejects_nonfinite_and_out_of_bounds(self):
        for part in ([0,0,float('nan'),.2],[0,0,float('inf'),.2],[.9,0,.2,.2],[-.1,0,.2,.2],[0,0,0,.2]):
            self.assertEqual(valid_profiles({'demo':{'mode':'region','region':part}}),{})

    def profile(self):
        return {'demo':{'mode':'tracked','binding':{'handle':1,'pid':10},
            'anchor':{'type':'native','class':'Pane','id':12,'fraction':[0,0,1,1]}}}

    def test_pending_whole_screen_and_other_apps_cannot_escape_selected_rect(self):
        target=window(1); other=window(2,'other',(700,100,500,400),'window')
        selected=(180,190,200,150)
        scopes={'demo':{'handle':1,'rect':selected}}
        masks,full=application_masks([target,other],[(0,0,1800,1200)],True,self.profile(),scopes)
        self.assertEqual(masks,[selected]);self.assertFalse(full)

    def test_lost_selection_does_not_mask_any_other_area(self):
        target=window(1);other=window(2,'other',(700,100,500,400),'chat')
        self.assertEqual(application_masks([target,other],[(0,0,1800,1200)],True,self.profile(),{}),([],False))

    def test_whole_window_binding_does_not_select_another_window_from_same_app(self):
        selected=window(1);second=window(2,rect=(700,100,500,400))
        profile={'demo':{'mode':'window','binding':{'handle':1,'pid':10}}}
        self.assertEqual(application_masks([selected,second],[],True,profile,{}),([selected['rect']],False))
        self.assertEqual(application_masks([second],[],True,profile,{}),([],False))

    def test_restarted_whole_window_profile_never_adopts_another_window(self):
        profile=stored_profiles({'demo':{'mode':'window','binding':{'handle':1,'pid':10}}})
        self.assertEqual(profile,{'demo':{'mode':'window'}})
        self.assertEqual(application_masks([window(1)],[],True,profile,{}),([],False))
        self.assertEqual(application_masks([window(1),window(2)],[],True,profile,{}),([],False))
        self.assertEqual(application_masks([window(2)],[],True,profile,{}),([],False))
        self.assertIn('整窗配置需暂停后重新点击',profile_status(profile,[window(2)],{}))

    def test_no_selected_scope_preserves_automatic_application_protection(self):
        automatic=window(1,mode='window')
        self.assertEqual(application_masks([automatic],[],True,{},{}),([automatic['rect']],False))

    def test_own_ui_is_clear_even_when_z_order_metadata_places_it_last(self):
        target=window(1)
        own=window(9,'own',(200,200,150,100),'ignore')
        own['own_ui']=True
        selected=(180,190,200,150)
        masks,full=application_masks([target,own],[],False,self.profile(),{'demo':{'handle':1,'rect':selected}})
        self.assertFalse(full)
        self.assertEqual(sum(r[2]*r[3] for r in masks),200*150-150*100)
        for r in masks:
            self.assertFalse(r[0]<350 and r[0]+r[2]>200 and r[1]<300 and r[1]+r[3]>200)

    def test_empty_inventory_never_switches_to_full_screen(self):
        self.assertEqual(application_masks([],[(0,0,1800,1200)],True,self.profile(),{}),([],False))

    def test_background_desktop_is_not_an_own_ui_exclusion(self):
        target=window(1)
        desktop=window(9,'explorer.exe|Progman',(0,0,1800,1200),'ignore')
        desktop['own_ui']=False
        selected=(180,190,200,150)
        self.assertEqual(application_masks([target,desktop],[],False,self.profile(),{'demo':{'handle':1,'rect':selected}}),([selected],False))


if __name__=='__main__':unittest.main()
