"""Synthetic pipeline comparison: never reads the screen, camera or user text."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
os.environ['QT_QPA_PLATFORM']='offscreen'
import numpy as np
from PySide6.QtWidgets import QApplication
from ocr_test import synthetic_image
from fast_ocr import FastOCR
from incremental_ocr import IncrementalOCR
from content_index import ContentIndex
from content_state import ContentState


def load_baseline(path, name):
    path=Path(path)
    if not (path/(name+'.py')).exists():
        path=path/'视界盾桌面防护'
    spec=importlib.util.spec_from_file_location('baseline_'+name,path/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(values):
    return {'median_ms':round(statistics.median(values),2),
            'p95_ms':round(float(np.percentile(values,95)),2),
            'max_ms':round(max(values),2),'first_ms':round(values[0],2),'samples':len(values)}


def benchmark_active_state(state_cls=ContentState, samples=10, warmups=2):
    """Measure the actual controller state, without loading any OCR models.

    All 140 stable sensitive lines must remain confirmed while a corner pixel
    remains protected as unknown. Timings are CPU region checks, not OCR or
    screen-to-overlay latency. Each iteration starts with independent state.
    """
    if samples < 1 or warmups < 0:
        raise ValueError('invalid region benchmark sample count')
    image=np.zeros((1600,2560,3),dtype=np.uint8)
    lines=[{'text':'13800138000','confidence':.99,
            'polygon':[[x,y],[x+900,y],[x+900,y+18],[x,y+18]]}
           for x in (50,1300) for y in range(20,1560,22)]
    changed=image.copy();changed[1590,2550]=255
    observe_times=[];accept_times=[];checks=[];counts=[];unknown_counts=[]
    for iteration in range(samples+warmups):
        state=state_cls()
        state.observe(SimpleNamespace(image=image,frame_id=1,captured_at=0.))
        initial=state.accept({'image':image,'frame_id':1,'captured_at':0.,
                              'lines':lines,'unknown_regions':[]},0.)
        started=time.perf_counter()
        state.observe(SimpleNamespace(image=changed,frame_id=3,captured_at=.1))
        observe_ms=(time.perf_counter()-started)*1000
        started=time.perf_counter()
        # A late result from the unchanged frame preceding the corner change.
        accepted=state.accept({'image':image,'frame_id':2,'captured_at':.05,
                               'lines':lines,'unknown_regions':[]},.1)
        accept_ms=(time.perf_counter()-started)*1000
        view=state.view(.1)
        corner_covered=any(x<=2550<x+w and y<=1590<y+h for x,y,w,h in view['rectangles'])
        checks.append(initial and accepted and len(view['hits'])==140
                      and view['valid_lines']==140 and not view['full']
                      and view['coordinates_valid'] and not view['coverage_complete']
                      and corner_covered)
        if iteration>=warmups:
            observe_times.append(observe_ms);accept_times.append(accept_ms)
            counts.append(len(view['hits']));unknown_counts.append(view['unknown_regions'])
    return {'observe':summarize(observe_times),'accept':summarize(accept_times),
            'fixture_correct':all(checks),'hit_counts':counts,'unknown_region_counts':unknown_counts,
            'scope':{'resolution':[2560,1600],'fixture_lines':140,'warmups':warmups,
                     'samples':samples,'screen_capture':False,'camera':False,'ocr_inference':False}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--baseline',type=Path,help='optional separate checkout of the old source')
    args=parser.parse_args()
    if not 2<=args.samples<=200:parser.error('--samples must be between 2 and 200')
    app=QApplication.instance() or QApplication([])
    first=np.full((1600,2560,3),255,dtype=np.uint8)
    first[100:460,40:1040]=synthetic_image('246810',32)
    first[1200:1560,1400:2400]=synthetic_image('975310',32)
    second=first.copy()
    second[100:460,40:1040]=synthetic_image('135790',32)
    second[1200:1560,1400:2400]=synthetic_image('864209',32)
    started=time.perf_counter()
    backend=FastOCR(not args.cpu)
    cold_ms=(time.perf_counter()-started)*1000
    backend.recognize(first)
    implementations=[('current',IncrementalOCR,ContentIndex,ContentState)]
    if args.baseline:
        has_state=any((path/'content_state.py').is_file()
                      for path in (args.baseline,args.baseline/'视界盾桌面防护'))
        baseline_state=load_baseline(args.baseline,'content_state').ContentState if has_state else None
        implementations.insert(0,('baseline',load_baseline(args.baseline,'incremental_ocr').IncrementalOCR,
                                  load_baseline(args.baseline,'content_index').ContentIndex,baseline_state))
    result={'scope':{'resolution':[2560,1600],'ocr_fixture_lines':8,'index_fixture_lines':140,
                     'screen_capture':False,'camera':False,'providers':backend.providers},
            'initialization_and_warmup_ms':round(cold_ms,2)}
    correct=True
    for label,incremental,index_cls,state_cls in implementations:
        values=[];full=[];areas=[];modes=[];checks=[];line_counts=[]
        for _ in range(args.samples):
            engine=incremental()
            started=time.perf_counter();engine.run(first,backend.recognize)
            full.append((time.perf_counter()-started)*1000)
            started=time.perf_counter();lines,metrics=engine.run(second,backend.recognize)
            values.append((time.perf_counter()-started)*1000)
            text=''.join(line['text'] for line in lines)
            checks.append(all(word in text for word in ('13800138000','demo@example.com','135790','864209'))
                          and '246810' not in text and '975310' not in text)
            line_counts.append(len(lines));areas.append(metrics['area_ratio']);modes.append(metrics['mode'])
        image=np.zeros((1600,2560,3),dtype=np.uint8)
        lines=[{'text':'13800138000','confidence':.99,
                'polygon':[[x,y],[x+900,y],[x+900,y+18],[x,y+18]]}
               for x in (50,1300) for y in range(20,1560,22)]
        index=index_cls();index.update(image);index.accept(image,lines)
        index_times={}
        for stage in ('update','accept'):
            samples=[]
            for _ in range(12):
                current=image.copy()
                started=time.perf_counter()
                index.update(current) if stage=='update' else index.accept(current,lines)
                samples.append((time.perf_counter()-started)*1000)
            index_times[stage]=summarize(samples[2:])
        result[label]={'full':summarize(full),'change':summarize(values),'fixture_correct':all(checks),
                       'line_counts':line_counts,'area_ratio_median':round(statistics.median(areas),6),
                       'modes':sorted(set(modes)),'content_index':index_times}
        if state_cls is None:
            result[label]['content_state']={'omitted':True,
                                            'reason':'baseline source does not include content_state.py'}
        else:
            state_metrics=benchmark_active_state(state_cls)
            result[label]['content_state']=state_metrics
            correct &= state_metrics['fixture_correct']
        correct &= all(checks)
    print(json.dumps(result,ensure_ascii=True))
    if not correct:raise SystemExit('Synthetic fixture recognition mismatch')


if __name__=='__main__':main()
