class Config:
    def __init__(self):
        # --- General Settings ---

        self.enableaim = True
        self.enabletb = False
        self.offsetX = -2
        self.offsetY = 3

        # --- Debug / Viewer ---
        self.debug_show = False  # gate cv2.imshow windows for smoothness
        self.viewer_port = 8080
        self.viewer_rcvbuf_mb = 256
        self.viewer_scale = 1.0
        self.viewer_max_display_fps = 240.0
        self.viewer_metrics_hz = 120.0

        # --- Mouse / MAKCU ---
        # Aimbot buttons (2 buttons)
        self.aim_button_1 = 1  # Button đầu tiên cho aim
        self.aim_button_2 = 2  # Button thứ hai cho aim
        # Triggerbot button (1 button)
        self.trigger_button = 1  # Button cho triggerbot
        self.in_game_sens = 0.235
        self.mouse_dpi = 800
        # --- Aimbot Mode ---
        self.mode = "Normal"

        self.fovsize = 100
        self.tbfovsize = 5
        self.tbdelay = 0.5
        self.trigger_fire_rate_ms = 100  # Tốc độ bắn triggerbot (millisecond)
        # --- Normal Aim ---
        self.normal_x_speed = 3
        self.normal_y_speed = 3

        self.normalsmooth = 30
        self.normalsmoothfov = 30

        # --- Anti-Recoil Settings ---
        self.anti_recoil_enabled = False
        self.anti_recoil_key_1 = 3  # Side Mouse 4 (phím 1)
        self.anti_recoil_key_2 = 4  # Side Mouse 5 (phím 2)
        self.anti_recoil_x = 0
        self.anti_recoil_y = 0
        self.anti_recoil_fire_rate = 100
        self.anti_recoil_hold_time = 0
        self.anti_recoil_scale_ads = 1.0
        self.anti_recoil_smooth_segments = 2
        self.anti_recoil_smooth_scale = 0.25
        self.anti_recoil_jitter_x = 0
        self.anti_recoil_jitter_y = 0


config = Config()
