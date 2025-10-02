import customtkinter as ctk
import threading
import queue
import time
import math
import numpy as np
import cv2
import tkinter as tk
from tkinter import filedialog
import os
import json
import subprocess
import sys
import socket
import select

from config import config
from mouse import Mouse
from detection_color import load_model, perform_detection
from detection_ai import (
    ai_detect_step as detect_step,
    DetectState,
    reinit_session as detect_reinit_session,
)
import esp
from aim import AimLogic, compute_target_point, plan_mouse_delta, ScreenScale
from esp import (
    draw_fov as esp_draw_fov,
    draw_boxes as esp_draw_boxes,
    draw_target as esp_draw_target,
    draw_head_dot as esp_draw_head,
    draw_ai_overlays,
    draw_color_overlays,
)
from trigger import TriggerLogic, trigger_update, TriggerState
from anti_recoil import anti_recoil_tick, AntiRecoilState

# ============================
# Integrated Ultrafast UDP Receiver (no external viewer)
# ============================
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
RECV_TMP_BYTES = 262140


class _LatestBytesStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._buf = None
        self._seq = 0
        # metrics
        self.packets_received = 0
        self.bytes_received = 0
        self.frames_total = 0
        self.first_frame_ns = None
        self.prev_frame_ns = None
        self.last_frame_ns = None
        self.rt_ms = None
        self.rt_fps = 0.0
        self.avg_ms = None
        self.avg_fps = 0.0

    def set_latest(self, data: bytes, now_ns: int):
        with self._lock:
            self._buf = data
            self._seq += 1
            if self.first_frame_ns is None:
                self.first_frame_ns = now_ns
            if self.prev_frame_ns is not None:
                dt_ns = now_ns - self.prev_frame_ns
                if dt_ns > 0:
                    self.rt_ms = dt_ns / 1e6
                    self.rt_fps = 1e9 / dt_ns
            self.prev_frame_ns = now_ns
            self.last_frame_ns = now_ns
            self.frames_total += 1
            if self.first_frame_ns is not None and self.frames_total > 0:
                total_ns = now_ns - self.first_frame_ns
                if total_ns > 0:
                    self.avg_ms = (total_ns / self.frames_total) / 1e6
                    self.avg_fps = self.frames_total / (total_ns / 1e9)

    def account_packet(self, nbytes: int):
        with self._lock:
            self.packets_received += 1
            self.bytes_received += nbytes

    def get_latest(self):
        with self._lock:
            return self._buf, self._seq, self.avg_ms, self.avg_fps


class _Receiver(threading.Thread):
    def __init__(
        self,
        host: str,
        port: int,
        rcvbuf_mb: int,
        max_assembly_bytes: int,
        store: _LatestBytesStore,
    ):
        super().__init__(daemon=True)
        self.host = host
        self.port = int(port)
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))
        self.max_assembly_bytes = max(2 * 1024 * 1024, int(max_assembly_bytes))
        self.store = store
        self._stop = threading.Event()
        self._buffer = bytearray()
        self._tmp = bytearray(RECV_TMP_BYTES)
        self._tmp_mv = memoryview(self._tmp)
        self.sock = None

    def stop(self):
        self._stop.set()

    def _open_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024
            )
        except OSError:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        sock.bind((self.host, self.port))
        sock.setblocking(False)
        return sock

    def run(self):
        self.sock = self._open_socket()
        while not self._stop.is_set():
            rlist, _, _ = select.select([self.sock], [], [], 0.001)
            while rlist and not self._stop.is_set():
                try:
                    nbytes, _ = self.sock.recvfrom_into(self._tmp_mv)
                    if nbytes <= 0:
                        break
                    self._buffer.extend(self._tmp_mv[:nbytes])
                    self.store.account_packet(nbytes)
                except BlockingIOError:
                    break
                except Exception:
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            latest = None
            latest_time_ns = None
            while True:
                start = self._buffer.find(SOI)
                if start == -1:
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer.clear()
                    break
                end = self._buffer.find(EOI, start + 2)
                if end == -1:
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024) :]
                    break
                latest = bytes(self._buffer[start : end + 2])
                del self._buffer[: end + 2]
                latest_time_ns = time.monotonic_ns()

            if latest is not None and latest_time_ns is not None:
                self.store.set_latest(latest, latest_time_ns)

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


class _Decoder:
    def __init__(self):
        self.use_turbo = False
        self.tj = None
        try:
            from turbojpeg import TurboJPEG  # type: ignore

            try:
                self.tj = TurboJPEG()
                self.use_turbo = True
            except Exception:
                self.tj = None
                self.use_turbo = False
        except Exception:
            self.tj = None
            self.use_turbo = False

    def decode_bgr(self, jpeg_bytes):
        try:
            if self.use_turbo and self.tj is not None:
                return self.tj.decode(jpeg_bytes)
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None


# ============================
# GL PBO Renderer (VISION + MASK)
# ============================
try:
    import glfw  # type: ignore
    from OpenGL import GL as gl  # type: ignore

    GL_AVAILABLE = True
except Exception:
    glfw = None
    gl = None
    GL_AVAILABLE = False

VISION_SCALE = 2.0
MASK_SCALE = 2.0
MAX_DISPLAY_FPS = 240.0


class SimpleFrameStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._seq = 0
        self._arr = None

    def set(self, arr):
        with self._lock:
            self._arr = arr
            self._seq += 1

    def get(self):
        with self._lock:
            return self._arr, self._seq


class GLRendererPBO:
    def __init__(self, title: str, scale: float):
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
        glfw.window_hint(glfw.RESIZABLE, True)

        self.win = glfw.create_window(640, 480, title, None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        glfw.make_context_current(self.win)
        glfw.swap_interval(0)  # disable VSync

        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

        self.tex_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        self.pbo_ids = gl.glGenBuffers(2)
        self.pbo_index = 0
        self.tex_w = 0
        self.tex_h = 0
        self.have_map_range = hasattr(gl, "glMapBufferRange")
        self.use_bgr = hasattr(gl, "GL_BGR")
        self.scale = float(scale) if scale and scale > 0 else 1.0

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
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGB,
            w,
            h,
            0,
            gl.GL_RGB,
            gl.GL_UNSIGNED_BYTE,
            None,
        )
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        win_w = max(1, int(w * self.scale))
        win_h = max(1, int(h * self.scale))
        glfw.set_window_size(self.win, win_w, win_h)
        self._setup_ortho(win_w, win_h)
        self._alloc_pbo(w, h)

    def _alloc_pbo(self, w: int, h: int) -> None:
        size = w * h * 3
        for pbo in self.pbo_ids:
            gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, pbo)
            gl.glBufferData(gl.GL_PIXEL_UNPACK_BUFFER, size, None, gl.GL_STREAM_DRAW)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, 0)

    def upload_bgr_pbo(self, frame_bgr: np.ndarray) -> None:
        # Ensure correct context
        glfw.make_context_current(self.win)
        h, w, c = frame_bgr.shape
        if c != 3:
            return
        self.ensure_texture(w, h)
        size = w * h * 3
        index = self.pbo_index
        next_index = (index + 1) % 2

        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, self.pbo_ids[next_index])
        gl.glBufferData(gl.GL_PIXEL_UNPACK_BUFFER, size, None, gl.GL_STREAM_DRAW)
        if self.have_map_range:
            flags = gl.GL_MAP_WRITE_BIT | gl.GL_MAP_INVALIDATE_BUFFER_BIT
            ptr = gl.glMapBufferRange(gl.GL_PIXEL_UNPACK_BUFFER, 0, size, flags)
        else:
            ptr = gl.glMapBuffer(gl.GL_PIXEL_UNPACK_BUFFER, gl.GL_WRITE_ONLY)
        # Convert to RGB to avoid GL_BGR ambiguity on some drivers
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if ptr:
            src = np.ascontiguousarray(rgb, dtype=np.uint8)
            import ctypes

            ctypes.memmove(int(ptr), src.ctypes.data, size)
            gl.glUnmapBuffer(gl.GL_PIXEL_UNPACK_BUFFER)
        else:
            src = np.ascontiguousarray(rgb, dtype=np.uint8)
            gl.glBufferSubData(gl.GL_PIXEL_UNPACK_BUFFER, 0, src)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, self.pbo_ids[index])
        try:
            fmt = gl.GL_RGB
            import ctypes

            gl.glTexSubImage2D(
                gl.GL_TEXTURE_2D,
                0,
                0,
                0,
                w,
                h,
                fmt,
                gl.GL_UNSIGNED_BYTE,
                ctypes.c_void_p(0),
            )
        except Exception:
            gl.glTexSubImage2D(
                gl.GL_TEXTURE_2D, 0, 0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, rgb
            )
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self.pbo_index = next_index

    def draw(self) -> None:
        glfw.make_context_current(self.win)
        w, h = glfw.get_framebuffer_size(self.win)
        self._setup_ortho(w, h)
        gl.glClearColor(0.05, 0.05, 0.05, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0.0, 0.0)
        gl.glVertex2f(0, 0)
        gl.glTexCoord2f(1.0, 0.0)
        gl.glVertex2f(w, 0)
        gl.glTexCoord2f(1.0, 1.0)
        gl.glVertex2f(w, h)
        gl.glTexCoord2f(0.0, 1.0)
        gl.glVertex2f(0, h)
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
        try:
            glfw.destroy_window(self.win)
        except Exception:
            pass


