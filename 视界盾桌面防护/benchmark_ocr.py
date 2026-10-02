"""仅测虚构文字，不采集桌面；串行比较配置，避免同时抢CPU。"""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from ocr_test import synthetic_image
from ocr_worker import build_ocr, recognize


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mkldnn', action='store_true')
    parser.add_argument('--batch', type=int, default=1)
    parser.add_argument('--det-max', type=int)
    args = parser.parse_args()
    app = QApplication([])
    settings = {'enable_mkldnn': args.mkldnn, 'text_recognition_batch_size': args.batch}
    if args.det_max:
        settings.update(text_det_limit_side_len=args.det_max, text_det_limit_type='max')
    ocr = build_ocr(Path(__file__).resolve().parent, settings=settings)
    image = synthetic_image()
    times = []
    correct = True
    for index in range(4):
        start = time.monotonic()
        lines = recognize(ocr, image)
        duration = (time.monotonic()-start)*1000
        text = ''.join(line['text'] for line in lines)
        correct &= all(token in text for token in ['视界盾','13800138000','246810','demo@example.com'])
        if index:
            times.append(duration)
    print(json.dumps({'settings':settings,'median_warm_ms':round(statistics.median(times),1),
                      'samples_ms':[round(t,1) for t in times], 'fixture_correct':correct}))
