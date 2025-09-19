"""
Pipeline module for better architectural separation.
Separates detection, tracking, and action execution into distinct stages.
"""

import time
import threading
import queue
from typing import Optional, List, Dict, Any
import numpy as np
import cv2

from config import config
from detection import perform_detection
from mouse import Mouse


class DetectionPipeline:
    """Handles detection processing with threading and buffering."""

    def __init__(self, model, class_names):
        self.model = model
        self.class_names = class_names
        self._detection_queue = queue.Queue(maxsize=3)
        self._result_queue = queue.Queue(maxsize=5)
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._detection_worker, daemon=True
        )
        self._worker_thread.start()

    def update_model(self, model, class_names):
        """Update the detection model safely."""
        self.model = model
        self.class_names = class_names

    def process_frame(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """Submit frame for detection and get latest results."""
        # Submit new frame (non-blocking)
        try:
            self._detection_queue.put_nowait((frame, time.time()))
        except queue.Full:
            pass  # Skip if queue is full

        # Get latest result (non-blocking)
        try:
            return self._result_queue.get_nowait()
        except queue.Empty:
            return None

    def _detection_worker(self):
        """Worker thread for detection processing."""
        while not self._stop_event.is_set():
            try:
                frame, timestamp = self._detection_queue.get(timeout=0.1)

                # Perform detection
                detections, mask = perform_detection(self.model, frame)

                result = {
                    "detections": detections,
                    "mask": mask,
                    "timestamp": timestamp,
                    "processing_time": time.time() - timestamp,
                }

                # Store result (replace old if queue is full)
                try:
                    self._result_queue.put_nowait(result)
                except queue.Full:
                    try:
                        self._result_queue.get_nowait()  # Remove old result
                        self._result_queue.put_nowait(result)
                    except queue.Empty:
                        pass

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Detection Pipeline Error] {e}")

    def stop(self):
        """Stop the detection pipeline."""
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)


class AimingPipeline:
    """Handles aiming calculations and smoothing."""

    def __init__(self):
        self.smoothing_buffer = []
        self.max_buffer_size = 5

    def calculate_aim_adjustment(self, targets: List, frame_info) -> tuple:
        """Calculate aim adjustment based on targets."""
        if not targets:
            return 0.0, 0.0, float("inf")

        center_x = frame_info.xres / 2.0
        center_y = frame_info.yres / 2.0

        # Select best target (closest to center)
        best_target = min(targets, key=lambda t: t[2])
        cx, cy, distance = best_target

        # Check if target is within FOV
        fov_size = float(getattr(config, "fovsize", 300))
        if distance > fov_size:
            return 0.0, 0.0, float("inf")

        # Calculate raw movement
        dx = cx - center_x
        dy = cy - center_y

        # Apply DPI and sensitivity calculations
        sens = float(getattr(config, "in_game_sens", 7))
        dpi = float(getattr(config, "mouse_dpi", 800))

        cm_per_rev_base = 54.54
        cm_per_rev = cm_per_rev_base / max(sens, 0.01)
        count_per_cm = dpi / 2.54
        deg_per_count = 360.0 / (cm_per_rev * count_per_cm)

        ndx = dx * deg_per_count
        ndy = dy * deg_per_count

        # Apply smoothing based on distance
        smooth_fov = float(getattr(config, "normalsmoothfov", 10))
        if distance < smooth_fov:
            smoothing = float(getattr(config, "normalsmooth", 10))
            ndx /= max(smoothing, 0.01)
            ndy /= max(smoothing, 0.01)

        # Apply speed multipliers
        ndx *= float(getattr(config, "normal_x_speed", 0.5))
        ndy *= float(getattr(config, "normal_y_speed", 0.5))

        return ndx, ndy, distance

    def apply_smoothing(self, dx: float, dy: float) -> tuple:
        """Apply additional smoothing using buffer."""
        self.smoothing_buffer.append((dx, dy))
        if len(self.smoothing_buffer) > self.max_buffer_size:
            self.smoothing_buffer.pop(0)

        # Simple moving average
        if len(self.smoothing_buffer) > 1:
            avg_dx = sum(x[0] for x in self.smoothing_buffer) / len(
                self.smoothing_buffer
            )
            avg_dy = sum(x[1] for x in self.smoothing_buffer) / len(
                self.smoothing_buffer
            )
            return avg_dx, avg_dy

        return dx, dy


class ActionPipeline:
    """Handles mouse movement and clicking actions."""

    def __init__(self):
        self.controller = Mouse()
        self.move_queue = queue.Queue(maxsize=50)
        self._stop_event = threading.Event()
        self._move_thread = threading.Thread(
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()
        self.last_tb_click_time = 0.0

    def queue_movement(self, dx: float, dy: float, delay: float = 0.005):
        """Queue a mouse movement."""
        try:
            # Apply speed limits
            max_speed = float(getattr(config, "max_speed", 1000.0))
            clipped_dx = np.clip(dx, -abs(max_speed), abs(max_speed))
            clipped_dy = np.clip(dy, -abs(max_speed), abs(max_speed))

            self.move_queue.put_nowait((float(clipped_dx), float(clipped_dy), delay))
        except queue.Full:
            pass  # Skip if queue is full

    def trigger_click(self):
        """Execute a trigger click with delay checking."""
        current_time = time.time()
        tb_delay = float(getattr(config, "tbdelay", 0.08))

        if current_time - self.last_tb_click_time >= tb_delay:
            self.controller.click()
            self.last_tb_click_time = current_time
            return True
        return False

    def _process_move_queue(self):
        """Process queued mouse movements."""
        while not self._stop_event.is_set():
            try:
                dx, dy, delay = self.move_queue.get(timeout=0.1)
                try:
                    self.controller.move(dx, dy)
                except Exception as e:
                    print(f"[Mouse.move error] {e}")
                if delay and delay > 0:
                    time.sleep(delay)
            except queue.Empty:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"[Move Queue Error] {e}")
                time.sleep(0.01)

    def stop(self):
        """Stop the action pipeline."""
        self._stop_event.set()
        if self._move_thread.is_alive():
            self._move_thread.join(timeout=1.0)


