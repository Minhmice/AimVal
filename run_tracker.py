#!/usr/bin/env python3
from __future__ import annotations

"""
AimVal runtime orchestrator.
- Serves a lightweight Web UI (FastAPI + WebSocket) for controls and preview
- Consumes UDP MJPEG via `udp_viewer_2` on demand (Connect Stream)
- Tracks the target and conditionally drives mouse via Makcu (Aimbot toggle)

We avoid heavy desktop GUI loops to prevent freezes and keep CPU/GPU low.
"""

import argparse
import asyncio
from typing import Optional, Tuple
import socket
import threading
import time
import sys
import asyncio

# Workaround Windows Proactor issues with background servers (uvicorn websockets)
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

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
from aimval_tracker.ui import TrackerUI
from aimval_tracker.webui import WebTrackerUI
from aimval_tracker.controller import NullController
import udp_viewer_2 as uv2


def parse_args() -> argparse.Namespace:
    """Parse CLI flags. Most runtime controls are in the Web UI."""
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
    """Build a config object (UI can override at runtime)."""
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
    """Return True if `msg_level` should be printed under `ns_level`."""
    levels = {"error": 40, "warn": 30, "info": 20, "debug": 10}
    return levels.get(msg_level, 20) >= levels.get(ns_level, 30)


