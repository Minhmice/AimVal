import math
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

from config import config
from mouse import is_button_pressed


Target = Tuple[float, float, float]  # (cx, cy, distance_to_center)


class AimLogic:
    """
    Stateless helper that decides if aim should engage and computes movement deltas
    based on current configuration and detected targets.
    """

    @staticmethod
    def _convert_pixels_to_counts(dx_px: float, dy_px: float) -> Tuple[float, float]:
        sens = float(getattr(config, "in_game_sens", 7))
        dpi = float(getattr(config, "mouse_dpi", 800))

        cm_per_rev_base = 54.54
        cm_per_rev = cm_per_rev_base / max(sens, 0.01)
        count_per_cm = dpi / 2.54
        deg_per_count = 360.0 / (cm_per_rev * count_per_cm)

        ndx = dx_px * deg_per_count
        ndy = dy_px * deg_per_count
        return ndx, ndy

    @staticmethod
    def _clip(ddx: float, ddy: float) -> Tuple[float, float]:
        max_speed = float(getattr(config, "max_speed", 1000.0))
        clipped_dx = np.clip(ddx, -abs(max_speed), abs(max_speed))
        clipped_dy = np.clip(ddy, -abs(max_speed), abs(max_speed))
        return float(clipped_dx), float(clipped_dy)

    @staticmethod
    def is_active() -> bool:
        """
        Decide whether any configured aim key is currently held.
        Uses config.selected_aim_keys if present, else falls back to selected_mouse_button.
        """
        chosen = getattr(config, "selected_aim_keys", None)
        if chosen and isinstance(chosen, (list, tuple)):
            for k in chosen:
                try:
                    if is_button_pressed(k):
                        return True
                except Exception:
                    continue
        else:
            selected_btn = getattr(config, "selected_mouse_button", None)
            if selected_btn is not None:
                try:
                    if is_button_pressed(selected_btn):
                        return True
                except Exception:
                    pass
        return False

    @staticmethod
    def plan_move(
        targets: List[Target], frame_width: int, frame_height: int
    ) -> Optional[Tuple[float, float]]:
        """
        Compute the aimbot movement counts (ddx, ddy) to enqueue, or None.
        Applies FOV gate, smoothing and speed scaling.
        """
        if not getattr(config, "enableaim", False):
            return None

        if not targets:
            return None

        center_x = frame_width / 2.0
        center_y = frame_height / 2.0

        # choose closest by distance_to_center
        best_cx, best_cy, best_d = min(targets, key=lambda t: t[2])

        # FOV check
        if best_d > float(getattr(config, "fovsize", 300)):
            return None

        # convert to counts
        dx = best_cx - center_x
        dy = best_cy - center_y
        ndx, ndy = AimLogic._convert_pixels_to_counts(dx, dy)

        # smoothing region
        smooth_fov = float(getattr(config, "normalsmoothfov", 10))
        if best_d < smooth_fov:
            smooth = max(float(getattr(config, "normalsmooth", 10)), 0.01)
            ndx *= float(getattr(config, "normal_x_speed", 0.5)) / smooth
            ndy *= float(getattr(config, "normal_y_speed", 0.5)) / smooth
        else:
            ndx *= float(getattr(config, "normal_x_speed", 0.5))
            ndy *= float(getattr(config, "normal_y_speed", 0.5))

        return AimLogic._clip(ndx, ndy)


# =====================
# Target point helpers
# =====================

@dataclass
class ScreenScale:
    """Simple scale factors to map ROI coordinates to screen coordinates."""
    x: float
    y: float


