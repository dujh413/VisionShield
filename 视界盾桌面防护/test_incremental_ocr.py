import unittest
import numpy as np
from incremental_ocr import IncrementalOCR


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


if __name__=='__main__':
    unittest.main()
