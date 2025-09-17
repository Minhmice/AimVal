#!/usr/bin/env python3
"""
UDP MJPEG viewer for Raspberry Pi 5.

This script listens on udp://0.0.0.0:8080, reconstructs JPEG frames from
UDP-delivered MJPEG (by locating JPEG SOI/EOI markers), decodes frames with
OpenCV, and focuses on low-latency display (no image-saving fallback in headless).

Usage:
    python udp_viewer.py [--record out.mp4] [--fps 30] [--fourcc mp4v] [--no-gui]

Notes:
    - If running over SSH without X11, consider using `ffplay udp://@:8080`.
    - For headless environments, you can install `opencv-python-headless`.
"""
from __future__ import annotations

import os
import socket
import signal
from typing import Optional
import argparse
import select
import time
import sys

import cv2
import numpy as np


# Network and decoding configuration
HOST: str = "0.0.0.0"
PORT: int = 8080
SOI: bytes = b"\xff\xd8"  # JPEG Start Of Image
EOI: bytes = b"\xff\xd9"  # JPEG End Of Image
WINDOW_NAME: str = "UDP Stream"

# Simple log levels
_LOG_LEVELS = {"error": 40, "warn": 30, "info": 20, "debug": 10}
_current_log_level = _LOG_LEVELS["info"]


def log(level: str, msg: str) -> None:
    lvl = _LOG_LEVELS.get(level, 20)
    if lvl >= _current_log_level:
        print(f"[{level.upper()}] {msg}")


def can_use_gui() -> bool:
    """Return True if a display is likely available for cv2.imshow.

    Heuristic: on Linux, require DISPLAY or WAYLAND_DISPLAY. On Windows, assume
    True. This avoids cv2 errors in headless shells.
    """
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def decode_jpeg(byte_data: bytes) -> Optional[np.ndarray]:
    """Decode JPEG bytes into a BGR image using OpenCV.

    Returns None if decoding fails.
    """
    if not byte_data:
        return None
    np_arr = np.frombuffer(byte_data, dtype=np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return img


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UDP MJPEG viewer/recorder for Raspberry Pi 5"
    )
    parser.add_argument(
        "--record",
        type=str,
        default=None,
        help="Path to output video file (e.g., out.mp4 or out.avi)",
    )
    parser.add_argument(
        "--fps", type=float, default=30.0, help="Target FPS for recording"
    )
    parser.add_argument(
        "--fourcc",
        type=str,
        default=None,
        help="FOURCC codec (default: auto by extension; mp4v for .mp4, XVID for .avi, MJPG otherwise)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Force headless mode even if a display is available",
    )
    parser.add_argument(
        "--no-metrics",
        action="store_true",
        help="Disable on-screen timing metrics overlay",
    )
    parser.add_argument(
        "--rcvbuf-mb",
        type=int,
        default=16,
        help="UDP socket receive buffer size in MB (default: 16)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=list(_LOG_LEVELS.keys()),
        help="Logging level (error, warn, info, debug)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Display scale factor (e.g., 0.5 to halve size; writer uses original)",
    )
    parser.add_argument(
        "--cv-threads",
        type=int,
        default=0,
        help="Set OpenCV thread count (>0 to override)",
    )
    parser.add_argument(
        "--max-display-fps",
        type=float,
        default=0.0,
        help="Cap display refresh FPS (0 = unlimited)",
    )
    parser.add_argument(
        "--no-tty-metrics",
        action="store_true",
        help="Disable terminal metrics (real-time and averages)",
    )
    return parser.parse_args()


def pick_fourcc(path: str, override: Optional[str]) -> int:
    if override:
        code = override
    else:
        lower = path.lower()
        if lower.endswith(".mp4"):
            code = "mp4v"  # widely available; H.264 not guaranteed on all builds
        elif lower.endswith(".avi"):
            code = "XVID"
        else:
            code = "MJPG"
    return cv2.VideoWriter_fourcc(*code)


