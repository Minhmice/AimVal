#!/usr/bin/env python3
"""
UDP MJPEG viewer for Raspberry Pi 5.

This script listens on udp://0.0.0.0:8080, reconstructs JPEG frames from
UDP-delivered MJPEG (by locating JPEG SOI/EOI markers), decodes frames with
OpenCV, and either displays them in a GUI window (if a display is available)
or continuously saves the latest frame to 'latest_frame.jpg' when headless.

Usage:
    python udp_viewer.py

Notes:
    - If running over SSH without X11, consider using `ffplay udp://@:8080`.
    - For headless environments, you can install `opencv-python-headless`.
"""
from __future__ import annotations

import os
import socket
import signal
from typing import Optional

import cv2
import numpy as np


# Network and decoding configuration
HOST: str = "0.0.0.0"
PORT: int = 8080
SOI: bytes = b"\xff\xd8"  # JPEG Start Of Image
EOI: bytes = b"\xff\xd9"  # JPEG End Of Image
WINDOW_NAME: str = "UDP Stream"
LATEST_FRAME_PATH: str = "latest_frame.jpg"


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


def main() -> None:
    # Initial log line required by spec
    print(f"Listening on udp://{HOST}:{PORT}")

    # Prepare UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Bump receive buffer to better handle bursty UDP
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.bind((HOST, PORT))
    sock.settimeout(1.0)

    # Choose output mode based on environment
    gui_mode = can_use_gui()
    if gui_mode:
        # Allow resizing window for different resolutions
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

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

    try:
        while not stop:
            # 1) Receive available UDP data
            try:
                data, _addr = sock.recvfrom(65535)
                buffer.extend(data)
            except socket.timeout:
                pass  # proceed to attempt parsing existing buffer

            # 2) Extract as many complete JPEG frames as currently available
            while True:
                start = buffer.find(SOI)
                if start == -1:
                    # No start marker present; periodically prune oversized buffer
                    if len(buffer) > max_buffer_bytes:
                        buffer.clear()
                    break

                end = buffer.find(EOI, start + 2)
                if end == -1:
                    # Incomplete frame so far; optionally prune old data
                    if len(buffer) > max_buffer_bytes:
                        # keep last 2MB hoping it contains SOI of next frame
                        buffer[:] = buffer[-(2 * 1024 * 1024):]
                    break

                # Extract one complete JPEG [SOI ... EOI]
                jpeg_bytes = bytes(buffer[start : end + 2])
                # Discard consumed bytes up to end marker
                del buffer[: end + 2]

                # 3) Decode and output
                frame = decode_jpeg(jpeg_bytes)
                if frame is None:
                    continue

                if gui_mode:
                    try:
                        cv2.imshow(WINDOW_NAME, frame)
                        # process GUI events; exit with 'q'
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            stop = True
                            break
                    except cv2.error:
                        # If GUI fails mid-run (e.g., lost X11), fallback to headless
                        gui_mode = False

                if not gui_mode:
                    # Continuously write the latest frame to disk in headless mode
                    cv2.imwrite(LATEST_FRAME_PATH, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])

    finally:
        sock.close()
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


