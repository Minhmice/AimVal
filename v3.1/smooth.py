# ============================
# MODULE SMOOTH MOVEMENT - CHUYỂN ĐỘNG MƯỢT MÀ
# ============================
import time
import random
from mouse import Mouse


def ease_out_cubic(t):
    """Ease out cubic function - nhanh → chậm"""
    return 1 - pow(1 - t, 3)


def ease_in_cubic(t):
    """Ease in cubic function - chậm → nhanh"""
    return t * t * t


def move_smooth(dx, dy):
    """
    HÀM SMOOTH DUY NHẤT CHO TẤT CẢ CHUYỂN ĐỘNG
    - Random time: 10-80ms
    - Random easing: ease_in hoặc ease_out
    - Áp dụng cho aim, anti-recoil, mọi chuyển động
    """
    try:
        mouse = Mouse()
        
        # Random duration: 10-80ms
        duration_ms = random.randint(10, 80)
        
        # Random easing type
        ease_type = random.choice(["ease_in", "ease_out"])
        
        # Tính số frame (60 FPS)
        fps = 60
        total_frames = max(1, int(duration_ms * fps / 1000))
        
        # Di chuyển từng frame
        for frame in range(total_frames + 1):
            # Tính progress (0.0 -> 1.0)
            progress = frame / total_frames
            
            # Áp dụng random easing
            if ease_type == "ease_out":
                eased_progress = ease_out_cubic(progress)
            else:  # ease_in
                eased_progress = ease_in_cubic(progress)
            
            # Tính vị trí di chuyển
            move_x = int(dx * eased_progress)
            move_y = int(dy * eased_progress)
            
            # Di chuyển chuột
            mouse.move(move_x, move_y)
            
            # Delay giữa các frame
            time.sleep(1.0 / fps)
            
    except Exception as e:
        print(f"[Smooth Movement Error] {e}")


def move_smooth_to_position(start_x, start_y, target_x, target_y):
    """
    DI CHUYỂN MƯỢT MÀ ĐẾN VỊ TRÍ MỤC TIÊU
    - Sử dụng hàm move_smooth() bên trong
    """
    try:
        # Tính khoảng cách
        dx = target_x - start_x
        dy = target_y - start_y
        
        # Sử dụng hàm move_smooth chính
        move_smooth(dx, dy)
            
    except Exception as e:
        print(f"[Smooth To Position Error] {e}")
