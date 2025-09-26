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
        self.in_game_sens = 0.235
        self.mouse_dpi = 800
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


config = Config()
