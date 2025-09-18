from typing import List
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


def nms(boxes: List[Box], iou_thr: float, top_k: int) -> List[Box]:
    if not boxes:
        return []
    # sort by score desc
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].score, reverse=True)
    picked: List[int] = []
    xyxy = [b.as_xyxy() for b in boxes]
    for i in order:
        keep = True
        for j in picked:
            if iou_xyxy(xyxy[i], xyxy[j]) >= iou_thr:
                keep = False
                break
        if keep:
            picked.append(i)
        if len(picked) >= top_k:
            break
    return [boxes[i] for i in picked]


def fuse(hsv_boxes: List[Box], ai_boxes: List[Box], mode: str = "Priority", fusion_iou_thr: float = 0.3, nms_iou_thr: float = 0.45, top_k: int = 30) -> List[Box]:
    mode = (mode or "Priority").lower()
    if mode == "and":
        out: List[Box] = []
        for hb in hsv_boxes:
            hxy = hb.as_xyxy()
            for ab in ai_boxes:
                if iou_xyxy(hxy, ab.as_xyxy()) >= fusion_iou_thr:
                    # merge by union
                    x1 = min(hxy[0], ab.x)
                    y1 = min(hxy[1], ab.y)
                    x2 = max(hxy[2], ab.x + ab.w)
                    y2 = max(hxy[3], ab.y + ab.h)
                    out.append(Box(x1, y1, x2 - x1, y2 - y1, label=ab.label or hb.label, score=max(hb.score, ab.score), source="fused"))
        return nms(out, nms_iou_thr, top_k)

    if mode == "or":
        merged = (hsv_boxes or []) + (ai_boxes or [])
        return nms(merged, nms_iou_thr, top_k)

    # Priority: ưu tiên HSV; hợp nhất OR-NMS để tăng recall
    merged: List[Box] = []
    # Boost HSV scores slightly to survive NMS preference
    for b in hsv_boxes:
        merged.append(Box(b.x, b.y, b.w, b.h, label=b.label, score=b.score + 0.05, source=b.source))
    for b in ai_boxes:
        merged.append(b)
    return nms(merged, nms_iou_thr, top_k)
