"""第四步：独立OCR文字框预览；不判断敏感，不遮罩，不保存原文。"""
import argparse
import multiprocessing
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from screen_capture import Frame, CaptureWorker, enable_dpi
from ocr_worker import OCRWorker
from sensitive_rules import detect


def synthetic_image(code='246810',font_size=24):
    # offscreen平台不会自动扫描Windows字体，显式加载防止生成方框字。
    font_file = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/msyh.ttc'
    font_id = QFontDatabase.addApplicationFont(str(font_file))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError('无法加载测试中文字体：'+str(font_file))
    image = QImage(1000, 360, QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setPen(QColor('black'))
    painter.setFont(QFont(families[0], font_size))
    for y, text in [(70,'视界盾 OCR 本地测试'), (145,'测试手机号：13800138000'),
                    (220,'验证码：'+code), (295,'邮箱：demo@example.com')]:
        painter.drawText(30, y, text)
    painter.end()
    rgb = image.convertToFormat(QImage.Format_RGB888)
    array = np.frombuffer(rgb.bits(), dtype=np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
    return cv2.cvtColor(array[:, :rgb.width()*3].reshape(rgb.height(), rgb.width(), 3).copy(), cv2.COLOR_RGB2BGR)


def check(root, sensitive=False, backend='fast'):
    worker = OCRWorker(root,backend)
    sent = False
    started = time.monotonic()
    try:
        while time.monotonic()-started < 120:
            for item in worker.poll():
                if item.get('error'):
                    raise RuntimeError('OCR worker error: '+item['error'])
                if item.get('ready') and not sent:
                    worker.submit(Frame(1,time.monotonic(),{'left':0,'top':0,'width':1000,'height':360},synthetic_image()))
                    sent = True
                elif 'lines' in item:
                    text = ''.join(line['text'] for line in item['lines'])
                    required = ['13800138000','246810','demo@example.com','视界盾']
                    missing = [token for token in required if token not in text]
                    print('Synthetic OCR lines:',len(item['lines']))
                    print('Inference ms:',round(item['elapsed_ms'],1))
                    print('Required tokens found:',not missing)
                    if missing:
                        raise RuntimeError('Synthetic fixture missed: '+str(missing))
                    if sensitive:
                        hits = detect(item['lines'])
                        found = {kind for hit in hits for kind in hit['categories']}
                        if not {'手机号','验证码','邮箱'}.issubset(found):
                            raise RuntimeError('Sensitive categories missing from synthetic fixture')
                        print('Sensitive fixture: PASS; matched lines:',len(hits))
                    if item.get('cached'):
                        print('Unchanged-frame reuse: PASS')
                        return
                    worker.submit(Frame(2,time.monotonic(),{'left':0,'top':0,'width':1000,'height':360},synthetic_image()))
            if not worker.process.is_alive():
                raise RuntimeError('OCR worker exited')
            time.sleep(.05)
        raise TimeoutError('OCR check timed out after 120 seconds')
    finally:
        worker.close()


class OCRPreview(QWidget):
    def __init__(self, root, sensitive=False, backend='fast'):
        super().__init__()
        self.sensitive = sensitive
        self.hit_count = 0
        self.setWindowTitle('第五步 · 敏感文字标记（不遮盖）' if sensitive else '第四步 · 自动OCR预览（不判断敏感、不遮盖）')
        self.resize(1250,750)
        self.status = QLabel('正在加载本地OCR模型，请稍候。')
        self.status.setWordWrap(True)
        self.preview = QLabel('等待识别；启动后自动采集主屏。')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(500,300)
        self.texts = QPlainTextEdit()
        self.texts.setReadOnly(True)
        self.texts.setPlaceholderText('识别文字仅在此窗口显示，不写入文件。')
        self.texts.setMinimumWidth(280)
        split = QSplitter()
        split.addWidget(self.preview)
        split.addWidget(self.texts)
        split.setSizes([900,350])
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(split)
        self.capture = CaptureWorker()
        self.worker = OCRWorker(root,backend)
        self.backend_label = '加载中'
        self.ready, self.last_capture = False, 0
        self.last_result = None
        self.shown_image = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            now = time.monotonic()
            if self.ready and now-self.last_capture >= .1:
                frame=self.capture.latest()
                if frame is not None:
                    self.worker.submit(frame)
                self.last_capture = now
            for item in self.worker.poll():
                if item.get('ready'):
                    self.ready = True
                    self.backend_label = str(item.get('providers',{}))
                    self.status.setText('模型就绪，正在识别主屏。')
                elif item.get('error'):
                    raise RuntimeError('OCR后台异常：'+item['error'])
                elif 'lines' in item:
                    self.last_result = {k:item[k] for k in ('frame_id','captured_at','elapsed_ms','cached','mode','area_ratio')}
                    snapshot = item['image'].copy()
                    output = []
                    hits = {hit['line_index']:hit for hit in detect(item['lines'])} if self.sensitive else {}
                    self.hit_count = len(hits)
                    for index,line in enumerate(item['lines'],1):
                        hit = hits.get(index-1)
                        color = (0,0,255) if hit and any(c!='无法确定' for c in hit['categories']) else (0,180,255) if hit else (0,220,0)
                        polygon = np.asarray(line['polygon'],dtype=np.int32)
                        cv2.polylines(snapshot,[polygon],True,color,2)
                        x,y = polygon[0]
                        cv2.putText(snapshot,str(index),(int(x),max(12,int(y)-4)),
                                    cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
                        result_text = f"{index}. [OCR置信度 {line['confidence']:.3f}] {line['text']}"
                        if hit:
                            result_text += '\n  类别：'+ '、'.join(hit['categories'])+'\n  理由：'+'；'.join(hit['reasons'])
                        elif self.sensitive:
                            result_text += '\n  未命中当前规则（不代表安全）'
                        output.append(result_text)
                    self.texts.setPlainText('\n'.join(output) if output else '本帧未识别到文字。')
                    rgb = cv2.cvtColor(snapshot,cv2.COLOR_BGR2RGB)
                    self.shown_image = QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()
                    self.render_preview()
                    del snapshot
            if self.last_result:
                result = self.last_result
                age = now-result['captured_at']
                action = {'cached':'未变化，复用结果','partial':'变化区OCR','full':'整屏OCR'}[result['mode']]
                legend = (f'敏感/待确认行 {self.hit_count}：红=规则命中，橙=低置信度，绿=未命中。尚未遮盖。' if self.sensitive else
                          '绿色框与左侧同一张快照对应；不是当前桌面的实时遮罩。关闭窗口退出。')
                self.status.setText(f"OCR快照帧 {result['frame_id']} · {action} {result['elapsed_ms']:.0f} ms · "
                                    f"处理面积 {result['area_ratio']:.0%} · 采集距今 {max(0,age):.1f} 秒\n"
                                    +legend+'\n后端：'+self.backend_label)
            if not self.worker.process.is_alive():
                raise RuntimeError('OCR进程退出；查看终端报错。')
        except Exception as error:
            self.timer.stop()
            self.status.setText(f'检查失败：{error}。关闭窗口后排查终端错误。')

    def render_preview(self):
        if self.shown_image is not None:
            self.preview.setPixmap(QPixmap.fromImage(self.shown_image).scaled(
                self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):
        if hasattr(self,'shown_image'):
            self.render_preview()
        super().resizeEvent(event)

    def closeEvent(self,event):
        self.timer.stop()
        self.worker.close()
        self.capture.close()
        self.texts.clear()
        self.shown_image = None
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true',help='只测试虚构图像，不采集桌面')
    parser.add_argument('--sensitive',action='store_true',help='第五步：显示敏感类别与命中理由，不遮盖')
    parser.add_argument('--paddle',action='store_true',help='对照旧Paddle CPU后端')
    args = parser.parse_args()
    if args.check:
        os.environ['QT_QPA_PLATFORM']='offscreen'
    enable_dpi()
    app = QApplication(sys.argv[:1])
    root = Path(__file__).resolve().parent
    if args.check:
        check(root,args.sensitive,'paddle' if args.paddle else 'fast')
        return
    panel = OCRPreview(root,args.sensitive,'paddle' if args.paddle else 'fast')
    panel.show()
    # 排除预览自身，避免画面递归识别。失败时停止，保持测试结果可解释。
    try:
        from overlay_window import exclude_capture
        exclude_capture(panel)
    except Exception as error:
        panel.close()
        raise RuntimeError('不能排除OCR预览窗口采集：'+str(error))
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
