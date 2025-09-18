import customtkinter as ctk
import tkinter as tk
import json
import os
import cv2
from PIL import Image, ImageTk
try:
    from app_controller import PipelineController
except ModuleNotFoundError:
    import sys as _sys
    _sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from app_controller import PipelineController


class App(ctk.CTk):
    def __init__(self, cfg_path: str):
        super().__init__()
        self.title("AimVal v5")
        ctk.set_appearance_mode("Dark")
        self.geometry("1280x800")
        self.cfg_path = cfg_path
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.ctrl = PipelineController(cfg_path)
        self._build_ui()
        # Auto save when closing
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass
        self._tick()

    def _build_ui(self):
        root = ctk.CTkFrame(self)
        root.pack(expand=True, fill="both")
        root.grid_columnconfigure(0, weight=3)
        root.grid_columnconfigure(1, weight=2)
        root.grid_rowconfigure(0, weight=1)

        # Left: Viewer + Controller
        left = ctk.CTkFrame(root)
        left.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=0)
        left.grid_columnconfigure(0, weight=1)

        # Viewer: two fixed square canvases (Vision | Debug)
        viewers = ctk.CTkFrame(left)
        viewers.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        viewers.grid_columnconfigure(0, weight=1)
        viewers.grid_columnconfigure(1, weight=1)
        side = 520
        vision_col = ctk.CTkFrame(viewers)
        vision_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        debug_col = ctk.CTkFrame(viewers)
        debug_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ctk.CTkLabel(vision_col, text="Vision").pack(anchor="w", padx=2)
        ctk.CTkLabel(debug_col, text="Debug").pack(anchor="w", padx=2)
        self.preview = tk.Canvas(
            vision_col, bg="#000000", width=side, height=side, highlightthickness=0
        )
        self.preview.pack()
        self.preview_dbg = tk.Canvas(
            debug_col, bg="#111111", width=side, height=side, highlightthickness=0
        )
        self.preview_dbg.pack()

        # Controller (below viewer)
        ctrl = ctk.CTkFrame(left)
        ctrl.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.status_var = tk.StringVar(value="Trạng thái: Dừng")
        ctk.CTkLabel(ctrl, textvariable=self.status_var).pack(side="left", padx=6)
        ctk.CTkButton(ctrl, text="Bắt đầu", command=self._start).pack(
            side="left", padx=6
        )
        ctk.CTkButton(ctrl, text="Dừng", command=self._stop).pack(side="left", padx=6)
        # Bỏ chọn nguồn/URL/Port để tối giản thanh điều khiển
        # Metrics
        self.fps_var = tk.StringVar(value="FPS: --")
        self.lat_var = tk.StringVar(value="Độ trễ: -- ms")
        ctk.CTkLabel(ctrl, textvariable=self.fps_var).pack(side="right", padx=6)
        ctk.CTkLabel(ctrl, textvariable=self.lat_var).pack(side="right", padx=6)

        # Right: Config tabs
        right = ctk.CTkFrame(root, width=500)
        right.grid(row=0, column=1, sticky="ns", padx=10, pady=10)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        # Cố định độ rộng panel bên phải
        right.grid_propagate(False)

        tabs = ctk.CTkTabview(right)
        tabs.grid(row=0, column=0, sticky="nsew")
        tab_aim = tabs.add("Aim")
        tab_detection = tabs.add("Detection")
        tab_trigger = tabs.add("Trigger")
        tab_advance = tabs.add("Advance")
        tab_setting = tabs.add("Setting")

        self._build_tab_aim(tab_aim)
        self._build_tab_detection(tab_detection)
        self._build_tab_trigger(tab_trigger)
        self._build_tab_advance(tab_advance)
        self._build_tab_setting(tab_setting)

    # ================= Tabs =================
    def _build_tab_aim(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        act = self.cfg.get("actions", {})
        self.var_aim = tk.BooleanVar(value=bool(act.get("aim_enabled", False)))
        ctk.CTkCheckBox(
            frm, text="Bật Aim", variable=self.var_aim, command=self._apply_actions
        ).pack(anchor="w", pady=(0, 8))

        def add_slider(label, min_v, max_v, init_v, step=0.01):
            row = ctk.CTkFrame(frm)
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=label).pack(side="left", padx=6)
            val_var = tk.DoubleVar(value=float(init_v))
            value_label = ctk.CTkLabel(row, text=f"{float(init_v):.2f}")
            value_label.pack(side="right", padx=6)
            slider = ctk.CTkSlider(
                row,
                from_=min_v,
                to=max_v,
                number_of_steps=max(1, int((max_v - min_v) / step)),
            )
            slider.set(float(init_v))
            slider.pack(fill="x", padx=6)

            def on_change(v):
                try:
                    val_var.set(float(v))
                    value_label.configure(text=f"{float(v):.2f}")
                except Exception:
                    pass

            slider.configure(command=on_change)
            return slider, val_var

        # Sliders per-line like v2
        self.msens_s, _ = add_slider(
            "Sensitivity", 0.01, 2.0, act.get("mouse_sensitivity", 0.35)
        )
        self.msmooth_s, _ = add_slider(
            "Smoothness", 0.1, 1.0, act.get("mouse_smoothness", 0.8)
        )
        self.mease = tk.BooleanVar(
            value=bool(self.ctrl.cfg.get("MOUSE_EASE_OUT", True))
        )
        ctk.CTkCheckBox(
            frm, text="Ease out", variable=self.mease, command=self._apply_actions
        ).pack(anchor="w")
        self.var_headshot = tk.BooleanVar(
            value=bool(self.ctrl.cfg.get("AIM_HEADSHOT_MODE", True))
        )
        ctk.CTkCheckBox(
            frm,
            text="Headshot mode",
            variable=self.var_headshot,
            command=self._apply_actions,
        ).pack(anchor="w")
        self.aim_range_s, _ = add_slider(
            "Aim range", 1, 1000, self.ctrl.cfg.get("AIM_ASSIST_RANGE", 23), step=1
        )
        self.aim_damp_s, _ = add_slider(
            "Vertical damp",
            0.0,
            1.0,
            self.ctrl.cfg.get("AIM_VERTICAL_DAMPING_FACTOR", 0.15),
        )
        self.aim_delay_s, _ = add_slider(
            "Aim delay (s)", 0.0, 1.0, self.ctrl.cfg.get("AIM_ASSIST_DELAY", 0.08)
        )
        self.aim_head_s, _ = add_slider(
            "Head offset (%)",
            0.0,
            100.0,
            self.ctrl.cfg.get("HEADSHOT_OFFSET_PERCENT", 18),
            step=1,
        )
        self.deadzone_s, _ = add_slider(
            "Deadzone", 0.0, 20.0, self.ctrl.cfg.get("DEADZONE", 2), step=0.5
        )
        # Option for aim mode
        rowm = ctk.CTkFrame(frm)
        rowm.pack(fill="x", pady=6)
        ctk.CTkLabel(rowm, text="Aim mode").pack(side="left", padx=6)
        self.aim_mode = ctk.CTkOptionMenu(
            rowm, values=["Hybrid", "Tracking", "Acquiring"]
        )
        self.aim_mode.set(self.ctrl.cfg.get("AIM_MODE", "Hybrid"))
        self.aim_mode.pack(side="left", padx=6)
        # Mouse button mapping
        rowb = ctk.CTkFrame(frm)
        rowb.pack(fill="x", pady=6)
        self.m1_btn = ctk.CTkOptionMenu(
            rowb, values=["left", "right", "middle", "mouse4", "mouse5"]
        )
        self.m1_btn.set(self.ctrl.cfg.get("MOUSE_1_BUTTON", "right"))
        self.m1_mode = ctk.CTkOptionMenu(rowb, values=["toggle", "hold"])
        self.m1_mode.set(self.ctrl.cfg.get("MOUSE_1_MODE", "toggle"))
        self.m2_btn = ctk.CTkOptionMenu(
            rowb, values=["left", "right", "middle", "mouse4", "mouse5"]
        )
        self.m2_btn.set(self.ctrl.cfg.get("MOUSE_2_BUTTON", "left"))
        self.m2_mode = ctk.CTkOptionMenu(rowb, values=["toggle", "hold"])
        self.m2_mode.set(self.ctrl.cfg.get("MOUSE_2_MODE", "hold"))
        ctk.CTkLabel(rowb, text="Mouse1").pack(side="left", padx=6)
        self.m1_btn.pack(side="left")
        self.m1_mode.pack(side="left", padx=6)
        ctk.CTkLabel(rowb, text="Mouse2").pack(side="left", padx=6)
        self.m2_btn.pack(side="left")
        self.m2_mode.pack(side="left", padx=6)

        # Advanced windmouse and locks as sliders/entries
        self.wind_g_s, _ = add_slider(
            "WindMouse G", 0.0, 20.0, self.ctrl.cfg.get("WINDMOUSE_G", 7.0)
        )
        self.wind_m_s, _ = add_slider(
            "WindMouse M", 0.0, 20.0, self.ctrl.cfg.get("WINDMOUSE_M", 12.0)
        )
        self.target_lock_s, _ = add_slider(
            "Target lock threshold",
            0.0,
            20.0,
            self.ctrl.cfg.get("TARGET_LOCK_THRESHOLD", 8.0),
        )
        self.aim_track_s, _ = add_slider(
            "Aim tracking speed",
            0.0,
            1.0,
            self.ctrl.cfg.get("AIM_TRACKING_SPEED", 0.04),
        )

        ctk.CTkButton(frm, text="Áp dụng Aim", command=self._apply_actions).pack(
            anchor="e", padx=6, pady=10
        )

    def _build_tab_detection(self, parent):
        # HSV + Morph bằng slider
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        self.var_hsv_enabled = tk.BooleanVar(
            value=bool(self.cfg.get("hsv", {}).get("enabled", True))
        )
        ctk.CTkCheckBox(
            frm,
            text="Bật Color Aimbot (HSV)",
            variable=self.var_hsv_enabled,
            command=self._toggle_hsv,
        ).pack(anchor="w")

        def add_slider(label, min_v, max_v, init_v, step=1):
            row = ctk.CTkFrame(frm)
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=label).pack(side="left", padx=6)
            value_label = ctk.CTkLabel(row, text=f"{float(init_v):.2f}")
            value_label.pack(side="right", padx=6)
            slider = ctk.CTkSlider(
                row,
                from_=min_v,
                to=max_v,
                number_of_steps=max(1, int((max_v - min_v) / step)),
            )
            slider.set(float(init_v))
            slider.pack(fill="x", padx=6)
            def on_change(v):
                try:
                    value_label.configure(text=f"{float(v):.2f}")
                except Exception:
                    pass
            slider.configure(command=on_change)
            return slider

        hsv_cfg = self.cfg.get("hsv", {})
        lower = hsv_cfg.get("lower", [20, 100, 100])
        upper = hsv_cfg.get("upper", [35, 255, 255])
        self.h_l_s = add_slider("H Lower", 0, 179, lower[0], step=1)
        self.s_l_s = add_slider("S Lower", 0, 255, lower[1], step=1)
        self.v_l_s = add_slider("V Lower", 0, 255, lower[2], step=1)
        self.h_u_s = add_slider("H Upper", 0, 179, upper[0], step=1)
        self.s_u_s = add_slider("S Upper", 0, 255, upper[1], step=1)
        self.v_u_s = add_slider("V Upper", 0, 255, upper[2], step=1)

        self.morph_k_s = add_slider("Morph kernel", 1, 15, hsv_cfg.get("morph_kernel", 3), step=1)
        self.min_area_s = add_slider("Min area", 0, 10000, hsv_cfg.get("min_area", 150), step=10)
        self.merge_iou_s = add_slider("Merge IoU", 0.0, 1.0, hsv_cfg.get("merge_iou", 0.2), step=0.01)
        ctk.CTkButton(frm, text="Áp dụng HSV", command=self._apply_hsv).pack(anchor="e", padx=6, pady=6)
        # AI
        ai_cfg = self.cfg.get("ai", {})
        self.var_ai_enabled = tk.BooleanVar(value=bool(ai_cfg.get("enabled", False)))
        ctk.CTkCheckBox(
            frm,
            text="Bật AI Aimbot (ONNXRuntime)",
            variable=self.var_ai_enabled,
            command=self._toggle_ai,
        ).pack(anchor="w")
        self.ai_model = ctk.CTkEntry(frm, width=420)
        self.ai_model.insert(0, ai_cfg.get("model_path", ""))
        r1 = ctk.CTkFrame(frm)
        r1.pack(fill="x", pady=6)
        ctk.CTkLabel(r1, text="Model .onnx").pack(side="left", padx=6)
        self.ai_model.pack(side="left", padx=4)
        self.ai_conf = ctk.CTkEntry(frm, width=80)
        self.ai_conf.insert(0, str(ai_cfg.get("conf_thresh", 0.35)))
        self.ai_iou = ctk.CTkEntry(frm, width=80)
        self.ai_iou.insert(0, str(ai_cfg.get("iou_thresh", 0.45)))
        self.ai_inp = ctk.CTkEntry(frm, width=80)
        self.ai_inp.insert(0, str(ai_cfg.get("input_size", 640)))
        r2 = ctk.CTkFrame(frm)
        r2.pack(fill="x", pady=6)
        ctk.CTkLabel(r2, text="Conf").pack(side="left", padx=6)
        self.ai_conf.pack(side="left", padx=2)
        ctk.CTkLabel(r2, text="IoU").pack(side="left", padx=6)
        self.ai_iou.pack(side="left", padx=2)
        ctk.CTkLabel(r2, text="Input").pack(side="left", padx=6)
        self.ai_inp.pack(side="left", padx=2)
        ctk.CTkButton(frm, text="Áp dụng AI", command=self._apply_ai).pack(
            anchor="e", padx=6, pady=6
        )
        # Fusion/Tracking
        fus_cfg = self.cfg.get("fusion", {})
        ctk.CTkLabel(frm, text="Chế độ").pack(side="left", padx=6)
        self.opt_fusion = ctk.CTkOptionMenu(frm, values=["AND", "OR", "Priority"])
        self.opt_fusion.set(fus_cfg.get("mode", "Priority"))
        self.opt_fusion.pack(side="left", padx=6)
        self.fus_iou = ctk.CTkEntry(frm, width=80)
        self.fus_iou.insert(0, str(fus_cfg.get("fusion_iou_thr", 0.3)))
        self.nms_iou = ctk.CTkEntry(frm, width=80)
        self.nms_iou.insert(0, str(fus_cfg.get("nms_iou_thr", 0.45)))
        self.top_k = ctk.CTkEntry(frm, width=80)
        self.top_k.insert(0, str(fus_cfg.get("top_k", 30)))
        r3 = ctk.CTkFrame(frm)
        r3.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(r3, text="Fusion IoU").pack(side="left", padx=6)
        self.fus_iou.pack(side="left", padx=2)
        ctk.CTkLabel(r3, text="NMS IoU").pack(side="left", padx=6)
        self.nms_iou.pack(side="left", padx=2)
        ctk.CTkLabel(r3, text="Top-K").pack(side="left", padx=6)
        self.top_k.pack(side="left", padx=2)
        trk_cfg = self.cfg.get("tracking", {})
        self.var_tracking = tk.BooleanVar(value=bool(trk_cfg.get("enabled", True)))
        ctk.CTkCheckBox(
            frm,
            text="Bật Tracking nhẹ",
            variable=self.var_tracking,
            command=self._toggle_tracking,
        ).pack(anchor="w", padx=10, pady=6)
        # Extra legacy morph params (saved to cfg)
        rowx = ctk.CTkFrame(frm)
        rowx.pack(fill="x", padx=10, pady=6)
        self.dil_iter = ctk.CTkEntry(rowx, width=80)
        self.dil_iter.insert(0, str(self.ctrl.cfg.get("DILATE_ITERATIONS", 2)))
        self.dil_w = ctk.CTkEntry(rowx, width=80)
        self.dil_w.insert(0, str(self.ctrl.cfg.get("DILATE_KERNEL_WIDTH", 3)))
        self.dil_h = ctk.CTkEntry(rowx, width=80)
        self.dil_h.insert(0, str(self.ctrl.cfg.get("DILATE_KERNEL_HEIGHT", 3)))
        ctk.CTkLabel(rowx, text="Dilate iters/W/H").pack(side="left", padx=6)
        self.dil_iter.pack(side="left", padx=2)
        self.dil_w.pack(side="left", padx=2)
        self.dil_h.pack(side="left", padx=2)
        rowy = ctk.CTkFrame(frm)
        rowy.pack(fill="x", padx=10, pady=6)
        self.er_iter = ctk.CTkEntry(rowy, width=80)
        self.er_iter.insert(0, str(self.ctrl.cfg.get("ERODE_ITERATIONS", 1)))
        self.er_w = ctk.CTkEntry(rowy, width=80)
        self.er_w.insert(0, str(self.ctrl.cfg.get("ERODE_KERNEL_WIDTH", 2)))
        self.er_h = ctk.CTkEntry(rowy, width=80)
        self.er_h.insert(0, str(self.ctrl.cfg.get("ERODE_KERNEL_HEIGHT", 2)))
        ctk.CTkLabel(rowy, text="Erode iters/W/H").pack(side="left", padx=6)
        self.er_iter.pack(side="left", padx=2)
        self.er_w.pack(side="left", padx=2)
        self.er_h.pack(side="left", padx=2)
        ctk.CTkButton(frm, text="Áp dụng Detection", command=self._apply_fusion).pack(
            anchor="e", padx=10, pady=6
        )

    def _build_tab_trigger(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        act = self.cfg.get("actions", {})
        self.var_trg = tk.BooleanVar(value=bool(act.get("trigger_enabled", False)))
        ctk.CTkCheckBox(
            frm, text="Bật Trigger", variable=self.var_trg, command=self._apply_actions
        ).pack(anchor="w")

        def add_slider(label, min_v, max_v, init_v, step=1):
            row = ctk.CTkFrame(frm)
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=label).pack(side="left", padx=6)
            value_label = ctk.CTkLabel(row, text=f"{float(init_v):.2f}")
            value_label.pack(side="right", padx=6)
            slider = ctk.CTkSlider(
                row,
                from_=min_v,
                to=max_v,
                number_of_steps=max(1, int((max_v - min_v) / step)),
            )
            slider.set(float(init_v))
            slider.pack(fill="x", padx=6)
            def on_change(v):
                try:
                    value_label.configure(text=f"{float(v):.2f}")
                except Exception:
                    pass
            slider.configure(command=on_change)
            return slider

        self.tdelay_s = add_slider("Delay (ms)", 0, 300, act.get("trigger_delay_ms", 10), step=1)
        self.tcd_s = add_slider("Cooldown (s)", 0.0, 1.0, act.get("trigger_cooldown", 0.15), step=0.01)
        # Advanced trigger
        self.tr_mode = ctk.CTkOptionMenu(frm, values=["instant", "burst", "adaptive"])
        self.tr_mode.set(self.ctrl.cfg.get("TRIGGER_MODE", "instant"))
        row2 = ctk.CTkFrame(frm)
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="Mode").pack(side="left", padx=6)
        self.tr_mode.pack(side="left", padx=2)
        self.tr_burst_cnt_s = add_slider("Burst count", 1, 10, self.ctrl.cfg.get("TRIGGER_BURST_COUNT", 3), step=1)
        self.tr_burst_delay_s = add_slider("Burst delay (s)", 0.0, 0.5, self.ctrl.cfg.get("TRIGGER_BURST_DELAY", 0.05), step=0.005)
        # Trigger button mapping (v3 style)
        btn_row = ctk.CTkFrame(frm)
        btn_row.pack(fill="x", pady=6)
        ctk.CTkLabel(btn_row, text="Trigger button").pack(side="left", padx=6)
        self.tb_button = ctk.CTkOptionMenu(
            btn_row, values=["left", "right", "middle", "mouse4", "mouse5"]
        )
        default_tb = self.ctrl.cfg.get("selected_tb_btn", None)
        # Map int 0..4 to names if present
        if isinstance(default_tb, int):
            name_map = ["left", "right", "middle", "mouse4", "mouse5"]
            if 0 <= default_tb < len(name_map):
                self.tb_button.set(name_map[default_tb])
            else:
                self.tb_button.set("mouse4")
        elif isinstance(default_tb, str) and default_tb:
            self.tb_button.set(default_tb)
        else:
            self.tb_button.set("mouse4")
        self.tb_button.pack(side="left", padx=6)
        ctk.CTkButton(frm, text="Áp dụng Trigger", command=self._apply_trigger).pack(
            anchor="e", padx=6, pady=6
        )

    def _build_tab_advance(self, parent):
        self._build_legacy_tab(parent)

    def _build_tab_setting(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        log = self.cfg.get("logging", {})
        row2 = ctk.CTkFrame(frm)
        row2.pack(fill="x", pady=6)
        self.log_enabled = tk.BooleanVar(value=bool(log.get("enabled", True)))
        ctk.CTkCheckBox(
            row2,
            text="Bật CSV metrics",
            variable=self.log_enabled,
            command=self._apply_logging,
        ).pack(side="left", padx=6)
        self.log_every = ctk.CTkEntry(row2, width=120)
        self.log_every.insert(0, str(log.get("log_every_n_frames", 20)))
        self.log_every.pack(side="left", padx=6)
        # General switches from legacy
        row3 = ctk.CTkFrame(frm)
        row3.pack(fill="x", pady=6)
        self.fps_limit = ctk.CTkEntry(row3, width=120)
        self.fps_limit.insert(0, str(self.ctrl.cfg.get("FPS_LIMIT", 240)))
        ctk.CTkLabel(row3, text="FPS limit").pack(side="left", padx=6)
        self.fps_limit.pack(side="left", padx=6)
        self.var_debug_wnd = tk.BooleanVar(
            value=bool(self.ctrl.cfg.get("DEBUG_WINDOW_VISIBLE", True))
        )
        self.var_hud = tk.BooleanVar(
            value=bool(self.ctrl.cfg.get("HUD_SHOW_AIM_STATUS", True))
        )
        ctk.CTkCheckBox(
            frm,
            text="Debug window visible",
            variable=self.var_debug_wnd,
            command=self._apply_setting,
        ).pack(anchor="w", padx=10)
        ctk.CTkCheckBox(
            frm,
            text="HUD show aim status",
            variable=self.var_hud,
            command=self._apply_setting,
        ).pack(anchor="w", padx=10)
        ctk.CTkButton(frm, text="Lưu cấu hình", command=self._save_cfg).pack(
            anchor="e", padx=10, pady=10
        )

    def _build_tab_detection(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        self.var_hsv_enabled = tk.BooleanVar(
            value=bool(self.cfg.get("hsv", {}).get("enabled", True))
        )
        ctk.CTkCheckBox(
            frm,
            text="Bật Color Aimbot (HSV)",
            variable=self.var_hsv_enabled,
            command=self._toggle_hsv,
        ).pack(anchor="w")
        # Lower/Upper HSV
        hsv_cfg = self.cfg.get("hsv", {})
        lower = hsv_cfg.get("lower", [20, 100, 100])
        upper = hsv_cfg.get("upper", [35, 255, 255])
        self.h_l = ctk.CTkEntry(frm, width=60)
        self.h_l.insert(0, str(lower[0]))
        self.s_l = ctk.CTkEntry(frm, width=60)
        self.s_l.insert(0, str(lower[1]))
        self.v_l = ctk.CTkEntry(frm, width=60)
        self.v_l.insert(0, str(lower[2]))
        self.h_u = ctk.CTkEntry(frm, width=60)
        self.h_u.insert(0, str(upper[0]))
        self.s_u = ctk.CTkEntry(frm, width=60)
        self.s_u.insert(0, str(upper[1]))
        self.v_u = ctk.CTkEntry(frm, width=60)
        self.v_u.insert(0, str(upper[2]))
        row1 = ctk.CTkFrame(frm)
        row1.pack(fill="x", pady=6)
        ctk.CTkLabel(row1, text="Lower [H,S,V]").pack(side="left", padx=6)
        self.h_l.pack(side="left", padx=2)
        self.s_l.pack(side="left", padx=2)
        self.v_l.pack(side="left", padx=2)
        row2 = ctk.CTkFrame(frm)
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="Upper [H,S,V]").pack(side="left", padx=6)
        self.h_u.pack(side="left", padx=2)
        self.s_u.pack(side="left", padx=2)
        self.v_u.pack(side="left", padx=2)
        # Morph/area/merge
        self.morph_k = ctk.CTkEntry(frm, width=60)
        self.morph_k.insert(0, str(hsv_cfg.get("morph_kernel", 3)))
        self.min_area = ctk.CTkEntry(frm, width=80)
        self.min_area.insert(0, str(hsv_cfg.get("min_area", 150)))
        self.merge_iou = ctk.CTkEntry(frm, width=80)
        self.merge_iou.insert(0, str(hsv_cfg.get("merge_iou", 0.2)))
        row3 = ctk.CTkFrame(frm)
        row3.pack(fill="x", pady=6)
        ctk.CTkLabel(row3, text="Morph kernel").pack(side="left", padx=6)
        self.morph_k.pack(side="left", padx=2)
        ctk.CTkLabel(row3, text="Min area").pack(side="left", padx=6)
        self.min_area.pack(side="left", padx=2)
        ctk.CTkLabel(row3, text="Merge IoU").pack(side="left", padx=6)
        self.merge_iou.pack(side="left", padx=2)
        ctk.CTkButton(frm, text="Áp dụng HSV", command=self._apply_hsv).pack(
            anchor="e", padx=6, pady=6
        )

        ai_cfg = self.cfg.get("ai", {})
        self.var_ai_enabled = tk.BooleanVar(value=bool(ai_cfg.get("enabled", False)))
        ctk.CTkCheckBox(
            frm,
            text="Bật AI Aimbot (ONNXRuntime)",
            variable=self.var_ai_enabled,
            command=self._toggle_ai,
        ).pack(anchor="w")
        self.ai_model = ctk.CTkEntry(frm, width=420)
        self.ai_model.insert(0, ai_cfg.get("model_path", ""))
        row1 = ctk.CTkFrame(frm)
        row1.pack(fill="x", pady=6)
        ctk.CTkLabel(row1, text="Model .onnx").pack(side="left", padx=6)
        self.ai_model.pack(side="left", padx=4)
        self.ai_conf = ctk.CTkEntry(frm, width=80)
        self.ai_conf.insert(0, str(ai_cfg.get("conf_thresh", 0.35)))
        self.ai_iou = ctk.CTkEntry(frm, width=80)
        self.ai_iou.insert(0, str(ai_cfg.get("iou_thresh", 0.45)))
        self.ai_inp = ctk.CTkEntry(frm, width=80)
        self.ai_inp.insert(0, str(ai_cfg.get("input_size", 640)))
        row2 = ctk.CTkFrame(frm)
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="Conf").pack(side="left", padx=6)
        self.ai_conf.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="IoU").pack(side="left", padx=6)
        self.ai_iou.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="Input").pack(side="left", padx=6)
        self.ai_inp.pack(side="left", padx=2)
        ctk.CTkButton(frm, text="Áp dụng AI", command=self._apply_ai).pack(
            anchor="e", padx=6, pady=6
        )

        fus_cfg = self.cfg.get("fusion", {})
        ctk.CTkLabel(frm, text="Chế độ").pack(side="left", padx=6)
        self.opt_fusion = ctk.CTkOptionMenu(frm, values=["AND", "OR", "Priority"])
        self.opt_fusion.set(fus_cfg.get("mode", "Priority"))
        self.opt_fusion.pack(side="left", padx=6)
        self.fus_iou = ctk.CTkEntry(frm, width=80)
        self.fus_iou.insert(0, str(fus_cfg.get("fusion_iou_thr", 0.3)))
        self.nms_iou = ctk.CTkEntry(frm, width=80)
        self.nms_iou.insert(0, str(fus_cfg.get("nms_iou_thr", 0.45)))
        self.top_k = ctk.CTkEntry(frm, width=80)
        self.top_k.insert(0, str(fus_cfg.get("top_k", 30)))
        row = ctk.CTkFrame(frm)
        row.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(row, text="Fusion IoU").pack(side="left", padx=6)
        self.fus_iou.pack(side="left", padx=2)
        ctk.CTkLabel(row, text="NMS IoU").pack(side="left", padx=6)
        self.nms_iou.pack(side="left", padx=2)
        ctk.CTkLabel(row, text="Top-K").pack(side="left", padx=6)
        self.top_k.pack(side="left", padx=2)
        trk_cfg = self.cfg.get("tracking", {})
        self.var_tracking = tk.BooleanVar(value=bool(trk_cfg.get("enabled", True)))
        ctk.CTkCheckBox(
            frm,
            text="Bật Tracking nhẹ",
            variable=self.var_tracking,
            command=self._toggle_tracking,
        ).pack(anchor="w", padx=10, pady=6)
        ctk.CTkButton(frm, text="Áp dụng Detection", command=self._apply_fusion).pack(
            anchor="e", padx=10, pady=6
        )

    def _build_actions_tab(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        act = self.cfg.get("actions", {})
        self.var_aim = tk.BooleanVar(value=bool(act.get("aim_enabled", False)))
        self.var_trg = tk.BooleanVar(value=bool(act.get("trigger_enabled", False)))
        ctk.CTkCheckBox(
            frm, text="Bật Aim", variable=self.var_aim, command=self._apply_actions
        ).pack(anchor="w")
        ctk.CTkCheckBox(
            frm, text="Bật Trigger", variable=self.var_trg, command=self._apply_actions
        ).pack(anchor="w")
        self.msens = ctk.CTkEntry(frm, width=80)
        self.msens.insert(0, str(act.get("mouse_sensitivity", 0.35)))
        self.msmooth = ctk.CTkEntry(frm, width=80)
        self.msmooth.insert(0, str(act.get("mouse_smoothness", 0.8)))
        row = ctk.CTkFrame(frm)
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(row, text="Sensitivity").pack(side="left", padx=6)
        self.msens.pack(side="left", padx=2)
        ctk.CTkLabel(row, text="Smoothness").pack(side="left", padx=6)
        self.msmooth.pack(side="left", padx=2)
        ctk.CTkLabel(row, text="Delay ms").pack(side="left", padx=6)
        ctk.CTkLabel(row, text="(dùng slider bên dưới)").pack(side="left", padx=6)
        ctk.CTkButton(
            frm, text="Áp dụng Aim/Trigger", command=self._apply_actions
        ).pack(anchor="e", padx=6, pady=6)

    # Actions
    def _start(self):
        ok = self.ctrl.start()
        self.status_var.set("Trạng thái: Đang chạy" if ok else "Trạng thái: Lỗi nguồn")

    def _stop(self):
        self.ctrl.stop()
        self.status_var.set("Trạng thái: Dừng")

    def _apply_source(self):
        # Nguồn đã được lược bỏ khỏi UI; giữ hàm để tránh lỗi gọi cũ
        pass

    def _toggle_hsv(self):
        self.ctrl.set_hsv_enabled(self.var_hsv_enabled.get())
        self.ctrl.save_to_disk()

    def _toggle_ai(self):
        self.ctrl.set_ai_enabled(self.var_ai_enabled.get())
        self.ctrl.save_to_disk()

    def _toggle_tracking(self):
        self.ctrl.set_tracking_enabled(self.var_tracking.get())
        self.ctrl.save_to_disk()

    def _apply_fusion(self):
        self.ctrl.set_fusion_mode(self.opt_fusion.get())
        # write additional params
        fus_iou = float(self.fus_iou.get())
        nms_iou = float(self.nms_iou.get())
        top_k = int(self.top_k.get())
        self.ctrl.cfg.setdefault("fusion", {})["fusion_iou_thr"] = fus_iou
        self.ctrl.cfg["fusion"]["nms_iou_thr"] = nms_iou
        self.ctrl.cfg["fusion"]["top_k"] = top_k
        self.ctrl.save_to_disk()

    def _apply_hsv(self):
        if hasattr(self, "h_l_s"):
            lower = [int(self.h_l_s.get()), int(self.s_l_s.get()), int(self.v_l_s.get())]
            upper = [int(self.h_u_s.get()), int(self.s_u_s.get()), int(self.v_u_s.get())]
            morph = int(self.morph_k_s.get())
            area = int(self.min_area_s.get())
            miou = float(self.merge_iou_s.get())
        else:
            lower = [int(self.h_l.get()), int(self.s_l.get()), int(self.v_l.get())]
            upper = [int(self.h_u.get()), int(self.s_u.get()), int(self.v_u.get())]
            morph = int(self.morph_k.get())
            area = int(self.min_area.get())
            miou = float(self.merge_iou.get())
        self.ctrl.set_hsv_params(lower, upper, morph, area, miou)
        self.ctrl.save_to_disk()

    def _apply_ai(self):
        enabled = self.var_ai_enabled.get()
        model = self.ai_model.get().strip()
        conf = float(self.ai_conf.get())
        iou = float(self.ai_iou.get())
        inp = int(self.ai_inp.get())
        self.ctrl.set_ai_params(enabled, model, conf, iou, inp)
        self.ctrl.save_to_disk()

    def _apply_actions(self):
        aim = self.var_aim.get()
        trg = self.var_trg.get() if hasattr(self, "var_trg") else False
        msens = (
            float(self.msens_s.get())
            if hasattr(self, "msens_s")
            else float(self.msens.get())
        )
        msmooth = (
            float(self.msmooth_s.get())
            if hasattr(self, "msmooth_s")
            else float(self.msmooth.get())
        )
        # Trigger from sliders if present
        if hasattr(self, "tdelay_s"):
            tdelay = float(self.tdelay_s.get())
        else:
            tdelay = float(self.tdelay.get()) if hasattr(self, "tdelay") else 10.0
        if hasattr(self, "tcd_s"):
            tcd = float(self.tcd_s.get())
        else:
            tcd = float(self.tcd.get()) if hasattr(self, "tcd") else 0.15
        self.ctrl.set_actions_params(aim, trg, msens, msmooth, tdelay, tcd)
        # persist extra aim
        try:
            self.ctrl.cfg["AIM_ASSIST_RANGE"] = (
                float(self.aim_range_s.get())
                if hasattr(self, "aim_range_s")
                else float(self.aim_range.get())
            )
            self.ctrl.cfg["AIM_VERTICAL_DAMPING_FACTOR"] = (
                float(self.aim_damp_s.get())
                if hasattr(self, "aim_damp_s")
                else float(self.aim_damp.get())
            )
            self.ctrl.cfg["AIM_ASSIST_DELAY"] = (
                float(self.aim_delay_s.get())
                if hasattr(self, "aim_delay_s")
                else float(self.aim_delay.get())
            )
            self.ctrl.cfg["HEADSHOT_OFFSET_PERCENT"] = (
                float(self.aim_head_s.get())
                if hasattr(self, "aim_head_s")
                else float(self.aim_head.get())
            )
            self.ctrl.cfg["AIM_HEADSHOT_MODE"] = bool(self.var_headshot.get())
            self.ctrl.cfg["DEADZONE"] = (
                float(self.deadzone_s.get())
                if hasattr(self, "deadzone_s")
                else float(self.deadzone.get())
            )
            self.ctrl.cfg["AIM_MODE"] = self.aim_mode.get()
            self.ctrl.cfg["WINDMOUSE_G"] = (
                float(self.wind_g_s.get())
                if hasattr(self, "wind_g_s")
                else float(self.wind_g.get())
            )
            self.ctrl.cfg["WINDMOUSE_M"] = (
                float(self.wind_m_s.get())
                if hasattr(self, "wind_m_s")
                else float(self.wind_m.get())
            )
            self.ctrl.cfg["TARGET_LOCK_THRESHOLD"] = (
                float(self.target_lock_s.get())
                if hasattr(self, "target_lock_s")
                else float(self.target_lock.get())
            )
            self.ctrl.cfg["AIM_TRACKING_SPEED"] = (
                float(self.aim_track_s.get())
                if hasattr(self, "aim_track_s")
                else float(self.aim_track.get())
            )
            self.ctrl.cfg["MOUSE_EASE_OUT"] = bool(self.mease.get())
            # Mouse buttons/modes
            self.ctrl.cfg["MOUSE_1_BUTTON"] = self.m1_btn.get()
            self.ctrl.cfg["MOUSE_1_MODE"] = self.m1_mode.get()
            self.ctrl.cfg["MOUSE_2_BUTTON"] = self.m2_btn.get()
            self.ctrl.cfg["MOUSE_2_MODE"] = self.m2_mode.get()
        except Exception:
            pass
        self.ctrl.save_to_disk()

    def _save_cfg(self):
        self.ctrl.save_to_disk()
        self.status_var.set("Đã lưu cấu hình")

    def _tick(self):
        try:
            frame = self.ctrl.get_latest_frame()
            if frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                side_w = self.preview.winfo_width() or 520
                side_h = self.preview.winfo_height() or 520
                scale = min(side_w / max(1, w), side_h / max(1, h))
                rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
                img = Image.fromarray(rgb)
                tkimg = ImageTk.PhotoImage(img)
                self.preview.image = tkimg
                self.preview.create_image(0, 0, image=tkimg, anchor="nw")
            dbg = None
            try:
                dbg = self.ctrl.get_latest_debug()
            except Exception:
                dbg = None
            if dbg is not None and hasattr(self, "preview_dbg"):
                drgb = cv2.cvtColor(dbg, cv2.COLOR_BGR2RGB)
                dh, dw = drgb.shape[:2]
                dsw = self.preview_dbg.winfo_width() or 520
                dsh = self.preview_dbg.winfo_height() or 520
                dscale = min(dsw / max(1, dw), dsh / max(1, dh))
                drgb = cv2.resize(drgb, (int(dw * dscale), int(dh * dscale)))
                dimg = Image.fromarray(drgb)
                dtkimg = ImageTk.PhotoImage(dimg)
                self.preview_dbg.image = dtkimg
                self.preview_dbg.create_image(0, 0, image=dtkimg, anchor="nw")
            m = self.ctrl.get_metrics()
            self.fps_var.set(f"FPS: {m.get('fps', 0.0):.1f}")
            self.lat_var.set(f"Độ trễ: {m.get('latency_ms', 0.0):.1f} ms")
        except Exception:
            pass
        self.after(100, self._tick)

    def _apply_trigger(self):
        # Write advanced trigger params into cfg
        try:
            self.ctrl.cfg["TRIGGER_MODE"] = self.tr_mode.get()
            # Prefer slider values if present
            if hasattr(self, "tr_burst_cnt_s"):
                self.ctrl.cfg["TRIGGER_BURST_COUNT"] = int(self.tr_burst_cnt_s.get())
            else:
                self.ctrl.cfg["TRIGGER_BURST_COUNT"] = int(self.tr_burst_cnt.get())
            if hasattr(self, "tr_burst_delay_s"):
                self.ctrl.cfg["TRIGGER_BURST_DELAY"] = float(self.tr_burst_delay_s.get())
            else:
                self.ctrl.cfg["TRIGGER_BURST_DELAY"] = float(self.tr_burst_delay.get())
            self.ctrl.cfg["SHOT_COOLDOWN"] = float(self.shot_cd.get())
            self.ctrl.cfg["TRIGGER_ADAPTIVE_DELAY"] = bool(self.tr_adapt.get())
            self.ctrl.cfg["TRIGGER_SIZE_FACTOR"] = float(self.tr_size.get())
            self.ctrl.cfg["TRIGGER_DISTANCE_FACTOR"] = float(self.tr_dist.get())
            self.ctrl.cfg["TRIGGER_MIN_COOLDOWN"] = float(self.tr_min_cd.get())
            self.ctrl.cfg["TRIGGER_RANDOM_DELAY"] = bool(self.tr_rand.get())
            self.ctrl.cfg["TRIGGER_RANDOM_MIN"] = int(self.tr_rand_min.get())
            self.ctrl.cfg["TRIGGER_RANDOM_MAX"] = int(self.tr_rand_max.get())
            self.ctrl.cfg["TRIGGER_SMOOTHING"] = bool(self.tr_smooth.get())
            self.ctrl.cfg["TRIGGER_SMOOTHING_FACTOR"] = float(self.tr_smooth_f.get())
            self.ctrl.cfg["TRIGGER_PREDICTION"] = bool(self.tr_pred.get())
            self.ctrl.cfg["TRIGGER_PREDICTION_TIME"] = float(self.tr_pred_t.get())
            self.ctrl.cfg["TRIGGER_ANTI_PATTERN"] = bool(self.tr_anti.get())
            self.ctrl.cfg["TRIGGER_ANTI_PATTERN_TIME"] = float(self.tr_anti_t.get())
            self.ctrl.cfg["TRIGGER_WEAPON_MODE"] = self.tr_weapon.get()
            self.ctrl.cfg["TRIGGER_TARGET_PRIORITY"] = self.tr_priority.get()
            self.ctrl.cfg["TRIGGER_TARGET_FILTER"] = bool(self.tr_filter.get())
            self.ctrl.cfg["TRIGGER_MIN_TARGET_SIZE"] = int(self.tr_min_size.get())
            self.ctrl.cfg["TRIGGER_MAX_TARGET_SIZE"] = int(self.tr_max_size.get())
            self.ctrl.cfg["TRIGGER_TARGET_CONFIDENCE"] = float(self.tr_conf.get())
            self.ctrl.cfg["TRIGGER_MOVEMENT_COMPENSATION"] = bool(self.tr_move.get())
            self.ctrl.cfg["TRIGGER_MOVEMENT_THRESHOLD"] = int(self.tr_move_th.get())
            self.ctrl.cfg["TRIGGER_MOVEMENT_FACTOR"] = float(self.tr_move_f.get())
            self.ctrl.cfg["TRIGGER_HEALTH_CHECK"] = bool(self.tr_health.get())
            self.ctrl.cfg["TRIGGER_HEALTH_THRESHOLD"] = float(self.tr_health_th.get())
            self.ctrl.cfg["TRIGGER_AMMO_CHECK"] = bool(self.tr_ammo.get())
            self.ctrl.cfg["TRIGGER_AMMO_THRESHOLD"] = int(self.tr_ammo_th.get())
            self.ctrl.cfg["TRIGGER_SOUND_DETECTION"] = bool(self.tr_sound.get())
            self.ctrl.cfg["TRIGGER_SOUND_THRESHOLD"] = float(self.tr_sound_th.get())
            self.ctrl.cfg["TRIGGER_VIBRATION_FEEDBACK"] = bool(self.tr_vibe.get())
            self.ctrl.cfg["TRIGGER_VIBRATION_INTENSITY"] = float(self.tr_vibe_i.get())
            self.ctrl.cfg["TRIGGER_DEBUG_MODE"] = bool(self.tr_debug.get())
            self.ctrl.cfg["TRIGGER_DEBUG_LEVEL"] = int(self.tr_debug_lvl.get())
            self.ctrl.cfg["TRIGGER_STATISTICS"] = bool(self.tr_stats.get())
            self.ctrl.cfg["TRIGGER_STATS_WINDOW"] = int(self.tr_stats_win.get())
            self.ctrl.cfg["TRIGGER_PERFORMANCE_MODE"] = bool(self.tr_perf.get())
            self.ctrl.cfg["TRIGGER_PERFORMANCE_THRESHOLD"] = float(
                self.tr_perf_th.get()
            )
            # save trigger button
            name = self.tb_button.get()
            name_map = ["left", "right", "middle", "mouse4", "mouse5"]
            try:
                idx = name_map.index(name)
                self.ctrl.cfg["selected_tb_btn"] = idx
            except Exception:
                self.ctrl.cfg["selected_tb_btn"] = name
        except Exception:
            pass
        # Also persist basic delay/cooldown via _apply_actions for consistency
        try:
            self._apply_actions()
        except Exception:
            pass
        self.ctrl.save_to_disk()

    def _apply_logging(self):
        log = self.ctrl.cfg.setdefault("logging", {})
        log["enabled"] = bool(self.log_enabled.get())
        try:
            log["log_every_n_frames"] = int(self.log_every.get())
        except Exception:
            pass
        self.ctrl.save_to_disk()

    def _apply_setting(self):
        try:
            self.ctrl.cfg["FPS_LIMIT"] = int(self.fps_limit.get())
            self.ctrl.cfg["DEBUG_WINDOW_VISIBLE"] = bool(self.var_debug_wnd.get())
            self.ctrl.cfg["HUD_SHOW_AIM_STATUS"] = bool(self.var_hud.get())
        except Exception:
            pass
        self.ctrl.save_to_disk()

    def _on_close(self):
        try:
            self.ctrl.save_to_disk()
        except Exception:
            pass
        try:
            self.ctrl.stop()
        except Exception:
            pass
        self.destroy()

    # ===== Legacy Full Config (v2/v3/v4) =====
    def _build_legacy_tab(self, parent):
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)
        ctk.CTkLabel(
            frm, text="Cấu hình đầy đủ từ các phiên bản trước (v2/v3/v4)"
        ).pack(anchor="w", padx=6, pady=6)

        # Define keys from v2 SharedConfig + v3 + v4 (scalar/basic JSON fields only)
        self.legacy_entries = {}

        legacy_keys = [
            # v2 core & mouse/aim
            "FPS_LIMIT",
            "HUD_SHOW_AIM_STATUS",
            "AIM_ASSIST_ENABLED",
            "TRIGGERBOT_ENABLED",
            "DEBUG_WINDOW_VISIBLE",
            "AIM_MODE",
            "WINDMOUSE_G",
            "WINDMOUSE_W",
            "WINDMOUSE_M",
            "WINDMOUSE_D",
            "TARGET_LOCK_THRESHOLD",
            "AIM_ACQUIRING_SPEED",
            "AIM_TRACKING_SPEED",
            "AIM_JITTER",
            "MOUSE_SENSITIVITY",
            "AIM_ASSIST_RANGE",
            "AIM_VERTICAL_DAMPING_FACTOR",
            "AIM_ASSIST_DELAY",
            "AIM_HEADSHOT_MODE",
            "HEADSHOT_OFFSET_PERCENT",
            "DEADZONE",
            "MOUSE_1_BUTTON",
            "MOUSE_2_BUTTON",
            "MOUSE_1_MODE",
            "MOUSE_2_MODE",
            "MOUSE_STEP_DELAY_MS",
            "MOUSE_EASE_OUT",
            "MOUSE_SMOOTHNESS",
            # v2 detection (HSV morph)
            "MIN_CONTOUR_AREA",
            "DILATE_ITERATIONS",
            "DILATE_KERNEL_WIDTH",
            "DILATE_KERNEL_HEIGHT",
            "ERODE_ITERATIONS",
            "ERODE_KERNEL_WIDTH",
            "ERODE_KERNEL_HEIGHT",
            # v2 trigger basic & advanced
            "SHOT_DURATION",
            "SHOT_COOLDOWN",
            "TRIGGERBOT_DELAY_MS",
            "TRIGGER_MODE",
            "TRIGGER_BURST_MODE",
            "TRIGGER_BURST_COUNT",
            "TRIGGER_BURST_DELAY",
            "TRIGGER_ADAPTIVE_DELAY",
            "TRIGGER_SIZE_FACTOR",
            "TRIGGER_DISTANCE_FACTOR",
            "TRIGGER_MAX_DELAY_MS",
            "TRIGGER_MIN_COOLDOWN",
            "TRIGGER_RANDOM_DELAY",
            "TRIGGER_RANDOM_MIN",
            "TRIGGER_RANDOM_MAX",
            "TRIGGER_SMOOTHING",
            "TRIGGER_SMOOTHING_FACTOR",
            "TRIGGER_PREDICTION",
            "TRIGGER_PREDICTION_TIME",
            "TRIGGER_ANTI_PATTERN",
            "TRIGGER_ANTI_PATTERN_TIME",
            "TRIGGER_WEAPON_MODE",
            "TRIGGER_ACCURACY_MODE",
            "TRIGGER_TARGET_PRIORITY",
            "TRIGGER_TARGET_FILTER",
            "TRIGGER_MIN_TARGET_SIZE",
            "TRIGGER_MAX_TARGET_SIZE",
            "TRIGGER_TARGET_CONFIDENCE",
            "TRIGGER_MOVEMENT_COMPENSATION",
            "TRIGGER_MOVEMENT_THRESHOLD",
            "TRIGGER_MOVEMENT_FACTOR",
            "TRIGGER_HEALTH_CHECK",
            "TRIGGER_HEALTH_THRESHOLD",
            "TRIGGER_AMMO_CHECK",
            "TRIGGER_AMMO_THRESHOLD",
            "TRIGGER_SOUND_DETECTION",
            "TRIGGER_SOUND_THRESHOLD",
            "TRIGGER_VIBRATION_FEEDBACK",
            "TRIGGER_VIBRATION_INTENSITY",
            "TRIGGER_DEBUG_MODE",
            "TRIGGER_DEBUG_LEVEL",
            "TRIGGER_STATISTICS",
            "TRIGGER_STATS_WINDOW",
            "TRIGGER_PERFORMANCE_MODE",
            "TRIGGER_PERFORMANCE_THRESHOLD",
            # v2 udp/logging
            "UDP_HOST",
            "UDP_PORT",
            "UDP_RCVBUF_MB",
            "UDP_TURBOJPEG",
            # v3 outsider (selected)
            "enableaim",
            "enabletb",
            "offsetX",
            "offsetY",
            "normal_x_speed",
            "normal_y_speed",
            "normalsmooth",
            "normalsmoothfov",
            "tbfovsize",
            "tbdelay",
            "in_game_sens",
            "mouse_dpi",
            "mode",
            "selected_mouse_button",
            "selected_tb_btn",
            # v4 basic
            "screenShotHeight",
            "screenShotWidth",
            "useMask",
            "maskSide",
            "maskWidth",
            "maskHeight",
            "aaMovementAmp",
            "confidence",
            "aaQuitKey",
            "headshot_mode",
            "cpsDisplay",
            "visuals",
            "centerOfScreen",
            "onnxChoice",
        ]

        # Exclude keys already exposed in dedicated tabs (Aim/Detection/Trigger/Setting)
        covered_keys = set(
            [
                # Detection
                "MIN_CONTOUR_AREA",
                "DILATE_ITERATIONS",
                "DILATE_KERNEL_WIDTH",
                "DILATE_KERNEL_HEIGHT",
                "ERODE_ITERATIONS",
                "ERODE_KERNEL_WIDTH",
                "ERODE_KERNEL_HEIGHT",
                "SANDWICH_CHECK_HEIGHT",
                "SANDWICH_CHECK_SCAN_WIDTH",
                # Aim
                "MOUSE_SENSITIVITY",
                "MOUSE_SMOOTHNESS",
                "MOUSE_EASE_OUT",
                "AIM_ASSIST_RANGE",
                "AIM_VERTICAL_DAMPING_FACTOR",
                "AIM_ASSIST_DELAY",
                "AIM_HEADSHOT_MODE",
                "HEADSHOT_OFFSET_PERCENT",
                "DEADZONE",
                "AIM_MODE",
                "WINDMOUSE_G",
                "WINDMOUSE_M",
                "TARGET_LOCK_THRESHOLD",
                "AIM_TRACKING_SPEED",
                "MOUSE_1_BUTTON",
                "MOUSE_2_BUTTON",
                "MOUSE_1_MODE",
                "MOUSE_2_MODE",
                # Trigger
                "TRIGGER_MODE",
                "TRIGGER_BURST_COUNT",
                "TRIGGER_BURST_DELAY",
                "TRIGGERBOT_DELAY_MS",
                "SHOT_COOLDOWN",
                # Setting
                "FPS_LIMIT",
                "HUD_SHOW_AIM_STATUS",
                "DEBUG_WINDOW_VISIBLE",
            ]
        )

        # Ẩn các khóa đã có UI riêng; chỉ hiển thị những khóa còn lại
        grid = ctk.CTkFrame(frm)
        grid.pack(fill="both", expand=True)
        cols = 2
        filtered = [k for k in legacy_keys if k not in covered_keys]
        for idx, key in enumerate(filtered):
            col = idx % cols
            row = idx // cols
            cell = ctk.CTkFrame(grid)
            cell.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
            val = self.ctrl.cfg.get(key, "")
            ent = ctk.CTkEntry(cell, width=180)
            ent.insert(0, str(val))
            ctk.CTkLabel(cell, text=key).pack(side="left", padx=4)
            ent.pack(side="right", padx=4)
            self.legacy_entries[key] = ent

        btns = ctk.CTkFrame(frm)
        btns.pack(fill="x", pady=8)
        ctk.CTkButton(btns, text="Áp dụng Legacy", command=self._apply_legacy).pack(
            side="right", padx=6
        )

    def _apply_legacy(self):
        import json as _json

        for key, ent in self.legacy_entries.items():
            txt = ent.get().strip()
            if txt == "":
                continue
            val: object = txt
            low = txt.lower()
            try:
                if low in ("true", "false"):
                    val = low == "true"
                elif txt.startswith("{") or txt.startswith("["):
                    val = _json.loads(txt)
                elif "." in txt:
                    val = float(txt)
                else:
                    val = int(txt)
            except Exception:
                pass
            self.ctrl.cfg[key] = val
        self.ctrl.save_to_disk()


def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "configs", "default.json")
    cfg_path = os.path.abspath(cfg_path)
    app = App(cfg_path)
    app.mainloop()


if __name__ == "__main__":
    main()
