#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDP MJPEG Receiver + OpenGL PBO Display (240Hz-capable)
- UDP non-blocking + select; ráp JPEG (SOI/EOI), drop-older (giữ JPEG mới nhất).
- Decode: TurboJPEG nếu có (rất nhanh), fallback OpenCV.
- Hiển thị bằng OpenGL (GLFW) với PBO double-buffer, tắt VSync, throttle theo MAX_DISPLAY_FPS.
- RX metrics: fps/ms bám sát khung nhận thật; kẹp trần hiển thị RX = MAX_METRIC_FPS (mặc định 240).
- Thêm 1 dòng log: %CPU / %RAM process, và GPU util + VRAM process (nếu có NVML).
- Thoát bằng đóng cửa sổ hoặc Ctrl+C.

Cài:
  pip install glfw PyOpenGL opencv-python turbojpeg psutil pynvml
Chạy:
  python udp_mjpeg_gl_pbo.py
"""

from __future__ import annotations

import os
import socket
import select
import time
import sys
import threading
from typing import Optional, Tuple

import numpy as np
import cv2

# TurboJPEG (optional)
try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None

# OpenGL + GLFW
import glfw  # type: ignore
from OpenGL import GL as gl  # type: ignore

# Process & GPU metrics
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

try:
    import pynvml  # type: ignore
except Exception:
    pynvml = None

# ============================
# CẤU HÌNH
# ============================
HOST: str = "0.0.0.0"
PORT: int = 8080

# Kernel recv buffer (MB)
RCVBUF_MB: int = 512

# User-space assembly buffer cap
MAX_ASSEMBLY_BYTES: int = 256 * 1024 * 1024  # 256MB

# Datagram temp buffer
RECV_TMP_BYTES: int = 262140

# TTY metrics rate (Hz)
TTY_METRICS_HZ: float = 120.0

# IDLE if no frame in (ms)
IDLE_AFTER_MS: int = 200

# Cap RX fps displayed
MAX_METRIC_FPS: float = 240.0

# Display
WINDOW_NAME: str = "UDP MJPEG (OpenGL PBO 240Hz)"
DISPLAY_SCALE: float = 1.0          # scale window vs frame size
MAX_DISPLAY_FPS: float = 240.0      # throttle display; VSync is disabled

# ============================
# JPEG markers
# ============================
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


# ============================
# Utils
# ============================
def human_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def open_socket(host: str, port: int, rcvbuf_mb: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        pass
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


# ============================
# Shared latest-bytes store
# ============================
class LatestBytesStore:
    """Lưu JPEG mới nhất + seq + timestamp (thread-safe)."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: Optional[bytes] = None
        self._seq: int = 0
        self._stamp_ns: int = 0

    def set(self, data: bytes, stamp_ns: int) -> None:
        with self._lock:
            self._buf = data
            self._seq += 1
            self._stamp_ns = stamp_ns

    def get(self) -> Tuple[Optional[bytes], int, int]:
        with self._lock:
            return self._buf, self._seq, self._stamp_ns


