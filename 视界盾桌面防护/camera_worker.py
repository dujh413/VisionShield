"""后台摄像头身份识别，只传状态；不传输或保存路人的面部特征。"""
import multiprocessing as mp
from math import isfinite
from pathlib import Path
import queue
import sys
import time
from runtime_paths import camera_root, owner_file


def identity_metadata(details, score, frontal, reliable):
    """队列/JSON边界只输出 Python 基础类型，不携带 NumPy 标量或特征。"""
    displayed=dict(details)
    for key in ('sharpness','brightness'):
        if key in displayed:displayed[key]=round(float(displayed[key]),2)
    return {**displayed,'owner_score':round(float(score),4) if score is not None else None,
            'frontal':bool(frontal),'reliable':bool(reliable)}


def identity_score_for_quality(score, sharpness):
    """中等模糊需更强身份匹配；严重模糊不用于确认机主。"""
    if score is None or sharpness is None or not isfinite(score) or not isfinite(sharpness) or sharpness < 20:return None
    return float(score) if sharpness >= 60 or score >= .60 else None


def camera_main(root, stop, outputs, preview=False, diagnostics=False, template_path=None):
    camera = None
    reader = None
    try:
        sys.path.insert(0, str(root))
        import cv2
        import numpy as np
        from identity_test import load_models, extract
        from camera_test import open_camera, LatestCameraFrame
        from face_detection import FaceScanner, BystanderHold
        from owner_tracking import ShortTracker
        from owner_presence import OwnerPresence, frontal_face
        from ocr_worker import put_latest
        cv2.setNumThreads(1)
        detector, recognizer = load_models(Path(root))
        path = Path(template_path) if template_path is not None else owner_file(root)
        templates = None
        if path.exists():
            with np.load(path, allow_pickle=False) as data:
                templates = data['features'].copy()
            if templates.ndim != 2 or not len(templates) or not np.isfinite(templates).all():
                raise ValueError('Invalid owner template')
        tracker, presence = ShortTracker(), OwnerPresence()
        scanner, bystander = FaceScanner(detector,diagnostics=diagnostics), BystanderHold()
        camera = open_camera(0, 'auto', resolution=(1280, 720))
        reader = LatestCameraFrame(camera)
        sequence = 0
        started = time.monotonic()
        while not stop.is_set():
            before = time.monotonic()
            ok, image = reader.read()
            if not ok:
                raise RuntimeError('Camera read failed')
            height, width = image.shape[:2]
            faces = scanner.detect(image, before)
            boxes = [(float(f[0])/width, float(f[1])/height,
                      float(f[0]+f[2])/width, float(f[1]+f[3])/height) for f in faces]
            tracks = tracker.update(boxes, int((before-started)*1000))
            observations = []
            identity_diagnostics=[]
            scores = []
            if templates is not None:
                for track, face in zip(tracks, faces):
                    details={}
                    # 登记仍使用默认60门限；运行中容许中等清晰度，但身份要求更严格。
                    feature = extract(image, face, recognizer, details, min_sharpness=20)
                    raw_score = float(np.max(templates@feature)) if feature is not None else None
                    score = identity_score_for_quality(raw_score,details.get('sharpness'))
                    if score is not None:
                        scores.append(score)
                    observations.append({'track_id':track.track_id, 'reliable':track.reliable,
                                         'bbox':track.bbox, 'score':score, 'frontal':frontal_face(face)})
                    if diagnostics:
                        details['identity_threshold']=.60 if details.get('sharpness',0)<60 else .45
                        details['identity_reason']='quality_match_rejected' if raw_score is not None and score is None else 'available'
                        identity_diagnostics.append(identity_metadata(details,raw_score,frontal_face(face),track.reliable))
            identity = presence.update(before, observations, enrolled=templates is not None)
            if templates is not None and bystander.update(before, identity['stranger_detected']):
                identity.update(stranger_detected=True, protect_request=True,
                                owner_session_active=False, pose_grace=False)
            sequence += 1
            published_at = time.monotonic()
            item = {'sequence':sequence, 'observed_at':before,
                       **identity, 'faces_count':len(faces),
                       'enrolled':templates is not None, **scanner.last_metrics,
                       'frame_age_ms':round((published_at-reader.last_consumed_at)*1000,2),
                       'processing_ms':round((published_at-before)*1000,2),
                       'face_sizes':[[round(float(f[2])),round(float(f[3]))] for f in faces],
                       'face_confidences':[round(float(f[14]),3) for f in faces]}
            if diagnostics:item['identity_diagnostics']=identity_diagnostics
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
        if reader is not None:
            reader.close()
        elif camera is not None:
            camera.release()


class CameraWorker:
    def __init__(self, preview=False, diagnostics=False, owner_path=None):
        ctx = mp.get_context('spawn')
        self.stop, self.outputs = ctx.Event(), ctx.Queue(2)
        root = camera_root()
        self.process = ctx.Process(target=camera_main, args=(root,self.stop,self.outputs,preview,diagnostics,owner_path), daemon=True)
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
        reason = ('检测到陌生人或旁人' if self.last.get('stranger_detected') else
                  '机主短时姿态宽限' if self.last.get('pose_grace') else
                  '机主未确认' if risk else '机主独处且已确认')
        return risk, reason

    def close(self):
        self.stop.set()
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        self.outputs.cancel_join_thread()
        self.outputs.close()
