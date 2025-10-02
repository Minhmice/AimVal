# ============================
# MODULE ESP - DETECTION ENGINE VÀ VẼ FOV
# ============================
import cv2
import numpy as np
import math
import time
from config import config
from detection import load_model, perform_detection


def draw_fov_circles(img, frame):
    """
    VẼ CÁC VÒNG TRÒN FOV (Field of View)
    - Vòng tròn aimbot (màu trắng)
    - Vòng tròn smoothing (màu vàng)
    - Vòng tròn triggerbot (màu trắng)
    """
    center_x = int(frame.xres / 2)
    center_y = int(frame.yres / 2)
    
    # Vẽ vòng tròn FOV aimbot
    if getattr(config, "enableaim", False):
        fov_size = int(getattr(config, "fovsize", 300))
        cv2.circle(
            img,
            (center_x, center_y),
            fov_size,
            (255, 255, 255),  # Màu trắng
            2,
        )
        # Vòng tròn smoothing (nhỏ hơn)
        smooth_fov = int(getattr(config, "normalsmoothfov", 10))
        cv2.circle(
            img,
            (center_x, center_y),
            smooth_fov,
            (51, 255, 255),  # Màu vàng
            2,
        )
    
    # Vẽ vòng tròn FOV triggerbot
    if getattr(config, "enabletb", False):
        tb_fov_size = int(getattr(config, "tbfovsize", 70))
        cv2.circle(
            img,
            (center_x, center_y),
            tb_fov_size,
            (255, 255, 255),  # Màu trắng
            2,
        )


def draw_body_bbox(img, x1, y1, x2, y2, conf):
    """
    VẼ BOUNDING BOX CỦA CƠ THỂ
    - Hình chữ nhật màu xanh dương
    - Hiển thị độ tin cậy
    """
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


def draw_head_bbox(img, headx, heady):
    """
    VẼ ĐIỂM ĐẦU MỤC TIÊU
    - Chấm tròn màu đỏ tại vị trí đầu
    """
    cv2.circle(img, (int(headx), int(heady)), 2, (0, 0, 255), -1)


def draw_roi_rectangle(img, x1, y1, x2, y2, color=(0, 0, 255)):
    """
    VẼ HÌNH CHỮ NHẬT ROI (Region of Interest)
    - Màu đỏ mặc định
    - Dùng để hiển thị vùng kiểm tra triggerbot
    """
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)


def draw_detection_rectangle(img, x1, y1, x2, y2, color=(0, 255, 0)):
    """
    VẼ HÌNH CHỮ NHẬT PHÁT HIỆN
    - Màu xanh lá mặc định
    - Dùng để hiển thị vùng phát hiện màu sắc
    """
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)


def draw_triggerbot_status(img, detected):
    """
    VẼ TRẠNG THÁI TRIGGERBOT
    - Hiển thị "PURPLE DETECTED" nếu phát hiện màu tím
    """
    if detected:
        cv2.putText(
            img,
            "PURPLE DETECTED",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),  # Màu đỏ
            2,
        )


def draw_crosshair(img, center_x, center_y, size=10, color=(0, 255, 0)):
    """
    VẼ CROSSHAIR (ĐỐI CHÉO) TẠI TRUNG TÂM
    - Màu xanh lá mặc định
    - Kích thước 10 pixel mặc định
    """
    # Vẽ đường ngang
    cv2.line(img, 
             (center_x - size, center_y), 
             (center_x + size, center_y), 
             color, 2)
    # Vẽ đường dọc
    cv2.line(img, 
             (center_x, center_y - size), 
             (center_x, center_y + size), 
             color, 2)


def draw_info_text(img, text, position=(10, 60), color=(255, 255, 255)):
    """
    VẼ VĂN BẢN THÔNG TIN
    - Màu trắng mặc định
    - Vị trí (10, 60) mặc định
    """
    cv2.putText(
        img,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        color,
        2,
    )


