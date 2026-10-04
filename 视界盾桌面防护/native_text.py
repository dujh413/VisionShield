"""应用可见文字直读；只读UIA公开属性，不注入、不读取进程内存。"""
import ctypes
from ctypes import wintypes
import multiprocessing as mp
import os
import time
from collections import deque

from ocr_worker import put_latest


def intersect(a,b):
    x1,y1,x2,y2=max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
    return (x1,y1,x2,y2) if x2>x1 and y2>y1 else None


def visible_windows(monitor, excluded_pids=()):
    user=ctypes.windll.user32
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    result=[]
    screen=(monitor['left'],monitor['top'],monitor['left']+monitor['width'],monitor['top']+monitor['height'])
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(handle,param):
        pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        rect=wintypes.RECT()
        if user.IsWindowVisible(handle) and pid.value not in excluded_pids and user.GetWindowRect(handle,ctypes.byref(rect)):
            box=intersect((rect.left,rect.top,rect.right,rect.bottom),screen)
            if box:
                result.append((int(handle),box))
        return True
    user.EnumWindows(visit,0)
    return result


def range_lines(pattern,auto,deadline,status=None):
    status={} if status is None else status
    start,end=auto.TextPatternRangeEndpoint.Start,auto.TextPatternRangeEndpoint.End
    for visible in pattern.GetVisibleRanges():
        cursor=visible.Clone()
        cursor.MoveEndpointByRange(end,visible,start,waitTime=0)
        cursor.ExpandToEnclosingUnit(auto.TextUnit.Line)
        for _ in range(80):
            if time.monotonic()>deadline:
                status['truncated']=True
                return
            if cursor.CompareEndpoints(start,visible,end)>=0:
                break
            part=cursor.Clone()
            if part.CompareEndpoints(start,visible,start)<0:
                part.MoveEndpointByRange(start,visible,start,waitTime=0)
            if part.CompareEndpoints(end,visible,end)>0:
                part.MoveEndpointByRange(end,visible,end,waitTime=0)
            text=part.GetText(2048).strip()
            if text:
                for rect in part.GetBoundingRectangles():
                    yield text,(rect.left,rect.top,rect.right,rect.bottom)
            if cursor.Move(auto.TextUnit.Line,1,waitTime=0)!=1:
                break
        else:
            status['truncated']=True


def native_edit_lines(handle,deadline,status=None):
    status={} if status is None else status
    """标准Windows Edit的可见行消息接口，不读取整个文档。"""
    user=ctypes.windll.user32
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    name=ctypes.create_unicode_buffer(128)
    user.GetClassNameW(handle,name,128)
    if name.value.lower()!='edit':
        return
    user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    if user.GetWindowLongW(handle,-16)&0x20:  # ES_PASSWORD
        return
    user.SendMessageTimeoutW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,
                                      wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype=wintypes.LPARAM
    user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    def message(code,wparam=0,lparam=0):
        value=ctypes.c_size_t()
        if not user.SendMessageTimeoutW(handle,code,wparam,lparam,2,100,ctypes.byref(value)):
            raise TimeoutError('Native edit did not respond')
        return value.value
    client=wintypes.RECT()
    user.GetClientRect(handle,ctypes.byref(client))
    origin=wintypes.POINT(0,0)
    user.ClientToScreen(handle,ctypes.byref(origin))
    first=message(0x00CE)  # EM_GETFIRSTVISIBLELINE
    count=message(0x00BA)  # EM_GETLINECOUNT
    for number in range(first,min(count,first+80)):
        if time.monotonic()>deadline:
            status['truncated']=True
            return
        index=message(0x00BB,number)  # EM_LINEINDEX
        packed=message(0x00D6,index)  # EM_POSFROMCHAR
        y=ctypes.c_short((packed>>16)&0xffff).value
        if y>=client.bottom:
            break
        buffer=ctypes.create_unicode_buffer(2049)
        ctypes.cast(buffer,ctypes.POINTER(wintypes.WORD))[0]=2048
        length=message(0x00C4,number,ctypes.addressof(buffer))  # EM_GETLINE
        text=buffer[:length].strip()
        if number+1<count:
            next_index=message(0x00BB,number+1)
            next_packed=message(0x00D6,next_index)
            next_y=ctypes.c_short((next_packed>>16)&0xffff).value
            line_height=max(16,next_y-y)
        else:
            line_height=24
        if text and y+line_height>0:
            yield text,(origin.x,origin.y+max(0,y),origin.x+client.right,
                        origin.y+min(client.bottom,y+line_height))
    else:
        if count>first+80:
            status['truncated']=True


