"""统一入口；默认只加载轻量托盘界面。"""
import multiprocessing
from pathlib import Path
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.path.insert(0, str(Path(__file__).resolve().parent/'视界盾桌面防护'))
    if '--backend-service' in sys.argv:
        from guard_service import main
    else:
        from app_shell import main
    sys.exit(main())
