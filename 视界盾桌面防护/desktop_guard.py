import argparse
import csv
from datetime import datetime
import multiprocessing
from pathlib import Path
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from screen_capture import ScreenCapture, CaptureWorker, enable_dpi
from identity_bridge import IdentityBridge
from ocr_worker import OCRWorker
from overlay_window import OverlayWindow, exclude_capture
from protection_state import ProtectionState
from content_state import ContentState
from mask_effect import parse_effect
from diagnostics import Diagnostics


class ControlPanel(QWidget):
    def __init__(self, semantic=False, diagnostics=False):
        super().__init__()
        if semantic:
            raise ValueError('当前仓库未交付语义分类器，请使用默认规则模式')
        self.setWindowTitle('视界盾 · 主屏自动防护')
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.status = QLabel('输入处理设置后点击启动。截图与文字仅在内存处理。')
        self.status.setWordWrap(True)
        self.effect_input = QLineEdit()
        self.effect_input.setMaxLength(128)
        self.effect_input.setPlaceholderText('整数：模糊半径（像素）；留空：不处理；其他字符：深色遮挡')
        self.effect_input.setAccessibleName('敏感内容处理设置')
        self.detail = QLabel('规则覆盖：手机号、邮箱、身份证、标签关联；低置信度保守处理。')
        self.detail.setWordWrap(True)
        start, pause, quit_button = QPushButton('启动 / 重试'), QPushButton('暂停防护'), QPushButton('退出')
        layout = QVBoxLayout(self)
        for item in (self.status, QLabel('敏感内容处理设置（点击启动后生效）：'),
                     self.effect_input, self.detail, start, pause, quit_button):
            layout.addWidget(item)
        start.clicked.connect(self.start)
        pause.clicked.connect(self.pause)
        quit_button.clicked.connect(self.close)
        self.resize(520, 330)
        self.capture = self.worker = self.overlay = self.bridge = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.root = Path(__file__).resolve().parent
        self.latest = self.valid_image = None
        self.hits, self.last_capture = [], 0
        self.error, self.ready = None, False
        self.semantic = None
        self.effect = parse_effect('')
        self.diagnostics_enabled = diagnostics
        self.diagnostics = None
        self.log = self.writer = None
        self.last_log_state = None

    def start(self):
        effect = parse_effect(self.effect_input.text())
        self.pause()
        try:
            self.effect = effect
            self.capture = ScreenCapture()
            screen = QApplication.primaryScreen()
            geometry, ratio = screen.geometry(), screen.devicePixelRatio()
            if (abs(geometry.width()*ratio-self.capture.monitor['width']) > 2 or
                    abs(geometry.height()*ratio-self.capture.monitor['height']) > 2):
                raise RuntimeError('主屏物理尺寸与Qt坐标不一致，请重启软件或检查缩放')
            self.overlay = OverlayWindow(screen)
            exclude_capture(self)
            from capture_probe import verify_exclusion
            if not verify_exclusion(self.capture, self.overlay):
                raise RuntimeError('遮罩实际采集排除验证失败；请更换捕获方案')
            # The exclusion probe always uses an opaque mask, independently of the selected mode.
            self.overlay.set_effect(effect)
            self.overlay.set_masks([], full=True, frame_image=self.capture.grab().image)
            self.capture.close()
            self.capture = CaptureWorker()
            self.raise_()
            self.bridge, self.worker = IdentityBridge(), OCRWorker(self.root)
            self.state, self.content = ProtectionState(), ContentState()
            self.latest = self.valid_image = None
            self.hits, self.last_capture = [], 0
            self.error, self.ready = None, False
            records = self.root/'records'
            records.mkdir(exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            self.log = (records/f'guard_{stamp}.csv').open('w', encoding='utf-8-sig', newline='')
            self.writer = csv.writer(self.log)
            self.writer.writerow(['elapsed_s','state','frame_id','sensitive_lines','categories','ocr_ms',
                                  'coordinates_valid','coverage_complete','unknown_regions','effect','radius'])
            self.started = time.monotonic()
            self.diagnostics = Diagnostics(records/f'diagnostic_{stamp}') if self.diagnostics_enabled else None
            self.last_log_state = None
            self.timer.start()
            self.status.setText(f'启动中 · {effect.description}；正在初始化本地OCR。')
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
        if self.diagnostics:
            self.diagnostics.close()
            self.diagnostics = None
        self.latest = self.valid_image = None
        self.hits = []
        self.status.setText('已暂停：当前桌面不受本软件处理。')

    def tick(self):
        try:
            now = time.monotonic()
            self.bridge.poll()
            risk, reason = self.bridge.risk(now)
            ocr_ms = None
            if now-self.last_capture >= .1:
                self.last_capture = now
                frame = self.capture.latest()
                if frame is not None:
                    screen = QApplication.primaryScreen()
                    geo, ratio = screen.geometry(), screen.devicePixelRatio()
                    if abs(geo.width()*ratio-frame.image.shape[1]) > 2 or abs(geo.height()*ratio-frame.image.shape[0]) > 2:
                        raise RuntimeError('运行中显示器尺寸变化，请重试')
                    self.content.observe(frame)
                    self.latest = self.content.latest
            for item in self.worker.poll():
                received = time.monotonic()
                if item.get('ready'):
                    self.ready = True
                    if self.diagnostics:
                        self.diagnostics.event(received, self.started, {
                            'event': 'ocr_ready', 'providers': item.get('providers'),
                            'backend': item.get('backend')})
                elif 'error' in item:
                    self.error = 'OCR异常：'+item['error']
                elif 'lines' in item:
                    accepted = self.content.accept(item, received, self.semantic)
                    ocr_ms = item['elapsed_ms']
                    if self.diagnostics:
                        self.diagnostics.event(received, self.started, {
                            **item, 'event': 'ocr_result', 'accepted': accepted,
                            'lines_count': len(item['lines']),
                            'result_age_ms': (received-item['captured_at'])*1000,
                            'receive_delay_ms': (received-item.get('ocr_finished_at',received))*1000})
            now = time.monotonic()
            if not self.worker.process.is_alive():
                self.error = self.error or 'OCR进程已退出'
            if self.ready and not self.error and self.content.should_submit(now):
                if self.worker.submit(self.content.latest):
                    self.content.mark_submitted(now)
            view = self.content.view(now)
            self.hits = view['hits']
            self.valid_image = self.content.result['image'] if view['coordinates_valid'] else None
            protecting = self.state.update(now, risk or bool(self.error) or view['capture_failed'])
            full = protecting and (view['full'] or bool(self.error))
            masks = view['rectangles'] if protecting and not self.error else []
            image = self.latest.image if self.latest is not None and not view['capture_failed'] else None
            self.overlay.set_masks(masks, full=full, frame_image=image)
            state = ('未处理' if self.effect.mode == 'off' else '异常保护' if self.error else
                     '临时全屏保护' if full else '局部保护' if protecting else '正常显示')
            reason += '；'+view['reason']
            self.status.setText(f'{state} · {self.effect.description} · {reason}'+chr(10)+'OCR：'+
                                ('异常' if self.error else '已就绪' if self.ready else '加载中'))
            self.detail.setText(f"有效敏感行：{len(self.hits)}；未知区域：{view.get('unknown_regions',0)}；主显示器"+chr(10)+
                                '修改输入后重新点击启动生效。规则模式尚不能覆盖全部私人聊天语义。')
            summary = (state, len(self.hits), tuple(sorted({c for h in self.hits for c in h['categories']})),
                       view['coordinates_valid'], view['coverage_complete'], view.get('unknown_regions',0))
            if summary != self.last_log_state or ocr_ms is not None:
                self.writer.writerow([round(now-self.started,3), state,
                                      self.latest.frame_id if self.latest else None, len(self.hits),
                                      '|'.join(summary[2]), ocr_ms, *summary[3:],
                                      self.effect.mode, self.effect.radius])
                self.log.flush()
                self.last_log_state = summary
            if self.diagnostics:
                self.diagnostics.heartbeat(now, self.started, {
                    'frame_id': self.latest.frame_id if self.latest else None,
                    'frame_age_s': round(now-self.latest.captured_at,3) if self.latest else None,
                    'ocr_ready': self.ready, 'ocr_alive': self.worker.process.is_alive(),
                    'capture_alive': self.capture.thread.is_alive(), 'control_timer_active': self.timer.isActive(),
                    **view, 'sensitive_lines': len(self.hits), 'effect': self.effect.mode,
                    'radius': self.effect.radius, 'blur_ms': self.overlay.blur_ms, 'error': self.error})
        except Exception as error:
            if self.overlay:
                self.overlay.set_masks([], full=True)
            self.timer.stop()
            self.status.setText(f'运行异常 · {self.effect.description} · {type(error).__name__}；可暂停或退出。')
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        self.pause()
        event.accept()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--semantic', action='store_true', help='尚未交付的实验功能')
    parser.add_argument('--diagnostics', action='store_true', help='记录匿名事件和每秒心跳，不保存截图或原文')
    args = parser.parse_args()
    if args.semantic:
        parser.error('当前仓库未交付语义分类器，请移除 --semantic')
    enable_dpi()
    app = QApplication(sys.argv[:1])
    panel = ControlPanel(diagnostics=args.diagnostics)
    panel.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()

