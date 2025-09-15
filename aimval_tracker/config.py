from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class HSVRange:
    h_low: int = 0
    s_low: int = 120
    v_low: int = 120
    h_high: int = 10
    s_high: int = 255
    v_high: int = 255


@dataclass
class ROI:
    x: int = 0
    y: int = 0
    w: Optional[int] = None
    h: Optional[int] = None


@dataclass
class TrackerConfig:
    hsv: HSVRange = field(default_factory=HSVRange)
    min_area: int = 150
    blur_kernel: int = 5
    morph_kernel: int = 3
    use_roi: bool = False
    roi: ROI = field(default_factory=ROI)
    # target selection: 'centroid' | 'topmost' | 'bbox_topcenter'
    target_mode: str = "centroid"


@dataclass
class MappingConfig:
    screen_size: Tuple[int, int] = (1920, 1080)
    method: str = "linear"  # "linear" or "homography"
    # Homography points: (src_pts, dst_pts) if method == "homography"
    homography_src: Optional[Tuple[Tuple[float, float], ...]] = None
    homography_dst: Optional[Tuple[Tuple[float, float], ...]] = None


@dataclass
class SmoothingConfig:
    ema_alpha: float = 0.5
    deadzone_px: int = 2
    max_step_px: int = 50


@dataclass
class ControllerConfig:
    debug: bool = False
    auto_reconnect: bool = True
    tick_hz: float = 240.0


@dataclass
class PipelineConfig:
    # Frame source
    udp_host: str = "0.0.0.0"
    udp_port: int = 8080
    # Tracker
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    # Mapping
    mapping: MappingConfig = field(default_factory=MappingConfig)
    # Smoothing
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    # Controller
    controller: ControllerConfig = field(default_factory=ControllerConfig)
    # Overlay/debug
    show_overlay: bool = True
    display_scale: float = 1.0
    aimbot: bool = False
    show_box: bool = False
