from __future__ import annotations

import select
import socket
from typing import Generator, Optional, Tuple

import cv2
import numpy as np


SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class UDPJPEGStream:
    """Minimal-latency UDP MJPEG frame source.

    - Listens on host:port
    - Collects UDP payloads into a rolling buffer
    - Extracts complete JPEGs by SOI/EOI markers
    - Yields only the latest complete frame to minimize latency
    """

    def __init__(
        self, host: str = "0.0.0.0", port: int = 8080, rcvbuf_mb: int = 16
    ) -> None:
        self.host = host
        self.port = port
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))
        self._sock: Optional[socket.socket] = None
        self._buffer = bytearray()
        self._max_buffer_bytes = 64 * 1024 * 1024

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024
            )
        except OSError:
            pass
        sock.bind((self.host, self.port))
        sock.setblocking(False)
        self._sock = sock

    def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def frames(self) -> Generator[np.ndarray, None, None]:
        if self._sock is None:
            self.start()
        assert self._sock is not None

        sock = self._sock
        buffer = self._buffer

        while True:
            # Pull all available UDP packets
            rlist, _, _ = select.select([sock], [], [], 0.0)
            while rlist:
                try:
                    data, _ = sock.recvfrom(65535)
                    buffer.extend(data)
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([sock], [], [], 0.0)

            # Extract newest full JPEG
            latest: Optional[bytes] = None
            while True:
                start = buffer.find(SOI)
                if start == -1:
                    if len(buffer) > self._max_buffer_bytes:
                        buffer.clear()
                    break
                end = buffer.find(EOI, start + 2)
                if end == -1:
                    if len(buffer) > self._max_buffer_bytes:
                        buffer[:] = buffer[-(2 * 1024 * 1024) :]
                    break
                latest = bytes(buffer[start : end + 2])
                del buffer[: end + 2]

            if latest is None:
                continue

            np_arr = np.frombuffer(latest, dtype=np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is None:
                continue
            yield img
