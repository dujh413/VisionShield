import unittest
import numpy as np
from incremental_ocr import IncrementalOCR, changed_box


def line(text,x,y,w=100,h=20):
    return {'text':text,'confidence':1.,'polygon':[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]}


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((1000,1000,3),dtype=np.uint8)

    def test_equal_does_not_infer(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('old',20,20)])
        def fail(*_):
            raise AssertionError('must not infer')
        lines,info=engine.run(self.image.copy(),fail)
        self.assertEqual(info['mode'],'cached')
        self.assertEqual(lines[0]['text'],'old')

    def test_partial_replaces_changed_line_and_offsets(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('changed',100,100),line('keep',800,800)])
        image=self.image.copy()
        image[110,150]=255
        calls=[]
        def infer(crop,native):
            calls.append((crop.shape,native))
            return [line('new',10,10)]
        lines,info=engine.run(image,infer)
        self.assertEqual(info['mode'],'partial')
        self.assertEqual({l['text'] for l in lines},{'new','keep'})
        self.assertTrue(calls[0][1])
        self.assertEqual(next(l for l in lines if l['text']=='new')['polygon'][0],[46.,46.])

    def test_delete_removes_old_text(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[line('deleted',100,100)])
        changed=self.image.copy()
        changed[110,110]=255
        lines,info=engine.run(changed,lambda *_:[])
        self.assertEqual(info['mode'],'partial')
        self.assertEqual(lines,[])

    def test_large_motion_and_size_change_use_full(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[])
        _,info=engine.run(np.full_like(self.image,255),lambda *_:[])
        self.assertEqual(info['mode'],'full')
        _,info=engine.run(np.zeros((800,800,3),dtype=np.uint8),lambda *_:[])
        self.assertEqual(info['mode'],'full')

    def test_periodic_full_refresh(self):
        engine=IncrementalOCR(max_partial=1)
        engine.run(self.image,lambda *_:[])
        first=self.image.copy()
        first[100,100]=1
        _,info=engine.run(first,lambda *_:[])
        self.assertEqual(info['mode'],'partial')
        second=first.copy()
        second[100,100]=2
        _,info=engine.run(second,lambda *_:[])
        self.assertEqual(info['mode'],'full')

    def test_distant_changes_use_separate_small_crops(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[])
        changed=self.image.copy()
        changed[100,100]=1
        changed[800,800]=1
        calls=[]
        def infer(crop,native):
            calls.append(crop.shape)
            return []
        _,info=engine.run(changed,infer)
        self.assertEqual(info['mode'],'partial')
        self.assertEqual(len(calls),2)
        self.assertLess(info['area_ratio'],.05)

    def test_failed_second_crop_does_not_commit_cache(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[])
        changed=self.image.copy()
        changed[100,100]=1
        changed[800,800]=1
        calls=[]
        def infer(*_):
            calls.append(1)
            if len(calls)==2:
                raise RuntimeError('fake failure')
            return []
        with self.assertRaises(RuntimeError):
            engine.run(changed,infer)
        self.assertIs(engine.image,self.image)
        self.assertEqual(engine.partial_updates,0)

    def test_periodic_refresh_without_pixel_changes(self):
        from unittest.mock import patch
        engine=IncrementalOCR(full_refresh_s=1.)
        with patch('incremental_ocr.time.monotonic',return_value=0.):
            engine.run(self.image,lambda *_:[])
        with patch('incremental_ocr.time.monotonic',return_value=2.):
            _,info=engine.run(self.image.copy(),lambda *_:[])
        self.assertEqual(info['mode'],'full')


