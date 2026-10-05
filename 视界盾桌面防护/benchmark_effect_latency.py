"""Synthetic OCR/Qt latency comparison; never captures desktop or camera.

Uses production OCRWorker, ContentState and OverlayWindow. Capture exclusion is
bypassed only for the synthetic offscreen window, not changed in product code.
Neither paint completion nor these generated frames measure monitor output.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import time
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
import onnxruntime as ort
from PySide6.QtWidgets import QApplication
from blur_renderer import mask_crops
from content_state import ContentState
from mask_effect import parse_effect
from ocr_test import synthetic_image
from ocr_worker import OCRWorker
from overlay_window import OverlayWindow
from screen_capture import Frame


WIDTH, HEIGHT, PERIOD = 2560, 1600, .020


def stats(values):
    return {'median_ms':round(statistics.median(values),3),
            'p95_ms':round(float(np.percentile(values,95)),3),
            'max_ms':round(max(values),3),'first_ms':round(values[0],3),
            'samples':len(values)}


def fixture(number):
    codes = (str(200000+number),str(700000+number))
    image=np.full((HEIGHT,WIDTH,3),255,np.uint8)
    image[100:460,40:1040]=synthetic_image(codes[0],32)
    image[1200:1560,1400:2400]=synthetic_image(codes[1],32)
    return image,codes


def overlay_for(app, effect):
    with patch('overlay_window.exclude_capture'):
        overlay=OverlayWindow(app.primaryScreen())
    ratio=overlay.devicePixelRatioF()
    overlay.setGeometry(0,0,round(WIDTH/ratio),round(HEIGHT/ratio))
    overlay.set_effect(parse_effect(effect))
    app.processEvents()
    return overlay


def paint(app, overlay):
    # Real Qt raster painting, with neither screen scraping nor image export.
    overlay.repaint()
    app.processEvents()
    if overlay.last_paint_ms is None:
        raise RuntimeError('offscreen Qt did not paint')


def validate_painted_masks(overlay, boxes):
    """Read only this generated offscreen QWidget, after timing has stopped."""
    rendered=overlay.grab().toImage()
    for x,y,w,h in boxes:
        color=rendered.pixelColor(x+w//2,y+h//2)
        if color.alpha()!=255:
            raise RuntimeError('synthetic protected pixel was not opaque')
        if overlay.effect.mode=='block' and color.getRgb()!=(20,24,32,255):
            raise RuntimeError('synthetic block color mismatch')


def await_effect(app, overlay, rectangles, image, full, started, timeout=20):
    first_protected=None
    callback=[]
    next_poll=time.perf_counter()
    while time.perf_counter()-started<timeout:
        now=time.perf_counter()
        if now>=next_poll:
            tick=time.perf_counter()
            overlay.set_masks(rectangles,full=full,image=image)
            paint(app,overlay)
            callback.append((time.perf_counter()-tick)*1000)
            if first_protected is None:
                first_protected=(time.perf_counter()-started)*1000
            complete=(overlay.effect.mode=='block' or
                      (bool(overlay.blurs) and not overlay._fallback_boxes))
            if complete:
                return {'first_protection_ms':first_protected,
                        'final_effect_ms':(time.perf_counter()-started)*1000,
                        'worker_ms':overlay.blur_ms or 0.,
                        'paint_ms':overlay.last_paint_ms,
                        'max_ui_callback_ms':max(callback)}
            if overlay.last_render_error:
                raise RuntimeError('background box blur failed')
            next_poll=max(next_poll+PERIOD,time.perf_counter())
        app.processEvents()
        time.sleep(.001)
    raise TimeoutError('synthetic mask completion timeout')


def mask_only(app, mode, rectangles, full=False, samples=30, warmups=3):
    overlay=overlay_for(app,mode)
    values=[]
    image,_=fixture(0)
    boxes=mask_crops(rectangles,image.shape,8) if not full else ((0,0,WIDTH,HEIGHT),)
    try:
        for i in range(samples+warmups):
            # Clear geometry before each trial; keep the idle worker warm.
            overlay.set_masks([],image=None)
            paint(app,overlay)
            current=image.copy()
            for x,y,w,h in boxes:
                current[y+h//2,x+w//2]=(i+1)%255
            started=time.perf_counter()
            row=await_effect(app,overlay,rectangles,current,full,started)
            if i>=warmups:values.append(row)
        validate_painted_masks(overlay,boxes)
        return {'effect':parse_effect(mode).__dict__,'warmups':warmups,
                'painted_fixture_correct':True,
                'physical_crops':len(boxes),
                'pixel_area_ratio':round(sum(w*h for x,y,w,h in boxes)/(WIDTH*HEIGHT),6),
                **{key:stats([row[key] for row in values]) for key in values[0]}}
    finally:
        overlay.close()


def pipeline(app, mode, samples=30, warmups=3):
    overlay=overlay_for(app,mode)
    startup=time.perf_counter()
    worker=OCRWorker(Path(__file__).parent)
    state=ContentState(capture_timeout=1.5)
    ready=None
    rows=[]
    sensitive_rectangles=None
    try:
        deadline=time.perf_counter()+30
        while time.perf_counter()<deadline and ready is None:
            for item in worker.poll():
                if 'error' in item:raise RuntimeError(item['error'])
                if item.get('ready'):ready=item
            app.processEvents();time.sleep(.005)
        if ready is None:raise TimeoutError('model initialization timeout')
        init_ms=(time.perf_counter()-startup)*1000
        baseline_ms=None
        for number in range(samples+warmups+1):
            image,codes=fixture(number)
            frame=Frame(number+1,time.monotonic(),{},image)
            started=time.perf_counter()
            t=time.perf_counter();state.observe(frame)
            observe_ms=(time.perf_counter()-t)*1000
            view=state.view(time.monotonic())
            overlay.set_masks(view['rectangles'],full=view['full'],image=image)
            paint(app,overlay)
            first_protection_ms=(time.perf_counter()-started)*1000
            if not worker.submit(frame):raise RuntimeError('OCR submit failed')
            accepted=None
            index_ms=None
            next_poll=time.perf_counter()+PERIOD
            deadline=time.perf_counter()+20
            while time.perf_counter()<deadline:
                if time.perf_counter()>=next_poll:
                    for item in worker.poll():
                        if 'error' in item:raise RuntimeError(item['error'])
                        if 'lines' in item:
                            t=time.perf_counter()
                            if not state.accept(item,time.monotonic()):
                                raise RuntimeError('OCR result was not fresh')
                            index_ms=(time.perf_counter()-t)*1000
                            text=''.join(line['text'] for line in item['lines'])
                            if (len(item['lines'])!=8 or
                                not all(token in text for token in (*codes,'13800138000','demo@example.com'))):
                                raise RuntimeError('synthetic OCR correctness failed')
                            accepted=item
                    view=state.view(time.monotonic())
                    overlay.set_masks(view['rectangles'],full=view['full'],image=image)
                    paint(app,overlay)
                    final=(overlay.effect.mode=='block' or
                           (bool(overlay.blurs) and not overlay._fallback_boxes))
                    if accepted is not None and final and view['coverage_complete']:
                        if len(view['hits'])!=6:
                            raise RuntimeError('expected all six sensitive lines to be protected')
                        row={'capture_to_final_qt_ms':(time.perf_counter()-started)*1000,
                             'first_protection_ms':first_protection_ms,
                             'ocr_processing_ms':accepted['elapsed_ms'],
                             'queue_wait_ms':accepted.get('queue_wait_ms',0.),
                             'observe_ms':observe_ms,'accept_ms':index_ms,
                             'blur_worker_ms':overlay.blur_ms or 0.,
                             'paint_ms':overlay.last_paint_ms,
                             'ocr_area_ratio':accepted['area_ratio'],'mode':accepted['mode'],
                             'sensitive_lines':len(view['hits'])}
                        if number==0:baseline_ms=row['capture_to_final_qt_ms']
                        elif number>warmups:rows.append(row)
                        sensitive_rectangles=view['rectangles']
                        break
                    next_poll=max(next_poll+PERIOD,time.perf_counter())
                app.processEvents();time.sleep(.001)
            else:raise TimeoutError('OCR/Qt pipeline completion timeout')
            if number in (0,10,20,30):
                print(json.dumps({'progress':'pipeline','effect':mode,'completed':number,
                                  'total':samples+warmups},ensure_ascii=True),flush=True)
        validate_painted_masks(overlay,mask_crops(sensitive_rectangles,image.shape,8))
        numeric=('capture_to_final_qt_ms','first_protection_ms','ocr_processing_ms',
                 'queue_wait_ms','observe_ms','accept_ms','blur_worker_ms','paint_ms')
        return ({'effect':parse_effect(mode).__dict__,'warmups':warmups,
                 'providers':ready['providers'],'model_ready_ms':round(init_ms,3),
                 'first_full_frame_ms':round(baseline_ms,3),
                 'fixture_correct':True,'ocr_modes':sorted({r['mode'] for r in rows}),
                 'sensitive_line_counts':sorted({r['sensitive_lines'] for r in rows}),
                 'ocr_area_ratio_median':round(statistics.median(r['ocr_area_ratio'] for r in rows),6),
                 **{key:stats([row[key] for row in rows]) for key in numeric}},
                sensitive_rectangles)
    finally:
        worker.close()
        if worker.process.is_alive():raise RuntimeError('OCR process still running')
        overlay.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--large-samples',type=int,default=10)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 2<=args.samples<=200 or not 2<=args.large_samples<=200:
        parser.error('sample counts must be between 2 and 200')
    app=QApplication([])
    result={'scope':{'resolution':[WIDTH,HEIGHT],'ocr_fixture_lines':8,'qt':'offscreen raster',
                     'poll_interval_ms':20,'desktop_capture':False,'camera':False,
                     'application_tracking':False,'compositor_monitor':False,
                     'risk':'assumed active','image_copy_fixture_generation_timed':False},
            'environment':{'python':platform.python_version(),'ort':ort.__version__,
                           'available_providers':ort.get_available_providers()},
            'pipeline':{},'mask_only':{}}
    for label,effect in [('block','遮挡'),('blur_r8','8')]:
        measured,rectangles=pipeline(app,effect,args.samples)
        result['pipeline'][label]=measured
    dense=[(x,y,900,18) for x in (50,1300) for y in range(20,1560,22)]
    for name,boxes,full,count in [('six_sensitive_regions',rectangles,False,args.samples),
                                ('dense_140_lines',dense,False,args.large_samples),
                                ('full_screen',[],True,args.large_samples)]:
        result['mask_only'][name]={}
        for label,effect in [('block','遮挡'),('blur_r8','8')]:
            result['mask_only'][name][label]=mask_only(app,effect,boxes,full,count)
            print(json.dumps({'progress':'mask_only','scenario':name,'effect':label},ensure_ascii=True),flush=True)
    result['radius_comparison']={str(radius):mask_only(app,str(radius),rectangles,samples=args.samples)
                                 for radius in (16,32)}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'output':str(args.output)},ensure_ascii=True),flush=True)


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
