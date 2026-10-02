"""快速文字路径原型：可见文字直读+异步OCR补充，无真实桌面遮罩。"""
import argparse
import multiprocessing
import os
from pathlib import Path
import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QLabel,QPlainTextEdit,QSplitter,QVBoxLayout,QWidget

from screen_capture import CaptureWorker,enable_dpi
from native_text import NativeTextWorker,visible_windows
from ocr_worker import OCRWorker
from sensitive_rules import detect


def report(lines,direct=False):
    hits={hit['line_index']:hit for hit in detect(lines)}
    output=[]
    for i,line in enumerate(lines):
        origin=line.get('source','ocr')
        hit=hits.get(i)
        title='、'.join(hit['categories']) if hit else '未命中当前规则'
        output.append(f"{i+1}. [{origin}] [{title}] {line['text']}")
    return '\n'.join(output) if output else '暂无文字；不能视为安全。'


class HybridPreview(QWidget):
    def __init__(self,demo=False):
        super().__init__()
        self.setWindowTitle('视界盾 · 快速文字混合路径验收')
        self.resize(1050,650)
        self.status=QLabel('初始化：快速直读＋后台OCR。只读可见文字，不保存截图/原文，不遮盖。')
        self.status.setWordWrap(True)
        self.direct_status=QLabel('直读初始化中')
        self.ocr_status=QLabel('OCR初始化中')
        self.direct_text=QPlainTextEdit(); self.direct_text.setReadOnly(True)
        self.ocr_text=QPlainTextEdit(); self.ocr_text.setReadOnly(True)
        split=QSplitter()
        for label,content in ((self.direct_status,self.direct_text),(self.ocr_status,self.ocr_text)):
            pane=QWidget(); layout=QVBoxLayout(pane)
            layout.addWidget(label); layout.addWidget(content); split.addWidget(pane)
        layout=QVBoxLayout(self); layout.addWidget(self.status); layout.addWidget(split)
        self.capture=CaptureWorker()
        self.native=NativeTextWorker()
        self.ocr=OCRWorker(Path(__file__).resolve().parent)
        self.native_ready=self.ocr_ready=False
        self.last_capture=0
        self.last_native=0
        self.sequence=0
        self.target=None
        self.native_at=None
        self.ocr_at=None
        self.last_request=None
        self.started=time.monotonic()
        self.demo_window=None
        if demo:
            from native_text_demo import create_demo
            self.demo_window,self.demo_handle=create_demo()
        self.timer=QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            now=time.monotonic()
            if now-self.last_capture>=.1:
                self.last_capture=now
                frame=self.capture.latest()
                if frame is not None:
                    if self.ocr_ready:
                        self.ocr.submit(frame)
                    windows=visible_windows(frame.monitor_rect,(os.getpid(),)) if not self.demo_window else []
                    handle=self.demo_handle if self.demo_window else windows[0][0] if windows else None
                    if handle!=self.target:
                        self.direct_text.clear()
                        self.native_at=None
                    self.target=handle
                    if self.native_ready and handle:
                        self.sequence+=1
                        request_time=time.monotonic()
                        self.native.submit({'handle':handle,'monitor':frame.monitor_rect,
                                            'frame_id':frame.frame_id,'sequence':self.sequence,'requested_at':request_time})
                        if self.last_request is None:
                            self.last_request=request_time
            now=time.monotonic()
            for item in self.native.poll():
                if item.get('ready'):
                    self.native_ready=True
                elif item.get('error'):
                    self.direct_status.setText('直读异常；OCR继续补充。')
                    self.direct_text.clear()
                    self.last_request=None
                elif item.get('handle')==self.target and 'lines' in item:
                    self.native_at=now
                    self.last_request=None
                    age=(now-item['requested_at'])*1000
                    if age>1000:
                        self.direct_text.clear()
                        self.direct_status.setText('直读结果过期，未使用；OCR继续。')
                        continue
                    self.direct_text.setPlainText(report(item['lines'],True))
                    self.direct_status.setText(f"快速路径：{len(item['lines'])}条 · 读取{item['read_ms']:.1f}ms · "
                                               f"含调度{age:.0f}ms\n覆盖状态："+
                                               ('部分/超预算' if item['truncated'] or item['errors'] else '已返回支持控件的文字（非整屏覆盖证明）'))
            for item in self.ocr.poll():
                if item.get('ready'):
                    self.ocr_ready=True
                elif item.get('error'):
                    self.ocr_status.setText('OCR异常：'+item['error'])
                elif 'lines' in item:
                    self.ocr_at=item['captured_at']
                    self.ocr_text.setPlainText(report(item['lines']))
                    label={'full':'整屏','partial':'变化区','cached':'缓存复用'}[item['mode']]
                    self.ocr_status.setText(f"OCR补充：{label} · {item['elapsed_ms']:.0f}ms · "
                                            f"快照距今{max(0,now-item['captured_at']):.1f}s\nOCR结果不能当成当前帧已完成的定位。")
            if self.last_request is not None and now-self.last_request>1.5:
                self.direct_text.clear()
                self.direct_status.setText('应用无障碍接口未及时响应；保持降级状态，后台OCR补充。')
            if self.native_at and now-self.native_at>1.5:
                self.direct_text.clear()
            if not self.native.process.is_alive():
                self.direct_status.setText('直读进程退出；关闭后重试。')
            if not self.ocr.process.is_alive():
                self.ocr_status.setText('OCR进程退出；关闭后查看终端。')
        except Exception as error:
            self.timer.stop()
            self.status.setText('验收异常：'+type(error).__name__+'；关闭窗口后查看终端。')
            import traceback
            traceback.print_exc()

    def closeEvent(self,event):
        self.timer.stop()
        self.native.close(); self.ocr.close(); self.capture.close()
        self.direct_text.clear(); self.ocr_text.clear()
        if self.demo_window:
            self.demo_window.close()
        event.accept()
        QApplication.quit()


if __name__=='__main__':
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='使用虚构原生编辑器验证快速路径')
    args=parser.parse_args()
    enable_dpi()
    app=QApplication(sys.argv[:1])
    window=HybridPreview(args.demo)
    window.show()
    try:
        from overlay_window import exclude_capture
        exclude_capture(window)
    except Exception:
        window.close()
        raise
    sys.exit(app.exec())
