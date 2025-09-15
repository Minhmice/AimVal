from __future__ import annotations

import time
from typing import Optional, Tuple

import cv2
import numpy as np


class FrameTimer:
    def __init__(self) -> None:
        self.prev_ns: Optional[int] = None
        self.last_dt_ms: float = 0.0
        self.fps: float = 0.0

    def tick(self) -> None:
        now = time.monotonic_ns()
        if self.prev_ns is not None:
            dt = now - self.prev_ns
            if dt > 0:
                self.last_dt_ms = dt / 1e6
                self.fps = 1000.0 / self.last_dt_ms
        self.prev_ns = now


def draw_overlay(
    img: np.ndarray,
    centroid: Optional[Tuple[int, int]],
    target_scr: Optional[Tuple[int, int]],
    roi_rect: Tuple[int, int, int, int],
    timer: FrameTimer,
) -> np.ndarray:
    out = img.copy()
    x, y, w, h = roi_rect
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 140, 255), 1)
    if centroid is not None:
        cv2.circle(out, centroid, 5, (0, 0, 255), -1)
    if target_scr is not None:
        cv2.putText(
            out,
            f"target_scr: {target_scr[0]},{target_scr[1]}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    cv2.putText(
        out,
        f"{timer.last_dt_ms:.1f} ms | {timer.fps:.1f} fps",
        (10, 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return out


