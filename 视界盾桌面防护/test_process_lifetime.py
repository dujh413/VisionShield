import ctypes
from ctypes import wintypes
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from process_lifetime import ProcessJob


@unittest.skipUnless(sys.platform=='win32','Windows Job test')
class LifetimeTests(unittest.TestCase):
    def test_job_close_stops_parent_and_descendant(self):
        # 子进程只有加入Job之后才允许创建孙进程，避免测试自身产生孤儿。
        with tempfile.TemporaryDirectory() as folder:
            ready=Path(folder)/'start'
            child_pid=Path(folder)/'child'
            code="""import pathlib,subprocess,sys,time
ready=pathlib.Path(sys.argv[1]);pid_file=pathlib.Path(sys.argv[2])
while not ready.exists():time.sleep(.02)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
pid_file.write_text(str(child.pid))
time.sleep(60)
"""
            job=ProcessJob()
            parent=subprocess.Popen([sys.executable,'-c',code,str(ready),str(child_pid)],
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                job.attach(parent.pid)
                ready.touch()
                deadline=time.monotonic()+5
                while not child_pid.exists() and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertTrue(child_pid.exists(),'descendant did not start')
                pid=int(child_pid.read_text())
                api=job.api
                api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
                api.WaitForSingleObject.restype=wintypes.DWORD
                handle=api.OpenProcess(0x100000,False,pid)
                self.assertTrue(handle)
                try:
                    job.close()
                    parent.wait(timeout=5)
                    self.assertEqual(api.WaitForSingleObject(handle,5000),0)
                finally:
                    api.CloseHandle(handle)
            finally:
                job.close()
                if parent.poll() is None:parent.kill();parent.wait(timeout=5)


if __name__=='__main__':unittest.main()
