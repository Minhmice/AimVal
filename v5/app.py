import os
import json
import time
import cv2

from detectors.hsv_color import HSVColorDetector
from framesource.udp_mjpeg import UdpMjpegSource
from hardware.makcu_controller import MakcuController
from actions.aim_trigger import AimTrigger

try:
    from framesource.udp_opencv import UdpOpenCVSource
except Exception:
    UdpOpenCVSource = None  # type: ignore

try:
    from logger.metrics import MetricsLogger
except Exception:
    MetricsLogger = None  # type: ignore


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_source(cfg: dict):
    udp_cfg = cfg.get("udp", {})
    mode = udp_cfg.get("mode", "mjpeg").lower()
    if mode == "mjpeg":
        port = int(udp_cfg.get("mjpeg_port", 8080))
        return UdpMjpegSource(host="0.0.0.0", port=port, rcvbuf_mb=64)
    elif mode == "opencv":
        if UdpOpenCVSource is None:
            raise RuntimeError("UdpOpenCVSource not available")
        url = udp_cfg.get("url", "udp://@:5600")
        max_w = int(udp_cfg.get("max_width", 1280))
        max_h = int(udp_cfg.get("max_height", 720))
        return UdpOpenCVSource(url=url, max_width=max_w, max_height=max_h)
    elif mode in ("rtsp", "file", "webcam"):
        from framesource.file_reader import FileReaderSource

        url = udp_cfg.get("url", 0 if mode == "webcam" else "")
        return FileReaderSource(url)
    else:
        raise ValueError(f"Unsupported udp.mode: {mode}")


def draw_boxes(bgr, boxes, thick=2, font_scale=0.5):
    color_map = {
        "hsv": (0, 255, 0),
        "ai": (0, 165, 255),
        "fused": (255, 0, 0),
    }
    for b in boxes:
        x1, y1, x2, y2 = b.as_xyxy()
        color = color_map.get(b.source, (255, 255, 255))
        cv2.rectangle(bgr, (x1, y1), (x2, y2), color, thick)
        label = f"{b.label}:{b.score:.2f}"
        cv2.putText(
            bgr,
            label,
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            1,
            cv2.LINE_AA,
        )
    return bgr


def verify_on_target_mask(
    mask, cx: int, cy: int, scan_h: int = 15, scan_w: int = 5
) -> bool:
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
        has_above = (
            (roi_above is not None)
            and (roi_above.size > 0)
            and int(cv2.countNonZero(roi_above)) > 0
        )
    if y_below_end > y_below_start:
        roi_below = mask[y_below_start:y_below_end, x1:x2]
        has_below = (
            (roi_below is not None)
            and (roi_below.size > 0)
            and int(cv2.countNonZero(roi_below)) > 0
        )
    return has_above and has_below


def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "configs", "default.json")
    cfg = load_config(cfg_path)

    visual = cfg.get("visual", {})
    show_boxes = bool(visual.get("show_boxes", True))
    show_mask = bool(visual.get("show_mask", False))
    thickness = int(visual.get("thickness", 2))
    font_scale = float(visual.get("font_scale", 0.5))

    # Build sources
    source = build_source(cfg)
    if not source.start():
        print("Không thể khởi động nguồn khung hình.")
        return

    # Detectors
    hsv_det = HSVColorDetector(cfg.get("hsv", {}))

    # Actions / Makcu
    actions_cfg = cfg.get("actions", {})
    makcu = MakcuController()
    aim_trigger = AimTrigger(actions_cfg, makcu)

    # Logger
    metrics_cfg = cfg.get("logging", {})
    if MetricsLogger is not None and bool(metrics_cfg.get("enabled", True)):
        logger = MetricsLogger(
            metrics_cfg.get("csv_path", "logs/metrics.csv"),
            int(metrics_cfg.get("log_every_n_frames", 20)),
        )
        session_meta = {
            "session_id": int(time.time()),
            "config": os.path.basename(cfg_path),
        }
        logger.start_session(session_meta)
    else:
        logger = None

    last = time.perf_counter()
    frame_idx = 0

    try:
        while True:
            bgr = source.get_latest_frame()
            if bgr is None:
                time.sleep(0.005)
                continue

            t0 = time.perf_counter()
            boxes, debug = hsv_det.infer(bgr)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            now = time.perf_counter()
            dt = now - last
            fps = 1.0 / dt if dt > 0 else 0.0
            last = now

            mask = debug.get("mask") if isinstance(debug, dict) else None
            if show_mask and mask is not None:
                cv2.imshow("Mask", mask)

            vis = bgr.copy()
            if show_boxes:
                vis = draw_boxes(vis, boxes, thick=thickness, font_scale=font_scale)
            cv2.imshow("Overlay", vis)

            # Aim & Trigger steps (center-based)
            h, w = bgr.shape[:2]
            cx, cy = w // 2, h // 2
            is_on_target = (
                verify_on_target_mask(mask, cx, cy) if mask is not None else False
            )
            try:
                aim_trigger.aim_step(bgr, boxes)
                aim_trigger.trigger_step(bgr, is_on_target)
            except Exception:
                pass
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            if logger is not None:
                logger.maybe_log(
                    frame_idx,
                    {
                        "fps": fps,
                        "latency_ms": latency_ms,
                        "num_boxes": len(boxes),
                        "num_keypoints": 0,
                    },
                )

            frame_idx += 1
    finally:
        try:
            source.stop()
        except Exception:
            pass
        try:
            if logger is not None:
                logger.close()
        except Exception:
            pass
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
