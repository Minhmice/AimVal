from typing import List, Dict, Tuple
from collections import deque
from detectors.base import Box


def iou_xyxy(a, b) -> float:
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


class LightTracker:
    def __init__(self, iou_thr: float = 0.3, trails: bool = False, trail_len: int = 20):
        self.iou_thr = float(iou_thr)
        self.trails = bool(trails)
        self.next_id = 1
        self.prev: List[Box] = []
        self.trail_map: Dict[int, deque] = {}
        self.trail_len = int(trail_len)

    def update(self, boxes: List[Box]) -> List[Box]:
        # Assign by best IoU to previous
        used_prev = set()
        for b in boxes:
            best_iou = 0.0
            best_idx = -1
            bxy = b.as_xyxy()
            for i, p in enumerate(self.prev):
                if i in used_prev:
                    continue
                iou = iou_xyxy(bxy, p.as_xyxy())
                if iou > best_iou:
                    best_iou = iou
                    best_idx = i
            if best_idx >= 0 and best_iou >= self.iou_thr:
                b.track_id = self.prev[best_idx].track_id
                used_prev.add(best_idx)
            else:
                b.track_id = self.next_id
                self.next_id += 1
            if self.trails and b.track_id is not None:
                cx = b.x + b.w // 2
                cy = b.y + b.h // 2
                dq = self.trail_map.get(b.track_id)
                if dq is None:
                    dq = deque(maxlen=self.trail_len)
                    self.trail_map[b.track_id] = dq
                dq.append((cx, cy))
        self.prev = [Box(b.x, b.y, b.w, b.h, b.label, b.score, b.source, b.track_id) for b in boxes]
        return boxes
