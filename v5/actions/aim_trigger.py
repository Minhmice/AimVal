import math
import time
import random
import numpy as np
from typing import List, Optional, Dict, Any
from detectors.base import Box
from hardware.makcu_controller import MakcuController


class AimTrigger:
    def __init__(self, cfg: dict, makcu: MakcuController):
        self.cfg = cfg
        self.makcu = makcu
        self.last_shot_time = 0.0
        self.pending_fire_time = 0.0
        
        # Advanced aim tracking state từ v2
        self.last_target_pos: Optional[tuple] = None
        self.target_lock_time = 0.0
        self.aim_mode_state = "acquiring"  # acquiring, tracking, locked
        self.movement_history = []
        self.max_history = 10
        
        # WindMouse algorithm state từ v2
        self.wind_x = 0.0
        self.wind_y = 0.0
        self.velocity_x = 0.0
        self.velocity_y = 0.0

    def _center(self, w: int, h: int):
        return w // 2, h // 2

    def _windmouse_move(self, start_x: float, start_y: float, dest_x: float, dest_y: float) -> tuple:
        """Advanced WindMouse algorithm từ v2 với float precision"""
        gravity = float(self.cfg.get("WINDMOUSE_G", 7.0))
        wind = float(self.cfg.get("WINDMOUSE_W", 3.0))
        magnitude = float(self.cfg.get("WINDMOUSE_M", 12.0))
        drag = float(self.cfg.get("WINDMOUSE_D", 10.0))
        
        sqrt3 = math.sqrt(3)
        sqrt5 = math.sqrt(5)
        
        current_x, current_y = start_x, start_y
        velocity_x, velocity_y = 0.0, 0.0
        wind_x = self.wind_x
        wind_y = self.wind_y
        
        distance = math.hypot(dest_x - start_x, dest_y - start_y)
        if distance < 1.0:
            return dest_x, dest_y
            
        # Calculate wind force
        wind_x = wind_x / sqrt3 + (random.random() * wind - wind / 2.0) / sqrt5
        wind_y = wind_y / sqrt3 + (random.random() * wind - wind / 2.0) / sqrt5
        
        # Update velocity with gravity and wind
        velocity_x += wind_x + gravity * (dest_x - current_x) / distance
        velocity_y += wind_y + gravity * (dest_y - current_y) / distance
        
        # Apply drag
        velocity_x *= (1.0 - drag / distance)
        velocity_y *= (1.0 - drag / distance)
        
        # Update position
        current_x += velocity_x
        current_y += velocity_y
        
        # Store wind state
        self.wind_x = wind_x
        self.wind_y = wind_y
        self.velocity_x = velocity_x
        self.velocity_y = velocity_y
        
        return current_x, current_y

    def _calculate_target_priority(self, targets: List[Box], cx: float, cy: float) -> Box:
        """Calculate target priority từ v2 với advanced scoring"""
        if not targets:
            return None
            
        best_target = None
        best_score = float('-inf')
        
        target_lock_thr = float(self.cfg.get("TARGET_LOCK_THRESHOLD", 8.0))
        
        for target in targets:
            target_cx = target.x + target.w / 2.0
            target_cy = target.y + target.h / 2.0
            
            # Distance score (closer is better)
            distance = math.hypot(target_cx - cx, target_cy - cy)
            distance_score = max(0.0, 100.0 - distance)
            
            # Size score (moderate size is better)
            area = target.w * target.h
            size_score = min(100.0, area / 10.0)
            
            # Confidence score
            confidence_score = target.score * 100.0
            
            # Lock persistence score (prefer previously locked targets)
            lock_bonus = 0.0
            if self.last_target_pos:
                last_distance = math.hypot(target_cx - self.last_target_pos[0], 
                                         target_cy - self.last_target_pos[1])
                if last_distance < target_lock_thr:
                    lock_bonus = 50.0
            
            # Combined score
            total_score = distance_score * 0.4 + size_score * 0.2 + confidence_score * 0.3 + lock_bonus * 0.1
            
            if total_score > best_score:
                best_score = total_score
                best_target = target
                
        return best_target

    def _update_aim_mode(self, target_distance: float, dt: float):
        """Update aim mode state machine từ v2"""
        deadzone = float(self.cfg.get("DEADZONE", 2.0))
        target_lock_thr = float(self.cfg.get("TARGET_LOCK_THRESHOLD", 8.0))
        
        if target_distance <= deadzone:
            if self.aim_mode_state != "locked":
                self.aim_mode_state = "locked"
                self.target_lock_time = time.time()
        elif target_distance <= target_lock_thr:
            if self.aim_mode_state == "acquiring":
                self.aim_mode_state = "tracking"
            elif self.aim_mode_state == "locked":
                # Stay locked for a bit before switching to tracking
                if time.time() - self.target_lock_time > 0.1:
                    self.aim_mode_state = "tracking"
        else:
            self.aim_mode_state = "acquiring"
            self.target_lock_time = 0.0

    def aim_step(self, frame_bgr, targets: List[Box]):
        if not self.cfg.get("aim_enabled", False):
            return
        if not self.makcu.is_connected:
            return
        if not targets:
            self.last_target_pos = None
            self.aim_mode_state = "acquiring"
            return
            
        h, w = frame_bgr.shape[:2]
        cx, cy = self._center(w, h)
        
        # Advanced target selection từ v2
        best = self._calculate_target_priority(targets, cx, cy)
        if not best:
            return
            
        # Calculate target position with headshot mode từ v2
        target_x = best.x + best.w / 2.0
        target_y = best.y + best.h / 2.0
        
        headshot_mode = bool(self.cfg.get("AIM_HEADSHOT_MODE", True))
        if headshot_mode:
            headshot_offset = float(self.cfg.get("HEADSHOT_OFFSET_PERCENT", 18.0)) / 100.0
            target_y = best.y + best.h * headshot_offset
            
        dx = target_x - cx
        dy = target_y - cy
        distance = math.hypot(dx, dy)
        
        # Update aim mode state machine
        dt = 1.0 / 60.0  # Assume 60 FPS for dt calculation
        self._update_aim_mode(distance, dt)
        
        # Check deadzone
        deadzone = float(self.cfg.get("DEADZONE", 2.0))
        if distance < deadzone:
            return
            
        # Get mode-specific parameters từ v2
        aim_mode = self.cfg.get("AIM_MODE", "Hybrid")
        
        if self.aim_mode_state == "acquiring" or aim_mode == "Acquiring":
            speed = float(self.cfg.get("AIM_ACQUIRING_SPEED", 0.15))
            jitter = float(self.cfg.get("AIM_JITTER", 0.0))
            vertical_damping = 1.0
        elif self.aim_mode_state == "tracking" or aim_mode == "Tracking":
            speed = float(self.cfg.get("AIM_TRACKING_SPEED", 0.04))
            jitter = float(self.cfg.get("AIM_JITTER", 0.0)) * 0.5  # Reduced jitter when tracking
            vertical_damping = float(self.cfg.get("AIM_VERTICAL_DAMPING_FACTOR", 0.15))
        else:  # locked or hybrid
            speed = float(self.cfg.get("AIM_TRACKING_SPEED", 0.04)) * 0.7  # Even slower when locked
            jitter = 0.0  # No jitter when locked
            vertical_damping = float(self.cfg.get("AIM_VERTICAL_DAMPING_FACTOR", 0.15))
            
        # Apply mouse settings từ v2/v3
        sens = float(self.cfg.get("mouse_sensitivity", 0.35))
        smooth = float(self.cfg.get("mouse_smoothness", 0.8))
        mouse_dpi = float(self.cfg.get("mouse_dpi", 800))
        in_game_sens = float(self.cfg.get("in_game_sens", 0.235))
        
        # DPI and sensitivity scaling từ v3
        dpi_scale = 800.0 / max(1.0, mouse_dpi)  # Normalize to 800 DPI
        sens_scale = in_game_sens / max(0.001, sens)
        
        # Apply ease out từ v2
        ease_out = bool(self.cfg.get("MOUSE_EASE_OUT", True))
        if ease_out:
            ease_factor = min(1.0, distance / 50.0)  # Start easing within 50px
            speed *= ease_factor
            
        # Apply smoothness and speed
        move_x = dx * speed * smooth * dpi_scale * sens_scale
        move_y = dy * speed * smooth * vertical_damping * dpi_scale * sens_scale
        
        # Add jitter for human-like movement từ v2
        if jitter > 0.0:
            jitter_x = random.uniform(-jitter, jitter)
            jitter_y = random.uniform(-jitter, jitter)
            move_x += jitter_x
            move_y += jitter_y
            
        # WindMouse algorithm từ v2 (optional)
        use_windmouse = bool(self.cfg.get("USE_WINDMOUSE", False))
        if use_windmouse and distance > 10.0:
            wind_x, wind_y = self._windmouse_move(0, 0, move_x, move_y)
            move_x, move_y = wind_x, wind_y
            
        # Apply movement with step delay từ v2
        if abs(move_x) > 0.5 or abs(move_y) > 0.5:
            self.makcu.move(move_x, move_y)
            
            # Update movement history
            self.movement_history.append((move_x, move_y, time.time()))
            if len(self.movement_history) > self.max_history:
                self.movement_history.pop(0)
                
        # Update target tracking
        self.last_target_pos = (target_x, target_y)
        
        # Apply step delay từ v2
        step_delay = float(self.cfg.get("MOUSE_STEP_DELAY_MS", 1.0))
        if step_delay > 0:
            time.sleep(step_delay / 1000.0)

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
