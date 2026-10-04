"""后台摄像头身份识别，只传状态；不传输或保存路人的面部特征。"""
import multiprocessing as mp
from pathlib import Path
import queue
import sys
import time
from runtime_paths import camera_root, owner_file


def camera_main(root, stop, outputs, preview=False):
    camera = None
    try:
        sys.path.insert(0, str(root))
        import cv2
        import numpy as np
        from identity_test import load_models, extract
        from camera_test import open_camera
        from owner_tracking import ShortTracker
        from identity_state import IdentityGate
        from ocr_worker import put_latest
        cv2.setNumThreads(1)
        detector, recognizer = load_models(Path(root))
        path = owner_file(root)
        templates = None
        if path.exists():
            with np.load(path, allow_pickle=False) as data:
                templates = data['features'].copy()
            if templates.ndim != 2 or not len(templates) or not np.isfinite(templates).all():
                raise ValueError('Invalid owner template')
        tracker, gate = ShortTracker(), IdentityGate()
        camera = open_camera(0, 'auto')
        sequence = 0
        started = time.monotonic()
        while not stop.is_set():
            before = time.monotonic()
            ok, image = camera.read()
            if not ok:
                raise RuntimeError('Camera read failed')
            height, width = image.shape[:2]
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
            faces = [] if faces is None else list(faces)
            boxes = [(float(f[0])/width, float(f[1])/height,
                      float(f[0]+f[2])/width, float(f[1]+f[3])/height) for f in faces]
            tracks = tracker.update(boxes, int((before-started)*1000))
            matches = []
            scores = []
            if templates is not None:
                for track, face in zip(tracks, faces):
                    feature = extract(image, face, recognizer)
                    score = float(np.max(templates@feature)) if feature is not None else None
                    if score is not None:
                        scores.append(score)
                    if track.reliable and score is not None and score >= .45:
                        matches.append(track.track_id)
            verified = gate.update(matches[0] if len(matches) == 1 else None)
            sequence += 1
            item = {'sequence':sequence, 'observed_at':before,
                       'owner_verified':verified, 'faces_count':len(faces),
                       'protect_request':not verified or len(faces)!=1,
                       'enrolled':templates is not None}
            if preview:
                item['brightness'] = round(float(image.mean()),1)
                item['best_score'] = max(scores,default=None)
                for f in faces:
                    x,y,w,h=map(int,f[:4]);cv2.rectangle(image,(x,y),(x+w,y+h),(0,180,255),2)
                ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,70])
                if ok:item['preview']=encoded.tobytes()
            put_latest(outputs, item)
            stop.wait(max(0, .1-(time.monotonic()-before)))
    except Exception as error:
        from ocr_worker import put_latest
        put_latest(outputs, {'error':type(error).__name__})
    finally:
        if camera is not None:
            camera.release()


class CameraWorker:
    def __init__(self, preview=False):
        ctx = mp.get_context('spawn')
        self.stop, self.outputs = ctx.Event(), ctx.Queue(2)
        root = camera_root()
        self.process = ctx.Process(target=camera_main, args=(root,self.stop,self.outputs,preview), daemon=True)
        self.process.start()
        self.last, self.error = None, None

    def poll(self):
        while True:
            try:
                item = self.outputs.get_nowait()
            except queue.Empty:
                break
            if 'error' in item:
                self.error = item['error']
            else:
                self.last = item
        if not self.process.is_alive():
            self.error = self.error or 'Camera process exited'

    def risk(self, now):
        if self.error:
            return True, '摄像头异常：'+self.error
        if self.last is None:
            return True, '摄像头启动中'
        if now-self.last['observed_at'] > 1.5:
            return True, '摄像头状态已过期'
        if not self.last['enrolled']:
            return True, '请先在设置中登记机主'
        risk = self.last['protect_request']
        reason = '检测到旁人' if self.last['faces_count']>1 else '机主未确认' if risk else '机主独处且已确认'
        return risk, reason

    def close(self):
        self.stop.set()
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        self.outputs.cancel_join_thread()
        self.outputs.close()