# ============================
# Receiver Thread
# ============================
class ReceiverThread(threading.Thread):
    def __init__(self, host: str, port: int, rcvbuf_mb: int,
                 max_assembly_bytes: int, store: LatestBytesStore) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = int(port)
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))
        self.max_assembly_bytes = max(2 * 1024 * 1024, int(max_assembly_bytes))
        self.store = store

        self.sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._buffer = bytearray()
        self._tmp = bytearray(RECV_TMP_BYTES)
        self._tmp_mv = memoryview(self._tmp)

        # Metrics
        self.packets_received = 0
        self.bytes_received = 0
        self.frames_total = 0
        self.first_frame_ns: Optional[int] = None
        self.prev_frame_ns: Optional[int] = None
        self.last_frame_ns: Optional[int] = None
        self.rt_ms: Optional[float] = None
        self.rt_fps: float = 0.0
        self.avg_ms: Optional[float] = None
        self.avg_fps: float = 0.0

    def stop(self) -> None:
        self._stop.set()

    def _open_socket(self) -> socket.socket:
        sock = open_socket(self.host, self.port, self.rcvbuf_mb)
        return sock

    def run(self) -> None:
        self.sock = self._open_socket()
        print(f"[INFO] Listening udp://{self.host}:{self.port}  (SO_RCVBUF≈{self.rcvbuf_mb}MB)")

        while not self._stop.is_set():
            # Poll quickly
            rlist, _, _ = select.select([self.sock], [], [], 0.001)
            while rlist and not self._stop.is_set():
                try:
                    nbytes, _ = self.sock.recvfrom_into(self._tmp_mv)
                    if nbytes <= 0:
                        break
                    self._buffer.extend(self._tmp_mv[:nbytes])
                    self.packets_received += 1
                    self.bytes_received += nbytes
                except BlockingIOError:
                    break
                except Exception as e:
                    print(f"[WARN] recv error: {e}")
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            # Extract all complete JPEGs; keep the latest
            latest: Optional[bytes] = None
            latest_time_ns: Optional[int] = None
            while True:
                start = self._buffer.find(SOI)
                if start == -1:
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer.clear()
                    break
                end = self._buffer.find(EOI, start + 2)
                if end == -1:
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024):]
                    break

                latest = bytes(self._buffer[start:end + 2])
                del self._buffer[:end + 2]
                now_ns = time.monotonic_ns()
                latest_time_ns = now_ns

                # RX metrics (per completed JPEG)
                if self.first_frame_ns is None:
                    self.first_frame_ns = now_ns
                if self.prev_frame_ns is not None:
                    dt_ns = now_ns - self.prev_frame_ns
                    if dt_ns > 0:
                        self.rt_ms = dt_ns / 1e6
                        raw = 1e9 / dt_ns
                        self.rt_fps = min(raw, MAX_METRIC_FPS)
                self.prev_frame_ns = now_ns
                self.last_frame_ns = now_ns
                self.frames_total += 1

                if self.first_frame_ns is not None and self.last_frame_ns is not None and self.frames_total > 1:
                    total_ns = self.last_frame_ns - self.first_frame_ns
                    if total_ns > 0:
                        self.avg_ms = (total_ns / self.frames_total) / 1e6
                        self.avg_fps = self.frames_total / (total_ns / 1e9)

            if latest is not None and latest_time_ns is not None:
                self.store.set(latest, latest_time_ns)

        # Cleanup
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


# ============================
# Decoder
# ============================
class Decoder:
    def __init__(self) -> None:
        self.use_turbo = False
        self.tj = None
        if TurboJPEG is not None:
            try:
                self.tj = TurboJPEG()
                self.use_turbo = True
                print("[INFO] TurboJPEG enabled")
            except Exception as e:
                print(f"[WARN] TurboJPEG init failed, fallback OpenCV: {e}")
                self.tj = None
                self.use_turbo = False

    def decode_bgr(self, jpeg_bytes: bytes) -> Optional[np.ndarray]:
        try:
            if self.use_turbo and self.tj is not None:
                return self.tj.decode(jpeg_bytes)  # BGR
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None


# ============================
# OpenGL PBO Renderer
# ============================
import ctypes

