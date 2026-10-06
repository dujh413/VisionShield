"""人工配合的人脸验证；仅保存检测状态/耗时，不保存画面、特征或模板。"""
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import time

from camera_worker import CameraWorker
from runtime_paths import user_root


def planned_phase(elapsed,duration):
    if elapsed < duration*7/30:return 'owner_only'
    if elapsed < duration*23/30:return 'bystander_present'
    return 'recovery'


def preview_window():
    """显式诊断选项；JPEG在队列/Qt内存中显示，永不写入报告。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPixmap
    from PySide6.QtWidgets import QApplication,QLabel,QVBoxLayout,QWidget
    app=QApplication.instance() or QApplication([])
    class Preview(QWidget):
        def __init__(self):
            super().__init__();self.canceled=False
            self.setWindowTitle('视界盾 · 双人测试（画面只在内存中显示）')
            self.setWindowFlags(self.windowFlags()|Qt.WindowStaysOnTopHint)
            self.instructions=QLabel('正在启动摄像头；倒计时将在画面就绪后开始。')
            self.instructions.setWordWrap(True)
            self.instructions.setStyleSheet('font-size:20px;font-weight:bold;padding:12px;')
            self.image=QLabel();self.image.setFixedSize(768,432);self.image.setAlignment(Qt.AlignCenter)
            self.status=QLabel('请确认预览里能看到完整人脸。关闭窗口可取消。')
            self.status.setWordWrap(True)
            layout=QVBoxLayout(self);layout.addWidget(self.instructions);layout.addWidget(self.image);layout.addWidget(self.status)
        def show_sample(self,item,elapsed,duration,guided):
            phase=planned_phase(elapsed,duration)
            if guided:
                messages={'owner_only':'第1阶段：仅机主露脸，正对镜头。',
                          'bystander_present':'第2阶段：另一人站在身后持续露脸，左右稍移动。',
                          'recovery':'第3阶段：另一人离开画面，机主保持正对镜头。'}
                deadline=duration*7/30 if phase=='owner_only' else duration*23/30 if phase=='bystander_present' else duration
                self.instructions.setText(messages[phase]+f'  本阶段剩余 {max(0,int(deadline-elapsed+1))} 秒')
            else:self.instructions.setText(f'请确认两张脸实际出现在画面中。剩余 {max(0,int(duration-elapsed+1))} 秒')
            jpeg=item.get('preview')
            if jpeg:
                image=QImage.fromData(jpeg,'JPG')
                if not image.isNull():self.image.setPixmap(QPixmap.fromImage(image).scaled(self.image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.status.setText(f"检测人脸 {item['faces_count']} · 机主确认 {item['owner_verified']} · 旁观风险 {item['stranger_detected']}。"
                                +quality_hint(item)+' 画面不会保存。')
        def closeEvent(self,event):
            self.canceled=True;self.image.clear();event.accept()
    window=Preview();window.show();app.processEvents()
    return app,window


def quality_hint(item):
    if not item.get('enrolled',True):return '尚未登记机主；请先在软件设置中本人登记。'
    if item.get('stranger_detected') and item.get('faces_count',0)>1:
        return '检测到旁人，保持保护；旁人离开视野后自动验证机主。请保持两张脸清晰，关闭摄像头背景虚化。'
    details=item.get('identity_diagnostics',[])
    if not details:return '请正对摄像头，并确认完整人脸位于预览内。'
    if any(face.get('quality_reason')=='brightness' for face in details):return '脸部光线不足或过曝；请补光并避免强背光。'
    if all(face.get('quality_reason')=='blur' for face in details):return '清晰度不足；请坐稳、擦拭镜头，调整距离/对焦并关闭摄像头背景虚化。'
    if all(face.get('quality_reason')=='too_small' for face in details):return '脸部太小；请靠近摄像头。'
    if not any(face.get('frontal',False) for face in details):return '请正对摄像头，保持完整脸部可见。'
    if item.get('owner_verified'):return '机主已匹配。旁人应露出完整且清晰的脸。'
    if any(face.get('identity_reason')=='quality_match_rejected' for face in details):return '清晰度较低且匹配证据不足；请改善光线和对焦。'
    if any(face.get('owner_score') is not None and face['owner_score'] < .45 for face in details):return '本机模板未匹配；确认本人及模板来源，请勿登记旁人。'
    return '正在连续验证机主；请保持正对和清晰。'


def main():
    parser=argparse.ArgumentParser(description='先关闭防护/其他摄像头程序，再配合指定场景。')
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--phase',default='unconfirmed',help='场景标签；实际人员动作仍需本人确认。')
    parser.add_argument('--output',type=Path,required=True,help='请使用本机忽略目录 test_artifacts/records。')
    parser.add_argument('--installed-owner',action='store_true',help='只读已安装exe的本机模板，不复制/替换。')
    parser.add_argument('--preview',action='store_true',help='仅本机临时预览，不保存画面。')
    parser.add_argument('--guided',action='store_true',help='提示仅本人→旁人出现→退出；30秒时为7/16/7秒。')
    args=parser.parse_args()
    if not 5 <= args.seconds <= 180:parser.error('seconds must be between 5 and 180')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    trace_path=args.output.with_suffix('.jsonl')
    trace=trace_path.open('w',encoding='utf-8')
    owner_path=user_root()/'private'/'owner_templates.npz' if args.installed_owner else None
    try:worker=CameraWorker(preview=args.preview,diagnostics=True,owner_path=owner_path)
    except Exception:
        trace.close()
        raise
    started=time.monotonic();ready_at=None;sequence=None;samples=[];error=None;phase=None
    app=window=None
    try:
        if args.preview:app,window=preview_window()
        while True:
            if app is not None:
                app.processEvents()
                if window.canceled:
                    error='User canceled'
                    break
            now=time.monotonic()
            if ready_at is None and now-started >= 30:
                error='Camera startup timed out'
                break
            if ready_at is not None and now-ready_at >= args.seconds:
                break
            worker.poll()
            if worker.error:
                error=worker.error
                break
            item=worker.last
            if item and item['sequence'] != sequence:
                if ready_at is None:
                    ready_at=time.monotonic()
                    print(json.dumps({'event':'camera_ready','startup_seconds':round(ready_at-started,2),
                                      'enrolled':item['enrolled'],'frame_size':item.get('frame_size'),
                                      'sample_seconds':args.seconds},ensure_ascii=True),flush=True)
                sequence=item['sequence']
                fields=('sequence','faces_count','enrolled','owner_verified','owner_session_active',
                        'protect_request','stranger_detected','pose_grace','detection_ms','detail_scan',
                        'frame_size','face_sizes','face_confidences','frame_age_ms','processing_ms',
                        'identity_diagnostics','weak_candidates','unconfirmed_faces','candidate_pending','scans')
                sample={'elapsed':round(time.monotonic()-ready_at,2),
                        **{key:item[key] for key in fields if key in item}}
                if args.guided:
                    sample['planned_phase']=planned_phase(sample['elapsed'],args.seconds)
                    if sample['planned_phase'] != phase:
                        phase=sample['planned_phase']
                        print(json.dumps({'event':'phase_prompt','phase':phase,'elapsed':sample['elapsed']},ensure_ascii=True),flush=True)
                if window is not None:window.show_sample(item,sample['elapsed'],args.seconds,args.guided)
                # 每条白名单状态单次写入并刷新；最后汇总失败也能恢复已完成样本。
                trace.write(json.dumps(sample,ensure_ascii=False)+'\n')
                trace.flush();os.fsync(trace.fileno())
                samples.append(sample)
            time.sleep(.05)
    finally:
        worker.close()
        trace.close()
        if window is not None:window.close();app.processEvents()
    report={'phase_label':args.phase,'human_actions_confirmed':False,'error':error,
            'template_source':'installed' if args.installed_owner else 'source',
            'guided_prompts':args.guided,'preview_in_memory':args.preview,
            'startup_seconds':round((ready_at or time.monotonic())-started,2),
            'duration_seconds':round(time.monotonic()-ready_at,2) if ready_at is not None else 0,'samples':samples,
            'summary':{'frames':len(samples),'max_faces':max((i['faces_count'] for i in samples),default=0),
                       'bystander_frames':sum(i['stranger_detected'] for i in samples),
                       'owner_verified_frames':sum(i['owner_verified'] for i in samples),
                       'protect_frames':sum(i['protect_request'] for i in samples)}}
    temporary=args.output.with_suffix('.pending.json')
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(args.output)
    print(json.dumps({'output':str(args.output),'error':error,**report['summary']},ensure_ascii=True))
    return 1 if error or not samples else 0


if __name__=='__main__':
    mp.freeze_support()
    raise SystemExit(main())
