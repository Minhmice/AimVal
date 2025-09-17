#!/usr/bin/env python3
"""
UDP MJPEG sender (PC2) — streams webcam or screen as MJPEG over UDP at high FPS.

Usage examples:
  # Webcam index 0 to Raspberry Pi at 240 FPS
  python udp_sender.py --dst-ip 192.168.1.50 --dst-port 8080 --source webcam:0 --fps 240 --quality 70

  # Screen capture (Linux/X11) at 60 FPS
  python udp_sender.py --dst-ip 192.168.1.50 --dst-port 8080 --source screen --fps 60 --quality 80

Notes:
- This sender builds raw JPEG frames via OpenCV and chunks them into UDP packets.
- For very high FPS, reduce resolution or quality.
- Use wired Ethernet for best stability.
"""
from __future__ import annotations

import argparse
import socket
import time
from typing import Optional, Tuple

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="High-FPS UDP MJPEG sender")
    p.add_argument("--dst-ip", type=str, required=True, help="Destination IP (Pi)")
    p.add_argument("--dst-port", type=int, default=8080, help="Destination UDP port")
    p.add_argument(
        "--source",
        type=str,
        default="webcam:0",
        help="Source: webcam:<index> | screen",
    )
    p.add_argument("--fps", type=float, default=60.0, help="Target capture FPS")
    p.add_argument("--width", type=int, default=1280, help="Capture width")
    p.add_argument("--height", type=int, default=720, help="Capture height")
    p.add_argument("--quality", type=int, default=75, help="JPEG quality (10-95)")
    p.add_argument(
        "--pkt-size", type=int, default=1300, help="UDP packet payload size (bytes)"
    )
    p.add_argument(
        "--rcvbuf-mb", type=int, default=8, help="Sender socket rcvbuf (MB)"
    )
    p.add_argument(
        "--sndbuf-mb", type=int, default=32, help="Sender socket sndbuf (MB)"
    )
    p.add_argument("--log-fps", action="store_true", help="Log effective FPS")
    return p.parse_args()


def open_source(spec: str, size: Tuple[int, int], fps: float) -> cv2.VideoCapture:
    if spec.startswith("webcam:"):
        idx = int(spec.split(":", 1)[1])
        cap = cv2.VideoCapture(idx)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        cap.set(cv2.CAP_PROP_FPS, fps)
        return cap
    elif spec == "screen":
        # Try to use desktop capture via X11 (Linux) with GStreamer if available
        # Fallback: try OpenCV's CAP_DSHOW/WIN32 or other backends if needed.
        cap = cv2.VideoCapture("ximagesrc use-damage=0 ! videoconvert ! appsink", cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            raise RuntimeError("Screen capture requires GStreamer and ximagesrc")
        return cap
    else:
        raise ValueError("Unknown source spec. Use webcam:<index> or screen")


def jpeg_encode(frame: np.ndarray, quality: int) -> Optional[bytes]:
    quality = max(10, min(95, int(quality)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return buf.tobytes()


def main() -> None:
    args = parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, args.sndbuf_mb * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, args.rcvbuf_mb * 1024 * 1024)
    except OSError:
        pass

    dst = (args.dst_ip, args.dst_port)

    cap = open_source(args.source, (args.width, args.height), args.fps)
    if not cap.isOpened():
        raise RuntimeError("Failed to open source")

    print(f"[INFO] Streaming to udp://{args.dst_ip}:{args.dst_port} @ {args.fps} FPS, {args.width}x{args.height}, q={args.quality}")

    frame_interval_ns = int(1e9 / max(1.0, float(args.fps)))
    last_send_ns: Optional[int] = None
    sent_frames = 0
    last_stat = time.monotonic()

    try:
        while True:
            now = time.monotonic_ns()
            if last_send_ns is not None and (now - last_send_ns) < frame_interval_ns:
                # Busy-wait lightly; in practice can sleep for a couple of ms
                time.sleep(0.0005)
                continue

            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # Ensure correct size
            if frame.shape[1] != args.width or frame.shape[0] != args.height:
                frame = cv2.resize(frame, (args.width, args.height), interpolation=cv2.INTER_AREA)

            jpg = jpeg_encode(frame, args.quality)
            if jpg is None:
                continue

            # Chunk JPEG into UDP packets
            pkt_size = max(600, min(1400, args.pkt_size))
            for i in range(0, len(jpg), pkt_size):
                chunk = jpg[i : i + pkt_size]
                sock.sendto(chunk, dst)

            last_send_ns = time.monotonic_ns()
            sent_frames += 1

            if args.log_fps and (time.monotonic() - last_stat) >= 1.0:
                print(f"[DBG] tx_fps={sent_frames}")
                sent_frames = 0
                last_stat = time.monotonic()

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        sock.close()
        print("[INFO] Sender stopped")


if __name__ == "__main__":
    main()
