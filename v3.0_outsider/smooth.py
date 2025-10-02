# ============================
# MODULE SMOOTH MOVEMENT - CHUYỂN ĐỘNG MƯỢT MÀ
# ============================
import time
import math
import random
from mouse import Mouse


class SmoothMovement:
    """
    LỚP SMOOTH MOVEMENT - CHUYỂN ĐỘNG MƯỢT MÀ VÀ HUMANIZE
    - Hỗ trợ ease in, ease out, ease in-out
    - Random time để humanize
    - Dùng chung cho aim và anti-recoil
    """
    
    def __init__(self):
        self.mouse = Mouse()
    
    def ease_in_out_cubic(self, t):
        """Ease in-out cubic function"""
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2
    
    def ease_out_cubic(self, t):
        """Ease out cubic function"""
        return 1 - pow(1 - t, 3)
    
    def ease_in_cubic(self, t):
        """Ease in cubic function"""
        return t * t * t
    
    def move_smooth_to_position(self, start_x, start_y, target_x, target_y, 
                               duration_ms=None, ease_type="ease_in_out"):
        """
        DI CHUYỂN MƯỢT MÀ ĐẾN VỊ TRÍ MỤC TIÊU
        
        Args:
            start_x, start_y: Vị trí bắt đầu
            target_x, target_y: Vị trí mục tiêu
            duration_ms: Thời gian di chuyển (ms), None = random
            ease_type: Loại easing ("ease_in_out", "ease_out", "ease_in")
        """
        try:
            # Tính toán khoảng cách
            dx = target_x - start_x
            dy = target_y - start_y
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance < 1:  # Quá gần, không cần di chuyển
                return
            
            # Random duration nếu không chỉ định
            if duration_ms is None:
                # Random từ 50ms đến 200ms dựa trên khoảng cách
                base_duration = max(50, min(200, int(distance * 0.5)))
                duration_ms = base_duration + random.randint(-20, 50)
            
            # Tính số frame (60 FPS)
            fps = 60
            total_frames = max(1, int(duration_ms * fps / 1000))
            
            # Di chuyển từng frame
            for frame in range(total_frames + 1):
                # Tính progress (0.0 -> 1.0)
                progress = frame / total_frames
                
                # Áp dụng easing
                if ease_type == "ease_in_out":
                    eased_progress = self.ease_in_out_cubic(progress)
                elif ease_type == "ease_out":
                    eased_progress = self.ease_out_cubic(progress)
                elif ease_type == "ease_in":
                    eased_progress = self.ease_in_cubic(progress)
                else:
                    eased_progress = progress  # Linear
                
                # Tính vị trí hiện tại
                current_x = start_x + dx * eased_progress
                current_y = start_y + dy * eased_progress
                
                # Di chuyển chuột
                self.mouse.move(int(current_x), int(current_y))
                
                # Delay giữa các frame
                time.sleep(1.0 / fps)
                
        except Exception as e:
            print(f"[Smooth Movement Error] {e}")
    
    def move_smooth_relative(self, dx, dy, duration_ms=None, ease_type="ease_in_out"):
        """
        DI CHUYỂN MƯỢT MÀ TƯƠNG ĐỐI
        
        Args:
            dx, dy: Khoảng cách di chuyển
            duration_ms: Thời gian di chuyển (ms)
            ease_type: Loại easing
        """
        try:
            # Lấy vị trí hiện tại
            current_pos = self.mouse.get_position()
            if not current_pos:
                return
            
            start_x, start_y = current_pos
            target_x = start_x + dx
            target_y = start_y + dy
            
            self.move_smooth_to_position(start_x, start_y, target_x, target_y, 
                                       duration_ms, ease_type)
            
        except Exception as e:
            print(f"[Smooth Relative Movement Error] {e}")
    
    def get_position(self):
        """Lấy vị trí chuột hiện tại"""
        try:
            return self.mouse.get_position()
        except Exception as e:
            print(f"[Get Position Error] {e}")
            return None


# Tạo instance global
smooth_movement = SmoothMovement()
