import time
from typing import Optional, Tuple, Dict, Protocol

import cv2
import numpy as np

from config import config
from mouse import is_button_pressed, Mouse


class TriggerLogic:
    """Small helper encapsulating triggerbot detection and click timing."""

    def __init__(self):
        self.last_click_s: float = 0.0

    def _roi_center(
        self, frame_w: int, frame_h: int, fov: float
    ) -> Tuple[int, int, int, int]:
        cx, cy = int(frame_w // 2), int(frame_h // 2)
        r = max(1, int(fov))
        x1, y1 = max(cx - r, 0), max(cy - r, 0)
        x2, y2 = cx + r, cy + r
        return x1, y1, x2, y2

    def should_run(self) -> bool:
        if not getattr(config, "enabletb", False):
            return False
        key1 = getattr(config, "selected_tb_btn", None)
        key2 = getattr(config, "selected_2_tb", None)
        try:
            return bool(
                (key1 is not None and is_button_pressed(key1))
                or (key2 is not None and is_button_pressed(key2))
            )
        except Exception:
            return False

    def detect_in_roi(self, model, img_bgr: np.ndarray) -> bool:
        if model is None or img_bgr is None or img_bgr.size == 0:
            return False
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, model[0], model[1])
        if getattr(config, "debug_show", False):
            cv2.imshow("TB_ROI", img_bgr)
            cv2.imshow("TB_Mask", mask)
            cv2.waitKey(1)
        return cv2.countNonZero(mask) > 0

    def maybe_click(self, controller: Mouse) -> None:
        now = time.time()
        delay = float(getattr(config, "tbdelay", 0.08))
        if now - self.last_click_s >= delay:
            controller.click()
            self.last_click_s = now

    def run_once(self, model, frame_bgr: np.ndarray, controller: Mouse) -> None:
        if not self.should_run():
            return
        h, w = frame_bgr.shape[:2]
        fov = float(getattr(config, "tbfovsize", 70))
        x1, y1, x2, y2 = self._roi_center(w, h, fov)
        roi = frame_bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return
        if self.detect_in_roi(model, roi):
            self.maybe_click(controller)


# =====================
# Stateless trigger module (unified)
# =====================

class SendInput(Protocol):
    """Interface required by trigger_update to send mouse actions and sleep."""
    def mouse_down(self) -> None: ...
    def mouse_up(self) -> None: ...
    def sleep_ms(self, ms: int) -> None: ...


class TriggerState:
    """Runtime state for the spray/safety logic."""
    def __init__(self):
        self.last_click_ms = 0
        self.spraying = False
        self.last_action_ms = 0  # safety pacing


def point_in_box(px: int, py: int, box: Dict) -> bool:
    return (box["x"] <= px <= box["x"] + box["w"]) and (box["y"] <= py <= box["y"] + box["h"])


def trigger_update(
    is_aim_pressed: bool,
    last_box_screen: Optional[Dict],
    cursor_xy: Tuple[int, int],
    now_ms: int,
    cfg_trigger: Dict,
    state: TriggerState,
    send_input: SendInput,
) -> None:
    """Frame-by-frame trigger controller.

    - Honors enabled/require_aim_pressed/cursor_check gates
    - Supports single-click and spray modes
    - Applies safety pacing (min interval, max rate)
    """
    if not cfg_trigger.get("enabled", False):
        if state.spraying:
            send_input.mouse_up()
            state.spraying = False
        return

    # gating
    if cfg_trigger.get("require_aim_pressed", True) and not is_aim_pressed:
        if state.spraying:
            send_input.mouse_up()
            state.spraying = False
        return

    # cursor check
    if cfg_trigger.get("cursor_check", True) and last_box_screen:
        if not point_in_box(cursor_xy[0], cursor_xy[1], last_box_screen):
            if cfg_trigger.get("mode", "single") == "spray" and state.spraying and cfg_trigger.get("spray", {}).get("release_if_cursor_outside_box", True):
                send_input.mouse_up()
                state.spraying = False
            return

    # safety
    safety = cfg_trigger.get("safety", {"min_interval_ms": 50, "max_rate_per_s": 15})
    if now_ms - state.last_action_ms < int(safety.get("min_interval_ms", 50)):
        return

    if cfg_trigger.get("mode", "single") == "spray":
        if not state.spraying:
            send_input.mouse_down()
            state.spraying = True
            state.last_action_ms = now_ms
        return

    # single
    delay = int(cfg_trigger.get("trigger_delay_ms", 120))
    if state.last_click_ms and (now_ms - state.last_click_ms) < delay:
        return

    # Prefer a direct click primitive if provided by adapter
    up_delay = int(cfg_trigger.get("click_down_up_delay_ms", 20))
    mouse_click = getattr(send_input, "mouse_click", None)
    if callable(mouse_click):
        try:
            mouse_click(up_delay)
        except Exception:
            send_input.mouse_down()
            send_input.sleep_ms(up_delay)
            send_input.mouse_up()
    else:
        send_input.mouse_down()
        send_input.sleep_ms(up_delay)
        send_input.mouse_up()
    state.last_click_ms = now_ms
    state.last_action_ms = now_ms
