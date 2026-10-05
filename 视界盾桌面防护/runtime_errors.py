"""记录最近一次Python回调异常，无终端运行也可诊断；不累积历史。"""
from datetime import datetime
import sys
import traceback
from runtime_paths import user_root


def install_exception_logging():
    original = sys.excepthook

    def record(kind, error, tb):
        try:
            folder = user_root()
            folder.mkdir(parents=True, exist_ok=True)
            message = ''.join(traceback.format_exception(kind, error, tb))[-65536:]
            (folder/'runtime_error.log').write_text(datetime.now().isoformat(timespec='seconds')+'\n'+message, encoding='utf-8')
        except OSError:
            pass
        if sys.stderr is not None:
            original(kind, error, tb)

    sys.excepthook = record
