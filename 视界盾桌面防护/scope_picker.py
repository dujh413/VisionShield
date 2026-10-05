"""框选应用区域；随后建立控件/视觉锚点，截图不落盘。"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QDialog


class ScopePicker(QDialog):
    def __init__(self, whole=False):
        super().__init__(None,Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.whole=whole;self.first=None;self.result_profile=None
        self.instruction = ('整窗保护 · 仅保护点击的窗口' if whole else '局部保护 · 仅保护框选部分')
        self.hint = ('点击目标应用窗口即可完成。窗口拖动或缩放时，保护范围随之变化；Esc 取消。' if whole else
                     '在目标窗口内按住鼠标拖动，松开完成。包含边框或固定图标可帮助追踪；Esc 取消。')
        self.notice = ''
        self.screen=QApplication.primaryScreen();self.ratio=self.screen.devicePixelRatio()
        self.setGeometry(self.screen.geometry())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        from app_scope import window_inventory
        self.windows=window_inventory({'left':0,'top':0,'width':round(self.width()*self.ratio),'height':round(self.height()*self.ratio)})

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.notice='';self.first=event.position();self.last=self.first;self.update()

    def mouseMoveEvent(self,event):
        if self.first is not None:
            self.last=event.position();self.update()

    def mouseReleaseEvent(self,event):
        if self.first is None or event.button()!=Qt.LeftButton:return
        from app_scope import intersect
        x,y=self.first.x()*self.ratio,self.first.y()*self.ratio
        window=next((w for w in self.windows if w['mode']!='ignore' and w['rect'][0]<=x<w['rect'][0]+w['rect'][2]
                     and w['rect'][1]<=y<w['rect'][1]+w['rect'][3]),None)
        if window is None:
            self.notice='没有选中应用窗口，请在目标窗口内重新选择。'
            self.first=None;self.update();return
        if self.whole:
            profile={'mode':'window','binding':{'handle':window['handle'],'pid':window['pid']}}
        else:
            end=event.position();left=min(x,end.x()*self.ratio);top=min(y,end.y()*self.ratio)
            area=(left,top,abs(end.x()*self.ratio-x),abs(end.y()*self.ratio-y))
            client=window['client'];clipped=intersect(area,client)
            if clipped is None or clipped[2]<20 or clipped[3]<20:
                self.notice='选区太小，请重新拖动框选目标区域。'
                self.first=None;self.update();return
            cx,cy,cw,ch=client
            profile={'command':'enroll','region':[(clipped[0]-cx)/cw,(clipped[1]-cy)/ch,clipped[2]/cw,clipped[3]/ch],
                     'binding':{'handle':window['handle'],'pid':window['pid']}}
        self.result_profile=(window['key'],profile)
        self.accept()

    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor(25,35,45,75))
        p.fillRect(QRectF(12,12,self.width()-24,96),QColor(20,24,32,230));p.setPen(QColor('white'))
        p.drawText(QRectF(24,20,self.width()-48,28),Qt.AlignLeft|Qt.AlignVCenter,self.instruction)
        p.drawText(QRectF(24,48,self.width()-48,42),Qt.AlignLeft|Qt.TextWordWrap,self.notice or self.hint)
        if self.first is not None:p.drawRect(QRectF(self.first,self.last).normalized())
