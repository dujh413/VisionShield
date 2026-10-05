"""Opt-in bounded-frequency metadata diagnostics; no pixels or recognized text."""
import csv
import json
from pathlib import Path


class PerformanceLog:
    EVENT_FIELDS = ('event','frame_id','elapsed_ms','mode','area_ratio','regions_count','diff_ms',
                    'capture_ms','queue_wait_ms','capture_to_infer_ms','stage_ms','batch_count',
                    'batch_widths','result_age_ms','receive_delay_ms','accepted','lines_count',
                    'index_ms','providers','backend','error')
    HEARTBEAT_FIELDS = ('elapsed_s','frame_id','frame_age_ms','ocr_ready','ocr_alive','capture_alive',
                        'sent_frames','unknown_regions','sensitive_lines','control_ms','blur_ms','paint_ms','error')

    def __init__(self, directory):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        self.events=(directory/'events.jsonl').open('w',encoding='utf-8',newline='')
        self.heartbeat_file=(directory/'heartbeat.csv').open('w',encoding='utf-8-sig',newline='')
        self.writer=csv.DictWriter(self.heartbeat_file,fieldnames=self.HEARTBEAT_FIELDS)
        self.writer.writeheader()
        self.last_heartbeat=None

    def event(self, now, started, item):
        safe={k:item[k] for k in self.EVENT_FIELDS if k in item}
        safe['elapsed_s']=round(now-started,3)
        self.events.write(json.dumps(safe,ensure_ascii=False,allow_nan=False)+'\n')
        self.events.flush()

    def heartbeat(self, now, started, item):
        if self.last_heartbeat is not None and now-self.last_heartbeat<1:
            return
        self.last_heartbeat=now
        safe={k:item.get(k) for k in self.HEARTBEAT_FIELDS}
        safe['elapsed_s']=round(now-started,3)
        self.writer.writerow(safe)
        self.heartbeat_file.flush()

    def close(self):
        self.events.close()
        self.heartbeat_file.close()
