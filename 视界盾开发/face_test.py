"""同步多人关键点测试：帧序号不是人物身份；默认不保存原始画面。"""
import argparse
import csv
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import statistics
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from camera_test import open_camera, window_closed


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="多人检测：按 Q / Esc 或关闭窗口退出")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["auto", "dshow", "msmf"], default="auto")
    parser.add_argument("--model", type=Path, default=root / "models" / "face_landmarker.task")
    parser.add_argument("--max-faces", type=int, default=3)
    args = parser.parse_args()
    if args.max_faces < 1:
        parser.error("--max-faces 必须至少为 1")
    if not args.model.is_file():
        parser.error(f"模型文件不存在：{args.model}。按操作指南先下载官方模型。")

    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=args.model.read_bytes()),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=args.max_faces,
    )
    records = root / "records"
    records.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_path = records / f"faces_{run_id}.csv"
    summary_path = records / f"faces_{run_id}_summary.json"
    name = "A - Multi-Face Test"
    camera = None
    count, max_seen, last_ms = 0, 0, -1
    inference_times = deque(maxlen=10000)
    error_message = None
    start = None
    actual_resolution = None
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            camera = open_camera(args.camera, args.backend)
            start = time.perf_counter()
            with log_path.open("w", newline="", encoding="utf-8-sig") as log_file:
                writer = csv.writer(log_file)
                writer.writerow(["frame", "capture_ms", "result_ms", "faces", "inference_ms"])
                while True:
                    ok, frame = camera.read()
                    if not ok:
                        raise RuntimeError("摄像头读帧失败。")
                    capture_ms = max(last_ms + 1, int((time.perf_counter() - start) * 1000))
                    last_ms = capture_ms
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    infer_start = time.perf_counter()
                    result = landmarker.detect_for_video(image, capture_ms)
                    infer_ms = (time.perf_counter() - infer_start) * 1000
                    result_ms = (time.perf_counter() - start) * 1000
                    inference_times.append(infer_ms)
                    count += 1
                    faces = len(result.face_landmarks)
                    max_seen = max(max_seen, faces)
                    height, width = frame.shape[:2]
                    actual_resolution = [width, height]
                    for frame_index, landmarks in enumerate(result.face_landmarks, 1):
                        xs = [point.x for point in landmarks]
                        ys = [point.y for point in landmarks]
                        x1 = max(0, min(width - 1, int(min(xs) * width)))
                        y1 = max(0, min(height - 1, int(min(ys) * height)))
                        x2 = max(0, min(width - 1, int(max(xs) * width)))
                        y2 = max(0, min(height - 1, int(max(ys) * height)))
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"frame face {frame_index}", (x1, max(45, y1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                        for point in landmarks[::8]:
                            cv2.circle(frame, (int(point.x * width), int(point.y * height)),
                                       1, (0, 255, 255), -1)
                    writer.writerow([count, capture_ms, round(result_ms, 3), faces, round(infer_ms, 3)])
                    if count % 30 == 0:
                        log_file.flush()
                    fps = count / max(time.perf_counter() - start, 1e-6)
                    cv2.putText(frame, f"Faces: {faces} | infer {infer_ms:.1f} ms | loop FPS {fps:.1f}",
                                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                    cv2.imshow(name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), ord("Q"), 27) or window_closed(name):
                        break
    except Exception as error:
        error_message = str(error)
        raise
    finally:
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()
        summary = {
            "model": str(args.model.resolve()), "max_faces_setting": args.max_faces,
            "camera": args.camera, "backend": args.backend, "actual_resolution": actual_resolution,
            "frames": count, "max_faces_seen": max_seen,
            "median_inference_ms": statistics.median(inference_times) if inference_times else None,
            "timing_samples": len(inference_times),
            "timing_scope": "latest 10000 frames (bounded memory)",
            "status": "error" if error_message else "completed",
            "error": error_message, "log": str(log_path),
            "raw_images_saved": False,
            "measurement": "inference only; not protection end-to-end latency",
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
