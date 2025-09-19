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
    Phát hiện vùng màu trên ảnh BGR theo config det_*.
    Trả về:
      - detections: List[{"class": "color", "bbox": (x,y,w,h), "confidence": 1.0}]
      - mask: ndarray (uint8)
    """
    if model is None or image_bgr is None:
        return [], None

    # ===== Đọc tham số từ config (20 sliders) =====
    # HSV range
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

    # Morphology
    close_kw = int(getattr(config, "det_close_kw", 15))
    close_kh = int(getattr(config, "det_close_kh", 30))
    dilate_k = int(getattr(config, "det_dilate_k", 15))
    dilate_iter = int(getattr(config, "det_dilate_iter", 1))

    # Contour filters
    min_area = int(getattr(config, "det_min_area", 80))
    max_area = int(getattr(config, "det_max_area", 200000))
    ar_min = float(getattr(config, "det_ar_min", 0.2))
    ar_max = float(getattr(config, "det_ar_max", 5.0))

    # Merge / Vline / Confidence
    merge_dist = float(getattr(config, "det_merge_dist", 250))
    iou_thr = float(getattr(config, "det_iou_thr", 0.1))
    conf_thr = float(
        getattr(config, "det_conf_thr", 0.02)
    )  # 2% pixel > 0 coi là có màu
    vline_min_h = int(getattr(config, "det_vline_min_h", 5))

    # ===== Tiền xử lý ánh sáng nếu cần =====
    img = _normalize_lighting(image_bgr)

    # ===== Tạo mask HSV =====
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, HSV_MIN, HSV_MAX)

    # ===== Morphology (đảm bảo kích thước kernel hợp lệ) =====
    close_kw = max(1, int(close_kw))
    close_kh = max(1, int(close_kh))
    dilate_k = max(1, int(dilate_k))
    dilate_iter = max(0, int(dilate_iter))

    kernel_close = np.ones((close_kh, close_kw), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=1)
    if dilate_iter > 0:
        kernel_dilate = np.ones((dilate_k, dilate_k), np.uint8)
        mask = cv2.dilate(mask, kernel_dilate, iterations=dilate_iter)

    # ===== Confidence toàn ảnh (tùy mục đích tham khảo) =====
    # (không dùng để quyết định trigger; chỉ hỗ trợ hiển thị)
    total_px = mask.size
    conf_img = (int((mask > 0).sum()) / total_px) if total_px > 0 else 0.0
    # Có thể log nhẹ:
    # logger.debug(f"[Detection] global confidence ~ {conf_img:.3f}")

    # ===== Tìm contours =====
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < min_area or area > max_area:
            continue
        ar = w / max(1.0, float(h))
        if ar < ar_min or ar > ar_max:
            continue

        # vertical line check
        cx = int(x + w * 0.5)
        if not _has_color_vertical_line(mask, cx, y, y + h, vline_min_h):
            continue

        # Optional: confidence theo bbox (tỷ lệ pixel >0 trong bbox)
        sub = mask[y : y + h, x : x + w]
        bbox_conf = (sub > 0).sum() / max(1, sub.size)
        if bbox_conf < conf_thr:
            continue

        rects.append((x, y, w, h))

    # ===== Gộp các bbox gần nhau =====
    merged = _merge_close_rects(rects, iou_thr=iou_thr, dist_thr=merge_dist)

    detections = [{"class": "color", "bbox": r, "confidence": 1.0} for r in merged]
    return detections, mask


# =========================
# Helpers (optional)
# =========================
def get_class_names():
    return _class_names
