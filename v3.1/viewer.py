# ============================
# MODULE VIEWER - UDP RECEIVER, DECODER VÀ OPENGL RENDERER
# ============================
import threading
import time
import socket
import select
import numpy as np
import cv2

# Thử import OpenGL libraries - nếu không có sẽ fallback về OpenCV
try:
    import glfw  # type: ignore  # GLFW - tạo cửa sổ OpenGL
    from OpenGL import GL as gl  # type: ignore  # OpenGL bindings
    GL_AVAILABLE = True  # Có thể sử dụng OpenGL
except Exception:
    glfw = None
    gl = None
    GL_AVAILABLE = False  # Không có OpenGL, dùng OpenCV

# Các hằng số cho định dạng JPEG
SOI = b"\xff\xd8"  # Start of Image - bắt đầu file JPEG
EOI = b"\xff\xd9"  # End of Image - kết thúc file JPEG
RECV_TMP_BYTES = 262140  # Kích thước buffer tạm để nhận dữ liệu UDP

# Các hằng số hiển thị
VISION_SCALE = 2.0  # Tỷ lệ phóng to cửa sổ VISION
MASK_SCALE = 2.0  # Tỷ lệ phóng to cửa sổ MASK  
MAX_DISPLAY_FPS = 240.0  # FPS tối đa cho hiển thị


class _LatestBytesStore:
    """
    Lớp lưu trữ dữ liệu video mới nhất từ UDP stream
    - Thread-safe: an toàn khi nhiều luồng truy cập đồng thời
    - Theo dõi metrics: FPS, thời gian xử lý, số packet nhận được
    """
    def __init__(self):
        self._lock = threading.Lock()  # Khóa để đồng bộ hóa truy cập
        self._buf = None  # Buffer chứa dữ liệu JPEG mới nhất
        self._seq = 0  # Số thứ tự frame để tránh xử lý trùng lặp
        # Các chỉ số thống kê hiệu suất
        self.packets_received = 0  # Tổng số packet UDP đã nhận
        self.bytes_received = 0  # Tổng số byte đã nhận
        self.frames_total = 0  # Tổng số frame đã xử lý
        self.first_frame_ns = None  # Thời điểm frame đầu tiên (nanosecond)
        self.prev_frame_ns = None  # Thời điểm frame trước đó
        self.last_frame_ns = None  # Thời điểm frame cuối cùng
        self.rt_ms = None  # Thời gian xử lý real-time (millisecond)
        self.rt_fps = 0.0  # FPS real-time
        self.avg_ms = None  # Thời gian xử lý trung bình
        self.avg_fps = 0.0  # FPS trung bình

    def set_latest(self, data: bytes, now_ns: int):
        """
        Lưu trữ frame mới nhất và cập nhật thống kê hiệu suất
        - data: dữ liệu JPEG của frame
        - now_ns: thời điểm hiện tại (nanosecond)
        """
        with self._lock:
            self._buf = data  # Lưu dữ liệu frame
            self._seq += 1  # Tăng số thứ tự frame
            if self.first_frame_ns is None:
                self.first_frame_ns = now_ns  # Ghi nhận frame đầu tiên
            if self.prev_frame_ns is not None:
                dt_ns = now_ns - self.prev_frame_ns  # Khoảng thời gian giữa 2 frame
                if dt_ns > 0:
                    self.rt_ms = dt_ns / 1e6  # Chuyển nanosecond thành millisecond
                    self.rt_fps = 1e9 / dt_ns  # Tính FPS real-time
            self.prev_frame_ns = now_ns
            self.last_frame_ns = now_ns
            self.frames_total += 1
            # Tính toán thống kê trung bình
            if self.first_frame_ns is not None and self.frames_total > 0:
                total_ns = now_ns - self.first_frame_ns
                if total_ns > 0:
                    self.avg_ms = (total_ns / self.frames_total) / 1e6  # Thời gian trung bình
                    self.avg_fps = self.frames_total / (total_ns / 1e9)  # FPS trung bình

    def account_packet(self, nbytes: int):
        """Ghi nhận packet UDP mới nhận được"""
        with self._lock:
            self.packets_received += 1
            self.bytes_received += nbytes

    def get_latest(self):
        """Lấy frame mới nhất và thống kê hiệu suất"""
        with self._lock:
            return self._buf, self._seq, self.avg_ms, self.avg_fps