class Pr10IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((1000,1000,3),dtype=np.uint8)

    def test_equal_does_not_infer(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('old',20,20)])
        def fail(*_):
            raise AssertionError('must not infer')
        lines,info=engine.run(self.image.copy(),fail)
        self.assertEqual(info['mode'],'cached')
        self.assertEqual(lines[0]['text'],'old')

    def test_partial_replaces_changed_line_and_offsets(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('changed',100,100),line('keep',800,800)])
        image=self.image.copy()
        image[110,150]=255
        calls=[]
        def infer(crop,native):
            calls.append((crop.shape,native))
            return [line('new',10,10)]
        lines,info=engine.run(image,infer)
        self.assertEqual(info['mode'],'partial')
        self.assertEqual({l['text'] for l in lines},{'new','keep'})
        self.assertTrue(calls[0][1])
        self.assertEqual(next(l for l in lines if l['text']=='new')['polygon'][0],[46.,46.])

    def test_delete_removes_old_text(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[line('deleted',100,100)])
        changed=self.image.copy()
        changed[110,110]=255
        lines,info=engine.run(changed,lambda *_:[])
        self.assertEqual(info['mode'],'partial')
        self.assertEqual(lines,[])
        self.assertTrue(info['unknown_regions'])

    def test_large_motion_and_size_change_use_full(self):
        engine=IncrementalOCR()
        engine.run(self.image,lambda *_:[])
        _,info=engine.run(np.full_like(self.image,255),lambda *_:[])
        self.assertEqual(info['mode'],'full')
        _,info=engine.run(np.zeros((800,800,3),dtype=np.uint8),lambda *_:[])
        self.assertEqual(info['mode'],'full')

    def test_periodic_full_refresh(self):
        engine=IncrementalOCR(max_partial=1)
        engine.run(self.image,lambda *_:[])
        first=self.image.copy()
        first[100,100]=1
        _,info=engine.run(first,lambda *_:[])
        self.assertEqual(info['mode'],'partial')
        second=first.copy()
        second[100,100]=2
        _,info=engine.run(second,lambda *_:[])
        self.assertEqual(info['mode'],'full')

    def test_two_distant_changes_use_two_small_crops(self):
        original = np.zeros((1600,2560,3),dtype=np.uint8)
        engine = IncrementalOCR()
        engine.run(original, lambda *_: [line('keep',1200,700)])
        changed = original.copy()
        changed[100,100,0] = 1
        changed[1450,2300,2] = 1
        calls = []
        def infer(crop, native):
            calls.append((crop.shape, native))
            return [line('new',10,10,w=40,h=15)]
        lines, info = engine.run(changed, infer)
        self.assertEqual(info['mode'], 'partial')
        self.assertEqual(info['regions_count'], 2)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(native for _,native in calls))
        self.assertAlmostEqual(info['area_ratio'], 2*129*129/(1600*2560))
        self.assertEqual(len(lines), 3)
        self.assertGreaterEqual(info['diff_ms'], 0)
        # The legacy single bounding rectangle covers >80% for this sample.
        x1,y1,x2,y2 = changed_box(original,changed,engine.lines)
        self.assertGreater((x2-x1)*(y2-y1)/(1600*2560), .8)

    def test_character_change_replaces_entire_long_line(self):
        engine = IncrementalOCR()
        engine.run(self.image, lambda *_: [line('123456789',100,100,w=700)])
        changed = self.image.copy()
        changed[110,750,0] = 1
        crops = []
        def infer(crop,native):
            crops.append(crop.shape)
            return [line('123456788',64,64,w=700)]
        lines, info = engine.run(changed, infer)
        self.assertEqual(info['mode'], 'partial')
        self.assertEqual(crops[0][1], 828)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['text'], '123456788')
        self.assertEqual(lines[0]['polygon'][0], [100.,100.])

    def test_failed_second_crop_does_not_commit_any_cache(self):
        engine = IncrementalOCR()
        initial_lines, _ = engine.run(self.image,lambda *_:[line('keep',450,450)])
        changed = self.image.copy()
        changed[100,100] = 1
        changed[850,850] = 1
        calls = []
        def infer(*_):
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('synthetic second crop failure')
            return [line('new',10,10)]
        with self.assertRaises(RuntimeError):
            engine.run(changed,infer)
        self.assertEqual(len(calls), 2)
        self.assertIs(engine.image, self.image)
        self.assertIs(engine.lines, initial_lines)
        self.assertEqual(engine.partial_updates, 0)
        self.assertEqual(engine.unknown_regions, [])

    def test_empty_crop_is_unknown_until_full_region_is_fresh(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('keep',800,800)])
        changed = self.image.copy()
        changed[100,100] = 1
        _, info = engine.run(changed,lambda *_:[])
        self.assertEqual(info['unknown_regions'], [(36,36,165,165)])
        fresh_image = changed.copy()
        fresh_image[100,100] = 2
        _, info = engine.run(fresh_image,lambda *_:[line('fresh',10,10,w=40)])
        self.assertEqual(info['unknown_regions'], [])

    def test_empty_full_and_cached_result_stay_unknown(self):
        engine = IncrementalOCR()
        _, full = engine.run(self.image,lambda *_:[])
        _, cached = engine.run(self.image.copy(),lambda *_:self.fail('unexpected OCR'))
        self.assertEqual(full['unknown_regions'],[(0,0,1000,1000)])
        self.assertEqual(cached['mode'],'cached')
        self.assertEqual(cached['unknown_regions'],full['unknown_regions'])

    def test_blank_or_low_confidence_text_cannot_clear_empty_region(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('keep',800,800)])
        changed = self.image.copy()
        changed[100,100] = 1
        blank = line('',10,10,w=40)
        _, info = engine.run(changed,lambda *_:[blank])
        self.assertEqual(info['unknown_regions'],[(36,36,165,165)])

    def test_stable_frame_still_receives_periodic_full_refresh(self):
        clock = [10.]
        engine = IncrementalOCR(full_refresh_s=15,clock=lambda:clock[0])
        engine.run(self.image,lambda *_:[line('old',20,20)])
        clock[0] = 24.999
        _, info = engine.run(self.image.copy(),lambda *_:self.fail('too early'))
        self.assertEqual(info['mode'],'cached')
        clock[0] = 25.
        native_flags = []
        def infer(_,native):
            native_flags.append(native)
            return [line('fresh',20,20)]
        lines, info = engine.run(self.image.copy(),infer)
        self.assertEqual(info['mode'],'full')
        self.assertEqual(native_flags,[False])
        self.assertEqual(lines[0]['text'],'fresh')

    def test_excessive_region_count_falls_back_to_full(self):
        engine = IncrementalOCR(max_regions=1)
        engine.run(self.image,lambda *_:[line('keep',450,450)])
        changed = self.image.copy()
        changed[100,100] = 1
        changed[850,850] = 1
        calls = []
        def infer(image,native):
            calls.append((image.shape,native))
            return [line('fresh',450,450)]
        _, info = engine.run(changed,infer)
        self.assertEqual(info['mode'],'full')
        self.assertEqual(info['area_ratio'],1.)
        self.assertEqual(calls,[(self.image.shape,False)])

    def test_invalid_fresh_geometry_does_not_commit_cache(self):
        engine = IncrementalOCR()
        engine.run(self.image,lambda *_:[line('keep',800,800)])
        bad = line('bad',10,10)
        bad['polygon'][0][0] = float('nan')
        changed = self.image.copy()
        changed[100,100] = 1
        with self.assertRaises(ValueError):
            engine.run(changed,lambda *_:[bad])
        self.assertIs(engine.image,self.image)
        self.assertEqual(engine.partial_updates,0)


if __name__=='__main__':
    unittest.main()
