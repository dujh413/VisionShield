import argparse
import csv
from datetime import datetime
import multiprocessing
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from screen_capture import ScreenCapture, CaptureWorker, enable_dpi
from sensitive_rules import rect_of
from identity_bridge import IdentityBridge
from ocr_worker import OCRWorker
from overlay_window import OverlayWindow, exclude_capture
from protection_state import ProtectionState
from content_index import ContentIndex
from runtime_paths import desktop_root, records_directory


class ControlPanel(QWidget):
    def __init__(self, semantic=False, integrated=False, shield_enabled=True):
        super().__init__()
        self.shield_enabled = shield_enabled
        self.exclusion_verified = False
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
        for item in (self.status, self.detail, start, pause, quit_button):
            layout.addWidget(item)
        start.clicked.connect(self.start)
        pause.clicked.connect(self.pause)
        quit_button.clicked.connect(self.close)
        self.resize(420, 230)
        self.capture = self.worker = self.overlay = self.bridge = None
        self.camera = None
        self.integrated = integrated
        self.content = ContentIndex()
        self.alert_message = None
        self.last_risk = False
        self.last_alert_at = -100
        self.last_ocr_finished = None
        self.protecting = True
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
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

    def start(self):
        if not self.pause():
            return
        try:
            self.capture = ScreenCapture()
            screen = QApplication.primaryScreen()
            geometry = screen.geometry()
            ratio = screen.devicePixelRatio()
            if (abs(geometry.width()*ratio-self.capture.monitor['width']) > 2 or
                    abs(geometry.height()*ratio-self.capture.monitor['height']) > 2):
                raise RuntimeError('主屏物理尺寸与Qt坐标不一致，请重启软件或检查缩放')
            self.overlay = OverlayWindow(screen)
            exclude_capture(self)
            # 采集排除必须先用本机探针成功验证，不能只依赖Win32返回值。
            from capture_probe import verify_exclusion
            if self.shield_enabled:
                if not verify_exclusion(self.capture, self.overlay):
                    raise RuntimeError('遮罩实际采集排除验证失败；未启动自动模式，请更换捕获方案')
                self.exclusion_verified = True
                self.overlay.set_masks([], full=True)
            else:
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
            self.content = ContentIndex()
            self.last_risk, self.alert_message, self.last_ocr_finished = False, None, None
            records = records_directory()
            records.mkdir(parents=True, exist_ok=True)
            self.log = (records/f"guard_{datetime.now():%Y%m%d_%H%M%S_%f}.csv").open('w', encoding='utf-8-sig', newline='')
            self.writer = csv.writer(self.log)
            self.writer.writerow(['elapsed_s','state','frame_id','sensitive_lines','categories','ocr_ms'])
            self.started = time.monotonic()
            self.last_log_state = None
            self.timer.start()
            self.status.setText('启动中：初始化本地OCR；'+('未确认安全前临时全屏保护。' if self.shield_enabled else '仅检测与提示，不遮蔽屏幕。'))
        except Exception as error:
            self.pause()
            self.status.setText(f'未启动：{error}')

    def apply_preferences(self, value):
        from app_scope import valid_profiles
        if isinstance(value.get('app_profiles'), dict):
            self.app_profiles = valid_profiles(value['app_profiles'])
        enabled = value.get('shield_enabled')
        if not isinstance(enabled, bool) or enabled == self.shield_enabled:
            return
        if enabled and self.overlay is not None and not self.exclusion_verified:
            from capture_probe import verify_exclusion
            capture = ScreenCapture()
            try:
                self.overlay.show()
                if not verify_exclusion(capture, self.overlay):
                    raise RuntimeError('遮罩采集排除验证失败')
                self.exclusion_verified = True
            except Exception as error:
                self.overlay.hide()
                self.error = str(error)
                return
            finally:
                capture.close()
        self.shield_enabled = enabled
        if self.overlay is not None:
            self.overlay.set_masks([], full=False)
            if enabled:
                self.overlay.show()
            else:
                self.overlay.hide()
                self.protecting = False

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
        self.latest = self.valid_image = None
        self.hits = []
        self.content = ContentIndex()
        self.ready = False
        self.last_ocr_finished = None
        self.protecting = self.overlay is not None
        self.error = '资源清理未完成：'+', '.join(failures) if failures else None
        self.status.setText(self.error or '已暂停：当前桌面不受本软件保护。')
        return not failures

    def tick(self):
        try:
            now = time.monotonic()
            sensor = self.camera if self.integrated else self.bridge
            sensor.poll()
            risk, reason = sensor.risk(now)
            confirmed_risk = (bool(sensor.last and sensor.last.get('stranger_detected', False))
                              if self.integrated else risk)
            if risk and confirmed_risk and not self.last_risk and now-self.last_alert_at>=10:
                self.alert_message = reason+('，已启用隐私遮蔽。' if self.shield_enabled else '，遮蔽已关闭，请注意屏幕内容。')
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
                    self.content.update(frame.image)
                    # 未有有效OCR时持续提交最新帧；队列最大1。
                    if self.ready and not self.error:
                        self.worker.submit(frame)
            for item in self.worker.poll():
                if item.get('ready'):
                    self.ready = True
                elif 'error' in item:
                    self.error = 'OCR异常：'+item['error']
                elif self.latest is not None and now-item['captured_at'] <= 10:
                    if self.content.accept(item['image'],item['lines'],self.semantic):
                        self.last_ocr_finished = now
                        ocr_ms = item['elapsed_ms']
            self.hits = self.content.hits
            self.valid_image = self.content.image if self.last_ocr_finished is not None else None
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
            risk_active = self.state.update(now, risk or bool(self.error) or stale or capture_stale)
            protecting = risk_active and self.shield_enabled
            self.protecting = protecting
            full = protecting and (self.latest is None or self.last_ocr_finished is None or bool(self.error) or stale or capture_stale)
            rectangles = ([rect_of(hit['polygon']) for hit in self.hits]+self.content.pending_rectangles()) if protecting else []
            scoped = False
            if self.latest is not None and self.latest.monitor_rect:
                from app_scope import application_masks, window_inventory
                windows = window_inventory(self.latest.monitor_rect)
                if self.region_tracker is None:
                    from region_tracker import RegionTracker
                    self.region_tracker = RegionTracker()
                scopes=self.region_tracker.resolve(self.app_profiles,windows,self.latest.image,
                    (self.latest.monitor_rect['left'],self.latest.monitor_rect['top']),now)
                self.region_status = ('区域特征追踪中' if scopes and all(s['rect'] is not None for s in scopes.values()) else
                                      '区域等待或失配，所属窗口保护' if any(p['mode']=='tracked' for p in self.app_profiles.values()) else '默认应用策略')
                if protecting:
                    rectangles, full = application_masks(windows, rectangles, full, self.app_profiles, resolved=scopes)
                    scoped = bool(windows)
            self.overlay.set_masks(rectangles, full=full, image=self.latest.image if self.latest is not None else None, padding=0 if scoped else 8)
            state = '异常保护' if self.error else '临时全屏保护' if full else '应用区域保护' if protecting else '正常显示'
            if not self.shield_enabled:
                state = '仅检测与提示（不遮蔽）' + (' · 检测异常' if self.error else ' · 存在风险' if risk_active else '')
            self.status.setText(f'{state} · {reason}\nOCR：'+('异常' if self.error else '已就绪' if self.ready else '加载中'))
            self.detail.setText(f'有效敏感行：{len(self.hits)}；范围：主显示器\n' +
                                ('实验语义已启用（小样本，需独立评估）' if self.semantic else '规则模式；尚不能覆盖全部私人聊天语义'))
            if protecting:self.status.setText(self.status.text()+'\n'+self.region_status)
            summary = (state, len(self.hits), tuple(sorted({c for h in self.hits for c in h['categories']})))
            if summary != self.last_log_state or ocr_ms is not None:
                self.writer.writerow([round(now-self.started,3), state,
                                      self.latest.frame_id if self.latest else None,
                                      len(self.hits), '|'.join(summary[2]), ocr_ms])
                self.log.flush()
                self.last_log_state = summary
        except Exception as error:
            # 保留可点击的控制面板；异常时不静默恢复内容。
            self.error = self.error or '控制流程异常：'+type(error).__name__
            self.protecting = self.shield_enabled
            if self.overlay:
                self.overlay.set_masks([], full=self.shield_enabled)
            self.timer.stop()
            effect = '已临时全屏保护' if self.shield_enabled else '遮蔽已关闭'
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
    args = parser.parse_args()
    if args.semantic:
        parser.error('实验语义分类模块尚未交付，请移除--semantic使用规则模式')
    enable_dpi()
    app = QApplication(sys.argv[:1])
    panel = ControlPanel(args.semantic)
    panel.show()
    QTimer.singleShot(300, panel.start)
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
