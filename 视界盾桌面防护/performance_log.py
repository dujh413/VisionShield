"""Opt-in bounded-frequency metadata diagnostics; no pixels or recognized text."""
import csv
import json
import math
import re
from pathlib import Path


class PerformanceLog:
    EVENT_FIELDS = ('event','frame_id','elapsed_ms','mode','area_ratio','regions_count','diff_ms',
                    'capture_ms','queue_wait_ms','capture_to_infer_ms','stage_ms','batch_count',
                    'batch_widths','result_age_ms','receive_delay_ms','accepted','lines_count',
                    'index_ms','providers','backend','effect','radius','blur_backend',
                    'blur_device','blur_gpu_ms','blur_fallback','error')
    HEARTBEAT_FIELDS = ('elapsed_s','frame_id','frame_age_ms','ocr_ready','ocr_alive','capture_alive',
                        'sent_frames','unknown_regions','sensitive_lines','effect','radius',
                        'control_ms','blur_ms','paint_ms','blur_backend','blur_device',
                        'blur_gpu_ms','blur_fallback','error')

    @staticmethod
    def _metadata_value(key, value):
        """Bound new rendering metadata; never stringify image/error objects."""
        if key == 'effect':
            return value if isinstance(value, str) and value in ('off','block','blur') else None
        if key == 'radius':
            # The input has a 128-character limit; preserve its exact integer.
            return value if type(value) is int and 0 <= value < 10**128 else None
        if key == 'blur_backend':
            return value if isinstance(value, str) and value in (
                'none','copy','cpu','opencl-gpu','mixed') else None
        if key == 'blur_gpu_ms':
            if type(value) not in (int, float):
                return None
            try:
                duration = float(value)
            except OverflowError:
                return None
            return duration if math.isfinite(duration) and duration >= 0 else None
        if key == 'blur_device':
            return value if isinstance(value, str) and len(value) <= 256 and all(
                ord(character) >= 32 and ord(character) != 127 for character in value) else None
        if key == 'blur_fallback':
            return value if isinstance(value, str) and re.fullmatch(
                r'[A-Za-z_][A-Za-z0-9_:.-]{0,127}', value) else None
        return value

    def __init__(self, directory):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        self.events=(directory/'events.jsonl').open('w',encoding='utf-8',newline='')
        self.heartbeat_file=(directory/'heartbeat.csv').open('w',encoding='utf-8-sig',newline='')
        self.writer=csv.DictWriter(self.heartbeat_file,fieldnames=self.HEARTBEAT_FIELDS)
        self.writer.writeheader()
        self.last_heartbeat=None

    def event(self, now, started, item):
        safe={k:self._metadata_value(k,item[k]) for k in self.EVENT_FIELDS if k in item}
        safe['elapsed_s']=round(now-started,3)
        self.events.write(json.dumps(safe,ensure_ascii=False,allow_nan=False)+'\n')
        self.events.flush()

    def heartbeat(self, now, started, item):
        if self.last_heartbeat is not None and now-self.last_heartbeat<1:
            return
        self.last_heartbeat=now
        safe={k:self._metadata_value(k,item.get(k)) for k in self.HEARTBEAT_FIELDS}
        safe['elapsed_s']=round(now-started,3)
        self.writer.writerow(safe)
        self.heartbeat_file.flush()

    def close(self):
        self.events.close()
        self.heartbeat_file.close()
