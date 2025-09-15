#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from typing import Optional, Tuple

import cv2

from aimval_tracker import (
    PipelineConfig,
    UDPJPEGStream,
    HSVTracker,
    LinearMapper,
    HomographyMapper,
    EMASmoother,
    MakcuAsyncController,
    FrameTimer,
    draw_overlay,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AimVal Tracker + Makcu controller")
    p.add_argument("--udp-host", type=str, default="0.0.0.0")
    p.add_argument("--udp-port", type=int, default=8080)
    p.add_argument("--rcvbuf-mb", type=int, default=16)
    # HSV
    p.add_argument("--h-low", type=int, default=0)
    p.add_argument("--s-low", type=int, default=120)
    p.add_argument("--v-low", type=int, default=120)
    p.add_argument("--h-high", type=int, default=10)
    p.add_argument("--s-high", type=int, default=255)
    p.add_argument("--v-high", type=int, default=255)
    p.add_argument("--min-area", type=int, default=150)
    p.add_argument("--blur", type=int, default=5)
    p.add_argument("--morph", type=int, default=3)
    # ROI
    p.add_argument("--roi", type=str, default="", help="x,y,w,h or empty")
    p.add_argument(
        "--target",
        type=str,
        default="centroid",
        choices=["centroid", "topmost", "bbox_topcenter"],
        help="Target point selection",
    )
    # Mapping
    p.add_argument("--screen", type=str, default="1920x1080")
    p.add_argument(
        "--mapping", type=str, default="linear", choices=["linear", "homography"]
    )
    p.add_argument(
        "--homography",
        type=str,
        default="",
        help="x1,y1;x2,y2;x3,y3;x4,y4 -> dst uses screen corners",
    )
    # Smoothing
    p.add_argument("--ema", type=float, default=0.5)
    p.add_argument("--deadzone", type=int, default=2)
    p.add_argument("--max-step", type=int, default=50)
    # Controller
    p.add_argument("--tick-hz", type=float, default=240.0)
    p.add_argument("--debug", action="store_true")
    # Overlay / display
    p.add_argument("--overlay", action="store_true")
    p.add_argument("--scale", type=float, default=1.0)
    return p.parse_args()


def build_config(ns: argparse.Namespace) -> PipelineConfig:
    from aimval_tracker.config import (
        HSVRange,
        ROI,
        TrackerConfig,
        MappingConfig,
        SmoothingConfig,
        ControllerConfig,
    )

    if ns.roi:
        try:
            x, y, w, h = [int(v) for v in ns.roi.split(",")]
            roi = ROI(x=x, y=y, w=w, h=h)
            use_roi = True
        except Exception:
            roi = ROI()
            use_roi = False
    else:
        roi = ROI()
        use_roi = False

    sw, sh = [int(v) for v in ns.screen.lower().split("x")]

    tracker = TrackerConfig(
        hsv=HSVRange(ns.h_low, ns.s_low, ns.v_low, ns.h_high, ns.s_high, ns.v_high),
        min_area=ns.min_area,
        blur_kernel=ns.blur,
        morph_kernel=ns.morph,
        use_roi=use_roi,
        roi=roi,
        target_mode=ns.target,
    )

    mapping = MappingConfig(screen_size=(sw, sh), method=ns.mapping)
    if ns.mapping == "homography" and ns.homography:
        try:
            parts = ns.homography.split(";")
            src_pts = []
            for p in parts:
                x, y = [float(v) for v in p.split(",")]
                src_pts.append((x, y))
            if len(src_pts) == 4:
                mapping.homography_src = tuple(src_pts)
                mapping.homography_dst = (
                    (0, 0),
                    (sw - 1, 0),
                    (sw - 1, sh - 1),
                    (0, sh - 1),
                )
        except Exception:
            pass

    smoothing = SmoothingConfig(
        ema_alpha=ns.ema, deadzone_px=ns.deadzone, max_step_px=ns.max_step
    )
    controller = ControllerConfig(
        debug=ns.debug, auto_reconnect=True, tick_hz=ns.tick_hz
    )

    cfg = PipelineConfig(
        udp_host=ns.udp_host,
        udp_port=ns.udp_port,
        tracker=tracker,
        mapping=mapping,
        smoothing=smoothing,
        controller=controller,
        show_overlay=ns.overlay,
        display_scale=ns.scale,
    )
    return cfg


async def run_pipeline(cfg: PipelineConfig) -> None:
    stream = UDPJPEGStream(cfg.udp_host, cfg.udp_port)
    tracker = HSVTracker(cfg.tracker)

    if (
        cfg.mapping.method == "homography"
        and cfg.mapping.homography_src
        and cfg.mapping.homography_dst
    ):
        mapper = HomographyMapper(cfg.mapping)
    else:
        mapper = LinearMapper(cfg.mapping)

    smoother = EMASmoother(cfg.smoothing)
    timer = FrameTimer()
    window = None

    async with MakcuAsyncController(cfg.controller) as ctrl:
        # Assume starting from the center of the screen for estimate
        sw, sh = cfg.mapping.screen_size
        ctrl.set_estimated_cursor(sw / 2, sh / 2)

        for frame in stream.frames():
            timer.tick()
            h, w = frame.shape[:2]

            centroid, mask_bgr, roi_rect = tracker.process(frame)

            target_scr: Optional[Tuple[int, int]] = None
            if centroid is not None:
                x_scr, y_scr = mapper.map_point(centroid, (w, h))
                target_scr = (x_scr, y_scr)

            # Prepare visualization
            disp = frame
            if cfg.show_overlay:
                disp = draw_overlay(disp, centroid, target_scr, roi_rect, timer)
                # Small debug mask inset
                try:
                    mask_small = cv2.resize(mask_bgr, (w // 4, h // 4))
                    disp[0 : h // 4, 0 : w // 4] = mask_small
                except cv2.error:
                    pass

            if cfg.display_scale != 1.0:
                try:
                    disp = cv2.resize(
                        disp, None, fx=cfg.display_scale, fy=cfg.display_scale
                    )
                except cv2.error:
                    pass

            # Control loop at frame cadence (can decouple to tick-hz with task)
            est = ctrl.get_estimated_cursor()
            if target_scr is not None and est is not None:
                smoothed = smoother.smooth(target_scr)
                if smoothed is None:
                    smoothed = (float(target_scr[0]), float(target_scr[1]))
                dx, dy = smoother.step_delta(est, smoothed)
                await ctrl.move_delta(dx, dy)
            else:
                # No target detected; keep smoother state but don't move
                smoother.smooth(None)

            # Show window and handle quit
            if window is None:
                try:
                    cv2.namedWindow("AimVal Tracker", cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(
                        "AimVal Tracker",
                        min(1280, disp.shape[1]),
                        min(720, disp.shape[0]),
                    )
                    window = "AimVal Tracker"
                except cv2.error:
                    window = None
            if window is not None:
                try:
                    cv2.imshow(window, disp)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error:
                    window = None


def main() -> None:
    args = parse_args()
    cfg = build_config(args)
    asyncio.run(run_pipeline(cfg))


if __name__ == "__main__":
    main()
