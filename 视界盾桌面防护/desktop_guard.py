import argparse
import csv
from datetime import datetime
import multiprocessing
import sys
import time

from PySide6.QtCore import QTimer, QSignalBlocker
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from effect_controls import EffectControls

from screen_capture import ScreenCapture, CaptureWorker, enable_dpi
from sensitive_rules import rect_of
from identity_bridge import IdentityBridge
from ocr_worker import OCRWorker
from overlay_window import OverlayWindow, exclude_capture
from protection_state import ProtectionState
from content_state import ContentState
from frame_scheduler import FrameScheduler
from mask_effect import parse_effect
from performance_log import PerformanceLog
from runtime_paths import desktop_root, records_directory


class ControlPanel(QWidget):
    def __init__(self, semantic=False, integrated=False, shield_enabled=True, effect_text="", diagnostics=False):
        super().__init__()
        self.shield_enabled = shield_enabled
        self.effect_input = EffectControls(effect_text,allow_off=True)
        self.effect_input.setAccessibleName('敏感内容处理设置')
        self.effect = parse_effect(effect_text)
        self.diagnostics_enabled = diagnostics
        self.diagnostics = None
        self.exclusion_verified = False
        self.probe_active = False
        self.app_profiles = {}
        self.region_tracker = None
        self.region_status = '未设置追踪区域'
        self.setWindowTitle('视界盾 · 主屏自动防护')
        from PySide6.QtCore import Qt
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.status = QLabel('启动后自动采集主显示器；不保存截图和原文。')
        self.status.setWordWrap(True)
        self.detail = QLabel('规则覆盖：手机号、邮箱、身份证、标签关联；低置信度保守遮盖。')
        self.detail.setWordWrap(True)
        start, pause, quit_button = QPushButton('启动 / 重试'), QPushButton('暂停防护'), QPushButton('退出')
        layout = QVBoxLayout(self)
        for item in (self.status, QLabel("遮蔽效果（即时生效）："), self.effect_input, self.detail, start, pause, quit_button):
            layout.addWidget(item)
        start.clicked.connect(self.start)
        pause.clicked.connect(self.pause)
        quit_button.clicked.connect(self.close)
        self.resize(420, 230)
        self.capture = self.worker = self.overlay = self.bridge = None
        self.camera = None
        self.integrated = integrated
        self.content = ContentState(capture_timeout=1.5)
        self.scheduler = FrameScheduler()
        self.alert_message = None
        self.last_risk = False
        self.last_alert_at = -100
        self.last_ocr_finished = None
        self.protecting = True
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.effect_input.changed.connect(lambda text:self.apply_preferences({'effect_text':text}))
        self.root = desktop_root()
        self.latest = self.valid_image = None
        self.hits, self.last_capture = [], 0
        self.error = None
        self.ready = False
        self.semantic = None
        if semantic:
            raise ValueError('实验语义分类模块尚未交付，请使用默认规则模式')
        self.log = self.writer = None
        self.last_log_state = None

    def drawing_enabled(self):
        return self.shield_enabled and self.effect.mode != "off"

    def start(self):
        effect = parse_effect(self.effect_input.text())
        if not self.pause():
            return
        try:
            self.effect = effect
            self.capture = ScreenCapture()
            screen = QApplication.primaryScreen()
            geometry = screen.geometry()
            ratio = screen.devicePixelRatio()
            if (abs(geometry.width()*ratio-self.capture.monitor['width']) > 2 or
                    abs(geometry.height()*ratio-self.capture.monitor['height']) > 2):
                raise RuntimeError('主屏物理尺寸与Qt坐标不一致，请重启软件或检查缩放')
            self.overlay = OverlayWindow(screen)
            exclude_capture(self)
            # 等拿到有效保护范围后在该范围内验证排除；不制造整屏启动黑帧。
            self.exclusion_verified = False
            self.overlay.set_effect(effect)
            self.overlay.hide()
            self.capture.close()
            self.capture=CaptureWorker()
            if self.isVisible():
                self.raise_()
            if self.integrated:
                from camera_worker import CameraWorker
                self.camera = CameraWorker()
            else:
                self.bridge = IdentityBridge()
            self.worker = OCRWorker(self.root)
            self.state = ProtectionState()
            self.latest = self.valid_image = None
            self.hits, self.last_capture = [], 0
            self.error, self.ready = None, False
            self.content = ContentState(capture_timeout=1.5)
            self.scheduler = FrameScheduler()
            self.last_risk, self.alert_message, self.last_ocr_finished = False, None, None
            records = records_directory()
            records.mkdir(parents=True, exist_ok=True)
            self.log = (records/f"guard_{datetime.now():%Y%m%d_%H%M%S_%f}.csv").open('w', encoding='utf-8-sig', newline='')
            self.writer = csv.writer(self.log)
            self.writer.writerow(['elapsed_s','state','frame_id','sensitive_lines','categories','ocr_ms'])
            self.started = time.monotonic()
            self.diagnostics = PerformanceLog(records/'performance'/f'{datetime.now():%Y%m%d_%H%M%S_%f}') if self.diagnostics_enabled else None
            self.last_log_state = None
            self.timer.start()
            self.status.setText('启动中：初始化本地OCR；'+('等待有效保护范围，不扩大到范围之外。' if self.drawing_enabled() else '仅检测与提示，不遮蔽屏幕。'))
        except Exception as error:
            self.pause()
            self.status.setText(f'未启动：{error}')

    def apply_preferences(self, value):
        from app_scope import valid_profiles
        if isinstance(value.get('app_profiles'), dict):
            new_profiles=valid_profiles(value['app_profiles'])
            if new_profiles!=self.app_profiles and self.overlay is not None:
                self.overlay.set_masks([],full=False)
            self.app_profiles = new_profiles
        enabled = value.get('shield_enabled', self.shield_enabled)
        if not isinstance(enabled, bool):
            enabled = self.shield_enabled
        text = value.get('effect_text')
        effect = parse_effect(text) if isinstance(text,str) and len(text)<=128 else self.effect
        drawing = enabled and effect.mode != 'off'
        changed = enabled != self.shield_enabled or effect != self.effect
        self.shield_enabled, self.effect = enabled, effect
        if isinstance(text,str) and len(text)<=128:
            with QSignalBlocker(self.effect_input):self.effect_input.setText(text)
        if changed and self.overlay is not None:
            self.overlay.set_effect(effect)
            if not drawing:
                self.overlay.set_masks([], full=False)
                self.overlay.hide()
                self.protecting = False

    def verify_range_capture(self, rectangles, windows=None):
        if self.exclusion_verified:return True
        from capture_probe import ProbeScopeChanged, verify_exclusion
        from app_scope import application_masks, intersect, subtract, window_inventory
        self.probe_active=True
        capture=None;overlay=self.overlay
        try:
            capture=ScreenCapture()
            monitor=self.latest.monitor_rect
            inventory=window_inventory(monitor) if windows is None else windows
            profiles_token=repr(self.app_profiles)
            effect=self.effect
            image=self.latest.image
            scope_checked_at=time.monotonic()
            pixel_clients=[window['client'] for window in inventory
                if (profile:=self.app_profiles.get(window['key'])) and profile['mode']=='tracked'
                and (profile['anchor']['type']!='native' or profile.get('features') is not None)
                and any(intersect(window['client'],rectangle) for rectangle in rectangles)]
            def scope_is_current(probe_box,probe_handle):
                if (self.overlay is not overlay or not self.drawing_enabled()
                        or self.effect!=effect or repr(self.app_profiles)!=profiles_token):return False
                current=[window for window in window_inventory(monitor) if window['handle']!=probe_handle]
                resolved={}
                if self.app_profiles:
                    # Probe pixels are expected capture changes. Keep async UIA
                    # work out of this nested loop; native geometry and guarded
                    # fresh client pixels validate the same initial async proof
                    # throughout this short wait, without borrowing newer work.
                    resolved=self.region_tracker.resolve(self.app_profiles,current,image,
                        (monitor['left'],monitor['top']),now=scope_checked_at,asynchronous=False)
                masks,_=application_masks(current,rectangles,False,self.app_profiles,resolved)
                if masks!=rectangles:return False
                if pixel_clients:
                    import math
                    import numpy as np
                    current_image=capture.grab().image
                    if current_image.shape!=image.shape:return False
                    screen=(0,0,image.shape[1],image.shape[0])
                    probe=None
                    if probe_box is not None:
                        x,y,width,height=probe_box
                        left,top=math.floor(x),math.floor(y)
                        probe=(left,top,math.ceil(x+width)-left,math.ceil(y+height)-top)
                    for client in pixel_clients:
                        clipped=intersect(client,screen)
                        if clipped is None:return False
                        parts=subtract(clipped,probe) if probe is not None else [clipped]
                        for x,y,width,height in parts:
                            if not np.array_equal(image[y:y+height,x:x+width],
                                                  current_image[y:y+height,x:x+width]):return False
                return True
            overlay.set_effect(parse_effect('遮挡'))
            if not verify_exclusion(capture,overlay,rectangles,scope_is_current):
                raise RuntimeError('当前范围遮罩采集排除验证失败')
            if self.overlay is not overlay:return False
            self.exclusion_verified=True
            return True
        except ProbeScopeChanged:
            overlay.set_masks([],full=False,padding=0)
            overlay.hide()
            return False
        except Exception as error:
            self.error=str(error)
            overlay.hide()
            return False
        finally:
            try:
                if self.overlay is overlay:overlay.set_effect(self.effect)
            finally:
                try:
                    if capture:capture.close()
                finally:self.probe_active=False

    def pause(self):
        self.timer.stop()
        failures = []
        if self.region_tracker is not None:
            try:self.region_tracker.close();self.region_tracker=None
            except Exception:failures.append('region_tracker')
        for name in ('overlay', 'capture', 'worker', 'camera', 'bridge'):
            obj = getattr(self, name, None)
            if obj is not None:
                try:
                    obj.close()
                    setattr(self, name, None)
                except Exception as error:
                    failures.append(name+':'+type(error).__name__)
        if self.log:
            try:
                self.log.close()
                self.log = self.writer = None
            except Exception as error:
                failures.append('log:'+type(error).__name__)
        if self.diagnostics:
            try:
                self.diagnostics.close()
                self.diagnostics = None
            except Exception as error:
                failures.append('diagnostics:'+type(error).__name__)
        self.latest = self.valid_image = None
        self.hits = []
        self.content = ContentState(capture_timeout=1.5)
        self.scheduler = FrameScheduler()
        self.ready = False
        self.last_ocr_finished = None
        self.protecting = self.overlay is not None
        self.error = '资源清理未完成：'+', '.join(failures) if failures else None
        self.status.setText(self.error or '已暂停：当前桌面不受本软件保护。')
        return not failures

    def tick(self):
        if self.probe_active:return
        try:
            callback_started = time.monotonic()
            now = time.monotonic()
            sensor = self.camera if self.integrated else self.bridge
            sensor.poll()
            risk, reason = sensor.risk(now)
            confirmed_risk = ((getattr(sensor,'new_stranger_event',False) is True or
                               bool(sensor.last and sensor.last.get('stranger_detected', False)))
                              if self.integrated else risk)
            if risk and confirmed_risk and not self.last_risk and now-self.last_alert_at>=10:
                self.alert_message = reason+('，已请求指定范围保护，请留意范围状态。' if self.drawing_enabled() else '，遮蔽已关闭，请注意屏幕内容。')
                self.last_alert_at = now
            self.last_risk = confirmed_risk
            ocr_ms = None
            if now-self.last_capture >= 0.1:
                frame = self.capture.latest()
                self.last_capture = now
                if frame is not None:
                    screen = QApplication.primaryScreen()
                    geometry = screen.geometry()
                    self.overlay.setGeometry(geometry)
                    ratio = screen.devicePixelRatio()
                    if (abs(geometry.width()*ratio-frame.image.shape[1])>2 or
                            abs(geometry.height()*ratio-frame.image.shape[0])>2):
                        self.error = '显示器尺寸已变化，请暂停后重新启用防护'
                        raise RuntimeError(self.error)
                    self.latest = frame
                    self.content.observe(frame)
            # 必须在poll分发待处理请求之前替换为当前帧，避免再序列化旧帧。
            if self.ready and not self.error and self.scheduler.due(self.latest, now):
                if self.worker.submit(self.latest):
                    self.scheduler.submitted(self.latest, now)
                    self.content.mark_submitted(now)
            for item in self.worker.poll():
                if item.get('ready'):
                    self.ready = True
                    if self.diagnostics:
                        self.diagnostics.event(now,self.started,{**item,'event':'ocr_ready'})
                elif 'error' in item:
                    self.error = 'OCR异常：'+item['error']
                elif 'lines' in item:
                    received = time.monotonic()
                    index_started = time.monotonic()
                    accepted = self.content.accept(item, received, self.semantic)
                    index_ms = (time.monotonic()-index_started)*1000
                    ocr_ms = item['elapsed_ms']
                    if accepted:
                        self.last_ocr_finished = received
                    if self.diagnostics:
                        self.diagnostics.event(received,self.started,{**item,'event':'ocr_result',
                            'accepted':accepted,'lines_count':len(item['lines']),
                            'result_age_ms':(received-item['captured_at'])*1000,
                            'receive_delay_ms':(received-item.get('ocr_finished_at',received))*1000,
                            'index_ms':index_ms})
            now = time.monotonic()
            view = self.content.view(now)
            self.hits = view['hits']
            self.valid_image = self.content.result['image'] if view['coordinates_valid'] else None
            if not self.worker.process.is_alive():
                self.error = self.error or 'OCR进程已退出'
            stale = (self.last_ocr_finished is None and now-self.started>30) or (self.last_ocr_finished is not None and now-self.last_ocr_finished>15)
            if stale:
                # 持续动画或OCR过慢时不将陈旧结果当作有效坐标。
                reason += '；OCR结果未及时更新，临时保护'
            capture_stale = ((self.latest is None and now-self.started>1.5) or
                             (self.latest is not None and now-self.latest.captured_at>1.5))
            if capture_stale:
                reason += '；桌面采集未及时更新，临时保护'
            observation=(sensor.last if self.integrated else
                         {'sequence':sensor.sequence,'received_at':sensor.received_at,'session':sensor.session}
                         if sensor.last else None)
            risk_active = self.state.update(now, risk or bool(self.error) or stale or capture_stale or view["full"],
                                           observation=observation)
            if self.state.evidence_error:
                reason+='；相机观察未连续确认，等待新检测'
            protecting = risk_active and self.drawing_enabled()
            self.protecting = protecting
            full = protecting and (self.latest is None or self.last_ocr_finished is None or bool(self.error) or stale or capture_stale or view["full"])
            rectangles = view["rectangles"] if protecting else []
            scoped = False
            if self.latest is not None and self.latest.monitor_rect:
                from app_scope import application_masks, window_inventory, profile_status
                windows = window_inventory(self.latest.monitor_rect)
                if self.region_tracker is None:
                    from region_tracker import RegionTracker
                    self.region_tracker = RegionTracker()
                scopes=self.region_tracker.resolve(self.app_profiles,windows,self.latest.image,
                    (self.latest.monitor_rect['left'],self.latest.monitor_rect['top']),now)
                self.region_status = profile_status(self.app_profiles,windows,scopes)
                if protecting:
                    rectangles, full = application_masks(windows, rectangles, full, self.app_profiles, resolved=scopes)
                    scoped = bool(windows)
            else:
                rectangles=[]
                self.region_status='等待桌面采集，尚未确认保护范围'
            # 所有运行路径只绘制已确认的应用/选区；失配和异常不扩展到整屏。
            full=False
            if protecting and rectangles and not self.verify_range_capture(rectangles,windows):rectangles=[]
            if self.overlay is None:return  # 探针事件循环中用户可暂停/退出。
            self.protecting=protecting and bool(rectangles)
            self.overlay.set_masks(rectangles, full=False, image=self.latest.image if self.latest is not None else None, padding=0)
            if rectangles and self.protecting:self.overlay.show()
            elif self.overlay.isVisible():self.overlay.hide()
            state = '检测异常 · 保持指定范围策略' if self.error else '应用区域保护' if self.protecting else '保护范围暂不可用' if protecting else '正常显示'
            if not self.drawing_enabled():
                state = '仅检测与提示（不遮蔽）' + (' · 检测异常' if self.error else ' · 存在风险' if risk_active else '')
            self.status.setText(f'{state} · {reason}\nOCR：'+('异常' if self.error else '已就绪' if self.ready else '加载中'))
            self.detail.setText(f'有效敏感行：{len(self.hits)}；{self.effect.description}；范围：主显示器\n' +
                                ('实验语义已启用（小样本，需独立评估）' if self.semantic else '规则模式；尚不能覆盖全部私人聊天语义'))
            if protecting or self.app_profiles:self.status.setText(self.status.text()+'\n'+self.region_status)
            summary = (state, len(self.hits), tuple(sorted({c for h in self.hits for c in h['categories']})))
            if summary != self.last_log_state or ocr_ms is not None:
                self.writer.writerow([round(now-self.started,3), state,
                                      self.latest.frame_id if self.latest else None,
                                      len(self.hits), '|'.join(summary[2]), ocr_ms])
                self.log.flush()
                self.last_log_state = summary
            if self.diagnostics:
                self.diagnostics.heartbeat(now,self.started,{**view,'frame_id':self.latest.frame_id if self.latest else None,
                    'frame_age_ms':(now-self.latest.captured_at)*1000 if self.latest else None,
                    'ocr_ready':self.ready,'ocr_alive':self.worker.process.is_alive(),
                    'capture_alive':self.capture.thread.is_alive(),
                    'sent_frames':self.worker.sent_frames,
                    'unknown_regions':view.get('unknown_regions',0),
                    'sensitive_lines':len(self.hits),'effect':self.effect.mode,'radius':self.effect.radius,
                    'control_ms':(time.monotonic()-callback_started)*1000,
                    'blur_ms':self.overlay.blur_ms,'paint_ms':getattr(self.overlay,'last_paint_ms',0),
                    'blur_backend':getattr(self.overlay,'blur_backend','none'),
                    'blur_device':getattr(self.overlay,'blur_device',''),
                    'blur_gpu_ms':getattr(self.overlay,'blur_gpu_ms',0),
                    'blur_fallback':getattr(self.overlay,'blur_fallback',None),
                    'error':self.error})
        except Exception as error:
            # 保留可点击的控制面板；异常时不静默恢复内容。
            self.error = self.error or '控制流程异常：'+type(error).__name__
            self.protecting = False
            if self.overlay:
                self.overlay.set_masks([], full=False)
                self.overlay.hide()
            self.timer.stop()
            effect = '无法确认范围，已暂停遮蔽' if self.drawing_enabled() else '遮蔽已关闭'
            self.status.setText(f'运行异常，{effect}：{self.error}；可暂停或退出。')
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        self.pause()
        event.accept()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--semantic', action='store_true', help='启用小样本实验语义分类')
    parser.add_argument('--diagnostics', action='store_true', help='记录匿名阶段耗时与心跳')
    args = parser.parse_args()
    if args.semantic:
        parser.error('实验语义分类模块尚未交付，请移除--semantic使用规则模式')
    enable_dpi()
    app = QApplication(sys.argv[:1])
    panel = ControlPanel(args.semantic, diagnostics=args.diagnostics)
    panel.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
