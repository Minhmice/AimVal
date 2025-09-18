import cv2
import threading
import time
from typing import Optional


class UdpOpenCVSource:
    def __init__(self, url: str, max_width: int = 1280, max_height: int = 720, reconnect_interval_ms: int = 500):
        self.url = url
        self.max_width = max_width
        self.max_height = max_height
        self.reconnect_interval_ms = reconnect_interval_ms
        self.cap: Optional[cv2.VideoCapture] = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None

    def start(self) -> bool:
        self._stop.clear()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout=1.0)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None

    def _ensure_open(self) -> bool:
        if self.cap is None or not self.cap.isOpened():
            try:
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            except Exception:
                self.cap = cv2.VideoCapture(self.url)
        return self.cap.isOpened() if self.cap is not None else False

    def _run(self):
        last_try = 0.0
        while not self._stop.is_set():
            ok = self._ensure_open()
            if not ok:
                now = time.time()
                if now - last_try >= (self.reconnect_interval_ms / 1000.0):
                    last_try = now
                time.sleep(self.reconnect_interval_ms / 1000.0)
                continue
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(self.reconnect_interval_ms / 1000.0)
                continue
            h, w = frame.shape[:2]
            if self.max_width > 0 and self.max_height > 0:
                scale = min(self.max_width / max(1, w), self.max_height / max(1, h))
                if scale < 1.0:
                    nw, nh = int(w * scale), int(h * scale)
                    frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            with self._lock:
                self._frame = frame

    def get_latest_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()
