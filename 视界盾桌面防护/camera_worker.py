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


class StrangerJournal:
    """后续状态保留真实旁人观察边沿；短暂风险保持不产生新观察。"""
    def __init__(self):
        self.sequence=0
        self.observed_at=None

    def record(self, sequence, observed_at, detected):
        if detected:
            self.sequence=sequence
            self.observed_at=observed_at
        return {'last_stranger_sequence':self.sequence,
                'last_stranger_observed_at':self.observed_at}


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
        journal=StrangerJournal()
        camera = open_camera(0, 'auto', resolution=(1280, 720))
        reader = LatestCameraFrame(camera)
        sequence = 0
        started = time.monotonic()
        while not stop.is_set():
            before = time.monotonic()
            ok, image = reader.read()
            if not ok:
                raise RuntimeError('Camera read failed')
            observed_at = reader.last_consumed_at
            height, width = image.shape[:2]
            faces = scanner.detect(image, observed_at)
            boxes = [(float(f[0])/width, float(f[1])/height,
                      float(f[0]+f[2])/width, float(f[1]+f[3])/height) for f in faces]
            tracks = tracker.update(boxes, int((observed_at-started)*1000))
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
            identity = presence.update(observed_at, observations, enrolled=templates is not None)
            candidate_pending=templates is not None and scanner.current_unconfirmed_count>0
            if candidate_pending:identity['protect_request']=True
            event=journal.record(sequence+1,observed_at,identity['stranger_detected'])
            if templates is not None and bystander.update(observed_at, identity['stranger_detected']):
                identity.update(stranger_detected=True, protect_request=True,
                                owner_session_active=False, pose_grace=False)
            sequence += 1
            published_at = time.monotonic()
            item = {'sequence':sequence, 'observed_at':observed_at,
                       **identity, 'faces_count':len(faces),
                       'enrolled':templates is not None, 'candidate_pending':candidate_pending,
                       **scanner.last_metrics, **event,
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
        self.last_stranger_sequence=0
        self.new_stranger_event=False

    def accept_status(self, item):
        """不让排队/丢旧状态消掉真实风险事件，拒绝倒序或无效状态。"""
        if not isinstance(item,dict):
            self.error='Invalid camera status'
            return False
        sequence=item.get('sequence');observed_at=item.get('observed_at')
        marker=item.get('last_stranger_sequence',0)
        event_at=item.get('last_stranger_observed_at')
        if (type(sequence) is not int or sequence<1 or type(observed_at) not in (int,float)
                or not isfinite(observed_at) or type(marker) is not int or not 0<=marker<=sequence
                or any(type(item.get(key)) is not bool for key in ('enrolled','protect_request','stranger_detected'))
                or (marker and (type(event_at) not in (int,float) or not isfinite(event_at) or event_at>observed_at))):
            self.error='Invalid camera status'
            return False
        if self.last and (sequence<=self.last['sequence'] or observed_at<=self.last['observed_at']):
            return False
        if marker>self.last_stranger_sequence:
            self.last_stranger_sequence=marker
            self.new_stranger_event=True
        self.last=item
        return True

    def poll(self):
        self.new_stranger_event=False
        while True:
            try:
                item = self.outputs.get_nowait()
            except queue.Empty:
                break
            if isinstance(item,dict) and 'error' in item:
                self.error = item['error']
            else:
                self.accept_status(item)
        if not self.process.is_alive():
            self.error = self.error or 'Camera process exited'

    def risk(self, now):
        if self.error:
            return True, '摄像头异常：'+self.error
        if self.last is None:
            return True, '摄像头启动中'
        if now < self.last['observed_at'] or now-self.last['observed_at'] > 1.5:
            return True, '摄像头状态已过期'
        if not self.last['enrolled']:
            return True, '请先在设置中登记机主'
        if self.new_stranger_event:
            return True, '近期检测到旁人，等待连续安全观察后恢复'
        risk = self.last['protect_request'] or self.last['stranger_detected']
        reason = ('检测到陌生人或旁人' if self.last.get('stranger_detected') else
                  '候选人脸待确认，暂时保护' if self.last.get('candidate_pending') else
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
