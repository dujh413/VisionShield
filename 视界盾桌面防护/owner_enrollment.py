"""仅在本人打开登记窗口并点击登记后采集模板；预览和样本不保存图像。"""
import multiprocessing as mp
from pathlib import Path
import queue
import sys
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout


def enroll_main(root, stop, enroll, output):
    camera = None
    try:
        sys.path.insert(0,str(root))
        import cv2
        import numpy as np
        from camera_test import open_camera
        from identity_test import load_models,extract
        from owner_tracking import ShortTracker
        from ocr_worker import put_latest
        cv2.setNumThreads(1)
        detector,recognizer = load_models(root)
        tracker = ShortTracker()
        camera = open_camera(0,'auto')
        samples,track_id,last_sample = [],None,0
        begun = time.monotonic()
        while not stop.is_set():
            before=time.monotonic()
            ok,image=camera.read()
            if not ok:raise RuntimeError('Camera read failed')
            h,w=image.shape[:2]
            detector.setInputSize((w,h))
            _,faces=detector.detect(image)
            faces=[] if faces is None else list(faces)
            tracks=tracker.update([(float(f[0])/w,float(f[1])/h,float(f[0]+f[2])/w,float(f[1]+f[3])/h) for f in faces],int((before-begun)*1000))
            message='仅本人入镜，然后点击“开始登记”'
            if enroll.is_set():
                feature=extract(image,faces[0],recognizer) if len(faces)==1 else None
                if len(tracks)!=1 or not tracks[0].reliable or feature is None:
                    samples,track_id=[],None
                    message='请保持仅一张清晰人脸；样本已重置'
                elif track_id is not None and track_id!=tracks[0].track_id:
                    samples,track_id=[],None
                else:
                    track_id=tracks[0].track_id
                    if before-last_sample>=.35:
                        samples.append(feature)
                        last_sample=before
                    message=f'登记 {len(samples)}/12：缓慢轻转头，保持脸部可见'
                    if len(samples)>=12:
                        folder=root/'private'
                        folder.mkdir(exist_ok=True)
                        target=folder/'owner_templates.npz'
                        temporary=folder/'owner_templates.pending.npz'
                        np.savez_compressed(temporary,features=np.stack(samples))
                        temporary.replace(target)
                        put_latest(output,{'saved':True})
                        return
            for face in faces:
                x,y,fw,fh=map(int,face[:4])
                cv2.rectangle(image,(x,y),(x+fw,y+fh),(0,180,255),2)
            ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,75])
            put_latest(output,{'image':encoded.tobytes() if ok else b'','message':message})
            stop.wait(max(0,.1-(time.monotonic()-before)))
    except Exception as exc:
        from ocr_worker import put_latest
        put_latest(output,{'error':type(exc).__name__})
    finally:
        if camera is not None:camera.release()


class EnrollmentDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('登记机主 · 仅保存在本机')
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumSize(500,440)
        layout=QVBoxLayout(self)
        self.preview=QLabel('正在打开摄像头…')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(460,300)
        self.status=QLabel('登记仅本人面部特征，不保存照片或视频。关闭窗口可取消。')
        self.status.setWordWrap(True)
        self.begin=QPushButton('开始本人登记（更新本机模板）')
        layout.addWidget(self.preview);layout.addWidget(self.status);layout.addWidget(self.begin)
        ctx=mp.get_context('spawn')
        self.stop,self.enroll,self.output=ctx.Event(),ctx.Event(),ctx.Queue(2)
        root=Path(__file__).resolve().parents[1]/'视界盾开发'
        self.process=ctx.Process(target=enroll_main,args=(root,self.stop,self.enroll,self.output),daemon=True)
        self.process.start()
        self.begin.clicked.connect(self.enroll.set)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(100)
        self.finished.connect(self.cleanup)

    def poll(self):
        while True:
            try:item=self.output.get_nowait()
            except queue.Empty:break
            if item.get('saved'):
                self.status.setText('登记完成，下次启用防护时自动验证本人。')
                self.begin.setEnabled(False)
                self.timer.stop()
                QTimer.singleShot(1000,self.accept)
            elif item.get('error'):
                self.status.setText('登记失败：'+item['error'])
                self.begin.setEnabled(False)
                self.timer.stop()
            else:
                image=QImage.fromData(item['image'],'JPG')
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
                self.status.setText(item['message'])

    def cleanup(self,*args):
        self.timer.stop();self.stop.set();self.process.join(timeout=2)
        if self.process.is_alive():self.process.terminate();self.process.join(timeout=2)
        self.output.cancel_join_thread();self.output.close();self.preview.clear()
