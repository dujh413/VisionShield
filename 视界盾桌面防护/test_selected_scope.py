import unittest
from app_scope import application_masks, stored_profiles


def window(handle, key='demo', rect=(100, 100, 500, 400), mode='lines'):
    return {'handle':handle,'pid':10,'key':key,'rect':rect,'client':rect,'mode':mode}


class SelectedScopeTests(unittest.TestCase):
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

    def test_restarted_whole_window_profile_requires_a_unique_candidate(self):
        profile=stored_profiles({'demo':{'mode':'window','binding':{'handle':1,'pid':10}}})
        self.assertEqual(profile,{'demo':{'mode':'window'}})
        self.assertEqual(application_masks([window(1),window(2)],[],True,profile,{}),([],False))

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
