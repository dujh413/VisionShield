"""统一入口；默认只加载轻量托盘界面。"""
import multiprocessing
from pathlib import Path
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.path.insert(0, str(Path(__file__).resolve().parent/'视界盾桌面防护'))
    try:
        if '--backend-service' in sys.argv:
            from guard_service import main
        else:
            from app_shell import main
        sys.exit(main())
    except Exception:
        import os
        import traceback
        folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'VisionShield'
        folder.mkdir(exist_ok=True)
        (folder/'launch_error.log').write_text(traceback.format_exc(), encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, '启动失败。错误记录：'+str(folder/'launch_error.log'), '视界盾', 0x10)
        sys.exit(1)
