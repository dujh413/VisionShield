"""临时打开虚构文本窗口，走独立进程读取；不读取其他应用或写入原文。"""
import json
import multiprocessing
import sys
import time
import statistics
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QPlainTextEdit
from screen_capture import enable_dpi
from native_text import NativeTextWorker


if __name__=='__main__':
    multiprocessing.freeze_support()
    enable_dpi()
    app=QApplication([])
    editor=QPlainTextEdit()
    editor.setWindowTitle('视界盾虚构文字速度测试（自动关闭）')
    editor.setPlainText('手机号：13800138000\n验证码：246810\n邮箱：demo@example.com\n今天下午一起去图书馆。')
    editor.resize(700,300)
    editor.show()
    # 原生Windows编辑控件是已知UIA提供器；Qt自绘编辑区不一定提供文字模式。
    user=ctypes.windll.user32
    user.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
                                  ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                  wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,ctypes.c_void_p]
    user.CreateWindowExW.restype=wintypes.HWND
    handle=user.CreateWindowExW(0,'EDIT','手机号：13800138000\r\n验证码：246810\r\n邮箱：demo@example.com\r\n今天下午一起去图书馆。',
                               0x50000004,10,10,650,220,wintypes.HWND(int(editor.winId())),None,None,None)
    if not handle:
        raise RuntimeError('Cannot create native test edit')
    worker=NativeTextWorker()
    results=[]
    started=time.monotonic()
    sequence=0
    pending=False
    failed=[None]
    timer=QTimer()
    def tick():
        global sequence,pending
        for item in worker.poll():
            if item.get('ready'):
                pending=False
            elif 'lines' in item:
                pending=False
                text=''.join(line['text'] for line in item['lines'])
                if not all(token in text for token in ('13800138000','246810','demo@example.com')):
                    if item['sequence']<=3:
                        # 初次激活应用的无障碍提供器可超过预算；预热后再测稳态。
                        continue
                    print({k:v for k,v in item.items() if k!='lines'})
                    failed[0]='direct text content missing'
                    app.quit()
                    return
                results.append((item['read_ms'],(time.monotonic()-item['requested_at'])*1000,len(item['lines'])))
                if len(results)>=10:
                    app.quit()
                    return
            elif item.get('error'):
                failed[0]=item['error']
                app.quit()
                return
        if time.monotonic()-started>20:
            failed[0]='timeout'
            app.quit()
        if worker.process.is_alive() and not pending:
            screen=app.primaryScreen()
            geometry=screen.geometry(); ratio=screen.devicePixelRatio()
            sequence+=1
            worker.submit({'handle':int(handle),'monitor':{'left':0,'top':0,
                          'width':round(geometry.width()*ratio),'height':round(geometry.height()*ratio)},
                          'sequence':sequence,'requested_at':time.monotonic()})
            pending=True
    timer.timeout.connect(tick)
    timer.start(20)
    try:
        app.exec()
    finally:
        worker.close()
        editor.close()
    if failed[0] or not results:
        raise RuntimeError('UIA self-check failed: '+str(failed[0]))
    warm=results[2:]
    print(json.dumps({'samples':len(results),'warm_samples':len(warm),
                      'median_read_ms':round(statistics.median(r[0] for r in warm),1),
                      'median_roundtrip_ms':round(statistics.median(r[1] for r in warm),1),
                      'max_roundtrip_ms':round(max(r[1] for r in warm),1),
                      'first_roundtrip_ms':round(results[0][1],1),'lines':results[-1][2],
                      'fictional_tokens_correct':True}))
