import os
import csv
import time
from typing import Dict, Any


class MetricsLogger:
    def __init__(self, csv_path: str, log_every_n_frames: int = 20):
        self.csv_path = csv_path
        self.log_every = max(1, int(log_every_n_frames))
        self._last_written_frame = -1
        self._writer = None
        self._file = None
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    def start_session(self, session_meta: Dict[str, Any]):
        self._file = open(self.csv_path, mode="w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        header = [
            "timestamp",
            "fps",
            "latency_ms",
            "num_boxes",
            "num_keypoints",
        ]
        self._writer.writerow(["# SESSION"])
        for k, v in session_meta.items():
            self._writer.writerow([f"# {k}", v])
        self._writer.writerow([])
        self._writer.writerow(header)
        self._file.flush()

    def maybe_log(self, frame_index: int, row: Dict[str, Any]):
        if self._writer is None:
            return
        if frame_index - self._last_written_frame < self.log_every and frame_index != 0:
            return
        self._last_written_frame = frame_index
        self._writer.writerow([
            int(time.time() * 1000),
            row.get("fps", 0.0),
            row.get("latency_ms", 0.0),
            row.get("num_boxes", 0),
            row.get("num_keypoints", 0),
        ])
        self._file.flush()

    def close(self):
        try:
            if self._file:
                self._file.close()
        except Exception:
            pass
        self._file = None
        self._writer = None
