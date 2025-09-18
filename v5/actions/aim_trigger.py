import math
import time
from typing import List
from detectors.base import Box
from hardware.makcu_controller import MakcuController


class AimTrigger:
    def __init__(self, cfg: dict, makcu: MakcuController):
        self.cfg = cfg
        self.makcu = makcu
        self.last_shot_time = 0.0
        self.pending_fire_time = 0.0

    def _center(self, w: int, h: int):
        return w // 2, h // 2

    def aim_step(self, frame_bgr, targets: List[Box]):
        if not self.cfg.get("aim_enabled", False):
            return
        if not self.makcu.is_connected:
            return
        if not targets:
            return
        h, w = frame_bgr.shape[:2]
        cx, cy = self._center(w, h)
        # pick closest to center
        best = min(targets, key=lambda b: math.hypot((b.x + b.w / 2) - cx, (b.y + b.h / 2) - cy))
        dx = (best.x + best.w / 2) - cx
        dy = (best.y + best.h / 2) - cy
        sens = float(self.cfg.get("mouse_sensitivity", 0.35))
        smooth = float(self.cfg.get("mouse_smoothness", 0.8))
        move_x = (dx * smooth) / max(0.01, sens)
        move_y = (dy * smooth) / max(0.01, sens)
        if abs(move_x) > 0.5 or abs(move_y) > 0.5:
            self.makcu.move(move_x, move_y)

    def trigger_step(self, frame_bgr, is_on_target: bool):
        if not self.cfg.get("trigger_enabled", False):
            self.pending_fire_time = 0.0
            return
        if not self.makcu.is_connected:
            self.pending_fire_time = 0.0
            return
        delay_ms = float(self.cfg.get("trigger_delay_ms", 10))
        cooldown = float(self.cfg.get("trigger_cooldown", 0.15))
        now = time.time()
        # if on target, schedule a fire time; else cancel
        if is_on_target:
            if self.pending_fire_time == 0.0:
                self.pending_fire_time = now + max(0.0, delay_ms) / 1000.0
        else:
            self.pending_fire_time = 0.0
            return
        # check cooldown and scheduled time
        if self.pending_fire_time > 0.0 and now >= self.pending_fire_time and (now - self.last_shot_time) >= cooldown:
            self.makcu.click_left()
            self.last_shot_time = now
            self.pending_fire_time = 0.0
