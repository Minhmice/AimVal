import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from .base import Box, Detector


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = max(1, area_a + area_b - inter)
    return inter / union


def _merge_by_iou(boxes: List[Box], thr: float) -> List[Box]:
    if not boxes:
        return []
    merged: List[Box] = []
    used = [False] * len(boxes)
    xyxy = [b.as_xyxy() for b in boxes]
    for i, bi in enumerate(boxes):
        if used[i]:
            continue
        group = [i]
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            if _iou(xyxy[i], xyxy[j]) >= thr:
                group.append(j)
        # merge group by min/max
        x1 = min(xyxy[k][0] for k in group)
        y1 = min(xyxy[k][1] for k in group)
        x2 = max(xyxy[k][2] for k in group)
        y2 = max(xyxy[k][3] for k in group)
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        score = float(np.mean([boxes[k].score for k in group]))
        merged.append(Box(x1, y1, w, h, label="hsv", score=score, source="hsv"))
        for k in group:
            used[k] = True
    return merged


class HSVColorDetector(Detector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = bool(config.get("enabled", True))
        self.lower = np.array(config.get("lower", [20, 100, 100]), dtype=np.uint8)
        self.upper = np.array(config.get("upper", [35, 255, 255]), dtype=np.uint8)
        self.kernel_size = int(config.get("morph_kernel", 3))
        self.min_area = int(config.get("min_area", 150))
        self.merge_iou = float(config.get("merge_iou", 0.2))
        self.profiles = config.get("profiles", {})

    def set_profile(self, name: str):
        rng = self.profiles.get(name)
        if rng:
            self.lower = np.array(rng[0], dtype=np.uint8)
            self.upper = np.array(rng[1], dtype=np.uint8)

    def infer(self, bgr) -> Tuple[List[Box], Dict[str, Any]]:
        if not self.enabled or bgr is None:
            return [], {}
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower, self.upper)
        k = max(1, self.kernel_size)
        kernel = np.ones((k, k), np.uint8)
        # closing to fill gaps then small open to reduce noise
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        if k >= 3:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: List[Box] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            boxes.append(Box(x, y, w, h, label="hsv", score=1.0, source="hsv"))
        boxes = _merge_by_iou(boxes, self.merge_iou)
        return boxes, {"mask": mask}