def main() -> None:
    global _current_log_level
    args = parse_args()
    _current_log_level = _LOG_LEVELS.get(args.log_level, 20)

    if args.cv_threads and args.cv_threads > 0:
        try:
            cv2.setNumThreads(int(args.cv_threads))
            cv2.setUseOptimized(True)
            log("info", f"OpenCV threads set to {args.cv_threads}")
        except Exception as e:
            log("warn", f"Failed to set OpenCV threads: {e}")

    # Initial log line required by spec
    log("info", f"Listening on udp://{HOST}:{PORT}")

    # Prepare UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Bump receive buffer to better handle bursty UDP
    rcvbuf_bytes = max(1, args.rcvbuf_mb) * 1024 * 1024
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_bytes)
    except OSError:
        pass
    sock.bind((HOST, PORT))
    sock.setblocking(False)  # non-blocking for low latency
    log("info", f"Socket configured: non-blocking, rcvbuf~{rcvbuf_bytes//(1024*1024)}MB")

    # Choose output mode based on environment
    gui_mode = can_use_gui() and not args.no_gui
    window_created = False  # lazy-create window on first decoded frame

    # Graceful shutdown support
    stop = False

    def _sigint(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    # Rolling buffer accumulates UDP payloads until complete JPEG is found
    buffer = bytearray()
    max_buffer_bytes = 64 * 1024 * 1024  # safety cap to avoid unbounded growth
    log("info", f"Max buffer size set to {max_buffer_bytes//(1024*1024)}MB")

    writer: Optional[cv2.VideoWriter] = None
    out_path = args.record
    target_fps = max(1.0, float(args.fps))

    # Overlay metrics are disabled on frame (moved to terminal output)
    show_overlay = False

    # Terminal metrics
    enable_tty_metrics = not args.no_tty_metrics
    tty_init = False
    prev_display_ns: Optional[int] = None
    first_display_ns: Optional[int] = None
    total_display_ns: int = 0
    display_frames: int = 0

    def tty_update(rt_ms: float, rt_fps: float, avg_ms: float, avg_fps: float) -> None:
        nonlocal tty_init
        try:
            if not tty_init:
                # Allocate two lines
                sys.stdout.write("\n\n")
                tty_init = True
            # Move cursor up 2 lines to update in place
            sys.stdout.write("\x1b[2F")  # cursor up 2 lines
            sys.stdout.write("\x1b[2K")  # clear line
            sys.stdout.write(f"RT: {rt_ms:.1f} ms {rt_fps:.1f} fps\n")
            sys.stdout.write("\x1b[2K")
            sys.stdout.write(f"AVG: {avg_ms:.1f} ms {avg_fps:.1f} fps\n")
            sys.stdout.flush()
        except Exception:
            # Fallback: print without ANSI control
            print(f"RT: {rt_ms:.1f} ms {rt_fps:.1f} fps")
            print(f"AVG: {avg_ms:.1f} ms {avg_fps:.1f} fps")

    last_show_ns: Optional[int] = None
    min_show_interval_ns = 0
    if args.max_display_fps and args.max_display_fps > 0:
        min_show_interval_ns = int(1e9 / float(args.max_display_fps))
        log("info", f"Cap display to {args.max_display_fps} FPS")

    try:
        while not stop:
            # 1) Receive all available UDP data without blocking
            rlist, _, _ = select.select([sock], [], [], 0.0)
            packets = 0
            bytes_in = 0
            while rlist:
                try:
                    data, _addr = sock.recvfrom(65535)
                    buffer.extend(data)
                    packets += 1
                    bytes_in += len(data)
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([sock], [], [], 0.0)
            if packets and _current_log_level <= _LOG_LEVELS["debug"]:
                log("debug", f"recv packets={packets}, bytes={bytes_in}, buffer_len={len(buffer)}")

            # 2) Extract frames; keep only most recent to minimize latency
            latest_frame_bytes: Optional[bytes] = None
            frames_found = 0
            while True:
                start = buffer.find(SOI)
                if start == -1:
                    # No start marker present; periodically prune oversized buffer
                    if len(buffer) > max_buffer_bytes:
                        log("warn", "Buffer oversized without SOI, clearing")
                        buffer.clear()
                    break

                end = buffer.find(EOI, start + 2)
                if end == -1:
                    # Incomplete frame so far; optionally prune old data
                    if len(buffer) > max_buffer_bytes:
                        # keep last 2MB hoping it contains SOI of next frame
                        log("warn", "Buffer oversized with incomplete frame, trimming tail to 2MB")
                        buffer[:] = buffer[-(2 * 1024 * 1024) :]
                    break

                # Extract complete JPEG; prefer the latest
                latest_frame_bytes = bytes(buffer[start : end + 2])
                frames_found += 1
                # Discard consumed bytes up to end marker
                del buffer[: end + 2]

            if frames_found > 1 and _current_log_level <= _LOG_LEVELS["debug"]:
                log("debug", f"dropped {frames_found-1} older frames; decoding latest only")

            if latest_frame_bytes is None:
                # No complete frame yet; continue receiving
                continue

            # 3) Decode only the latest frame to minimize latency
            decode_start_ns = time.monotonic_ns()
            frame = decode_jpeg(latest_frame_bytes)
            if frame is None:
                log("warn", "Failed to decode JPEG frame")
                continue
            decode_ms = (time.monotonic_ns() - decode_start_ns) / 1e6

            # Create window lazily
            if gui_mode and not window_created:
                try:
                    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
                    # Ensure window is not fullscreen to avoid cursor issues
                    try:
                        cv2.setWindowProperty(
                            WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL
                        )
                    except cv2.error:
                        pass
                    # Resize and place the window to avoid cursor capture feel
                    h, w = frame.shape[:2]
                    cv2.resizeWindow(WINDOW_NAME, min(1280, w), min(720, h))
                    cv2.moveWindow(WINDOW_NAME, 60, 60)
                    log("info", "Window created on first frame")
                    window_created = True
                except cv2.error:
                    log("warn", "Failed to create window; running headless")
                    gui_mode = False

            # Initialize video writer lazily when first frame arrives
            if out_path and writer is None:
                h, w = frame.shape[:2]
                fourcc = pick_fourcc(out_path, args.fourcc)
                writer = cv2.VideoWriter(out_path, fourcc, target_fps, (w, h))
                if not writer.isOpened():
                    log("warn", f"Failed to open writer for {out_path}. Recording disabled.")
                    writer = None
                else:
                    log("info", f"Recording to {out_path} at {target_fps} FPS")

            # Prepare display frame (optionally scaled). Overlay disabled.
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

            if writer is not None:
                writer.write(frame)

            # Respect max display FPS if set
            should_show = gui_mode and window_created
            if should_show and min_show_interval_ns:
                now_ns = time.monotonic_ns()
                if last_show_ns is not None and (now_ns - last_show_ns) < min_show_interval_ns:
                    should_show = False
                else:
                    last_show_ns = now_ns

            # Terminal metrics
            if enable_tty_metrics:
                now = time.monotonic_ns()
                rt_ms = 0.0
                rt_fps = 0.0
                if prev_display_ns is not None:
                    dt_ns = now - prev_display_ns
                    if dt_ns > 0:
                        rt_ms = dt_ns / 1e6
                        rt_fps = 1e9 / dt_ns
                prev_display_ns = now
                if first_display_ns is None:
                    first_display_ns = now
                else:
                    total_display_ns = now - first_display_ns
                display_frames += 1
                avg_ms = 0.0
                avg_fps = 0.0
                if total_display_ns > 0:
                    avg_ms = (total_display_ns / display_frames) / 1e6
                    avg_fps = display_frames / (total_display_ns / 1e9)
                tty_update(rt_ms, rt_fps, avg_ms, avg_fps)

            if should_show:
                try:
                    cv2.imshow(WINDOW_NAME, disp)
                    # process GUI events; exit with 'q'
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        stop = True
                        break
                except cv2.error:
                    # If GUI fails mid-run (e.g., lost X11), fallback to headless
                    log("warn", "cv2.imshow failed; switching to headless mode")
                    gui_mode = False

    finally:
        sock.close()
        if writer is not None:
            writer.release()
            log("info", "Video writer released")
        if gui_mode:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
