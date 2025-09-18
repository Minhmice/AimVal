import cv2
import numpy as np
from typing import List, Optional
from detectors.base import Box


def draw_boxes(img, boxes: List[Box], thickness: int = 2, font_scale: float = 0.5):
    color_map = {
        "hsv": (0, 255, 0),
        "ai": (0, 165, 255),
        "fused": (255, 0, 0),
    }
    for b in boxes:
        x1, y1, x2, y2 = b.as_xyxy()
        color = color_map.get(b.source, (255, 255, 255))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        label = f"{b.label}:{b.score:.2f}"
        if b.track_id is not None:
            label = f"ID{b.track_id} " + label
        cv2.putText(img, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 1, cv2.LINE_AA)
    return img


def dual_view(overlay_bgr, mask_gray: Optional[np.ndarray]):
    if mask_gray is None:
        return overlay_bgr
    if len(mask_gray.shape) == 2:
        mask_bgr = cv2.cvtColor(mask_gray, cv2.COLOR_GRAY2BGR)
    else:
        mask_bgr = mask_gray
    h = max(overlay_bgr.shape[0], mask_bgr.shape[0])
    scale_overlay = h / overlay_bgr.shape[0]
    scale_mask = h / mask_bgr.shape[0]
    ov = cv2.resize(overlay_bgr, (int(overlay_bgr.shape[1] * scale_overlay), h))
    mk = cv2.resize(mask_bgr, (int(mask_bgr.shape[1] * scale_mask), h))
    return np.hstack([ov, mk])
