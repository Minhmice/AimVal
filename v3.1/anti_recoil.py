# ============================
# MODULE ANTI-RECOIL - CHỐNG GIẬT SÚNG (PATTERN-BASED)
# ============================
# 
# TÍNH NĂNG MỚI:
# - Pattern-based recoil compensation với timeline cụ thể
# - Compensation Strength: Điều chỉnh cường độ từ 0-100%
# - Start Delay: Thời gian chờ trước khi bắt đầu pattern (ms)
# - Duration per Level: Thời gian thực hiện mỗi bước trong pattern (ms)
# - Pattern: Chuỗi các giá trị compensation "3,4,4,3,4,5,5,7,6,8,7,9"
# - Timeline: Start Delay + (Levels × Duration per Level) = Total Time
#
# VÍ DỤ: Pattern "3,4,4,3,4,5,5,7,6,8,7,9" với 70% strength:
# - Level 0: 3 × 0.7 = 2.1px compensation trong 40ms
# - Level 1: 4 × 0.7 = 2.8px compensation trong 40ms
# - ... (tiếp tục cho 12 levels)
# - Total time: 120ms (start delay) + 480ms (12×40ms) = 600ms
#
# ============================
import time
import random
from config import config
from mouse import Mouse, is_button_pressed
from smooth import move_smooth_to_position


class AntiRecoilState:
    """
    LỚP LƯU TRỮ TRẠNG THÁI ANTI-RECOIL
    - Theo dõi thời gian pull cuối cùng
    - Quản lý trạng thái kích hoạt anti-recoil
    - Lưu trữ vị trí chuột để tự động trở về
    - Hỗ trợ pattern-based recoil compensation
    """
    def __init__(self):
        self.last_pull_ms = 0  # Thời điểm pull cuối cùng (millisecond)
        self.is_ads_held = False  # Trạng thái giữ ADS
        self.ads_start_time = 0  # Thời điểm bắt đầu giữ ADS
        self.is_triggering = False  # Trạng thái đang bắn
        self.trigger_start_time = 0  # Thời điểm bắt đầu bắn
        self.was_triggering = False  # Trạng thái bắn trước đó
        
        # ========== TRẠNG THÁI MỚI CHO 2 PHÍM ==========
        self.is_anti_recoil_active = False  # Trạng thái anti-recoil đang chạy
        self.initial_target_detected = False  # Đã phát hiện mục tiêu ban đầu
        self.start_mouse_x = 0  # Vị trí chuột khi bắt đầu
        self.start_mouse_y = 0  # Vị trí chuột khi bắt đầu
        
        # ========== PATTERN-BASED RECOIL STATE ==========
        self.pattern_start_time = 0  # Thời điểm bắt đầu pattern
        self.current_level = 0  # Level hiện tại trong pattern
        self.level_start_time = 0  # Thời điểm bắt đầu level hiện tại
        self.pattern_completed = False  # Pattern đã hoàn thành chưa
        self.start_delay_completed = False  # Start delay đã hoàn thành chưa


