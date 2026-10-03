"""虚构窗口中的IPC→保护状态→Qt绘制计时；不使用真实机主或桌面原文。"""
import json
import socket
import statistics
import time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPainter,QColor
from PySide6.QtWidgets import QApplication,QWidget
from identity_bridge import IdentityBridge
from protection_state import ProtectionState


class Fixture(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(500,160)
        self.setWindowTitle('虚构字段控制延迟测试（自动关闭）')
        self.bridge=IdentityBridge(port=0)
        self.port=self.bridge.socket.getsockname()[1]
        self.sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.state=ProtectionState()
        self.mask=False
        self.sent=None
        self.values=[]
        self.sequence=0
        self.timer=QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        QTimer.singleShot(200,self.request)

    def request(self):
        self.sequence+=1
        self.sent=time.perf_counter()
        self.sender.sendto(json.dumps({'owner_verified':False,'protect_request':True,'faces_count':2,
                                      'sequence':self.sequence,'session':'fictional-control-check',
                                      'updated_at':time.time()}).encode(),('127.0.0.1',self.port))

    def poll(self):
        self.bridge.poll()
        if self.sent is not None and self.bridge.last and self.bridge.last['sequence']==self.sequence:
            risk,_=self.bridge.risk(time.monotonic())
            self.mask=self.state.update(time.monotonic(),risk)
            self.update()

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('white'))
        painter.drawText(20,45,'虚构敏感字段：13800138000')
        if self.mask:
            painter.fillRect(10,10,400,70,QColor(20,24,32))
            if self.sent is not None:
                self.values.append((time.perf_counter()-self.sent)*1000)
                self.sent=None
                if len(self.values)>=20:
                    QTimer.singleShot(0,self.close)
                else:
                    QTimer.singleShot(40,self.reset)

    def reset(self):
        # 仅为重复测量新保护绘制；不改变生产恢复延时策略。
        self.mask=False
        self.update()
        QTimer.singleShot(40,self.request)

    def closeEvent(self,event):
        self.timer.stop()
        self.sender.close(); self.bridge.close()
        event.accept()
        QApplication.quit()


if __name__=='__main__':
    app=QApplication([])
    fixture=Fixture(); fixture.show()
    QTimer.singleShot(10000,fixture.close)
    app.exec()
    if len(fixture.values)!=20:
        raise RuntimeError('Incomplete control latency check')
    values=sorted(fixture.values)
    print(json.dumps({'samples':len(values),'median_ipc_to_qt_paint_ms':round(statistics.median(values),1),
                      'p95_ms':round(values[18],1),'max_ms':round(max(values),1),
                      'scope':'fictional_window_not_real_desktop_or_camera'}))

