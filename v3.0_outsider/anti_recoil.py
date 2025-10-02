# ============================
# MODULE ANTI-RECOIL - CHỐNG GIẬT SÚNG
# ============================
import time
import random
from config import config
from mouse import Mouse, is_button_pressed


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
        self.total_recoil_x = 0  # Tổng recoil X đã áp dụng
        self.total_recoil_y = 0  # Tổng recoil Y đã áp dụng
        self.was_triggering = False  # Trạng thái bắn trước đó
        
        # ========== TRẠNG THÁI MỚI CHO 1 PHÍM ==========
        self.is_anti_recoil_active = False  # Trạng thái anti-recoil đang chạy
        self.initial_target_detected = False  # Đã phát hiện mục tiêu ban đầu


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
        
        # Phím điều khiển (1 phím duy nhất)
        self.anti_recoil_key = getattr(config, "anti_recoil_key", 3)  # Side Mouse 4
        self.require_initial_target = getattr(config, "anti_recoil_require_initial_target", True)  # Bắt buộc có mục tiêu để bắt đầu

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
        self.anti_recoil_key = getattr(config, "anti_recoil_key", 3)
        self.require_initial_target = getattr(config, "anti_recoil_require_initial_target", True)

    def check_target_in_fov(self, detection_engine):
        """
        KIỂM TRA CÓ MỤC TIÊU TRONG FOV KHÔNG
        - Sử dụng kết quả từ DetectionEngine
        - Kiểm tra có người trong FOV triggerbot không
        - Trả về True nếu có mục tiêu, False nếu không
        """
        try:
            detection_data = detection_engine.get_last_detection()
            if not detection_data or not detection_data.get('detection_results'):
                return False
            
            # Kiểm tra có detection results không
            return len(detection_data['detection_results']) > 0
        except Exception as e:
            print(f"[Anti-Recoil FOV Check Error] {e}")
            return False

    def tick(self, detection_engine=None):
        """
        HÀM XỬ LÝ ANTI-RECOIL CHÍNH (CẬP NHẬT)
        - Chỉ cần 1 phím để điều khiển
        - Kiểm tra có mục tiêu trong FOV để bắt đầu
        - Tiếp tục chạy cho đến khi thả phím
        """
        if not self.enabled:
            return

        try:
            # Kiểm tra phím anti-recoil
            key_pressed = is_button_pressed(self.anti_recoil_key)
            
            if key_pressed and not self.state.is_anti_recoil_active:
                # Bắt đầu: Kiểm tra có mục tiêu trong FOV không
                if self.require_initial_target and detection_engine:
                    if not self.check_target_in_fov(detection_engine):
                        return  # Không có mục tiêu → không bắt đầu
                
                self.state.is_anti_recoil_active = True
                self.state.initial_target_detected = True
                print("[Anti-Recoil] Started - Target detected in FOV")
            
            elif not key_pressed and self.state.is_anti_recoil_active:
                # Dừng: Thả phím
                self.state.is_anti_recoil_active = False
                self.state.initial_target_detected = False
                print("[Anti-Recoil] Stopped - Key released")
            
            # Chỉ chạy anti-recoil khi đang active
            if self.state.is_anti_recoil_active:
                self._apply_anti_recoil()
            
        except Exception as e:
            print(f"[Anti-Recoil Error] {e}")

    def _update_key_states(self):
        """Cập nhật trạng thái các phím điều khiển"""
        try:
            # Kiểm tra trạng thái ADS
            ads_pressed = is_button_pressed(self.ads_key)
            if ads_pressed and not self.state.is_ads_held:
                # Bắt đầu giữ ADS
                self.state.is_ads_held = True
                self.state.ads_start_time = time.time() * 1000  # Chuyển sang millisecond
            elif not ads_pressed and self.state.is_ads_held:
                # Thả ADS
                self.state.is_ads_held = False
                self.state.ads_start_time = 0

            # Kiểm tra trạng thái trigger
            was_triggering = self.state.is_triggering
            self.state.is_triggering = is_button_pressed(self.trigger_key)
            
            # Nếu vừa bắt đầu bắn
            if self.state.is_triggering and not was_triggering:
                self.state.trigger_start_time = time.time() * 1000
                self.state.total_recoil_x = 0  # Reset tổng recoil
                self.state.total_recoil_y = 0
            # Nếu vừa thả nút bắn
            elif not self.state.is_triggering and was_triggering:
                self._return_to_original_position()
            
            self.state.was_triggering = was_triggering
            
        except Exception as e:
            print(f"[Anti-Recoil Key Update Error] {e}")

    def _should_activate(self):
        """Kiểm tra xem có nên kích hoạt anti-recoil không"""
        # Kiểm tra điều kiện cơ bản
        if not self.state.is_ads_held:
            return False

        # Kiểm tra thời gian giữ ADS tối thiểu
        if self.hold_time_ms > 0:
            held_time = (time.time() * 1000) - self.state.ads_start_time
            if held_time < self.hold_time_ms:
                return False

        # Kiểm tra điều kiện trigger
        if self.only_when_triggering and not self.state.is_triggering:
            return False

        # Kiểm tra fire rate
        now_ms = time.time() * 1000
        if now_ms - self.state.last_pull_ms < self.fire_rate_ms:
            return False

        return True

    def _apply_anti_recoil(self):
        """Áp dụng chuyển động anti-recoil"""
        try:
            # Tính toán chuyển động cơ bản
            dx = int(self.x_recoil)
            dy = int(self.y_recoil)

            # Thêm random jitter nếu được bật (SỬA LỖI: chuyển float thành int)
            if self.random_jitter_x > 0:
                jitter_x = int(self.random_jitter_x)
                dx += random.randint(-jitter_x, jitter_x)
            if self.random_jitter_y > 0:
                jitter_y = int(self.random_jitter_y)
                dy += random.randint(-jitter_y, jitter_y)

            # Áp dụng scale với ADS
            dx = int(dx * self.scale_with_ads)
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

            # Cập nhật tổng recoil đã áp dụng
            self.state.total_recoil_x += dx
            self.state.total_recoil_y += dy

            # Cập nhật thời gian pull cuối cùng
            self.state.last_pull_ms = time.time() * 1000

        except Exception as e:
            print(f"[Anti-Recoil Apply Error] {e}")

    def _return_to_original_position(self):
        """
        HÀM TỰ ĐỘNG TRỞ VỀ VỊ TRÍ CŨ
        Di chuyển chuột ngược lại để bù trừ tất cả recoil đã áp dụng
        """
        try:
            if self.state.total_recoil_x != 0 or self.state.total_recoil_y != 0:
                # Di chuyển ngược lại với tổng recoil đã áp dụng
                return_x = -self.state.total_recoil_x
                return_y = -self.state.total_recoil_y
                
                print(f"[Anti-Recoil] Returning to original position: X={return_x}, Y={return_y}")
                
                # Thực hiện chuyển động trở về
                if hasattr(self.controller, "move_smooth"):
                    # Sử dụng chuyển động mượt để trở về
                    self.controller.move_smooth(
                        return_x, return_y,
                        segments=max(1, int(self.smooth_segments)),
                        ctrl_scale=float(self.smooth_ctrl_scale)
                    )
                else:
                    # Fallback về chuyển động thông thường
                    self.controller.move(return_x, return_y)
                
                # Reset tổng recoil
                self.state.total_recoil_x = 0
                self.state.total_recoil_y = 0
                
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
