"""YuNet+SFace登记与自动重新确认；仅输出保护请求，不连接字段。"""
import argparse
import csv
from datetime import datetime
from pathlib import Path
import time

import cv2
import numpy as np

from camera_test import open_camera, window_closed
from owner_tracking import ShortTracker
from identity_state import IdentityGate
from identity_sender import IdentitySender
from face_detection import FaceScanner


def load_models(root):
    # 使用内存加载，避免Windows中文路径被OpenCV文件接口误解码。
    detector_buffer = np.frombuffer((root / 'models/face_detection_yunet_2023mar.onnx').read_bytes(), dtype=np.uint8)
    recognizer_buffer = np.frombuffer((root / 'models/face_recognition_sface_2021dec.onnx').read_bytes(), dtype=np.uint8)
    empty = np.empty(0, dtype=np.uint8)
    detector = cv2.FaceDetectorYN.create(
        'onnx', detector_buffer, empty, (640, 480), 0.6, 0.45)
    try:
        recognizer = cv2.FaceRecognizerSF.create('onnx', recognizer_buffer, empty)
    except TypeError:
        # 较旧OpenCV仅支持文件参数；本机模型缓存使用英文路径。
        import os
        import shutil
        cache = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'VisionShield/face_models'
        cache.mkdir(parents=True, exist_ok=True)
        target = cache/'face_recognition_sface_2021dec.onnx'
        if not str(target).isascii():
            raise RuntimeError('当前OpenCV需要英文模型路径，请升级OpenCV后重试')
        source = root/'models/face_recognition_sface_2021dec.onnx'
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
        recognizer = cv2.FaceRecognizerSF.create(str(target), '')
    return detector, recognizer


