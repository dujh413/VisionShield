"""仅虚构桌面：验证本地ONNX推理耗时和关键文字。"""
import argparse
import json
import os
from pathlib import Path
import statistics
import time
import numpy as np
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from ocr_test import synthetic_image
from fast_ocr import FastOCR
from incremental_ocr import IncrementalOCR


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--det-long',type=int,default=1536)
    parser.add_argument('--small',action='store_true')
    args=parser.parse_args()
    app=QApplication([])
    backend=FastOCR(not args.cpu,args.det_long)
    first=np.full((1600,2560,3),255,dtype=np.uint8)
    second=first.copy()
    first[200:560,80:1080]=synthetic_image('246810',12 if args.small else 24)
    second[200:560,80:1080]=synthetic_image('135790',12 if args.small else 24)
    # 热身不计入稳态，冷启动由软件启动状态单独处理。
    backend.recognize(first)
    full=[]; partial=[]; correct=True
    for i in range(5):
        engine=IncrementalOCR()
        start=time.perf_counter()
        lines,_=engine.run(first,backend.recognize)
        full.append((time.perf_counter()-start)*1000)
        start=time.perf_counter()
        lines,metrics=engine.run(second,backend.recognize)
        partial.append((time.perf_counter()-start)*1000)
        text=''.join(line['text'] for line in lines)
        correct &= all(t in text for t in ('视界盾','13800138000','135790','demo@example.com')) and '246810' not in text
    print(json.dumps({'providers':backend.providers,'samples':5,
                      'full_median_ms':round(statistics.median(full),1),'full_max_ms':round(max(full),1),
                      'partial_median_ms':round(statistics.median(partial),1),'partial_max_ms':round(max(partial),1),
                      'fixture_correct':correct,'area_ratio':round(metrics['area_ratio'],3)}))
    if not correct:
        raise RuntimeError('Fast OCR synthetic correctness check failed')
