"""按DXGI顺序枚举DirectML设备，避免双显卡笔记本误用默认核显。"""
import ctypes
from ctypes import wintypes
import uuid


class AdapterDesc(ctypes.Structure):
    _fields_=[('Description',wintypes.WCHAR*128),('VendorId',wintypes.UINT),
              ('DeviceId',wintypes.UINT),('SubSysId',wintypes.UINT),('Revision',wintypes.UINT),
              ('DedicatedVideoMemory',ctypes.c_size_t),('DedicatedSystemMemory',ctypes.c_size_t),
              ('SharedSystemMemory',ctypes.c_size_t),('LuidLow',wintypes.DWORD),('LuidHigh',wintypes.LONG)]


def method(pointer,index,restype,*args):
    table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype,ctypes.c_void_p,*args)(table[index])


def adapters():
    library=ctypes.WinDLL('dxgi')
    iid=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    factory=ctypes.c_void_p()
    library.CreateDXGIFactory1.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    library.CreateDXGIFactory1.restype=wintypes.LONG
    if library.CreateDXGIFactory1(ctypes.byref(iid),ctypes.byref(factory))!=0:
        return []
    result=[]
    try:
        for index in range(16):
            adapter=ctypes.c_void_p()
            status=method(factory,7,wintypes.LONG,wintypes.UINT,ctypes.POINTER(ctypes.c_void_p))(factory,index,ctypes.byref(adapter))
            if status!=0:
                break
            try:
                desc=AdapterDesc()
                if method(adapter,8,wintypes.LONG,ctypes.POINTER(AdapterDesc))(adapter,ctypes.byref(desc))==0:
                    result.append({'device_id':index,'name':desc.Description,'vendor':desc.VendorId,
                                   'vram_mb':int(desc.DedicatedVideoMemory/1024**2)})
            finally:
                method(adapter,2,wintypes.ULONG)(adapter)
    finally:
        method(factory,2,wintypes.ULONG)(factory)
    return result


def preferred_adapter():
    available=[a for a in adapters() if a['vendor'] in (0x10de,0x1002,0x8086)]
    return max(available,key=lambda a:(a['vendor']==0x10de,a['vram_mb'])) if available else None


if __name__=='__main__':
    import json
    print(json.dumps(adapters()))
