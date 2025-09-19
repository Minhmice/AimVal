# detection2.py
import logging
from typing import Dict, Tuple, List, Optional

import cv2
import numpy as np
from config import config

# =========================
# Logging
# =========================
LOG_LEVEL = getattr(config, "log_level", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Detection2")

# =========================
# Globals / State
# =========================
_model = None  # tuple (HSV_MIN, HSV_MAX) hoặc dict {name: (min, max)}
_class_names = {}  # {name: 'Target Color: name'}


# =========================
# Utils
# =========================
def _normalize_lighting(bgr: np.ndarray) -> np.ndarray:
    """CLAHE trên kênh V (HSV) nếu bật use_clahe."""
    if not bool(getattr(config, "use_clahe", True)):
        return bgr
    clip = float(getattr(config, "det_clahe_clip", getattr(config, "clahe_clip", 2.0)))
    grid = int(getattr(config, "det_clahe_grid", 8))
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    clahe = cv2.createCLAHE(
        clipLimit=max(1.0, clip), tileGridSize=(max(1, grid), max(1, grid))
    )
    v2 = clahe.apply(v)
    hsv2 = cv2.merge([h, s, v2])
    return cv2.cvtColor(hsv2, cv2.COLOR_HSV2BGR)


def _has_color_vertical_line(
    mask: np.ndarray, x: int, y1: int, y2: int, min_h: int
) -> bool:
    """Kiểm tra cột dọc tại x có >=1 pixel >0 và chiều cao vùng > min_h (xấp xỉ)."""
    x = int(np.clip(x, 0, mask.shape[1] - 1))
    y1 = int(np.clip(y1, 0, mask.shape[0] - 1))
    y2 = int(np.clip(y2, 0, mask.shape[0]))
    col = mask[y1:y2, x]
    if col.size == 0:
        return False
    # Độ cao ước lượng: số pixel liên tiếp >0 (đơn giản)
    nz = np.where(col > 0)[0]
    if nz.size == 0:
        return False
    if min_h <= 1:
        return True
    # kiểm tra đoạn liên tục dài nhất
    longest = 1
    cur = 1
    for i in range(1, nz.size):
        if nz[i] == nz[i - 1] + 1:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1
    return longest >= int(min_h)


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _center(rect):
    x, y, w, h = rect
    return (x + w * 0.5, y + h * 0.5)


def _dist(c1, c2):
    return float(np.hypot(c1[0] - c2[0], c1[1] - c2[1]))


def _merge_close_rects(
    rects: List[Tuple[int, int, int, int]], iou_thr: float, dist_thr: float
) -> List[Tuple[int, int, int, int]]:
    """Gộp bbox nếu IOU cao hoặc tâm gần nhau."""
    if not rects:
        return []
    used = [False] * len(rects)
    merged = []

    for i in range(len(rects)):
        if used[i]:
            continue
        base = rects[i]
        bx, by, bw, bh = base
        group = [i]

        for j in range(i + 1, len(rects)):
            if used[j]:
                continue
            r2 = rects[j]
            if (
                _iou(base, r2) >= iou_thr
                or _dist(_center(base), _center(r2)) <= dist_thr
            ):
                group.append(j)
                x2, y2, w2, h2 = r2
                nx1 = min(bx, x2)
                ny1 = min(by, y2)
                nx2 = max(bx + bw, x2 + w2)
                ny2 = max(by + bh, y2 + h2)
                bx, by, bw, bh = nx1, ny1, nx2 - nx1, ny2 - ny1
                base = (bx, by, bw, bh)

        for g in group:
            used[g] = True
        merged.append(base)
    return merged


# =========================
# Public API
# =========================
def load_model(model_path: Optional[str] = None):
    """
    Tạo model HSV từ config (20 tham số Detection).
    Trả về:
      - model: tuple(HSV_MIN, HSV_MAX)
      - class_names: {"color": "Target Color: color"}
    """
    global _model, _class_names
    try:
        # Lấy range HSV từ config.det_*
        hmin = int(getattr(config, "det_h_min", 30))
        hmax = int(getattr(config, "det_h_max", 160))
        smin = int(getattr(config, "det_s_min", 125))
        smax = int(getattr(config, "det_s_max", 255))
        vmin = int(getattr(config, "det_v_min", 150))
        vmax = int(getattr(config, "det_v_max", 255))

        HSV_MIN = np.array(
            [np.clip(hmin, 0, 179), np.clip(smin, 0, 255), np.clip(vmin, 0, 255)],
            dtype=np.uint8,
        )
        HSV_MAX = np.array(
            [np.clip(hmax, 0, 179), np.clip(smax, 0, 255), np.clip(vmax, 0, 255)],
            dtype=np.uint8,
        )

        _model = (HSV_MIN, HSV_MAX)
        color_name = getattr(config, "color", "color")
        _class_names = {"color": f"Target Color: {color_name}"}
        logger.info(f"Detection2 model loaded: {HSV_MIN.tolist()} - {HSV_MAX.tolist()}")
        return _model, _class_names
    except Exception as e:
        logger.exception(f"load_model error: {e}")
        _model, _class_names = None, {}
        return None, {}


def reload_model(model_path: Optional[str] = None):
    return load_model(model_path)


def perform_detection(model, image_bgr: np.ndarray):
    """
    Phát hiện vùng màu trên ảnh BGR theo config det_* (50 parameters).
    Trả về:
      - detections: List[{"class": "body|head", "bbox": (x,y,w,h), "confidence": float, "type": "body|head"}]
      - mask: ndarray (uint8)
    """
    if model is None or image_bgr is None:
        return [], None

    # ===== Đọc tham số từ config (50 parameters) =====
    # HSV range - Body Detection
    body_h_min = float(getattr(config, "det_body_h_min", 30.0))
    body_h_max = float(getattr(config, "det_body_h_max", 160.0))
    body_s_min = float(getattr(config, "det_body_s_min", 125.0))
    body_s_max = float(getattr(config, "det_body_s_max", 255.0))
    body_v_min = float(getattr(config, "det_body_v_min", 150.0))
    body_v_max = float(getattr(config, "det_body_v_max", 255.0))

    # HSV range - Head Detection  
    head_h_min = float(getattr(config, "det_head_h_min", 25.0))
    head_h_max = float(getattr(config, "det_head_h_max", 170.0))
    head_s_min = float(getattr(config, "det_head_s_min", 100.0))
    head_s_max = float(getattr(config, "det_head_s_max", 255.0))
    head_v_min = float(getattr(config, "det_head_v_min", 120.0))
    head_v_max = float(getattr(config, "det_head_v_max", 255.0))

    # Pre-processing
    blur_kernel = int(getattr(config, "det_blur_kernel", 3))
    blur_sigma = float(getattr(config, "det_blur_sigma", 1.0))
    gamma_correction = float(getattr(config, "det_gamma", 1.0))
    brightness = float(getattr(config, "det_brightness", 0.0))
    contrast = float(getattr(config, "det_contrast", 1.0))
    
    # Morphology - Body
    body_close_kw = int(getattr(config, "det_body_close_kw", 15))
    body_close_kh = int(getattr(config, "det_body_close_kh", 30))
    body_dilate_k = int(getattr(config, "det_body_dilate_k", 15))
    body_dilate_iter = int(getattr(config, "det_body_dilate_iter", 1))
    body_erode_k = int(getattr(config, "det_body_erode_k", 3))
    body_erode_iter = int(getattr(config, "det_body_erode_iter", 1))
    
    # Morphology - Head
    head_close_kw = int(getattr(config, "det_head_close_kw", 8))
    head_close_kh = int(getattr(config, "det_head_close_kh", 12))
    head_dilate_k = int(getattr(config, "det_head_dilate_k", 5))
    head_dilate_iter = int(getattr(config, "det_head_dilate_iter", 1))
    head_erode_k = int(getattr(config, "det_head_erode_k", 2))
    head_erode_iter = int(getattr(config, "det_head_erode_iter", 1))

    # Contour filters - Body
    body_min_area = float(getattr(config, "det_body_min_area", 500.0))
    body_max_area = float(getattr(config, "det_body_max_area", 50000.0))
    body_ar_min = float(getattr(config, "det_body_ar_min", 0.3))
    body_ar_max = float(getattr(config, "det_body_ar_max", 3.0))
    body_solidity_min = float(getattr(config, "det_body_solidity_min", 0.5))
    body_extent_min = float(getattr(config, "det_body_extent_min", 0.3))
    
    # Contour filters - Head
    head_min_area = float(getattr(config, "det_head_min_area", 50.0))
    head_max_area = float(getattr(config, "det_head_max_area", 2000.0))
    head_ar_min = float(getattr(config, "det_head_ar_min", 0.6))
    head_ar_max = float(getattr(config, "det_head_ar_max", 1.8))
    head_solidity_min = float(getattr(config, "det_head_solidity_min", 0.7))
    head_extent_min = float(getattr(config, "det_head_extent_min", 0.5))

    # Advanced filters
    edge_threshold1 = float(getattr(config, "det_edge_threshold1", 50.0))
    edge_threshold2 = float(getattr(config, "det_edge_threshold2", 150.0))
    contour_epsilon = float(getattr(config, "det_contour_epsilon", 0.02))
    min_contour_points = int(getattr(config, "det_min_contour_points", 5))
    
    # Merge / Confidence / Validation
    merge_dist = float(getattr(config, "det_merge_dist", 250.0))
    iou_thr = float(getattr(config, "det_iou_thr", 0.1))
    body_conf_thr = float(getattr(config, "det_body_conf_thr", 0.02))
    head_conf_thr = float(getattr(config, "det_head_conf_thr", 0.05))
    vline_min_h = float(getattr(config, "det_vline_min_h", 5.0))
    
    # Position validation
    head_body_ratio = float(getattr(config, "det_head_body_ratio", 0.3))  # head should be ~30% of body size
    head_position_ratio = float(getattr(config, "det_head_position_ratio", 0.25))  # head in top 25% of body

    # ===== Tiền xử lý ảnh =====
    img = _normalize_lighting(image_bgr)
    
    # Apply brightness/contrast
    if brightness != 0.0 or contrast != 1.0:
        img = cv2.convertScaleAbs(img, alpha=contrast, beta=brightness)
    
    # Apply gamma correction
    if gamma_correction != 1.0:
        gamma_table = np.array([((i / 255.0) ** (1.0 / gamma_correction)) * 255 for i in np.arange(0, 256)]).astype("uint8")
        img = cv2.LUT(img, gamma_table)
    
    # Apply blur if needed
    if blur_kernel > 1:
        if blur_sigma > 0:
            img = cv2.GaussianBlur(img, (blur_kernel, blur_kernel), blur_sigma)
        else:
            img = cv2.blur(img, (blur_kernel, blur_kernel))

    # ===== Tạo mask HSV cho Body và Head =====
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Body mask
    BODY_HSV_MIN = np.array([np.clip(body_h_min, 0, 179), np.clip(body_s_min, 0, 255), np.clip(body_v_min, 0, 255)], dtype=np.uint8)
    BODY_HSV_MAX = np.array([np.clip(body_h_max, 0, 179), np.clip(body_s_max, 0, 255), np.clip(body_v_max, 0, 255)], dtype=np.uint8)
    body_mask = cv2.inRange(hsv, BODY_HSV_MIN, BODY_HSV_MAX)
    
    # Head mask  
    HEAD_HSV_MIN = np.array([np.clip(head_h_min, 0, 179), np.clip(head_s_min, 0, 255), np.clip(head_v_min, 0, 255)], dtype=np.uint8)
    HEAD_HSV_MAX = np.array([np.clip(head_h_max, 0, 179), np.clip(head_s_max, 0, 255), np.clip(head_v_max, 0, 255)], dtype=np.uint8)
    head_mask = cv2.inRange(hsv, HEAD_HSV_MIN, HEAD_HSV_MAX)

    # ===== Morphology cho Body =====
    def apply_morphology(mask, close_kw, close_kh, dilate_k, dilate_iter, erode_k, erode_iter):
        # Close operation
        if close_kw > 0 and close_kh > 0:
            kernel_close = np.ones((max(1, close_kh), max(1, close_kw)), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=1)
        
        # Erosion
        if erode_iter > 0 and erode_k > 0:
            kernel_erode = np.ones((max(1, erode_k), max(1, erode_k)), np.uint8)
            mask = cv2.erode(mask, kernel_erode, iterations=erode_iter)
        
        # Dilation
        if dilate_iter > 0 and dilate_k > 0:
            kernel_dilate = np.ones((max(1, dilate_k), max(1, dilate_k)), np.uint8)
            mask = cv2.dilate(mask, kernel_dilate, iterations=dilate_iter)
        
        return mask
    
    # Apply morphology to both masks
    body_mask = apply_morphology(body_mask, body_close_kw, body_close_kh, body_dilate_k, body_dilate_iter, body_erode_k, body_erode_iter)
    head_mask = apply_morphology(head_mask, head_close_kw, head_close_kh, head_dilate_k, head_dilate_iter, head_erode_k, head_erode_iter)

    # ===== Advanced contour analysis =====
    def analyze_contour(contour, mask, min_area, max_area, ar_min, ar_max, solidity_min, extent_min, conf_thr, detection_type):
        """Analyze contour with advanced filters"""
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        
        # Basic area filter
        if area < min_area or area > max_area:
            return None
            
        # Aspect ratio
        ar = w / max(1.0, float(h))
        if ar < ar_min or ar > ar_max:
            return None
            
        # Solidity (convex hull ratio)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        if solidity < solidity_min:
            return None
            
        # Extent (contour area vs bounding rect area)
        rect_area = w * h
        extent = area / rect_area if rect_area > 0 else 0
        if extent < extent_min:
            return None
            
        # Vertical line check
        cx = int(x + w * 0.5)
        if not _has_color_vertical_line(mask, cx, y, y + h, int(vline_min_h)):
            return None
            
        # Confidence (pixel density in bbox)
        sub = mask[y : y + h, x : x + w]
        bbox_conf = (sub > 0).sum() / max(1, sub.size)
        if bbox_conf < conf_thr:
            return None
            
        # Edge detection validation
        if edge_threshold1 > 0 and edge_threshold2 > 0:
            roi_gray = cv2.cvtColor(img[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(roi_gray, edge_threshold1, edge_threshold2)
            edge_density = np.sum(edges > 0) / (w * h)
            if edge_density < 0.01:  # Too few edges, might be noise
                return None
                
        return {
            "class": detection_type,
            "bbox": (x, y, w, h),
            "confidence": float(bbox_conf),
            "type": detection_type,
            "area": float(area),
            "solidity": float(solidity),
            "extent": float(extent),
            "aspect_ratio": float(ar)
        }
    
    # ===== Process Body Detections =====
    body_contours, _ = cv2.findContours(body_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    body_detections = []
    
    for contour in body_contours:
        if len(contour) < min_contour_points:
            continue
            
        # Approximate contour to reduce points
        epsilon = contour_epsilon * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        detection = analyze_contour(
            approx, body_mask, body_min_area, body_max_area, 
            body_ar_min, body_ar_max, body_solidity_min, body_extent_min,
            body_conf_thr, "body"
        )
        if detection:
            body_detections.append(detection)
    
    # ===== Process Head Detections =====
    head_contours, _ = cv2.findContours(head_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    head_detections = []
    
    for contour in head_contours:
        if len(contour) < min_contour_points:
            continue
            
        epsilon = contour_epsilon * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        detection = analyze_contour(
            approx, head_mask, head_min_area, head_max_area,
            head_ar_min, head_ar_max, head_solidity_min, head_extent_min, 
            head_conf_thr, "head"
        )
        if detection:
            head_detections.append(detection)
    
    # ===== Validate Head-Body Relationships =====
    validated_detections = []
    
    # Add all body detections
    for body_det in body_detections:
        validated_detections.append(body_det)
        
        # Find associated heads
        bx, by, bw, bh = body_det["bbox"]
        body_center = (bx + bw//2, by + bh//2)
        
        for head_det in head_detections:
            hx, hy, hw, hh = head_det["bbox"]
            head_center = (hx + hw//2, hy + hh//2)
            
            # Check if head is in reasonable position relative to body
            head_in_body_top = hy < (by + bh * head_position_ratio)
            head_reasonable_size = (hw * hh) < (bw * bh * head_body_ratio)
            
            if head_in_body_top and head_reasonable_size:
                # This head belongs to this body
                head_det["parent_body"] = body_det
                validated_detections.append(head_det)
    
    # Add orphan heads (heads without associated bodies)
    for head_det in head_detections:
        if "parent_body" not in head_det:
            validated_detections.append(head_det)
    
    # ===== Merge overlapping detections of same type =====
    body_rects = [(d["bbox"], d) for d in validated_detections if d["type"] == "body"]
    head_rects = [(d["bbox"], d) for d in validated_detections if d["type"] == "head"]
    
    merged_bodies = _merge_close_rects([r[0] for r in body_rects], iou_thr=iou_thr, dist_thr=merge_dist)
    merged_heads = _merge_close_rects([r[0] for r in head_rects], iou_thr=iou_thr, dist_thr=merge_dist)
    
    # Reconstruct detections with merged bboxes
    final_detections = []
    
    for merged_bbox in merged_bodies:
        final_detections.append({
            "class": "body",
            "bbox": merged_bbox,
            "confidence": 1.0,
            "type": "body"
        })
        
    for merged_bbox in merged_heads:
        final_detections.append({
            "class": "head", 
            "bbox": merged_bbox,
            "confidence": 1.0,
            "type": "head"
        })
    
    # Combine masks for visualization
    combined_mask = cv2.bitwise_or(body_mask, head_mask)
    
    return final_detections, combined_mask


# =========================
# Helpers (optional)
# =========================
def get_class_names():
    return _class_names
