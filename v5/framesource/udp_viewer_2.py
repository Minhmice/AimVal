"""
UdpViewer2Source - Optimized UDP MJPEG frame source based on v2.0_Modern/udp_viewer_2.py
Focused on maximum performance streaming without GUI/viewer features.

Key features:
- Non-blocking UDP with dedicated receiver thread
- Drop-older strategy: always keep latest complete frame
- TurboJPEG decode if available, fallback to OpenCV
- Thread-safe frame buffer with stats tracking
- Minimal memory footprint and CPU usage
"""
from __future__ import annotations

import socket
import threading
import time
import select
from typing import Optional, Any, Dict
import numpy as np
import cv2

try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None  # type: ignore

from .base import FrameSource

# MJPEG markers
SOI = b"\xff\xd8"  # Start of Image
EOI = b"\xff\xd9"  # End of Image


class FrameBuffer:
    """Thread-safe storage for the latest complete JPEG frame bytes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: Optional[bytes] = None
        # Stats tracking
        self.frames_completed: int = 0
        self.bytes_received: int = 0
        self.packets_received: int = 0
        self.last_frame_ns: int = 0
        self.first_frame_ns: int = 0
        self.prev_frame_ns: int = 0
        self.rt_ms: float = 0.0
        self.rt_fps: float = 0.0
        self.avg_ms: float = 0.0
        self.avg_fps: float = 0.0
        self.last_sender_ip: Optional[str] = None

    def set_latest(self, data: bytes, sender_ip: Optional[str] = None) -> None:
        with self._lock:
            self._buf = data
            self.frames_completed += 1
            if sender_ip:
                self.last_sender_ip = sender_ip
            
            # Update timing stats
            now_ns = time.monotonic_ns()
            self.last_frame_ns = now_ns
            if self.first_frame_ns == 0:
                self.first_frame_ns = now_ns
            
            # Calculate real-time FPS
            if self.prev_frame_ns != 0:
                dt_ns = now_ns - self.prev_frame_ns
                if dt_ns > 0:
                    self.rt_ms = dt_ns / 1e6
                    self.rt_fps = 1e9 / dt_ns
            self.prev_frame_ns = now_ns
            
            # Calculate average FPS
            total_ns = now_ns - self.first_frame_ns if self.first_frame_ns else 0
            if total_ns > 0 and self.frames_completed > 0:
                self.avg_ms = (total_ns / self.frames_completed) / 1e6
                self.avg_fps = self.frames_completed / (total_ns / 1e9)

    def get_latest(self) -> Optional[bytes]:
        with self._lock:
            return self._buf

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "frames": self.frames_completed,
                "packets": self.packets_received,
                "bytes": self.bytes_received,
                "rt_ms": self.rt_ms,
                "rt_fps": self.rt_fps,
                "avg_ms": self.avg_ms,
                "avg_fps": self.avg_fps,
                "last_frame_ns": self.last_frame_ns,
                "last_sender_ip": self.last_sender_ip,
            }

    def update_packet_stats(self, packet_size: int, sender_ip: str) -> None:
        with self._lock:
            self.packets_received += 1
            self.bytes_received += packet_size
            self.last_sender_ip = sender_ip


class ReceiverThread(threading.Thread):
    """High-performance UDP receiver thread with frame assembly."""
    
    def __init__(
        self, 
        sock: socket.socket, 
        max_buffer_bytes: int, 
        frame_store: FrameBuffer
    ) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.max_buffer_bytes = max_buffer_bytes
        self.frame_store = frame_store
        self._stop = threading.Event()
        self._buffer = bytearray()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Main receiver loop with optimized frame extraction."""
        while not self._stop.is_set():
            # Drain socket with non-blocking select
            rlist, _, _ = select.select([self.sock], [], [], 0.002)
            while rlist and not self._stop.is_set():
                try:
                    data, addr = self.sock.recvfrom(65535)
                    self._buffer.extend(data)
                    # Update packet stats
                    self.frame_store.update_packet_stats(len(data), addr[0])
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            # Extract all complete JPEGs; keep only the latest
            latest: Optional[bytes] = None
            while True:
                start = self._buffer.find(SOI)
                if start == -1:
                    # No SOI found, clear buffer if too large
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer.clear()
                    break
                
                end = self._buffer.find(EOI, start + 2)
                if end == -1:
                    # No EOI found, trim buffer if too large
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024):]
                    break
                
                # Extract complete JPEG
                latest = bytes(self._buffer[start:end + 2])
                del self._buffer[:end + 2]

            # Store the latest complete frame
            if latest is not None:
                self.frame_store.set_latest(latest)


