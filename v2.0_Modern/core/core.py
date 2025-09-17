import cv2
import numpy as np
import threading
import time
import logging
import dxcam
from screeninfo import get_monitors
import ctypes
from collections import deque

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SharedConfig
from .hardware import MakcuController
from .detection import Detector, visualize_detection, verify_on_target, draw_range_circle
from .aiming import Aimer
from .udp_source import UdpFrameSource

logger = logging.getLogger(__name__)


class TriggerbotCore:
    """Main runtime loop coordinating capture, detection, aiming and trigger.

    Lifecycle:
    - setup(): initialize hardware controller, detector/aimer, and screen capture
    - run_one_frame(): single-tick processing (called on a tight worker thread)
    - cleanup(): release resources when stopping

    Debug windows:
    - Two OpenCV windows show the processed mask and the annotated vision. They
      are created lazily when the flag is enabled and torn down when disabled.
    """

    def __init__(self, config: SharedConfig):
        self.config = config
        self.mouse_controller = None
        self.detector = None
        self.aimer = None
        self.camera = None
        # (left, top, right, bottom) region for dxcam screen capture
        self.capture_region = {}

        self.last_shot_time = 0
        self.trigger_activated_at = 0

        self.debug_windows_active = False
        self.wnd_mask = "Debug: Mask"
        self.wnd_vision = "Debug: Vision"

        self.aim_target_first_seen_time = 0
        # Track optional raw viewer window lifecycle

        # Rolling performance stats
        self._frame_durations = deque(maxlen=240)
        self._frame_latencies = deque(maxlen=240)
        self._last_process_time = time.process_time()
        self._last_perf_wall_time = time.time()

        # Mouse button state
        self.mouse1_pressed = False
        self.mouse2_pressed = False
        self.last_mouse1_time = 0.0
        self.last_mouse2_time = 0.0
        self.mouse1_toggle_state = False
        self.mouse2_toggle_state = False
        self.is_aim_active = False

    def setup(self):
        """Create all components and start screen capture.

        Returns False on any fatal initialization error so the caller can abort.
        """
        logger.info("Setting up bot core...")
        
        # Debug config values
        logger.info(f"TRIGGERBOT_ENABLED: {self.config.get('TRIGGERBOT_ENABLED')}")
        logger.info(f"AIM_ASSIST_ENABLED: {self.config.get('AIM_ASSIST_ENABLED')}")
        
        # Force disable trigger bot on startup if not explicitly enabled
        if not self.config.get("TRIGGERBOT_ENABLED"):
            self.config.set("TRIGGERBOT_ENABLED", False)
            logger.info("Force disabled trigger bot on startup")
        self.mouse_controller = MakcuController(self.config)
        if not self.mouse_controller.is_connected:
            # Allow running without hardware: enter simulation mode
            logger.warning(
                "Makcu controller not connected. Continuing in simulation mode."
            )

        self.detector = Detector(self.config)
        self.aimer = Aimer(self.config, self.mouse_controller)

        # Force UDP source unless explicitly changed in code; prevents dxcam fallback
        try:
            self.config.set("FRAME_SOURCE", "udp")
        except Exception:
            pass
        source = "udp"
        logger.info("Frame source selected: %s", source)
        if source == "udp":
            try:
                host = self.config.get("UDP_HOST")
                port = int(self.config.get("UDP_PORT"))
                rcvbuf_mb = int(self.config.get("UDP_RCVBUF_MB"))
                use_turbo = bool(self.config.get("UDP_TURBOJPEG"))
                self.camera = UdpFrameSource(
                    host=host, port=port, rcvbuf_mb=rcvbuf_mb, use_turbo=use_turbo
                )
                if not self.camera.start():
                    raise Exception("Failed to start UDP frame source")
                logger.info(f"UDP frame source started on udp://{host}:{port}")
            except Exception as e:
                logger.critical(f"Failed to initialize UDP source: {e}")
                return False
        else:
            try:
                fov_res_str = self.config.get("FOV_RESOLUTION")
                fov_w, fov_h = map(int, fov_res_str.split("x"))

                monitor = get_monitors()[0]
                screen_w, screen_h = monitor.width, monitor.height

                capture_left = (screen_w - fov_w) // 2
                capture_top = (screen_h - fov_h) // 2

                self.capture_region = (
                    capture_left,
                    capture_top,
                    capture_left + fov_w,
                    capture_top + fov_h,
                )

                # Create a DXGI-based screen capture camera (Windows only)
                self.camera = dxcam.create(output_color="BGR")
                if self.camera is None:
                    raise Exception("Failed to create dxcam instance.")

                self.camera.start(target_fps=0, region=self.capture_region)
                logger.info(f"Screen capture started for region: {self.capture_region}")
            except Exception as e:
                logger.critical(f"Failed to initialize screen capture: {e}")
                return False

        return True

    def _get_mouse_vk(self, button_name):
        """Get virtual key code for mouse button."""
        if button_name.lower() == "disable":
            return None
        button_map = {
            "left": 0x01,
            "right": 0x02,
            "middle": 0x04,
            "mid": 0x04,
            "mouse4": 0x05,
            "mouse5": 0x06,
        }
        return button_map.get(button_name.lower(), 0x02)  # default right

    def _is_mouse_button_down(self, button_name):
        """Check if mouse button is currently pressed using Makcu ONLY."""
        try:
            if button_name.lower() == "disable":
                return False
                
            # Check Makcu connection
            if not self.mouse_controller or not self.mouse_controller.is_connected:
                # Only log warning once per session to avoid spam
                if not hasattr(self, '_makcu_warning_logged'):
                    logger.warning("Makcu not connected - mouse buttons disabled")
                    self._makcu_warning_logged = True
                return False
                
            try:
                import makcu
                from makcu import MouseButton
                
                # Map button names to Makcu MouseButton
                # Note: Makcu v2.2.0 supports MOUSE4, MOUSE5
                button_map = {
                    "left": MouseButton.LEFT,
                    "right": MouseButton.RIGHT,
                    "middle": MouseButton.MIDDLE,
                    "mid": MouseButton.MIDDLE,
                    "mouse4": MouseButton.MOUSE4,
                    "mouse5": MouseButton.MOUSE5,
                }
                
                makcu_button = button_map.get(button_name.lower())
                if makcu_button:
                    is_pressed = self.mouse_controller.makcu.is_pressed(makcu_button)
                    if is_pressed:
                        logger.debug(f"Makcu mouse button {button_name} is DOWN")
                    return is_pressed
                else:
                    # mouse4/mouse5 not supported by Makcu
                    logger.warning(f"Button {button_name} not supported by Makcu - returning False")
                    return False
                    
            except Exception as makcu_error:
                logger.error(f"Makcu button check failed: {makcu_error}")
                return False
            
        except Exception as e:
            logger.error(f"Error checking mouse button {button_name}: {e}")
            return False

    def _check_mouse_toggles(self):
        """Check mouse button toggles and update states."""
        now = time.time()
        
        # Check if Makcu is connected before processing mouse buttons
        if not self.mouse_controller or not self.mouse_controller.is_connected:
            # If Makcu disconnected, reset all states to OFF
            if self.mouse1_toggle_state or self.mouse2_toggle_state or self.is_aim_active:
                logger.info("Makcu disconnected - resetting all mouse states to OFF")
                self.mouse1_toggle_state = False
                self.mouse2_toggle_state = False
                self.is_aim_active = False
            return
        
        # Mouse 1 button (default: right mouse button)
        mouse1_button = self.config.get("MOUSE_1_BUTTON", "right")
        mouse1_mode = self.config.get("MOUSE_1_MODE", "toggle")
        mouse1_down = self._is_mouse_button_down(mouse1_button)
        
        # Debug mouse button detection
        if mouse1_down:
            logger.debug(f"Mouse 1 ({mouse1_button}) is DOWN - Mode: {mouse1_mode}")
        
        if mouse1_mode == "toggle":
            # Toggle mode: press to toggle on/off
            if mouse1_down and not self.mouse1_pressed and (now - self.last_mouse1_time) > 0.2:
                old_state = self.mouse1_toggle_state
                self.mouse1_toggle_state = not self.mouse1_toggle_state
                self.mouse1_pressed = True
                self.last_mouse1_time = now
                logger.info(f"Mouse 1 ({mouse1_button}): Toggle {old_state} -> {self.mouse1_toggle_state}")
            elif not mouse1_down:
                self.mouse1_pressed = False
        else:
            # Hold mode: active while held
            old_state = self.mouse1_toggle_state
            self.mouse1_toggle_state = mouse1_down
            if mouse1_down and not self.mouse1_pressed:
                logger.info(f"Mouse 1 ({mouse1_button}): Hold ON")
                self.mouse1_pressed = True
            elif not mouse1_down and self.mouse1_pressed:
                logger.info(f"Mouse 1 ({mouse1_button}): Hold OFF")
                self.mouse1_pressed = False
            # Log state change for hold mode
            if old_state != self.mouse1_toggle_state:
                logger.info(f"Mouse 1 ({mouse1_button}): State changed to {self.mouse1_toggle_state}")
            
        # Mouse 2 button (default: left)
        mouse2_button = self.config.get("MOUSE_2_BUTTON", "left")
        mouse2_mode = self.config.get("MOUSE_2_MODE", "hold")
        mouse2_down = self._is_mouse_button_down(mouse2_button)
        
        # Debug mouse button detection
        if mouse2_down:
            logger.debug(f"Mouse 2 ({mouse2_button}) is DOWN - Mode: {mouse2_mode}")
        
        if mouse2_mode == "toggle":
            # Toggle mode: press to toggle on/off
            if mouse2_down and not self.mouse2_pressed and (now - self.last_mouse2_time) > 0.2:
                old_state = self.mouse2_toggle_state
                self.mouse2_toggle_state = not self.mouse2_toggle_state
                self.mouse2_pressed = True
                self.last_mouse2_time = now
                logger.info(f"Mouse 2 ({mouse2_button}): Toggle {old_state} -> {self.mouse2_toggle_state}")
            elif not mouse2_down:
                self.mouse2_pressed = False
        else:
            # Hold mode: active while held
            old_state = self.mouse2_toggle_state
            self.mouse2_toggle_state = mouse2_down
            if mouse2_down and not self.mouse2_pressed:
                logger.info(f"Mouse 2 ({mouse2_button}): Hold ON")
                self.mouse2_pressed = True
            elif not mouse2_down and self.mouse2_pressed:
                logger.info(f"Mouse 2 ({mouse2_button}): Hold OFF")
                self.mouse2_pressed = False
            # Log state change for hold mode
            if old_state != self.mouse2_toggle_state:
                logger.info(f"Mouse 2 ({mouse2_button}): State changed to {self.mouse2_toggle_state}")
        
        # Update aim bot state: either button can activate (OR logic)
        old_aim_state = self.is_aim_active
        self.is_aim_active = self.mouse1_toggle_state or self.mouse2_toggle_state
        
        # Log aim state changes
        if old_aim_state != self.is_aim_active:
            logger.info(f"Aim bot: {old_aim_state} -> {self.is_aim_active} (Mouse1: {self.mouse1_toggle_state}, Mouse2: {self.mouse2_toggle_state})")

    def monitor_performance(self):
        """Return dict with cpu_percent, ram_mb, avg_fps, avg_latency_ms."""
        # FPS from rolling durations
        avg_dt = np.mean(self._frame_durations) if self._frame_durations else 0.0
        avg_fps = (1.0 / avg_dt) if avg_dt > 0 else 0.0
        avg_latency_ms = (
            float(np.mean(self._frame_latencies) * 1000.0)
            if self._frame_latencies
            else 0.0
        )

        # CPU% approx from process_time delta over wall delta
        now_pt = time.process_time()
        now_wall = time.time()
        dt_pt = max(1e-6, now_pt - self._last_process_time)
        dt_wall = max(1e-6, now_wall - self._last_perf_wall_time)
        cpu_percent = min(100.0, max(0.0, (dt_pt / dt_wall) * 100.0))
        self._last_process_time = now_pt
        self._last_perf_wall_time = now_wall

        # RAM (optional psutil)
        ram_mb = 0.0
        try:
            import psutil  # type: ignore

            p = psutil.Process()
            ram_mb = p.memory_info().rss / (1024 * 1024)
        except Exception:
            ram_mb = 0.0

        return {
            "cpu_percent": cpu_percent,
            "ram_mb": ram_mb,
            "avg_fps": avg_fps,
            "avg_latency_ms": avg_latency_ms,
        }

    def shoot_burst(self, duration):
        """Start a non-blocking shot: press then release after duration seconds."""
        if self.mouse_controller:
            threading.Thread(
                target=self._shoot_worker, args=(duration,), daemon=True
            ).start()

    def _shoot_worker(self, duration):
        self.mouse_controller.press_left()
        time.sleep(duration)
        self.mouse_controller.release_left()

    def _handle_triggerbot(self, is_on_target):
        """Optimized trigger bot handler with advanced features."""
        if not self.config.get("TRIGGERBOT_ENABLED"):
            self.trigger_activated_at = 0
            return
        
        current_time = time.time()
        
        # Advanced trigger modes
        trigger_mode = self.config.get("TRIGGER_MODE", "instant")
        burst_mode = self.config.get("TRIGGER_BURST_MODE", False)
        adaptive_delay = self.config.get("TRIGGER_ADAPTIVE_DELAY", False)
        
        if is_on_target:
            if self.trigger_activated_at == 0:
                self.trigger_activated_at = current_time
                logger.debug("Trigger activated - on target detected")
            
            # Calculate delay based on mode
            if adaptive_delay:
                # Adaptive delay based on target size and distance
                delay_ms = self._calculate_adaptive_delay()
            else:
                delay_ms = self.config.get("TRIGGERBOT_DELAY_MS")
            
            # Check if delay has passed
            if (current_time - self.trigger_activated_at) * 1000 >= delay_ms:
                # Check cooldown
                shot_duration = self.config.get("SHOT_DURATION")
                shot_cooldown = self.config.get("SHOT_COOLDOWN")
                min_cooldown = self.config.get("TRIGGER_MIN_COOLDOWN", shot_cooldown)
                
                if (current_time - self.last_shot_time) > (shot_duration + min_cooldown):
                    if trigger_mode == "instant":
                        self._fire_trigger_shot()
                    elif trigger_mode == "burst":
                        self._fire_trigger_burst()
                    elif trigger_mode == "adaptive":
                        self._fire_adaptive_shot()
                    
                    self.last_shot_time = current_time
        else:
            if self.trigger_activated_at != 0:
                logger.debug("Trigger deactivated - off target")
            self.trigger_activated_at = 0

    def _calculate_adaptive_delay(self):
        """Calculate adaptive delay based on target characteristics."""
        base_delay = self.config.get("TRIGGERBOT_DELAY_MS")
        target_size_factor = self.config.get("TRIGGER_SIZE_FACTOR", 1.0)
        distance_factor = self.config.get("TRIGGER_DISTANCE_FACTOR", 1.0)
        
        # Simple adaptive calculation (can be enhanced)
        adaptive_delay = base_delay * target_size_factor * distance_factor
        return max(0, min(adaptive_delay, self.config.get("TRIGGER_MAX_DELAY_MS", 100)))

    def _fire_trigger_shot(self):
        """Fire a single trigger shot."""
        shot_duration = self.config.get("SHOT_DURATION")
        logger.info("TRIGGER BOT: Firing shot!")
        self.shoot_burst(shot_duration)

    def _fire_trigger_burst(self):
        """Fire a burst of shots."""
        burst_count = self.config.get("TRIGGER_BURST_COUNT", 3)
        burst_delay = self.config.get("TRIGGER_BURST_DELAY", 0.05)
        shot_duration = self.config.get("SHOT_DURATION")
        
        logger.info(f"TRIGGER BOT: Firing burst of {burst_count} shots!")
        
        def burst_sequence():
            for i in range(burst_count):
                self.shoot_burst(shot_duration)
                if i < burst_count - 1:  # Don't delay after last shot
                    time.sleep(burst_delay)
        
        # Run burst in separate thread to avoid blocking
        threading.Thread(target=burst_sequence, daemon=True).start()

    def _fire_adaptive_shot(self):
        """Fire adaptive shot based on target characteristics."""
        # This can be enhanced with more sophisticated logic
        self._fire_trigger_shot()

    def run_one_frame(self):
        """Process a single frame: capture -> detect -> trigger -> aim -> debug.

        The GUI thread toggles a boolean to stop the loop outside; this function
        itself does not loop, it only performs one step and returns quickly.
        """
        frame_start_time = time.perf_counter()
        try:
            show_debug = self.config.get("DEBUG_WINDOW_VISIBLE")
            show_view = False  # View screen removed
            show_hud = bool(self.config.get("HUD_SHOW_AIM_STATUS"))

            # Fetch latest frame early so we can derive current dimensions
            frame = self.camera.get_latest_frame()
            if frame is not None and hasattr(frame, "shape") and frame.size > 0:
                cur_h, cur_w = frame.shape[:2]
            else:
                # If we have a capture region (dxcam), derive size from it; else default
                if (
                    isinstance(self.capture_region, tuple)
                    and len(self.capture_region) == 4
                ):
                    cur_w = self.capture_region[2] - self.capture_region[0]
                    cur_h = self.capture_region[3] - self.capture_region[1]
                else:
                    cur_w, cur_h = 640, 480

            if show_debug and not self.debug_windows_active:
                cv2.namedWindow(self.wnd_mask, cv2.WINDOW_NORMAL)
                cv2.moveWindow(self.wnd_mask, 0, 0)
                cv2.namedWindow(self.wnd_vision, cv2.WINDOW_NORMAL)
                cv2.moveWindow(self.wnd_vision, cur_w, 0)
                cv2.setWindowProperty(self.wnd_mask, cv2.WND_PROP_TOPMOST, 1)
                cv2.setWindowProperty(self.wnd_vision, cv2.WND_PROP_TOPMOST, 1)
                self.debug_windows_active = True
            elif not show_debug and self.debug_windows_active:
                cv2.destroyAllWindows()
                self.debug_windows_active = False

            # If no valid frame, render placeholders and skip
            if frame is None or not hasattr(frame, "shape") or frame.size == 0:
                if show_debug:
                    black_screen = np.zeros((cur_h, cur_w, 3), dtype=np.uint8)
                    cv2.putText(
                        black_screen,
                        "NO SIGNAL",
                        (10, cur_h - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 255),
                        1,
                    )
                    cv2.imshow(self.wnd_mask, black_screen)
                    cv2.imshow(self.wnd_vision, black_screen)
                    cv2.waitKey(1)
                return

            potential_targets, processed_mask = self.detector.run(frame)

            crosshair_x = cur_w // 2
            crosshair_y = cur_h // 2

            scan_height = self.config.get("SANDWICH_CHECK_HEIGHT")
            scan_width = self.config.get("SANDWICH_CHECK_SCAN_WIDTH")
            # Sandwich verification: require color above and below the crosshair
            is_on_target = verify_on_target(
                processed_mask, crosshair_x, crosshair_y, scan_height, scan_width
            )

            # Check mouse button toggles
            self._check_mouse_toggles()

            # Triggerbot: simplified and optimized
            self._handle_triggerbot(is_on_target)

            # Aim assist: only when enabled
            if self.is_aim_active:
                target_in_range = None
                if potential_targets:
                    distances = [
                        np.hypot(
                            t["center"][0] - crosshair_x, t["center"][1] - crosshair_y
                        )
                        for t in potential_targets
                    ]
                    best_index = np.argmin(distances)
                    if distances[best_index] < self.config.get("AIM_ASSIST_RANGE"):
                        target_in_range = potential_targets[best_index]

                aim_delay = self.config.get("AIM_ASSIST_DELAY")
                if target_in_range:
                    if self.aim_target_first_seen_time == 0:
                        self.aim_target_first_seen_time = time.time()

                    if time.time() - self.aim_target_first_seen_time > aim_delay:
                        self.aimer.start_aim(
                            target_in_range, crosshair_x, crosshair_y, is_on_target
                        )
                    else:
                        self.aimer.stop_aim()
                else:
                    self.aim_target_first_seen_time = 0
                    self.aimer.stop_aim()

            if show_debug:
                mask_display = cv2.cvtColor(processed_mask, cv2.COLOR_GRAY2BGR)
                vision_display = visualize_detection(frame.copy(), potential_targets)

                trigger_color = (0, 255, 0) if is_on_target else (0, 0, 255)

                scan_x_start = max(0, crosshair_x - scan_width // 2)
                scan_x_end = min(cur_w, crosshair_x + scan_width // 2 + 1)

                for display in [mask_display, vision_display]:
                    cv2.rectangle(
                        display,
                        (scan_x_start, max(0, crosshair_y - scan_height)),
                        (scan_x_end, crosshair_y),
                        trigger_color,
                        1,
                    )
                    cv2.rectangle(
                        display,
                        (scan_x_start, crosshair_y + 1),
                        (scan_x_end, min(cur_h, crosshair_y + scan_height + 1)),
                        trigger_color,
                        1,
                    )

                # Add range circle to debug vision window
                try:
                    vision_display = draw_range_circle(
                        vision_display,
                        (crosshair_x, crosshair_y),
                        int(self.config.get("AIM_ASSIST_RANGE")),
                    )
                except Exception:
                    pass

                cv2.imshow(self.wnd_mask, mask_display)
                cv2.imshow(self.wnd_vision, vision_display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    self.config.set("is_running", False)

        except Exception as e:
            logger.exception("An unhandled exception occurred during a frame run")
            self.config.set("is_running", False)

        finally:
            target_fps = self.config.get("FPS_LIMIT")
            if target_fps > 0:
                target_frame_time = 1 / target_fps
                elapsed_time = time.perf_counter() - frame_start_time
                sleep_time = target_frame_time - elapsed_time
                if sleep_time > 0:
                    time.sleep(sleep_time)

            # Record perf stats
            try:
                total_dt = time.perf_counter() - frame_start_time
                self._frame_durations.append(total_dt)
                if isinstance(self.camera, UdpFrameSource):
                    stats = self.camera.get_stats()
                    rt_ms = stats.get("rt_ms", 0.0)
                    self._frame_latencies.append(rt_ms / 1000.0)
            except Exception:
                pass

    def cleanup(self):
        """Stop aiming, stop capture, close windows, and disconnect hardware."""
        logger.info("Cleaning up bot core resources...")
        if self.aimer:
            self.aimer.stop_aim()
        if self.camera:
            self.camera.stop()
        cv2.destroyAllWindows()
        if self.mouse_controller:
            self.mouse_controller.disconnect()
