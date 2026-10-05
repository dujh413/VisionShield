"""Verify real DirectML detection/recognition on generated text only."""
import collections
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM']='offscreen'
import onnxruntime as ort
from PySide6.QtWidgets import QApplication
from fast_ocr import FastOCR
from ocr_test import synthetic_image
from sensitive_rules import detect


def check():
    if 'DmlExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('DirectML is not loaded; run Enable-GpuOcr.ps1 in the desktop virtual environment')
    app=QApplication.instance() or QApplication([])
    actual_session=ort.InferenceSession
    sessions=[]
    with tempfile.TemporaryDirectory(prefix='visionshield-gpu-check-') as directory:
        def create_session(*args,**kwargs):
            providers=kwargs.get('providers',[])
            names=[p[0] if isinstance(p,tuple) else p for p in providers]
            gpu='DmlExecutionProvider' in names
            if gpu:
                options=kwargs['sess_options']
                options.enable_profiling=True
                options.profile_file_prefix=str(Path(directory)/f'gpu_{len(sessions)}')
            session=actual_session(*args,**kwargs)
            if gpu:sessions.append(session)
            return session
        started=time.perf_counter()
        with patch.object(ort,'InferenceSession',side_effect=create_session):
            ocr=FastOCR(gpu=True)
        ready_ms=(time.perf_counter()-started)*1000
        if not ocr.use_dml or len(sessions)!=2:
            raise RuntimeError('Expected GPU detection and recognition sessions')
        if any(names[0]!='DmlExecutionProvider' for names in ocr.providers.values()):
            raise RuntimeError('OCR session fell back to CPU')
        image=synthetic_image('246810',32)
        started=time.perf_counter()
        lines=ocr.recognize(image)
        infer_ms=(time.perf_counter()-started)*1000
        text=''.join(line['text'] for line in lines)
        if not all(token in text for token in ('13800138000','246810','demo@example.com','视界盾')):
            raise RuntimeError('Synthetic GPU OCR recognition mismatch')
        categories={category for hit in detect(lines) for category in hit['categories']}
        if not {'手机号','验证码','邮箱'}.issubset(categories):
            raise RuntimeError('Synthetic GPU sensitive rules mismatch')
        kernels=[]
        for session in sessions:
            path=Path(session.end_profiling())
            events=json.loads(path.read_text(encoding='utf-8'))
            counts=collections.Counter(e.get('args',{}).get('provider') for e in events
                                       if e.get('cat')=='Node' and e.get('args',{}).get('provider'))
            if not counts['DmlExecutionProvider']:
                raise RuntimeError('No DirectML kernel execution in ORT profile')
            kernels.append(dict(counts))
        return {'passed':True,'ort_version':ort.__version__,'adapter':ocr.adapter,
                'providers':ocr.providers,'executed_kernel_counts':{'detection':kernels[0],'recognition':kernels[1]},
                'model_ready_ms':round(ready_ms,2),'synthetic_inference_ms':round(infer_ms,2),
                'fixture_lines':len(lines),'fixture_correct':True}


if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False))
