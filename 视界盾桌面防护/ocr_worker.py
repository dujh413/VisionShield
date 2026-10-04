import json
import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import numpy as np
import queue
import shutil
import time
from incremental_ocr import IncrementalOCR


MODEL_NAMES = ('PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_rec')


def model_path(root, name):
    source = Path(root)/'models'/name
    if str(source).isascii():
        return source
    # Paddle原生推理在Windows中文路径上可能读取失败；仅复制模型，无桌面内容。
    target = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'VisionShield'/'ocr_models'/name
    if not str(target).isascii():
        raise RuntimeError('Paddle模型需要英文路径，请将项目放到英文目录后重试')
    fingerprint = hashlib.sha256()
    for file in sorted(source.rglob('*')):
        if file.is_file():
            fingerprint.update(str(file.relative_to(source)).encode('utf-8'))
            fingerprint.update(file.read_bytes())
    digest = fingerprint.hexdigest()
    marker = target/'source.sha256'
    if not marker.exists() or marker.read_text(encoding='ascii') != digest:
        shutil.copytree(source, target, dirs_exist_ok=True)
        marker.write_text(digest, encoding='ascii')
    return target


def build_ocr(root, download=False, settings=None):
    # 运行时显式使用本地目录；初始化不发送桌面图像到网络。
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    from paddleocr import PaddleOCR
    kwargs = dict(text_detection_model_name=MODEL_NAMES[0], text_recognition_model_name=MODEL_NAMES[1],
                  use_doc_orientation_classify=False, use_doc_unwarping=False,
                  use_textline_orientation=False, device='cpu', enable_mkldnn=False,
                  cpu_threads=4, text_rec_score_thresh=0.0)
    if settings:
        kwargs.update(settings)
    if not download:
        for name in MODEL_NAMES:
            if not (Path(root)/'models'/name/'inference.yml').exists():
                raise RuntimeError('缺少本地OCR模型，请先运行 prepare_models.py')
        kwargs.update(text_detection_model_dir=str(model_path(root, MODEL_NAMES[0])),
                      text_recognition_model_dir=str(model_path(root, MODEL_NAMES[1])))
    return PaddleOCR(**kwargs)


def prepare(root):
    build_ocr(root, download=True)
    cache = Path.home()/'.paddlex'/'official_models'
    target = Path(root)/'models'
    target.mkdir(exist_ok=True)
    for name in MODEL_NAMES:
        shutil.copytree(cache/name, target/name, dirs_exist_ok=True)
    (target/'manifest.json').write_text(json.dumps({'models': MODEL_NAMES, 'mode': 'local_cpu'}), encoding='utf-8')


def recognize(ocr, image, preserve_scale=False):
    options = {}
    if preserve_scale:
        # 小变化区不能按短边放大到736，否则裁剪反而更慢。
        options = {'text_det_limit_side_len': max(image.shape[:2]), 'text_det_limit_type':'max'}
    result = list(ocr.predict(image, **options))[0]
    texts, scores = result['rec_texts'], result['rec_scores']
    polygons = result['rec_polys']
    lines = [{'text': str(text), 'confidence': float(score),
              'polygon': polygon.tolist() if hasattr(polygon, 'tolist') else polygon}
             for text, score, polygon in zip(texts, scores, polygons)]
    # 未被识别输出覆盖的检测框也不能直接当安全。
    for polygon in result.get('dt_polys', []):
        if not any(np.array_equal(polygon,line['polygon']) for line in lines):
            lines.append({'text': '', 'confidence': 0.0,
                          'polygon': polygon.tolist() if hasattr(polygon, 'tolist') else polygon})
    return lines


def put_latest(channel, item):
    try:
        channel.put_nowait(item)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(item)
        except queue.Full:
            pass


def process_main(root, inputs, outputs, backend='fast'):
    try:
        if backend=='fast':
            from fast_ocr import FastOCR
            ocr=FastOCR()
            infer=ocr.recognize
            providers=ocr.providers
        else:
            ocr = build_ocr(root)
            infer=lambda image,native:recognize(ocr,image,native)
            providers={'backend':'paddle_cpu'}
        outputs.put({'ready': True,'backend':backend,'providers':providers})
        incremental = IncrementalOCR()
        while True:
            frame = inputs.get()
            if frame is None:
                return
            started = time.monotonic()
            lines, metrics = incremental.run(frame.image, infer)
            put_latest(outputs, {'frame_id': frame.frame_id, 'captured_at': frame.captured_at,
                                 'ocr_finished_at': time.monotonic(), 'image': frame.image,
                                 'lines': lines, 'cached': metrics['mode']=='cached',
                                 'mode': metrics['mode'], 'area_ratio': metrics['area_ratio'],
                                 'elapsed_ms': (time.monotonic()-started)*1000})
    except Exception as error:
        # 不保存OCR结果或桌面原文，异常详情只出现在终端。
        import traceback
        traceback.print_exc()
        put_latest(outputs, {'error': type(error).__name__})


class OCRWorker:
    def __init__(self, root, backend='fast'):
        ctx = mp.get_context('spawn')
        self.inputs, self.outputs = ctx.Queue(1), ctx.Queue(2)
        self.process = ctx.Process(target=process_main, args=(str(root), self.inputs, self.outputs,backend), daemon=True)
        self.process.start()

    def submit(self, frame):
        put_latest(self.inputs, frame)

    def poll(self):
        items = []
        while True:
            try:
                items.append(self.outputs.get_nowait())
            except queue.Empty:
                return items

    def close(self):
        self.process.terminate()
        self.process.join(timeout=2)
        # 强制停止子进程时，不等待仍含屏幕图像的队列馈送线程。
        self.inputs.cancel_join_thread()
        self.outputs.cancel_join_thread()
        self.inputs.close()
        self.outputs.close()
