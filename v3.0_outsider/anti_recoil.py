# ============================
# MODULE ANTI-RECOIL - CHỐNG GIẬT SÚNG
# ============================
import time
import random
from config import config
from mouse import Mouse, is_button_pressed
from smooth import smooth_movement


class AntiRecoilState:
    """
    LỚP LƯU TRỮ TRẠNG THÁI ANTI-RECOIL
    - Theo dõi thời gian pull cuối cùng
    - Quản lý trạng thái kích hoạt anti-recoil
    - Lưu trữ vị trí chuột để tự động trở về
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
        
        # Cấu hình mặc định
        self.enabled = getattr(config, "anti_recoil_enabled", False)
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
        
        # Phím điều khiển (2 phím)
        self.anti_recoil_key_1 = getattr(config, "anti_recoil_key_1", 3)  # Side Mouse 4
        self.anti_recoil_key_2 = getattr(config, "anti_recoil_key_2", 4)  # Side Mouse 5

    def update_config(self):
        """Cập nhật cấu hình từ config"""
        self.enabled = getattr(config, "anti_recoil_enabled", False)
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
        
        # Cập nhật phím mới
        self.anti_recoil_key_1 = getattr(config, "anti_recoil_key_1", 3)
        self.anti_recoil_key_2 = getattr(config, "anti_recoil_key_2", 4)

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
        HÀM XỬ LÝ ANTI-RECOIL CHÍNH (CẬP NHẬT)
        - Sử dụng 2 phím để điều khiển
        - Kiểm tra hold time trước khi kích hoạt
        - Lưu vị trí chuột khi bắt đầu
        - Quay về vị trí ban đầu khi dừng
        """
        if not self.enabled:
            return

        try:
            # Kiểm tra có phím anti-recoil nào được nhấn không
            key_pressed = self.check_anti_recoil_keys()
            
            if key_pressed and not self.state.is_anti_recoil_active:
                # Bắt đầu: Kiểm tra hold time
                if self.hold_time_ms > 0:
                    # Cần hold đủ thời gian trước khi kích hoạt
                    if not hasattr(self.state, 'hold_start_time'):
                        self.state.hold_start_time = time.time() * 1000  # Bắt đầu đếm hold time
                    else:
                        held_time = (time.time() * 1000) - self.state.hold_start_time
                        if held_time < self.hold_time_ms:
                            return  # Chưa đủ thời gian hold
                
                # Lưu vị trí chuột khi bắt đầu
                current_pos = smooth_movement.get_position()
                if current_pos:
                    self.state.start_mouse_x, self.state.start_mouse_y = current_pos
                
                self.state.is_anti_recoil_active = True
                self.state.initial_target_detected = True
                print("[Anti-Recoil] Started - Key pressed")
            
            elif not key_pressed and self.state.is_anti_recoil_active:
                # Dừng: Thả phím - Quay về vị trí ban đầu
                self.state.is_anti_recoil_active = False
                self.state.initial_target_detected = False
                
                # Quay về vị trí ban đầu với smooth movement
                self._return_to_start_position()
                
                if hasattr(self.state, 'hold_start_time'):
                    delattr(self.state, 'hold_start_time')  # Reset hold time
                print("[Anti-Recoil] Stopped - Key released")
            
            # Chỉ chạy anti-recoil khi đang active
            if self.state.is_anti_recoil_active:
                self._apply_anti_recoil()
            
        except Exception as e:
            print(f"[Anti-Recoil Error] {e}")


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
            current_pos = smooth_movement.get_position()
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
            smooth_movement.move_smooth_to_position(
                current_x, current_y,
                start_x, start_y,
                duration_ms=None,  # Random duration
                ease_type="ease_out"  # Ease out cho mượt mà
            )
                
        except Exception as e:
            print(f"[Anti-Recoil Return Error] {e}")

    def get_status(self):
        """Lấy trạng thái hiện tại của anti-recoil"""
        return {
            "enabled": self.enabled,
            "is_ads_held": self.state.is_ads_held,
            "is_triggering": self.state.is_triggering,
            "last_pull_ms": self.state.last_pull_ms,
            "ads_hold_time": (time.time() * 1000) - self.state.ads_start_time if self.state.is_ads_held else 0,
            "total_recoil_x": self.state.total_recoil_x,
            "total_recoil_y": self.state.total_recoil_y
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