def decode_jpeg_cv2(buf: bytes) -> Optional[np.ndarray]:
    """Fallback JPEG decoder using OpenCV."""
    try:
        arr = np.frombuffer(buf, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


class UdpViewer2Source(FrameSource):
    """
    High-performance UDP MJPEG source based on v2.0_Modern/udp_viewer_2.py
    Optimized for streaming without GUI overhead.
    """
    
    def __init__(
        self, 
        host: str = "0.0.0.0", 
        port: int = 8080, 
        rcvbuf_mb: int = 64,
        use_turbojpeg: bool = True
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.rcvbuf_mb = max(1, rcvbuf_mb)
        self.use_turbojpeg = use_turbojpeg
        
        # Networking
        self.sock: Optional[socket.socket] = None
        self.max_buffer_bytes = 64 * 1024 * 1024  # 64MB
        
        # Threading
        self.frame_store = FrameBuffer()
        self.receiver_thread: Optional[ReceiverThread] = None
        
        # JPEG decoding
        self.jpeg_decoder: Optional[Any] = None
        self.turbo_available = False
        
        # Initialize TurboJPEG if available and requested
        if self.use_turbojpeg and TurboJPEG is not None:
            try:
                self.jpeg_decoder = TurboJPEG()
                self.turbo_available = True
            except Exception:
                self.turbo_available = False

    def start(self) -> bool:
        """Start the UDP receiver and frame processing."""
        try:
            # Create and configure socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(
                    socket.SOL_SOCKET, 
                    socket.SO_RCVBUF, 
                    self.rcvbuf_mb * 1024 * 1024
                )
            except OSError:
                pass  # Ignore if can't set buffer size
            
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)
            
            # Start receiver thread
            self.receiver_thread = ReceiverThread(
                self.sock, 
                self.max_buffer_bytes, 
                self.frame_store
            )
            self.receiver_thread.start()
            
            return super().start()
        except Exception:
            self.stop()
            return False

    def stop(self) -> None:
        """Stop the receiver thread and clean up resources."""
        try:
            if self.receiver_thread is not None:
                self.receiver_thread.stop()
                self.receiver_thread.join(timeout=1.0)
                self.receiver_thread = None
        except Exception:
            pass
        
        try:
            if self.sock is not None:
                self.sock.close()
                self.sock = None
        except Exception:
            pass
        
        super().stop()

    def get_latest_frame(self) -> Optional[Any]:
        """Get the latest decoded frame."""
        if not self.started:
            return None
        
        # Get latest JPEG bytes
        buf = self.frame_store.get_latest()
        if buf is None:
            return None
        
        # Decode JPEG
        frame = None
        if self.turbo_available and self.jpeg_decoder is not None:
            try:
                frame = self.jpeg_decoder.decode(buf)  # Returns BGR by default
            except Exception:
                frame = decode_jpeg_cv2(buf)
        else:
            frame = decode_jpeg_cv2(buf)
        
        return frame

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive source statistics."""
        base_stats = super().get_stats()
        frame_stats = self.frame_store.get_stats()
        
        return {
            **base_stats,
            **frame_stats,
            "turbo_enabled": self.turbo_available,
            "rcvbuf_mb": self.rcvbuf_mb,
            "host": self.host,
            "port": self.port,
        }

    def is_connected(self) -> bool:
        """Check if we're receiving data."""
        stats = self.frame_store.get_stats()
        if stats["frames"] == 0:
            return False
        
        # Consider connected if we received a frame in the last 5 seconds
        now_ns = time.monotonic_ns()
        time_since_last_frame_ms = (now_ns - stats["last_frame_ns"]) / 1e6
        return time_since_last_frame_ms < 5000.0
