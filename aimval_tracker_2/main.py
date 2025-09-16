import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
import os
import time
import logging
import numpy as np
import threading

from config import SharedConfig
from core import TriggerbotCore
from logger import setup_logging
from udp_source import UdpFrameSource


class ControlPanelGUI(ttk.Window):
    """Desktop GUI to control the triggerbot using ttkbootstrap.

    - Provides tabs for Main, Aiming, Detection, Advanced settings
    - Binds widgets directly to SharedConfig so changes apply immediately
    - Spawns a worker thread to run the core frame loop when started
    """

    def __init__(self, config: SharedConfig):
        super().__init__(
            themename="cyborg",
            title="Warsaw CB v1.0 ~ @Elusive1337",
            resizable=(True, True),
        )
        try:
            self.iconbitmap("app_icon.ico")
        except Exception:
            # if icon is not found, do nothing and use the default icon
            pass

        self.config = config
        self.bot_instance = None
        self.bot_thread = None
        self.health_log_job = None
        self.widget_vars = {}
        self.geometry("550x950")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=X)
        self.start_button = ttk.Button(
            top_frame, text="Start", command=self.start_bot, bootstyle=SUCCESS
        )
        self.start_button.pack(side=LEFT, padx=(0, 5))
        self.stop_button = ttk.Button(
            top_frame,
            text="Stop",
            command=self.stop_bot,
            state=DISABLED,
            bootstyle=DANGER,
        )
        self.stop_button.pack(side=LEFT)
        self.debug_var = tk.BooleanVar(value=self.config.get("DEBUG_WINDOW_VISIBLE"))
        self.widget_vars["DEBUG_WINDOW_VISIBLE"] = self.debug_var
        debug_check = ttk.Checkbutton(
            top_frame,
            text="Show Debug",
            variable=self.debug_var,
            bootstyle="round-toggle",
            command=lambda: self.config.set(
                "DEBUG_WINDOW_VISIBLE", self.debug_var.get()
            ),
        )
        debug_check.pack(side=RIGHT)
        self.view_var = tk.BooleanVar(value=self.config.get("VIEW_SCREEN_VISIBLE"))
        self.widget_vars["VIEW_SCREEN_VISIBLE"] = self.view_var
        view_check = ttk.Checkbutton(
            top_frame,
            text="View Screen",
            variable=self.view_var,
            bootstyle="round-toggle",
            command=lambda: self.config.set(
                "VIEW_SCREEN_VISIBLE", self.view_var.get()
            ),
        )
        view_check.pack(side=RIGHT, padx=(0, 8))
        # Log toggle changes
        self.debug_var.trace_add(
            "write",
            lambda *args: logging.info(
                "UI: DEBUG_WINDOW_VISIBLE=%s", bool(self.debug_var.get())
            ),
        )
        self.view_var.trace_add(
            "write",
            lambda *args: logging.info(
                "UI: VIEW_SCREEN_VISIBLE=%s", bool(self.view_var.get())
            ),
        )

        notebook = ttk.Notebook(self, padding=10)
        notebook.pack(fill=BOTH, expand=YES)

        main_tab = ttk.Frame(notebook)
        notebook.add(main_tab, text=" Main ")
        aiming_tab = ttk.Frame(notebook)
        notebook.add(aiming_tab, text=" Aiming ")
        detection_tab = ttk.Frame(notebook)
        notebook.add(detection_tab, text=" Detection ")
        advanced_tab = ttk.Frame(notebook)
        notebook.add(advanced_tab, text=" Advanced ")

        self.populate_main_tab(main_tab)
        self.populate_aiming_tab(aiming_tab)
        self.populate_detection_tab(detection_tab)
        self.populate_advanced_tab(advanced_tab)
        self._update_gui_from_config()
        self._start_health_logger()

    def populate_main_tab(self, parent):
        """Build Main tab: config file actions, global toggles, FPS and FOV."""
        config_frame = ttk.LabelFrame(parent, text="Config Profile", padding=10)
        config_frame.pack(fill=X, pady=5, padx=5)
        self.config_entry_var = tk.StringVar(
            value=os.path.basename(self.config.current_filepath)
        )
        self.config_entry = ttk.Entry(config_frame, textvariable=self.config_entry_var)
        self.config_entry.pack(side=LEFT, expand=YES, fill=X, padx=(0, 5))
        ttk.Button(
            config_frame, text="Save", command=self._save_config_from_entry
        ).pack(side=LEFT, padx=(0, 5))
        ttk.Button(config_frame, text="Load", command=self._load_config_dialog).pack(
            side=LEFT
        )

        toggles_frame = ttk.LabelFrame(parent, text="Global Toggles", padding=10)
        toggles_frame.pack(fill=X, pady=5, padx=5)
        for key, text in {
            "AIM_ASSIST_ENABLED": "Enable Aim Assist",
            "TRIGGERBOT_ENABLED": "Enable Triggerbot",
        }.items():
            var = tk.BooleanVar(value=self.config.get(key))
            self.widget_vars[key] = var
            ttk.Checkbutton(
                toggles_frame,
                text=text,
                variable=var,
                bootstyle="round-toggle",
                command=lambda k=key, v=var: self.config.set(k, v.get()),
            ).pack(anchor=W, padx=5, pady=2)

        core_frame = ttk.LabelFrame(parent, text="Core Settings", padding=10)
        core_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(core_frame, "FPS_LIMIT", "FPS Limit", 100, 240)

        fov_frame = ttk.LabelFrame(
            parent, text="Capture FOV (Restart Required)", padding=10
        )
        fov_frame.pack(fill=X, pady=5, padx=5)
        self.fov_var = tk.StringVar(value=self.config.get("FOV_RESOLUTION"))
        self.widget_vars["FOV_RESOLUTION"] = self.fov_var
        fov_values = list(self.config.get("FOV_RESOLUTIONS_MAP").keys())
        fov_combo = ttk.Combobox(
            fov_frame, textvariable=self.fov_var, values=fov_values, state="readonly"
        )
        fov_combo.pack(fill=X, expand=YES)
        fov_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.config.set("FOV_RESOLUTION", self.fov_var.get()),
        )

    def populate_aiming_tab(self, parent):
        """Build Aiming tab including mode-specific frames and common options."""
        mode_frame = ttk.LabelFrame(parent, text="Aim Assist Mode", padding=10)
        mode_frame.pack(fill=X, pady=5, padx=5)
        self.aim_mode_var = tk.StringVar(value=self.config.get("AIM_MODE"))
        self.widget_vars["AIM_MODE"] = self.aim_mode_var
        aim_combo = ttk.Combobox(
            mode_frame,
            textvariable=self.aim_mode_var,
            values=["Classic", "WindMouse", "Hybrid"],
            state="readonly",
        )
        aim_combo.pack(fill=X, expand=YES, pady=(0, 5))
        aim_combo.bind("<<ComboboxSelected>>", self._on_aim_mode_change)

        self.dynamic_frame_container = ttk.Frame(parent)
        self.dynamic_frame_container.pack(fill=X, pady=0, padx=0)

        self.classic_aim_frame = ttk.Frame(self.dynamic_frame_container)
        self.windmouse_aim_frame = ttk.Frame(self.dynamic_frame_container)
        self.hybrid_aim_frame = ttk.Frame(self.dynamic_frame_container)

        classic_acquiring_frame = ttk.LabelFrame(
            self.classic_aim_frame, text="Aim Assist (Acquiring Target)", padding=10
        )
        classic_acquiring_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            classic_acquiring_frame,
            "AIM_ACQUIRING_SPEED",
            "Acquire Speed",
            0.01,
            0.7,
            is_float=True,
        )
        self.create_slider(
            classic_acquiring_frame,
            "AIM_JITTER",
            "Jitter (px)",
            0.0,
            10.0,
            is_float=True,
        )

        classic_tracking_frame = ttk.LabelFrame(
            self.classic_aim_frame, text="Aim Assist (On Target)", padding=10
        )
        classic_tracking_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            classic_tracking_frame,
            "AIM_TRACKING_SPEED",
            "Track Speed",
            0.01,
            0.7,
            is_float=True,
        )
        self.create_slider(
            classic_tracking_frame,
            "AIM_VERTICAL_DAMPING_FACTOR",
            "Vertical Damp",
            0.0,
            0.5,
            is_float=True,
        )
        self.create_slider(
            classic_tracking_frame,
            "MOUSE_SENSITIVITY",
            "In-Game Sens",
            0.200,
            0.900,
            is_float=True,
        )

        windmouse_settings_frame = ttk.LabelFrame(
            self.windmouse_aim_frame,
            text="WindMouse Settings (Full Movement)",
            padding=10,
        )
        windmouse_settings_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            windmouse_settings_frame, "WINDMOUSE_G", "Gravity", 3.0, 20.0, is_float=True
        )
        self.create_slider(
            windmouse_settings_frame, "WINDMOUSE_W", "Wind", 0.0, 15.0, is_float=True
        )
        self.create_slider(
            windmouse_settings_frame,
            "WINDMOUSE_M",
            "Max Step",
            1.0,
            60.0,
            is_float=True,
        )
        self.create_slider(
            windmouse_settings_frame,
            "WINDMOUSE_D",
            "Damping Dist",
            1.0,
            25.0,
            is_float=True,
        )
        self.create_slider(
            windmouse_settings_frame,
            "TARGET_LOCK_THRESHOLD",
            "Lock Thresh",
            1.0,
            25.0,
            is_float=True,
        )

        hybrid_windmouse_frame = ttk.LabelFrame(
            self.hybrid_aim_frame, text="WindMouse (Flick Settings)", padding=10
        )
        hybrid_windmouse_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            hybrid_windmouse_frame,
            "WINDMOUSE_G",
            "Gravity",
            3.0,
            20.0,
            is_float=True,
            clone=True,
        )
        self.create_slider(
            hybrid_windmouse_frame,
            "WINDMOUSE_W",
            "Wind",
            0.0,
            15.0,
            is_float=True,
            clone=True,
        )
        self.create_slider(
            hybrid_windmouse_frame,
            "WINDMOUSE_M",
            "Max Step",
            1.0,
            60.0,
            is_float=True,
            clone=True,
        )
        self.create_slider(
            hybrid_windmouse_frame,
            "WINDMOUSE_D",
            "Damping Dist",
            1.0,
            25.0,
            is_float=True,
            clone=True,
        )

        hybrid_tracking_frame = ttk.LabelFrame(
            self.hybrid_aim_frame, text="Classic (Tracking Settings)", padding=10
        )
        hybrid_tracking_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            hybrid_tracking_frame,
            "AIM_TRACKING_SPEED",
            "Track Speed",
            0.01,
            0.5,
            is_float=True,
            clone=True,
        )
        self.create_slider(
            hybrid_tracking_frame,
            "AIM_VERTICAL_DAMPING_FACTOR",
            "Vertical Damp",
            0.0,
            1.0,
            is_float=True,
            clone=True,
        )

        common_frame = ttk.LabelFrame(parent, text="Common Aim Settings", padding=10)
        common_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(common_frame, "AIM_ASSIST_RANGE", "Range (px)", 10, 60)
        self.create_slider(
            common_frame, "AIM_ASSIST_DELAY", "Aim Delay (s)", 0.0, 0.5, is_float=True
        )
        self.create_slider(common_frame, "DEADZONE", "Deadzone (px)", 1, 12)
        var = tk.BooleanVar(value=self.config.get("AIM_HEADSHOT_MODE"))
        self.widget_vars["AIM_HEADSHOT_MODE"] = var
        ttk.Checkbutton(
            common_frame,
            text="Target Head",
            variable=var,
            bootstyle="round-toggle",
            command=lambda v=var: self.config.set("AIM_HEADSHOT_MODE", v.get()),
        ).pack(anchor=W, pady=(5, 5))
        self.create_slider(common_frame, "HEADSHOT_OFFSET_PERCENT", "Head %", 5, 30)

    def populate_detection_tab(self, parent):
        """Build Detection tab: morphology params and color profile selection."""
        basic_detection_frame = ttk.LabelFrame(
            parent, text="Basic Detection", padding=10
        )
        basic_detection_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            basic_detection_frame, "MIN_CONTOUR_AREA", "Min Size", 10, 1000
        )

        noise_frame = ttk.LabelFrame(parent, text="Noise Processing", padding=10)
        noise_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(noise_frame, "DILATE_ITERATIONS", "Dilate Iter", 1, 6)
        self.create_slider(noise_frame, "DILATE_KERNEL_WIDTH", "Dilate K-W", 1, 10)
        self.create_slider(noise_frame, "DILATE_KERNEL_HEIGHT", "Dilate K-H", 1, 10)
        self.create_slider(noise_frame, "ERODE_ITERATIONS", "Erode Iter", 1, 5)
        self.create_slider(noise_frame, "ERODE_KERNEL_WIDTH", "Erode K-W", 1, 10)
        self.create_slider(noise_frame, "ERODE_KERNEL_HEIGHT", "Erode K-H", 1, 10)

        verification_frame = ttk.LabelFrame(
            parent, text="Verification (Sandwich)", padding=10
        )
        verification_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            verification_frame, "SANDWICH_CHECK_HEIGHT", "Sandwich H", 1, 50
        )
        self.create_slider(
            verification_frame, "SANDWICH_CHECK_SCAN_WIDTH", "Sandwich W", 1, 10
        )

        color_frame = ttk.LabelFrame(parent, text="Color Profile (Enemy)", padding=10)
        color_frame.pack(fill=X, pady=5, padx=5)
        self.color_profile_var = tk.StringVar(
            value=self.config.get("ACTIVE_COLOR_PROFILE")
        )
        self.widget_vars["ACTIVE_COLOR_PROFILE"] = self.color_profile_var
        color_combo = ttk.Combobox(
            color_frame,
            textvariable=self.color_profile_var,
            values=list(self.config.color_profiles.keys()),
            state="readonly",
        )
        color_combo.pack(fill=X, expand=YES, pady=(0, 5))
        color_combo.bind("<<ComboboxSelected>>", self._on_color_profile_change)

        lower_frame = ttk.Frame(color_frame)
        lower_frame.pack(fill=X)
        ttk.Label(lower_frame, text="Lower Color", width=10).pack(side=LEFT)
        self.create_spinbox(lower_frame, "LOWER_YELLOW_H", 0, 179)
        self.create_spinbox(lower_frame, "LOWER_YELLOW_S", 0, 255)
        self.create_spinbox(lower_frame, "LOWER_YELLOW_V", 0, 255)

        upper_frame = ttk.Frame(color_frame)
        upper_frame.pack(fill=X)
        ttk.Label(upper_frame, text="Upper Color", width=10).pack(side=LEFT)
        self.create_spinbox(upper_frame, "UPPER_YELLOW_H", 0, 179)
        self.create_spinbox(upper_frame, "UPPER_YELLOW_S", 0, 255)
        self.create_spinbox(upper_frame, "UPPER_YELLOW_V", 0, 255)

    def populate_advanced_tab(self, parent):
        """Build Advanced tab: trigger durations and delays."""
        fire_control_frame = ttk.LabelFrame(parent, text="Fire Control", padding=10)
        fire_control_frame.pack(fill=X, pady=5, padx=5)
        self.create_slider(
            fire_control_frame, "SHOT_DURATION", "Duration", 0.25, 0.6, is_float=True
        )
        self.create_slider(
            fire_control_frame, "SHOT_COOLDOWN", "Cooldown", 0.25, 0.6, is_float=True
        )
        self.create_slider(
            fire_control_frame, "TRIGGERBOT_DELAY_MS", "Trig. Delay", 0, 120
        )

    def _on_aim_mode_change(self, event=None):
        """Switch visible aiming sub-frame according to selected mode."""
        mode = self.aim_mode_var.get()
        self.config.set("AIM_MODE", mode)

        for widget in self.dynamic_frame_container.winfo_children():
            widget.pack_forget()

        if mode == "Classic":
            self.classic_aim_frame.pack(fill=X)
        elif mode == "WindMouse":
            self.windmouse_aim_frame.pack(fill=X)
        elif mode == "Hybrid":
            self.hybrid_aim_frame.pack(fill=X)

    def _on_color_profile_change(self, event=None):
        """Apply selected color profile and refresh bound HSV fields."""
        profile_name = self.color_profile_var.get()
        if profile := self.config.color_profiles.get(profile_name):
            self.config.set("ACTIVE_COLOR_PROFILE", profile_name)
            hsv_keys = {
                "LOWER_YELLOW_H": profile["lower"][0],
                "LOWER_YELLOW_S": profile["lower"][1],
                "LOWER_YELLOW_V": profile["lower"][2],
                "UPPER_YELLOW_H": profile["upper"][0],
                "UPPER_YELLOW_S": profile["upper"][1],
                "UPPER_YELLOW_V": profile["upper"][2],
            }
            for k, v in hsv_keys.items():
                self.config.set(k, v)
            self._update_gui_from_config()
            logging.getLogger(__name__).info(f"Color profile set to '{profile_name}'")

    def create_spinbox(self, parent, key, from_, to):
        """Create a small integer spin control bound to a config key."""
        var = tk.IntVar(value=self.config.get(key))
        self.widget_vars[key] = var
        spin = ttk.Spinbox(
            parent,
            from_=from_,
            to=to,
            textvariable=var,
            width=5,
            command=lambda k=key, v=var: self.config.set(k, v.get()),
        )
        spin.pack(side=LEFT, padx=2, pady=2)
        var.trace_add("write", lambda *args, k=key, v=var: self.config.set(k, v.get()))

    def create_slider(self, parent, key, text, from_, to, is_float=False, clone=False):
        """Create a labeled slider with +/- nudge buttons bound to a config key.

        If clone=True and another slider for the same key exists, mirror that
        variable; otherwise create a fresh Tk variable and register it.
        """
        container = ttk.Frame(parent)
        container.pack(fill=X, expand=YES, pady=2)
        ttk.Label(container, text=text, width=12).pack(side=LEFT, padx=(0, 5))

        var = self.widget_vars.get(key)
        if clone or not var:
            value = self.config.get(key)
            var = tk.DoubleVar(value=value) if is_float else tk.IntVar(value=value)
            if not clone:
                self.widget_vars[key] = var
        else:
            value = var.get()

        val_label = ttk.Label(
            container, text=f"{value:.3f}" if is_float else str(value), width=5
        )
        val_label.pack(side=RIGHT, padx=(5, 0))

        def btn_cmd(v, s):
            v.set(round(v.get() + s, 3 if is_float else 0))

        ttk.Button(
            container,
            text="+",
            width=2,
            bootstyle=SECONDARY,
            command=lambda v=var, s=(0.01 if is_float else 1): btn_cmd(v, s),
        ).pack(side=RIGHT)
        ttk.Scale(
            container,
            from_=from_,
            to=to,
            orient=HORIZONTAL,
            variable=var,
            bootstyle=SECONDARY,
            command=lambda v, k=key, f=is_float: self.config.set(
                k, float(v) if f else int(float(v))
            ),
        ).pack(side=RIGHT, fill=X, expand=YES, padx=5)
        ttk.Button(
            container,
            text="-",
            width=2,
            bootstyle=SECONDARY,
            command=lambda v=var, s=-(0.01 if is_float else 1): btn_cmd(v, s),
        ).pack(side=RIGHT)
        var.trace_add(
            "write",
            lambda *args, lbl=val_label, v=var, f=is_float, k=key: (
                lbl.config(text=f"{v.get():.3f}" if f else str(int(v.get()))),
                self.config.set(k, v.get()),
            ),
        )

    def _update_gui_from_config(self):
        """Refresh all widgets from the current SharedConfig values."""
        for key, var in self.widget_vars.items():
            new_val = self.config.get(key)
            if new_val is not None:
                try:
                    current_val = var.get()
                    if isinstance(current_val, float):
                        if not np.isclose(current_val, new_val):
                            var.set(new_val)
                    elif current_val != new_val:
                        var.set(new_val)
                except (tk.TclError, TypeError):
                    pass
        self.config_entry_var.set(os.path.basename(self.config.current_filepath))
        self._on_aim_mode_change()

    def _load_config_dialog(self):
        """Open a file chooser and load the selected JSON config file."""
        if fp := filedialog.askopenfilename(
            title="Load Config", filetypes=[("JSON", "*.json")], initialdir=os.getcwd()
        ):
            if self.config.load_from(fp):
                self._update_gui_from_config()
                Messagebox.show_info(
                    f"Loaded: {os.path.basename(fp)}", "Success", parent=self
                )
                logging.info("Config loaded: %s", os.path.basename(fp))

    def _save_config_from_entry(self):
        """Save current config to the filename typed in the input box."""
        filename = self.config_entry_var.get()
        if not filename:
            Messagebox.show_error(
                "Filename cannot be empty.", "Save Error", parent=self
            )
            return
        if not filename.endswith(".json"):
            filename += ".json"
        self.config.save_to(os.path.join(os.getcwd(), filename))
        Messagebox.show_info(f"Saved to {filename}", "Success", parent=self)
        logging.info("Config saved: %s", filename)

    def run_bot_loop(self):
        """Worker loop: call the core once per frame while running flag is set."""
        while self.config.get("is_running"):
            self.bot_instance.run_one_frame()

    def start_bot(self):
        """Initialize the core and start the frame loop in a daemon thread."""
        if self.bot_instance is not None:
            return

        # Log startup configuration snapshot
        try:
            src = self.config.get("FRAME_SOURCE")
            udp_host = self.config.get("UDP_HOST")
            udp_port = self.config.get("UDP_PORT")
            udp_buf = self.config.get("UDP_RCVBUF_MB")
            udp_turbo = self.config.get("UDP_TURBOJPEG")
            fov = self.config.get("FOV_RESOLUTION")
            logging.info(
                "Starting core with FRAME_SOURCE=%s, UDP=%s:%s bufMB=%s turbo=%s, FOV=%s",
                src, udp_host, udp_port, udp_buf, udp_turbo, fov,
            )
        except Exception:
            pass

        self.bot_instance = TriggerbotCore(self.config)
        if not self.bot_instance.setup():
            Messagebox.show_error(
                "Failed to setup bot core. Check logs.", "Startup Error", parent=self
            )
            self.bot_instance = None
            return

        self.config.set("is_running", True)
        self.bot_thread = threading.Thread(target=self.run_bot_loop, daemon=True)
        self.bot_thread.start()

        self.start_button.config(state=DISABLED)
        self.stop_button.config(state=NORMAL)
        logging.getLogger(__name__).info("Start signal sent.")
        # Confirm camera type
        try:
            cam = getattr(self.bot_instance, "camera", None)
            logging.info("Camera type: %s", cam.__class__.__name__ if cam else None)
        except Exception:
            pass

    def stop_bot(self):
        """Signal the worker to stop, wait briefly, and release resources."""
        if self.bot_instance is None:
            return
        logging.getLogger(__name__).info("Stop signal sent.")
        self.config.set("is_running", False)

        # wait briefly for the thread to finish its last frame
        if self.bot_thread:
            self.bot_thread.join(timeout=0.1)

        self.bot_instance.cleanup()
        self.bot_instance = None
        self.bot_thread = None

        self.stop_button.config(state=DISABLED)
        self.start_button.config(state=NORMAL)
        logging.info("Core stopped and resources released.")

    def _start_health_logger(self):
        try:
            if self.health_log_job is None:
                self.health_log_job = self.after(1500, self._health_log_tick)
        except Exception:
            pass

    def _health_log_tick(self):
        try:
            running = bool(self.config.get("is_running"))
            source = self.config.get("FRAME_SOURCE")
            cam = getattr(self.bot_instance, "camera", None) if self.bot_instance else None
            if source == "udp" and cam is not None and isinstance(cam, UdpFrameSource):
                stats = cam.get_stats()
                now_ns = time.monotonic_ns()
                last_pkt_ms = (now_ns - stats.get("last_packet_ns", 0)) / 1e6 if stats.get("last_packet_ns", 0) else -1
                last_frm_ms = (now_ns - stats.get("last_frame_ns", 0)) / 1e6 if stats.get("last_frame_ns", 0) else -1
                packets = stats.get("packets", 0)
                frames = stats.get("frames", 0)
                rt_ms = stats.get("rt_ms", 0.0)
                rt_fps = stats.get("rt_fps", 0.0)
                avg_ms = stats.get("avg_ms", 0.0)
                avg_fps = stats.get("avg_fps", 0.0)

                # Emit logs with clear diagnostics
                if packets == 0:
                    logging.warning("UDP: no packets received yet (running=%s)", running)
                elif frames == 0:
                    logging.warning("UDP: packets=%s bytes=%s but frames=0 (not MJPEG?)", packets, stats.get("bytes", 0))
                elif last_pkt_ms > 2000 or last_frm_ms > 2000:
                    logging.warning("UDP: stalled stream lastPkt=%.0fms lastFrm=%.0fms", last_pkt_ms, last_frm_ms)
                else:
                    logging.info(
                        "UDP: pkts=%s bytes=%s frames=%s rt=%.1fms %.1ffps avg=%.1fms %.1ffps lastPkt=%.0fms lastFrm=%.0fms",
                        packets, stats.get("bytes", 0), frames, rt_ms, rt_fps, avg_ms, avg_fps, last_pkt_ms, last_frm_ms,
                    )
            else:
                # For dxcam or not running, still checkpoint occasionally
                logging.debug("Health: running=%s source=%s cam=%s", running, source, cam.__class__.__name__ if cam else None)
        except Exception as e:
            logging.exception("Health logger tick failed")
        finally:
            try:
                self.health_log_job = self.after(1500, self._health_log_tick)
            except Exception:
                pass

    def on_closing(self):
        """Ensure the core stops before closing the window."""
        if self.config.get("is_running"):
            self.stop_bot()
        self.destroy()


if __name__ == "__main__":
    setup_logging()
    try:
        shared_config = SharedConfig()
        app = ControlPanelGUI(shared_config)
        app.mainloop()
    except Exception as e:
        logging.getLogger(__name__).critical(
            "A critical error occurred in the GUI thread", exc_info=True
        )
