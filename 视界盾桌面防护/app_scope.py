"""应用策略与物理像素几何。只枚举可见窗口；不保存标题、截图或应用文字。"""
import ctypes
from ctypes import wintypes as w
import os

CHAT = {'wechat.exe','weixin.exe','qq.exe','tim.exe','dingtalk.exe','feishu.exe','teams.exe','ms-teams.exe','telegram.exe','discord.exe'}
IMAGE = {'photos.exe','microsoft.photos.exe','photoviewer.exe','photoshop.exe','gimp.exe','paintdotnet.exe','mspaint.exe','imageglass.exe','irfanview.exe','i_view64.exe'}
WHOLE = IMAGE | {'excel.exe','wps.exe','et.exe','acrord32.exe','acrobat.exe'}


def intersect(a,b):
    x,y=max(a[0],b[0]),max(a[1],b[1])
    right,bottom=min(a[0]+a[2],b[0]+b[2]),min(a[1]+a[3],b[1]+b[3])
    return (x,y,right-x,bottom-y) if right>x and bottom>y else None


def subtract(rect, cover):
    cut=intersect(rect,cover)
    if cut is None:
        return [rect]
    x,y,width,height=rect;cx,cy,cw,ch=cut
    parts=[(x,y,width,cy-y),(x,cy+ch,width,y+height-cy-ch),
           (x,cy,cx-x,ch),(cx+cw,cy,x+width-cx-cw,ch)]
    return [p for p in parts if p[2]>0 and p[3]>0]


def valid_profiles(value):
    result={}
    if not isinstance(value,dict):
        return result
    for key,profile in list(value.items())[:100]:
        if not isinstance(key,str) or len(key)>256 or not isinstance(profile,dict):
            continue
        if profile.get('mode')=='window':
            result[key]={'mode':'window'}
        elif profile.get('mode')=='chat':
            region,size=profile.get('region'),profile.get('size')
            if (isinstance(region,list) and len(region)==4 and isinstance(size,list) and len(size)==2
                    and all(type(v) in (int,float) and 0<=v<=1 for v in region)
                    and region[2]>0 and region[3]>0 and region[0]+region[2]<=1.00001 and region[1]+region[3]<=1.00001
                    and all(type(v) in (int,float) and 10<=v<=32768 for v in size)):
                result[key]={'mode':'chat','region':region,'size':size}
    return result


def application_masks(windows, rectangles, uncertain, profiles=None):
    profiles=valid_profiles(profiles or {})
    if not windows:
        # 枚举失败或未能取得应用边界时不能以空结果恢复。
        return rectangles, bool(uncertain)
    masks=[];covers=[]
    for window in windows:  # EnumWindows顺序：前景到背景。
        rect=window['rect'];mode=window['mode'];profile=profiles.get(window['key'])
        if profile and mode != 'ignore':
            mode=profile['mode']
        scope=rect
        if mode=='chat':
            scope=rect
            client=window['client']
            if profile and profile.get('mode')=='chat':
                cw,ch=client[2:]
                expected=profile['size']
                if abs(cw-expected[0])<=max(2,expected[0]*.02) and abs(ch-expected[1])<=max(2,expected[1]*.02):
                    x,y,width,height=profile['region']
                    scope=(client[0]+x*cw,client[1]+y*ch,width*cw,height*ch)
            # 无有效校准时整应用保护，不猜对话区域。
        selected=([scope] if mode in ('window','chat') else
                  [rect] if uncertain and mode!='ignore' else
                  [clip for candidate in rectangles if (clip:=intersect(candidate,rect))] if mode!='ignore' else [])
        for cover in covers:
            selected=[part for candidate in selected for part in subtract(candidate,cover)]
        masks.extend(selected)
        covers.append(rect)
    return masks, False


def window_inventory(monitor, excluded_pids=None):
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    dwm=ctypes.WinDLL('dwmapi')
    excluded={os.getpid(),os.getppid()} if excluded_pids is None else set(excluded_pids)
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.ClientToScreen.argtypes=[w.HWND,ctypes.POINTER(w.POINT)]
    user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
    user.IsWindowVisible.argtypes=[w.HWND];user.IsIconic.argtypes=[w.HWND]
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int]
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,ctypes.c_void_p,w.DWORD]
    screen=(0,0,monitor['width'],monitor['height']);result=[]
    @ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    def visit(handle,param):
        try:
            if not user.IsWindowVisible(handle) or user.IsIconic(handle):return True
            cloaked=w.DWORD()
            if dwm.DwmGetWindowAttribute(handle,14,ctypes.byref(cloaked),4)==0 and cloaked.value:return True
            bounds=w.RECT()
            if not user.GetWindowRect(handle,ctypes.byref(bounds)):return True
            rect=(bounds.left-monitor['left'],bounds.top-monitor['top'],bounds.right-bounds.left,bounds.bottom-bounds.top)
            clipped=intersect(rect,screen)
            if not clipped:return True
            pid=w.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
            cls=ctypes.create_unicode_buffer(256);user.GetClassNameW(handle,cls,256)
            # 输入穿透的系统浮层不是真正遮挡应用的窗口。
            if user.GetWindowLongW(handle,-20)&0x20 or cls.value.startswith('ShellHandwritingCanvas'):
                return True
            process=kernel.OpenProcess(0x1000,False,pid.value);exe='unknown'
            if process:
                try:
                    path=ctypes.create_unicode_buffer(32768);length=w.DWORD(len(path))
                    if kernel.QueryFullProcessImageNameW(process,0,path,ctypes.byref(length)):
                        exe=path.value.rsplit('\\',1)[-1].lower()
                finally:kernel.CloseHandle(process)
            client=w.RECT();origin=w.POINT()
            user.GetClientRect(handle,ctypes.byref(client));user.ClientToScreen(handle,ctypes.byref(origin))
            mode=('ignore' if pid.value in excluded or cls.value in ('Progman','WorkerW','Shell_TrayWnd','Shell_SecondaryTrayWnd') else
                  'chat' if exe in CHAT else 'window' if exe in WHOLE else 'lines')
            result.append({'handle':int(handle),'key':exe+'|'+cls.value,'mode':mode,'rect':clipped,
                           'client':(origin.x-monitor['left'],origin.y-monitor['top'],client.right,client.bottom)})
        except (OSError,ValueError):pass
        return True
    user.EnumWindows(visit,0)
    return result
