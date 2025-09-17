import socket
import threading
import select
import time
from typing import Optional

import numpy as np
import cv2

try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None  # type: ignore


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
            # realtime
            if self.prev_frame_ns != 0:
                dt_ns = now_ns - self.prev_frame_ns
                if dt_ns > 0:
                    self.rt_ms = dt_ns / 1e6
                    self.rt_fps = 1e9 / dt_ns
            self.prev_frame_ns = now_ns
            # average
            total_ns = now_ns - self.first_frame_ns if self.first_frame_ns else 0
            if total_ns > 0 and self.frames_completed > 0:
                self.avg_ms = (total_ns / self.frames_completed) / 1e6
                self.avg_fps = self.frames_completed / (total_ns / 1e9)

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._buf


class _Receiver(threading.Thread):
    def __init__(
        self, sock: socket.socket, max_buffer_bytes: int, store: _FrameStore
    ) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.max_buffer_bytes = max_buffer_bytes
        self.store = store
        self._stop = threading.Event()
        self._buffer = bytearray()

    def stop(self) -> None:
        self._stop.set()
    
    def _is_valid_jpeg(self, data: bytes) -> bool:
        """Check if the data is a valid JPEG frame."""
        try:
            # Basic JPEG validation
            if len(data) < 4:
                return False
            if not data.startswith(SOI) or not data.endswith(EOI):
                return False
            # Try to decode with OpenCV to validate
            nparr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return img is not None and img.size > 0
        except Exception:
            return False

    def run(self) -> None:
        while not self._stop.is_set():
            rlist, _, _ = select.select([self.sock], [], [], 0.002)
            while rlist and not self._stop.is_set():
                try:
                    data, addr = self.sock.recvfrom(65535)
                    # Only add data if buffer is not too large
                    if len(self._buffer) < self.max_buffer_bytes:
                        self._buffer.extend(data)
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
                start = self._buffer.find(SOI)
                if start == -1:
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer.clear()
                    break
                end = self._buffer.find(EOI, start + 2)
                if end == -1:
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024) :]
                    break
                # Extract JPEG frame
                jpeg_data = bytes(self._buffer[start : end + 2])
                del self._buffer[: end + 2]
                # Validate JPEG frame before storing
                if self._is_valid_jpeg(jpeg_data):
                    latest = jpeg_data
                else:
                    continue

            if latest is not None:
                self.store.set(latest)


class UdpFrameSource:
    """Receive MJPEG over UDP and expose latest decoded BGR frame."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        rcvbuf_mb: int = 64,
        use_turbo: bool = True,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))
        self.max_buffer_bytes = 64 * 1024 * 1024
        self.store = _FrameStore()
        self.sock: Optional[socket.socket] = None
        self.receiver: Optional[_Receiver] = None
        self.jpeg: Optional[object] = None
        self.use_turbo = use_turbo and (TurboJPEG is not None)
        if self.use_turbo and TurboJPEG is not None:
            try:
                self.jpeg = TurboJPEG()
            except Exception:
                self.jpeg = None
                self.use_turbo = False

    def start(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024
                )
            except OSError:
                pass
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)
            self.receiver = _Receiver(self.sock, self.max_buffer_bytes, self.store)
            self.receiver.start()
            return True
        except Exception:
            self.stop()
            return False

    def get_latest_frame(self) -> Optional[np.ndarray]:
        buf = self.store.get()
        if buf is None:
            return None
        if self.use_turbo and self.jpeg is not None:
            try:
                frame = self.jpeg.decode(buf)  # type: ignore[attr-defined]
                return frame
            except Exception:
                pass
        try:
            arr = np.frombuffer(buf, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                return None
            return img
        except Exception:
            return None

    def stop(self) -> None:
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver.join(timeout=1.0)
            self.receiver = None
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

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


