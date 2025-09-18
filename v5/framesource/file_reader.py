import cv2
import threading
import time
from typing import Optional, Union


class FileReaderSource:
    def __init__(self, url: Union[str, int]):
        self.url = url
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
            self.cap = cv2.VideoCapture(self.url)
        return self.cap.isOpened() if self.cap is not None else False

    def _run(self):
        while not self._stop.is_set():
            if not self._ensure_open():
                time.sleep(0.25)
                continue
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame

    def get_latest_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()