def draw_fps_counter(img, fps, position=(10, 90), color=(0, 255, 0)):
    """
    VẼ BỘ ĐẾM FPS
    - Màu xanh lá mặc định
    - Vị trí (10, 90) mặc định
    """
    cv2.putText(
        img,
        f"FPS: {fps:.1f}",
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def draw_target_info(img, targets, position=(10, 120), color=(255, 255, 0)):
    """
    VẼ THÔNG TIN MỤC TIÊU
    - Màu vàng mặc định
    - Hiển thị số lượng mục tiêu
    """
    cv2.putText(
        img,
        f"Targets: {len(targets)}",
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def draw_aimbot_status(img, enabled, position=(10, 150), color=(0, 255, 0)):
    """
    VẼ TRẠNG THÁI AIMBOT
    - Màu xanh lá nếu bật, đỏ nếu tắt
    """
    status = "AIMBOT: ON" if enabled else "AIMBOT: OFF"
    color = (0, 255, 0) if enabled else (0, 0, 255)
    cv2.putText(
        img,
        status,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def draw_triggerbot_status(img, enabled, position=(10, 180), color=(0, 255, 0)):
    """
    VẼ TRẠNG THÁI TRIGGERBOT
    - Màu xanh lá nếu bật, đỏ nếu tắt
    """
    status = "TRIGGERBOT: ON" if enabled else "TRIGGERBOT: OFF"
    color = (0, 255, 0) if enabled else (0, 0, 255)
    cv2.putText(
        img,
        status,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


class DetectionEngine:
    """
    LỚP DETECTION ENGINE - TRUNG TÂM PHÁT HIỆN VÀ TRACKING
    - Chạy detection 1 lần duy nhất cho toàn bộ frame
    - Vẽ tất cả FOV, bounding box, crosshair
    - Cung cấp kết quả detection cho Aim và Trigger modules
    - Tránh duplicate detection và tối ưu hiệu suất
    """
    
    def __init__(self):
        """Khởi tạo Detection Engine"""
        # Tải mô hình AI detection
        self.model, self.class_names = load_model()
        print("Detection Engine - Classes:", self.class_names)
        
        # Lưu trữ kết quả detection cuối cùng
        self.last_detection_results = []
        self.last_mask = None
        self.last_frame_info = None
        
        # Cấu hình FOV
        self.fovsize = float(getattr(config, "fovsize", 300))
        self.tbfovsize = float(getattr(config, "tbfovsize", 70))
        self.normalsmoothfov = float(getattr(config, "normalsmoothfov", 10))
        
    def detect_and_track(self, img, frame_info):
        """
        HÀM DETECTION VÀ TRACKING CHÍNH
        - Chạy AI detection 1 lần duy nhất
        - Vẽ tất cả FOV, bounding box, crosshair
        - Trả về kết quả detection cho các module khác
        
        Args:
            img: Ảnh BGR để xử lý
            frame_info: Thông tin frame (xres, yres)
            
        Returns:
            dict: {
                'targets': [(x, y, distance), ...],  # Danh sách mục tiêu cho aimbot
                'detection_results': [...],           # Kết quả detection gốc
                'mask': mask,                        # Mask để hiển thị
                'center_detection': bool,            # Có phát hiện ở trung tâm không (cho triggerbot)
                'img': img_with_overlays            # Ảnh đã vẽ overlay
            }
        """
        try:
            # ========== CHẠY AI DETECTION 1 LẦN DUY NHẤT ==========
            detection_results, mask = perform_detection(self.model, img)
            
            # Lưu kết quả để sử dụng sau
            self.last_detection_results = detection_results
            self.last_mask = mask
            self.last_frame_info = frame_info
            
            # Tạo bản copy để vẽ overlay
            img_with_overlays = img.copy()
            
            # ========== XỬ LÝ KẾT QUẢ DETECTION VÀ TÌM MỤC TIÊU ==========
            targets = []  # Danh sách mục tiêu cho aimbot
            center_detection = False  # Có phát hiện ở trung tâm không (cho triggerbot)
            
            if detection_results:
                center_x = frame_info.xres / 2.0
                center_y = frame_info.yres / 2.0
                
                for det in detection_results:
                    try:
                        x, y, w, h = det["bbox"]
                        conf = det.get("confidence", 1.0)
                        x1, y1 = int(x), int(y)
                        x2, y2 = int(x + w), int(y + h)
                        y1 *= 1.03  # Điều chỉnh vị trí Y
                        
                        # Vẽ bounding box của cơ thể
                        draw_body_bbox(img_with_overlays, x1, y1, x2, y2, conf)
                        
                        # Ước tính vị trí đầu
                        head_positions = self._estimate_head_positions(x1, y1, x2, y2, img_with_overlays)
                        for head_cx, head_cy, bbox in head_positions:
                            draw_head_bbox(img_with_overlays, head_cx, head_cy)
                            
                            # Tính khoảng cách từ đầu đến trung tâm
                            d = math.hypot(head_cx - center_x, head_cy - center_y)
                            targets.append((head_cx, head_cy, d))
                            
                            # Kiểm tra có phát hiện ở trung tâm không (cho triggerbot)
                            if not center_detection:
                                # Kiểm tra vùng ROI nhỏ ở trung tâm (5x5 pixel)
                                roi_size = 5
                                if (abs(head_cx - center_x) <= roi_size and 
                                    abs(head_cy - center_y) <= roi_size):
                                    center_detection = True
                                    
                    except Exception as e:
                        print(f"[Detection Engine Error] {e}")
            
            # ========== VẼ TẤT CẢ FOV VÀ OVERLAY ==========
            self._draw_all_overlays(img_with_overlays, frame_info)
            
            # ========== TRẢ VỀ KẾT QUẢ ==========
            return {
                'targets': targets,
                'detection_results': detection_results,
                'mask': mask,
                'center_detection': center_detection,
                'img': img_with_overlays
            }
            
        except Exception as e:
            print(f"[Detection Engine Error] {e}")
            return {
                'targets': [],
                'detection_results': [],
                'mask': None,
                'center_detection': False,
                'img': img
            }
    
    def _estimate_head_positions(self, x1, y1, x2, y2, img):
        """
        HÀM ƯỚC TÍNH VỊ TRÍ ĐẦU TRONG BOUNDING BOX CỦA CƠ THỂ
        - Tương tự như trong aim.py nhưng được tối ưu hóa
        """
        # Lấy offset từ config
        offsetY = getattr(config, "offsetY", 0)
        offsetX = getattr(config, "offsetX", 0)
        
        # Tính kích thước bounding box
        width = x2 - x1
        height = y2 - y1
        
        # Crop nhẹ để tập trung vào vùng đầu
        top_crop_factor = 0.10
        side_crop_factor = 0.10
        
        effective_y1 = y1 + height * top_crop_factor
        effective_height = height * (1 - top_crop_factor)
        effective_x1 = x1 + width * side_crop_factor
        effective_x2 = x2 - width * side_crop_factor
        effective_width = effective_x2 - effective_x1
        
        # Tính vị trí đầu cơ bản với offset
        center_x = (effective_x1 + effective_x2) / 2
        headx_base = center_x + effective_width * (offsetX / 100)
        heady_base = effective_y1 + effective_height * (offsetY / 100)
        
        # Tạo ROI xung quanh vị trí đầu
        pixel_marginx = 40
        pixel_marginy = 10
        
        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))
        
        roi = img[y1_roi:y2_roi, x1_roi:x2_roi]
        draw_roi_rectangle(img, x1_roi, y1_roi, x2_roi, y2_roi)
        
        # Chạy detection trên ROI
        results = []
        try:
            detections, _ = perform_detection(self.model, roi)
        except Exception as e:
            print(f"[Detection Engine ROI Error] {e}")
            detections = []
        
        if not detections:
            # Không tìm thấy đầu → dùng vị trí ước tính
            results.append((headx_base, heady_base, (x1_roi, y1_roi, x2_roi, y2_roi)))
        else:
            # Tìm thấy đầu → tính vị trí chính xác
            for det in detections:
                x, y, w, h = det["bbox"]
                draw_detection_rectangle(img, x1_roi + x, y1_roi + y, 
                                       x1_roi + x + w, y1_roi + y + h)
                
                headx_det = x1_roi + x + w / 2
                heady_det = y1_roi + y + h / 2
                
                # Áp dụng offset
                headx_det += effective_width * (offsetX / 100)
                heady_det += effective_height * (offsetY / 100)
                
                results.append((headx_det, heady_det, (x1_roi + x, y1_roi + y, w, h)))
        
        return results
    
    def _draw_all_overlays(self, img, frame_info):
        """
        VẼ TẤT CẢ OVERLAY LÊN ẢNH
        - FOV circles
        - Crosshair
        - Status text
        """
        center_x = int(frame_info.xres / 2)
        center_y = int(frame_info.yres / 2)
        
        # Vẽ FOV circles
        draw_fov_circles(img, frame_info)
        
        # Vẽ crosshair
        draw_crosshair(img, center_x, center_y)
        
        # Vẽ status text (ĐÃ ẨN - CHỈ HIỂN THỊ ESP BOX VÀ FOV)
        # aim_enabled = getattr(config, "enableaim", False)
        # trigger_enabled = getattr(config, "enabletb", False)
        
        # draw_aimbot_status(img, aim_enabled)
        # draw_triggerbot_status(img, trigger_enabled)
        
        # Vẽ thông tin detection (ĐÃ ẨN)
        # if self.last_detection_results:
        #     draw_target_info(img, self.last_detection_results)
    
    def get_last_detection(self):
        """
        LẤY KẾT QUẢ DETECTION CUỐI CÙNG
        - Dùng cho các module khác khi cần kết quả detection
        """
        return {
            'detection_results': self.last_detection_results,
            'mask': self.last_mask,
            'frame_info': self.last_frame_info
        }