class AntiRecoil:
    """
    LỚP ANTI-RECOIL CHÍNH - CHỐNG GIẬT SÚNG TỰ ĐỘNG
    - Áp dụng chuyển động vi mô để bù trừ recoil
    - Hỗ trợ cấu hình linh hoạt (ADS, fire rate, jitter)
    - Tích hợp với hệ thống mouse control
    """
    def __init__(self, app):
        self.app = app  # Tham chiếu đến ứng dụng chính
        self.controller = Mouse()  # Điều khiển chuột
        self.state = AntiRecoilState()  # Trạng thái anti-recoil
        
        # Cấu hình mặc định - Pattern-based recoil
        self.enabled = getattr(config, "anti_recoil_enabled", False)
        self.compensation_strength = getattr(config, "anti_recoil_compensation_strength", 70)  # 0-100%
        self.start_delay_ms = getattr(config, "anti_recoil_start_delay", 120)  # Start delay
        self.duration_per_level_ms = getattr(config, "anti_recoil_duration_per_level", 40)  # Duration per level
        self.recoil_pattern = getattr(config, "anti_recoil_pattern", "3,4,4,3,4,5,5,7,6,8,7,9")  # Pattern string
        
        # Legacy config (for backward compatibility)
        self.x_recoil = getattr(config, "anti_recoil_x", 0)
        self.y_recoil = getattr(config, "anti_recoil_y", 0)
        self.fire_rate_ms = getattr(config, "anti_recoil_fire_rate", 100)
        self.hold_time_ms = getattr(config, "anti_recoil_hold_time", 0)
        self.only_when_triggering = getattr(config, "anti_recoil_only_triggering", True)
        self.scale_with_ads = getattr(config, "anti_recoil_scale_ads", 1.0)
        self.smooth_segments = getattr(config, "anti_recoil_smooth_segments", 2)
        self.smooth_ctrl_scale = getattr(config, "anti_recoil_smooth_scale", 0.25)
        self.random_jitter_x = getattr(config, "anti_recoil_jitter_x", 0)
        self.random_jitter_y = getattr(config, "anti_recoil_jitter_y", 0)
        
        # Parse pattern string into list
        self.pattern_values = self._parse_pattern(self.recoil_pattern)
        
        # Phím điều khiển (2 phím)
        self.anti_recoil_key_1 = getattr(config, "anti_recoil_key_1", 3)  # Side Mouse 4
        self.anti_recoil_key_2 = getattr(config, "anti_recoil_key_2", 4)  # Side Mouse 5

    def _parse_pattern(self, pattern_string):
        """Parse pattern string into list of integers"""
        try:
            # Parse pattern string "3,4,4,3,4,5,5,7,6,8,7,9" into [3,4,4,3,4,5,5,7,6,8,7,9]
            values = [int(x.strip()) for x in pattern_string.split(',') if x.strip()]
            return values
        except Exception as e:
            print(f"[Anti-Recoil] Pattern parsing error: {e}, using default pattern")
            return [3,4,4,3,4,5,5,7,6,8,7,9]  # Default pattern

    def update_config(self):
        """Cập nhật cấu hình từ config"""
        # Pattern-based config
        self.enabled = getattr(config, "anti_recoil_enabled", False)
        self.compensation_strength = getattr(config, "anti_recoil_compensation_strength", 70)
        self.start_delay_ms = getattr(config, "anti_recoil_start_delay", 120)
        self.duration_per_level_ms = getattr(config, "anti_recoil_duration_per_level", 40)
        self.recoil_pattern = getattr(config, "anti_recoil_pattern", "3,4,4,3,4,5,5,7,6,8,7,9")
        
        # Legacy config (for backward compatibility)
        self.x_recoil = getattr(config, "anti_recoil_x", 0)
        self.y_recoil = getattr(config, "anti_recoil_y", 0)
        self.fire_rate_ms = getattr(config, "anti_recoil_fire_rate", 100)
        self.hold_time_ms = getattr(config, "anti_recoil_hold_time", 0)
        self.only_when_triggering = getattr(config, "anti_recoil_only_triggering", True)
        self.scale_with_ads = getattr(config, "anti_recoil_scale_ads", 1.0)
        self.smooth_segments = getattr(config, "anti_recoil_smooth_segments", 2)
        self.smooth_ctrl_scale = getattr(config, "anti_recoil_smooth_scale", 0.25)
        self.random_jitter_x = getattr(config, "anti_recoil_jitter_x", 0)
        self.random_jitter_y = getattr(config, "anti_recoil_jitter_y", 0)
        
        # Cập nhật phím và pattern
        self.anti_recoil_key_1 = getattr(config, "anti_recoil_key_1", 3)
        self.anti_recoil_key_2 = getattr(config, "anti_recoil_key_2", 4)
        self.pattern_values = self._parse_pattern(self.recoil_pattern)

    def check_anti_recoil_keys(self):
        """
        KIỂM TRA CÓ PHÍM ANTI-RECOIL NÀO ĐƯỢC NHẤN KHÔNG
        - Kiểm tra anti_recoil_key_1 hoặc anti_recoil_key_2 có được nhấn không
        - Trả về True nếu có phím nào được nhấn, False nếu không
        """
        try:
            from mouse import is_button_pressed
            
            # Kiểm tra có phím anti-recoil nào được nhấn không
            return (is_button_pressed(self.anti_recoil_key_1) or is_button_pressed(self.anti_recoil_key_2))
        except Exception as e:
            print(f"[Anti-Recoil Key Check Error] {e}")
            return False

    def tick(self, detection_engine=None):
        """
        HÀM XỬ LÝ ANTI-RECOIL CHÍNH - PATTERN-BASED SYSTEM
        - Sử dụng pattern với timeline cụ thể
        - Start delay trước khi bắt đầu pattern
        - Thực hiện từng level trong pattern theo duration
        - Compensation strength để điều chỉnh cường độ
        """
        if not self.enabled:
            return

        try:
            # Kiểm tra có phím anti-recoil nào được nhấn không
            key_pressed = self.check_anti_recoil_keys()
            current_time = time.time() * 1000  # Current time in ms
            
            if key_pressed:
                if not self.state.is_anti_recoil_active:
                    # Bắt đầu pattern-based anti-recoil
                    self._start_pattern_anti_recoil(current_time)
                else:
                    # Đang chạy - xử lý pattern execution
                    self._execute_pattern_anti_recoil(current_time)
            
            else:
                # Không có phím nào được nhấn - dừng pattern
                if self.state.is_anti_recoil_active:
                    self._stop_pattern_anti_recoil()
            
        except Exception as e:
            print(f"[Anti-Recoil Error] {e}")

    def _start_pattern_anti_recoil(self, current_time):
        """Bắt đầu pattern-based anti-recoil"""
        try:
            # Lưu vị trí chuột khi bắt đầu
            current_pos = self.controller.get_position()
            if current_pos:
                self.state.start_mouse_x, self.state.start_mouse_y = current_pos
                print(f"[Anti-Recoil] Start position saved: X={self.state.start_mouse_x}, Y={self.state.start_mouse_y}")
            else:
                self.state.start_mouse_x, self.state.start_mouse_y = 0, 0
            
            # Khởi tạo trạng thái pattern
            self.state.is_anti_recoil_active = True
            self.state.pattern_start_time = current_time
            self.state.current_level = 0
            self.state.level_start_time = current_time
            self.state.pattern_completed = False
            self.state.start_delay_completed = False
            
            print(f"[Anti-Recoil] Pattern started - {len(self.pattern_values)} levels, Start delay: {self.start_delay_ms}ms")
            
        except Exception as e:
            print(f"[Anti-Recoil Start Error] {e}")

    def _execute_pattern_anti_recoil(self, current_time):
        """Thực hiện pattern anti-recoil theo timeline"""
        try:
            # Kiểm tra start delay
            if not self.state.start_delay_completed:
                elapsed_time = current_time - self.state.pattern_start_time
                if elapsed_time < self.start_delay_ms:
                    return  # Chưa hết start delay
                else:
                    self.state.start_delay_completed = True
                    self.state.level_start_time = current_time  # Reset level timer
                    print(f"[Anti-Recoil] Start delay completed - Beginning pattern execution")
            
            # Kiểm tra pattern đã hoàn thành chưa
            if self.state.current_level >= len(self.pattern_values):
                self.state.pattern_completed = True
                print(f"[Anti-Recoil] Pattern completed - All {len(self.pattern_values)} levels executed")
                return
            
            # Thực hiện level hiện tại
            level_elapsed = current_time - self.state.level_start_time
            if level_elapsed >= self.duration_per_level_ms:
                # Đã hết thời gian cho level hiện tại - thực hiện compensation
                self._execute_level_compensation()
                
                # Chuyển sang level tiếp theo
                self.state.current_level += 1
                self.state.level_start_time = current_time
                
                if self.state.current_level < len(self.pattern_values):
                    print(f"[Anti-Recoil] Level {self.state.current_level-1} completed - Moving to level {self.state.current_level}")
                else:
                    print(f"[Anti-Recoil] Pattern completed - All levels executed")
            
        except Exception as e:
            print(f"[Anti-Recoil Execute Error] {e}")

    def _execute_level_compensation(self):
        """Thực hiện compensation cho level hiện tại"""
        try:
            if self.state.current_level >= len(self.pattern_values):
                return
            
            # Lấy giá trị pattern cho level hiện tại
            pattern_value = self.pattern_values[self.state.current_level]
            
            # Áp dụng compensation strength (0-100%)
            strength_multiplier = self.compensation_strength / 100.0
            compensation_y = int(pattern_value * strength_multiplier)
            
            print(f"[Anti-Recoil] Level {self.state.current_level}: Pattern={pattern_value}, Compensation={compensation_y}px (Strength={self.compensation_strength}%)")
            
            # Thực hiện chuyển động chuột (chỉ Y - xuống dưới)
            dx = 0  # Không di chuyển ngang
            dy = compensation_y  # Di chuyển xuống dưới
            
            if hasattr(self.controller, "move_smooth"):
                self.controller.move_smooth(
                    dx, dy,
                    segments=max(1, int(self.smooth_segments)),
                    ctrl_scale=float(self.smooth_ctrl_scale)
                )
            else:
                self.controller.move(dx, dy)
                
        except Exception as e:
            print(f"[Anti-Recoil Level Error] {e}")

    def _stop_pattern_anti_recoil(self):
        """Dừng pattern anti-recoil và quay về vị trí ban đầu"""
        try:
            self.state.is_anti_recoil_active = False
            self.state.pattern_completed = False
            self.state.start_delay_completed = False
            self.state.current_level = 0
            
            # Quay về vị trí ban đầu
            self._return_to_start_position()
            
            print("[Anti-Recoil] Pattern stopped - Key released")
            
        except Exception as e:
            print(f"[Anti-Recoil Stop Error] {e}")

    def _apply_anti_recoil(self):
        """Áp dụng chuyển động anti-recoil - chỉ Y recoil"""
        try:
            # Kiểm tra fire rate
            now_ms = time.time() * 1000
            if now_ms - self.state.last_pull_ms < self.fire_rate_ms:
                return  # Chưa đủ thời gian fire rate
            
            # Tính toán chuyển động - chỉ Y recoil (xuống dưới)
            dx = 0  # Không di chuyển ngang
            dy = int(self.y_recoil)  # Chỉ di chuyển xuống dưới

            # Thêm random jitter Y nếu được bật
            if self.random_jitter_y > 0:
                jitter_y = int(self.random_jitter_y)
                dy += random.randint(-jitter_y, jitter_y)

            # Áp dụng scale với ADS
            dy = int(dy * self.scale_with_ads)

            # Thực hiện chuyển động chuột
            if hasattr(self.controller, "move_smooth"):
                # Sử dụng chuyển động mượt nếu có
                self.controller.move_smooth(
                    dx, dy, 
                    segments=max(1, int(self.smooth_segments)),
                    ctrl_scale=float(self.smooth_ctrl_scale)
                )
            else:
                # Fallback về chuyển động thông thường
                self.controller.move(dx, dy)

            # Cập nhật thời gian pull cuối cùng
            self.state.last_pull_ms = now_ms

        except Exception as e:
            print(f"[Anti-Recoil Apply Error] {e}")

    def _return_to_start_position(self):
        """
        HÀM QUAY VỀ VỊ TRÍ BAN ĐẦU
        Di chuyển chuột về vị trí khi bắt đầu anti-recoil với smooth movement
        """
        try:
            # Lấy vị trí hiện tại
            current_pos = self.controller.get_position()
            if not current_pos:
                return
            
            current_x, current_y = current_pos
            start_x = self.state.start_mouse_x
            start_y = self.state.start_mouse_y
            
            # Tính khoảng cách
            dx = start_x - current_x
            dy = start_y - current_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance < 1:  # Quá gần, không cần di chuyển
                return
            
            print(f"[Anti-Recoil] Returning to start position: X={dx}, Y={dy}")
            
            # Sử dụng smooth movement để quay về
            if hasattr(self.controller, "move_smooth"):
                self.controller.move_smooth(
                    dx, dy,
                    segments=max(1, int(self.smooth_segments)),
                    ctrl_scale=float(self.smooth_ctrl_scale)
                )
            else:
                # Fallback về chuyển động thông thường
                self.controller.move(dx, dy)
                
        except Exception as e:
            print(f"[Anti-Recoil Return Error] {e}")

    def get_status(self):
        """Lấy trạng thái hiện tại của anti-recoil"""
        current_time = time.time() * 1000
        return {
            "enabled": self.enabled,
            "is_active": self.state.is_anti_recoil_active,
            "current_level": self.state.current_level,
            "total_levels": len(self.pattern_values),
            "pattern_completed": self.state.pattern_completed,
            "start_delay_completed": self.state.start_delay_completed,
            "compensation_strength": self.compensation_strength,
            "start_delay_ms": self.start_delay_ms,
            "duration_per_level_ms": self.duration_per_level_ms,
            "total_pattern_time": self.start_delay_ms + (len(self.pattern_values) * self.duration_per_level_ms),
            "elapsed_time": current_time - self.state.pattern_start_time if self.state.is_anti_recoil_active else 0,
            "start_mouse_x": self.state.start_mouse_x,
            "start_mouse_y": self.state.start_mouse_y,
            "recoil_pattern": self.recoil_pattern
        }


