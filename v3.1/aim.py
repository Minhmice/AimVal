# ============================
# MODULE AIMBOT - LOGIC NHẮM VÀ BẮN TỰ ĐỘNG
# ============================
# File này là module aimbot chính - xử lý logic nhắm và bắn tự động trong game
# Sử dụng AI (YOLO) để phát hiện mục tiêu và điều khiển chuột để nhắm bắn
# Aimbot mượt mà với smoothing
# Có triggerbot: tự động bắn khi phát hiện màu sắc cụ thể

import threading  # Đa luồng để xử lý song song
import time       # Thời gian và delay
import math       # Tính toán toán học (hypot, sqrt...)
import queue      # Hàng đợi để quản lý chuyển động chuột
import numpy as np  # Xử lý mảng số học
import cv2        # OpenCV để xử lý ảnh
from config import config  # Module cấu hình của ứng dụng
from mouse import Mouse, is_button_pressed  # Module điều khiển chuột


class AimTracker:
    """
    LỚP AIMBOT CHÍNH - XỬ LÝ LOGIC NHẮM VÀ BẮN TỰ ĐỘNG
    - Phát hiện mục tiêu bằng AI (YOLO/computer vision)
    - Tính toán chuyển động chuột để nhắm vào mục tiêu
    - Aimbot mượt mà với smoothing
    - Triggerbot: tự động bắn khi phát hiện màu sắc
    """
    def __init__(self, app, detection_engine, target_fps=80):
        """
        CONSTRUCTOR - KHỞI TẠO AIMBOT
        app: Tham chiếu đến ứng dụng chính
        detection_engine: DetectionEngine để lấy kết quả detection
        target_fps: FPS mục tiêu cho vòng lặp tracking (mặc định 80 FPS)
        """
        self.app = app  # Tham chiếu đến ứng dụng chính để truy cập UDP stream
        self.detection_engine = detection_engine  # DetectionEngine để lấy kết quả detection
        
        # ========== CÁC THAM SỐ CẤU HÌNH (load từ config với giá trị mặc định) ==========
        # Tham số tốc độ và độ mượt mà
        self.normal_x_speed = float(getattr(config, "normal_x_speed", 0.5))    # Tốc độ di chuyển X chuột
        self.normal_y_speed = float(getattr(config, "normal_y_speed", 0.5))    # Tốc độ di chuyển Y chuột
        self.normalsmooth = int(getattr(config, "normalsmooth", 10))         # Độ mượt mà khi gần mục tiêu
        self.normalsmoothfov = int(getattr(config, "normalsmoothfov", 10))   # FOV áp dụng smoothing
        
        # Tham số chuột và độ nhạy
        self.mouse_dpi = int(getattr(config, "mouse_dpi", 800))              # DPI chuột
        self.in_game_sens = float(getattr(config, "in_game_sens", 7))        # Độ nhạy trong game
        self.max_speed = int(getattr(config, "max_speed", 1000))             # Tốc độ tối đa (giới hạn)
        
        # Tham số FOV (Field of View)
        self.fovsize = int(getattr(config, "fovsize", 300))                  # Kích thước FOV aimbot (pixel)
        self.tbfovsize = int(getattr(config, "tbfovsize", 70))               # Kích thước FOV triggerbot
        
        # Tham số triggerbot
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))               # Độ trễ giữa các lần bắn (giây)
        self.last_tb_click_time = 0                                          # Thời điểm click cuối cùng
        self.color = getattr(config, "color", "purple")                     # Màu sắc để triggerbot phát hiện
        
        # Tham số phím
        self.selected_mouse_button = (getattr(config, "selected_mouse_button", 3),)  # Nút chuột aim
        self.selected_tb_btn = getattr(config, "selected_tb_btn", 3)         # Nút chuột triggerbot

        # ========== KHỞI TẠO ĐIỀU KHIỂN CHUỘT VÀ HÀNG ĐỢI ==========
        self.controller = Mouse()                    # Đối tượng điều khiển chuột
        self.move_queue = queue.Queue(maxsize=50)   # Hàng đợi chuyển động chuột (tối đa 50 lệnh)
        self._move_thread = threading.Thread(       # Luồng xử lý chuyển động chuột
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()                   # Bắt đầu luồng xử lý chuyển động

        # ========== KHỞI TẠO TRACKING (KHÔNG CẦN LOAD MODEL NỮA) ==========
        self._stop_event = threading.Event()        # Sự kiện dừng luồng tracking
        self._target_fps = target_fps               # FPS mục tiêu cho vòng lặp tracking
        self._track_thread = threading.Thread(      # Luồng tracking chính
            target=self._track_loop, daemon=True
        )
        self._track_thread.start()                  # Bắt đầu luồng tracking

    def stop(self):
        """
        HÀM DỪNG AIMBOT
        Dừng tất cả các luồng và giải phóng tài nguyên
        """
        self._stop_event.set()  # Báo hiệu dừng luồng tracking
        try:
            self._track_thread.join(timeout=1.0)  # Chờ luồng tracking dừng (tối đa 1 giây)
        except Exception:
            pass  # Bỏ qua lỗi nếu luồng không dừng được

    def _process_move_queue(self):
        """
        LUỒNG XỬ LÝ HÀNG ĐỢI CHUYỂN ĐỘNG CHUỘT
        Chạy liên tục để xử lý các lệnh di chuyển chuột từ hàng đợi
        Đảm bảo chuyển động chuột mượt mà và không bị block
        """
        while True:
            try:
                # Lấy lệnh di chuyển từ hàng đợi (chờ tối đa 0.1 giây)
                dx, dy, delay = self.move_queue.get(timeout=0.1)
                try:
                    self.controller.move(dx, dy)  # Thực hiện di chuyển chuột
                except Exception as e:
                    print(f"[Aimbot Mouse Error] {e}")  # In lỗi nếu không di chuyển được
                if delay and delay > 0:
                    time.sleep(delay)  # Chờ nếu có delay được yêu cầu
            except queue.Empty:
                time.sleep(0.001)  # Hàng đợi trống, chờ 1ms rồi thử lại
                continue
            except Exception as e:
                print(f"[Aimbot Queue Error] {e}")  # In lỗi xử lý hàng đợi
                time.sleep(0.01)  # Chờ 10ms trước khi thử lại

    def _clip_movement(self, dx, dy):
        """
        HÀM GIỚI HẠN TỐC ĐỘ CHUYỂN ĐỘNG
        Đảm bảo chuyển động chuột không vượt quá tốc độ tối đa cho phép
        Tránh chuyển động quá nhanh có thể bị phát hiện
        """
        clipped_dx = np.clip(dx, -abs(self.max_speed), abs(self.max_speed))  # Giới hạn X
        clipped_dy = np.clip(dy, -abs(self.max_speed), abs(self.max_speed))  # Giới hạn Y
        return int(clipped_dx), int(clipped_dy)  # Trả về giá trị đã giới hạn

    def _track_loop(self):
        """
        VÒNG LẶP TRACKING CHÍNH
        Chạy liên tục ở FPS cố định để xử lý từng frame
        Đảm bảo aimbot hoạt động mượt mà và ổn định
        """
        period = 1.0 / int(self._target_fps)  # Thời gian mỗi frame (1/80 = 0.0125 giây)
        while not self._stop_event.is_set():    # Chạy cho đến khi được báo dừng
            start = time.time()                 # Ghi nhận thời điểm bắt đầu xử lý
            try:
                self.track_once()              # Xử lý 1 frame (phát hiện + aim)
            except Exception as e:
                print(f"[Aimbot Error] {e}")   # In lỗi nếu có
            elapsed = time.time() - start       # Tính thời gian đã xử lý
            to_sleep = period - elapsed         # Tính thời gian cần chờ để đạt FPS mục tiêu
            if to_sleep > 0:
                time.sleep(to_sleep)           # Chờ để đảm bảo FPS ổn định

    def track_once(self):
        """
        HÀM TRACKING CHÍNH - XỬ LÝ MỘT FRAME
        Đây là hàm cốt lõi của aimbot, xử lý từng frame:
        1. Lấy frame mới nhất từ UDP stream
        2. Lấy kết quả detection từ DetectionEngine
        3. Tính toán và thực hiện chuyển động chuột
        4. Cập nhật hiển thị cho người dùng
        """
        # ========== KIỂM TRA KẾT NỐI UDP ==========
        if not getattr(self.app, "connected", False):
            return  # Không kết nối UDP thì bỏ qua frame này

        # ========== LẤY FRAME TỪ UDP STREAM ==========
        try:
            img = self.app.get_latest_frame()  # Lấy frame mới nhất từ UDP receiver
            if img is None:
                return  # Không có frame thì bỏ qua
            h, w = img.shape[:2]  # Lấy kích thước ảnh (height, width)
            # Tạo object thông tin frame nhẹ với thuộc tính xres/yres để tương thích
            frame = type("FrameInfo", (), {"xres": w, "yres": h})()
        except Exception:
            return  # Lỗi lấy frame thì bỏ qua frame này

        # ========== LẤY KẾT QUẢ DETECTION TỪ DETECTION ENGINE ==========
        try:
            # Lấy kết quả detection từ DetectionEngine (đã được xử lý)
            detection_data = self.detection_engine.detect_and_track(img, frame)
            
            # Trích xuất dữ liệu từ kết quả detection
            targets = detection_data['targets']  # Danh sách mục tiêu cho aimbot
            detection_results = detection_data['detection_results']  # Kết quả detection gốc
            mask = detection_data['mask']  # Mask để hiển thị
            center_detection = detection_data['center_detection']  # Có phát hiện ở trung tâm không
            img_with_overlays = detection_data['img']  # Ảnh đã vẽ overlay
            
            # Gửi frame đến luồng hiển thị cho người dùng
            try:
                self.app.vision_store.set(img_with_overlays)  # Lưu ảnh đã vẽ overlay
                # Đảm bảo mask là 3-channel BGR cho OpenGL rendering
                if mask is not None and len(mask.shape) == 2:
                    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)  # Chuyển grayscale thành BGR
                else:
                    mask_bgr = mask
                self.app.mask_store.set(mask_bgr)  # Lưu mask để hiển thị
            except Exception:
                pass  # Bỏ qua lỗi hiển thị, không ảnh hưởng đến aimbot
        except Exception as e:
            print(f"[Aimbot Detection Error] {e}")  # In lỗi detection
            targets = []  # Lỗi detection thì danh sách rỗng
            center_detection = False

        # ========== THỰC HIỆN AIMBOT VÀ TRIGGERBOT ==========
        try:
            # Logic chính của aimbot: tính toán và thực hiện chuyển động chuột
            self._aim_and_move(targets, frame, img, center_detection)
            
            # Chạy anti-recoil nếu có (bù đắp độ giật súng)
            try:
                if hasattr(self.app, 'anti_recoil'):
                    self.app.anti_recoil.tick()
            except Exception as e:
                print(f"[Aimbot Anti-Recoil Error] {e}")
        except Exception as e:
            print(f"[Aimbot Aim Error] {e}")  # In lỗi nếu có

        # Hiển thị được xử lý bởi DisplayThread; không cần làm gì thêm ở đây


    def _aim_and_move(self, targets, frame, img, center_detection=False):
        """
        HÀM LOGIC AIMBOT VÀ TRIGGERBOT CHÍNH
        Đây là trái tim của aimbot, xử lý:
        1. Chọn mục tiêu gần nhất
        2. Tính toán chuyển động chuột
        3. Thực hiện aimbot (Normal/Silent)
        4. Thực hiện triggerbot (tự động bắn)
        """
        # ========== LẤY CẤU HÌNH VÀ TÍNH TOÁN CƠ BẢN ==========
        aim_enabled = getattr(config, "enableaim", False)  # Aimbot có được bật không
        # Kiểm tra phím aim (2 phím)
        aim_pressed = (is_button_pressed(getattr(config, "aim_button_1", 1)) or 
                      is_button_pressed(getattr(config, "aim_button_2", 2)))

        center_x = frame.xres / 2.0  # Trung tâm màn hình X
        center_y = frame.yres / 2.0  # Trung tâm màn hình Y
        
        # ========== CHỌN MỤC TIÊU TỐT NHẤT ==========
        if not targets:
            # Không có mục tiêu → dùng trung tâm màn hình
            cx, cy, distance_to_center = center_x, center_y, float("inf")
        else:
            # Chọn mục tiêu gần trung tâm màn hình nhất
            best_target = min(targets, key=lambda t: t[2])  # t[2] là khoảng cách
            cx, cy, _ = best_target
            distance_to_center = math.hypot(cx - center_x, cy - center_y)
            # Kiểm tra mục tiêu có trong FOV không
            if distance_to_center > int(getattr(config, "fovsize", self.fovsize)):
                return  # Mục tiêu ngoài FOV → bỏ qua

        # ========== TÍNH TOÁN KHOẢNG CÁCH CẦN DI CHUYỂN ==========
        dx = cx - center_x  # Khoảng cách X cần di chuyển (pixel)
        dy = cy - center_y  # Khoảng cách Y cần di chuyển (pixel)

        # ========== CHUYỂN ĐỔI PIXEL THÀNH COUNT CHUỘT ==========
        sens = float(getattr(config, "in_game_sens", self.in_game_sens))  # Độ nhạy trong game
        dpi = float(getattr(config, "mouse_dpi", self.mouse_dpi))         # DPI chuột

        # Công thức chuyển đổi từ pixel sang count chuột
        cm_per_rev_base = 54.54  # Cm chuột cần để quay 360 độ (giá trị chuẩn)
        cm_per_rev = cm_per_rev_base / max(sens, 0.01)  # Điều chỉnh theo sensitivity
        count_per_cm = dpi / 2.54  # Count chuột trên mỗi cm
        deg_per_count = 360.0 / (cm_per_rev * count_per_cm)  # Độ trên mỗi count

        # Chuyển đổi pixel thành count chuột
        ndx = dx * deg_per_count  # Count X cần di chuyển
        ndy = dy * deg_per_count  # Count Y cần di chuyển

        # ========== THỰC HIỆN AIMBOT ==========
        try:
            # ========== AIMBOT MƯỢT MÀ ==========
            # Thực hiện aimbot nếu được bật, có phím được nhấn và có mục tiêu
            if aim_enabled and aim_pressed and targets:
                if distance_to_center < int(getattr(config, "normalsmoothfov", self.normalsmoothfov)):
                    # Gần mục tiêu → áp dụng smoothing để mượt mà hơn
                    ndx *= float(getattr(config, "normal_x_speed", self.normal_x_speed)) / max(
                        int(getattr(config, "normalsmooth", self.normalsmooth)), 1
                    )
                    ndy *= float(getattr(config, "normal_y_speed", self.normal_y_speed)) / max(
                        int(getattr(config, "normalsmooth", self.normalsmooth)), 1
                    )
                else:
                    # Xa mục tiêu → không smoothing, di chuyển nhanh
                    ndx *= float(getattr(config, "normal_x_speed", self.normal_x_speed))
                    ndy *= float(getattr(config, "normal_y_speed", self.normal_y_speed))
                
                # Giới hạn tốc độ và thêm vào hàng đợi
                ddx, ddy = self._clip_movement(ndx, ndy)
                self.move_queue.put((ddx, ddy, 0.005))  # Thêm delay 5ms
        except Exception:
            pass  # Bỏ qua lỗi aimbot

        try:
            # ========== TRIGGERBOT - TỰ ĐỘNG BẮN KHI PHÁT HIỆN MÀU SẮC ==========
            # Kiểm tra triggerbot có được bật và phím có được nhấn không
            if (getattr(config, "enabletb", False) and 
                is_button_pressed(getattr(config, "trigger_button", 1))):
                
                # Sử dụng kết quả detection từ DetectionEngine (không cần detect riêng)
                if center_detection:
                    # Có phát hiện màu sắc ở trung tâm → tự động bắn
                    now = time.time()
                    # Kiểm tra delay để tránh bắn quá nhanh
                    if now - self.last_tb_click_time >= float(getattr(config, "tbdelay", self.tbdelay)):
                        self.controller.click()  # Bắn
                        self.last_tb_click_time = now  # Cập nhật thời gian bắn cuối

        except Exception as e:
            print(f"[Aimbot Triggerbot Error] {e}")