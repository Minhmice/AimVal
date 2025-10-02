import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import onnxruntime as ort  # type: ignore
except Exception:
    ort = None  # type: ignore
    _ORT_IMPORT_MSG_PRINTED = False

import cv2

from config import config
import detection_color as color_detection


class _OrtSessionManager:
    def __init__(self):
        self._session = None
        self._provider_in_use = "CPUExecutionProvider"
        self._input_name = None
        self._output_name = None
        self._image_size = 640
        self._warm = False
        self._init_attempted = False

    def _pick_providers(self, runtime_cfg: Dict) -> List[str]:
        active = runtime_cfg.get("active_provider", "auto")
        order = runtime_cfg.get("providers_order", [
            "DmlExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ])
        available = []
        try:
            if ort is not None:
                available = list(ort.get_available_providers())
        except Exception:
            available = []

        if active != "auto":
            if available and active not in available:
                fb = "CPUExecutionProvider" if "CPUExecutionProvider" in available else (available[0] if available else active)
                print(f"[Detect] Requested provider '{active}' not available. Available: {available}. Falling back to '{fb}'.")
                return [fb]
            return [active]

        if available:
            for p in order:
                if p in available:
                    return [p]
            if "CPUExecutionProvider" in available:
                return ["CPUExecutionProvider"]
            return [available[0]]

        return list(order)

    def _try_create_session(self, model_path: str, provider: str, runtime_cfg: Dict):
        if ort is None:
            raise RuntimeError("onnxruntime not available")
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(runtime_cfg.get("num_threads", {}).get("intra_op", 0) or 0)
        so.inter_op_num_threads = int(runtime_cfg.get("num_threads", {}).get("inter_op", 0) or 0)
        opt_level = runtime_cfg.get("graph_optimization", "all").lower()
        if opt_level == "all":
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        elif opt_level == "basic":
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        elif opt_level == "extended":
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
        else:
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        exec_mode = runtime_cfg.get("execution_mode", "parallel").lower()
        if exec_mode == "sequential":
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        else:
            so.execution_mode = ort.ExecutionMode.ORT_PARALLEL
        providers = [provider]
        try:
            sess = ort.InferenceSession(model_path, sess_options=so, providers=providers)
            return sess
        except Exception as e:
            raise e

    def reinit(self, runtime_cfg: Dict) -> Tuple[bool, str]:
        global _ORT_IMPORT_MSG_PRINTED
        self._init_attempted = True
        if ort is None:
            if not _ORT_IMPORT_MSG_PRINTED:
                prov = runtime_cfg.get("active_provider", "auto")
                hint = "pip install onnxruntime"
                if prov in ("DmlExecutionProvider", "auto"):
                    hint = "pip install onnxruntime-directml"
                elif prov == "CUDAExecutionProvider":
                    hint = "pip install onnxruntime-gpu"
                print(f"[Detect] ONNX Runtime not installed. Install with: {hint}")
                _ORT_IMPORT_MSG_PRINTED = True
            return False, "ORT Missing"
        model_path = runtime_cfg.get("model_path", "")
        if not model_path or not os.path.exists(model_path):
            self._session = None
            self._provider_in_use = "CPUExecutionProvider"
            return False, "No model"
        providers = self._pick_providers(runtime_cfg)
        last_err = None
        for p in providers:
            try:
                sess = self._try_create_session(model_path, p, runtime_cfg)
                self._session = sess
                self._provider_in_use = p
                self._input_name = runtime_cfg.get("input_name")
                self._output_name = runtime_cfg.get("output_name")
                self._image_size = int(runtime_cfg.get("image_size", 640))
                self._warm = False
                return True, p
            except Exception as e:
                last_err = e
                continue
        try:
            if ort is not None:
                sess = self._try_create_session(model_path, "CPUExecutionProvider", runtime_cfg)
                self._session = sess
                self._provider_in_use = "CPUExecutionProvider"
                self._input_name = runtime_cfg.get("input_name")
                self._output_name = runtime_cfg.get("output_name")
                self._image_size = int(runtime_cfg.get("image_size", 640))
                self._warm = False
                print("[Detect] Provider fallback to CPUExecutionProvider")
                return True, "CPUExecutionProvider"
        except Exception as e:
            last_err = e
        if not _ORT_IMPORT_MSG_PRINTED:
            print(f"[Detect] Failed to init ORT session: {last_err}")
        self._session = None
        return False, "CPUExecutionProvider"

    def ensure_warm(self, runtime_cfg: Dict):
        if self._session is None or self._warm:
            return
        warmup = int(runtime_cfg.get("warmup_runs", 1))
        s = int(self._image_size)
        dummy = np.zeros((1, 3, s, s), dtype=np.float32)
        inp = self._input_name or self._session.get_inputs()[0].name
        for _ in range(max(0, warmup)):
            try:
                self._session.run(None, {inp: dummy})
            except Exception:
                break
        self._warm = True

    def run(self, inp_tensor: np.ndarray, runtime_cfg: Dict) -> Optional[np.ndarray]:
        if self._session is None:
            return None
        self.ensure_warm(runtime_cfg)
        inp_name = self._input_name or self._session.get_inputs()[0].name
        out_name = self._output_name
        if out_name:
            outs = self._session.run([out_name], {inp_name: inp_tensor})
        else:
            outs = self._session.run(None, {inp_name: inp_tensor})
        out = outs[0]
        return out

    @property
    def image_size(self) -> int:
        return int(self._image_size)

    @property
    def provider(self) -> str:
        return str(self._provider_in_use)


_ORT = _OrtSessionManager()


def _preprocess_bgra_to_nchw(roi_bgra: np.ndarray, size: int, runtime_cfg: Dict) -> np.ndarray:
    rgb = cv2.cvtColor(roi_bgra, cv2.COLOR_BGRA2RGB)
    h, w = rgb.shape[:2]
    if h != size or w != size:
        min_side = min(h, w)
        y0 = max(0, (h - min_side) // 2)
        x0 = max(0, (w - min_side) // 2)
        crop = rgb[y0:y0 + min_side, x0:x0 + min_side]
        rgb = cv2.resize(crop, (size, size), interpolation=cv2.INTER_LINEAR)
    img = rgb.astype(np.float32)
    if runtime_cfg.get("normalize", True):
        mean = runtime_cfg.get("mean", [0.0, 0.0, 0.0])
        std = runtime_cfg.get("std", [255.0, 255.0, 255.0])
        m = np.array(mean, dtype=np.float32).reshape(1, 1, 3)
        s = np.array(std, dtype=np.float32).reshape(1, 1, 3)
        img = (img - m) / (s + 1e-8)
    chw = np.transpose(img, (2, 0, 1))
    nchw = np.expand_dims(chw, 0)
    return nchw


def _iou_xywh(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    inter_w = max(0.0, min(ax2, bx2) - max(ax, bx))
    inter_h = max(0.0, min(ay2, by2) - max(ay, by))
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def _nms(dets: List[Dict], iou_thr: float, class_agnostic: bool, max_det: int) -> List[Dict]:
    if not dets:
        return []
    dets_sorted = sorted(dets, key=lambda d: d.get("conf", 0.0), reverse=True)
    picked: List[Dict] = []
    for d in dets_sorted:
        keep = True
        for p in picked:
            if (class_agnostic or d.get("class_id") == p.get("class_id")):
                i = _iou_xywh((d["x"], d["y"], d["w"], d["h"]), (p["x"], p["y"], p["w"], p["h"]))
                if i >= iou_thr:
                    keep = False
                    break
        if keep:
            picked.append(d)
            if len(picked) >= max(1, int(max_det)):
                break
    return picked


def _parse_yolov8_output(out: np.ndarray, class_names: List[str], cfg_det: Dict) -> List[Dict]:
    if out is None:
        return []
    arr = out
    if isinstance(arr, list):
        arr = arr[0]
    if arr.ndim != 3:
        return []
    _, ch, N = arr.shape
    C = ch - 4
    dets: List[Dict] = []
    for i in range(N):
        x = float(arr[0, 0, i])
        y = float(arr[0, 1, i])
        w = float(arr[0, 2, i])
        h = float(arr[0, 3, i])
        if C <= 1:
            score = float(arr[0, 4, i]) if ch > 4 else 0.0
            cls_id = 0
        else:
            scores = arr[0, 4:4 + C, i]
            cls_id = int(np.argmax(scores))
            score = float(scores[cls_id])
        if class_names and 0 <= cls_id < len(class_names):
            cls_name = class_names[cls_id]
        else:
            cls_name = f"class_{cls_id}"
        dets.append({"cx": x, "cy": y, "w": w, "h": h, "conf": score, "class_id": cls_id, "class_name": cls_name})
    return dets


def _center_distance(cx: float, cy: float, w: int, h: int) -> float:
    return float(np.hypot(cx - (w / 2.0), cy - (h / 2.0)))


class DetectState:
    def __init__(self):
        self.sticky_target: Optional[Dict] = None
        self.lost_frames: int = 0
        self.last_timing_print_ms: int = 0
        self.last_save_ms: int = 0
        self.last_infer_ms: int = 0


def ai_detect_step(
    roi_bgra: np.ndarray,
    roi_rect_screen: Dict,
    cfg_runtime: Dict,
    cfg_detection: Dict,
    state: DetectState,
    debug_cfg: Optional[Dict] = None,
) -> Dict[str, Any]:
    debug_cfg = debug_cfg or {}
    timings_en = bool(debug_cfg.get("timings", {}).get("enabled", False))
    timings_every = int(debug_cfg.get("timings", {}).get("print_every_ms", 300))
    t0 = time.perf_counter_ns()

    source = cfg_detection.get("source", "color")

    h, w = roi_bgra.shape[:2]
    dets: List[Dict] = []
    mask_bgr = None
    stage_pre_ms = stage_inf_ms = stage_parse_ms = stage_filt_ms = stage_sel_ms = 0.0

    if source == "ai":
        cap = int(cfg_runtime.get("inference_fps_cap", 0))
        if cap > 0 and state.last_infer_ms:
            now_ms = int(time.time() * 1000)
            min_dt = int(1000 / max(1, cap))
            if now_ms - state.last_infer_ms < min_dt:
                return {"detections": [], "selected": None, "last_detection_box_screen": None}

        if _ORT._session is None:
            _ORT.reinit(cfg_runtime)

        size = int(cfg_runtime.get("image_size", 640))
        inp = _preprocess_bgra_to_nchw(roi_bgra, size, cfg_runtime)
        t1 = time.perf_counter_ns()
        out = None
        if _ORT._session is not None:
            out = _ORT.run(inp, cfg_runtime)
            t2 = time.perf_counter_ns()
            names = []
            try:
                meta = _ORT._session.get_modelmeta().custom_metadata_map
                if isinstance(meta, dict) and "names" in meta:
                    import json
                    try:
                        parsed = json.loads(meta["names"]) if isinstance(meta["names"], str) else meta["names"]
                        if isinstance(parsed, dict):
                            names = [parsed[str(i)] for i in range(len(parsed))]
                        elif isinstance(parsed, list):
                            names = [str(x) for x in parsed]
                    except Exception:
                        pass
            except Exception:
                pass
            if not names:
                names = cfg_detection.get("classes", {}).get("class_names", []) or []
            parsed = _parse_yolov8_output(out, names, cfg_detection)
            t3 = time.perf_counter_ns()
            tmp = []
            for d in parsed:
                cx, cy, bw, bh = d["cx"], d["cy"], d["w"], d["h"]
                x = cx - bw / 2.0
                y = cy - bh / 2.0
                tmp.append({"x": x, "y": y, "w": bw, "h": bh, "conf": d.get("conf", 0.0), "class_id": d.get("class_id", 0), "class_name": d.get("class_name", "")})
            dets = tmp
            t4 = time.perf_counter_ns()
            stage_pre_ms = (t1 - t0) / 1e6
            stage_inf_ms = (t2 - t1) / 1e6
            stage_parse_ms = (t3 - t2) / 1e6
            stage_filt_ms = (t4 - t3) / 1e6
            state.last_infer_ms = int(time.time() * 1000)
        else:
            # No fallback to color in AI mode per requirement
            dets = []
            mask_bgr = None
    else:
        bgr = cv2.cvtColor(roi_bgra, cv2.COLOR_BGRA2BGR)
        t1 = time.perf_counter_ns()
        try:
            results, mask = color_detection.perform_detection(color_detection._model, bgr)
        except Exception:
            results, mask = [], None
        t2 = time.perf_counter_ns()
        dets = []
        for r in results or []:
            x, y, bw, bh = r.get("bbox", (0, 0, 0, 0))
            dets.append({
                "x": float(x), "y": float(y), "w": float(bw), "h": float(bh),
                "conf": 1.0, "class_id": 0, "class_name": "color",
            })
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR) if mask is not None and len(mask.shape) == 2 else mask
        stage_pre_ms = (t1 - t0) / 1e6
        stage_inf_ms = (t2 - t1) / 1e6

    conf_thr = float(cfg_detection.get("confidence_threshold", 0.25))
    fov_clip = bool(cfg_detection.get("postprocess", {}).get("clip_to_fov", False))
    min_area = float(cfg_detection.get("postprocess", {}).get("min_box_area", 0))
    max_area = float(cfg_detection.get("postprocess", {}).get("max_box_area", 1e12))
    wR, hR = w, h
    filtered: List[Dict] = []
    for d in dets:
        if d.get("conf", 0.0) < conf_thr:
            continue
        x, y, bw, bh = d["x"], d["y"], d["w"], d["h"]
        if fov_clip:
            if x < 0 or y < 0 or x + bw > wR or y + bh > hR:
                continue
        area = max(0.0, bw) * max(0.0, bh)
        if area < min_area or area > max_area:
            continue
        filtered.append(d)

    nms_cfg = cfg_detection.get("nms", {"enabled": True, "iou_threshold": 0.5, "max_detections": 100, "class_agnostic": False})
    if nms_cfg.get("enabled", True):
        filtered = _nms(filtered, float(nms_cfg.get("iou_threshold", 0.5)), bool(nms_cfg.get("class_agnostic", False)), int(nms_cfg.get("max_detections", 100)))

    max_targets = int(cfg_detection.get("target_selection", {}).get("max_targets_considered", 200))
    if len(filtered) > max_targets:
        filtered = sorted(filtered, key=lambda d: d.get("conf", 0.0), reverse=True)[:max_targets]

    tsel = cfg_detection.get("target_selection", {})
    nearest_k = int(tsel.get("nearest_k", 1))
    strategy = tsel.get("strategy", "nearest_to_center")
    selected = None
    if filtered:
        if strategy == "nearest_to_center":
            dists = [(i, _center_distance(f["x"] + f["w"] / 2.0, f["y"] + f["h"] / 2.0, wR, hR)) for i, f in enumerate(filtered)]
            dists.sort(key=lambda x: x[1])
            topk = [filtered[i] for i, _ in dists[:max(1, nearest_k)]]
            selected = max(topk, key=lambda d: d.get("conf", 0.0))
        else:
            selected = max(filtered, key=lambda d: d.get("conf", 0.0))

    st_cfg = tsel.get("sticky_aim", {"enabled": False, "threshold_px": 30, "max_lost_frames": 10})
    if st_cfg.get("enabled", False):
        th = float(st_cfg.get("threshold_px", 30))
        if selected is not None:
            cx = selected["x"] + selected["w"] / 2.0
            cy = selected["y"] + selected["h"] / 2.0
            if state.sticky_target is not None:
                pcx = state.sticky_target["x"] + state.sticky_target["w"] / 2.0
                pcy = state.sticky_target["y"] + state.sticky_target["h"] / 2.0
                if np.hypot(cx - pcx, cy - pcy) <= th:
                    selected = state.sticky_target
                    state.lost_frames = 0
                else:
                    state.sticky_target = selected
                    state.lost_frames = 0
            else:
                state.sticky_target = selected
                state.lost_frames = 0
        else:
            if state.sticky_target is not None:
                state.lost_frames += 1
                if state.lost_frames <= int(st_cfg.get("max_lost_frames", 10)):
                    selected = state.sticky_target
                else:
                    state.sticky_target = None
                    state.lost_frames = 0
    else:
        state.sticky_target = selected
        state.lost_frames = 0 if selected is not None else state.lost_frames

    last_detection_box_screen = None
    if selected is not None:
        x = max(0, int(round(selected["x"])))
        y = max(0, int(round(selected["y"])))
        bw = max(0, int(round(selected["w"])))
        bh = max(0, int(round(selected["h"])))
        left = int(roi_rect_screen.get("left", 0))
        top = int(roi_rect_screen.get("top", 0))
        last_detection_box_screen = {"x": left + x, "y": top + y, "w": bw, "h": bh}

    t_end = time.perf_counter_ns()
    stage_sel_ms = (t_end - t0) / 1e6 - stage_pre_ms - stage_inf_ms - stage_parse_ms - stage_filt_ms
    if timings_en:
        now_ms = int(time.time() * 1000)
        if now_ms - state.last_timing_print_ms >= max(1, timings_every):
            print(f"[Detect] pre:{stage_pre_ms:.2f}ms inf:{stage_inf_ms:.2f}ms parse:{stage_parse_ms:.2f}ms filt:{stage_filt_ms:.2f}ms sel:{stage_sel_ms:.2f}ms N:{len(filtered)} prov:{_ORT.provider if source=='ai' else 'color'}")
            state.last_timing_print_ms = now_ms

    sf = cfg_detection.get("save_frames", {"enabled": False, "cooldown_ms": 1000, "images_dir": "captures", "labels_dir": "captures"})
    if sf.get("enabled", False):
        now_ms = int(time.time() * 1000)
        if now_ms - state.last_save_ms >= int(sf.get("cooldown_ms", 1000)):
            try:
                os.makedirs(sf.get("images_dir", "captures"), exist_ok=True)
                os.makedirs(sf.get("labels_dir", "captures"), exist_ok=True)
                ts = now_ms
                img_path = os.path.join(sf.get("images_dir", "captures"), f"roi_{ts}.jpg")
                cv2.imwrite(img_path, cv2.cvtColor(roi_bgra, cv2.COLOR_BGRA2BGR))
                if filtered:
                    lbl_path = os.path.join(sf.get("labels_dir", "captures"), f"roi_{ts}.txt")
                    with open(lbl_path, "w") as f:
                        for d in filtered:
                            cx = (d["x"] + d["w"] / 2.0) / max(1, w)
                            cy = (d["y"] + d["h"] / 2.0) / max(1, h)
                            ww = d["w"] / max(1, w)
                            hh = d["h"] / max(1, h)
                            f.write(f"{int(d.get('class_id',0))} {cx:.6f} {cy:.6f} {ww:.6f} {hh:.6f}\n")
                state.last_save_ms = now_ms
            except Exception as e:
                print(f"[Detect] save_frames error: {e}")

    unified = []
    for d in filtered:
        ux = d["x"] + d["w"] / 2.0
        uy = d["y"] + d["h"] / 2.0
        unified.append({
            "cx": ux,
            "cy": uy,
            "w": d["w"],
            "h": d["h"],
            "conf": d.get("conf", 0.0),
            "class_id": d.get("class_id", 0),
            "class_name": d.get("class_name", ""),
        })

    sel_unified = None
    if selected is not None:
        sel_unified = {
            "cx": selected["x"] + selected["w"] / 2.0,
            "cy": selected["y"] + selected["h"] / 2.0,
            "w": selected["w"],
            "h": selected["h"],
            "conf": selected.get("conf", 0.0),
            "class_id": selected.get("class_id", 0),
            "class_name": selected.get("class_name", ""),
        }

    return {
        "detections": unified,
        "selected": sel_unified,
        "last_detection_box_screen": last_detection_box_screen,
        "mask_bgr": mask_bgr,
    }


def reinit_session(model_path: str, active_provider: str, runtime_cfg: Dict) -> Tuple[bool, str]:
    cfg = dict(runtime_cfg)
    cfg["model_path"] = model_path
    cfg["active_provider"] = active_provider
    ok, provider = _ORT.reinit(cfg)
    return ok, provider


