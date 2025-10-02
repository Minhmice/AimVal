# ============================
# MODULE TRIGGERBOT - LOGIC TỰ ĐỘNG BẮN
# ============================
import time
from config import config
from mouse import Mouse, is_button_pressed


class TriggerBot:
    """
    LỚP TRIGGERBOT - TỰ ĐỘNG BẮN KHI PHÁT HIỆN MÀU SẮC
    - Kiểm tra vùng trung tâm màn hình để phát hiện màu sắc
    - Tự động click chuột khi phát hiện màu tím (purple)
    - Có độ trễ để tránh spam click
    - Hỗ trợ cấu hình fire rate (tốc độ bắn)
    """
    def __init__(self, detection_engine):
        self.detection_engine = detection_engine  # DetectionEngine để lấy kết quả detection
        self.controller = Mouse()  # Điều khiển chuột
        self.last_click_time = 0.0  # Thời điểm click cuối cùng
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))  # Độ trễ giữa các lần click
        self.fire_rate_ms = float(getattr(config, "trigger_fire_rate_ms", 100))  # Tốc độ bắn (ms)
        self.enabled = False  # Trạng thái bật/tắt triggerbot

    def update_config(self):
        """Cập nhật cấu hình từ config"""
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))
        self.fire_rate_ms = float(getattr(config, "trigger_fire_rate_ms", 100))
        self.enabled = getattr(config, "enabletb", False)

    def check_and_trigger(self, center_detection):
        """
        KIỂM TRA VÀ THỰC HIỆN TRIGGERBOT
        - Sử dụng kết quả detection từ DetectionEngine
        - Tự động click nếu phát hiện màu sắc ở trung tâm và đã đủ thời gian delay
        """
        if not self.enabled:
            return

        # Kiểm tra có phím triggerbot được nhấn không
        if not is_button_pressed(getattr(config, "trigger_button", 1)):
            return

        try:
            # Sử dụng kết quả detection từ DetectionEngine (không cần detect riêng)
            if center_detection:
                # Có phát hiện màu sắc ở trung tâm → tự động bắn
                now = time.time()
                now_ms = now * 1000  # Chuyển sang millisecond
                
                # Kiểm tra cả tbdelay (giây) và fire_rate_ms (millisecond)
                if (now - self.last_click_time >= self.tbdelay and 
                    now_ms - self.last_click_time * 1000 >= self.fire_rate_ms):
                    self.controller.click()  # Thực hiện click
                    self.last_click_time = now  # Cập nhật thời gian click

        except Exception as e:
            print(f"[Triggerbot Error] {e}")


