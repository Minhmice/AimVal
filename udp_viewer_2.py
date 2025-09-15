#!/usr/bin/env python3
"""
udp_viewer_2.py — Threaded UDP MJPEG viewer for Raspberry Pi 5 (low-latency)

Highlights:
- Non-blocking UDP + dedicated receiver thread that assembles JPEG frames
- Drop-older strategy: always keep only the latest complete frame
- TurboJPEG decode if available, fallback to OpenCV imdecode
- Lazy GUI window creation; optional scaled display to reduce cost
- Terminal metrics (real-time and average) with controlled update rate

Usage:
  python udp_viewer_2.py --rcvbuf-mb 64 --scale 0.75 --max-display-fps 120 --metrics-rate 15

Install optional TurboJPEG on Pi:
  sudo apt-get update && sudo apt-get install -y libturbojpeg0-dev
  pip install PyTurboJPEG
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np

try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None  # type: ignore

HOST = "0.0.0.0"
PORT = 8080
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
WINDOW_NAME = "UDP Stream (v2)"

_LOG_LEVELS = {"error": 40, "warn": 30, "info": 20, "debug": 10}
_current_log_level = _LOG_LEVELS["info"]


def log(level: str, msg: str) -> None:
    lvl = _LOG_LEVELS.get(level, 20)
    if lvl >= _current_log_level:
        print(f"[{level.upper()}] {msg}")


def can_use_gui() -> bool:
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def decode_jpeg_cv2(buf: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


class FrameBuffer:
    """Thread-safe storage for the latest complete JPEG frame bytes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: Optional[bytes] = None

    def set_latest(self, data: bytes) -> None:
        with self._lock:
            self._buf = data

    def get_latest(self) -> Optional[bytes]:
        with self._lock:
            return self._buf


class ReceiverThread(threading.Thread):
    def __init__(self, sock: socket.socket, max_buffer_bytes: int, frame_store: FrameBuffer) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.max_buffer_bytes = max_buffer_bytes
        self.frame_store = frame_store
        self._stop = threading.Event()
        self._buffer = bytearray()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            # Drain socket
            rlist, _, _ = select.select([self.sock], [], [], 0.002)
            while rlist and not self._stop.is_set():
                try:
                    data, _ = self.sock.recvfrom(65535)
                    self._buffer.extend(data)
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            # Extract all complete JPEGs; keep only the latest
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
                latest = bytes(self._buffer[start : end + 2])
                del self._buffer[: end + 2]

            if latest is not None:
                self.frame_store.set_latest(latest)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Threaded UDP MJPEG viewer")
    p.add_argument("--rcvbuf-mb", type=int, default=64, help="UDP receive buffer (MB)")
    p.add_argument("--scale", type=float, default=1.0, help="Display scale factor")
    p.add_argument("--cv-threads", type=int, default=0, help="OpenCV threads (>0 to set)")
    p.add_argument("--max-display-fps", type=float, default=0.0, help="Cap display FPS (0=unlimited)")
    p.add_argument("--metrics-rate", type=float, default=15.0, help="TTY metrics update rate (Hz)")
    p.add_argument("--no-gui", action="store_true", help="Disable GUI window")
    p.add_argument("--turbojpeg", action="store_true", help="Force TurboJPEG if available")
    p.add_argument("--log-level", type=str, default="info", choices=list(_LOG_LEVELS.keys()))
    return p


