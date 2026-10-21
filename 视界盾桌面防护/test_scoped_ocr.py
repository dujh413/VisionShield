"""Fictional crops only; verify native-scale inference and physical offsets."""
import unittest
import numpy as np
from incremental_ocr import ScopedOCR
from app_scope import recognition_regions


class ScopedTests(unittest.TestCase):
    def setUp(self):
        self.image=np.zeros((800,1200,3),np.uint8)
        self.engine=ScopedOCR()

    def infer(self,image,native):
        self.calls.append(image.shape)
        return [{'text':'demo@example.com','confidence':.99,
                 'polygon':[[5,10],[105,10],[105,30],[5,30]]}]

    def test_only_selected_native_pixels_are_inferred_and_boxes_map_back(self):
        self.calls=[]
        regions=((300,200,600,400),)
        lines,metrics=self.engine.run(self.image,self.infer,regions)
        self.assertEqual(self.calls,[(200,300,3)])
        self.assertEqual(lines[0]['polygon'],[[305.,210.],[405.,210.],[405.,230.],[305.,230.]])
        self.assertEqual(metrics['analysis_regions'],list(regions))
        self.assertEqual(metrics['mode'],'selected')

    def test_other_apps_animation_does_not_reinfer_stable_selection(self):
        self.calls=[];regions=((300,200,600,400),)
        self.engine.run(self.image,self.infer,regions)
        changed=self.image.copy();changed[:180]=255
        self.engine.run(changed,self.infer,regions)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.engine.selected),1)

    def test_moving_scope_cache_is_bounded_and_empty_scope_never_falls_back_to_screen(self):
        self.calls=[]
        for x in range(100,150):self.engine.run(self.image,self.infer,((x,200,x+300,400),))
        self.assertEqual(len(self.engine.selected),1)
        count=len(self.calls)
        lines,metrics=self.engine.run(self.image,self.infer,())
        self.assertEqual(lines,[]);self.assertEqual(len(self.calls),count)
        self.assertEqual(metrics['analysis_regions'],[])

    def test_invalid_crop_is_rejected_before_inference(self):
        self.calls=[]
        for regions in (((-1,0,300,400),),((0,0,3000,400),),((0,0,0,4),)):
            with self.assertRaises(ValueError):self.engine.run(self.image,self.infer,regions)
        self.assertEqual(self.calls,[])

    def test_full_screen_path_still_works_when_local_mode_is_disabled(self):
        self.calls=[]
        self.engine.run(self.image,self.infer,((300,200,600,400),))
        _,metrics=self.engine.run(self.image,self.infer)
        self.assertEqual(self.calls[-1],self.image.shape)
        self.assertEqual(metrics['mode'],'full')
        self.assertEqual(self.engine.selected,{})

    def test_region_generation_requires_valid_bound_local_selection(self):
        window={'handle':10,'pid':20,'key':'demo','mode':'lines',
                'rect':(100,100,500,400),'client':(100,100,500,400)}
        profiles={'demo':{'mode':'region','region':[.1,.1,.4,.5],'binding':{'handle':10,'pid':20}}}
        self.assertEqual(recognition_regions([window],profiles,{},self.image.shape),((150,140,350,340),))
        self.assertEqual(recognition_regions([],profiles,{},self.image.shape),())
        self.assertEqual(recognition_regions([window],{'demo':{'mode':'window'}},{},self.image.shape),())
