import cv2
from typing import List, Dict, Tuple, Optional


def should_draw(over_cfg: Dict) -> bool:
    return bool(over_cfg.get("draw_esp", True))


def draw_fov(
    img,
    center_xy: Tuple[int, int],
    radius: int,
    color=(255, 255, 255),
    thickness=2,
    over_cfg: Optional[Dict] = None,
):
    if over_cfg and not over_cfg.get("draw_fov", True):
        return
    cx, cy = int(center_xy[0]), int(center_xy[1])
    cv2.circle(img, (cx, cy), int(radius), color, int(thickness))


def draw_boxes(
    img,
    detections: List[Dict],
    color=(0, 255, 0),
    thickness=2,
    show_label=True,
    over_cfg: Optional[Dict] = None,
):
    if over_cfg and not over_cfg.get("draw_boxes", True):
        return
    for d in detections:
        if "bbox" in d:
            x, y, w, h = d["bbox"]
        else:
            # accept cx,cy,w,h
            cx, cy, w, h = d.get("cx", 0), d.get("cy", 0), d.get("w", 0), d.get("h", 0)
            x, y = cx - w / 2.0, cy - h / 2.0
        x1, y1 = int(x), int(y)
        x2, y2 = int(x + w), int(y + h)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, int(thickness))
        if show_label:
            conf = d.get("conf", 0.0)
            cls_name = d.get("class_name", "")
            label = f"{cls_name} {conf:.2f}" if cls_name else f"{conf:.2f}"
            cv2.putText(
                img,
                label,
                (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
            )


def draw_target(
    img,
    target_bbox: Dict,
    color=(0, 0, 255),
    thickness=2,
    over_cfg: Optional[Dict] = None,
):
    if over_cfg and not over_cfg.get("draw_target", True):
        return
    if not target_bbox:
        return
    x, y, w, h = target_bbox["x"], target_bbox["y"], target_bbox["w"], target_bbox["h"]
    # Ensure non-negative and within frame bounds
    ih, iw = img.shape[:2]
    x = max(0, min(int(x), iw - 1))
    y = max(0, min(int(y), ih - 1))
    w = max(0, min(int(w), iw - x))
    h = max(0, min(int(h), ih - y))
    cv2.rectangle(img, (x, y), (x + w, y + h), color, int(thickness))


def draw_head_dot(
    img,
    head_xy: Tuple[float, float],
    color=(0, 0, 255),
    radius=2,
    over_cfg: Optional[Dict] = None,
):
    if over_cfg and not over_cfg.get("draw_boxes", True):
        return
    cv2.circle(img, (int(head_xy[0]), int(head_xy[1])), int(radius), color, -1)


# ---- High-level helpers for AI and COLOR overlays ----

AI_BOX_COLOR = (255, 0, 0)  # Blue (BGR)
AI_TARGET_COLOR = (255, 255, 0)  # Cyan/Yellowish for emphasis
COLOR_BOX_COLOR = (255, 0, 255)  # Purple (BGR)


def draw_ai_overlays(img, out_dict: Dict, over_cfg: Optional[Dict] = None):
    if over_cfg and not over_cfg.get("draw_esp", True):
        return
    dets = out_dict.get("detections", []) or []
    if not dets:
        return
    boxes: List[Dict] = []
    for d in dets:
        cx, cy, w, h = d.get("cx", 0), d.get("cy", 0), d.get("w", 0), d.get("h", 0)
        x, y = cx - w / 2.0, cy - h / 2.0
        boxes.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "conf": d.get("conf", 0.0),
                "class_name": d.get("class_name", ""),
            }
        )
    # Draw boxes with confidence labels
    draw_boxes(
        img, boxes, color=AI_BOX_COLOR, thickness=2, show_label=True, over_cfg=over_cfg
    )
    # Draw selected/target if present
    sel = out_dict.get("last_detection_box_screen")
    if sel and (over_cfg is None or over_cfg.get("draw_target", True)):
        draw_target(img, sel, color=AI_TARGET_COLOR, thickness=2, over_cfg=over_cfg)


def draw_color_overlays(
    img, detection_results: List[Dict], over_cfg: Optional[Dict] = None
):
    if over_cfg and not over_cfg.get("draw_esp", True):
        return
    if not detection_results:
        return
    boxes: List[Dict] = []
    for det in detection_results or []:
        if "bbox" in det:
            x, y, w, h = det["bbox"]
            boxes.append(
                {
                    "bbox": (x, y, w, h),
                    "conf": det.get("confidence", 1.0),
                    "class_name": det.get("class", "color"),
                }
            )
    draw_boxes(
        img,
        boxes,
        color=COLOR_BOX_COLOR,
        thickness=2,
        show_label=False,
        over_cfg=over_cfg,
    )
