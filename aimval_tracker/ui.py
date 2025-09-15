from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2
import numpy as np
from dearpygui import dearpygui as dpg

from .config import (
    PipelineConfig,
    HSVRange,
    ROI,
    TrackerConfig,
    MappingConfig,
    SmoothingConfig,
    ControllerConfig,
)


class TrackerUI:
    def __init__(
        self,
        cfg: PipelineConfig,
        on_config_change: Callable[[PipelineConfig], None],
        on_apply_udp: Optional[Callable[[], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.on_config_change = on_config_change
        self._on_apply_udp = on_apply_udp
        self._texture_id = None
        self._tex_size = (1280, 720)
        self._lock = threading.Lock()
        self._last_frame: Optional[np.ndarray] = None
        self._main_win = "main"
        self._loader_win = "loader"
        self._loader_text_tag = "loader_text"
        self._actions: list[tuple[str, tuple, dict]] = []

    def set_frame(self, frame_bgr: np.ndarray) -> None:
        with self._lock:
            self._last_frame = frame_bgr.copy()

    def _ensure_texture(self, w: int, h: int) -> None:
        if self._texture_id is not None:
            return
        self._tex_size = (int(w), int(h))
        with dpg.texture_registry(show=False):
            self._texture_id = dpg.add_dynamic_texture(
                w, h, np.zeros((h, w, 3), dtype=np.float32).ravel(), tag="frame_tex"
            )

    def update_texture(self) -> None:
        with self._lock:
            frame = self._last_frame
        if frame is None:
            return
        # Ensure texture (pre-sized once)
        w_tex, h_tex = self._tex_size
        self._ensure_texture(w_tex, h_tex)
        # BGR -> RGB and normalize to [0,1]; resize to texture size
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if (rgb.shape[1], rgb.shape[0]) != (w_tex, h_tex):
                rgb = cv2.resize(rgb, (w_tex, h_tex))
            dpg.set_value("frame_tex", (rgb.astype(np.float32) / 255.0).ravel())
        except Exception as e:
            print(f"[UI] update_texture error: {e}")

    def save_config(self, path: str) -> None:
        p = Path(path)
        data = asdict(self.cfg)
        p.write_text(json.dumps(data, indent=2))

    def load_config(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text())
        # Simple dataclass rebuild
        self.cfg = PipelineConfig(
            udp_host=data.get("udp_host", self.cfg.udp_host),
            udp_port=data.get("udp_port", self.cfg.udp_port),
            tracker=TrackerConfig(
                hsv=HSVRange(
                    **data.get("tracker", {}).get("hsv", asdict(self.cfg.tracker.hsv))
                ),
                min_area=data.get("tracker", {}).get(
                    "min_area", self.cfg.tracker.min_area
                ),
                blur_kernel=data.get("tracker", {}).get(
                    "blur_kernel", self.cfg.tracker.blur_kernel
                ),
                morph_kernel=data.get("tracker", {}).get(
                    "morph_kernel", self.cfg.tracker.morph_kernel
                ),
                use_roi=data.get("tracker", {}).get(
                    "use_roi", self.cfg.tracker.use_roi
                ),
                roi=ROI(
                    **data.get("tracker", {}).get("roi", asdict(self.cfg.tracker.roi))
                ),
                target_mode=data.get("tracker", {}).get(
                    "target_mode", self.cfg.tracker.target_mode
                ),
            ),
            mapping=MappingConfig(**data.get("mapping", asdict(self.cfg.mapping))),
            smoothing=SmoothingConfig(
                **data.get("smoothing", asdict(self.cfg.smoothing))
            ),
            controller=ControllerConfig(
                **data.get("controller", asdict(self.cfg.controller))
            ),
            show_overlay=data.get("show_overlay", self.cfg.show_overlay),
            display_scale=data.get("display_scale", self.cfg.display_scale),
        )
        self.on_config_change(self.cfg)

    def build(self) -> None:
        dpg.create_context()
        dpg.create_viewport(title="AimVal UI", width=1280, height=820)
        # Create texture upfront to avoid 'Texture not found'
        self._ensure_texture(self._tex_size[0], self._tex_size[1])

        # Loader window (shown first)
        with dpg.window(
            tag=self._loader_win, label="Starting...", width=1280, height=820
        ):
            dpg.add_text("Finding OBS stream PC...", tag=self._loader_text_tag)
            dpg.add_loading_indicator()

        # Main window hidden until first frame
        with dpg.window(
            tag=self._main_win, label="AimVal", width=1280, height=820, show=False
        ):
            # Viewer at top
            with dpg.group(horizontal=False):
                dpg.add_text("Viewer")
                dpg.add_image(
                    "frame_tex", width=self._tex_size[0], height=self._tex_size[1]
                )
            dpg.add_separator()
            # Config panel
            with dpg.collapsing_header(label="Config", default_open=True):
                with dpg.group(horizontal=True):
                    # Stream
                    with dpg.child_window(width=300, height=260, border=True):
                        dpg.add_text("Stream (UDP)")
                        dpg.add_input_text(
                            label="Host",
                            default_value=self.cfg.udp_host,
                            callback=lambda s, a, u: self._set_udp_field("udp_host", a),
                        )
                        dpg.add_input_int(
                            label="Port",
                            default_value=self.cfg.udp_port,
                            callback=lambda s, a, u: self._set_udp_field("udp_port", a),
                        )
                        dpg.add_input_int(
                            label="RecvBuf MB",
                            default_value=16,
                            callback=lambda s, a, u: self._set_udp_field(
                                "rcvbuf_mb", a
                            ),
                        )
                        dpg.add_button(
                            label="Apply UDP (restart)", callback=self._apply_udp
                        )
                    # HSV
                    with dpg.child_window(width=300, height=260, border=True):
                        dpg.add_text("HSV")
                        hv = self.cfg.tracker.hsv
                        dpg.add_input_int(
                            label="H low",
                            default_value=hv.h_low,
                            callback=lambda s, a, u: self._update_hsv("h_low", a),
                        )
                        dpg.add_input_int(
                            label="H high",
                            default_value=hv.h_high,
                            callback=lambda s, a, u: self._update_hsv("h_high", a),
                        )
                        dpg.add_input_int(
                            label="S low",
                            default_value=hv.s_low,
                            callback=lambda s, a, u: self._update_hsv("s_low", a),
                        )
                        dpg.add_input_int(
                            label="V low",
                            default_value=hv.v_low,
                            callback=lambda s, a, u: self._update_hsv("v_low", a),
                        )
                        dpg.add_input_int(
                            label="S high",
                            default_value=hv.s_high,
                            callback=lambda s, a, u: self._update_hsv("s_high", a),
                        )
                        dpg.add_input_int(
                            label="V high",
                            default_value=hv.v_high,
                            callback=lambda s, a, u: self._update_hsv("v_high", a),
                        )
                        dpg.add_combo(
                            label="Target",
                            items=["centroid", "topmost", "bbox_topcenter"],
                            default_value=self.cfg.tracker.target_mode,
                            callback=lambda s, a, u: self._set_target(a),
                        )
                    # ROI / Mapping
                    with dpg.child_window(width=300, height=260, border=True):
                        dpg.add_text("ROI & Mapping")
                        r = self.cfg.tracker.roi
                        dpg.add_checkbox(
                            label="Use ROI",
                            default_value=self.cfg.tracker.use_roi,
                            callback=lambda s, a, u: self._set_use_roi(a),
                        )
                        dpg.add_input_int(
                            label="ROI x",
                            default_value=r.x,
                            callback=lambda s, a, u: self._set_roi_field("x", a),
                        )
                        dpg.add_input_int(
                            label="ROI y",
                            default_value=r.y,
                            callback=lambda s, a, u: self._set_roi_field("y", a),
                        )
                        dpg.add_input_int(
                            label="ROI w",
                            default_value=r.w or 0,
                            callback=lambda s, a, u: self._set_roi_field("w", a),
                        )
                        dpg.add_input_int(
                            label="ROI h",
                            default_value=r.h or 0,
                            callback=lambda s, a, u: self._set_roi_field("h", a),
                        )
                        dpg.add_combo(
                            label="Mapping",
                            items=["linear", "homography"],
                            default_value=self.cfg.mapping.method,
                            callback=lambda s, a, u: self._set_mapping(a),
                        )
                        dpg.add_input_text(
                            label="Screen (WxH)",
                            default_value=f"{self.cfg.mapping.screen_size[0]}x{self.cfg.mapping.screen_size[1]}",
                            callback=lambda s, a, u: self._set_screen(a),
                        )
                    # Smoothing / Controller
                    with dpg.child_window(width=300, height=260, border=True):
                        dpg.add_text("Smoothing & Control")
                        dpg.add_input_float(
                            label="EMA alpha",
                            default_value=self.cfg.smoothing.ema_alpha,
                            callback=lambda s, a, u: self._set_smooth("ema_alpha", a),
                        )
                        dpg.add_input_int(
                            label="Deadzone px",
                            default_value=self.cfg.smoothing.deadzone_px,
                            callback=lambda s, a, u: self._set_smooth("deadzone_px", a),
                        )
                        dpg.add_input_int(
                            label="Max step px",
                            default_value=self.cfg.smoothing.max_step_px,
                            callback=lambda s, a, u: self._set_smooth("max_step_px", a),
                        )
                        dpg.add_checkbox(
                            label="Overlay",
                            default_value=self.cfg.show_overlay,
                            callback=lambda s, a, u: self._set_overlay(a),
                        )
                        dpg.add_input_float(
                            label="Display scale",
                            default_value=self.cfg.display_scale,
                            callback=lambda s, a, u: self._set_scale(a),
                        )
                        dpg.add_checkbox(
                            label="Aimbot (enable control)",
                            default_value=self.cfg.aimbot,
                            callback=lambda s, a, u: self._set_aimbot(a),
                        )
                        dpg.add_checkbox(
                            label="Box (draw square)",
                            default_value=self.cfg.show_box,
                            callback=lambda s, a, u: self._set_box(a),
                        )
                    # Save/Load
                    with dpg.child_window(width=300, height=260, border=True):
                        dpg.add_text("Preset")
                        dpg.add_input_text(
                            label="File",
                            default_value="aimval_config.json",
                            tag="cfg_path",
                        )
                        dpg.add_button(
                            label="Save",
                            callback=lambda: self.save_config(
                                dpg.get_value("cfg_path")
                            ),
                        )
                        dpg.add_button(
                            label="Load",
                            callback=lambda: self.load_config(
                                dpg.get_value("cfg_path")
                            ),
                        )

        dpg.setup_dearpygui()
        dpg.show_viewport()

    def _do_show_loader(self) -> None:
        dpg.configure_item(self._loader_win, show=True)
        dpg.configure_item(self._main_win, show=False)

    def _do_show_main(self) -> None:
        dpg.configure_item(self._loader_win, show=False)
        dpg.configure_item(self._main_win, show=True)

    def _do_set_loader_text(self, msg: str) -> None:
        dpg.set_value(self._loader_text_tag, msg)

    # Thread-safe action queue
    def _post(self, name: str, *args, **kwargs) -> None:
        with self._lock:
            self._actions.append((name, args, kwargs))

    def request_show_loader(self) -> None:
        self._post("show_loader")

    def request_show_main(self) -> None:
        self._post("show_main")

    def request_loader_text(self, msg: str) -> None:
        self._post("set_loader_text", msg)

    def render_loop(self) -> None:
        while dpg.is_dearpygui_running():
            # process queued UI actions on render thread
            try:
                with self._lock:
                    actions = list(self._actions)
                    self._actions.clear()
                for name, args, kwargs in actions:
                    if name == "show_loader":
                        self._do_show_loader()
                    elif name == "show_main":
                        self._do_show_main()
                    elif name == "set_loader_text":
                        self._do_set_loader_text(*args, **kwargs)
            except Exception as e:
                print(f"[UI] action error: {e}")
            self.update_texture()
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

    def render_step(self) -> None:
        """Render one DearPyGui frame (non-blocking helper for main thread)."""
        if dpg.is_dearpygui_running():
            self.update_texture()
            dpg.render_dearpygui_frame()

    # Update helpers
    def _update_hsv(self, field: str, value: int) -> None:
        hv = self.cfg.tracker.hsv
        setattr(hv, field, int(value))
        self.on_config_change(self.cfg)

    def _set_target(self, value: str) -> None:
        self.cfg.tracker.target_mode = value
        self.on_config_change(self.cfg)

    def _set_use_roi(self, value: bool) -> None:
        self.cfg.tracker.use_roi = bool(value)
        self.on_config_change(self.cfg)

    def _set_roi_field(self, field: str, value: int) -> None:
        r = self.cfg.tracker.roi
        if field in ("w", "h") and int(value) <= 0:
            setattr(r, field, None)
        else:
            setattr(r, field, int(value))
        self.on_config_change(self.cfg)

    def _set_mapping(self, value: str) -> None:
        self.cfg.mapping.method = value
        self.on_config_change(self.cfg)

    def _set_screen(self, value: str) -> None:
        try:
            w, h = [int(v) for v in value.lower().split("x")]
            self.cfg.mapping.screen_size = (w, h)
            self.on_config_change(self.cfg)
        except Exception:
            pass

    def _set_smooth(self, field: str, value) -> None:
        setattr(
            self.cfg.smoothing, field, type(getattr(self.cfg.smoothing, field))(value)
        )
        self.on_config_change(self.cfg)

    def _set_overlay(self, value: bool) -> None:
        self.cfg.show_overlay = bool(value)
        self.on_config_change(self.cfg)

    def _set_scale(self, value: float) -> None:
        self.cfg.display_scale = float(value)
        self.on_config_change(self.cfg)

    def _set_aimbot(self, value: bool) -> None:
        self.cfg.aimbot = bool(value)
        self.on_config_change(self.cfg)

    def _set_box(self, value: bool) -> None:
        self.cfg.show_box = bool(value)
        self.on_config_change(self.cfg)

    # Stream helpers
    def _set_udp_field(self, field: str, value) -> None:
        if field == "udp_port":
            self.cfg.udp_port = int(value)
        elif field == "udp_host":
            self.cfg.udp_host = str(value)
        else:
            # rcvbuf_mb saved transiently via controller state; ignore persist
            pass
        self.on_config_change(self.cfg)

    def _apply_udp(self) -> None:
        if self._on_apply_udp is not None:
            try:
                self._on_apply_udp()
            except Exception as e:
                print(f"[UI] apply_udp error: {e}")
