#!/usr/bin/env bash

set -Eeuo pipefail

#
# Raspberry Pi 5 setup script
# - Updates system packages
# - Installs Python and ffmpeg
# - Creates a virtual environment and installs dependencies
# - Generates udp_viewer.py if missing
# - Runs the viewer
#

PROJECT_DIR="$(pwd)"
VENV_DIR="$PROJECT_DIR/venv"

echo "[1/5] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[2/5] Installing system dependencies..."
sudo apt-get install -y python3-full python3-venv python3-pip ffmpeg

echo "[3/5] Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip

echo "[4/5] Installing Python packages..."
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
  pip install -r "$PROJECT_DIR/requirements.txt"
else
  pip install numpy imutils opencv-python
fi

VIEWER_FILE="$PROJECT_DIR/udp_viewer.py"
if [ ! -f "$VIEWER_FILE" ]; then
  echo "[Info] Creating udp_viewer.py (auto-generated)..."
  cat > "$VIEWER_FILE" <<'PY'
#!/usr/bin/env python3
"""
UDP MJPEG viewer for Raspberry Pi 5.
- Listens on 0.0.0.0:8080
- Reassembles JPEG frames from UDP packets (FFD8 -> FFD9)
- Decodes with OpenCV. Shows GUI if display available; otherwise writes latest_frame.jpg.
"""
import os
import sys
import socket
import signal
import time
from typing import Optional

import cv2
import numpy as np


HOST = "0.0.0.0"
PORT = 8080
SOI = b"\xff\xd8"  # JPEG start of image
EOI = b"\xff\xd9"  # JPEG end of image
WINDOW_NAME = "UDP Stream"
LATEST_FRAME_PATH = "latest_frame.jpg"


def can_use_gui() -> bool:
    """Return True if a display is likely available for cv2.imshow."""
    if os.name == "nt":
        return True
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    return bool(display)


def decode_jpeg(byte_data: bytes) -> Optional[np.ndarray]:
    """Decode JPEG bytes into a BGR image using OpenCV."""
    if not byte_data:
        return None
    np_arr = np.frombuffer(byte_data, dtype=np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return img


def main() -> None:
    print(f"Listening on udp://{HOST}:{PORT}")

    # Prepare UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.bind((HOST, PORT))
    sock.settimeout(1.0)

    # Choose output mode
    gui_mode = can_use_gui()
    if gui_mode:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    # Graceful shutdown support
    stop = False
    def _sigint(_sig, _frm):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    buffer = bytearray()
    max_buffer_bytes = 64 * 1024 * 1024  # safety cap

    try:
        while not stop:
            try:
                data, _addr = sock.recvfrom(65535)
                buffer.extend(data)
            except socket.timeout:
                pass

            # Find complete JPEG frames inside buffer
            while True:
                start = buffer.find(SOI)
                if start == -1:
                    # No start marker; prune oversized buffer
                    if len(buffer) > max_buffer_bytes:
                        buffer.clear()
                    break
                end = buffer.find(EOI, start + 2)
                if end == -1:
                    # Incomplete frame, wait for more data
                    if len(buffer) > max_buffer_bytes:
                        # Keep tail to improve chance of next SOI
                        buffer[:] = buffer[-(2 * 1024 * 1024):]
                    break

                jpeg_bytes = bytes(buffer[start:end + 2])
                # Consume up to end marker
                del buffer[:end + 2]

                frame = decode_jpeg(jpeg_bytes)
                if frame is None:
                    continue

                if gui_mode:
                    try:
                        cv2.imshow(WINDOW_NAME, frame)
                        # 1ms process GUI events
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            stop = True
                            break
                    except cv2.error:
                        # Fallback to headless if GUI fails mid-run
                        gui_mode = False
                if not gui_mode:
                    # Write the latest frame to disk in headless mode
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
PY
  chmod +x "$VIEWER_FILE"
fi

echo "[5/5] Starting viewer (Ctrl+C to quit)..."
python "$VIEWER_FILE"

echo "Done. You can re-run with: source venv/bin/activate && python udp_viewer.py"