def anti_recoil_tick(
    enabled: bool,
    is_triggering: bool,
    now_ms: int,
    held_ms: int,
    cfg_ar,
    state: AntiRecoilState,
    send_input,
):
    """
    HÀM ANTI-RECOIL TICK GỐC (COMPATIBILITY)
    - Giữ nguyên interface gốc để tương thích
    - Áp dụng chuyển động anti-recoil dựa trên cấu hình
    """
    if not cfg_ar.get("enabled", False) or not enabled:
        return
    if cfg_ar.get("only_when_triggering", True) and not is_triggering:
        return
    if held_ms < int(cfg_ar.get("hold_time_ms", 0)):
        return
    if now_ms - state.last_pull_ms < int(cfg_ar.get("fire_rate_ms", 100)):
        return

    dx = int(cfg_ar.get("x_recoil", 0))
    dy = int(cfg_ar.get("y_recoil", 0))

    rj = cfg_ar.get("random_jitter_px", {"x": 0, "y": 0})
    if rj.get("x", 0) or rj.get("y", 0):
        jitter_x = int(rj.get("x", 0))
        jitter_y = int(rj.get("y", 0))
        dx += random.randint(-jitter_x, jitter_x)
        dy += random.randint(-jitter_y, jitter_y)

    scale_ads = float(cfg_ar.get("scale_with_ads", 1.0))
    dx = int(dx * scale_ads)
    dy = int(dy * scale_ads)

    # Prefer smooth movement if the controller supports it
    try:
        if hasattr(send_input, "move_smooth"):
            send_input.move_smooth(dx, dy, segments=max(1, int(cfg_ar.get("smooth_segments", 2))), ctrl_scale=float(cfg_ar.get("smooth_ctrl_scale", 0.25)))
        else:
            send_input.move(dx, dy)
    except Exception:
        send_input.move(dx, dy)
    state.last_pull_ms = now_ms
