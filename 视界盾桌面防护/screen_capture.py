import ctypes
import time
import mss
import numpy as np
import queue
import threading
from dataclasses import dataclass


def enable_dpi():
    # Qt和采集统一使用物理屏幕坐标；必须在QApplication之前调用。
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


@dataclass
class Frame:
    frame_id: int
    captured_at: float
    monitor_rect: dict
    image: np.ndarray
    capture_ms: float = 0.0
    submitted_at: float = 0.0


class ScreenCapture:
    def __init__(self):
        self.source = mss.mss()
        # 主屏物理坐标原点为(0,0)，不假定mss.monitors[1]一定为主屏。
        self.monitor = next((dict(m) for m in self.source.monitors[1:]
                             if m['left'] == 0 and m['top'] == 0), None)
        if self.monitor is None:
            self.source.close()
            raise RuntimeError('无法找到主显示器')
        self.sequence = 0

    def grab(self):
        started=time.monotonic()
        self.sequence += 1
        image = np.asarray(self.source.grab(self.monitor))[:, :, :3].copy()
        # Each capture owns fresh pixels; consumers may share but never alter them.
        image.flags.writeable = False
        return Frame(self.sequence, started, self.monitor, image, (time.monotonic()-started)*1000)

    def close(self):
        self.source.close()


class CaptureWorker:
    """采集不占用Qt主线程；只保留最新帧。mss对象在采集线程内创建。"""
    def __init__(self,interval=.1):
        self.interval=interval
        self.stop=threading.Event()
        self.frames=queue.Queue(1)
        self.error=None
        self.thread=threading.Thread(target=self.run,daemon=True,name='screen-capture')
        self.thread.start()

    def run(self):
        capture=None
        try:
            capture=ScreenCapture()
            while not self.stop.is_set():
                started=time.monotonic()
                frame=capture.grab()
                try: self.frames.get_nowait()
                except queue.Empty: pass
                self.frames.put_nowait(frame)
                self.stop.wait(max(0,self.interval-(time.monotonic()-started)))
        except Exception as error:
            self.error=type(error).__name__
        finally:
            if capture: capture.close()

    def latest(self):
        if self.error:
            raise RuntimeError('桌面采集异常：'+self.error)
        try: return self.frames.get_nowait()
        except queue.Empty: return None

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise TimeoutError('桌面采集线程未停止')
        try: self.frames.get_nowait()
        except queue.Empty: pass


def same_image(first, second):
    return first.shape == second.shape and np.array_equal(first, second)


def change_regions(first, second, tile=64):
    if first is None or first.shape != second.shape:
        return [(0, 0, second.shape[1], second.shape[0])]
    mask = np.any(first != second, axis=2)
    regions = []
    height, width = mask.shape
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            if mask[y:y+tile, x:x+tile].any():
                regions.append((x, y, min(tile, width-x), min(tile, height-y)))
    return regions
