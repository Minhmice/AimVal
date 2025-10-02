# ============================
# MODULE AIMBOT - LOGIC NHẮM VÀ BẮN TỰ ĐỘNG
# ============================
# File này là module aimbot chính - xử lý logic nhắm và bắn tự động trong game
# Sử dụng AI (YOLO) để phát hiện mục tiêu và điều khiển chuột để nhắm bắn
# Hỗ trợ 2 chế độ: Normal (mượt mà) và Silent (ẩn giấu)
# Có triggerbot: tự động bắn khi phát hiện màu sắc cụ thể

import threading  # Đa luồng để xử lý song song
import time       # Thời gian và delay
import math       # Tính toán toán học (hypot, sqrt...)
import queue      # Hàng đợi để quản lý chuyển động chuột
import numpy as np  # Xử lý mảng số học
import cv2        # OpenCV để xử lý ảnh
from config import config  # Module cấu hình của ứng dụng
from mouse import Mouse, is_button_pressed  # Module điều khiển chuột
from detection import load_model, perform_detection  # Module AI detection


def threaded_silent_move(controller, dx, dy):
    """
    HÀM CHẾ ĐỘ SILENT - DI CHUYỂN ẨN GIẤU
    Chế độ Silent: di chuyển chuột đến mục tiêu, bắn, rồi di chuyển ngược lại
    để che giấu hành vi aimbot khỏi hệ thống chống cheat
    """
    controller.move(dx, dy)      # Di chuyển chuột đến vị trí mục tiêu
    time.sleep(0.001)           # Chờ 1ms để đảm bảo di chuyển hoàn tất
    controller.click()          # Click chuột để bắn
    time.sleep(0.001)           # Chờ 1ms để đảm bảo click hoàn tất
    controller.move(-dx, -dy)   # Di chuyển ngược lại vị trí ban đầu để ẩn giấu