def read_window(handle,monitor,budget=.35):
    started=time.perf_counter()
    deadline=time.monotonic()+budget
    screen=(monitor['left'],monitor['top'],monitor['left']+monitor['width'],monitor['top']+monitor['height'])
    native_status={}
    native=list(native_edit_lines(handle,deadline,native_status))
    if native:
        lines=[]
        for text,rect in native:
            box=intersect(rect,screen)
            if box:
                x1,y1,x2,y2=box
                lines.append({'text':text,'confidence':1.0,'source':'win32_visible_line',
                              'polygon':[[x1-screen[0],y1-screen[1]],[x2-screen[0],y1-screen[1]],
                                         [x2-screen[0],y2-screen[1]],[x1-screen[0],y2-screen[1]]]})
        return {'lines':lines,'read_ms':(time.perf_counter()-started)*1000,'truncated':bool(native_status.get('truncated')),
                'errors':0,'nodes':1,'control_types':['native_edit']}
    import uiautomation as auto
    root=auto.ControlFromHandle(handle)
    nodes=deque([root] if root else [])
    lines=[]
    visited=0
    errors=0
    truncated=bool(native_status.get('truncated'))
    controls=[]
    while nodes and visited<100 and time.monotonic()<deadline:
        control=nodes.popleft()
        visited+=1
        try:
            kind=control.ControlType
            controls.append(auto.ControlTypeNames[kind])
            if control.IsOffscreen or control.IsPassword:
                continue
            rect=control.BoundingRectangle
            box=intersect((rect.left,rect.top,rect.right,rect.bottom),screen)
            if box is None:
                continue
            native_status={}
            native=list(native_edit_lines(control.NativeWindowHandle,deadline,native_status)) if kind==auto.ControlType.EditControl and control.NativeWindowHandle else []
            truncated |= bool(native_status.get('truncated'))
            if native:
                for text,bounds in native:
                    clipped=intersect(bounds,box)
                    if clipped:
                        x1,y1,x2,y2=clipped
                        lines.append({'text':text,'confidence':1.0,'source':'win32_visible_line',
                                      'polygon':[[x1-screen[0],y1-screen[1]],[x2-screen[0],y1-screen[1]],
                                                 [x2-screen[0],y2-screen[1]],[x1-screen[0],y2-screen[1]]]})
                continue
            pattern=(control.GetPattern(auto.PatternId.TextPattern)
                     if kind in (auto.ControlType.DocumentControl,auto.ControlType.EditControl) else None)
            if pattern:
                text_status={}
                for text,bounds in range_lines(pattern,auto,deadline,text_status):
                    clipped=intersect(bounds,box)
                    if clipped:
                        x1,y1,x2,y2=clipped
                        x1-=monitor['left']; x2-=monitor['left']
                        y1-=monitor['top']; y2-=monitor['top']
                        lines.append({'text':text,'confidence':1.0,'source':'uia_text',
                                      'polygon':[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]})
                truncated |= bool(text_status.get('truncated'))
                # 父文本模式已提供文字；不重复遍历其文本子节点。
                if time.monotonic()>deadline:
                    truncated=True
                continue
            # 文本标签公开Name；不读取ValuePattern，避免读取隐藏文档/密码。
            if kind==auto.ControlType.TextControl:
                text=control.Name.strip()
                if text:
                    x1,y1,x2,y2=box
                    lines.append({'text':text,'confidence':1.0,'source':'uia_label',
                                  'polygon':[[x1-screen[0],y1-screen[1]],[x2-screen[0],y1-screen[1]],
                                             [x2-screen[0],y2-screen[1]],[x1-screen[0],y2-screen[1]]]})
            nodes.extend(control.GetChildren())
        except Exception:
            errors+=1
    return {'lines':lines,'read_ms':(time.perf_counter()-started)*1000,
            'truncated':truncated or bool(nodes),'errors':errors,'nodes':visited,'control_types':controls}


def process_main(inputs,outputs):
    # COM初始化放在独立进程；第三方应用卡住不会冻结软件控制面板。
    import uiautomation
    outputs.put({'ready':True})
    while True:
        request=inputs.get()
        if request is None:
            return
        try:
            result=read_window(request['handle'],request['monitor'])
            result.update(sequence=request['sequence'],frame_id=request.get('frame_id'),
                          handle=request['handle'],
                          finished_at=time.monotonic(),requested_at=request['requested_at'])
            put_latest(outputs,result)
        except Exception as error:
            put_latest(outputs,{'error':type(error).__name__,'sequence':request['sequence']})


class NativeTextWorker:
    def __init__(self):
        context=mp.get_context('spawn')
        self.inputs,self.outputs=context.Queue(1),context.Queue(2)
        self.process=context.Process(target=process_main,args=(self.inputs,self.outputs),daemon=True)
        self.process.start()

    def submit(self,request):
        put_latest(self.inputs,request)

    def poll(self):
        import queue
        items=[]
        while True:
            try: items.append(self.outputs.get_nowait())
            except queue.Empty: return items

    def close(self):
        self.process.terminate()
        self.process.join(timeout=1)
        for channel in (self.inputs,self.outputs):
            channel.cancel_join_thread()
            channel.close()
