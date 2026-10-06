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
    for key,profile in list(value.items())[:20]:
        if not isinstance(key,str) or len(key)>256 or not isinstance(profile,dict):
            continue
        if profile.get('mode')=='window':
            result[key]={'mode':'window'}
            binding=profile.get('binding')
            if isinstance(binding,dict) and all(type(binding.get(k)) is int and 0<binding[k]<2**64 for k in ('handle','pid')):
                result[key]['binding']={'handle':binding['handle'],'pid':binding['pid']}
        elif profile.get('mode')=='tracked':
            from region_features import valid_features
            anchor=profile.get('anchor');binding=profile.get('binding')
            if not isinstance(anchor,dict) or anchor.get('type') not in ('native','uia','visual'):continue
            kind=anchor['type'];clean={'type':kind}
            if kind!='visual':
                import math
                part=anchor.get('fraction')
                if not isinstance(part,list) or len(part)!=4 or not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in part) or min(part[2:])<=0 or part[0]+part[2]>1.00001 or part[1]+part[3]>1.00001:continue
                clean['fraction']=part
            if kind=='native':
                if not isinstance(anchor.get('class'),str) or len(anchor['class'])>128 or type(anchor.get('id')) is not int:continue
                clean.update({'class':anchor['class'],'id':anchor['id']})
                if type(anchor.get('handle')) is int and 0<anchor['handle']<2**64:clean['handle']=anchor['handle']
            if kind=='uia':
                path=anchor.get('path')
                if not isinstance(path,list) or not 1<=len(path)<=12 or any(not isinstance(s,dict) or type(s.get('kind')) is not int or not isinstance(s.get('class'),str) or len(s['class'])>128 or not isinstance(s.get('id'),str) or len(s['id'])>96 for s in path):continue
                clean['path']=[{'kind':s['kind'],'class':s['class'],'id':s['id']} for s in path]
            entry={'mode':'tracked','anchor':clean}
            if isinstance(binding,dict) and all(type(binding.get(k)) is int and 0<binding[k]<2**64 for k in ('handle','pid')):
                entry['binding']={'handle':binding['handle'],'pid':binding['pid']}
            features=valid_features(profile.get('features'))
            if features is not None:entry['features']=features
            result[key]=entry
        elif profile.get('mode')=='chat':
            region,size=profile.get('region'),profile.get('size')
            if (isinstance(region,list) and len(region)==4 and isinstance(size,list) and len(size)==2
                    and all(type(v) in (int,float) and 0<=v<=1 for v in region)
                    and region[2]>0 and region[3]>0 and region[0]+region[2]<=1.00001 and region[1]+region[3]<=1.00001
                    and all(type(v) in (int,float) and 10<=v<=32768 for v in size)):
                result[key]={'mode':'chat','region':region,'size':size}
    return result


def stored_profiles(profiles):
    """持久化控件结构；视觉描述子和本次窗口句柄不落盘。"""
    result={key:{k:v for k,v in profile.items() if k not in ('features','binding')} for key,profile in valid_profiles(profiles).items()}
    for profile in result.values():
        if 'anchor' in profile:profile['anchor']={k:v for k,v in profile['anchor'].items() if k!='handle'}
    return result


def profile_status(profiles, windows, resolved):
    if not profiles:
        return '默认应用策略'
    available=0
    for key,profile in profiles.items():
        candidates=[win for win in windows if win['key']==key and win['mode']!='ignore']
        bound=profile.get('binding')
        window=(next((win for win in candidates if win['handle']==bound['handle'] and win['pid']==bound['pid']),None)
                if bound else candidates[0] if len(candidates)==1 and profile['mode']!='window' else None)
        if window is None:continue
        if profile['mode']=='window':available+=1
        elif profile['mode']=='tracked':
            match=resolved.get(key)
            if match and match['handle']==window['handle'] and match['rect'] is not None and intersect(match['rect'],window['rect']):
                available+=1
    status=f'已定位{available}/{len(profiles)}个指定范围'
    if any(profile['mode']=='window' and not profile.get('binding') for profile in profiles.values()):
        status+='；整窗配置需暂停后重新点击目标窗口'
    if available<len(profiles):status+='；未定位的范围暂停遮蔽，请暂停后重新选择；不会扩大保护'
    return status


def application_masks(windows, rectangles, uncertain, profiles=None, resolved=None):
    profiles=valid_profiles(profiles or {})
    if not windows:
        # 无法确认边界时不越过用户范围；状态栏提示范围暂不可用。
        return [], False
    masks=[];covers=[]
    excluded=[win['rect'] for win in windows if win.get('own_ui',False)]
    for window in windows:  # EnumWindows顺序：前景到背景。
        rect=window['rect'];mode=window['mode'];profile=profiles.get(window['key'])
        scope_valid=True
        if profiles and mode!='ignore':
            candidates=[win for win in windows if win['key']==window['key'] and win['mode']!='ignore']
            bound=profile.get('binding') if profile else None
            scope_valid=bool(profile and (bound and window.get('handle')==bound['handle'] and window.get('pid')==bound['pid']
                                         or not bound and profile['mode']!='window' and len(candidates)==1))
        if profile and mode != 'ignore':
            mode=profile['mode']
        scope=rect
        if mode=='tracked':
            match=(resolved or {}).get(window['key'])
            if match and match['handle']==window['handle'] and match['rect'] is not None:
                scope=intersect(match['rect'],rect)
                scope_valid=scope_valid and scope is not None
            else:scope_valid=False
        if mode=='chat':
            scope=rect
            client=window['client']
            if profile and profile.get('mode')=='chat' and resolved is None:
                cw,ch=client[2:]
                expected=profile['size']
                if abs(cw-expected[0])<=max(2,expected[0]*.02) and abs(ch-expected[1])<=max(2,expected[1]*.02):
                    x,y,width,height=profile['region']
                    scope=(client[0]+x*cw,client[1]+y*ch,width*cw,height*ch)
                else:scope_valid=False
            elif profile and profile.get('mode')=='chat':scope_valid=False
            # 无有效校准时整应用保护，不猜对话区域。
        selected=([] if not scope_valid else [scope] if mode in ('window','chat','tracked') else
                  [rect] if uncertain and mode!='ignore' else
                  [clip for candidate in rectangles if (clip:=intersect(candidate,rect))] if mode!='ignore' else [])
        # 程序自身始终保持可见，不能依赖Qt置顶窗口的瞬时排序。
        for cover in covers+excluded:
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
            result.append({'handle':int(handle),'pid':pid.value,'key':exe+'|'+cls.value,'mode':mode,'rect':clipped,'own_ui':pid.value in excluded,
                           'client':(origin.x-monitor['left'],origin.y-monitor['top'],client.right,client.bottom)})
        except (OSError,ValueError):pass
        return True
    user.EnumWindows(visit,0)
    return result
