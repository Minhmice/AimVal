#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from typing import Optional, Tuple
import socket
import threading
import time

import cv2

from aimval_tracker import (
    PipelineConfig,
    HSVTracker,
    LinearMapper,
    HomographyMapper,
    EMASmoother,
    MakcuAsyncController,
    FrameTimer,
    draw_overlay,
)
from aimval_tracker.ui import TrackerUI
import udp_viewer_2 as uv2


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
    p.add_argument(
        "--log-level",
        type=str,
        default="warn",
        choices=["error", "warn", "info", "debug"],
    )
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


def _should_log(ns_level: str, msg_level: str) -> bool:
    levels = {"error": 40, "warn": 30, "info": 20, "debug": 10}
    return levels.get(msg_level, 20) >= levels.get(ns_level, 30)


async def run_pipeline(
    cfg: PipelineConfig, ns: argparse.Namespace | None = None
) -> None:
    # Use udp_viewer_2 receiver for frames
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Allow quick rebinding if previous run left port in TIME_WAIT
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024 * 1024)
    except OSError:
        pass
    try:
        sock.bind((cfg.udp_host, int(cfg.udp_port)))
    except OSError as e:
        print(f"[ERROR] UDP bind failed on {cfg.udp_host}:{cfg.udp_port} - {e}")
        ui_temp = TrackerUI(cfg, lambda c: None)
        try:
            ui_temp.set_loader_text(
                f"Port {cfg.udp_port} in use. Close other app or change port."
            )
        except Exception:
            pass
        raise
    sock.setblocking(False)

    store = uv2.FrameBuffer()
    recv_thread = uv2.ReceiverThread(sock, 64 * 1024 * 1024, store)
    recv_thread.start()

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

    # UI setup
    state = {"cfg": cfg, "tracker": tracker, "mapper": None, "smoother": smoother}

    def on_config_change(new_cfg: PipelineConfig) -> None:
        state["cfg"] = new_cfg
        state["tracker"] = HSVTracker(new_cfg.tracker)
        if (
            new_cfg.mapping.method == "homography"
            and new_cfg.mapping.homography_src
            and new_cfg.mapping.homography_dst
        ):
            state["mapper"] = HomographyMapper(new_cfg.mapping)
        else:
            state["mapper"] = LinearMapper(new_cfg.mapping)
        state["smoother"] = EMASmoother(new_cfg.smoothing)

    def restart_udp():
        nonlocal sock, store, recv_thread
        try:
            print(
                f"[INFO] Restarting UDP on {state['cfg'].udp_host}:{state['cfg'].udp_port}"
            )
            recv_thread.stop()
            recv_thread.join(timeout=1.0)
            sock.close()
        except Exception:
            pass
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024 * 1024)
        except OSError:
            pass
        try:
            sock.bind((state["cfg"].udp_host, int(state["cfg"].udp_port)))
        except OSError as e:
            print(f"[ERROR] UDP rebinding failed: {e}")
            return
        sock.setblocking(False)
        store = uv2.FrameBuffer()
        recv_thread = uv2.ReceiverThread(sock, 64 * 1024 * 1024, store)
        recv_thread.start()

    ui = TrackerUI(cfg, on_config_change, on_apply_udp=restart_udp)
    ui.build()
    ui.request_show_loader()
    threading.Thread(target=ui.render_loop, daemon=True).start()

    async with MakcuAsyncController(cfg.controller) as ctrl:
        # Assume starting from the center of the screen for estimate
        sw, sh = cfg.mapping.screen_size
        ctrl.set_estimated_cursor(sw / 2, sh / 2)

        # Prepare JPEG decoder (TurboJPEG if available via uv2)
        use_turbo = False
        jpeg_decoder = None
        if uv2.TurboJPEG is not None:
            try:
                jpeg_decoder = uv2.TurboJPEG()
                use_turbo = True
            except Exception:
                jpeg_decoder = None
                use_turbo = False

        try:
            while True:
                buf = store.get_latest()
                if buf is None:
                    await asyncio.sleep(0.001)
                    continue
                t0 = time.monotonic_ns()
                if use_turbo and jpeg_decoder is not None:
                    try:
                        frame = jpeg_decoder.decode(buf)
                    except Exception:
                        frame = uv2.decode_jpeg_cv2(buf)
                else:
                    frame = uv2.decode_jpeg_cv2(buf)
                if frame is None:
                    continue
                # first frame -> switch UI to main
                if ns is None or _should_log(ns.log_level, "info"):
                    ui.request_show_main()

                timer.tick()
                h, w = frame.shape[:2]

                centroid, mask_bgr, roi_rect = state["tracker"].process(frame)
            if centroid is None and (ns is None or _should_log(ns.log_level, "debug")):
                print("[DEBUG] No target found in frame")

            target_scr: Optional[Tuple[int, int]] = None
            mapper_obj = state["mapper"]
            if mapper_obj is None:
                if (
                    cfg.mapping.method == "homography"
                    and cfg.mapping.homography_src
                    and cfg.mapping.homography_dst
                ):
                    mapper_obj = HomographyMapper(cfg.mapping)
                else:
                    mapper_obj = LinearMapper(cfg.mapping)
                state["mapper"] = mapper_obj
            if centroid is not None:
                x_scr, y_scr = mapper_obj.map_point(centroid, (w, h))
                target_scr = (x_scr, y_scr)
            else:
                if ns is None or _should_log(ns.log_level, "debug"):
                    print("[DEBUG] centroid None; skip mapping")

            # Prepare visualization
            disp = frame
            if cfg.show_overlay:
                disp = draw_overlay(
                    disp,
                    centroid,
                    target_scr,
                    roi_rect,
                    timer,
                    show_box=state["cfg"].show_box,
                )
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
            if target_scr is not None and est is not None and state["cfg"].aimbot:
                smoothed = state["smoother"].smooth(target_scr)
                if smoothed is None:
                    smoothed = (float(target_scr[0]), float(target_scr[1]))
                dx, dy = state["smoother"].step_delta(est, smoothed)
                await ctrl.move_delta(dx, dy)
            else:
                if (ns is None or _should_log(ns.log_level, "info")) and not state[
                    "cfg"
                ].aimbot:
                    print("[INFO] aimbot off; not moving")
                if (
                    ns is None or _should_log(ns.log_level, "debug")
                ) and target_scr is None:
                    print("[DEBUG] target_scr None; not moving")
                # No target or disabled control: keep smoother state but don't move
                state["smoother"].smooth(None)

                # Send frame to UI viewer (top area) and step UI once (reduces chance of UI freeze)
                ui.set_frame(disp)
                try:
                    ui.render_step()
                except Exception as e:
                    if ns is None or _should_log(ns.log_level, "warn"):
                        print(f"[UI] render_step error: {e}")
        except asyncio.CancelledError:
            if ns is None or _should_log(ns.log_level, "info"):
                print("[INFO] Run loop cancelled; shutting down...")
        finally:
            # Cleanup
            try:
                recv_thread.stop()
                recv_thread.join(timeout=1.0)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass


def main() -> None:
    args = parse_args()
    cfg = build_config(args)
    try:
        asyncio.run(run_pipeline(cfg, args))
    except KeyboardInterrupt:
        if _should_log(args.log_level, "info"):
            print("[INFO] Interrupted by user")


if __name__ == "__main__":
    main()