async def run_pipeline(
    cfg: PipelineConfig, ns: argparse.Namespace | None = None
) -> None:
    """Main async loop coordinating stream, tracking, UI, and controller.

    - Stream is created lazily when the user clicks Connect Stream in the Web UI
    - Frames are decoded and the latest frame is used for tracking
    - Preview frames are pushed to the Web UI via WebSocket
    - Aimbot movement is gated by a toggle and the Makcu connection state
    """
    # Defer opening UDP until user clicks Connect Stream (lighter startup)
    sock: Optional[socket.socket] = None
    store: Optional[uv2.FrameBuffer] = None
    recv_thread: Optional[uv2.ReceiverThread] = None

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

    # UI setup state
    state = {"cfg": cfg, "tracker": tracker, "mapper": None, "smoother": smoother}

    def on_config_change(new_cfg: PipelineConfig) -> None:
        """Apply config changes coming from UI in-place."""
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

    # Prepare Web UI reference for logging from nested handlers
    webui: Optional[WebTrackerUI] = None

    # Hook UI buttons to control connections and tracker
    def connect_stream():
        """Bind UDP socket and start the receiver thread."""
        nonlocal sock, store, recv_thread
        if recv_thread is not None:
            return
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
            print(f"[ERROR] UDP bind failed: {e}")
            try:
                asyncio.get_running_loop().create_task(
                    webui.send_log(f"UDP bind failed: {e}") if webui else asyncio.sleep(0)
                )
            except Exception:
                pass
            return
        sock.setblocking(False)
        store = uv2.FrameBuffer()
        recv_thread = uv2.ReceiverThread(sock, 64 * 1024 * 1024, store)
        recv_thread.start()
        try:
            asyncio.get_running_loop().create_task(
                webui.send_log(
                    f"UDP listening on {state['cfg'].udp_host}:{state['cfg'].udp_port}"
                ) if webui else asyncio.sleep(0)
            )
        except Exception:
            pass

    def disconnect_stream():
        """Stop receiver thread and close socket."""
        nonlocal sock, recv_thread
        try:
            if recv_thread is not None:
                recv_thread.stop()
                recv_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass
        recv_thread = None
        store = None
        sock = None
        try:
            asyncio.get_running_loop().create_task(
                webui.send_log("UDP stream disconnected") if webui else asyncio.sleep(0)
            )
        except Exception:
            pass

    # Makcu connect/disconnect toggles managed by UI
    makcu_connect_requested = {"want": False}

    def request_makcu_connect():
        makcu_connect_requested["want"] = True

    def request_makcu_disconnect():
        makcu_connect_requested["want"] = False

    tracker_enabled = {"on": cfg.aimbot}

    def toggle_tracker(on: bool):
        tracker_enabled["on"] = bool(on)

    def set_udp_from_web(payload: dict) -> None:
        # Update stream-related config (host/port/buffer) and preview scale
        h = payload.get("host")
        p = payload.get("port")
        b = payload.get("rcvbuf_mb")
        s = payload.get("scale")
        if isinstance(h, str):
            state["cfg"].udp_host = h
        if isinstance(p, int):
            state["cfg"].udp_port = p
        if isinstance(s, (int, float)):
            state["cfg"].display_scale = float(s)
        # Apply requires reconnect
        disconnect_stream()
        connect_stream()

    webui = WebTrackerUI(
        on_connect_stream=connect_stream,
        on_disconnect_stream=disconnect_stream,
        on_connect_makcu=request_makcu_connect,
        on_disconnect_makcu=request_makcu_disconnect,
        on_toggle_aimbot=lambda v: toggle_tracker(v),
        on_toggle_box=lambda v: state.setdefault("cfg", cfg) or setattr(state["cfg"], "show_box", v),
        on_set_udp=set_udp_from_web,
    )
    import uvicorn

    def start_web():
        uvicorn.run(webui.app, host="127.0.0.1", port=8765, log_level="warning")

    threading.Thread(target=start_web, daemon=True).start()
    print("[INFO] Web UI at http://127.0.0.1:8765")

    # Makcu connect is user-driven; start with NullController
    ctrl_cm = NullController()
    ctrl = await ctrl_cm.__aenter__()
    using_null = True
    try:
        # Cursor estimate starts at screen center
        sw, sh = cfg.mapping.screen_size
        ctrl.set_estimated_cursor(sw / 2, sh / 2)

        # TurboJPEG if available
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
                # If stream not yet connected, idle light
                if store is None:
                    await asyncio.sleep(0.05)
                    continue
                buf = store.get_latest()
                if buf is None:
                    await asyncio.sleep(0.05)
                    # periodic waiting log
                    try:
                        now = time.monotonic()
                        if 'last_wait_log' not in state:
                            state['last_wait_log'] = 0.0
                        if now - state['last_wait_log'] > 2.0:
                            state['last_wait_log'] = now
                            asyncio.get_running_loop().create_task(
                                webui.send_log("Waiting for frames...") if webui else asyncio.sleep(0)
                            )
                    except Exception:
                        pass
                    continue
                # Decode latest frame
                if use_turbo and jpeg_decoder is not None:
                    try:
                        frame = jpeg_decoder.decode(buf)
                    except Exception:
                        frame = uv2.decode_jpeg_cv2(buf)
                else:
                    frame = uv2.decode_jpeg_cv2(buf)
                if frame is None:
                    continue

                # Makcu connect/disconnect requests
                if using_null and makcu_connect_requested["want"]:
                    try:
                        await ctrl_cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                    try:
                        controller_cm = MakcuAsyncController(state["cfg"].controller)
                        ctrl_cm = controller_cm
                        ctrl = await ctrl_cm.__aenter__()
                        using_null = False
                        print("[INFO] Makcu connected")
                    except Exception as e:
                        print(f"[WARN] Makcu connect failed: {e}")
                        ctrl_cm = NullController()
                        ctrl = await ctrl_cm.__aenter__()
                        using_null = True
                elif (not using_null) and (not makcu_connect_requested["want"]):
                    try:
                        await ctrl_cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                    ctrl_cm = NullController()
                    ctrl = await ctrl_cm.__aenter__()
                    using_null = True
                    print("[INFO] Makcu disconnected")

                # Tracking
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

                # Overlay preview
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
                # Scale down preview for sending
                if cfg.display_scale != 1.0:
                    try:
                        disp = cv2.resize(
                            disp, None, fx=cfg.display_scale, fy=cfg.display_scale
                        )
                    except cv2.error:
                        pass

                # Control loop
                est = ctrl.get_estimated_cursor()
                if target_scr is not None and est is not None and tracker_enabled["on"]:
                    smoothed = state["smoother"].smooth(target_scr)
                    if smoothed is None:
                        smoothed = (float(target_scr[0]), float(target_scr[1]))
                    dx, dy = state["smoother"].step_delta(est, smoothed)
                    await ctrl.move_delta(dx, dy)
                else:
                    # Keep smoother state, but do not move
                    state["smoother"].smooth(None)

                # Push preview to Web UI
                try:
                    await webui.push_frame(disp)
                except Exception:
                    pass
        except asyncio.CancelledError:
            if ns is None or _should_log(ns.log_level, "info"):
                print("[INFO] Run loop cancelled; shutting down...")
        finally:
            # Cleanup
            try:
                if recv_thread is not None:
                    recv_thread.stop()
                    recv_thread.join(timeout=1.0)
            except Exception:
                pass
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass
    finally:
        try:
            await ctrl_cm.__aexit__(None, None, None)
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