class MasterPipeline:
    """Coordinates all pipeline stages."""

    def __init__(self, model, class_names):
        self.detection_pipeline = DetectionPipeline(model, class_names)
        self.aiming_pipeline = AimingPipeline()
        self.action_pipeline = ActionPipeline()
        self._stats = {
            "frames_processed": 0,
            "detections_found": 0,
            "movements_executed": 0,
            "triggers_fired": 0,
            "avg_processing_time": 0.0,
        }

    def update_model(self, model, class_names):
        """Update detection model."""
        self.detection_pipeline.update_model(model, class_names)

    def process_frame(self, frame: np.ndarray, frame_info) -> Dict[str, Any]:
        """Process a frame through the entire pipeline."""
        self._stats["frames_processed"] += 1

        # Detection stage
        detection_result = self.detection_pipeline.process_frame(frame)
        if not detection_result:
            return {"targets": [], "mask": None}

        detections = detection_result["detections"]
        mask = detection_result["mask"]

        if detections:
            self._stats["detections_found"] += 1

        # Convert detections to targets
        targets = self._convert_detections_to_targets(detections, frame_info)

        # Aiming stage
        if targets and getattr(config, "enableaim", False):
            dx, dy, distance = self.aiming_pipeline.calculate_aim_adjustment(
                targets, frame_info
            )
            if distance != float("inf"):
                # Apply additional smoothing
                smooth_dx, smooth_dy = self.aiming_pipeline.apply_smoothing(dx, dy)

                # Check if aim button is pressed
                from mouse import is_button_pressed

                selected_btn = getattr(config, "selected_mouse_button", None)
                if selected_btn is not None and is_button_pressed(selected_btn):
                    self.action_pipeline.queue_movement(smooth_dx, smooth_dy)
                    self._stats["movements_executed"] += 1

        # Triggerbot stage
        if getattr(config, "enabletb", False):
            if self._should_trigger(frame, frame_info):
                if self.action_pipeline.trigger_click():
                    self._stats["triggers_fired"] += 1

        # Update processing time stats
        if "processing_time" in detection_result:
            self._stats["avg_processing_time"] = (
                self._stats["avg_processing_time"] * 0.9
                + detection_result["processing_time"] * 0.1
            )

        return {"targets": targets, "mask": mask, "detection_result": detection_result}

    def _convert_detections_to_targets(self, detections: List, frame_info) -> List:
        """Convert detection results to target list."""
        targets = []
        center_x = frame_info.xres / 2.0
        center_y = frame_info.yres / 2.0

        for det in detections:
            try:
                x, y, w, h = det["bbox"]
                # Calculate target center (with offset)
                offsetX = getattr(config, "offsetX", 0)
                offsetY = getattr(config, "offsetY", 0)

                target_x = x + w / 2 + (w * offsetX / 100)
                target_y = y + h / 2 + (h * offsetY / 100)

                distance = np.hypot(target_x - center_x, target_y - center_y)
                targets.append((target_x, target_y, distance))
            except Exception as e:
                print(f"[Target conversion error] {e}")

        return targets

    def _should_trigger(self, frame: np.ndarray, frame_info) -> bool:
        """Determine if triggerbot should fire."""
        try:
            from mouse import is_button_pressed

            # Check if trigger buttons are pressed
            tb_btn = getattr(config, "selected_tb_btn", None)
            tb_btn2 = getattr(config, "selected_2_tb", None)

            if not (is_button_pressed(tb_btn) or is_button_pressed(tb_btn2)):
                return False

            # Check center ROI for target color
            cx, cy = int(frame_info.xres // 2), int(frame_info.yres // 2)
            ROI_SIZE = 5
            x1, y1 = max(cx - ROI_SIZE, 0), max(cy - ROI_SIZE, 0)
            x2, y2 = min(cx + ROI_SIZE, frame.shape[1]), min(
                cy + ROI_SIZE, frame.shape[0]
            )

            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                return False

            # Use detection model HSV range for trigger detection
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            # Get HSV range from model
            HSV_LOWER = self.detection_pipeline.model[0]
            HSV_UPPER = self.detection_pipeline.model[1]

            mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)
            detected = cv2.countNonZero(mask) > 0

            return detected

        except Exception as e:
            print(f"[Triggerbot error] {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return self._stats.copy()

    def stop(self):
        """Stop all pipeline stages."""
        self.detection_pipeline.stop()
        self.action_pipeline.stop()
