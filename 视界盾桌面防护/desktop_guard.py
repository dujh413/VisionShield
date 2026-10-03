import argparse
import csv
from datetime import datetime
import multiprocessing
from pathlib import Path
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from screen_capture import ScreenCapture, CaptureWorker, change_regions, enable_dpi, same_image
from sensitive_rules import detect, rect_of
from identity_bridge import IdentityBridge
from ocr_worker import OCRWorker
from overlay_window import OverlayWindow, exclude_capture
from protection_state import ProtectionState


class ControlPanel(QWidget):
    def __init__(self, semantic=False):
        super().__init__()
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
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.root = Path(__file__).resolve().parent
        self.latest = self.valid_image = None
        self.hits, self.last_capture = [], 0
        self.error = None
        self.ready = False
        self.semantic = None
        if semantic:
            from semantic_classifier import SemanticClassifier
            self.semantic = SemanticClassifier(self.root/'data/semantic_samples.json')
        self.log = self.writer = None
        self.last_log_state = None

    def start(self):
        self.pause()
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
            if not verify_exclusion(self.capture, self.overlay):
                raise RuntimeError('遮罩实际采集排除验证失败；未启动自动模式，请更换捕获方案')
            self.overlay.set_masks([], full=True)
            self.capture.close()
            self.capture=CaptureWorker()
            if self.isVisible():
                self.raise_()
            self.bridge = IdentityBridge()
            self.worker = OCRWorker(self.root)
            self.state = ProtectionState()
            self.latest = self.valid_image = None
            self.hits, self.last_capture = [], 0
            self.error, self.ready = None, False
            records = self.root/'records'
            records.mkdir(exist_ok=True)
            self.log = (records/f"guard_{datetime.now():%Y%m%d_%H%M%S_%f}.csv").open('w', encoding='utf-8-sig', newline='')
            self.writer = csv.writer(self.log)
            self.writer.writerow(['elapsed_s','state','frame_id','sensitive_lines','categories','ocr_ms'])
            self.started = time.monotonic()
            self.last_log_state = None
            self.timer.start()
            self.status.setText('启动中：初始化本地OCR；未确认安全前临时全屏保护。')
        except Exception as error:
            self.pause()
            self.status.setText(f'未启动：{error}')

    def pause(self):
        self.timer.stop()
        for name in ('overlay', 'capture', 'worker', 'bridge'):
            obj = getattr(self, name, None)
            if obj is not None:
                obj.close()
                setattr(self, name, None)
        if self.log:
            self.log.close()
            self.log = self.writer = None
        self.latest = self.valid_image = None
        self.hits = []
        self.status.setText('已暂停：当前桌面不受本软件保护。')

    def tick(self):
        try:
            now = time.monotonic()
            self.bridge.poll()
            risk, reason = self.bridge.risk(now)
            ocr_ms = None
            if now-self.last_capture >= 0.1:
                frame = self.capture.latest()
                self.last_capture = now
                if frame is not None:
                    old = self.latest
                    self.latest = frame
                    changed = old is None or not same_image(old.image, frame.image)
                    if changed:
                        self.valid_image, self.hits = None, []
                    # 未有有效OCR时持续提交最新帧；队列最大1。
                    if self.ready and self.valid_image is None and not self.error:
                        self.worker.submit(frame)
            for item in self.worker.poll():
                if item.get('ready'):
                    self.ready = True
                elif 'error' in item:
                    self.error = 'OCR异常：'+item['error']
                elif (self.latest is not None and
                      now-item['captured_at'] <= 10 and
                      same_image(item['image'], self.latest.image)):
                    self.hits = detect(item['lines'], self.semantic)
                    self.valid_image = item['image']
                    ocr_ms = item['elapsed_ms']
            if not self.worker.process.is_alive():
                self.error = self.error or 'OCR进程已退出'
            if self.valid_image is None and now-self.started > 30 and self.ready:
                # 持续动画或OCR过慢时不将陈旧结果当作有效坐标。
                reason += '；画面持续变化或OCR尚未完成'
            protecting = self.state.update(now, risk or bool(self.error))
            valid = self.latest is not None and self.valid_image is not None
            full = protecting and (not valid or bool(self.error))
            rectangles = [rect_of(hit['polygon']) for hit in self.hits] if protecting and valid else []
            self.overlay.set_masks(rectangles, full=full)
            state = '异常全屏保护' if self.error else '临时全屏保护' if full else '敏感行保护' if protecting else '正常显示'
            self.status.setText(f'{state} · {reason}\nOCR：'+('异常' if self.error else '已就绪' if self.ready else '加载中'))
            self.detail.setText(f'有效敏感行：{len(self.hits)}；范围：主显示器\n' +
                                ('实验语义已启用（小样本，需独立评估）' if self.semantic else '规则模式；尚不能覆盖全部私人聊天语义'))
            summary = (state, len(self.hits), tuple(sorted({c for h in self.hits for c in h['categories']})))
            if summary != self.last_log_state or ocr_ms is not None:
                self.writer.writerow([round(now-self.started,3), state,
                                      self.latest.frame_id if self.latest else None,
                                      len(self.hits), '|'.join(summary[2]), ocr_ms])
                self.log.flush()
                self.last_log_state = summary
        except Exception as error:
            # 保留可点击的控制面板；异常时不静默恢复内容。
            if self.overlay:
                self.overlay.set_masks([], full=True)
            self.timer.stop()
            self.status.setText(f'运行异常，已临时全屏保护：{type(error).__name__}；可暂停或退出。')
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
    enable_dpi()
    app = QApplication(sys.argv[:1])
    panel = ControlPanel(args.semantic)
    panel.show()
    QTimer.singleShot(300, panel.start)
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
