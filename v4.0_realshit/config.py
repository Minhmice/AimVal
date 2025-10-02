class Config:
    def __init__(self):
        # --- General Settings ---

        self.enableaim = True
        self.enabletb = False
        self.offsetX = -2
        self.offsetY = 3

        # color removed (fixed to purple in detection)

        # --- Debug / Viewer ---
        self.debug_show = False  # gate cv2.imshow windows for smoothness
        self.viewer_port = 8080
        self.viewer_rcvbuf_mb = 256
        self.viewer_scale = 1.0
        self.viewer_max_display_fps = 240.0
        self.viewer_metrics_hz = 120.0

        # --- Mouse / MAKCU ---
        self.selected_mouse_button = 1
        self.selected_tb_btn = 1
        self.selected_2_tb = 2
        self.in_game_sens = 0.189
        self.mouse_dpi = 1600
        # --- Aimbot Mode ---
        self.mode = "Normal"

        self.fovsize = 100
        self.tbfovsize = 5
        self.tbdelay = 0.5
        # --- Normal Aim ---
        self.normal_x_speed = 3
        self.normal_y_speed = 3

        self.normalsmooth = 30
        self.normalsmoothfov = 30

        # Feature toggles for new unified modules
        self.use_new_aim = False
        self.use_new_trigger = False
        self.use_new_anti_recoil = False

        # --- Detect module (unified) ---
        self.use_new_detect = False
        self.runtime = {
            "active_provider": "auto",
            "providers_order": ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
            "model_path": "",
            "input_name": "",
            "output_name": "",
            "image_size": 640,
            "normalize": True,
            "mean": [0.0, 0.0, 0.0],
            "std": [255.0, 255.0, 255.0],
            "channels": "RGB",
            "layout": "NCHW",
            "warmup_runs": 1,
            "num_threads": {"intra_op": 0, "inter_op": 0},
            "graph_optimization": "all",
            "execution_mode": "parallel",
            "inference_fps_cap": 0,
        }
        self.detection = {
            "source": "color",  # ai | color
            "fov": {"mode": "center", "size": 640, "roi_padding_px": 0},
            "confidence_threshold": 0.25,
            "classes": {
                "target": "Best Confidence",
                "allow": [],
                "deny": [],
                "class_id_map": {},
                "class_names": [],
            },
            "postprocess": {
                "box_format": "cxcywh",
                "output_layout": "1x(4+C)xN",
                "clip_to_fov": False,
                "min_box_area": 0.0,
                "max_box_area": 1e12,
            },
            "nms": {"enabled": True, "iou_threshold": 0.5, "max_detections": 200, "class_agnostic": False},
            "target_selection": {
                "strategy": "nearest_to_center",
                "distance_metric": "euclidean",
                "nearest_k": 1,
                "max_targets_considered": 200,
                "use_kd_tree": False,
                "sticky_aim": {"enabled": False, "threshold_px": 30, "max_lost_frames": 10},
            },
            "save_frames": {"enabled": False, "cooldown_ms": 1000, "images_dir": "captures", "labels_dir": "captures"},
        }
        self.debug = {
            "log_level": "info",
            "overlay": {"draw_fov": True, "draw_boxes": True, "draw_target": True, "draw_mask": False},
            "timings": {"enabled": False, "print_every_ms": 300},
        }


        # --- Aim Module (new unified) ---
        self.aim = {
            "alignment": "Center",  # Top | Center | Bottom
            "offset_percent": {"use_x": False, "use_y": True, "x": 50.0, "y": 65.0},
            "offset_px": {"x": 0, "y": 0},
            "movement": {
                "mouse_sensitivity_scale": 1.0,
                "deadzone_px": {"x": 0, "y": 0},
                "max_step_px": {"x": 30, "y": 30},
                "jitter_px": {"x": 0, "y": 0},
                "aspect_ratio_correction": True,
                "lock_on_screen": True,
            },
        }

        # --- Trigger Module (new unified) ---
        self.trigger = {
            "enabled": False,
            "mode": "single",  # single | spray
            "require_aim_pressed": True,
            "cursor_check": True,
            "trigger_delay_ms": 120,
            "click_down_up_delay_ms": 20,
            "safety": {"min_interval_ms": 50, "max_rate_per_s": 15},
            "spray": {"release_if_cursor_outside_box": True},
        }

        # --- Anti-recoil Module (new unified) ---
        self.anti_recoil = {
            "enabled": True,
            "hold_time_ms": 150,
            "fire_rate_ms": 95,
            "x_recoil": 0,
            "y_recoil": 2,
            "random_jitter_px": {"x": 0, "y": 1},
            "scale_with_ads": 1.0,
            "only_when_triggering": True,
        }


config = Config()
