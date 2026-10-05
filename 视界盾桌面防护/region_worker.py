"""独立进程读取控件结构；队列仅保留最近请求，卡住后由父进程关闭。"""
import multiprocessing as mp
import queue
import time


def worker_main(inputs,outputs,stop):
    from ocr_worker import put_latest
    try:
        from screen_capture import enable_dpi
        enable_dpi()
        import cv2
        cv2.setNumThreads(1)
        from region_anchor import enroll_anchor,locate_anchor
        from region_features import extract_features
        put_latest(outputs,{'ready':True})
        while not stop.is_set():
            try:request=inputs.get(timeout=.1)
            except queue.Empty:continue
            try:
                if request['command']=='enroll':
                    from app_scope import window_inventory
                    from screen_capture import ScreenCapture,enable_dpi
                    enable_dpi();capture=ScreenCapture()
                    try:
                        windows=window_inventory(capture.monitor)
                        window=next(w for w in windows if w['handle']==request['binding']['handle'] and w['pid']==request['binding']['pid'])
                        cx,cy,cw,ch=window['client'];x,y,width,height=request['region']
                        rect=(cx+x*cw,cy+y*ch,width*cw,height*ch)
                        # 校准时被其他窗口遮住的特征不可当成目标应用特征。
                        from app_scope import intersect
                        for front in windows[:windows.index(window)]:
                            import os
                            if front['mode']=='ignore' and front['pid'] in (os.getpid(),os.getppid()):continue
                            overlap=intersect(rect,front['rect'])
                            if overlap and overlap[2]*overlap[3]>rect[2]*rect[3]*.05:
                                raise ValueError('选区被其他窗口覆盖，请把目标应用置于前景')
                        anchor=enroll_anchor(window['handle'],rect,(capture.monitor['left'],capture.monitor['top']))
                        features=extract_features(capture.grab().image,rect)
                        if anchor['type']=='visual' and features is None:
                            raise ValueError('选区缺少稳定特征，请包含边框、图标或选择整窗保护')
                        profile={'mode':'tracked','region':request['region'],'size':[cw,ch],
                                 'binding':{'handle':window['handle'],'pid':window['pid']},'anchor':anchor}
                        if features:profile['features']=features
                        from app_scope import valid_profiles
                        clean=valid_profiles({window['key']:profile})
                        if not clean:raise ValueError('区域结构不稳定，请重新框选或采用整窗保护')
                        put_latest(outputs,{'profile':clean[window['key']]})
                    finally:capture.close()
                else:
                    regions={}
                    for key,task in request['tasks'].items():
                        try:regions[key]=locate_anchor(task['handle'],task['anchor'],request['origin'])
                        except Exception:regions[key]=None
                    put_latest(outputs,{'regions':regions,'sequence':request['sequence'],'requested_at':request['requested_at'],
                                        'clients':request['clients'],'finished_at':time.monotonic()})
            except Exception as error:
                put_latest(outputs,{'error':str(error)[:160] if isinstance(error,ValueError) else type(error).__name__})
    except Exception as error:
        from ocr_worker import put_latest
        put_latest(outputs,{'error':type(error).__name__})


class RegionWorker:
    def __init__(self):
        context=mp.get_context('spawn')
        self.inputs,self.outputs=context.Queue(1),context.Queue(2)
        self.stop=context.Event()
        self.process=context.Process(target=worker_main,args=(self.inputs,self.outputs,self.stop),daemon=True)
        self.process.start()
        self.ready=False;self.created_at=time.monotonic();self.requested_at=None

    def submit(self,value):
        from ocr_worker import put_latest
        put_latest(self.inputs,value);self.requested_at=time.monotonic()

    def poll(self):
        result=[]
        while True:
            try:item=self.outputs.get_nowait()
            except queue.Empty:break
            if item.get('ready'):self.ready=True
            else:self.requested_at=None
            result.append(item)
        return result

    def close(self):
        self.stop.set();self.process.join(.3)
        if self.process.is_alive():self.process.terminate();self.process.join(1)
        for channel in (self.inputs,self.outputs):channel.cancel_join_thread();channel.close()


def enroll_region(request,parent=None):
    from PySide6.QtCore import QEventLoop,QTimer
    from PySide6.QtWidgets import QProgressDialog
    dialog=QProgressDialog('正在识别所选区域的控件与视觉特征…','取消',0,0,parent)
    dialog.setWindowTitle('区域追踪');dialog.setMinimumDuration(0)
    from overlay_window import exclude_capture
    exclude_capture(dialog)
    worker=RegionWorker();loop=QEventLoop();result={};sent=False
    def tick():
        nonlocal sent
        for item in worker.poll():
            if not item.get('ready'):result.update(item);loop.quit();return
        if worker.ready and not sent:worker.submit(request);sent=True
        if time.monotonic()-worker.created_at>12 or not worker.process.is_alive():
            result['error']='区域识别超时，请重试或选择整窗保护';loop.quit()
    timer=QTimer();timer.timeout.connect(tick);timer.start(50)
    dialog.canceled.connect(loop.quit)
    try:dialog.show();loop.exec()
    finally:timer.stop();worker.close();dialog.close();dialog.deleteLater()
    return result