class GLRendererPBO:
    def __init__(self, title: str) -> None:
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
        glfw.window_hint(glfw.RESIZABLE, True)

        self.win = glfw.create_window(1280, 960, title, None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        glfw.make_context_current(self.win)
        glfw.swap_interval(0)  # disable VSync

        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

        # Texture
        self.tex_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        # PBO double buffer
        self.pbo_ids = gl.glGenBuffers(2)
        self.pbo_index = 0

        self.tex_w = 0
        self.tex_h = 0

        # Feature detect
        self.have_map_range = hasattr(gl, "glMapBufferRange")
        self.use_bgr = hasattr(gl, "GL_BGR")

    def _setup_ortho(self, w: int, h: int) -> None:
        gl.glViewport(0, 0, w, h)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, w, h, 0, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()

    def ensure_texture(self, w: int, h: int) -> None:
        if w == self.tex_w and h == self.tex_h:
            return
        self.tex_w, self.tex_h = w, h
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, None)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        # Resize window according to DISPLAY_SCALE
        win_w = max(1, int(w * DISPLAY_SCALE))
        win_h = max(1, int(h * DISPLAY_SCALE))
        glfw.set_window_size(self.win, win_w, win_h)
        self._setup_ortho(win_w, win_h)

        # Reallocate both PBOs to new size
        self._alloc_pbo(w, h)

    def _alloc_pbo(self, w: int, h: int) -> None:
        size = w * h * 3  # BGR
        for pbo in self.pbo_ids:
            gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, pbo)
            gl.glBufferData(gl.GL_PIXEL_UNPACK_BUFFER, size, None, gl.GL_STREAM_DRAW)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, 0)

    def upload_bgr_pbo(self, frame_bgr: np.ndarray) -> None:
        h, w, c = frame_bgr.shape
        assert c == 3
        self.ensure_texture(w, h)
        size = w * h * 3

        # Ping-pong PBOs
        index = self.pbo_index
        next_index = (index + 1) % 2

        # 1) Bind next PBO & orphan buffer, map and copy CPU->PBO
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, self.pbo_ids[next_index])
        gl.glBufferData(gl.GL_PIXEL_UNPACK_BUFFER, size, None, gl.GL_STREAM_DRAW)  # orphan

        ptr = None
        if self.have_map_range:
            # Write-only & invalidate for speed
            flags = gl.GL_MAP_WRITE_BIT | gl.GL_MAP_INVALIDATE_BUFFER_BIT
            ptr = gl.glMapBufferRange(gl.GL_PIXEL_UNPACK_BUFFER, 0, size, flags)
        else:
            ptr = gl.glMapBuffer(gl.GL_PIXEL_UNPACK_BUFFER, gl.GL_WRITE_ONLY)

        if ptr:
            # Ensure contiguous uint8
            src = np.ascontiguousarray(frame_bgr, dtype=np.uint8)
            ctypes.memmove(int(ptr), src.ctypes.data, size)
            gl.glUnmapBuffer(gl.GL_PIXEL_UNPACK_BUFFER)
        else:
            # As a (rare) fallback: use glBufferSubData (still copies once)
            src = np.ascontiguousarray(frame_bgr, dtype=np.uint8)
            gl.glBufferSubData(gl.GL_PIXEL_UNPACK_BUFFER, 0, src)

        # 2) Bind texture & use the "current" PBO (index) to perform GPU copy
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, self.pbo_ids[index])

        # Try GL_BGR to avoid CPU color conversion
        try:
            fmt = gl.GL_BGR if self.use_bgr else gl.GL_RGB
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, fmt, gl.GL_UNSIGNED_BYTE, ctypes.c_void_p(0))
        except Exception:
            # Fallback: convert to RGB on CPU
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, rgb)

        # Unbind
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        # Swap PBO indices
        self.pbo_index = next_index

    def draw(self) -> None:
        w, h = glfw.get_framebuffer_size(self.win)
        self._setup_ortho(w, h)
        gl.glClearColor(0.05, 0.05, 0.05, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0.0, 0.0); gl.glVertex2f(0, 0)
        gl.glTexCoord2f(1.0, 0.0); gl.glVertex2f(w, 0)
        gl.glTexCoord2f(1.0, 1.0); gl.glVertex2f(w, h)
        gl.glTexCoord2f(0.0, 1.0); gl.glVertex2f(0, h)
        gl.glEnd()
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        glfw.swap_buffers(self.win)

    def should_close(self) -> bool:
        return glfw.window_should_close(self.win)

    def poll(self) -> None:
        glfw.poll_events()

    def destroy(self) -> None:
        try:
            gl.glDeleteBuffers(len(self.pbo_ids), self.pbo_ids)
        except Exception:
            pass
        try:
            gl.glDeleteTextures([self.tex_id])
        except Exception:
            pass
        glfw.destroy_window(self.win)
        glfw.terminate()


