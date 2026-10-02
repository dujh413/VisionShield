import ctypes
from ctypes import wintypes
from PySide6.QtWidgets import QWidget


def create_demo():
    window=QWidget()
    window.setWindowTitle('虚构内容 · 标准Windows编辑器（可直接修改）')
    window.resize(750,330)
    window.show()
    user=ctypes.windll.user32
    user.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
                                  ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                  wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,ctypes.c_void_p]
    user.CreateWindowExW.restype=wintypes.HWND
    handle=user.CreateWindowExW(0,'EDIT','手机号：13800138000\r\n验证码：246810\r\n邮箱：demo@example.com\r\n今天下午一起去图书馆。',
                               0x50000004,10,10,700,280,wintypes.HWND(int(window.winId())),None,None,None)
    if not handle:
        window.close()
        raise RuntimeError('无法建立标准Windows文本测试控件')
    return window,int(handle)