def extract(frame, face, recognizer, diagnostics=None, min_sharpness=60):
    x, y, w, h = face[:4]
    if min(w, h) < 80:
        if diagnostics is not None:diagnostics['quality_reason']='too_small'
        return None
    crop = recognizer.alignCrop(frame, face)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness,brightness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),float(gray.mean())
    if diagnostics is not None:
        # 策略使用原始精度；显示/日志在元数据边界统一四舍五入。
        diagnostics.update(sharpness=sharpness,brightness=brightness)
    if sharpness < min_sharpness or not 40 <= brightness <= 220:
        if diagnostics is not None:diagnostics['quality_reason']='blur' if sharpness < min_sharpness else 'brightness'
        return None
    feature = recognizer.feature(crop).reshape(-1)
    norm = float(np.linalg.norm(feature))
    if not np.isfinite(feature).all() or not np.isfinite(norm) or norm<1e-9:
        if diagnostics is not None:diagnostics['quality_reason']='invalid_feature'
        return None
    if diagnostics is not None:
        diagnostics['quality_reason']='accepted'
        diagnostics['quality_level']='moderate_blur' if sharpness<60 else 'clear'
    return feature / norm


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='E enroll; D delete template; Q quit. Signal only.')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=['auto', 'dshow', 'msmf'], default='auto')
    parser.add_argument('--threshold', type=float, default=0.45)
    parser.add_argument('--check-models', action='store_true')
    args = parser.parse_args()
    if not 0 < args.threshold < 1:
        parser.error('threshold must be between 0 and 1')
    detector, recognizer = load_models(root)
    if args.check_models:
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        detector.detect(blank)
        recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
        print('Both models loaded and inference passed; camera not opened.')
        return
    private = root / 'private'
    private.mkdir(exist_ok=True)
    template_path = private / 'owner_templates.npz'
    templates = None
    if template_path.exists():
        with np.load(template_path, allow_pickle=False) as data:
            templates = data['features'].copy()
        if templates.ndim != 2 or templates.shape[0] < 1 or not np.isfinite(templates).all():
            raise ValueError('Invalid template. Delete private/owner_templates.npz and enroll again.')
    tracker, gate = ShortTracker(), IdentityGate()
    scanner = FaceScanner(detector)
    samples, enrolling, enroll_id = [], False, None
    last_sample, last_ms = 0, -1
    camera = None
    sender = IdentitySender()
    records = root / 'records'
    records.mkdir(exist_ok=True)
    log_path = records / ('identity_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
    name = 'Owner Identity - E enroll (local save), D delete, Q exit'
    message = 'E: enroll with only yourself visible; saves local feature templates'
    start = time.perf_counter()
    try:
        camera = open_camera(args.camera, args.backend, resolution=(1280, 720))
        with log_path.open('w', encoding='utf-8-sig', newline='') as log:
            writer = csv.writer(log)
            writer.writerow(['ms', 'state', 'faces', 'owner_track', 'best_score', 'protect_request', 'enroll_samples'])
            while True:
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError('Camera read failed')
                height, width = frame.shape[:2]
                ms = max(last_ms + 1, int((time.perf_counter() - start) * 1000))
                last_ms = ms
                faces = scanner.detect(frame)
                boxes = [(float(f[0])/width, float(f[1])/height,
                          float(f[0]+f[2])/width, float(f[1]+f[3])/height) for f in faces]
                tracks = tracker.update(boxes, ms)
                features = [extract(frame, f, recognizer) for f in faces]
                scores = [None if templates is None or feature is None else
                          float(np.max(templates @ feature)) for feature in features]
                if enrolling:
                    if len(tracks) != 1 or not tracks[0].reliable or features[0] is None:
                        samples, enroll_id = [], None
                        message = 'Enroll: one clear face only; samples reset on loss'
                    elif enroll_id is not None and tracks[0].track_id != enroll_id:
                        samples, enroll_id = [], None
                        message = 'Enroll: track changed; samples reset'
                    else:
                        enroll_id = tracks[0].track_id
                        if ms - last_sample >= 350:
                            samples.append(features[0])
                            last_sample = ms
                        message = f'Enroll {len(samples)}/12: gently turn left/right; keep face visible'
                        if len(samples) >= 12:
                            templates = np.stack(samples)
                            np.savez_compressed(template_path, features=templates)
                            enrolling = False
                            gate.update(None)
                            message = 'Saved local templates. Look forward for verification.'
                matches = [track.track_id for track, score in zip(tracks, scores)
                           if track.reliable and score is not None and score >= args.threshold]
                candidate = matches[0] if len(matches) == 1 and not enrolling else None
                verified = gate.update(candidate)
                owner_id = candidate if verified else None
                state = ('ENROLLING' if enrolling else 'NOT_ENROLLED' if templates is None else
                         'OWNER_VERIFIED' if verified else 'VERIFYING' if candidate is not None else
                         'OWNER_NOT_CONFIRMED')
                protect = owner_id is None or len(faces) != 1
                sender.send(verified, protect, len(faces))
                for track, face, score in zip(tracks, faces, scores):
                    x, y, w, h = [int(v) for v in face[:4]]
                    is_owner = track.track_id == owner_id
                    color = (0, 255, 0) if is_owner else (0, 180, 255)
                    cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                    label = 'OWNER' if is_owner else 'PENDING/OTHER'
                    score_text = '--' if score is None else f'{score:.3f}'
                    cv2.putText(frame, f'{track.track_id} {label} score={score_text}',
                                (x, max(90, y-5)), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
                cv2.putText(frame, f'{state} PROTECT_REQUEST={int(protect)}', (8, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, .48, (0, 220, 255), 1)
                cv2.putText(frame, message, (8, 40), cv2.FONT_HERSHEY_SIMPLEX, .38, (255,255,255), 1)
                cv2.putText(frame, 'SIGNAL ONLY; no field hiding; E saves biometric template locally',
                            (8, 60), cv2.FONT_HERSHEY_SIMPLEX, .35, (0,220,255), 1)
                best = max((s for s in scores if s is not None), default=None)
                writer.writerow([ms, state, len(faces), owner_id, best, int(protect), len(samples)])
                cv2.imshow(name, frame)
                key = cv2.waitKey(1) & 0xff
                if key in (ord('e'), ord('E')):
                    samples, enroll_id, enrolling = [], None, True
                    gate.update(None)
                    message = 'Enroll starts: only owner visible; old template replaced on completion'
                    log.flush()
                if key in (ord('d'), ord('D')):
                    template_path.unlink(missing_ok=True)
                    templates, samples, enroll_id, enrolling = None, [], None, False
                    gate.update(None)
                    message = 'Template deleted. E to enroll again.'
                    log.flush()
                if key in (ord('q'), ord('Q'), 27) or window_closed(name):
                    break
    finally:
        sender.close()
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()
        print('Log:', log_path)


if __name__ == '__main__':
    main()
