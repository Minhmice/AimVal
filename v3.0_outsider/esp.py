# ============================
# MODULE ESP - VẼ FOV VÀ CÁC THÔNG TIN HIỂN THỊ
# ============================
import cv2
import numpy as np
from config import config


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
