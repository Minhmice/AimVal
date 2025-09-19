# hsv_detector.py
import json
import math
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import cv2
import numpy as np
from config import config

# =========================
# Logging setup
# =========================
LOG_LEVEL = getattr(config, "log_level", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("HSVDetector")

# =========================
# Globals / State
# =========================
# _models: {color_name: (HSV_MIN ndarray, HSV_MAX ndarray)}
_models: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
_class_names: Dict[str, str] = {}
HSV_MIN = None  # Kept for backward-compat (single color)
HSV_MAX = None  # Kept for backward-compat (single color)

# Tracker state (optional, if user wants cross-frame IDs)
_tracker = None


# =========================
# GPU helpers (optional)
# =========================
def _have_cuda():
    return getattr(config, "use_cuda", False) and hasattr(cv2, "cuda")


def _cuda_inrange(hsv_gpu, lower: np.ndarray, upper: np.ndarray):
    # OpenCV CUDA inRange uses cv2.cuda.compare + logical ops; simpler path:
    # Fallback to CPU if not convenient
    hsv = hsv_gpu.download()
    mask = cv2.inRange(hsv, lower, upper)
    return cv2.cuda_GpuMat().upload(mask) if _have_cuda() else mask


def _to_hsv(img_bgr: np.ndarray):
    if _have_cuda():
        try:
            gpu = cv2.cuda_GpuMat()
            gpu.upload(img_bgr)
            hsv_gpu = cv2.cuda.cvtColor(gpu, cv2.COLOR_BGR2HSV)
            return hsv_gpu
        except Exception as e:
            logger.warning(f"CUDA path failed, fallback CPU: {e}")
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)


def _morph(mask, kernel_size=(3, 3), op="close", iterations=1, dilate_after=None):
    kernel = np.ones(kernel_size, np.uint8)
    if _have_cuda() and isinstance(mask, cv2.cuda_GpuMat):
        # CUDA morphology is limited; fallback to CPU for reliability
        mask_cpu = mask.download()
        mask_cpu = cv2.morphologyEx(mask_cpu, cv2.MORPH_CLOSE if op == "close" else cv2.MORPH_OPEN, kernel, iterations=iterations)
        if dilate_after:
            mask_cpu = cv2.dilate(mask_cpu, np.ones(dilate_after, np.uint8), iterations=1)
        return mask_cpu
    else:
        mask_cpu = mask if isinstance(mask, np.ndarray) else mask.download()
        mask_cpu = cv2.morphologyEx(mask_cpu, cv2.MORPH_CLOSE if op == "close" else cv2.MORPH_OPEN, kernel, iterations=iterations)
        if dilate_after:
            mask_cpu = cv2.dilate(mask_cpu, np.ones(dilate_after, np.uint8), iterations=1)
        return mask_cpu


# =========================
# CLAHE / lighting normalization
# =========================
def _normalize_lighting(bgr: np.ndarray) -> np.ndarray:
    """
    Optional pre-processing: CLAHE on V channel (HSV) to stabilize lighting.
    """
    use_clahe = getattr(config, "use_clahe", True)
    if not use_clahe:
        return bgr

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    clahe = cv2.createCLAHE(clipLimit=getattr(config, "clahe_clip", 2.0), tileGridSize=(8, 8))
    v2 = clahe.apply(v)
    hsv2 = cv2.merge([h, s, v2])
    return cv2.cvtColor(hsv2, cv2.COLOR_HSV2BGR)


