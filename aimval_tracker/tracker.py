from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import TrackerConfig, HSVRange, ROI


def _apply_roi(frame: np.ndarray, roi: ROI) -> Tuple[np.ndarray, Tuple[int, int]]:
    h, w = frame.shape[:2]
    x = max(0, roi.x)
    y = max(0, roi.y)
    rw = roi.w if roi.w is not None else (w - x)
    rh = roi.h if roi.h is not None else (h - y)
    rw = max(1, min(rw, w - x))
    rh = max(1, min(rh, h - y))
    return frame[y : y + rh, x : x + rw], (x, y)


class HSVTracker:
    def __init__(self, cfg: TrackerConfig) -> None:
        self.cfg = cfg
        self._morph_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (max(1, cfg.morph_kernel), max(1, cfg.morph_kernel))
        )

    def process(self, frame_bgr: np.ndarray) -> Tuple[Optional[Tuple[int, int]], np.ndarray, Tuple[int, int, int, int]]:
        """Return (target_point or None, debug_mask_bgr, roi_rect).

        roi_rect = (x, y, w, h) in full-frame coordinates.
        """
        if self.cfg.use_roi:
            roi_img, (ox, oy) = _apply_roi(frame_bgr, self.cfg.roi)
        else:
            roi_img, (ox, oy) = frame_bgr, (0, 0)

        img = roi_img
        if self.cfg.blur_kernel and self.cfg.blur_kernel > 1:
            k = int(self.cfg.blur_kernel) | 1
            img = cv2.GaussianBlur(img, (k, k), 0)

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h = self.cfg.hsv
        # Support hue wrap-around (e.g., red: h_low=170, h_high=10)
        if h.h_low <= h.h_high:
            lower = np.array([h.h_low, h.s_low, h.v_low], dtype=np.uint8)
            upper = np.array([h.h_high, h.s_high, h.v_high], dtype=np.uint8)
            mask = cv2.inRange(hsv, lower, upper)
        else:
            lower1 = np.array([0, h.s_low, h.v_low], dtype=np.uint8)
            upper1 = np.array([h.h_high, h.s_high, h.v_high], dtype=np.uint8)
            lower2 = np.array([h.h_low, h.s_low, h.v_low], dtype=np.uint8)
            upper2 = np.array([179, h.s_high, h.v_high], dtype=np.uint8)
            mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._morph_kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._morph_kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_c = None
        best_area = 0
        for c in contours:
            area = cv2.contourArea(c)
            if area >= self.cfg.min_area and area > best_area:
                best_area = area
                best_c = c

        centroid: Optional[Tuple[int, int]] = None
        topmost: Optional[Tuple[int, int]] = None
        bbox_topcenter: Optional[Tuple[int, int]] = None
        if best_c is not None:
            m = cv2.moments(best_c)
            if m["m00"] != 0:
                cx = int(m["m10"] / m["m00"]) + ox
                cy = int(m["m01"] / m["m00"]) + oy
                centroid = (cx, cy)
            # Topmost point in image coordinates (min y)
            ys = best_c[:, 0, 1]
            idx = int(np.argmin(ys))
            tx = int(best_c[idx, 0, 0]) + ox
            ty = int(best_c[idx, 0, 1]) + oy
            topmost = (tx, ty)
            # Bounding box top-center
            x, y, w, h = cv2.boundingRect(best_c)
            bbox_topcenter = (x + w // 2 + ox, y + oy)

        # Debug mask to BGR
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        if best_c is not None:
            cv2.drawContours(mask_bgr, [best_c], -1, (0, 255, 0), 2, offset=(ox, oy))
            if centroid is not None:
                cv2.circle(mask_bgr, centroid, 4, (0, 0, 255), -1)
            if topmost is not None:
                cv2.circle(mask_bgr, topmost, 4, (255, 0, 255), -1)
            if bbox_topcenter is not None:
                cv2.circle(mask_bgr, bbox_topcenter, 4, (255, 255, 0), -1)

        # Pick according to target_mode
        target: Optional[Tuple[int, int]]
        mode = (self.cfg.target_mode or "centroid").lower()
        if mode == "topmost":
            target = topmost or centroid
        elif mode == "bbox_topcenter":
            target = bbox_topcenter or centroid
        else:
            target = centroid

        roi_rect = (ox, oy, mask.shape[1], mask.shape[0])
        return target, mask_bgr, roi_rect