class AimTracker:
    """
    LỚP AIMBOT CHÍNH - XỬ LÝ LOGIC NHẮM VÀ BẮN TỰ ĐỘNG
    - Phát hiện mục tiêu bằng AI (YOLO/computer vision)
    - Tính toán chuyển động chuột để nhắm vào mục tiêu
    - Hỗ trợ 2 chế độ: Normal (mượt mà) và Silent (ẩn)
    - Triggerbot: tự động bắn khi phát hiện màu sắc
    """
    def __init__(self, app, target_fps=80):
        """
        CONSTRUCTOR - KHỞI TẠO AIMBOT
        app: Tham chiếu đến ứng dụng chính
        target_fps: FPS mục tiêu cho vòng lặp tracking (mặc định 80 FPS)
        """
        self.app = app  # Tham chiếu đến ứng dụng chính để truy cập UDP stream
        
        # ========== CÁC THAM SỐ CẤU HÌNH (load từ config với giá trị mặc định) ==========
        # Tham số tốc độ và độ mượt mà
        self.normal_x_speed = float(getattr(config, "normal_x_speed", 0.5))  # Tốc độ di chuyển X chuột
        self.normal_y_speed = float(getattr(config, "normal_y_speed", 0.5))  # Tốc độ di chuyển Y chuột
        self.normalsmooth = float(getattr(config, "normalsmooth", 10))       # Độ mượt mà khi gần mục tiêu
        self.normalsmoothfov = float(getattr(config, "normalsmoothfov", 10)) # FOV áp dụng smoothing
        
        # Tham số chuột và độ nhạy
        self.mouse_dpi = float(getattr(config, "mouse_dpi", 800))            # DPI chuột
        self.in_game_sens = float(getattr(config, "in_game_sens", 7))        # Độ nhạy trong game
        self.max_speed = float(getattr(config, "max_speed", 1000.0))         # Tốc độ tối đa (giới hạn)
        
        # Tham số FOV (Field of View)
        self.fovsize = float(getattr(config, "fovsize", 300))                # Kích thước FOV aimbot (pixel)
        self.tbfovsize = float(getattr(config, "tbfovsize", 70))             # Kích thước FOV triggerbot
        
        # Tham số triggerbot
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))               # Độ trễ giữa các lần bắn (giây)
        self.last_tb_click_time = 0.0                                        # Thời điểm click cuối cùng
        self.color = getattr(config, "color", "purple")                     # Màu sắc để triggerbot phát hiện
        
        # Tham số chế độ và phím
        self.mode = getattr(config, "mode", "Normal")                        # Chế độ: Normal hoặc Silent
        self.selected_mouse_button = (getattr(config, "selected_mouse_button", 3),)  # Nút chuột aim
        self.selected_tb_btn = getattr(config, "selected_tb_btn", 3)         # Nút chuột triggerbot

        # ========== KHỞI TẠO ĐIỀU KHIỂN CHUỘT VÀ HÀNG ĐỢI ==========
        self.controller = Mouse()                    # Đối tượng điều khiển chuột
        self.move_queue = queue.Queue(maxsize=50)   # Hàng đợi chuyển động chuột (tối đa 50 lệnh)
        self._move_thread = threading.Thread(       # Luồng xử lý chuyển động chuột
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()                   # Bắt đầu luồng xử lý chuyển động

        # ========== TẢI MÔ HÌNH AI VÀ KHỞI TẠO TRACKING ==========
        self.model, self.class_names = load_model() # Load mô hình YOLO để phát hiện mục tiêu
        print("Classes:", self.class_names)         # In ra các class có thể phát hiện (person, head...)
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
        return float(clipped_dx), float(clipped_dy)  # Trả về giá trị đã giới hạn

    def _track_loop(self):
        """
        VÒNG LẶP TRACKING CHÍNH
        Chạy liên tục ở FPS cố định để xử lý từng frame
        Đảm bảo aimbot hoạt động mượt mà và ổn định
        """
        period = 1.0 / float(self._target_fps)  # Thời gian mỗi frame (1/80 = 0.0125 giây)
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
        2. Chạy AI detection để tìm mục tiêu
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
            bgr_img = img.copy()  # Copy để tránh modify ảnh gốc
        except Exception:
            return  # Lỗi lấy frame thì bỏ qua frame này

        # ========== CHẠY AI DETECTION ==========
        try:
            # Chạy AI detection (YOLO) để tìm mục tiêu trong ảnh
            detection_results, mask = perform_detection(self.model, bgr_img)
            
            # Gửi frame đến luồng hiển thị cho người dùng
            try:
                self.app.vision_store.set(bgr_img)  # Lưu ảnh gốc để hiển thị
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
            detection_results = []  # Lỗi detection thì danh sách rỗng

        # ========== XỬ LÝ KẾT QUẢ DETECTION VÀ TÌM MỤC TIÊU ==========
        targets = []  # Danh sách mục tiêu để aim (tọa độ + khoảng cách)
        if detection_results:
            for det in detection_results:  # Duyệt qua từng detection từ AI
                try:
                    x, y, w, h = det["bbox"]  # Lấy bounding box (x, y, width, height)
                    conf = det.get("confidence", 1.0)  # Lấy độ tin cậy của detection
                    x1, y1 = int(x), int(y)  # Tọa độ góc trên trái
                    x2, y2 = int(x + w), int(y + h)  # Tọa độ góc dưới phải
                    y1 *= 1.03  # Điều chỉnh vị trí Y (offset đặc biệt cho game)
                    
                    # Vẽ bounding box của cơ thể lên ảnh để debug
                    self._draw_body(bgr_img, x1, y1, x2, y2, conf)
                    
                    # Ước tính vị trí đầu trong bounding box của cơ thể
                    head_positions = self._estimate_head_positions(x1, y1, x2, y2, bgr_img)
                    for head_cx, head_cy, bbox in head_positions:
                        self._draw_head_bbox(bgr_img, head_cx, head_cy)  # Vẽ điểm đầu
                        # Tính khoảng cách từ đầu đến trung tâm màn hình
                        d = math.hypot(head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0)
                        targets.append((head_cx, head_cy, d))  # Thêm vào danh sách mục tiêu
                except Exception as e:
                    print(f"[Aimbot Head Position Error] {e}")  # In lỗi xử lý vị trí đầu

        # ========== VẼ CÁC VÒNG FOV (Field of View) ==========
        try:
            self._draw_fovs(bgr_img, frame)  # Vẽ vòng tròn FOV aimbot và triggerbot
        except Exception:
            pass  # Bỏ qua lỗi vẽ FOV, không ảnh hưởng đến chức năng

        # ========== THỰC HIỆN AIMBOT VÀ TRIGGERBOT ==========
        try:
            # Logic chính của aimbot: tính toán và thực hiện chuyển động chuột
            self._aim_and_move(targets, frame, bgr_img)
            
            # Chạy anti-recoil nếu có (bù đắp độ giật súng)
            try:
                if hasattr(self.app, 'anti_recoil'):
                    self.app.anti_recoil.tick()
            except Exception as e:
                print(f"[Aimbot Anti-Recoil Error] {e}")
        except Exception as e:
            print(f"[Aimbot Aim Error] {e}")  # In lỗi nếu có

        # Hiển thị được xử lý bởi DisplayThread; không cần làm gì thêm ở đây

    def _draw_head_bbox(self, img, headx, heady):
        """
        HÀM VẼ ĐIỂM ĐẦU
        Vẽ một chấm tròn đỏ tại vị trí đầu được phát hiện để debug
        """
        cv2.circle(img, (int(headx), int(heady)), 2, (0, 0, 255), -1)  # Vẽ chấm tròn đỏ

    def _estimate_head_positions(self, x1, y1, x2, y2, img):
        """
        HÀM ƯỚC TÍNH VỊ TRÍ ĐẦU TRONG BOUNDING BOX CỦA CƠ THỂ
        Đây là thuật toán thông minh để tìm vị trí đầu chính xác:
        1. Tính toán vùng có khả năng chứa đầu dựa trên tỷ lệ cơ thể
        2. Tạo ROI (Region of Interest) nhỏ xung quanh vùng đó
        3. Chạy AI detection lại trên ROI để tìm đầu chính xác
        4. Áp dụng offset từ config để điều chỉnh vị trí cuối cùng
        """
        # Lấy offset từ config (điều chỉnh vị trí nhắm)
        offsetY = getattr(config, "offsetY", 0)  # Offset Y (lên/xuống)
        offsetX = getattr(config, "offsetX", 0)  # Offset X (trái/phải)

        # Tính kích thước bounding box của cơ thể
        width = x2 - x1   # Chiều rộng
        height = y2 - y1  # Chiều cao

        # ========== CROP NHẸ ĐỂ TẬP TRUNG VÀO VÙNG ĐẦU ==========
        top_crop_factor = 0.10    # Cắt 10% phía trên (loại bỏ chân)
        side_crop_factor = 0.10   # Cắt 10% hai bên (tập trung vào giữa)

        # Tính vùng hiệu quả sau khi crop
        effective_y1 = y1 + height * top_crop_factor
        effective_height = height * (1 - top_crop_factor)
        effective_x1 = x1 + width * side_crop_factor
        effective_x2 = x2 - width * side_crop_factor
        effective_width = effective_x2 - effective_x1

        # ========== TÍNH VỊ TRÍ ĐẦU CƠ BẢN VỚI OFFSET ==========
        center_x = (effective_x1 + effective_x2) / 2  # Trung tâm X của vùng hiệu quả
        headx_base = center_x + effective_width * (offsetX / 100)  # Vị trí X với offset
        heady_base = effective_y1 + effective_height * (offsetY / 100)  # Vị trí Y với offset

        # ========== TẠO ROI (REGION OF INTEREST) XUNG QUANH VỊ TRÍ ĐẦU ==========
        pixel_marginx = 40  # Margin X (pixel) xung quanh vị trí đầu
        pixel_marginy = 10  # Margin Y (pixel) xung quanh vị trí đầu

        # Tính tọa độ ROI với giới hạn ảnh
        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))

        # Cắt ROI từ ảnh gốc
        roi = img[y1_roi:y2_roi, x1_roi:x2_roi]
        cv2.rectangle(img, (x1_roi, y1_roi), (x2_roi, y2_roi), (0, 0, 255), 2)  # Vẽ ROI

        # ========== CHẠY AI DETECTION LẠI TRÊN ROI ==========
        results = []
        detections = []
        try:
            detections, mask = perform_detection(self.model, roi)  # Chạy YOLO trên ROI
        except Exception as e:
            print(f"[Aimbot ROI Detection Error] {e}")

        if not detections:
            # Không tìm thấy đầu trong ROI → dùng vị trí ước tính với offset
            results.append((headx_base, heady_base, (x1_roi, y1_roi, x2_roi, y2_roi)))
        else:
            # Tìm thấy đầu trong ROI → tính vị trí chính xác
            for det in detections:
                x, y, w, h = det["bbox"]  # Bounding box của đầu trong ROI
                # Vẽ bounding box của đầu lên ảnh chính
                cv2.rectangle(
                    img,
                    (x1_roi + x, y1_roi + y),
                    (x1_roi + x + w, y1_roi + y + h),
                    (0, 255, 0),  # Màu xanh lá
                    2,
                )

                # Tính vị trí đầu từ detection trong ROI
                headx_det = x1_roi + x + w / 2  # Trung tâm X của đầu
                heady_det = y1_roi + y + h / 2  # Trung tâm Y của đầu

                # Áp dụng offset lên vị trí detection
                headx_det += effective_width * (offsetX / 100)
                heady_det += effective_height * (offsetY / 100)

                # Thêm vào kết quả
                results.append((headx_det, heady_det, (x1_roi + x, y1_roi + y, w, h)))

        return results

    def _draw_body(self, img, x1, y1, x2, y2, conf):
        """
        HÀM VẼ BOUNDING BOX CỦA CƠ THỂ
        Vẽ hình chữ nhật xanh dương quanh cơ thể được phát hiện
        Hiển thị độ tin cậy của detection để debug
        """
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)  # Vẽ hình chữ nhật xanh dương
        cv2.putText(
            img,
            f"Body {conf:.2f}",  # Hiển thị độ tin cậy
            (int(x1), int(y1) - 6),  # Vị trí text (phía trên bounding box)
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,  # Kích thước font
            (255, 0, 0),  # Màu xanh dương
            2,  # Độ dày text
        )

    def _aim_and_move(self, targets, frame, img):
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
            if distance_to_center > float(getattr(config, "fovsize", self.fovsize)):
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

        # ========== THỰC HIỆN AIMBOT THEO CHẾ ĐỘ ==========
        mode = getattr(config, "mode", "Normal")  # Lấy chế độ từ config
        if mode == "Normal":
            try:
                # ========== CHẾ ĐỘ NORMAL - AIMBOT MƯỢT MÀ ==========
                # Thực hiện aimbot nếu được bật, có phím được nhấn và có mục tiêu
                if aim_enabled and aim_pressed and targets:
                    if distance_to_center < float(getattr(config, "normalsmoothfov", self.normalsmoothfov)):
                        # Gần mục tiêu → áp dụng smoothing để mượt mà hơn
                        ndx *= float(getattr(config, "normal_x_speed", self.normal_x_speed)) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)), 0.01
                        )
                        ndy *= float(getattr(config, "normal_y_speed", self.normal_y_speed)) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)), 0.01
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
                    
                    # Tạo ROI nhỏ ở trung tâm màn hình (nơi crosshair)
                    cx0, cy0 = int(frame.xres // 2), int(frame.yres // 2)  # Trung tâm màn hình
                    ROI_SIZE = 5  # Kích thước ROI nhỏ (5x5 pixel)
                    x1, y1 = max(cx0 - ROI_SIZE, 0), max(cy0 - ROI_SIZE, 0)
                    x2, y2 = (min(cx0 + ROI_SIZE, img.shape[1]), min(cy0 + ROI_SIZE, img.shape[0]))
                    roi = img[y1:y2, x1:x2]  # Cắt ROI từ ảnh

                    if roi.size == 0:
                        return  # ROI rỗng → bỏ qua

                    # Chuyển đổi sang HSV để phát hiện màu sắc
                    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

                    # Lấy ngưỡng màu từ model (đã được train)
                    HSV_UPPER = self.model[1]  # Ngưỡng màu trên
                    HSV_LOWER = self.model[0]  # Ngưỡng màu dưới

                    # Tạo mask để phát hiện màu sắc
                    mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)
                    detected = cv2.countNonZero(mask) > 0  # Có pixel màu target không?

                    # Debug: hiển thị ROI và mask nếu được bật
                    if getattr(config, "debug_show", False):
                        cv2.imshow("ROI", roi)
                        cv2.imshow("Mask", mask)
                        cv2.waitKey(1)

                    # Nếu phát hiện màu sắc → tự động bắn
                    if detected:
                        cv2.putText(img, "PURPLE DETECTED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        now = time.time()
                        # Kiểm tra delay để tránh bắn quá nhanh
                        if now - self.last_tb_click_time >= float(getattr(config, "tbdelay", self.tbdelay)):
                            self.controller.click()  # Bắn
                            self.last_tb_click_time = now  # Cập nhật thời gian bắn cuối

            except Exception as e:
                print(f"[Aimbot Triggerbot Error] {e}")

        elif mode == "Silent":
            # ========== CHẾ ĐỘ SILENT - AIMBOT ẨN GIẤU ==========
            if aim_enabled and aim_pressed and targets:  # Kiểm tra phím và mục tiêu
                dx_raw = int(dx)  # Chuyển thành int
                dy_raw = int(dy)  # Chuyển thành int
                dx_raw *= self.normal_x_speed  # Áp dụng tốc độ
                dy_raw *= self.normal_y_speed  # Áp dụng tốc độ
                # Chạy trong luồng riêng để không block luồng chính
                threading.Thread(
                    target=threaded_silent_move,  # Hàm di chuyển ẩn giấu
                    args=(self.controller, dx_raw, dy_raw),
                    daemon=True,
                ).start()

    def _draw_fovs(self, img, frame):
        """
        HÀM VẼ CÁC VÒNG FOV (FIELD OF VIEW)
        Vẽ vòng tròn FOV aimbot và triggerbot lên ảnh để người dùng thấy phạm vi hoạt động
        """
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        
        # Vẽ vòng tròn FOV aimbot (màu xanh lá)
        aimbot_fov = int(getattr(config, "fovsize", self.fovsize))
        cv2.circle(img, (center_x, center_y), aimbot_fov, (0, 255, 0), 2)
        
        # Vẽ vòng tròn FOV triggerbot (màu đỏ)
        triggerbot_fov = int(getattr(config, "tbfovsize", self.tbfovsize))
        cv2.circle(img, (center_x, center_y), triggerbot_fov, (0, 0, 255), 2)
        
        # Vẽ crosshair ở trung tâm
        cv2.line(img, (center_x - 10, center_y), (center_x + 10, center_y), (255, 255, 255), 1)
        cv2.line(img, (center_x, center_y - 10), (center_x, center_y + 10), (255, 255, 255), 1)