class DisplayThread(threading.Thread):
    def __init__(
        self,
        app,
        vision_store: SimpleFrameStore,
        mask_store: SimpleFrameStore,
        create_mask: bool = True,
    ):
        super().__init__(daemon=True)
        self.app = app
        self.vision_store = vision_store
        self.mask_store = mask_store
        self._stop = threading.Event()
        self.use_gl = False
        self.vision = None
        self.mask = None
        self.interval_ns = int(1e9 / MAX_DISPLAY_FPS) if MAX_DISPLAY_FPS > 0 else 0
        self.allow_mask = bool(create_mask)
        self._mask_window_destroyed = False
        self._create_mask = bool(create_mask)

    def stop(self):
        self._stop.set()

    def _try_init_gl(self):
        if not GL_AVAILABLE:
            return False
        try:
            self.vision = GLRendererPBO("VISION", VISION_SCALE)
            if self._create_mask:
                self.mask = GLRendererPBO("MASK", MASK_SCALE)
            else:
                self.mask = None
            return True
        except Exception:
            try:
                if self.vision:
                    self.vision.destroy()
            except Exception:
                pass
            try:
                if self.mask:
                    self.mask.destroy()
            except Exception:
                pass
            self.vision = None
            self.mask = None
            return False

    def set_allow_mask(self, allow: bool):
        self.allow_mask = bool(allow)
        if not self.allow_mask:
            self.hide_mask_window()
        else:
            self._mask_window_destroyed = False

    def hide_mask_window(self):
        try:
            if self.use_gl and self.mask is not None:
                self.mask.destroy()
                self.mask = None
                self._mask_window_destroyed = True
            else:
                try:
                    cv2.destroyWindow("MASK")
                except Exception:
                    pass
        except Exception:
            pass

    def run(self):
        self.use_gl = self._try_init_gl()
        self.app.use_gl = bool(self.use_gl)
        last_show_ns = 0
        last_vis_seq = -1
        last_msk_seq = -1
        try:
            while not self._stop.is_set():
                now_ns = time.monotonic_ns()
                if self.interval_ns and (now_ns - last_show_ns) < self.interval_ns:
                    time.sleep(0.0004)
                    continue
                last_show_ns = now_ns

                vis, vis_seq = self.vision_store.get()
                msk, msk_seq = self.mask_store.get()
                if self.use_gl and self.vision:
                    if vis is not None and vis_seq != last_vis_seq:
                        self.vision.upload_bgr_pbo(vis)
                        last_vis_seq = vis_seq
                    if self.allow_mask and (self.mask is not None) and (msk is not None) and msk_seq != last_msk_seq:
                        self.mask.upload_bgr_pbo(msk)
                        last_msk_seq = msk_seq
                    self.vision.draw()
                    if self.allow_mask and self.mask is not None:
                        self.mask.draw()
                    elif (
                        not self.allow_mask
                        and self.mask is not None
                        and not self._mask_window_destroyed
                    ):
                        # ensure hidden once
                        self.hide_mask_window()
                    glfw.poll_events()
                    if self.vision.should_close() or (
                        self.mask and self.mask.should_close()
                    ):
                        break
                else:
                    # Fallback cv2
                    if vis is not None and vis_seq != last_vis_seq:
                        last_vis_seq = vis_seq
                        try:
                            disp = vis
                            if VISION_SCALE != 1.0:
                                disp = cv2.resize(
                                    disp,
                                    None,
                                    fx=VISION_SCALE,
                                    fy=VISION_SCALE,
                                    interpolation=cv2.INTER_AREA,
                                )
                            cv2.imshow("VISION", disp)
                        except Exception:
                            pass
                    if self.allow_mask and (msk is not None) and msk_seq != last_msk_seq:
                        last_msk_seq = msk_seq
                        try:
                            disp = msk
                            if MASK_SCALE != 1.0:
                                disp = cv2.resize(
                                    disp,
                                    None,
                                    fx=MASK_SCALE,
                                    fy=MASK_SCALE,
                                    interpolation=cv2.INTER_AREA,
                                )
                            cv2.imshow("MASK", disp)
                        except Exception:
                            pass
                    if not self.allow_mask:
                        try:
                            cv2.destroyWindow("MASK")
                        except Exception:
                            pass
                    cv2.waitKey(1)
        finally:
            try:
                if self.vision:
                    self.vision.destroy()
            except Exception:
                pass
            try:
                if self.mask:
                    self.mask.destroy()
            except Exception:
                pass


BUTTONS = {
    0: "Left Mouse Button",
    1: "Right Mouse Button",
    2: "Middle Mouse Button",
    3: "Side Mouse 4 Button",
    4: "Side Mouse 5 Button",
}


def threaded_silent_move(controller, dx, dy):
    """Petit move-restore pour le mode Silent."""
    controller.move(dx, dy)
    time.sleep(0.001)
    controller.click()
    time.sleep(0.001)
    controller.move(-dx, -dy)


