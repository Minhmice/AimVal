from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from .config import MappingConfig


class LinearMapper:
    def __init__(self, cfg: MappingConfig) -> None:
        self.cfg = cfg

    def map_point(
        self, pt_img: Tuple[int, int], img_size: Tuple[int, int]
    ) -> Tuple[int, int]:
        x, y = pt_img
        w_img, h_img = img_size
        w_scr, h_scr = self.cfg.screen_size
        x_scr = int(x * float(w_scr) / float(w_img))
        y_scr = int(y * float(h_scr) / float(h_img))
        return x_scr, y_scr


class HomographyMapper:
    def __init__(self, cfg: MappingConfig) -> None:
        self.cfg = cfg
        if not (cfg.homography_src and cfg.homography_dst):
            raise ValueError("Homography requires src and dst points")
        src = np.array(cfg.homography_src, dtype=np.float32)
        dst = np.array(cfg.homography_dst, dtype=np.float32)
        self.H, _ = cv2.findHomography(src, dst)
        if self.H is None:
            raise ValueError("Failed to compute homography matrix")

    def map_point(
        self, pt_img: Tuple[int, int], img_size: Tuple[int, int]
    ) -> Tuple[int, int]:
        x, y = pt_img
        p = np.array([[x, y, 1.0]], dtype=np.float32).T
        q = self.H @ p
        q /= q[2, 0] + 1e-6
        return int(q[0, 0]), int(q[1, 0])
