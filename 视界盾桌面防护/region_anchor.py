"""可见控件结构定位，不读控件Name/Value或聊天内容。COM只在独立进程调用。"""
import ctypes
from ctypes import wintypes as w
import time


def contains(outer,inner):
    x,y,width,height=outer;a,b,c,d=inner
    return x<=a+2 and y<=b+2 and x+width>=a+c-2 and y+height>=b+d-2


def safe_id(value):
    import re
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z_][A-Za-z_.:-]{0,95}',value) else ''


def metadata(control):
    return {'kind':int(control.ControlType),'class':str(control.ClassName)[:128],'id':safe_id(control.AutomationId)}


def rect_of_control(control,origin):
    if control.IsOffscreen:return None
    r=control.BoundingRectangle
    return (r.left-origin[0],r.top-origin[1],r.right-r.left,r.bottom-r.top) if r.right>r.left and r.bottom>r.top else None


def native_nodes(handle,origin):
    user=ctypes.WinDLL('user32')
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetDlgCtrlID.argtypes=[w.HWND]
    user.IsWindowVisible.argtypes=[w.HWND]
    result=[]
    @ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    def visit(child,param):
        if len(result)>=256:return False
        if not user.IsWindowVisible(child):return True
        r=w.RECT();name=ctypes.create_unicode_buffer(128)
        if user.GetWindowRect(child,ctypes.byref(r)):
            user.GetClassNameW(child,name,128)
            result.append({'handle':int(child),'class':name.value,'id':user.GetDlgCtrlID(child),
                           'rect':(r.left-origin[0],r.top-origin[1],r.right-r.left,r.bottom-r.top)})
        return True
    user.EnumChildWindows(w.HWND(handle),visit,0)
    return result


def enroll_anchor(handle,selection,origin):
    native=[n for n in native_nodes(handle,origin) if contains(n['rect'],selection) and n['rect'][2]*n['rect'][3]<=selection[2]*selection[3]*1.5]
    if native:
        node=min(native,key=lambda n:n['rect'][2]*n['rect'][3])
        return {'type':'native','class':node['class'],'id':node['id'],'handle':node['handle'],'fraction':fraction(selection,node['rect'])}
    import uiautomation as auto
    root=auto.ControlFromHandle(handle);deadline=time.monotonic()+.6
    stack=[(root,[])];visited=0;candidates=[]
    while stack and visited<160 and time.monotonic()<deadline:
        control,path=stack.pop();visited+=1
        try:
            rect=rect_of_control(control,origin)
            if rect is None:continue
            if path and contains(rect,selection) and rect[2]*rect[3]<=selection[2]*selection[3]*1.5:
                candidates.append((rect,path))
            children=control.GetChildren()
            signatures=[metadata(c) for c in children]
            for i,child in enumerate(children):
                signature=signatures[i]
                # 相同结构不能仅依赖第几个节点，避免同级重排后追错控件。
                if signatures.count(signature)==1 and len(path)<12:
                    stack.append((child,path+[signature]))
        except Exception:continue
    if candidates:
        rect,path=min(candidates,key=lambda v:v[0][2]*v[0][3])
        return {'type':'uia','path':path,'fraction':fraction(selection,rect)}
    return {'type':'visual'}


def fraction(selection,rect):
    x,y,width,height=rect;a,b,c,d=selection
    return [(a-x)/width,(b-y)/height,c/width,d/height]


def locate_anchor(handle,anchor,origin):
    rect=None
    if anchor['type']=='native':
        nodes=[n for n in native_nodes(handle,origin) if n['class']==anchor['class'] and n['id']==anchor['id']]
        if anchor.get('handle'):
            nodes=[n for n in nodes if n['handle']==anchor['handle']]
        if len(nodes)==1:rect=nodes[0]['rect']
    elif anchor['type']=='uia':
        import uiautomation as auto
        control=auto.ControlFromHandle(handle)
        for signature in anchor['path']:
            matches=[c for c in control.GetChildren() if metadata(c)==signature]
            if len(matches)!=1:return None
            control=matches[0]
        rect=rect_of_control(control,origin)
    if rect is None:return None
    x,y,width,height=rect;a,b,c,d=anchor['fraction']
    return (x+a*width,y+b*height,c*width,d*height)