def main() -> None:
    global _current_log_level
    args = build_argparser().parse_args()
    _current_log_level = _LOG_LEVELS.get(args.log_level, 20)

    if args.cv_threads and args.cv_threads > 0:
        try:
            cv2.setNumThreads(int(args.cv_threads))
            cv2.setUseOptimized(True)
            log("info", f"OpenCV threads set to {args.cv_threads}")
        except Exception as e:
            log("warn", f"Failed to set OpenCV threads: {e}")

    log("info", f"Listening on udp://{HOST}:{PORT}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, max(1, args.rcvbuf_mb) * 1024 * 1024)
    except OSError:
        pass
    sock.bind((HOST, PORT))
    sock.setblocking(False)

    max_buffer_bytes = 64 * 1024 * 1024
    store = FrameBuffer()

    recv_thread = ReceiverThread(sock, max_buffer_bytes, store)
    recv_thread.start()

    use_turbo = False
    jpeg_decoder = None
    if args.turbojpeg and TurboJPEG is not None:
        try:
            jpeg_decoder = TurboJPEG()
            use_turbo = True
            log("info", "TurboJPEG enabled")
        except Exception as e:
            log("warn", f"TurboJPEG init failed: {e}")

    gui_mode = can_use_gui() and not args.no_gui
    window_created = False

    # TTY metrics
    tty_prev_ns: Optional[int] = None
    tty_first_ns: Optional[int] = None
    tty_total_ns: int = 0
    tty_frames: int = 0
    metrics_interval_ns = int(1e9 / max(1.0, float(args.metrics_rate)))
    tty_last_ns = time.monotonic_ns()

    # Display throttle
    last_show_ns: Optional[int] = None
    min_show_interval_ns = 0
    if args.max_display_fps and args.max_display_fps > 0:
        min_show_interval_ns = int(1e9 / float(args.max_display_fps))

    stop = False

    def _sigint(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    try:
        while not stop:
            buf = store.get_latest()
            if buf is None:
                time.sleep(0.0005)
                # still update TTY rate timer
                now_ns = time.monotonic_ns()
                if now_ns - tty_last_ns >= metrics_interval_ns:
                    # print placeholder when idle
                    print("\x1b[2F\x1b[2KRT: -- ms -- fps\n\x1b[2KAVG: -- ms -- fps\n", end="", flush=True)
                    tty_last_ns = now_ns
                continue

            # Decode
            t0 = time.monotonic_ns()
            if use_turbo and jpeg_decoder is not None:
                try:
                    frame = jpeg_decoder.decode(buf)  # BGR by default
                except Exception:
                    frame = decode_jpeg_cv2(buf)
            else:
                frame = decode_jpeg_cv2(buf)
            if frame is None:
                continue
            t1 = time.monotonic_ns()

            # GUI window lazy create
            if gui_mode and not window_created:
                try:
                    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
                    h, w = frame.shape[:2]
                    cv2.resizeWindow(WINDOW_NAME, min(1280, w), min(720, h))
                    cv2.moveWindow(WINDOW_NAME, 60, 60)
                    window_created = True
                except cv2.error:
                    gui_mode = False

            # Display throttling
            show_now = gui_mode and window_created
            if show_now and min_show_interval_ns:
                now_ns = time.monotonic_ns()
                if last_show_ns is not None and (now_ns - last_show_ns) < min_show_interval_ns:
                    show_now = False
                else:
                    last_show_ns = now_ns

            disp = frame
            if args.scale and args.scale > 0 and args.scale != 1.0:
                try:
                    disp = cv2.resize(
                        frame,
                        None,
                        fx=float(args.scale),
                        fy=float(args.scale),
                        interpolation=cv2.INTER_AREA,
                    )
                except cv2.error:
                    disp = frame

            # Terminal metrics update
            now_ns = time.monotonic_ns()
            if tty_prev_ns is None:
                tty_prev_ns = now_ns
                tty_first_ns = now_ns
            dt_ns = now_ns - tty_prev_ns
            tty_prev_ns = now_ns
            if dt_ns > 0:
                rt_ms = dt_ns / 1e6
                rt_fps = 1e9 / dt_ns
            else:
                rt_ms = 0.0
                rt_fps = 0.0
            tty_frames += 1
            if tty_first_ns is not None:
                tty_total_ns = now_ns - tty_first_ns
            avg_ms = (tty_total_ns / max(1, tty_frames)) / 1e6 if tty_total_ns > 0 else 0.0
            avg_fps = (tty_frames / (tty_total_ns / 1e9)) if tty_total_ns > 0 else 0.0

            if now_ns - tty_last_ns >= metrics_interval_ns:
                sys.stdout.write("\x1b[2F\x1b[2K")
                sys.stdout.write(f"RT: {rt_ms:.1f} ms {rt_fps:.1f} fps\n")
                sys.stdout.write("\x1b[2K")
                sys.stdout.write(f"AVG: {avg_ms:.1f} ms {avg_fps:.1f} fps\n")
                sys.stdout.flush()
                tty_last_ns = now_ns

            if show_now:
                try:
                    cv2.imshow(WINDOW_NAME, disp)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error:
                    gui_mode = False

    finally:
        recv_thread.stop()
        recv_thread.join(timeout=1.0)
        sock.close()
        if gui_mode:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass


if __name__ == "__main__":
    main()
