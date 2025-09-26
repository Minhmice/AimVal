import customtkinter as ctk
import threading
import queue
import time
import math
import numpy as np
import cv2
import tkinter as tk
import os
import json
import subprocess
import sys
import socket
import select

from config import config
from mouse import Mouse, is_button_pressed
from detection import load_model, perform_detection

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
    def __init__(self, host: str, port: int, rcvbuf_mb: int, max_assembly_bytes: int, store: _LatestBytesStore):
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
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024)
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
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024):]
                    break
                latest = bytes(self._buffer[start:end + 2])
                del self._buffer[:end + 2]
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
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, None)
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
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, fmt, gl.GL_UNSIGNED_BYTE, ctypes.c_void_p(0))
        except Exception:
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, rgb)
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
        try:
            glfw.destroy_window(self.win)
        except Exception:
            pass


class DisplayThread(threading.Thread):
    def __init__(self, app, vision_store: SimpleFrameStore, mask_store: SimpleFrameStore):
        super().__init__(daemon=True)
        self.app = app
        self.vision_store = vision_store
        self.mask_store = mask_store
        self._stop = threading.Event()
        self.use_gl = False
        self.vision = None
        self.mask = None
        self.interval_ns = int(1e9 / MAX_DISPLAY_FPS) if MAX_DISPLAY_FPS > 0 else 0

    def stop(self):
        self._stop.set()

    def _try_init_gl(self):
        if not GL_AVAILABLE:
            return False
        try:
            self.vision = GLRendererPBO("VISION", VISION_SCALE)
            self.mask = GLRendererPBO("MASK", MASK_SCALE)
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
                if self.use_gl and self.vision and self.mask:
                    if vis is not None and vis_seq != last_vis_seq:
                        self.vision.upload_bgr_pbo(vis)
                        last_vis_seq = vis_seq
                    if msk is not None and msk_seq != last_msk_seq:
                        self.mask.upload_bgr_pbo(msk)
                        last_msk_seq = msk_seq
                    self.vision.draw(); self.mask.draw()
                    glfw.poll_events()
                    if self.vision.should_close() or self.mask.should_close():
                        break
                else:
                    # Fallback cv2
                    if vis is not None and vis_seq != last_vis_seq:
                        last_vis_seq = vis_seq
                        try:
                            disp = vis
                            if VISION_SCALE != 1.0:
                                disp = cv2.resize(disp, None, fx=VISION_SCALE, fy=VISION_SCALE, interpolation=cv2.INTER_AREA)
                            cv2.imshow("VISION", disp)
                        except Exception:
                            pass
                    if msk is not None and msk_seq != last_msk_seq:
                        last_msk_seq = msk_seq
                        try:
                            disp = msk
                            if MASK_SCALE != 1.0:
                                disp = cv2.resize(disp, None, fx=MASK_SCALE, fy=MASK_SCALE, interpolation=cv2.INTER_AREA)
                            cv2.imshow("MASK", disp)
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
        self.last_tb_click_time = 0.0

        self.in_game_sens = float(getattr(config, "in_game_sens", 7))
        self.color = getattr(config, "color", "yellow")
        self.mode = getattr(config, "mode", "Normal")
        self.selected_mouse_button = (getattr(config, "selected_mouse_button", 3),)
        self.selected_tb_btn = getattr(config, "selected_tb_btn", 3)
        self.max_speed = float(getattr(config, "max_speed", 1000.0))

        self.controller = Mouse()
        self.move_queue = queue.Queue(maxsize=50)
        self._move_thread = threading.Thread(
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()

        self.model, self.class_names = load_model()
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
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        if getattr(config, "enableaim", False):
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "fovsize", self.fovsize)),
                (255, 255, 255),
                2,
            )
            # Correct: cercle smoothing = normalsmoothFOV
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "normalsmoothfov", self.normalsmoothfov)),
                (51, 255, 255),
                2,
            )
        if getattr(config, "enabletb", False):
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "tbfovsize", self.tbfovsize)),
                (255, 255, 255),
                2,
            )

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
            detection_results, mask = perform_detection(self.model, bgr_img)
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
        if detection_results:
            for det in detection_results:
                try:
                    x, y, w, h = det["bbox"]
                    conf = det.get("confidence", 1.0)
                    x1, y1 = int(x), int(y)
                    x2, y2 = int(x + w), int(y + h)
                    y1 *= 1.03
                    # Dessin corps
                    self._draw_body(bgr_img, x1, y1, x2, y2, conf)
                    # Estimation têtes dans la bbox
                    head_positions = self._estimate_head_positions(
                        x1, y1, x2, y2, bgr_img
                    )
                    for head_cx, head_cy, bbox in head_positions:
                        self._draw_head_bbox(bgr_img, head_cx, head_cy)
                        d = math.hypot(
                            head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0
                        )
                        targets.append((head_cx, head_cy, d))
                except Exception as e:
                    print("Erreur dans _estimate_head_positions:", e)

        # FOVs une fois par frame
        try:
            self._draw_fovs(bgr_img, frame)
        except Exception:
            pass

        try:
            self._aim_and_move(targets, frame, bgr_img)
        except Exception as e:
            print("[Aim error]", e)

        # GL/cv2 display handled by DisplayThread; nothing more to do here

    def _draw_head_bbox(self, img, headx, heady):
        cv2.circle(img, (int(headx), int(heady)), 2, (0, 0, 255), -1)

    def _estimate_head_positions(self, x1, y1, x2, y2, img):
        offsetY = getattr(config, "offsetY", 0)
        offsetX = getattr(config, "offsetX", 0)

        width = x2 - x1
        height = y2 - y1

        # Crop léger
        top_crop_factor = 0.10
        side_crop_factor = 0.10

        effective_y1 = y1 + height * top_crop_factor
        effective_height = height * (1 - top_crop_factor)

        effective_x1 = x1 + width * side_crop_factor
        effective_x2 = x2 - width * side_crop_factor
        effective_width = effective_x2 - effective_x1

        center_x = (effective_x1 + effective_x2) / 2
        headx_base = center_x + effective_width * (offsetX / 100)
        heady_base = effective_y1 + effective_height * (offsetY / 100)

        pixel_marginx = 40
        pixel_marginy = 10

        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))

        roi = img[y1_roi:y2_roi, x1_roi:x2_roi]
        cv2.rectangle(img, (x1_roi, y1_roi), (x2_roi, y2_roi), (0, 0, 255), 2)

        results = []
        detections = []
        try:
            detections, mask = perform_detection(self.model, roi)
        except Exception as e:
            print("[perform_detection ROI error]", e)

        if not detections:
            # Sans détection → garder le head position avec offset
            results.append((headx_base, heady_base, (x1_roi, y1_roi, x2_roi, y2_roi)))
        else:
            for det in detections:
                x, y, w, h = det["bbox"]
                cv2.rectangle(
                    img,
                    (x1_roi + x, y1_roi + y),
                    (x1_roi + x + w, y1_roi + y + h),
                    (0, 255, 0),
                    2,
                )

                # Position détection brute
                headx_det = x1_roi + x + w / 2
                heady_det = y1_roi + y + h / 2

                # Application de l’offset aussi sur la détection
                headx_det += effective_width * (offsetX / 100)
                heady_det += effective_height * (offsetY / 100)

                results.append((headx_det, heady_det, (x1_roi + x, y1_roi + y, w, h)))

        return results

    def _draw_body(self, img, x1, y1, x2, y2, conf):
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
        cv2.putText(
            img,
            f"Body {conf:.2f}",
            (int(x1), int(y1) - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 0, 0),
            2,
        )

    def _aim_and_move(self, targets, frame, img):
        aim_enabled = getattr(config, "enableaim", False)
        selected_btn = getattr(config, "selected_mouse_button", None)

        center_x = frame.xres / 2.0
        center_y = frame.yres / 2.0
        # --- Si pas de target, on saute l'aimbot mais on continue triggerbot ---
        if not targets:
            cx, cy, distance_to_center = center_x, center_y, float("inf")
        else:
            # Sélectionne la meilleure target
            best_target = min(targets, key=lambda t: t[2])
            cx, cy, _ = best_target
            distance_to_center = math.hypot(cx - center_x, cy - center_y)
            if distance_to_center > float(getattr(config, "fovsize", self.fovsize)):
                return

        dx = cx - center_x
        dy = cy - center_y

        sens = float(getattr(config, "in_game_sens", self.in_game_sens))
        dpi = float(getattr(config, "mouse_dpi", self.mouse_dpi))

        cm_per_rev_base = 54.54
        cm_per_rev = cm_per_rev_base / max(sens, 0.01)

        count_per_cm = dpi / 2.54
        deg_per_count = 360.0 / (cm_per_rev * count_per_cm)

        ndx = dx * deg_per_count
        ndy = dy * deg_per_count

        mode = getattr(config, "mode", "Normal")
        if mode == "Normal":
            try:
                # --- AIMBOT ---
                # Aimbot triggers when any selected aim key is held
                chosen = getattr(config, "selected_aim_keys", None)
                any_held = False
                if chosen and isinstance(chosen, (list, tuple)):
                    for k in chosen:
                        try:
                            if is_button_pressed(k):
                                any_held = True
                                break
                        except Exception:
                            continue
                else:
                    # fallback to single button if configured
                    if selected_btn is not None and is_button_pressed(selected_btn):
                        any_held = True

                if aim_enabled and any_held and targets:
                    if distance_to_center < float(
                        getattr(config, "normalsmoothfov", self.normalsmoothfov)
                    ):
                        ndx *= float(
                            getattr(config, "normal_x_speed", self.normal_x_speed)
                        ) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)),
                            0.01,
                        )
                        ndy *= float(
                            getattr(config, "normal_y_speed", self.normal_y_speed)
                        ) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)),
                            0.01,
                        )
                    else:
                        ndx *= float(
                            getattr(config, "normal_x_speed", self.normal_x_speed)
                        )
                        ndy *= float(
                            getattr(config, "normal_y_speed", self.normal_y_speed)
                        )
                    ddx, ddy = self._clip_movement(ndx, ndy)
                    self.move_queue.put((ddx, ddy, 0.005))
            except Exception:
                pass

            try:
                # --- Paramètres triggerbot ---
                if (
                    getattr(config, "enabletb", False)
                    and is_button_pressed(getattr(config, "selected_tb_btn", None))
                    or is_button_pressed(getattr(config, "selected_2_tb", None))
                ):
                    # Centre de l'écran
                    cx0, cy0 = int(frame.xres // 2), int(frame.yres // 2)
                    ROI_SIZE = 5  # petit carré autour du centre
                    x1, y1 = max(cx0 - ROI_SIZE, 0), max(cy0 - ROI_SIZE, 0)
                    x2, y2 = (
                        min(cx0 + ROI_SIZE, img.shape[1]),
                        min(cy0 + ROI_SIZE, img.shape[0]),
                    )
                    roi = img[y1:y2, x1:x2]

                    if roi.size == 0:
                        return  # sécurité

                    # Conversion HSV (assure-toi que img est BGR)
                    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

                    # Plage HSV pour le violet (ajuste si nécessaire)

                    HSV_UPPER = self.model[1]
                    HSV_LOWER = self.model[0]

                    mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)

                    detected = cv2.countNonZero(mask) > 0
                    # print(f"ROI shape: {roi.shape}, NonZero pixels: {cv2.countNonZero(mask)}")

                    # Debug affichage
                    if getattr(config, "debug_show", False):
                        cv2.imshow("ROI", roi)
                        cv2.imshow("Mask", mask)
                        cv2.waitKey(1)

                    # Texte sur l'image principale
                    if detected:
                        cv2.putText(
                            img,
                            "PURPLE DETECTED",
                            (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 255),
                            2,
                        )
                        now = time.time()
                        if now - self.last_tb_click_time >= float(
                            getattr(config, "tbdelay", self.tbdelay)
                        ):
                            self.controller.click()
                            self.last_tb_click_time = now

            except Exception as e:
                print("[Triggerbot error]", e)

        elif mode == "Silent":
            if targets:  # évite crash si pas de target
                dx_raw = int(dx)
                dy_raw = int(dy)
                dx_raw *= self.normal_x_speed
                dy_raw *= self.normal_y_speed
                threading.Thread(
                    target=threaded_silent_move,
                    args=(self.controller, dx_raw, dy_raw),
                    daemon=True,
                ).start()


class ViewerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CUPSY Colorbot")
        self.geometry("400x700")

        # Dicos pour MAJ UI <-> config
        self._slider_widgets = {}  # key -> {"slider": widget, "label": widget, "min":..., "max":...}
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
        self.tab_aimbot = self.tabview.add("🎯 Aimbot")
        self.tab_tb = self.tabview.add("🔫 Triggerbot")
        self.tab_config = self.tabview.add("💾 Config")

        self._build_general_tab()
        self._build_aimbot_tab()
        self._build_tb_tab()
        self._build_config_tab()

        # Status polling
        self.after(500, self._update_connection_status_loop)
        self._load_initial_config()

    # ---------- Helpers de mapping UI ----------
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
            from detection import reload_model

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
            from detection import reload_model

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

        ctk.CTkLabel(self.tab_aimbot, text="Aim Keys (choose two)").pack(pady=5, anchor="w")
        # Two selectors for aim keys
        self.aim_key_1 = ctk.CTkOptionMenu(self.tab_aimbot, values=list(BUTTONS.values()), command=lambda v:self._on_aim_key_changed())
        self.aim_key_1.pack(pady=4, fill="x")
        self.aim_key_2 = ctk.CTkOptionMenu(self.tab_aimbot, values=list(BUTTONS.values()), command=lambda v:self._on_aim_key_changed())
        self.aim_key_2.pack(pady=4, fill="x")

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
            self.receiver = _Receiver("0.0.0.0", port, rcvbuf, max_assembly, self.rx_store)
            self.receiver.start()
            # Start display thread
            if self.display_thread is None or not self.display_thread.is_alive():
                self.display_thread = DisplayThread(self, self.vision_store, self.mask_store)
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
                port = int(port_text) if port_text else getattr(config, "viewer_port", 8080)
            except Exception:
                port = getattr(config, "viewer_port", 8080)
            args = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "upd_viewer_ultrafast.py"),
                "--port", str(port),
                "--rcvbuf-mb", str(getattr(config, "viewer_rcvbuf_mb", 256)),
                "--metrics-hz", str(getattr(config, "viewer_metrics_hz", 120.0)),
                "--max-display-fps", str(getattr(config, "viewer_max_display_fps", 240.0)),
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
                    self.metrics_label.configure(text=f"Avg: {avg_ms:.1f} ms  {avg_fps:.1f} fps")
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
