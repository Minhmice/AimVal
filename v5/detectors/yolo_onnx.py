from typing import List, Dict, Any, Tuple
import numpy as np
import cv2
from .base import Box, Detector

try:
    import onnxruntime as ort  # type: ignore
except Exception:
    ort = None  # type: ignore


def _letterbox(img, new_size=640, color=(114, 114, 114)):
    h, w = img.shape[:2]
    scale = min(new_size / max(1, w), new_size / max(1, h))
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_w = new_size - nw
    pad_h = new_size - nh
    top = pad_h // 2
    bottom = pad_h - top
    left = pad_w // 2
    right = pad_w - left
    out = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return out, scale, left, top


def _nms(boxes: List[Box], iou_thr: float) -> List[Box]:
    if not boxes:
        return []
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].score, reverse=True)
    picked = []
    xyxy = [b.as_xyxy() for b in boxes]
    while order:
        i = order.pop(0)
        picked.append(i)
        keep = []
        for j in order:
            # IoU
            ax1, ay1, ax2, ay2 = xyxy[i]
            bx1, by1, bx2, by2 = xyxy[j]
            inter_x1 = max(ax1, bx1)
            inter_y1 = max(ay1, by1)
            inter_x2 = min(ax2, bx2)
            inter_y2 = min(ay2, by2)
            iw = max(0, inter_x2 - inter_x1)
            ih = max(0, inter_y2 - inter_y1)
            inter = iw * ih
            if inter <= 0:
                keep.append(j)
                continue
            area_a = (ax2 - ax1) * (ay2 - ay1)
            area_b = (bx2 - bx1) * (by2 - by1)
            iou = inter / max(1e-6, area_a + area_b - inter)
            if iou < iou_thr:
                keep.append(j)
        order = keep
    return [boxes[i] for i in picked]


class YoloOnnxDetector(Detector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = bool(config.get("enabled", False))
        self.model_path = str(config.get("model_path", ""))
        self.conf_thresh = float(config.get("conf_thresh", 0.35))
        self.iou_thresh = float(config.get("iou_thresh", 0.45))
        self.input_size = int(config.get("input_size", 640))
        self.classes = list(config.get("classes", ["person"]))
        self.session = None
        self.input_name = None
        if self.enabled and ort is not None and self.model_path:
            try:
                so = ort.SessionOptions()
                so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.session = ort.InferenceSession(self.model_path, sess_options=so)
                self.input_name = self.session.get_inputs()[0].name
            except Exception:
                self.session = None
                self.enabled = False
        else:
            self.enabled = False

    def infer(self, bgr) -> Tuple[List[Box], Dict[str, Any]]:
        if not self.enabled or self.session is None or bgr is None:
            return [], {}
        img, scale, pad_x, pad_y = _letterbox(bgr, self.input_size)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        inp = rgb.astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[None, ...]
        try:
            outputs = self.session.run(None, {self.input_name: inp})
        except Exception:
            return [], {}

        preds = outputs[0]
        if preds.ndim == 3:
            preds = preds[0]

        boxes: List[Box] = []
        for det in preds:
            cx, cy, w, h = float(det[0]), float(det[1]), float(det[2]), float(det[3])
            obj = float(det[4])
            cls_scores = det[5:]
            if cls_scores.size == 0:
                conf = obj
                cls_id = 0
            else:
                cls_id = int(np.argmax(cls_scores))
                cls_conf = float(cls_scores[cls_id])
                conf = obj * cls_conf
            if conf < self.conf_thresh:
                continue
            x1i = cx - w / 2.0
            y1i = cy - h / 2.0
            x2i = cx + w / 2.0
            y2i = cy + h / 2.0
            # remove pad, rescale to original
            x1 = (x1i - pad_x) / max(1e-6, scale)
            y1 = (y1i - pad_y) / max(1e-6, scale)
            x2 = (x2i - pad_x) / max(1e-6, scale)
            y2 = (y2i - pad_y) / max(1e-6, scale)
            x1 = int(max(0, min(bgr.shape[1] - 1, x1)))
            y1 = int(max(0, min(bgr.shape[0] - 1, y1)))
            x2 = int(max(0, min(bgr.shape[1], x2)))
            y2 = int(max(0, min(bgr.shape[0], y2)))
            w0 = max(1, x2 - x1)
            h0 = max(1, y2 - y1)
            boxes.append(Box(x1, y1, w0, h0, label="ai", score=conf, source="ai"))

        boxes = _nms(boxes, self.iou_thresh)
        return boxes, {}
