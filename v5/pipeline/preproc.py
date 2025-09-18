import cv2
import numpy as np
from typing import Tuple


def resize_keep_max(bgr, max_width: int, max_height: int):
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    scale = min(max_width / max(1, w), max_height / max(1, h))
    if scale >= 1.0:
        return bgr
    nw, nh = int(w * scale), int(h * scale)
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def apply_preproc(bgr, cfg: dict):
    if bgr is None:
        return None
    # Optional gamma
    gamma = float(cfg.get("gamma", 1.0)) if cfg else 1.0
    if abs(gamma - 1.0) > 1e-3:
        lut = np.array([((i / 255.0) ** (1.0 / max(1e-3, gamma))) * 255 for i in range(256)]).astype("uint8")
        bgr = cv2.LUT(bgr, lut)
    # Optional CLAHE (light)
    if cfg and cfg.get("clahe", False):
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        lab = cv2.merge((cl, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    # Optional blur
    k = int(cfg.get("blur", 0)) if cfg else 0
    if k >= 3 and k % 2 == 1:
        bgr = cv2.GaussianBlur(bgr, (k, k), 0)
    return bgr
