"""第三步独立验收：每500毫秒采集主屏，不启动OCR/摄像头/遮罩。"""
import argparse
import json
import time

import cv2
from screen_capture import ScreenCapture, enable_dpi


def main():
    parser = argparse.ArgumentParser(description='Primary screen preview; Q/Esc to quit. No screenshots saved.')
    parser.add_argument('--check', action='store_true', help='采集3帧检查元数据，不显示预览')
    args = parser.parse_args()
    enable_dpi()
    capture = ScreenCapture()
    name = 'Step 3 - Primary Screen Preview (Q/Esc exit)'
    start = time.monotonic()
    next_capture = start
    frames, durations, intervals = 0, [], []
    last_at = None
    try:
        print('Primary monitor:', json.dumps(capture.monitor))
        if not args.check:
            cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
        while True:
            now = time.monotonic()
            if now >= next_capture:
                before = time.monotonic()
                frame = capture.grab()
                elapsed_ms = (time.monotonic()-before)*1000
                expected = (frame.monitor_rect['height'], frame.monitor_rect['width'], 3)
                if frame.image.shape != expected or frame.image.dtype.name != 'uint8':
                    raise RuntimeError(f'Unexpected image shape/dtype: {frame.image.shape}, {frame.image.dtype}')
                if last_at is not None:
                    intervals.append((frame.captured_at-last_at)*1000)
                last_at = frame.captured_at
                durations.append(elapsed_ms)
                frames += 1
                next_capture = before + 0.5
                if args.check:
                    print(json.dumps({'frame_id': frame.frame_id, 'captured_at': frame.captured_at,
                                      'monitor_rect': frame.monitor_rect, 'shape': frame.image.shape,
                                      'capture_ms': round(elapsed_ms, 2)}))
                    if frames >= 3:
                        break
                else:
                    # 仅缩小预览；原始采集数据始终保持物理像素尺寸。
                    height, width = frame.image.shape[:2]
                    ratio = min(1.0, 1000/width, 650/height)
                    preview = cv2.resize(frame.image, (round(width*ratio), round(height*ratio)))
                    cv2.rectangle(preview, (0,0), (preview.shape[1],52), (20,24,32), -1)
                    cv2.putText(preview, f'frame={frame.frame_id} size={width}x{height} capture={elapsed_ms:.1f}ms',
                                (10,20), cv2.FONT_HERSHEY_SIMPLEX, .45, (0,220,255), 1)
                    cv2.putText(preview, '500ms interval | memory only | Q/Esc exit',
                                (10,42), cv2.FONT_HERSHEY_SIMPLEX, .45, (255,255,255), 1)
                    cv2.imshow(name, preview)
            if args.check:
                time.sleep(min(0.02, max(0.0, next_capture-time.monotonic())))
            else:
                key = cv2.waitKey(20) & 0xff
                if key in (ord('q'), ord('Q'), 27):
                    break
                try:
                    if cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except cv2.error:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()
        if not args.check:
            cv2.destroyAllWindows()
        print(json.dumps({'frames': frames, 'elapsed_seconds': round(time.monotonic()-start, 2),
                          'mean_capture_ms': round(sum(durations)/len(durations),2) if durations else None,
                          'mean_interval_ms': round(sum(intervals)/len(intervals),2) if intervals else None,
                          'images_saved': False, 'ocr_started': False, 'camera_started': False}, indent=2))


if __name__ == '__main__':
    main()
