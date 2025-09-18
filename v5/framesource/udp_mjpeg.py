import socket
import threading
import select
import time
from typing import Optional, Any
import numpy as np
import cv2

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class _FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: Optional[bytes] = None
        self.frames_completed: int = 0
        self.bytes_received: int = 0
        self.packets_received: int = 0
        self.last_packet_ns: int = 0
        self.last_frame_ns: int = 0
        self.first_frame_ns: int = 0
        self.prev_frame_ns: int = 0
        self.rt_ms: float = 0.0
        self.rt_fps: float = 0.0
        self.avg_ms: float = 0.0
        self.avg_fps: float = 0.0
        self.last_sender_ip: Optional[str] = None

    def set(self, data: bytes, sender_ip: Optional[str] = None) -> None:
        with self._lock:
            self._buf = data
            self.frames_completed += 1
            if sender_ip:
                self.last_sender_ip = sender_ip
            now_ns = time.monotonic_ns()
            self.last_frame_ns = now_ns
            if self.first_frame_ns == 0:
                self.first_frame_ns = now_ns
            if self.prev_frame_ns != 0:
                dt_ns = now_ns - self.prev_frame_ns
                if dt_ns > 0:
                    self.rt_ms = dt_ns / 1e6
                    self.rt_fps = 1e9 / dt_ns
            self.prev_frame_ns = now_ns
            total_ns = now_ns - self.first_frame_ns if self.first_frame_ns else 0
            if total_ns > 0 and self.frames_completed > 0:
                self.avg_ms = (total_ns / self.frames_completed) / 1e6
                self.avg_fps = self.frames_completed / (total_ns / 1e9)

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._buf


class UdpMjpegSource:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, rcvbuf_mb: int = 32) -> None:
        self.host = host
        self.port = int(port)
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))
        self.max_buffer_bytes = 8 * 1024 * 1024
        self.store = _FrameStore()
        self.sock: Optional[socket.socket] = None
        self.receiver: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024)
            except OSError:
                pass
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)
            self._stop.clear()
            self.receiver = threading.Thread(target=self._run, daemon=True)
            self.receiver.start()
            return True
        except Exception:
            self.stop()
            return False

    def stop(self) -> None:
        try:
            self._stop.set()
            if self.receiver is not None:
                self.receiver.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self.receiver = None

    def _is_valid_jpeg(self, data: bytes) -> bool:
        try:
            if len(data) < 4:
                return False
            if not data.startswith(SOI) or not data.endswith(EOI):
                return False
            arr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img is not None and img.size > 0
        except Exception:
            return False

    def _run(self) -> None:
        buffer = bytearray()
        while not self._stop.is_set():
            rlist, _, _ = select.select([self.sock], [], [], 0.005)
            while rlist and not self._stop.is_set():
                try:
                    data, addr = self.sock.recvfrom(65535)
                    if len(buffer) < self.max_buffer_bytes:
                        buffer.extend(data)
                    with self.store._lock:
                        self.store.packets_received += 1
                        self.store.bytes_received += len(data)
                        self.store.last_packet_ns = time.monotonic_ns()
                        self.store.last_sender_ip = addr[0]
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            latest: Optional[bytes] = None
            while True:
                start = buffer.find(SOI)
                if start == -1:
                    if len(buffer) > self.max_buffer_bytes:
                        buffer.clear()
                    break
                end = buffer.find(EOI, start + 2)
                if end == -1:
                    if len(buffer) > self.max_buffer_bytes:
                        buffer[:] = buffer[-(2 * 1024 * 1024):]
                    break
                jpeg = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                if self._is_valid_jpeg(jpeg):
                    latest = jpeg
                else:
                    continue
            if latest is not None:
                self.store.set(latest)

    def get_latest_frame(self) -> Optional[Any]:
        buf = self.store.get()
        if buf is None:
            return None
        try:
            arr = np.frombuffer(buf, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                return None
            return img
        except Exception:
            return None

    def get_stats(self) -> dict:
        with self.store._lock:
            return {
                "packets": int(self.store.packets_received),
                "bytes": int(self.store.bytes_received),
                "frames": int(self.store.frames_completed),
                "last_packet_ns": int(self.store.last_packet_ns),
                "last_frame_ns": int(self.store.last_frame_ns),
                "rt_ms": float(self.store.rt_ms),
                "rt_fps": float(self.store.rt_fps),
                "avg_ms": float(self.store.avg_ms),
                "avg_fps": float(self.store.avg_fps),
                "last_sender_ip": self.store.last_sender_ip,
            }
