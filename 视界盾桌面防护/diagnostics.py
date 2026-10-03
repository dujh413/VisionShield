"""Optional metadata-only events and one-second heartbeats. Never accepts image/text payloads."""
import csv
import json
from pathlib import Path


class Diagnostics:
    HEARTBEAT_FIELDS = ('elapsed_s','frame_id','frame_age_s','ocr_ready','ocr_alive','capture_alive',
                        'control_timer_active','coordinates_valid','coverage_complete','valid_lines',
                        'unknown_regions','sensitive_lines','effect','radius','blur_ms','error')
    EVENT_FIELDS = ('event','frame_id','captured_at','ocr_finished_at','elapsed_ms','mode','area_ratio',
                    'regions_count','diff_ms','capture_ms','queue_wait_ms','capture_to_infer_ms','stage_ms',
                    'accepted','result_age_ms','receive_delay_ms','lines_count','error','blur_ms','providers','backend')

    def __init__(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.events = (root/'ocr_events.jsonl').open('w', encoding='utf-8', newline='')
        self.heartbeat_file = (root/'heartbeat.csv').open('w', encoding='utf-8-sig', newline='')
        self.writer = csv.DictWriter(self.heartbeat_file, fieldnames=self.HEARTBEAT_FIELDS)
        self.writer.writeheader()
        self.last_heartbeat = None

    def event(self, now, started, item):
        safe = {key: item[key] for key in self.EVENT_FIELDS if key in item}
        safe['elapsed_s'] = round(now-started, 3)
        self.events.write(json.dumps(safe, ensure_ascii=False, allow_nan=False)+'\n')
        self.events.flush()

    def heartbeat(self, now, started, data):
        if self.last_heartbeat is not None and now-self.last_heartbeat < 1:
            return
        self.last_heartbeat = now
        safe = {key: data.get(key) for key in self.HEARTBEAT_FIELDS}
        safe['elapsed_s'] = round(now-started, 3)
        self.writer.writerow(safe)
        self.heartbeat_file.flush()

    def close(self):
        self.events.close()
        self.heartbeat_file.close()
