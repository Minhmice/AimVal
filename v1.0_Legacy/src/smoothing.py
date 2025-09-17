from __future__ import annotations

from typing import Optional, Tuple

from .config import SmoothingConfig


class EMASmoother:
    def __init__(self, cfg: SmoothingConfig) -> None:
        self.cfg = cfg
        self._last: Optional[Tuple[float, float]] = None

    def reset(self) -> None:
        self._last = None

    def smooth(self, pt: Optional[Tuple[int, int]]) -> Optional[Tuple[float, float]]:
        if pt is None:
            return self._last
        x, y = float(pt[0]), float(pt[1])
        if self._last is None:
            self._last = (x, y)
        else:
            a = float(self.cfg.ema_alpha)
            lx, ly = self._last
            self._last = (a * x + (1 - a) * lx, a * y + (1 - a) * ly)
        return self._last

    def step_delta(
        self, current: Tuple[float, float], target: Tuple[float, float]
    ) -> Tuple[int, int]:
        cx, cy = current
        tx, ty = target
        dx = tx - cx
        dy = ty - cy

        # Deadzone
        if abs(dx) <= self.cfg.deadzone_px:
            dx = 0.0
        if abs(dy) <= self.cfg.deadzone_px:
            dy = 0.0

        # Clamp
        max_step = float(self.cfg.max_step_px)
        if dx > max_step:
            dx = max_step
        elif dx < -max_step:
            dx = -max_step
        if dy > max_step:
            dy = max_step
        elif dy < -max_step:
            dy = -max_step

        return int(round(dx)), int(round(dy))