# =========================
# Config loading
# =========================
def _load_hsv_from_json(path: str) -> Dict[str, List[int]]:
    """
    JSON format:
    {
      "yellow": [hmin, smin, vmin, hmax, smax, vmax],
      "purple": [ ... ]
    }
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"HSV config JSON not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # basic validation
    for name, arr in data.items():
        if not (isinstance(arr, list) and len(arr) == 6):
            raise ValueError(f"Invalid HSV array for '{name}': expect 6 integers")
    return data


# =========================
# Auto-calibration HSV
# =========================
def autocalibrate_hsv_from_samples(bgr_samples: np.ndarray, margin=(5, 30, 30)) -> Tuple[np.ndarray, np.ndarray]:
    """
    bgr_samples: ndarray of shape (N, 3) or (H, W, 3) with selected pixels.
    margin: (h, s, v) margin around mean HSV to create a robust range.

    Returns: (HSV_MIN, HSV_MAX)
    """
    if bgr_samples.ndim == 2 and bgr_samples.shape[1] == 3:
        bgr = bgr_samples.reshape(-1, 1, 3).astype(np.uint8)
    else:
        bgr = bgr_samples.astype(np.uint8)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hsv_flat = hsv.reshape(-1, 3).astype(np.int32)

    h_mean, s_mean, v_mean = hsv_flat.mean(axis=0)
    h_std, s_std, v_std = hsv_flat.std(axis=0)

    # range around mean ± (k*std + margin)
    k = getattr(config, "autocalib_std_scale", 1.0)
    h_low = max(0, int(h_mean - k * h_std - margin[0]))
    s_low = max(0, int(s_mean - k * s_std - margin[1]))
    v_low = max(0, int(v_mean - k * v_std - margin[2]))

    h_high = min(179, int(h_mean + k * h_std + margin[0]))
    s_high = min(255, int(s_mean + k * s_std + margin[1]))
    v_high = min(255, int(v_mean + k * v_std + margin[2]))

    HSV_MIN = np.array([h_low, s_low, v_low], dtype=np.uint8)
    HSV_MAX = np.array([h_high, s_high, v_high], dtype=np.uint8)
    return HSV_MIN, HSV_MAX


# =========================
# Public API: test()
# =========================
def test():
    logger.info("HSV Detection test initialized")
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    hsv_img = cv2.cvtColor(dummy_img, cv2.COLOR_BGR2HSV)
    logger.info("HSV conversion done")


# =========================
# Public API: load_model / reload_model
# =========================
def load_model(model_path: Optional[str] = None):
    """
    Loads HSV ranges into _models (support multi-color).
    Priority:
      1) If config.hsv_config_path is present -> load JSON
      2) Else fall back to built-ins (yellow/purple) or config.color list

    Backward-compat:
      - sets global HSV_MIN/HSV_MAX if a single color is effectively chosen.
    """
    global _models, _class_names, HSV_MIN, HSV_MAX
    config.model_load_error = ""
    _models = {}
    _class_names = {}
    HSV_MIN = None
    HSV_MAX = None

    try:
        logger.info("Loading HSV parameters...")

        # 1) Try JSON config
        hsv_path = getattr(config, "hsv_config_path", None) or model_path
        if hsv_path:
            data = _load_hsv_from_json(hsv_path)
            for name, arr in data.items():
                _models[name] = (
                    np.array(arr[:3], dtype=np.uint8),
                    np.array(arr[3:], dtype=np.uint8),
                )
                _class_names[name] = f"Target Color: {name}"

        # 2) Fallback built-ins if nothing loaded
        if not _models:
            yellow = [30, 125, 150, 30, 255, 255]
            purple = [144, 106, 172, 160, 255, 255]
            builtin_colors = {"yellow": yellow, "purple": purple}

            # If user specified colors
            colors = getattr(config, "colors", None)  # e.g., ["yellow", "purple"]
            if isinstance(colors, (list, tuple)) and len(colors) > 0:
                for name in colors:
                    if name not in builtin_colors:
                        raise ValueError(f"Unknown color '{name}' in config.colors")
                    arr = builtin_colors[name]
                    _models[name] = (np.array(arr[:3], np.uint8), np.array(arr[3:], np.uint8))
                    _class_names[name] = f"Target Color: {name}"
            else:
                # Single color (back-compat with config.color)
                color = getattr(config, "color", "yellow")
                if color not in builtin_colors:
                    raise ValueError(f"Unknown color {color}")
                arr = builtin_colors[color]
                _models[color] = (np.array(arr[:3], np.uint8), np.array(arr[3:], np.uint8))
                _class_names[color] = f"Target Color: {color}"

        # Backward-compat single color
        if len(_models) == 1:
            only = next(iter(_models.values()))
            HSV_MIN, HSV_MAX = only

        config.model_classes = list(_class_names.values())
        config.model_file_size = 0
        logger.info(f"Loaded colors: {list(_models.keys())}")
        return _models, _class_names

    except Exception as e:
        config.model_load_error = f"Failed to load HSV params: {e}"
        _models, _class_names = {}, {}
        logger.exception(config.model_load_error)
        return None, {}


def reload_model(model_path: Optional[str] = None):
    return load_model(model_path)


# =========================
# Geometry / Merge
# =========================
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
    return (x + w / 2.0, y + h / 2.0)


def _dist(c1, c2):
    return math.hypot(c1[0] - c2[0], c1[1] - c2[1])


def merge_close_rects(rects: List[Tuple[int, int, int, int]],
                      iou_threshold: float = 0.1,
                      dist_threshold: float = None) -> List[Tuple[int, int, int, int]]:
    """
    Merge rectangles if they significantly overlap (IOU) OR are close by center distance.
    Uses a simple agglomerative approach.
    """
    if not rects:
        return []

    if dist_threshold is None:
        dist_threshold = float(getattr(config, "merge_distance", 250))

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
            if _iou(base, r2) >= iou_threshold or _dist(_center(base), _center(r2)) <= dist_threshold:
                group.append(j)
                # expand base to include r2
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
# Vertical line check (kept)
# =========================
def has_color_vertical_line(mask: np.ndarray, x: int, y1: int, y2: int) -> bool:
    line = mask[y1:y2, x]
    return np.any(line > 0)


# =========================
# Triggerbot with confidence
# =========================
def triggerbot_detect(model, roi: np.ndarray, return_confidence: bool = True):
    """
    Checks color presence in ROI.
    If return_confidence=True, returns dict: {"detected": bool, "confidence": float, "count": int}
    Else returns bool (backward-compat).
    """
    if model is None or roi is None:
        return {"detected": False, "confidence": 0.0, "count": 0} if return_confidence else False

    # If multi-color model, union all masks
    roi_proc = _normalize_lighting(roi)
    hsv_roi = _to_hsv(roi_proc)
    masks = []
    if isinstance(model, dict):
        # model: {color: (min, max)}
        for (mn, mx) in model.values():
            if _have_cuda() and isinstance(hsv_roi, cv2.cuda_GpuMat):
                mask_gpu = _cuda_inrange(hsv_roi, mn, mx)
                mask = mask_gpu.download()
            else:
                hsv_cpu = hsv_roi if isinstance(hsv_roi, np.ndarray) else hsv_roi.download()
                mask = cv2.inRange(hsv_cpu, mn, mx)
            masks.append(mask)
        mask = np.clip(sum(masks), 0, 255).astype(np.uint8) if masks else None
    else:
        # tuple (HSV_MIN, HSV_MAX)
        hsv_cpu = hsv_roi if isinstance(hsv_roi, np.ndarray) else hsv_roi.download()
        mask = cv2.inRange(hsv_cpu, model[0], model[1])

    mask = _morph(mask, kernel_size=(3, 3), op="close", iterations=1)

    total = mask.size
    pos = int((mask > 0).sum())
    conf = pos / total if total > 0 else 0.0
    detected = pos > 0

    if return_confidence:
        return {"detected": detected, "confidence": float(conf), "count": pos}
    return detected


# =========================
# Detection per frame (multi-color)
# =========================
def perform_detection(model, image: np.ndarray):
    """
    Detect colored regions; supports multi-color.
    Returns (detections, combined_mask)
    detections: [{"class": <color>, "bbox": (x,y,w,h), "confidence": 1.0}, ...]
    """
    if model is None:
        return None

    img_proc = _normalize_lighting(image)
    hsv_img = _to_hsv(img_proc)

    color_masks = {}
    combined = None

    # Build masks per color
    if isinstance(model, dict):
        items = model.items()
    else:
        # single color back-compat
        items = [("color", model)]

    for color, (mn, mx) in items:
        if _have_cuda() and isinstance(hsv_img, cv2.cuda_GpuMat):
            mask = _cuda_inrange(hsv_img, mn, mx)
            mask = mask.download()
        else:
            hsv_cpu = hsv_img if isinstance(hsv_img, np.ndarray) else hsv_img.download()
            mask = cv2.inRange(hsv_cpu, mn, mx)

        # Morphology (adaptive kernel size based on resolution)
        H, W = mask.shape[:2]
        kh = max(3, int(max(H, W) * 0.02))  # ~2% of larger dim
        kw = max(3, int(max(H, W) * 0.01))
        mask = _morph(mask, kernel_size=(kh, kw), op="close", iterations=1, dilate_after=(kh, kw))

        color_masks[color] = mask
        combined = mask if combined is None else np.clip(combined + mask, 0, 255)

    detections = []
    for color, mask in color_masks.items():
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw_rects = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            cx, cy = x + w // 2, y + h // 2
            if not has_color_vertical_line(mask, cx, y, y + h):
                continue
            raw_rects.append((x, y, w, h))

        merged_rects = merge_close_rects(raw_rects)
        for r in merged_rects:
            detections.append({"class": color, "bbox": r, "confidence": 1.0})

    return detections, combined


# =========================
# Simple Centroid Tracker
# =========================
class CentroidTracker:
    def __init__(self, max_disappeared=10, max_distance=300.0):
        self.next_id = 1
        self.objects = {}         # id -> (cx, cy, bbox, cls)
        self.disappeared = {}     # id -> count
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    def _centroid(self, bbox):
        x, y, w, h = bbox
        return (x + w / 2.0, y + h / 2.0)

    def update(self, detections: List[Dict]):
        # If no detections, mark disappearances
        if len(detections) == 0:
            for oid in list(self.disappeared.keys()):
                self.disappeared[oid] += 1
                if self.disappeared[oid] > self.max_disappeared:
                    self.objects.pop(oid, None)
                    self.disappeared.pop(oid, None)
            return self.objects

        # Build arrays of current centroids
        input_centroids = []
        input_infos = []
        for det in detections:
            c = self._centroid(det["bbox"])
            input_centroids.append(c)
            input_infos.append(det)

        if len(self.objects) == 0:
            # Register all
            for det, c in zip(input_infos, input_centroids):
                oid = self.next_id
                self.next_id += 1
                self.objects[oid] = (c[0], c[1], det["bbox"], det.get("class", "color"))
                self.disappeared[oid] = 0
            return self.objects

        # Match by nearest neighbor (greedy)
        obj_ids = list(self.objects.keys())
        obj_centroids = np.array([(self.objects[i][0], self.objects[i][1]) for i in obj_ids], dtype=np.float32)
        inp_centroids = np.array(input_centroids, dtype=np.float32)

        # Distance matrix
        D = np.sqrt(((obj_centroids[:, None, :] - inp_centroids[None, :, :]) ** 2).sum(axis=2))

        used_rows = set()
        used_cols = set()

        # For each object, find best match input
        while True:
            if D.size == 0:
                break
            r, c = np.unravel_index(np.argmin(D), D.shape)
            if r in used_rows or c in used_cols:
                D[r, c] = np.inf
                if not np.isfinite(D).any():
                    break
                continue
            if D[r, c] > self.max_distance:
                D[r, c] = np.inf
                if not np.isfinite(D).any():
                    break
                continue

            oid = obj_ids[r]
            det = input_infos[c]
            cx, cy = input_centroids[c]
            self.objects[oid] = (cx, cy, det["bbox"], det.get("class", "color"))
            self.disappeared[oid] = 0

            used_rows.add(r)
            used_cols.add(c)

            D[r, :] = np.inf
            D[:, c] = np.inf
            if not np.isfinite(D).any():
                break

        # Any unmatched objects -> increment disappeared
        for i, oid in enumerate(obj_ids):
            if i not in used_rows:
                self.disappeared[oid] += 1
                if self.disappeared[oid] > self.max_disappeared:
                    self.objects.pop(oid, None)
                    self.disappeared.pop(oid, None)

        # Any unmatched inputs -> register as new
        for j, det in enumerate(input_infos):
            if j not in used_cols:
                oid = self.next_id
                self.next_id += 1
                cx, cy = input_centroids[j]
                self.objects[oid] = (cx, cy, det["bbox"], det.get("class", "color"))
                self.disappeared[oid] = 0

        return self.objects


def get_tracker(create_if_missing=True):
    global _tracker
    if _tracker is None and create_if_missing:
        _tracker = CentroidTracker(
            max_disappeared=getattr(config, "track_max_disappeared", 10),
            max_distance=float(getattr(config, "track_max_distance", 300.0)),
        )
    return _tracker


def track_detections(detections: List[Dict], tracker: Optional[CentroidTracker] = None):
    """
    Update tracker with current detections, return dict: id -> (cx, cy, bbox, class)
    """
    tr = tracker or get_tracker(True)
    return tr.update(detections or [])


# =========================
# Visualization
# =========================
def draw_detections(image: np.ndarray,
                    detections: List[Dict],
                    tracked: Optional[Dict[int, Tuple[float, float, Tuple[int, int, int, int], str]]] = None):
    """
    Draw bounding boxes, color labels, and optional track IDs.
    """
    out = image.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    for det in detections or []:
        x, y, w, h = det["bbox"]
        cls = det.get("class", "color")
        conf = det.get("confidence", 1.0)
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(out, f"{cls} {conf:.2f}", (x, y - 6), font, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

    if tracked:
        for tid, (cx, cy, bbox, cls) in tracked.items():
            x, y, w, h = bbox
            cv2.putText(out, f"ID {tid}", (x, y - 22), font, 0.5, (255, 255, 0), 1, cv2.LINE_AA)
            cv2.circle(out, (int(cx), int(cy)), 3, (255, 255, 0), -1)

    return out


# =========================
# Helpers (kept)
# =========================
def get_class_names():
    return _class_names


def get_model_size(model_path=None):
    return 0
