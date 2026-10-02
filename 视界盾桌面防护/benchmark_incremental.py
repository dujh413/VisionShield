"""虚构2560x1600桌面：改一行数字，比较整屏与局部。不采集真实桌面。"""
import json
import os
from pathlib import Path
import time
import numpy as np

os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from ocr_test import synthetic_image
from ocr_worker import build_ocr, recognize
from incremental_ocr import IncrementalOCR


def desktop(code):
    image=np.full((1600,2560,3),255,dtype=np.uint8)
    image[200:560,80:1080]=synthetic_image(code)
    return image


if __name__=='__main__':
    app=QApplication([])
    ocr=build_ocr(Path(__file__).resolve().parent)
    engine=IncrementalOCR()
    infer=lambda image,native:recognize(ocr,image,native)
    first,second=desktop('246810'),desktop('135790')
    engine.run(first,infer)
    start=time.monotonic()
    lines,info=engine.run(second,infer)
    partial_ms=(time.monotonic()-start)*1000
    start=time.monotonic()
    reference=recognize(ocr,second)
    full_ms=(time.monotonic()-start)*1000
    text=''.join(line['text'] for line in lines)
    full_text=''.join(line['text'] for line in reference)
    required=['视界盾','13800138000','135790','demo@example.com']
    passed=all(token in text and token in full_text for token in required) and '246810' not in text
    print(json.dumps({'mode':info['mode'],'area_ratio':round(info['area_ratio'],3),
                      'partial_ms':round(partial_ms,1),'full_ms':round(full_ms,1),
                      'tokens_correct_and_old_code_removed':passed}))
    if not passed or info['mode']!='partial':
        raise RuntimeError('Incremental synthetic verification failed')
