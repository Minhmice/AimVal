import os
import json
import time
import threading
from typing import Optional, Dict, Any, List
import cv2

from framesource.udp_mjpeg import UdpMjpegSource
try:
    from framesource.udp_opencv import UdpOpenCVSource
except Exception:
    UdpOpenCVSource = None  # type: ignore
from framesource.file_reader import FileReaderSource

from detectors.hsv_color import HSVColorDetector
from detectors.yolo_onnx import YoloOnnxDetector
from pipeline.fusion import fuse
from pipeline.tracker import LightTracker
from visualize.overlay import draw_boxes
from actions.aim_trigger import AimTrigger
from hardware.makcu_controller import MakcuController
from logger.metrics import MetricsLogger


class PipelineController:
    def __init__(self, cfg_path: str):
        self.cfg_path = cfg_path
        self.cfg = self._load(cfg_path)
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None
        self.is_running = False

        # Runtime
        self.source = None
        self.hsv = None
        self.ai = None
        self.tracker = None
        self.makcu = None
        self.aim_trigger = None
        self.logger: Optional[MetricsLogger] = None

        # Published state
        self._lock = threading.Lock()
        self.latest_vis_bgr: Optional[Any] = None
        self.latest_mask = None
        self.metrics: Dict[str, Any] = {"fps": 0.0, "latency_ms": 0.0}

    def _load(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def reload_from_disk(self):
        try:
            self.cfg = self._load(self.cfg_path)
        except Exception:
            pass

    def save_to_disk(self):
        try:
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _build_source(self):
        udp = self.cfg.get("udp", {})
        mode = udp.get("mode", "mjpeg").lower()
        if mode == "mjpeg":
            port = int(udp.get("mjpeg_port", 8080))
            return UdpMjpegSource("0.0.0.0", port, rcvbuf_mb=64)
        if mode == "opencv":
            if UdpOpenCVSource is None:
                raise RuntimeError("Nguồn OpenCV không khả dụng trên hệ này")
            url = udp.get("url", "udp://@:5600")
            mw = int(udp.get("max_width", 1280))
            mh = int(udp.get("max_height", 720))
            return UdpOpenCVSource(url, max_width=mw, max_height=mh)
        if mode in ("rtsp", "file"):
            url = udp.get("url", 0 if mode == "webcam" else "")
            return FileReaderSource(url)
        raise ValueError(f"udp.mode không hỗ trợ: {mode}")

    def _build_detectors(self):
        hsv_cfg = self.cfg.get("hsv", {})
        self.hsv = HSVColorDetector(hsv_cfg)
        ai_cfg = self.cfg.get("ai", {})
        self.ai = YoloOnnxDetector(ai_cfg)

    def _build_actions(self):
        self.makcu = MakcuController()
        self.aim_trigger = AimTrigger(self.cfg.get("actions", {}), self.makcu)

    def _build_tracker(self):
        trk_cfg = self.cfg.get("tracking", {"enabled": True, "trails": False})
        self.tracker = LightTracker(iou_thr=0.3, trails=bool(trk_cfg.get("trails", False)))

    def start(self) -> bool:
        if self.is_running:
            return True
        self._stop.clear()
        # Build components
        self.source = self._build_source()
        if not self.source.start():
            return False
        self._build_detectors()
        self._build_actions()
        self._build_tracker()
        # Logger
        log_cfg = self.cfg.get("logging", {})
        if bool(log_cfg.get("enabled", True)):
            csv_path = log_cfg.get("csv_path", "logs/metrics.csv")
            self.logger = MetricsLogger(csv_path, int(log_cfg.get("log_every_n_frames", 20)))
            session_meta = {"session_id": int(time.time()), "config": os.path.basename(self.cfg_path)}
            self.logger.start_session(session_meta)
        else:
            self.logger = None
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()
        self.is_running = True
        return True

    def stop(self):
        self._stop.set()
        try:
            if self._th and self._th.is_alive():
                self._th.join(timeout=1.5)
        except Exception:
            pass
        self.is_running = False
        try:
            if self.source:
                self.source.stop()
        except Exception:
            pass
        try:
            if self.logger:
                self.logger.close()
        except Exception:
            pass

    def _verify_on_target_mask(self, mask, cx: int, cy: int, scan_h: int = 15, scan_w: int = 5) -> bool:
        if mask is None:
            return False
        h, w = mask.shape[:2]
        x1 = max(0, cx - scan_w // 2)
        x2 = min(w, cx + scan_w // 2 + 1)
        y_above_start = max(0, cy - scan_h)
        y_above_end = max(0, cy)
        y_below_start = min(h, cy + 1)
        y_below_end = min(h, cy + scan_h + 1)
        has_above = False
        has_below = False
        if y_above_end > y_above_start:
            roi_above = mask[y_above_start:y_above_end, x1:x2]
            has_above = (roi_above is not None) and (roi_above.size > 0) and int(cv2.countNonZero(roi_above)) > 0
        if y_below_end > y_below_start:
            roi_below = mask[y_below_start:y_below_end, x1:x2]
            has_below = (roi_below is not None) and (roi_below.size > 0) and int(cv2.countNonZero(roi_below)) > 0
        return has_above and has_below

    def _loop(self):
        last = time.perf_counter()
        frame_idx = 0

        while not self._stop.is_set():
            # pull latest config every frame (hot-apply)
            fusion_cfg = self.cfg.get("fusion", {})
            fusion_mode = fusion_cfg.get("mode", "Priority")
            fusion_iou_thr = float(fusion_cfg.get("fusion_iou_thr", 0.3))
            nms_iou_thr = float(fusion_cfg.get("nms_iou_thr", 0.45))
            top_k = int(fusion_cfg.get("top_k", 30))
            tracking_enabled = bool(self.cfg.get("tracking", {}).get("enabled", True))
            hsv_enabled = bool(self.cfg.get("hsv", {}).get("enabled", True))
            ai_enabled = bool(self.cfg.get("ai", {}).get("enabled", False))

            bgr = self.source.get_latest_frame() if self.source else None
            if bgr is None:
                time.sleep(0.005)
                continue

            t0 = time.perf_counter()
            hsv_boxes: List = []
            mask = None
            if hsv_enabled and self.hsv:
                hsv_boxes, debug = self.hsv.infer(bgr)
                mask = debug.get("mask") if isinstance(debug, dict) else None
            ai_boxes: List = []
            if ai_enabled and self.ai:
                ai_boxes, _ = self.ai.infer(bgr)

            fused = fuse(hsv_boxes, ai_boxes, mode=fusion_mode, fusion_iou_thr=fusion_iou_thr, nms_iou_thr=nms_iou_thr, top_k=top_k)
            if tracking_enabled and self.tracker:
                fused = self.tracker.update(fused)

            vis = bgr.copy()
            vis = draw_boxes(vis, fused, thickness=int(self.cfg.get("visual", {}).get("thickness", 2)), font_scale=float(self.cfg.get("visual", {}).get("font_scale", 0.5)))

            # Draw vision guides (aim/trigger FOV rings like v2/v3)
            try:
                aim_fov = int(self.cfg.get("fovsize", 300))
                smooth_fov = int(self.cfg.get("normalsmoothfov", 10))
                tb_fov = int(self.cfg.get("tbfovsize", 70))
                cx, cy = cx, cy  # from below computed
            except Exception:
                pass

            # Aim + trigger
            h, w = bgr.shape[:2]
            cx, cy = w // 2, h // 2
            # overlay FOV circles
            try:
                if 'aim_fov' in locals():
                    import cv2 as _cv2
                    _cv2.circle(vis, (cx, cy), max(1, int(aim_fov)), (255, 255, 255), 1)
                    _cv2.circle(vis, (cx, cy), max(1, int(smooth_fov)), (51, 255, 255), 1)
                    _cv2.circle(vis, (cx, cy), max(1, int(tb_fov)), (255, 255, 255), 1)
            except Exception:
                pass
            is_on_target = self._verify_on_target_mask(mask, cx, cy) if mask is not None else False
            try:
                if self.aim_trigger:
                    self.aim_trigger.aim_step(bgr, fused)
                    self.aim_trigger.trigger_step(bgr, is_on_target)
            except Exception:
                pass

            latency_ms = (time.perf_counter() - t0) * 1000.0
            now = time.perf_counter()
            dt = now - last
            fps = 1.0 / dt if dt > 0 else 0.0
            last = now

            # Publish
            with self._lock:
                self.latest_vis_bgr = vis
                self.latest_mask = mask
                self.metrics = {
                    "fps": fps,
                    "latency_ms": latency_ms,
                }

            # Logging
            if self.logger:
                try:
                    self.logger.maybe_log(frame_idx, {
                        "fps": fps,
                        "latency_ms": latency_ms,
                        "num_boxes": len(fused),
                        "num_keypoints": 0,
                    })
                except Exception:
                    pass

            frame_idx += 1

    def get_latest_frame(self) -> Optional[Any]:
        with self._lock:
            if self.latest_vis_bgr is None:
                return None
            return self.latest_vis_bgr.copy()

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.metrics)

    def get_latest_debug(self) -> Optional[Any]:
        with self._lock:
            if self.latest_mask is None:
                return None
            try:
                import cv2 as _cv2
                return _cv2.cvtColor(self.latest_mask, _cv2.COLOR_GRAY2BGR)
            except Exception:
                return None

    # Live toggles
    def set_hsv_enabled(self, enabled: bool):
        self.cfg.setdefault("hsv", {})["enabled"] = bool(enabled)

    def set_ai_enabled(self, enabled: bool):
        self.cfg.setdefault("ai", {})["enabled"] = bool(enabled)

    def set_tracking_enabled(self, enabled: bool):
        self.cfg.setdefault("tracking", {})["enabled"] = bool(enabled)

    def set_fusion_mode(self, mode: str):
        self.cfg.setdefault("fusion", {})["mode"] = mode

    def set_udp_mode_and_url(self, mode: str, url: str, mjpeg_port: int):
        self.cfg.setdefault("udp", {})
        self.cfg["udp"]["mode"] = mode
        self.cfg["udp"]["url"] = url
        self.cfg["udp"]["mjpeg_port"] = int(mjpeg_port)

    # Detailed param setters (hot-apply where possible)
    def set_hsv_params(self, lower, upper, morph_kernel: int, min_area: int, merge_iou: float):
        h = self.cfg.setdefault("hsv", {})
        h["lower"] = list(map(int, lower))
        h["upper"] = list(map(int, upper))
        h["morph_kernel"] = int(morph_kernel)
        h["min_area"] = int(min_area)
        h["merge_iou"] = float(merge_iou)
        # apply to runtime detector
        try:
            if self.hsv is not None:
                import numpy as np
                self.hsv.lower = np.array(h["lower"], dtype=np.uint8)
                self.hsv.upper = np.array(h["upper"], dtype=np.uint8)
                self.hsv.kernel_size = int(h["morph_kernel"])
                self.hsv.min_area = int(h["min_area"])
                self.hsv.merge_iou = float(h["merge_iou"])
        except Exception:
            pass

    def set_ai_params(self, enabled: bool, model_path: str, conf_thresh: float, iou_thresh: float, input_size: int):
        a = self.cfg.setdefault("ai", {})
        a["enabled"] = bool(enabled)
        a["model_path"] = model_path
        a["conf_thresh"] = float(conf_thresh)
        a["iou_thresh"] = float(iou_thresh)
        a["input_size"] = int(input_size)
        # rebuild session if needed
        try:
            from detectors.yolo_onnx import YoloOnnxDetector
            self.ai = YoloOnnxDetector(a)
        except Exception:
            self.ai = None

    def set_actions_params(self, aim_enabled: bool, trigger_enabled: bool, mouse_sensitivity: float, mouse_smoothness: float, trigger_delay_ms: float, trigger_cooldown: float):
        act = self.cfg.setdefault("actions", {})
        act["aim_enabled"] = bool(aim_enabled)
        act["trigger_enabled"] = bool(trigger_enabled)
        act["mouse_sensitivity"] = float(mouse_sensitivity)
        act["mouse_smoothness"] = float(mouse_smoothness)
        act["trigger_delay_ms"] = float(trigger_delay_ms)
        act["trigger_cooldown"] = float(trigger_cooldown)
        try:
            if self.aim_trigger is not None:
                self.aim_trigger.cfg = act
        except Exception:
            pass
