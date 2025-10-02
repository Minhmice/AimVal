# ============================
# MODULE TRIGGERBOT - LOGIC TỰ ĐỘNG BẮN
# ============================
import time
import cv2
import numpy as np
from config import config
from mouse import Mouse, is_button_pressed
from detection import perform_detection


class TriggerBot:
    """
    LỚP TRIGGERBOT - TỰ ĐỘNG BẮN KHI PHÁT HIỆN MÀU SẮC
    - Kiểm tra vùng trung tâm màn hình để phát hiện màu sắc
    - Tự động click chuột khi phát hiện màu tím (purple)
    - Có độ trễ để tránh spam click
    """
    def __init__(self, model):
        self.model = model  # Mô hình HSV để phát hiện màu
        self.controller = Mouse()  # Điều khiển chuột
        self.last_click_time = 0.0  # Thời điểm click cuối cùng
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))  # Độ trễ giữa các lần click
        self.enabled = False  # Trạng thái bật/tắt triggerbot

    def update_config(self):
        """Cập nhật cấu hình từ config"""
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))
        self.enabled = getattr(config, "enabletb", False)

    def check_and_trigger(self, img, frame):
        """
        KIỂM TRA VÀ THỰC HIỆN TRIGGERBOT
        - Kiểm tra vùng trung tâm màn hình có màu sắc mục tiêu không
        - Tự động click nếu phát hiện và đã đủ thời gian delay
        """
        if not self.enabled or self.model is None:
            return

        # Kiểm tra có phím triggerbot được nhấn không
        if not is_button_pressed(getattr(config, "trigger_button", 1)):
            return

        try:
            # Lấy vùng trung tâm màn hình (ROI nhỏ)
            center_x, center_y = int(frame.xres // 2), int(frame.yres // 2)
            ROI_SIZE = 5  # Kích thước vùng kiểm tra (5x5 pixel)
            x1 = max(center_x - ROI_SIZE, 0)
            y1 = max(center_y - ROI_SIZE, 0)
            x2 = min(center_x + ROI_SIZE, img.shape[1])
            y2 = min(center_y + ROI_SIZE, img.shape[0])
            
            roi = img[y1:y2, x1:x2]  # Lấy vùng ROI

            if roi.size == 0:
                return  # ROI rỗng thì bỏ qua

            # Chuyển đổi sang HSV và tạo mask
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            HSV_LOWER = self.model[0]  # Giá trị HSV tối thiểu
            HSV_UPPER = self.model[1]  # Giá trị HSV tối đa
            mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)

            # Kiểm tra có pixel màu sắc nào không
            detected = cv2.countNonZero(mask) > 0

            # Debug hiển thị (nếu bật)
            if getattr(config, "debug_show", False):
                cv2.imshow("ROI", roi)
                cv2.imshow("Mask", mask)
                cv2.waitKey(1)

            # Hiển thị thông báo trên ảnh chính
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
                
                # Kiểm tra thời gian delay
                now = time.time()
                if now - self.last_click_time >= self.tbdelay:
                    self.controller.click()  # Thực hiện click
                    self.last_click_time = now  # Cập nhật thời gian click

        except Exception as e:
            print(f"[Triggerbot Error] {e}")


def triggerbot_detect(model, roi):
    """
    PHÁT HIỆN MÀU SẮC CHO TRIGGERBOT
    - Kiểm tra xem có màu sắc mục tiêu trong vùng ROI không
    - Sử dụng cho triggerbot - tự động bắn khi phát hiện màu
    - Trả về True nếu có ít nhất 1 pixel màu sắc, False nếu không

    Tham số:
        model : tuple (HSV_MIN, HSV_MAX) - mô hình HSV
        roi : ảnh BGR của vùng cần phân tích
    """
    if model is None or roi is None:
        return False  # Không có model hoặc ROI thì trả về False

    # Chuyển đổi sang HSV và tạo mask
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # Chuyển BGR sang HSV
    mask = cv2.inRange(hsv_roi, model[0], model[1])  # Tạo mask theo khoảng HSV

    # Làm sạch mask bằng phép toán hình thái học nhẹ
    kernel = np.ones((3, 3), np.uint8)  # Kernel 3x3
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)  # Đóng các lỗ hổng nhỏ

    # Trả về True nếu có ít nhất 1 pixel được phát hiện
    return np.any(mask > 0)