class _Receiver(threading.Thread):
    """
    Luồng nhận dữ liệu UDP video stream
    - Chạy trong background (daemon thread)
    - Ghép nối các packet UDP thành frame JPEG hoàn chỉnh
    - Xử lý non-blocking để tránh lag
    """
    def __init__(self, host: str, port: int, rcvbuf_mb: int, max_assembly_bytes: int, store: _LatestBytesStore):
        super().__init__(daemon=True)  # Luồng daemon - tự kết thúc khi chương trình chính kết thúc
        self.host = host  # Địa chỉ IP để bind (thường là "0.0.0.0")
        self.port = int(port)  # Cổng UDP để lắng nghe
        self.rcvbuf_mb = max(1, int(rcvbuf_mb))  # Kích thước buffer nhận (MB)
        self.max_assembly_bytes = max(2 * 1024 * 1024, int(max_assembly_bytes))  # Kích thước tối đa để ghép frame
        self.store = store  # Nơi lưu trữ frame đã ghép xong
        self._stop = threading.Event()  # Sự kiện để dừng luồng
        self._buffer = bytearray()  # Buffer để ghép các packet UDP
        self._tmp = bytearray(RECV_TMP_BYTES)  # Buffer tạm để nhận packet
        self._tmp_mv = memoryview(self._tmp)  # Memory view để tối ưu hiệu suất
        self.sock = None  # Socket UDP

    def stop(self):
        """Dừng luồng nhận UDP"""
        self._stop.set()

    def _open_socket(self):
        """
        Tạo và cấu hình socket UDP
        - Tăng kích thước buffer nhận để xử lý video tốc độ cao
        - Cho phép tái sử dụng địa chỉ (SO_REUSEADDR)
        - Non-blocking mode để không bị treo
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Tạo socket UDP
        try:
            # Tăng kích thước buffer nhận để xử lý video tốc độ cao
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024)
        except OSError:
            pass  # Bỏ qua nếu không thể set buffer size
        try:
            # Cho phép tái sử dụng địa chỉ (quan trọng khi restart nhanh)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        sock.bind((self.host, self.port))  # Bind vào địa chỉ và cổng
        sock.setblocking(False)  # Non-blocking mode để không bị treo
        return sock

    def run(self):
        """
        Vòng lặp chính của luồng nhận UDP
        - Nhận packet UDP và ghép thành frame JPEG
        - Xử lý non-blocking để tránh lag
        - Tự động dọn dẹp buffer khi quá lớn
        """
        self.sock = self._open_socket()
        while not self._stop.is_set():
            # Kiểm tra có dữ liệu để đọc không (timeout 1ms)
            rlist, _, _ = select.select([self.sock], [], [], 0.001)
            # Đọc tất cả packet có sẵn
            while rlist and not self._stop.is_set():
                try:
                    nbytes, _ = self.sock.recvfrom_into(self._tmp_mv)  # Nhận packet vào buffer tạm
                    if nbytes <= 0:
                        break
                    self._buffer.extend(self._tmp_mv[:nbytes])  # Thêm vào buffer chính
                    self.store.account_packet(nbytes)  # Ghi nhận packet
                except BlockingIOError:
                    break  # Không có dữ liệu để đọc
                except Exception:
                    break  # Lỗi khác
                rlist, _, _ = select.select([self.sock], [], [], 0.0)  # Kiểm tra lại ngay

            # Ghép các packet thành frame JPEG hoàn chỉnh
            latest = None
            latest_time_ns = None
            while True:
                start = self._buffer.find(SOI)  # Tìm bắt đầu frame JPEG
                if start == -1:
                    # Không tìm thấy SOI, dọn dẹp nếu buffer quá lớn
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer.clear()
                    break
                end = self._buffer.find(EOI, start + 2)  # Tìm kết thúc frame JPEG
                if end == -1:
                    # Không tìm thấy EOI, giữ lại phần cuối buffer
                    if len(self._buffer) > self.max_assembly_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024):]
                    break
                # Trích xuất frame JPEG hoàn chỉnh
                latest = bytes(self._buffer[start:end + 2])
                del self._buffer[:end + 2]  # Xóa frame đã xử lý khỏi buffer
                latest_time_ns = time.monotonic_ns()  # Ghi nhận thời điểm

            # Lưu frame mới nhất vào store
            if latest is not None and latest_time_ns is not None:
                self.store.set_latest(latest, latest_time_ns)

        # Dọn dẹp khi kết thúc
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


class _Decoder:
    """
    Lớp giải mã JPEG thành ảnh BGR
    - Ưu tiên sử dụng TurboJPEG (nhanh hơn) nếu có
    - Fallback về OpenCV nếu không có TurboJPEG
    """
    def __init__(self):
        self.use_turbo = False  # Có sử dụng TurboJPEG không
        self.tj = None  # Đối tượng TurboJPEG
        try:
            from turbojpeg import TurboJPEG  # type: ignore
            try:
                self.tj = TurboJPEG()  # Khởi tạo TurboJPEG
                self.use_turbo = True  # Đánh dấu có thể sử dụng
            except Exception:
                self.tj = None
                self.use_turbo = False  # Không thể khởi tạo TurboJPEG
        except Exception:
            self.tj = None
            self.use_turbo = False  # Không có thư viện TurboJPEG

    def decode_bgr(self, jpeg_bytes):
        """
        Giải mã dữ liệu JPEG thành ảnh BGR
        - jpeg_bytes: dữ liệu JPEG dạng bytes
        - Trả về: ảnh BGR (numpy array) hoặc None nếu lỗi
        """
        try:
            if self.use_turbo and self.tj is not None:
                return self.tj.decode(jpeg_bytes)  # Sử dụng TurboJPEG (nhanh hơn)
            # Fallback về OpenCV
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)  # Chuyển bytes thành numpy array
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # Giải mã JPEG thành BGR
            return img
        except Exception:
            return None  # Lỗi giải mã


class SimpleFrameStore:
    """
    Lớp lưu trữ frame đơn giản cho hiển thị
    - Thread-safe: an toàn khi nhiều luồng truy cập
    - Lưu trữ ảnh và số thứ tự để tránh hiển thị trùng lặp
    """
    def __init__(self):
        self._lock = threading.Lock()  # Khóa đồng bộ hóa
        self._seq = 0  # Số thứ tự frame
        self._arr = None  # Dữ liệu ảnh (numpy array)

    def set(self, arr):
        """Lưu frame mới"""
        with self._lock:
            self._arr = arr  # Lưu ảnh
            self._seq += 1  # Tăng số thứ tự

    def get(self):
        """Lấy frame hiện tại và số thứ tự"""
        with self._lock:
            return self._arr, self._seq


class GLRendererPBO:
    """
    Bộ renderer OpenGL sử dụng Pixel Buffer Object (PBO)
    - Hiệu suất cao cho việc hiển thị video real-time
    - Sử dụng PBO để tối ưu upload texture
    - Hỗ trợ scaling và anti-aliasing
    """
    def __init__(self, title: str, scale: float):
        # Khởi tạo GLFW
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        # Cấu hình OpenGL context
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)  # OpenGL 2.1
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
        glfw.window_hint(glfw.RESIZABLE, True)  # Cho phép thay đổi kích thước

        # Tạo cửa sổ OpenGL
        self.win = glfw.create_window(640, 480, title, None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        glfw.make_context_current(self.win)  # Kích hoạt context
        glfw.swap_interval(0)  # Tắt VSync để có FPS cao nhất

        # Cấu hình OpenGL state
        gl.glDisable(gl.GL_DEPTH_TEST)  # Tắt depth test (2D rendering)
        gl.glEnable(gl.GL_TEXTURE_2D)  # Bật texture 2D
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)  # Cấu hình pixel alignment

        # Tạo texture để hiển thị ảnh
        self.tex_id = gl.glGenTextures(1)  # Tạo texture ID
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex_id)  # Bind texture
        # Cấu hình filtering
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)  # Unbind

        # Tạo 2 PBO để double buffering
        self.pbo_ids = gl.glGenBuffers(2)  # Tạo 2 PBO IDs
        self.pbo_index = 0  # Index của PBO hiện tại
        self.tex_w = 0  # Chiều rộng texture
        self.tex_h = 0  # Chiều cao texture
        # Kiểm tra khả năng của OpenGL
        self.have_map_range = hasattr(gl, "glMapBufferRange")  # Có glMapBufferRange không
        self.use_bgr = hasattr(gl, "GL_BGR")  # Có hỗ trợ BGR không
        self.scale = float(scale) if scale and scale > 0 else 1.0  # Tỷ lệ phóng to

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