# ============================
# Process & GPU metrics
# ============================
class ProcMonitor:
    def __init__(self) -> None:
        self.enabled = psutil is not None
        if self.enabled:
            self.proc = psutil.Process(os.getpid())
            try:
                self.proc.cpu_percent(None)  # prime
            except Exception:
                pass

    def sample(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if not self.enabled:
            return None, None, None
        try:
            cpu = self.proc.cpu_percent(None)  # %
            mem_pct = self.proc.memory_percent()  # %
            mem_mb = self.proc.memory_info().rss / (1024 * 1024)
            return cpu, mem_pct, mem_mb
        except Exception:
            return None, None, None


class NVMLMonitor:
    def __init__(self) -> None:
        self.enabled = False
        self.handles = []
        if pynvml is None:
            return
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                self.handles.append(pynvml.nvmlDeviceGetHandleByIndex(i))
            self.enabled = len(self.handles) > 0
            self.pid = os.getpid()
        except Exception:
            self.enabled = False

    def _proc_vram_mb_on_device(self, h) -> Optional[float]:
        # Try both Graphics & Compute running processes
        try:
            procs = pynvml.nvmlDeviceGetGraphicsRunningProcesses_v3(h)
        except Exception:
            try:
                procs = pynvml.nvmlDeviceGetGraphicsRunningProcesses(h)
            except Exception:
                procs = []
        try:
            procs += pynvml.nvmlDeviceGetComputeRunningProcesses_v3(h)
        except Exception:
            try:
                procs += pynvml.nvmlDeviceGetComputeRunningProcesses(h)
            except Exception:
                pass

        for p in procs:
            try:
                if int(p.pid) == self.pid:
                    return float(p.usedGpuMemory) / (1024 * 1024)
            except Exception:
                continue
        return None

    def sample(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (device_util%, proc_vram_mb_total_on_all_devices)."""
        if not self.enabled:
            return None, None
        util_sum = 0.0
        util_count = 0
        vram_total_mb = 0.0
        for h in self.handles:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                util_sum += float(util.gpu)
                util_count += 1
            except Exception:
                pass
            vram = self._proc_vram_mb_on_device(h)
            if vram:
                vram_total_mb += vram
        util_avg = (util_sum / util_count) if util_count > 0 else None
        return util_avg, (vram_total_mb if vram_total_mb > 0 else None)

    def shutdown(self) -> None:
        if self.enabled:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


# ============================
# Main
# ============================
def main() -> None:
    # Shared store & threads
    store = LatestBytesStore()
    rx = ReceiverThread(HOST, PORT, RCVBUF_MB, MAX_ASSEMBLY_BYTES, store)
    rx.start()

    decoder = Decoder()

    # OpenGL
    try:
        renderer = GLRendererPBO(WINDOW_NAME)
    except Exception as e:
        print(f"[ERROR] OpenGL init failed: {e}")
        print("Tip: pip install glfw PyOpenGL; hoặc chạy ở môi trường có GUI.")
        rx.stop(); rx.join(timeout=1.0)
        return

    # Throttle display
    show_interval_ns = int(1e9 / MAX_DISPLAY_FPS) if MAX_DISPLAY_FPS > 0 else 0
    last_show_ns = 0
    last_seq_shown = -1

    # Display metrics
    disp_first_ns: Optional[int] = None
    disp_prev_ns: Optional[int] = None
    disp_last_ns: Optional[int] = None
    disp_count: int = 0
    disp_rt_ms: Optional[float] = None
    disp_fps: float = 0.0
    disp_avg_ms: Optional[float] = None
    disp_avg_fps: float = 0.0
    last_resource_log_ns = 0


    # TTY cadence
    metrics_interval_ns = int(1e9 / max(1.0, TTY_METRICS_HZ))
    next_metrics_ns = time.monotonic_ns()

    # Proc & GPU monitors
    pm = ProcMonitor()
    gm = NVMLMonitor()

    try:
        while True:
            if renderer.should_close():
                break

            now_ns = time.monotonic_ns()
            can_show_time = (show_interval_ns == 0) or ((now_ns - last_show_ns) >= show_interval_ns)

            # Fetch latest JPEG
            jpeg, seq, stamp_ns = store.get()
            has_new_frame = (jpeg is not None) and (seq != last_seq_shown)

            # Decode + upload + draw (throttle + only newest)
            if can_show_time and has_new_frame and jpeg is not None:
                frame_bgr = decoder.decode_bgr(jpeg)
                if frame_bgr is not None and frame_bgr.size > 0:
                    renderer.upload_bgr_pbo(frame_bgr)
                    renderer.draw()
                    last_show_ns = now_ns
                    last_seq_shown = seq

                    # Display metrics
                    if disp_first_ns is None:
                        disp_first_ns = now_ns
                    if disp_prev_ns is not None:
                        ddt_ns = now_ns - disp_prev_ns
                        if ddt_ns > 0:
                            disp_rt_ms = ddt_ns / 1e6
                            disp_fps = 1e9 / ddt_ns
                    disp_prev_ns = now_ns
                    disp_last_ns = now_ns
                    disp_count += 1
                    if disp_first_ns is not None and disp_last_ns is not None and disp_count > 1:
                        dtotal_ns = disp_last_ns - disp_first_ns
                        if dtotal_ns > 0:
                            disp_avg_ms = (dtotal_ns / disp_count) / 1e6
                            disp_avg_fps = disp_count / (dtotal_ns / 1e9)

            # Poll GUI
            renderer.poll()

            # Print metrics
            if now_ns >= next_metrics_ns:
                next_metrics_ns = now_ns + metrics_interval_ns

                # RX state
                if rx.last_frame_ns is not None:
                    age_ms = (now_ns - rx.last_frame_ns) / 1e6
                    rx_active = age_ms <= IDLE_AFTER_MS
                else:
                    age_ms = None
                    rx_active = False

                # Display state
                if disp_last_ns is not None:
                    dage_ms = (now_ns - disp_last_ns) / 1e6
                    disp_active = dage_ms <= IDLE_AFTER_MS
                else:
                    dage_ms = None
                    disp_active = False

                # Process & GPU usage
                cpu_pct, mem_pct, mem_mb = pm.sample()
                gpu_util, vram_mb = gm.sample()

                sys.stdout.write("\x1b[4F\x1b[2K")
                sys.stdout.write(
                    f"PKT: {rx.packets_received:,}  BYTES: {human_bytes(rx.bytes_received)}  "
                    f"FRAMES(RX): {rx.frames_total:,}  SHOWN: {disp_count:,}\n"
                )
                sys.stdout.write("\x1b[2K")
                if rx_active and rx.rt_ms is not None and rx.avg_ms is not None:
                    sys.stdout.write(
                        f"RX  RT: {rx.rt_ms:.1f} ms  {rx.rt_fps:.1f} fps   "
                        f"AVG: {rx.avg_ms:.1f} ms  {min(rx.avg_fps, MAX_METRIC_FPS):.1f} fps   "
                        f"STATE: RX (last {age_ms:.0f} ms)\n"
                    )
                else:
                    age_txt = f"{age_ms:.0f} ms" if age_ms is not None else "N/A"
                    sys.stdout.write(
                        f"RX  RT: -- ms  0.0 fps   AVG: -- ms  0.0 fps   "
                        f"STATE: IDLE (no frames, last {age_txt})\n"
                    )
                sys.stdout.write("\x1b[2K")
                if disp_active and disp_rt_ms is not None and disp_avg_ms is not None:
                    lim_txt = f"{MAX_DISPLAY_FPS:.0f}" if MAX_DISPLAY_FPS > 0 else "∞"
                    sys.stdout.write(
                        f"DISP RT: {disp_rt_ms:.1f} ms  {disp_fps:.1f} fps   "
                        f"AVG: {disp_avg_ms:.1f} ms  {disp_avg_fps:.1f} fps   "
                        f"STATE: SHOWN (last {dage_ms:.0f} ms)  LIM: {lim_txt} fps\n"
                    )
                else:
                    dage_txt = f"{dage_ms:.0f} ms" if dage_ms is not None else "N/A"
                    lim_txt = f"{MAX_DISPLAY_FPS:.0f}" if MAX_DISPLAY_FPS > 0 else "∞"
                    sys.stdout.write(
                        f"DISP RT: -- ms  0.0 fps   AVG: -- ms  0.0 fps   "
                        f"STATE: IDLE (last {dage_txt})  LIM: {lim_txt} fps\n"
                    )
                # ---- One-line app resource usage (CPU/RAM/GPU) ----
                if now_ns - last_resource_log_ns >= 1_000_000_000:  # ~1s
                    last_resource_log_ns = now_ns
                    cpu_pct, mem_pct, mem_mb = pm.sample()
                    gpu_util, vram_mb = gm.sample()

                    sys.stdout.write("\x1b[2K")
                    cpu_txt = f"{cpu_pct:.1f}%" if cpu_pct is not None else "N/A"
                    ram_txt = f"{mem_mb:.0f} MB ({mem_pct:.1f}%)" if (mem_mb is not None and mem_pct is not None) else "N/A"
                    gpu_txt = f"{gpu_util:.0f}%" if gpu_util is not None else "N/A"
                    vram_txt = f"{vram_mb:.0f} MB" if vram_mb is not None else "N/A"
                    sys.stdout.write(f"APP: CPU {cpu_txt}  RAM {ram_txt}  GPU {gpu_txt}  VRAM(proc) {vram_txt}\n")
                # ---------------------------------------------------
                sys.stdout.flush()

            # Save CPU when idle
            if not has_new_frame and not can_show_time:
                time.sleep(0.0004)

    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user (Ctrl+C).")
    finally:
        try:
            renderer.destroy()
        except Exception:
            pass
        rx.stop()
        rx.join(timeout=1.0)
        gm.shutdown()
        

if __name__ == "__main__":
    main()