def compute_target_point(detection: Dict, roi_rect_screen: Dict, cfg_aim: Dict, screen_scale: ScreenScale) -> Tuple[int, int]:
    """Convert a detection (cx,cy,w,h in ROI coords) to a target point on screen.

    - Supports vertical alignment Top/Center/Bottom
    - Applies percentage offsets inside the box and absolute pixel offsets
    - Scales to full-screen coordinates using provided `screen_scale`
    """
    cx, cy, w, h = detection["cx"], detection["cy"], detection["w"], detection["h"]
    left, top = roi_rect_screen["left"], roi_rect_screen["top"]

    # alignment
    align = cfg_aim.get("alignment", "Center")
    if align == "Top":
        ty = cy - h / 2.0
    elif align == "Bottom":
        ty = cy + h / 2.0
    else:
        ty = cy

    # offset percent
    offp = cfg_aim.get("offset_percent", {})
    tx = cx
    if offp.get("use_x", False):
        tx = cx + (w * (float(offp.get("x", 50.0)) / 100.0 - 0.5))
    if offp.get("use_y", False):
        # 0% bottom, 100% top
        ty = (cy + h / 2.0) - (h * (float(offp.get("y", 50.0)) / 100.0))

    # offset px
    off = cfg_aim.get("offset_px", {"x": 0, "y": 0})
    tx += float(off.get("x", 0))
    ty += float(off.get("y", 0))

    # to screen coords
    sx = int(left + tx * screen_scale.x)
    sy = int(top + ty * screen_scale.y)
    return sx, sy


class EmaFilter:
    """Lightweight exponential moving-average filter for smoothing a series."""

    def __init__(self, factor: float):
        self.a = float(factor)
        self.prev = None

    def apply(self, value: float) -> float:
        if self.prev is None:
            self.prev = value
            return value
        sm = self.a * value + (1.0 - self.a) * self.prev
        self.prev = sm
        return sm


def plan_mouse_delta(
    cursor_xy: Tuple[int, int],
    target_xy: Tuple[int, int],
    cfg_movement: Dict,
    aspect_ratio_correction: bool = True,
    lock_on_screen: bool = True,
    screen_size: Tuple[int, int] = (1920, 1080),
) -> Tuple[int, int]:
    """Plan a single mouse delta step toward target with safety and UX niceties.

    - Applies a deadzone around the cursor
    - Scales by a sensitivity factor
    - Clamps per-axis max step
    - Optionally compensates vertical movement by aspect ratio
    - Optionally prevents moving outside screen bounds
    - Adds optional random jitter to appear less mechanical
    """
    cx, cy = cursor_xy
    tx, ty = target_xy
    dx = tx - cx
    dy = ty - cy

    # deadzone
    dz = cfg_movement.get("deadzone_px", {"x": 0, "y": 0})
    if abs(dx) <= int(dz.get("x", 0)) and abs(dy) <= int(dz.get("y", 0)):
        return 0, 0

    # sensitivity scale
    scale = max(float(cfg_movement.get("mouse_sensitivity_scale", 1.0)), 0.01)
    dx *= scale
    dy *= scale

    # clamp max step
    mx = int(cfg_movement.get("max_step_px", {}).get("x", 20))
    my = int(cfg_movement.get("max_step_px", {}).get("y", 20))
    if mx <= 0:
        mx = 1
    if my <= 0:
        my = 1
    dx = int(max(-mx, min(mx, dx)))
    dy = int(max(-my, min(my, dy)))

    if aspect_ratio_correction and cfg_movement.get("aspect_ratio_correction", True):
        sw, sh = screen_size
        if sh != 0:
            dy = int(dy / (sw / float(sh)))

    # jitter
    j = cfg_movement.get("jitter_px", {"x": 0, "y": 0})
    jx = int(j.get("x", 0))
    jy = int(j.get("y", 0))
    if jx or jy:
        import random
        dx += random.randint(-jx, jx)
        dy += random.randint(-jy, jy)

    # lock on screen check (do not move off-screen)
    if lock_on_screen and cfg_movement.get("lock_on_screen", True):
        nx = cx + dx
        ny = cy + dy
        sw, sh = screen_size
        if nx < 0 or ny < 0 or nx >= sw or ny >= sh:
            return 0, 0

    return dx, dy
