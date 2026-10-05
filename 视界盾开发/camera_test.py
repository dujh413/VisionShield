"""摄像头基本测试；只显示画面，不保存视频或照片。"""
import argparse
import threading
import time

import cv2


def open_camera(index, backend, resolution=(640, 480)):
    backends = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
    camera = cv2.VideoCapture(index, backends[backend])
    if not camera.isOpened():
        camera.release()
        raise RuntimeError("摄像头未打开：检查权限、设备编号及其他程序是否占用。")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return camera


class LatestCameraFrame:
    """持续排空设备帧，仅保留最新一帧，避免低频推理积累摄像头旧画面。"""
    def __init__(self, camera):
        self.camera = camera
        self.condition = threading.Condition()
        self.stopped = False
        self.failed = False
        self.frame = None
        self.sequence = 0
        self.consumed = 0
        self.captured_at = None
        self.last_consumed_at = None
        self.thread = threading.Thread(target=self._capture,daemon=True)
        self.thread.start()

    def _capture(self):
        while not self.stopped:
            try:
                ok, frame = self.camera.read()
            except Exception:
                ok, frame = False, None
            with self.condition:
                if self.stopped:
                    return
                if not ok:
                    self.failed = True
                    self.condition.notify_all()
                    return
                self.frame = frame
                self.captured_at = time.monotonic()
                self.sequence += 1
                self.condition.notify_all()

    def read(self, timeout=1.5):
        with self.condition:
            available = self.condition.wait_for(
                lambda:self.failed or self.stopped or self.sequence != self.consumed,timeout)
            if not available or self.failed or self.stopped:
                return False, None
            self.consumed = self.sequence
            self.last_consumed_at = self.captured_at
            return True, self.frame

    def close(self):
        with self.condition:
            self.stopped = True
            self.frame = None
            self.condition.notify_all()
        self.camera.release()
        self.thread.join(timeout=1)


def window_closed(name):
    try:
        return cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def main():
    parser = argparse.ArgumentParser(description="摄像头基本检查：按 Q / Esc 或关闭窗口退出")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["auto", "dshow", "msmf"], default="auto")
    args = parser.parse_args()
    camera = open_camera(args.camera, args.backend)
    name = "A - Camera Test"
    count, start = 0, time.perf_counter()
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("摄像头读帧失败。")
            count += 1
            elapsed = time.perf_counter() - start
            fps = count / max(elapsed, 1e-6)
            height, width = frame.shape[:2]
            cv2.putText(frame, f"{width}x{height} | loop FPS {fps:.1f} | Q: exit",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27) or window_closed(name):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()
        print(f"摄像头已释放。处理帧数：{count}")


if __name__ == "__main__":
    main()
