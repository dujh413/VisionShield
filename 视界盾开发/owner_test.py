"""接续 face_test：短期跟踪、点击机主、保护请求；尚未接字段隐藏。"""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from camera_test import open_camera, window_closed
from owner_tracking import OwnerSession, ShortTracker


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="点击选机主；R重置；Q/Esc退出。仅输出保护请求。")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["auto", "dshow", "msmf"], default="auto")
    parser.add_argument("--model", type=Path, default=root / "models" / "face_landmarker.task")
    parser.add_argument("--max-faces", type=int, default=3)
    args = parser.parse_args()
    if args.max_faces < 1:
        parser.error("max-faces必须至少为1")
    if not args.model.is_file():
        parser.error("模型不存在；沿用 face_test 的 --model 参数。")
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=args.model.read_bytes()),
        running_mode=vision.RunningMode.VIDEO, num_faces=args.max_faces,
    )
    tracker, owner = ShortTracker(), OwnerSession()
    records = root / "records"
    records.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_path = records / f"owner_{run_id}.csv"
    summary_path = records / f"owner_{run_id}_summary.json"
    name = "A - Owner Session (no content protection yet)"
    camera, frames, max_seen, start = None, 0, 0, time.perf_counter()
    last_ms, error, status = -1, None, "completed"
    context = {"frame": 0, "capture_ms": 0, "width": 1, "height": 1,
               "ready": False, "message": "Click your face; R reset; Q exit"}
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            camera = open_camera(args.camera, args.backend)
            start = time.perf_counter()
            with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["event", "frame", "capture_ms", "event_ms", "faces",
                                 "track_ids", "owner_id", "owner_state", "protect_request", "reason"])

                def record(event, reason=""):
                    writer.writerow([event, context["frame"], context["capture_ms"],
                                     round((time.perf_counter() - start) * 1000, 3), len(owner.tracks),
                                     ";".join(str(item.track_id) for item in owner.tracks),
                                     owner.owner_id, owner.state, int(owner.protect_request), reason])

                def click(event, x, y, flags, parameter):
                    if event != cv2.EVENT_LBUTTONDOWN or not context["ready"]:
                        return
                    nx, ny = x / context["width"], y / context["height"]
                    hits = [item for item in owner.tracks
                            if item.bbox[0] <= nx <= item.bbox[2]
                            and item.bbox[1] <= ny <= item.bbox[3]]
                    if len(hits) == 1 and owner.select(hits[0].track_id):
                        context["message"] = f"Selected owner track {owner.owner_id}"
                        record("select", "manual_click")
                    else:
                        context["message"] = "Selection rejected: click one clear, separate face"
                        record("select_rejected", "no_unique_reliable_face")
                    file.flush()

                cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
                cv2.setMouseCallback(name, click)
                while True:
                    ok, frame = camera.read()
                    if not ok:
                        raise RuntimeError("摄像头读帧失败。")
                    timestamp_ms = max(last_ms + 1, int((time.perf_counter() - start) * 1000))
                    last_ms = timestamp_ms
                    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                     data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    result = landmarker.detect_for_video(image, timestamp_ms)
                    boxes = []
                    for landmarks in result.face_landmarks:
                        xs, ys = [item.x for item in landmarks], [item.y for item in landmarks]
                        box = (max(0.0, min(xs)), max(0.0, min(ys)),
                               min(1.0, max(xs)), min(1.0, max(ys)))
                        if box[2] > box[0] and box[3] > box[1]:
                            boxes.append(box)
                    frames += 1
                    max_seen = max(max_seen, len(boxes))
                    previous_id = owner.owner_id
                    owner.update(tracker.update(boxes, timestamp_ms))
                    height, width = frame.shape[:2]
                    context.update(frame=frames, capture_ms=timestamp_ms,
                                   width=width, height=height, ready=True)
                    if previous_id is not None and owner.owner_id is None:
                        context["message"] = "Owner lost or uncertain: click again"
                        record("owner_lost", "missing_ambiguous_or_stale")
                    for item in owner.tracks:
                        is_owner = item.track_id == owner.owner_id
                        color = ((0, 255, 0) if is_owner else (0, 180, 255)) if item.reliable else (0, 0, 255)
                        x1, y1, x2, y2 = (int(item.bbox[0] * width), int(item.bbox[1] * height),
                                          int(item.bbox[2] * width), int(item.bbox[3] * height))
                        role = "OWNER" if is_owner else ("OTHER" if item.reliable else "UNCERTAIN")
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(frame, f"ID {item.track_id} {role}", (x1, max(80, y1 - 6)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                    cv2.putText(frame, f"{owner.state} | PROTECT_REQUEST={int(owner.protect_request)}",
                                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
                    cv2.putText(frame, context["message"], (8, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                    cv2.putText(frame, "SIGNAL ONLY: not connected to sensitive fields", (8, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
                    record("frame")
                    if frames % 30 == 0:
                        file.flush()
                    cv2.imshow(name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("r"), ord("R")):
                        owner.reset()
                        context["message"] = "Reset: click your face again"
                        record("reset", "manual_reset")
                        file.flush()
                    if key in (ord("q"), ord("Q"), 27) or window_closed(name):
                        break
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception as exc:
        status, error = "error", str(exc)
        raise
    finally:
        owner.reset()
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()
        summary = {"frames": frames, "max_faces_seen": max_seen, "status": status,
                   "error": error, "log": str(csv_path), "raw_images_saved": False,
                   "identity_mode": "manual_session_tracking",
                   "content_protection_connected": False,
                   "matching_parameters": {"max_gap_ms": 500, "max_area_ratio": 2.5,
                                           "max_normalized_center_distance": 0.6,
                                           "overlap_reject_iou": 0.1, "ambiguity_margin": 0.25}}
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