class AimTracker:
    def __init__(self, app, target_fps=80):
        self.app = app
        # --- Params (avec valeurs fallback) ---
        self.normal_x_speed = float(getattr(config, "normal_x_speed", 0.5))
        self.normal_y_speed = float(getattr(config, "normal_y_speed", 0.5))
        self.normalsmooth = float(getattr(config, "normalsmooth", 10))
        self.normalsmoothfov = float(getattr(config, "normalsmoothfov", 10))
        self.mouse_dpi = float(getattr(config, "mouse_dpi", 800))
        self.fovsize = float(getattr(config, "fovsize", 300))
        self.tbfovsize = float(getattr(config, "tbfovsize", 70))
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))

        self.in_game_sens = float(getattr(config, "in_game_sens", 7))
        self.color = getattr(config, "color", "yellow")
        self.mode = getattr(config, "mode", "Normal")
        self.selected_mouse_button = (getattr(config, "selected_mouse_button", 3),)
        self.selected_tb_btn = getattr(config, "selected_tb_btn", 3)
        self.max_speed = float(getattr(config, "max_speed", 1000.0))

        self.controller = Mouse()
        self.trigger = TriggerLogic()
        # Unified modules state
        self.trigger_state = TriggerState()
        self.ar_state = AntiRecoilState()
        self.last_detection_box_screen = None
        self._aim_pressed_since_ms = None
        self.move_queue = queue.Queue(maxsize=50)
        self._move_thread = threading.Thread(
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()

        self.model, self.class_names = load_model()
        self.detect_state = DetectState()
        print("Classes:", self.class_names)
        self._stop_event = threading.Event()
        self._target_fps = target_fps
        self._track_thread = threading.Thread(target=self._track_loop, daemon=True)
        self._track_thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            self._track_thread.join(timeout=1.0)
        except Exception:
            pass

    def _process_move_queue(self):
        while True:
            try:
                dx, dy, delay = self.move_queue.get(timeout=0.1)
                try:
                    # Use smooth movement if configured
                    if getattr(config, "aim", {}).get("movement", {}).get("use_smooth", True):
                        # segments and ctrl_scale can be tuned via config if desired
                        seg = int(getattr(config, "aim", {}).get("movement", {}).get("smooth_segments", 4))
                        ctrl = float(getattr(config, "aim", {}).get("movement", {}).get("smooth_ctrl_scale", 0.35))
                        try:
                            self.controller.move_smooth(dx, dy, segments=seg, ctrl_scale=ctrl)
                        except Exception:
                            self.controller.move(dx, dy)
                    else:
                        self.controller.move(dx, dy)
                except Exception as e:
                    print("[Mouse.move error]", e)
                if delay and delay > 0:
                    time.sleep(delay)
            except queue.Empty:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"[Move Queue Error] {e}")
                time.sleep(0.01)

    def _clip_movement(self, dx, dy):
        clipped_dx = np.clip(dx, -abs(self.max_speed), abs(self.max_speed))
        clipped_dy = np.clip(dy, -abs(self.max_speed), abs(self.max_speed))
        return float(clipped_dx), float(clipped_dy)

    def _track_loop(self):
        period = 1.0 / float(self._target_fps)
        while not self._stop_event.is_set():
            start = time.time()
            try:
                self.track_once()
            except Exception as e:
                print("[Track error]", e)
            elapsed = time.time() - start
            to_sleep = period - elapsed
            if to_sleep > 0:
                time.sleep(to_sleep)

    def _draw_fovs(self, img, frame):
        over = getattr(config, "debug", {}).get("overlay", {})
        if not over.get("draw_esp", True):
            return
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        if getattr(config, "enableaim", False):
            esp_draw_fov(img, (center_x, center_y), int(getattr(config, "fovsize", self.fovsize)), (255,255,255), 2, over)
            esp_draw_fov(img, (center_x, center_y), int(getattr(config, "normalsmoothfov", self.normalsmoothfov)), (51,255,255), 2, over)
        if getattr(config, "enabletb", False):
            esp_draw_fov(img, (center_x, center_y), int(getattr(config, "tbfovsize", self.tbfovsize)), (255,255,255), 2, over)

    def track_once(self):
        if not getattr(self.app, "connected", False):
            return

        # Fetch latest UDP MJPEG frame (already BGR)
        try:
            img = self.app.get_latest_frame()
            if img is None:
                return
            h, w = img.shape[:2]
            # Build a lightweight frame info object with xres/yres attributes
            frame = type("FrameInfo", (), {"xres": w, "yres": h})()
            bgr_img = img.copy()
        except Exception:
            return

        try:
            if getattr(config, "detection", {}).get("source", "color") == "ai":
                # Build ROI as full frame for now
                roi_bgra = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2BGRA)
                roi_rect = {"left": 0, "top": 0, "width": int(w), "height": int(h)}
                out = detect_step(
                    roi_bgra,
                    roi_rect,
                    getattr(config, "runtime", {}),
                    getattr(config, "detection", {}),
                    self.detect_state,
                    getattr(config, "debug", {}),
                )
                detection_results = []
                mask = out.get("mask_bgr")
                # When using AI source, do not show mask window; clear leftovers by not pushing mask
                try:
                    if getattr(config, "detection", {}).get("source", "color") == "ai":
                        self.app.display_thread.set_allow_mask(False)
                    else:
                        self.app.display_thread.set_allow_mask(True)
                except Exception:
                    pass
                # map unified detections back to legacy format for drawing pipelines
                for d in out.get("detections", []):
                    x = d["cx"] - d["w"] / 2.0
                    y = d["cy"] - d["h"] / 2.0
                    detection_results.append(
                        {
                            "bbox": (x, y, d["w"], d["h"]),
                            "confidence": d.get("conf", 0.0),
                        }
                    )
                self.last_detection_box_screen = out.get("last_detection_box_screen")
                # Draw AI overlays only if there are detections
                try:
                    over = getattr(config, "debug", {}).get("overlay", {})
                    if over.get("draw_esp", True) and out.get("detections"):
                        # Use unified format directly for ESP drawing
                        esp.draw_ai_overlays(bgr_img, out, over)
                except Exception:
                    pass
                # publish frames to display thread (no mask when AI)
                try:
                    self.app.vision_store.set(bgr_img)
                    mask_bgr = out.get("mask_bgr")
                    if mask_bgr is not None and getattr(config, "detection", {}).get("source", "color") != "ai":
                        self.app.mask_store.set(mask_bgr)
                except Exception:
                    pass
            else:
                detection_results, mask = perform_detection(self.model, bgr_img)
                # Draw COLOR overlays (boxes, no label) before publishing (only in color mode)
                try:
                    over = getattr(config, "debug", {}).get("overlay", {})
                    if over.get("draw_esp", True) and detection_results:
                        esp.draw_color_overlays(bgr_img, detection_results, over)
                except Exception:
                    pass
                # publish frames to display thread
                try:
                    self.app.vision_store.set(bgr_img)
                    # ensure mask is 3-channel BGR for GL
                    if mask is not None and len(mask.shape) == 2:
                        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
                    else:
                        mask_bgr = mask
                    self.app.mask_store.set(mask_bgr)
                except Exception:
                    pass
        except Exception as e:
            print("[perform_detection error]", e)
            detection_results = []

        targets = []
        targets_info = []
        if detection_results:
            for det in detection_results:
                try:
                    x, y, w, h = det["bbox"]
                    conf = det.get("confidence", 1.0)
                    x1, y1 = int(x), int(y)
                    x2, y2 = int(x + w), int(y + h)
                    y1 *= 1.03
                    # Dessin corps
                    # draw body box via ESP (consistent coloring handled by draw_color_overlays)
                    pass
                    # Estimation têtes dans la bbox
                    from detection_color import detect_heads_in_roi
                    head_positions = detect_heads_in_roi(
                        bgr_img, x1, y1, x2, y2, getattr(config, "offsetX", 0), getattr(config, "offsetY", 0)
                    )
                    for head_cx, head_cy, bbox in head_positions:
                        over = getattr(config, "debug", {}).get("overlay", {})
                        if over.get("draw_esp", True):
                            esp_draw_head(bgr_img, (head_cx, head_cy), (0,0,255), 2, over)
                        d = math.hypot(
                            head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0
                        )
                        targets.append((head_cx, head_cy, d))
                        try:
                            bx, by, bw, bh = bbox
                            targets_info.append(
                                {
                                    "cx": head_cx,
                                    "cy": head_cy,
                                    "d": d,
                                    "bbox": (int(bx), int(by), int(bw), int(bh)),
                                    "conf": float(conf),
                                }
                            )
                        except Exception:
                            pass
                except Exception as e:
                    print("Erreur dans _estimate_head_positions:", e)

        # FOVs une fois par frame
        try:
            self._draw_fovs(bgr_img, frame)
        except Exception:
            pass

        try:
            self._aim_and_move(targets, frame, bgr_img, targets_info)
        except Exception as e:
            print("[Aim error]", e)

        # GL/cv2 display handled by DisplayThread; nothing more to do here

    # drawing moved to esp.py

    # removed: _estimate_head_positions moved to detection_color.detect_heads_in_roi

    # body box drawing handled via esp.py in track_once

    def _aim_and_move(self, targets, frame, img, targets_info):
        mode = getattr(config, "mode", "Normal")
        if mode == "Normal":
            try:
                # Aimbot
                if getattr(config, "enableaim", False) and AimLogic.is_active():
                    if getattr(config, "use_new_aim", False) and targets_info:
                        # New unified Aim path
                        # pick nearest to center
                        best = (
                            min(targets_info, key=lambda t: t["d"])
                            if targets_info
                            else None
                        )
                        if best is not None:
                            bx, by, bw, bh = best.get("bbox", (0, 0, 0, 0))
                            det = {
                                "cx": float(best["cx"]),
                                "cy": float(best["cy"]),
                                "w": float(bw),
                                "h": float(bh),
                                "conf": float(best.get("conf", 1.0)),
                                "class_id": 0,
                                "class_name": "color",
                            }
                            roi_rect_screen = {
                                "left": 0,
                                "top": 0,
                                "width": int(frame.xres),
                                "height": int(frame.yres),
                            }
                            screen_scale = ScreenScale(1.0, 1.0)
                            tx, ty = compute_target_point(
                                det,
                                roi_rect_screen,
                                getattr(config, "aim", {}),
                                screen_scale,
                            )
                            # Approximate cursor at screen center (no OS cursor API here)
                            cursor_xy = (int(frame.xres // 2), int(frame.yres // 2))
                            dx, dy = plan_mouse_delta(
                                cursor_xy,
                                (tx, ty),
                                getattr(config, "aim", {}).get("movement", {}),
                                aspect_ratio_correction=True,
                                lock_on_screen=True,
                                screen_size=(int(frame.xres), int(frame.yres)),
                            )
                            if dx or dy:
                                self.move_queue.put((dx, dy, 0.005))
                            # update last selected box in screen coords
                            self.last_detection_box_screen = {
                                "x": int(bx),
                                "y": int(by),
                                "w": int(bw),
                                "h": int(bh),
                            }
                    else:
                        # Legacy aim path
                        move = AimLogic.plan_move(
                            targets, int(frame.xres), int(frame.yres)
                        )
                        if move is not None:
                            ddx, ddy = move
                            self.move_queue.put((ddx, ddy, 0.005))
            except Exception as e:
                print("[Aim error]", e)

            try:
                # Triggerbot
                if getattr(config, "use_new_trigger", False):
                    # Build adapter
                    class _SendAdapter:
                        def __init__(self, controller):
                            self.c = controller

                        def mouse_down(self):
                            try:
                                self.c.press()
                            except Exception:
                                pass

                        def mouse_up(self):
                            try:
                                self.c.release()
                            except Exception:
                                pass

                        def sleep_ms(self, ms: int):
                            try:
                                time.sleep(max(0, int(ms)) / 1000.0)
                            except Exception:
                                pass

                        def mouse_click(self, down_up_delay_ms: int = 20):
                            try:
                                self.c.click_with_delay(down_up_delay_ms)
                            except Exception:
                                # fallback
                                self.c.press()
                                time.sleep(max(0, int(down_up_delay_ms)) / 1000.0)
                                self.c.release()

                    is_aim_pressed = AimLogic.is_active()
                    now_ms = int(time.time() * 1000)
                    cursor_xy = (int(frame.xres // 2), int(frame.yres // 2))
                    cfg_trigger = getattr(config, "trigger", {})
                    if not cfg_trigger.get("cursor_check", True):
                        pass
                    trigger_update(
                        is_aim_pressed,
                        self.last_detection_box_screen,
                        cursor_xy,
                        now_ms,
                        cfg_trigger,
                        self.trigger_state,
                        _SendAdapter(self.controller),
                    )
                else:
                    self.trigger.run_once(self.model, img, self.controller)
            except Exception as e:
                print("[Triggerbot error]", e)

            try:
                # Anti-recoil (unified)
                if getattr(config, "use_new_anti_recoil", False):
                    now_ms = int(time.time() * 1000)
                    if AimLogic.is_active():
                        if self._aim_pressed_since_ms is None:
                            self._aim_pressed_since_ms = now_ms
                    else:
                        self._aim_pressed_since_ms = None
                    held_ms = (
                        0
                        if self._aim_pressed_since_ms is None
                        else max(0, now_ms - self._aim_pressed_since_ms)
                    )
                    anti_recoil_tick(
                        True,
                        bool(self.trigger_state.spraying),
                        now_ms,
                        held_ms,
                        getattr(config, "anti_recoil", {}),
                        self.ar_state,
                        self.controller,
                    )
            except Exception as e:
                print("[Anti-recoil error]", e)

        elif mode == "Silent":
            # Use a quick move-click-move-back approach towards closest target
            if targets:
                center_x = frame.xres / 2.0
                center_y = frame.yres / 2.0
                best_cx, best_cy, _ = min(targets, key=lambda t: t[2])
                dx = int(best_cx - center_x)
                dy = int(best_cy - center_y)
                dx *= self.normal_x_speed
                dy *= self.normal_y_speed
                threading.Thread(
                    target=threaded_silent_move,
                    args=(self.controller, dx, dy),
                    daemon=True,
                ).start()


class ViewerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CUPSY Colorbot")
        self.geometry("400x700")

        # Dicos pour MAJ UI <-> config
        self._slider_widgets = (
            {}
        )  # key -> {"slider": widget, "label": widget, "min":..., "max":...}
        self._checkbox_vars = {}  # key -> tk.BooleanVar
        self._option_widgets = {}  # key -> CTkOptionMenu

        # Integrated UDP receiver/decoder state
        self.receiver = None
        self.rx_store = _LatestBytesStore()
        self.decoder = _Decoder()
        self.last_decoded_seq = -1
        self.last_bgr = None
        self.connected = False
        # enlève la barre native

        # barre custom
        self.title_bar = ctk.CTkFrame(self, height=30, corner_radius=0)
        self.title_bar.pack(fill="x", side="top")

        self.title_label = ctk.CTkLabel(self.title_bar, text="CUPSY CB", anchor="w")
        self.title_label.pack(side="left", padx=10)

        # Removed explicit close button; standard window close is used

        # rendre la barre draggable
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.do_move)

        # Shared stores for display
        self.vision_store = SimpleFrameStore()
        self.mask_store = SimpleFrameStore()
        self.display_thread = None
        self.use_gl = False

        # Tracker
        self.tracker = AimTracker(app=self, target_fps=80)

        # TabView
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(expand=True, fill="both", padx=20, pady=20)
        self.tab_general = self.tabview.add("⚙️ General")
        self.tab_detect = self.tabview.add("🧠 Detect")
        self.tab_aimbot = self.tabview.add("🎯 Aimbot")
        self.tab_tb = self.tabview.add("🔫 Triggerbot")
        self.tab_ar = self.tabview.add("🧷 Anti-Recoil")
        self.tab_config = self.tabview.add("💾 Config")

        self._build_general_tab()
        self._build_detect_tab()
        self._build_aimbot_tab()
        self._build_tb_tab()
        self._build_ar_tab()
        self._build_config_tab()

        # Status polling
        self.after(500, self._update_connection_status_loop)
        self._load_initial_config()

    # ---------- Helpers de mapping UI ----------
    def _ui_log(self, msg: str):
        try:
            print(msg)
        except Exception:
            pass

    def _register_slider(self, key, slider, label, vmin, vmax, is_float):
        self._slider_widgets[key] = {
            "slider": slider,
            "label": label,
            "min": vmin,
            "max": vmax,
            "is_float": is_float,
        }

    def _load_initial_config(self):
        try:
            import json, os
            from detection_color import reload_model

            if os.path.exists("configs/default.json"):
                with open("configs/default.json", "r") as f:
                    data = json.load(f)

                self._apply_settings(data)

            else:
                print("doesn't exist")
        except Exception as e:
            print("Impossible de charger la config initiale:", e)

    def _set_slider_value(self, key, value):
        if key not in self._slider_widgets:
            return
        w = self._slider_widgets[key]
        vmin, vmax = w["min"], w["max"]
        is_float = w["is_float"]
        # Clamp
        try:
            v = float(value) if is_float else int(round(float(value)))
        except Exception:
            return
        v = max(vmin, min(v, vmax))
        w["slider"].set(v)
        # Rafraîchir label
        txt = (
            f"{key.replace('_', ' ').title()}: {v:.2f}"
            if is_float
            else f"{key.replace('_', ' ').title()}: {int(v)}"
        )
        # On garde le libellé humain (X Speed etc.) si déjà présent
        current = w["label"].cget("text")
        prefix = current.split(":")[0] if ":" in current else txt.split(":")[0]
        w["label"].configure(
            text=f"{prefix}: {v:.2f}" if is_float else f"{prefix}: {int(v)}"
        )

    def _set_checkbox_value(self, key, value_bool):
        var = self._checkbox_vars.get(key)
        if var is not None:
            var.set(bool(value_bool))

    def _set_option_value(self, key, value_str):
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))

    def _set_btn_option_value(self, key, value_str):
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))

    # -------------- Tab Config --------------
    def _build_config_tab(self):
        os.makedirs("configs", exist_ok=True)

        ctk.CTkLabel(self.tab_config, text="Choose a config:").pack(pady=5, anchor="w")

        self.config_option = ctk.CTkOptionMenu(
            self.tab_config, values=[], command=self._on_config_selected
        )
        self.config_option.pack(pady=5, fill="x")

        ctk.CTkButton(self.tab_config, text="💾 Save", command=self._save_config).pack(
            pady=10, fill="x"
        )
        ctk.CTkButton(
            self.tab_config, text="💾 New Config", command=self._save_new_config
        ).pack(pady=5, fill="x")
        ctk.CTkButton(
            self.tab_config, text="📂 Load config", command=self._load_selected_config
        ).pack(pady=5, fill="x")

        self.config_log = ctk.CTkTextbox(self.tab_config, height=120)
        self.config_log.pack(pady=10, fill="both", expand=True)

        self._refresh_config_list()

    def _build_ar_tab(self):
        ar = getattr(config, "anti_recoil", {})
        frame = ctk.CTkFrame(self.tab_ar)
        frame.pack(padx=12, pady=8, fill="x")
        self.var_ar_enabled = tk.BooleanVar(value=bool(ar.get("enabled", True)))
        ctk.CTkCheckBox(
            frame,
            text="Enabled",
            variable=self.var_ar_enabled,
            command=self._on_ar_changed,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(frame, text="Hold time ms").grid(row=1, column=0, sticky="w")
        self.entry_ar_hold = ctk.CTkEntry(frame, width=80)
        self.entry_ar_hold.insert(0, str(int(ar.get("hold_time_ms", 150))))
        self.entry_ar_hold.grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(frame, text="Fire rate ms").grid(row=1, column=2, sticky="w")
        self.entry_ar_rate = ctk.CTkEntry(frame, width=80)
        self.entry_ar_rate.insert(0, str(int(ar.get("fire_rate_ms", 95))))
        self.entry_ar_rate.grid(row=1, column=3, sticky="w")

        ctk.CTkLabel(frame, text="X Recoil").grid(row=2, column=0, sticky="w")
        self.entry_ar_x = ctk.CTkEntry(frame, width=80)
        self.entry_ar_x.insert(0, str(int(ar.get("x_recoil", 0))))
        self.entry_ar_x.grid(row=2, column=1, sticky="w")
        ctk.CTkLabel(frame, text="Y Recoil").grid(row=2, column=2, sticky="w")
        self.entry_ar_y = ctk.CTkEntry(frame, width=80)
        self.entry_ar_y.insert(0, str(int(ar.get("y_recoil", 2))))
        self.entry_ar_y.grid(row=2, column=3, sticky="w")

        ctk.CTkLabel(frame, text="Jitter X/Y").grid(row=3, column=0, sticky="w")
        self.entry_ar_jx = ctk.CTkEntry(frame, width=80)
        self.entry_ar_jx.insert(0, str(int(ar.get("random_jitter_px", {}).get("x", 0))))
        self.entry_ar_jx.grid(row=3, column=1, sticky="w")
        self.entry_ar_jy = ctk.CTkEntry(frame, width=80)
        self.entry_ar_jy.insert(0, str(int(ar.get("random_jitter_px", {}).get("y", 1))))
        self.entry_ar_jy.grid(row=3, column=2, sticky="w")

        ctk.CTkLabel(frame, text="Scale with ADS").grid(row=4, column=0, sticky="w")
        self.entry_ar_ads = ctk.CTkEntry(frame, width=80)
        self.entry_ar_ads.insert(0, str(float(ar.get("scale_with_ads", 1.0))))
        self.entry_ar_ads.grid(row=4, column=1, sticky="w")
        self.var_ar_only_trig = tk.BooleanVar(
            value=bool(ar.get("only_when_triggering", True))
        )
        ctk.CTkCheckBox(
            frame,
            text="Only when triggering",
            variable=self.var_ar_only_trig,
            command=self._on_ar_changed,
        ).grid(row=4, column=2, sticky="w")

        ctk.CTkButton(frame, text="Apply", command=self._on_ar_changed).grid(
            row=5, column=0, pady=6, sticky="w"
        )

    def _on_ar_changed(self):
        ar = getattr(config, "anti_recoil", {})
        ar["enabled"] = bool(self.var_ar_enabled.get())
        ar["only_when_triggering"] = bool(self.var_ar_only_trig.get())
        try:
            ar["hold_time_ms"] = int(self.entry_ar_hold.get())
        except Exception:
            pass
        try:
            ar["fire_rate_ms"] = int(self.entry_ar_rate.get())
        except Exception:
            pass
        try:
            ar["x_recoil"] = int(self.entry_ar_x.get())
            ar["y_recoil"] = int(self.entry_ar_y.get())
        except Exception:
            pass
        try:
            ar.setdefault("random_jitter_px", {})["x"] = int(self.entry_ar_jx.get())
            ar.setdefault("random_jitter_px", {})["y"] = int(self.entry_ar_jy.get())
        except Exception:
            pass
        try:
            ar["scale_with_ads"] = float(self.entry_ar_ads.get())
        except Exception:
            pass

    def start_move(self, event):
        self._x = event.x
        self._y = event.y

    def do_move(self, event):
        x = self.winfo_pointerx() - self._x
        y = self.winfo_pointery() - self._y
        self.geometry(f"+{x}+{y}")

    def _get_current_settings(self):
        return {
            "normal_x_speed": getattr(config, "normal_x_speed", 0.5),
            "normal_y_speed": getattr(config, "normal_y_speed", 0.5),
            "normalsmooth": getattr(config, "normalsmooth", 10),
            "normalsmoothfov": getattr(config, "normalsmoothfov", 10),
            "mouse_dpi": getattr(config, "mouse_dpi", 800),
            "fovsize": getattr(config, "fovsize", 300),
            "tbfovsize": getattr(config, "tbfovsize", 70),
            "tbdelay": getattr(config, "tbdelay", 0.08),
            "in_game_sens": getattr(config, "in_game_sens", 7),
            "color": getattr(config, "color", "yellow"),
            "mode": getattr(config, "mode", "Normal"),
            "enableaim": getattr(config, "enableaim", False),
            "enabletb": getattr(config, "enabletb", False),
            "selected_mouse_button": getattr(config, "selected_mouse_button", 3),
            "selected_tb_btn": getattr(config, "selected_tb_btn", 3),
        }

    def _apply_settings(self, data, config_name=None):
        """
        Applique un dictionnaire de settings sur le config global, le tracker et l'UI.
        Recharge le modèle si nécessaire.
        """
        try:
            # --- Appliquer sur config global ---
            for k, v in data.items():
                setattr(config, k, v)

            # --- Appliquer sur le tracker si l'attribut existe ---
            for k, v in data.items():
                if hasattr(self.tracker, k):
                    setattr(self.tracker, k, v)

            # --- Mettre à jour les sliders ---
            for k, v in data.items():
                if k in self._slider_widgets:
                    self._set_slider_value(k, v)

            # --- Mettre à jour les checkbox ---
            for k, v in data.items():
                if k in self._checkbox_vars:
                    self._set_checkbox_value(k, v)

            # --- Mettre à jour les OptionMenu ---
            for k, v in data.items():
                if k in self._option_widgets:
                    self._set_option_value(k, v)

            # --- Mettre à jour les OptionMenu ---
            for k, v in data.items():
                if k == "selected_mouse_button" or k == "selected_tb_btn":
                    if k in self._option_widgets:
                        print(k, v)

                        v = BUTTONS[v]
                        print(v)
                        self._set_btn_option_value(k, v)

            # --- Recharger le modèle si nécessaire ---
            from detection_color import reload_model

            self.tracker.model, self.tracker.class_names = reload_model()

            if config_name:
                self._log_config(
                    f"Config '{config_name}' applied and model reloaded ✅"
                )
            else:
                self._log_config(f"Config applied and model reloaded ✅")

        except Exception as e:
            self._log_config(f"[Erreur _apply_settings] {e}")

    def _save_new_config(self):
        from tkinter import simpledialog

        name = simpledialog.askstring("Config name", "Enter the config name:")
        if not name:
            self._log_config("Cancelled save (pas de nom fourni).")
            return
        data = self._get_current_settings()
        path = os.path.join("configs", f"{name}.json")
        try:
            os.makedirs("configs", exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            self._refresh_config_list()
            self.config_option.set(name)  # Sélectionner automatiquement
            self._log_config(f"New config'{name}' saved ✅")
        except Exception as e:
            self._log_config(f"[Erreur SAVE] {e}")

    def _load_selected_config(self):
        """
        Charge la config sélectionnée dans l'OptionMenu.
        """
        name = self.config_option.get()
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._apply_settings(data, config_name=name)
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Erreur LOAD] {e}")

    def _refresh_config_list(self):
        files = [f[:-5] for f in os.listdir("configs") if f.endswith(".json")]
        if not files:
            files = ["default"]
        current = self.config_option.get()
        self.config_option.configure(values=files)
        if current in files:
            self.config_option.set(current)
        else:
            self.config_option.set(files[0])

    def _on_config_selected(self, val):
        self._log_config(f"Selected config: {val}")

    def _save_config(self):
        name = self.config_option.get() or "default"
        data = self._get_current_settings()
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            self._log_config(f"Config '{name}' sauvegardée ✅")
            self._refresh_config_list()
        except Exception as e:
            self._log_config(f"[Erreur SAVE] {e}")

    def _load_config(self):
        name = self.config_option.get() or "default"
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._apply_settings(data)
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Erreur LOAD] {e}")

    def _log_config(self, msg):
        self.config_log.insert("end", msg + "\n")
        self.config_log.see("end")

    # ----------------------- UI BUILDERS -----------------------
    def _build_general_tab(self):
        self.status_label = ctk.CTkLabel(self.tab_general, text="Status: Disconnected")
        self.status_label.pack(pady=5, anchor="w")
        self.metrics_label = ctk.CTkLabel(self.tab_general, text="Avg: -- ms  -- fps")
        self.metrics_label.pack(pady=2, anchor="w")

        # UDP controls
        port_frame = ctk.CTkFrame(self.tab_general)
        port_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(port_frame, text="UDP Port").pack(side="left", padx=6)
        self.udp_port_entry = ctk.CTkEntry(port_frame)
        self.udp_port_entry.insert(0, "8080")
        self.udp_port_entry.pack(side="left", fill="x", expand=True)
        btn_frame = ctk.CTkFrame(self.tab_general)
        btn_frame.pack(pady=5, fill="x")
        ctk.CTkButton(btn_frame, text="Start UDP", command=self._start_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )
        ctk.CTkButton(btn_frame, text="Stop UDP", command=self._stop_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )
        # Removed Appearance/Mode/Color controls

    def _build_aimbot_tab(self):
        # Alignment
        align_frame = ctk.CTkFrame(self.tab_aimbot)
        align_frame.pack(padx=12, pady=6, fill="x")
        ctk.CTkLabel(align_frame, text="Alignment").pack(side="left")
        self.opt_align = ctk.CTkOptionMenu(
            align_frame,
            values=["Top", "Center", "Bottom"],
            command=lambda v: self._on_aim_alignment(v),
        )
        self.opt_align.pack(side="left", padx=8)
        self.opt_align.set(getattr(config, "aim", {}).get("alignment", "Center"))

        # Offset percent
        offp = getattr(config, "aim", {}).get(
            "offset_percent", {"use_x": False, "use_y": True, "x": 50.0, "y": 65.0}
        )
        offp_frame = ctk.CTkFrame(self.tab_aimbot)
        offp_frame.pack(padx=12, pady=6, fill="x")
        self.var_use_xp = tk.BooleanVar(value=bool(offp.get("use_x", False)))
        self.var_use_yp = tk.BooleanVar(value=bool(offp.get("use_y", True)))
        ctk.CTkCheckBox(
            offp_frame,
            text="Use Offset% X",
            variable=self.var_use_xp,
            command=self._on_aim_offsets_percent,
        ).pack(side="left")
        ctk.CTkCheckBox(
            offp_frame,
            text="Use Offset% Y",
            variable=self.var_use_yp,
            command=self._on_aim_offsets_percent,
        ).pack(side="left", padx=8)
        self.entry_offx_pct = ctk.CTkEntry(offp_frame, width=60)
        self.entry_offx_pct.insert(0, str(offp.get("x", 50.0)))
        self.entry_offx_pct.pack(side="left", padx=4)
        self.entry_offy_pct = ctk.CTkEntry(offp_frame, width=60)
        self.entry_offy_pct.insert(0, str(offp.get("y", 65.0)))
        self.entry_offy_pct.pack(side="left", padx=4)
        ctk.CTkButton(
            offp_frame, text="Apply%", command=self._on_aim_offsets_percent
        ).pack(side="left", padx=6)

        # Offset px
        offpx = getattr(config, "aim", {}).get("offset_px", {"x": 0, "y": 0})
        offpx_frame = ctk.CTkFrame(self.tab_aimbot)
        offpx_frame.pack(padx=12, pady=6, fill="x")
        ctk.CTkLabel(offpx_frame, text="Offset px X").pack(side="left")
        self.entry_offx_px = ctk.CTkEntry(offpx_frame, width=60)
        self.entry_offx_px.insert(0, str(offpx.get("x", 0)))
        self.entry_offx_px.pack(side="left", padx=4)
        ctk.CTkLabel(offpx_frame, text="Offset px Y").pack(side="left")
        self.entry_offy_px = ctk.CTkEntry(offpx_frame, width=60)
        self.entry_offy_px.insert(0, str(offpx.get("y", 0)))
        self.entry_offy_px.pack(side="left", padx=4)
        ctk.CTkButton(
            offpx_frame, text="Apply px", command=self._on_aim_offsets_px
        ).pack(side="left", padx=6)

        # Movement group
        mov = getattr(config, "aim", {}).get("movement", {})
        mv_frame = ctk.CTkFrame(self.tab_aimbot)
        mv_frame.pack(padx=12, pady=6, fill="x")
        ctk.CTkLabel(mv_frame, text="Sensitivity Scale").grid(
            row=0, column=0, sticky="w"
        )
        self.var_sens = tk.DoubleVar(
            value=float(mov.get("mouse_sensitivity_scale", 1.0))
        )
        ctk.CTkSlider(
            mv_frame,
            from_=0.1,
            to=5.0,
            number_of_steps=99,
            variable=self.var_sens,
            command=lambda v: self._on_aim_movement_changed(),
        ).grid(row=0, column=1, sticky="we")
        ctk.CTkLabel(mv_frame, text="Deadzone X/Y").grid(row=1, column=0, sticky="w")
        self.entry_dz_x = ctk.CTkEntry(mv_frame, width=60)
        self.entry_dz_x.insert(0, str(mov.get("deadzone_px", {}).get("x", 0)))
        self.entry_dz_x.grid(row=1, column=1, sticky="w")
        self.entry_dz_y = ctk.CTkEntry(mv_frame, width=60)
        self.entry_dz_y.insert(0, str(mov.get("deadzone_px", {}).get("y", 0)))
        self.entry_dz_y.grid(row=1, column=2, sticky="w")
        ctk.CTkLabel(mv_frame, text="Max step X/Y").grid(row=2, column=0, sticky="w")
        self.entry_ms_x = ctk.CTkEntry(mv_frame, width=60)
        self.entry_ms_x.insert(0, str(mov.get("max_step_px", {}).get("x", 30)))
        self.entry_ms_x.grid(row=2, column=1, sticky="w")
        self.entry_ms_y = ctk.CTkEntry(mv_frame, width=60)
        self.entry_ms_y.insert(0, str(mov.get("max_step_px", {}).get("y", 30)))
        self.entry_ms_y.grid(row=2, column=2, sticky="w")
        ctk.CTkLabel(mv_frame, text="Jitter X/Y").grid(row=3, column=0, sticky="w")
        self.entry_j_x = ctk.CTkEntry(mv_frame, width=60)
        self.entry_j_x.insert(0, str(mov.get("jitter_px", {}).get("x", 0)))
        self.entry_j_x.grid(row=3, column=1, sticky="w")
        self.entry_j_y = ctk.CTkEntry(mv_frame, width=60)
        self.entry_j_y.insert(0, str(mov.get("jitter_px", {}).get("y", 0)))
        self.entry_j_y.grid(row=3, column=2, sticky="w")
        self.var_ar_corr = tk.BooleanVar(
            value=bool(mov.get("aspect_ratio_correction", True))
        )
        ctk.CTkCheckBox(
            mv_frame,
            text="Aspect ratio correction",
            variable=self.var_ar_corr,
            command=self._on_aim_movement_changed,
        ).grid(row=4, column=0, sticky="w")
        self.var_lock = tk.BooleanVar(value=bool(mov.get("lock_on_screen", True)))
        ctk.CTkCheckBox(
            mv_frame,
            text="Lock on screen",
            variable=self.var_lock,
            command=self._on_aim_movement_changed,
        ).grid(row=4, column=1, sticky="w")

        # X Speed
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "X Speed",
            0.1,
            2000,
            float(getattr(config, "normal_x_speed", 0.5)),
            self._on_normal_x_speed_changed,
            is_float=True,
        )
        self._register_slider("normal_x_speed", s, l, 0.1, 2000, True)
        # Y Speed
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Y Speed",
            0.1,
            2000,
            float(getattr(config, "normal_y_speed", 0.5)),
            self._on_normal_y_speed_changed,
            is_float=True,
        )
        self._register_slider("normal_y_speed", s, l, 0.1, 2000, True)
        # In-game sens
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "In-game sens",
            0.1,
            2000,
            float(getattr(config, "in_game_sens", 7)),
            self._on_config_in_game_sens_changed,
            is_float=True,
        )
        self._register_slider("in_game_sens", s, l, 0.1, 2000, True)
        # Smoothing
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Smoothing",
            1,
            30,
            float(getattr(config, "normalsmooth", 10)),
            self._on_config_normal_smooth_changed,
            is_float=True,
        )
        self._register_slider("normalsmooth", s, l, 1, 30, True)
        # Smoothing FOV
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Smoothing FOV",
            1,
            30,
            float(getattr(config, "normalsmoothfov", 10)),
            self._on_config_normal_smoothfov_changed,
            is_float=True,
        )
        self._register_slider("normalsmoothfov", s, l, 1, 30, True)
        # FOV Size
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "FOV Size",
            1,
            1000,
            float(getattr(config, "fovsize", 300)),
            self._on_fovsize_changed,
            is_float=True,
        )
        self._register_slider("fovsize", s, l, 1, 1000, True)

        # Enable Aim
        self.var_enableaim = tk.BooleanVar(value=getattr(config, "enableaim", False))
        ctk.CTkCheckBox(
            self.tab_aimbot,
            text="Enable Aim",
            variable=self.var_enableaim,
            command=self._on_enableaim_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["enableaim"] = self.var_enableaim

        ctk.CTkLabel(self.tab_aimbot, text="Aim Keys (choose two)").pack(
            pady=5, anchor="w"
        )
        # Two selectors for aim keys
        self.aim_key_1 = ctk.CTkOptionMenu(
            self.tab_aimbot,
            values=list(BUTTONS.values()),
            command=lambda v: self._on_aim_key_changed(),
        )
        self.aim_key_1.pack(pady=4, fill="x")
        self.aim_key_2 = ctk.CTkOptionMenu(
            self.tab_aimbot,
            values=list(BUTTONS.values()),
            command=lambda v: self._on_aim_key_changed(),
        )
        self.aim_key_2.pack(pady=4, fill="x")

    def _on_aim_alignment(self, v):
        getattr(config, "aim", {})["alignment"] = v

    def _on_aim_offsets_percent(self):
        aim = getattr(config, "aim", {})
        offp = aim.setdefault("offset_percent", {})
        offp["use_x"] = bool(self.var_use_xp.get())
        offp["use_y"] = bool(self.var_use_yp.get())
        try:
            offp["x"] = float(self.entry_offx_pct.get())
        except Exception:
            pass
        try:
            offp["y"] = float(self.entry_offy_pct.get())
        except Exception:
            pass

    def _on_aim_offsets_px(self):
        aim = getattr(config, "aim", {})
        off = aim.setdefault("offset_px", {})
        try:
            off["x"] = int(float(self.entry_offx_px.get()))
        except Exception:
            pass
        try:
            off["y"] = int(float(self.entry_offy_px.get()))
        except Exception:
            pass

    def _on_aim_movement_changed(self):
        aim = getattr(config, "aim", {})
        mov = aim.setdefault("movement", {})
        try:
            mov["mouse_sensitivity_scale"] = float(self.var_sens.get())
        except Exception:
            pass
        try:
            mov.setdefault("deadzone_px", {})["x"] = int(float(self.entry_dz_x.get()))
            mov.setdefault("deadzone_px", {})["y"] = int(float(self.entry_dz_y.get()))
        except Exception:
            pass
        try:
            mov.setdefault("max_step_px", {})["x"] = int(float(self.entry_ms_x.get()))
            mov.setdefault("max_step_px", {})["y"] = int(float(self.entry_ms_y.get()))
        except Exception:
            pass
        try:
            mov.setdefault("jitter_px", {})["x"] = int(float(self.entry_j_x.get()))
            mov.setdefault("jitter_px", {})["y"] = int(float(self.entry_j_y.get()))
        except Exception:
            pass
        mov["aspect_ratio_correction"] = bool(self.var_ar_corr.get())
        mov["lock_on_screen"] = bool(self.var_lock.get())

    def _build_tb_tab(self):
        # TB FOV Size
        s, l = self._add_slider_with_label(
            self.tab_tb,
            "TB FOV Size",
            1,
            300,
            float(getattr(config, "tbfovsize", 70)),
            self._on_tbfovsize_changed,
            is_float=True,
        )
        self._register_slider("tbfovsize", s, l, 1, 300, True)
        # TB Delay
        s, l = self._add_slider_with_label(
            self.tab_tb,
            "TB Delay",
            0.0,
            1.0,
            float(getattr(config, "tbdelay", 0.08)),
            self._on_tbdelay_changed,
            is_float=True,
        )
        self._register_slider("tbdelay", s, l, 0.0, 1.0, True)

        # Enable TB
        self.var_enabletb = tk.BooleanVar(value=getattr(config, "enabletb", False))
        ctk.CTkCheckBox(
            self.tab_tb,
            text="Enable TB",
            variable=self.var_enabletb,
            command=self._on_enabletb_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["enabletb"] = self.var_enabletb

        ctk.CTkLabel(self.tab_tb, text="Triggerbot Button").pack(pady=5, anchor="w")
        self.tb_button_option = ctk.CTkOptionMenu(
            self.tab_tb,
            values=list(BUTTONS.values()),
            command=self._on_tb_button_selected,
        )
        self.tb_button_option.pack(pady=5, fill="x")
        self._option_widgets["selected_tb_btn"] = self.tb_button_option

        # New Trigger settings UI
        tr = getattr(config, "trigger", {})
        trg_frame = ctk.CTkFrame(self.tab_tb)
        trg_frame.pack(padx=12, pady=8, fill="x")
        ctk.CTkLabel(trg_frame, text="Mode").grid(row=0, column=0, sticky="w")
        self.opt_trigger_mode = ctk.CTkOptionMenu(
            trg_frame,
            values=["single", "spray"],
            command=lambda v: self._on_trigger_mode(v),
        )
        self.opt_trigger_mode.grid(row=0, column=1, sticky="w")
        self.opt_trigger_mode.set(tr.get("mode", "single"))
        self.var_tr_enabled = tk.BooleanVar(value=bool(tr.get("enabled", False)))
        ctk.CTkCheckBox(
            trg_frame,
            text="Enabled",
            variable=self.var_tr_enabled,
            command=self._on_trigger_flags,
        ).grid(row=0, column=2, sticky="w")
        self.var_tr_req_aim = tk.BooleanVar(
            value=bool(tr.get("require_aim_pressed", True))
        )
        ctk.CTkCheckBox(
            trg_frame,
            text="Require Aim Pressed",
            variable=self.var_tr_req_aim,
            command=self._on_trigger_flags,
        ).grid(row=1, column=0, sticky="w")
        self.var_tr_cursor = tk.BooleanVar(value=bool(tr.get("cursor_check", True)))
        ctk.CTkCheckBox(
            trg_frame,
            text="Cursor In Box",
            variable=self.var_tr_cursor,
            command=self._on_trigger_flags,
        ).grid(row=1, column=1, sticky="w")

        ctk.CTkLabel(trg_frame, text="Trigger Delay ms").grid(
            row=2, column=0, sticky="w"
        )
        self.entry_tr_delay = ctk.CTkEntry(trg_frame, width=80)
        self.entry_tr_delay.insert(0, str(int(tr.get("trigger_delay_ms", 120))))
        self.entry_tr_delay.grid(row=2, column=1, sticky="w")
        ctk.CTkLabel(trg_frame, text="Down→Up Delay ms").grid(
            row=2, column=2, sticky="w"
        )
        self.entry_tr_downup = ctk.CTkEntry(trg_frame, width=80)
        self.entry_tr_downup.insert(0, str(int(tr.get("click_down_up_delay_ms", 20))))
        self.entry_tr_downup.grid(row=2, column=3, sticky="w")

        ctk.CTkLabel(trg_frame, text="Safety Min Interval ms").grid(
            row=3, column=0, sticky="w"
        )
        self.entry_tr_min_int = ctk.CTkEntry(trg_frame, width=80)
        self.entry_tr_min_int.insert(
            0, str(int(tr.get("safety", {}).get("min_interval_ms", 50)))
        )
        self.entry_tr_min_int.grid(row=3, column=1, sticky="w")
        ctk.CTkLabel(trg_frame, text="Max Rate /s").grid(row=3, column=2, sticky="w")
        self.entry_tr_max_rate = ctk.CTkEntry(trg_frame, width=80)
        self.entry_tr_max_rate.insert(
            0, str(int(tr.get("safety", {}).get("max_rate_per_s", 15)))
        )
        self.entry_tr_max_rate.grid(row=3, column=3, sticky="w")

        self.var_spray_release = tk.BooleanVar(
            value=bool(tr.get("spray", {}).get("release_if_cursor_outside_box", True))
        )
        ctk.CTkCheckBox(
            trg_frame,
            text="Spray: release if cursor outside box",
            variable=self.var_spray_release,
            command=self._on_trigger_flags,
        ).grid(row=4, column=0, columnspan=3, sticky="w")

    def _on_trigger_mode(self, v):
        getattr(config, "trigger", {})["mode"] = v

    def _on_trigger_flags(self):
        tr = getattr(config, "trigger", {})
        tr["enabled"] = bool(self.var_tr_enabled.get())
        tr["require_aim_pressed"] = bool(self.var_tr_req_aim.get())
        tr["cursor_check"] = bool(self.var_tr_cursor.get())
        try:
            tr["trigger_delay_ms"] = int(self.entry_tr_delay.get())
        except Exception:
            pass
        try:
            tr["click_down_up_delay_ms"] = int(self.entry_tr_downup.get())
        except Exception:
            pass
        sa = tr.setdefault("safety", {})
        try:
            sa["min_interval_ms"] = int(self.entry_tr_min_int.get())
        except Exception:
            pass
        try:
            sa["max_rate_per_s"] = int(self.entry_tr_max_rate.get())
        except Exception:
            pass
        tr.setdefault("spray", {})["release_if_cursor_outside_box"] = bool(
            self.var_spray_release.get()
        )

    # Generic slider helper (parent-aware)
    def _add_slider_with_label(
        self, parent, text, min_val, max_val, init_val, command, is_float=False
    ):
        frame = ctk.CTkFrame(parent)
        frame.pack(padx=12, pady=6, fill="x")

        label = ctk.CTkLabel(
            frame, text=f"{text}: {init_val:.2f}" if is_float else f"{text}: {init_val}"
        )
        label.pack(side="left")

        steps = 100 if is_float else max(1, int(max_val - min_val))
        slider = ctk.CTkSlider(
            frame,
            from_=min_val,
            to=max_val,
            number_of_steps=steps,
            command=lambda v: self._slider_callback(v, label, text, command, is_float),
        )
        slider.set(init_val)
        slider.pack(side="right", fill="x", expand=True)
        return slider, label

    def _slider_callback(self, value, label, text, command, is_float):
        val = float(value) if is_float else int(round(value))
        label.configure(text=f"{text}: {val:.2f}" if is_float else f"{text}: {val}")
        command(val)

    # ----------------------- Detect Tab -----------------------
    def _build_detect_tab(self):
        # Source
        src_frame = ctk.CTkFrame(self.tab_detect)
        src_frame.pack(padx=12, pady=8, fill="x")
        ctk.CTkLabel(src_frame, text="Detection Source").pack(side="left")
        self.var_detect_source = tk.StringVar(
            value=getattr(config, "detection", {}).get("source", "color")
        )
        ctk.CTkRadioButton(
            src_frame,
            text="AI",
            variable=self.var_detect_source,
            value="ai",
            command=self._on_detect_source_changed,
        ).pack(side="left", padx=8)
        ctk.CTkRadioButton(
            src_frame,
            text="Color",
            variable=self.var_detect_source,
            value="color",
            command=self._on_detect_source_changed,
        ).pack(side="left", padx=8)

        # Runtime
        rt = getattr(config, "runtime", {})
        rt_frame = ctk.CTkFrame(self.tab_detect)
        rt_frame.pack(padx=12, pady=8, fill="x")
        ctk.CTkLabel(rt_frame, text="Active Provider").grid(
            row=0, column=0, sticky="w", padx=4, pady=2
        )
        self.opt_active_provider = ctk.CTkOptionMenu(
            rt_frame,
            values=[
                "auto",
                "DmlExecutionProvider",
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ],
            command=self._on_runtime_changed,
        )
        self.opt_active_provider.grid(row=0, column=1, sticky="w")
        self.opt_active_provider.set(rt.get("active_provider", "auto"))

        ctk.CTkLabel(rt_frame, text="Model Path").grid(
            row=1, column=0, sticky="w", padx=4, pady=2
        )
        self.entry_model_path = ctk.CTkEntry(rt_frame, width=280)
        self.entry_model_path.grid(row=1, column=1, sticky="w")
        self.entry_model_path.insert(0, rt.get("model_path", ""))
        ctk.CTkButton(
            rt_frame, text="Browse .onnx", command=self._on_browse_model
        ).grid(row=1, column=2, padx=6)

        ctk.CTkLabel(rt_frame, text="Image Size").grid(
            row=2, column=0, sticky="w", padx=4, pady=2
        )
        self.opt_img_size = ctk.CTkOptionMenu(
            rt_frame,
            values=["320", "416", "512", "640"],
            command=self._on_runtime_changed,
        )
        self.opt_img_size.grid(row=2, column=1, sticky="w")
        self.opt_img_size.set(str(rt.get("image_size", 640)))

        self.btn_reinit_detect = ctk.CTkButton(
            rt_frame,
            text="Reinitialize Session",
            command=self._on_reinit_detect_session,
        )
        self.btn_reinit_detect.grid(row=3, column=1, sticky="w", pady=4)
        self.lbl_detect_status = ctk.CTkLabel(
            rt_frame, text="Provider: -- | Status: idle"
        )
        self.lbl_detect_status.grid(row=3, column=2, sticky="w", padx=6)
        # Optional FPS cap
        ctk.CTkLabel(rt_frame, text="FPS Cap (0=off)").grid(
            row=4, column=0, sticky="w", padx=4, pady=2
        )
        self.entry_fps_cap = ctk.CTkEntry(rt_frame, width=80)
        self.entry_fps_cap.grid(row=4, column=1, sticky="w")
        self.entry_fps_cap.insert(0, str(int(rt.get("inference_fps_cap", 0))))
        ctk.CTkButton(
            rt_frame, text="Apply FPS Cap", command=self._on_runtime_changed
        ).grid(row=4, column=2, sticky="w")

        # Thresholds & NMS
        filt_frame = ctk.CTkFrame(self.tab_detect)
        filt_frame.pack(padx=12, pady=8, fill="x")
        ctk.CTkLabel(filt_frame, text="Confidence").grid(row=0, column=0, sticky="w")
        self.var_conf = tk.DoubleVar(
            value=float(
                getattr(config, "detection", {}).get("confidence_threshold", 0.25)
            )
        )
        ctk.CTkSlider(
            filt_frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=self.var_conf,
            command=lambda v: self._on_confidence_changed(v),
        ).grid(row=0, column=1, sticky="we")

        nms = getattr(config, "detection", {}).get("nms", {})
        self.var_nms_enabled = tk.BooleanVar(value=bool(nms.get("enabled", True)))
        ctk.CTkCheckBox(
            filt_frame,
            text="NMS Enabled",
            variable=self.var_nms_enabled,
            command=self._on_nms_changed,
        ).grid(row=1, column=0, sticky="w")
        ctk.CTkLabel(filt_frame, text="IoU").grid(row=1, column=1, sticky="w")
        self.var_iou = tk.DoubleVar(value=float(nms.get("iou_threshold", 0.5)))
        ctk.CTkSlider(
            filt_frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=self.var_iou,
            command=lambda v: self._on_nms_changed(),
        ).grid(row=1, column=2, sticky="we")
        ctk.CTkLabel(filt_frame, text="Max Detections").grid(
            row=1, column=3, sticky="w"
        )
        self.entry_max_det = ctk.CTkEntry(filt_frame, width=60)
        self.entry_max_det.grid(row=1, column=4, sticky="w")
        self.entry_max_det.insert(0, str(int(nms.get("max_detections", 200))))

        # Sticky Aim
        sel = getattr(config, "detection", {}).get("target_selection", {})
        st = sel.get(
            "sticky_aim", {"enabled": False, "threshold_px": 30, "max_lost_frames": 10}
        )
        st_frame = ctk.CTkFrame(self.tab_detect)
        st_frame.pack(padx=12, pady=8, fill="x")
        self.var_sticky = tk.BooleanVar(value=bool(st.get("enabled", False)))
        ctk.CTkCheckBox(
            st_frame,
            text="Sticky Aim",
            variable=self.var_sticky,
            command=self._on_sticky_changed,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(st_frame, text="Threshold px").grid(row=0, column=1, sticky="w")
        self.var_sticky_px = tk.IntVar(value=int(st.get("threshold_px", 30)))
        ctk.CTkSlider(
            st_frame,
            from_=0,
            to=200,
            number_of_steps=200,
            variable=self.var_sticky_px,
            command=lambda v: self._on_sticky_changed(),
        ).grid(row=0, column=2, sticky="we")
        ctk.CTkLabel(st_frame, text="Lost frames").grid(row=0, column=3, sticky="w")
        self.entry_lost = ctk.CTkEntry(st_frame, width=60)
        self.entry_lost.grid(row=0, column=4, sticky="w")
        self.entry_lost.insert(0, str(int(st.get("max_lost_frames", 10))))

        # Debug & overlay & actions
        act_frame = ctk.CTkFrame(self.tab_detect)
        act_frame.pack(padx=12, pady=8, fill="x")
        dbg = getattr(config, "debug", {})
        self.var_timings = tk.BooleanVar(
            value=bool(dbg.get("timings", {}).get("enabled", False))
        )
        ctk.CTkCheckBox(
            act_frame,
            text="Timings",
            variable=self.var_timings,
            command=self._on_timings_changed,
        ).pack(side="left")
        # Global ESP toggle for Vision overlay
        over = dbg.get("overlay", {})
        self.var_draw_esp = tk.BooleanVar(value=bool(over.get("draw_esp", True)))
        ctk.CTkCheckBox(
            act_frame,
            text="ESP (Vision)",
            variable=self.var_draw_esp,
            command=self._on_overlay_esp_toggle,
        ).pack(side="left", padx=10)
        self.var_draw_fov = tk.BooleanVar(value=bool(over.get("draw_fov", True)))
        self.var_draw_boxes = tk.BooleanVar(value=bool(over.get("draw_boxes", True)))
        self.var_draw_target = tk.BooleanVar(value=bool(over.get("draw_target", True)))
        self.var_draw_mask = tk.BooleanVar(value=bool(over.get("draw_mask", False)))
        ctk.CTkCheckBox(
            act_frame,
            text="Draw FOV",
            variable=self.var_draw_fov,
            command=self._on_overlay_changed,
        ).pack(side="left", padx=6)
        ctk.CTkCheckBox(
            act_frame,
            text="Draw Boxes",
            variable=self.var_draw_boxes,
            command=self._on_overlay_changed,
        ).pack(side="left", padx=6)
        ctk.CTkCheckBox(
            act_frame,
            text="Draw Target",
            variable=self.var_draw_target,
            command=self._on_overlay_changed,
        ).pack(side="left", padx=6)
        ctk.CTkCheckBox(
            act_frame,
            text="Draw Mask",
            variable=self.var_draw_mask,
            command=self._on_overlay_changed,
        ).pack(side="left", padx=6)

        self._update_detect_runtime_enabled()

    def _on_detect_source_changed(self):
        det = getattr(config, "detection", {})
        det["source"] = self.var_detect_source.get()
        self._update_detect_runtime_enabled()
        # Auto reinit if switched to AI and runtime looks valid
        if det.get("source") == "ai":
            self._auto_reinit_if_possible()

    def _update_detect_runtime_enabled(self):
        enable = self.var_detect_source.get() == "ai"
        for w in (
            self.opt_active_provider,
            self.entry_model_path,
            self.btn_reinit_detect,
            self.opt_img_size,
        ):
            try:
                w.configure(state="normal" if enable else "disabled")
            except Exception:
                pass
        # Restart display thread to create only relevant windows
        try:
            if self.display_thread is not None and self.display_thread.is_alive():
                self.display_thread.stop()
                self.display_thread.join(timeout=1.0)
                # hard close cv2 windows to avoid frozen extra Vision
                try:
                    cv2.destroyWindow("VISION")
                except Exception:
                    pass
                try:
                    cv2.destroyWindow("MASK")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            create_mask = not enable
            # Recreate display thread with fresh windows (avoid double Vision)
            self.display_thread = DisplayThread(self, self.vision_store, self.mask_store, create_mask=create_mask)
            self.display_thread.start()
        except Exception:
            pass

    def _on_browse_model(self):
        path = filedialog.askopenfilename(filetypes=[("ONNX Model", "*.onnx")])
        if not path:
            return
        self.entry_model_path.delete(0, "end")
        self.entry_model_path.insert(0, path)
        getattr(config, "runtime", {})["model_path"] = path
        self._mark_detect_runtime_dirty()
        self._auto_reinit_if_possible()

    def _on_runtime_changed(self, *_):
        rt = getattr(config, "runtime", {})
        rt["active_provider"] = self.opt_active_provider.get()
        try:
            rt["image_size"] = int(self.opt_img_size.get())
        except Exception:
            pass
        self._mark_detect_runtime_dirty()
        self._validate_detect_config()
        self._auto_reinit_if_possible()

    def _mark_detect_runtime_dirty(self):
        self._ui_log("[DetectUI] Status: pending reinit")

    def _on_reinit_detect_session(self):
        model = self.entry_model_path.get().strip()
        if not model or not model.lower().endswith(".onnx"):
            self._ui_log("[DetectUI] Invalid model path")
            return
        if not os.path.exists(model):
            self._ui_log("[DetectUI] Model file not found")
            return
        # Validate image size set
        try:
            img_sz = int(self.opt_img_size.get())
            if img_sz not in (320, 416, 512, 640):
                self._ui_log("[DetectUI] Invalid image size")
                return
        except Exception:
            self._ui_log("[DetectUI] Invalid image size")
            return
        # Validate IoU
        try:
            iou = float(self.var_iou.get())
            if iou < 0.0 or iou > 1.0:
                self._ui_log("[DetectUI] IoU must be 0..1")
                return
        except Exception:
            pass
        # Validate areas
        try:
            min_a = float(
                self.entry_max_det.get()
            )  # placeholder to keep structure; real check below after widgets exist
        except Exception:
            pass
        self._ui_log("[DetectUI] Status: initializing...")
        ok, prov = detect_reinit_session(
            model, self.opt_active_provider.get(), getattr(config, "runtime", {})
        )
        if ok:
            self._ui_log(f"[DetectUI] Provider: {prov} | Status: ready")
        else:
            self._ui_log("[DetectUI] Provider: CPU (fallback)")

    def _auto_reinit_if_possible(self):
        try:
            det = getattr(config, "detection", {})
            if det.get("source") != "ai":
                return
            model = self.entry_model_path.get().strip()
            img_sz_ok = False
            try:
                img_sz_ok = int(self.opt_img_size.get()) in (320, 416, 512, 640)
            except Exception:
                img_sz_ok = False
            if (
                model
                and model.lower().endswith(".onnx")
                and os.path.exists(model)
                and img_sz_ok
            ):
                self._ui_log("[DetectUI] Status: initializing...")
                ok, prov = detect_reinit_session(
                    model,
                    self.opt_active_provider.get(),
                    getattr(config, "runtime", {}),
                )
                if ok:
                    self._ui_log(f"[DetectUI] Provider: {prov} | Status: ready")
                else:
                    self._ui_log("[DetectUI] Provider: CPU (fallback)")
        except Exception:
            pass

    def _on_confidence_changed(self, v):
        det = getattr(config, "detection", {})
        det["confidence_threshold"] = round(float(v), 3)

    def _on_nms_changed(self):
        det = getattr(config, "detection", {})
        nms = det.setdefault("nms", {})
        nms["enabled"] = bool(self.var_nms_enabled.get())
        try:
            nms["iou_threshold"] = float(self.var_iou.get())
        except Exception:
            pass
        try:
            nms["max_detections"] = int(self.entry_max_det.get())
        except Exception:
            pass

    def _on_sticky_changed(self):
        det = getattr(config, "detection", {})
        ts = det.setdefault("target_selection", {})
        st = ts.setdefault("sticky_aim", {})
        st["enabled"] = bool(self.var_sticky.get())
        try:
            st["threshold_px"] = int(self.var_sticky_px.get())
        except Exception:
            pass
        try:
            st["max_lost_frames"] = int(self.entry_lost.get())
        except Exception:
            pass

    def _on_timings_changed(self):
        dbg = getattr(config, "debug", {})
        t = dbg.setdefault("timings", {})
        t["enabled"] = bool(self.var_timings.get())

    def _on_overlay_changed(self):
        try:
            dbg = getattr(config, "debug", {})
            over = dbg.setdefault("overlay", {})
            if not over.get("draw_esp", True):
                # If global ESP disabled, force all sub overlays off in config
                over["draw_fov"] = False
                over["draw_boxes"] = False
                over["draw_target"] = False
            over["draw_fov"] = bool(self.var_draw_fov.get())
            over["draw_boxes"] = bool(self.var_draw_boxes.get())
            over["draw_target"] = bool(self.var_draw_target.get())
            over["draw_mask"] = bool(self.var_draw_mask.get())
        except Exception:
            pass

    def _on_overlay_esp_toggle(self):
        try:
            dbg = getattr(config, "debug", {})
            over = dbg.setdefault("overlay", {})
            over["draw_esp"] = bool(self.var_draw_esp.get())
            if not over["draw_esp"]:
                # Turn off sub-overlays in UI and config
                for var in (self.var_draw_fov, self.var_draw_boxes, self.var_draw_target):
                    var.set(False)
                over["draw_fov"] = False
                over["draw_boxes"] = False
                over["draw_target"] = False
            else:
                # Re-enable defaults when turning ESP back on
                self.var_draw_fov.set(True)
                self.var_draw_boxes.set(True)
                self.var_draw_target.set(True)
                over["draw_fov"] = True
                over["draw_boxes"] = True
                over["draw_target"] = True
        except Exception:
            pass

    def _validate_detect_config(self):
        try:
            iou = float(self.var_iou.get())
        except Exception:
            iou = 0.5
        try:
            img_sz = int(self.opt_img_size.get())
        except Exception:
            img_sz = 640
        ok = (0.0 <= iou <= 1.0) and (img_sz in (320, 416, 512, 640))
        # No UI text; optional color hint removed per request

    def _reset_sticky_target(self):
        try:
            self.tracker.detect_state.sticky_target = None
            self.tracker.detect_state.lost_frames = 0
            self.lbl_detect_status.configure(text="Sticky reset", text_color="#3a6")
        except Exception:
            pass

    def _test_detect_once(self):
        try:
            img = self.get_latest_frame()
            if img is None:
                self._ui_log("[DetectUI] No ROI")
                return
            h, w = img.shape[:2]
            roi_bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            roi_rect = {"left": 0, "top": 0, "width": int(w), "height": int(h)}
            t0 = time.perf_counter_ns()
            out = detect_step(
                roi_bgra,
                roi_rect,
                getattr(config, "runtime", {}),
                getattr(config, "detection", {}),
                self.tracker.detect_state,
                getattr(config, "debug", {}),
            )
            t1 = time.perf_counter_ns()
            n = len(out.get("detections", []))
            ms = (t1 - t0) / 1e6
            self._ui_log(f"[DetectUI] N:{n} | {ms:.1f} ms")
        except Exception as e:
            self._ui_log(f"[DetectUI] Test error: {e}")

    def _dump_current_roi(self):
        try:
            img = self.get_latest_frame()
            if img is None:
                self._ui_log("[DetectUI] No ROI")
                return
            ts = int(time.time() * 1000)
            os.makedirs("captures", exist_ok=True)
            path = os.path.join("captures", f"dump_{ts}.jpg")
            cv2.imwrite(path, img)
            self._ui_log(f"[DetectUI] Dumped {path}")
        except Exception as e:
            self._ui_log(f"[DetectUI] Dump error: {e}")

    # ----------------------- Callbacks -----------------------
    def _on_normal_x_speed_changed(self, val):
        config.normal_x_speed = val
        self.tracker.normal_x_speed = val

    def _on_normal_y_speed_changed(self, val):
        config.normal_y_speed = val
        self.tracker.normal_y_speed = val

    def _on_config_in_game_sens_changed(self, val):
        config.in_game_sens = val
        self.tracker.in_game_sens = val

    def _on_config_normal_smooth_changed(self, val):
        config.normalsmooth = val
        self.tracker.normalsmooth = val

    def _on_config_normal_smoothfov_changed(self, val):
        config.normalsmoothfov = val
        self.tracker.normalsmoothfov = val

    def _on_aim_key_changed(self):
        # Map selected names back to keys and store as a tuple
        selected = []
        for widget in (self.aim_key_1, self.aim_key_2):
            name = widget.get()
            for key, n in BUTTONS.items():
                if n == name:
                    selected.append(key)
                    break
        # Ensure uniqueness and length<=2
        if not selected:
            return
        sel = list(dict.fromkeys(selected))[:2]
        # store on config for runtime use
        config.selected_aim_keys = tuple(sel)
        self._log_config(f"Aim keys set to: {', '.join([BUTTONS[k] for k in sel])}")

    def _on_tb_button_selected(self, val):
        for key, name in BUTTONS.items():
            if name == val:
                config.selected_tb_btn = key
                # self.tracker.selected_tb_btn = val
                break
        self._log_config(f"Triggerbot button set to {val} ({key})")

    def _on_fovsize_changed(self, val):
        config.fovsize = val
        self.tracker.fovsize = val

    def _on_tbdelay_changed(self, val):
        config.tbdelay = val
        self.tracker.tbdelay = val

    def _on_tbfovsize_changed(self, val):
        config.tbfovsize = val
        self.tracker.tbfovsize = val

    def _on_enableaim_changed(self):
        config.enableaim = self.var_enableaim.get()

    def _on_enabletb_changed(self):
        config.enabletb = self.var_enabletb.get()

    def _on_source_selected(self, val):
        pass

    # Removed appearance/mode/color handlers

    # ----------------------- UDP helpers -----------------------
    def _start_udp(self):
        try:
            port_text = self.udp_port_entry.get().strip()
            port = int(port_text) if port_text else 8080
        except Exception:
            port = 8080
        try:
            if self.receiver is not None:
                self._stop_udp()
            rcvbuf = getattr(config, "viewer_rcvbuf_mb", 256)
            max_assembly = 256 * 1024 * 1024
            self.rx_store = _LatestBytesStore()
            self.decoder = _Decoder()
            self.last_decoded_seq = -1
            self.last_bgr = None
            self.receiver = _Receiver(
                "0.0.0.0", port, rcvbuf, max_assembly, self.rx_store
            )
            self.receiver.start()
            # Start display thread
            if self.display_thread is None or not self.display_thread.is_alive():
                create_mask = (
                    getattr(config, "detection", {}).get("source", "color") != "ai"
                )
                self.display_thread = DisplayThread(
                    self, self.vision_store, self.mask_store, create_mask=create_mask
                )
                self.display_thread.start()
            self.connected = True
            self.status_label.configure(
                text=f"UDP listening on :{port}", text_color="green"
            )
        except Exception as e:
            self.connected = False
            self.status_label.configure(text=f"UDP error: {e}", text_color="red")

    def _stop_udp(self):
        try:
            if self.receiver is not None:
                self.receiver.stop()
                self.receiver.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.display_thread is not None:
                self.display_thread.stop()
                self.display_thread.join(timeout=1.5)
        except Exception:
            pass
        self.receiver = None
        self.last_bgr = None
        self.connected = False
        self.status_label.configure(text="Status: Disconnected", text_color="red")

    # ----------------------- Ultrafast Viewer helpers -----------------------
    def _start_viewer(self):
        try:
            if self._viewer_proc is not None and self._viewer_proc.poll() is None:
                return
            try:
                port_text = self.udp_port_entry.get().strip()
                port = (
                    int(port_text)
                    if port_text
                    else getattr(config, "viewer_port", 8080)
                )
            except Exception:
                port = getattr(config, "viewer_port", 8080)
            args = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "upd_viewer_ultrafast.py"),
                "--port",
                str(port),
                "--rcvbuf-mb",
                str(getattr(config, "viewer_rcvbuf_mb", 256)),
                "--metrics-hz",
                str(getattr(config, "viewer_metrics_hz", 120.0)),
                "--max-display-fps",
                str(getattr(config, "viewer_max_display_fps", 240.0)),
            ]
            self._viewer_proc = subprocess.Popen(args)
        except Exception as e:
            print("[Viewer start error]", e)

    def _stop_viewer(self):
        try:
            if self._viewer_proc is not None and self._viewer_proc.poll() is None:
                self._viewer_proc.terminate()
                try:
                    self._viewer_proc.wait(timeout=1.5)
                except Exception:
                    self._viewer_proc.kill()
        except Exception:
            pass
        self._viewer_proc = None

    def _update_connection_status_loop(self):
        try:
            if self.receiver is not None:
                self.connected = True
                _, _, avg_ms, avg_fps = self.rx_store.get_latest()
                if avg_ms is not None and avg_fps is not None:
                    self.metrics_label.configure(
                        text=f"Avg: {avg_ms:.1f} ms  {avg_fps:.1f} fps"
                    )
                self.status_label.configure(text="UDP Connected", text_color="green")
            else:
                self.connected = False
                self.status_label.configure(text="Disconnected", text_color="red")
                self.metrics_label.configure(text="Avg: -- ms  -- fps")
        except Exception:
            pass
        self.after(500, self._update_connection_status_loop)

    def _on_close(self):
        try:
            self.tracker.stop()
        except Exception:
            pass
        try:
            self._stop_udp()
        except Exception:
            pass
        # Stop display thread and UDP
        self.destroy()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    # ----------------------- Frame access -----------------------
    def get_latest_frame(self):
        try:
            buf, seq, _, _ = self.rx_store.get_latest()
            if buf is None:
                return None
            if seq == self.last_decoded_seq and self.last_bgr is not None:
                return self.last_bgr
            frame = self.decoder.decode_bgr(buf)
            if frame is None or frame.size == 0:
                return None
            self.last_decoded_seq = seq
            self.last_bgr = frame
            return frame
        except Exception:
            return None


if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    try:
        ctk.set_default_color_theme("themes/metal.json")
    except Exception:
        pass
    app = ViewerApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
