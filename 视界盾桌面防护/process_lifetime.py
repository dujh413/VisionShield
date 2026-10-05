"""Windows Job确保前端/服务异常退出时，整个识别进程树一并释放。"""
import ctypes
from ctypes import wintypes


class ProcessJob:
    def __init__(self):
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        api=self.api
        api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        api.CreateJobObjectW.restype=wintypes.HANDLE
        api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        api.SetInformationJobObject.restype=wintypes.BOOL
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.OpenProcess.restype=wintypes.HANDLE
        api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        api.AssignProcessToJobObject.restype=wintypes.BOOL
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        api.CloseHandle.restype=wintypes.BOOL

        class Limits(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),
                      ('flags',wintypes.DWORD),('min_working_set',ctypes.c_size_t),
                      ('max_working_set',ctypes.c_size_t),('active_processes',wintypes.DWORD),
                      ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),
                      ('scheduling',wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_=[('basic',Limits),('io',ctypes.c_uint64*6),
                      ('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                      ('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]

        self.handle=api.CreateJobObjectW(None,None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits=ExtendedLimits()
        limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def attach(self,pid):
        process=self.api.OpenProcess(0x0101,False,pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle,process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(process)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle=None
