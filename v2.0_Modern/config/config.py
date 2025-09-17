import threading
import json
import os
import numpy as np
import logging


class SharedConfig:
    """Thread-safe configuration storage shared across the app.

    Responsibilities:
    - Hold default values and the current runtime values for all tunables
    - Persist a curated subset of settings to disk (JSON) and load them back
    - Provide helpers to expose derived structures (e.g., HSV bounds, kernels)

    Notes about mutability and safety:
    - All reads/writes of the in-memory settings dict are protected by a lock
      to keep GUI thread and worker threads consistent.
    - Some keys are marked as "hardcoded". Those are injected on top of the
      loaded settings at all times and cannot be overridden by files or the UI.
    """

    def __init__(self, filename="config.json"):
        # A single lock protects all accesses to self.settings
        self.lock = threading.Lock()
        # Default location for the config file; also used on first run
        self.default_filename = filename
        # Tracks the path of the most recently loaded/saved file for the GUI
        self.current_filepath = filename
        # The order in which keys are written to disk so diffs stay stable
        self.key_order = [
            "ACTIVE_COLOR_PROFILE",
            "FRAME_SOURCE",
            "FPS_LIMIT",
            "DEBUG_WINDOW_VISIBLE",
            "HUD_SHOW_AIM_STATUS",
            "AIM_ASSIST_ENABLED",
            "TRIGGERBOT_ENABLED",
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
            "MOUSE_SPEED_MULTIPLIER",
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
            "MIN_CONTOUR_AREA",
            "DILATE_ITERATIONS",
            "DILATE_KERNEL_WIDTH",
            "DILATE_KERNEL_HEIGHT",
            "ERODE_ITERATIONS",
            "ERODE_KERNEL_WIDTH",
            "ERODE_KERNEL_HEIGHT",
            "SANDWICH_CHECK_HEIGHT",
            "SANDWICH_CHECK_SCAN_WIDTH",
            "SHOT_DURATION",
            "SHOT_COOLDOWN",
            "TRIGGERBOT_DELAY_MS",
            "LOWER_YELLOW_H",
            "LOWER_YELLOW_S",
            "LOWER_YELLOW_V",
            "UPPER_YELLOW_H",
            "UPPER_YELLOW_S",
            "UPPER_YELLOW_V",
            "FOV_RESOLUTION",
            "UDP_HOST",
            "UDP_PORT",
            "UDP_RCVBUF_MB",
            "UDP_TURBOJPEG",
        ]
        # Hardcoded keys are merged after loading and cannot be overridden.
        # FOV_RESOLUTIONS_MAP maps a string resolution to an on-screen anchor.
        self.hardcoded_settings = {
            "FOV_RESOLUTIONS_MAP": {
                "128x128": (896, 476),
                "160x160": (880, 460),
                "192x192": (864, 444),
                "224x224": (848, 428),
                "256x256": (832, 412),
                "288x288": (816, 396),
                "320x320": (800, 380),
                "352x352": (784, 364),
                "384x384": (768, 348),
                "416x416": (752, 332),
                "448x448": (736, 316),
                "480x480": (720, 300),
                "512x512": (704, 284),
                "544x544": (688, 268),
                "576x576": (672, 252),
                "608x608": (656, 236),
                "640x640": (640, 220),
            }
        }
        # Predefined HSV color profiles. ACTIVE_COLOR_PROFILE selects one and
        # the corresponding bounds are copied into the mutable settings below.
        self.color_profiles = {
            "purple-new": {"lower": [144, 106, 172], "upper": [151, 255, 255]},
            "yellow": {"lower": [30, 113, 131], "upper": [32, 255, 255]},
        }
        default_profile = self.color_profiles["purple-new"]
        # Defaults establish a safe, usable baseline for all tunables.
        # They are applied before loading any file on disk.
        self.defaults = {
            "ACTIVE_COLOR_PROFILE": "purple-new",
            "FRAME_SOURCE": "udp",
            "FPS_LIMIT": 240,
            "HUD_SHOW_AIM_STATUS": True,
            "LOWER_YELLOW_H": default_profile["lower"][0],
            "LOWER_YELLOW_S": default_profile["lower"][1],
            "LOWER_YELLOW_V": default_profile["lower"][2],
            "UPPER_YELLOW_H": default_profile["upper"][0],
            "UPPER_YELLOW_S": default_profile["upper"][1],
            "UPPER_YELLOW_V": default_profile["upper"][2],
            "is_running": False,
            "AIM_ASSIST_ENABLED": True,
            "TRIGGERBOT_ENABLED": False,
            "DEBUG_WINDOW_VISIBLE": True,
            "MOUSE_ACTIVATION_BUTTON_1": "Right",  # Left/Right/Middle/Mouse4/Mouse5
            "MOUSE_ACTIVATION_BUTTON_2": "Mouse4",  # Left/Right/Middle/Mouse4/Mouse5
            "MOUSE_ACTIVATION_MODE_1": "Hold",  # Hold/Toggle for button 1
            "MOUSE_ACTIVATION_MODE_2": "Toggle",  # Hold/Toggle for button 2
            "MOUSE_ACTIVATION_DELAY_MS": 0,
            "MOUSE_SPEED_MULTIPLIER": 1.0,
            "MOUSE_STEP_DELAY_MS": 1,
            "MOUSE_EASE_OUT": True,
            "MOUSE_SMOOTHNESS": 0.8,
            "AIM_MODE": "Hybrid",
            "WINDMOUSE_G": 7.0,
            "WINDMOUSE_W": 3.0,
            "WINDMOUSE_M": 12.0,
            "WINDMOUSE_D": 10.0,
            "TARGET_LOCK_THRESHOLD": 8.0,
            "AIM_ACQUIRING_SPEED": 0.15,
            "AIM_TRACKING_SPEED": 0.04,
            "AIM_JITTER": 0.0,
            "MOUSE_SENSITIVITY": 0.350,
            "AIM_ASSIST_RANGE": 23,
            "AIM_VERTICAL_DAMPING_FACTOR": 0.15,
            "AIM_ASSIST_DELAY": 0.080,
            "AIM_HEADSHOT_MODE": True,
            "HEADSHOT_OFFSET_PERCENT": 18,
            "DEADZONE": 2,
            "MOUSE_1_BUTTON": "right",
            "MOUSE_2_BUTTON": "left",
            "MOUSE_1_MODE": "toggle",
            "MOUSE_2_MODE": "hold",
            "MIN_CONTOUR_AREA": 40,
            "DILATE_ITERATIONS": 2.0,
            "DILATE_KERNEL_WIDTH": 3.0,
            "DILATE_KERNEL_HEIGHT": 3.0,
            "ERODE_ITERATIONS": 1.0,
            "ERODE_KERNEL_WIDTH": 2.0,
            "ERODE_KERNEL_HEIGHT": 2.0,
            "SANDWICH_CHECK_HEIGHT": 15,
            "SANDWICH_CHECK_SCAN_WIDTH": 5,
            "SHOT_DURATION": 0.1,
            "SHOT_COOLDOWN": 0.15,
            "TRIGGERBOT_DELAY_MS": 10,
            # Advanced Trigger Bot Settings
            "TRIGGER_MODE": "instant",  # instant, burst, adaptive
            "TRIGGER_BURST_MODE": False,
            "TRIGGER_BURST_COUNT": 3,
            "TRIGGER_BURST_DELAY": 0.05,
            "TRIGGER_ADAPTIVE_DELAY": False,
            "TRIGGER_SIZE_FACTOR": 1.0,
            "TRIGGER_DISTANCE_FACTOR": 1.0,
            "TRIGGER_MAX_DELAY_MS": 100,
            "TRIGGER_MIN_COOLDOWN": 0.15,
            "TRIGGER_RANDOM_DELAY": False,
            "TRIGGER_RANDOM_MIN": 5,
            "TRIGGER_RANDOM_MAX": 15,
            "TRIGGER_SMOOTHING": True,
            "TRIGGER_SMOOTHING_FACTOR": 0.8,
            "TRIGGER_PREDICTION": False,
            "TRIGGER_PREDICTION_TIME": 0.1,
            "TRIGGER_ANTI_PATTERN": False,
            "TRIGGER_ANTI_PATTERN_TIME": 0.5,
            "TRIGGER_WEAPON_MODE": "auto",  # auto, single, burst, spray
            "TRIGGER_WEAPON_DELAYS": {
                "auto": 0.05,
                "single": 0.1,
                "burst": 0.08,
                "spray": 0.03,
            },
            "TRIGGER_WEAPON_COOLDOWNS": {
                "auto": 0.1,
                "single": 0.2,
                "burst": 0.15,
                "spray": 0.05,
            },
            "TRIGGER_ACCURACY_MODE": "normal",  # normal, high, low
            "TRIGGER_ACCURACY_FACTORS": {"normal": 1.0, "high": 0.8, "low": 1.2},
            "TRIGGER_TARGET_PRIORITY": "center",  # center, closest, largest
            "TRIGGER_TARGET_FILTER": True,
            "TRIGGER_MIN_TARGET_SIZE": 5,
            "TRIGGER_MAX_TARGET_SIZE": 100,
            "TRIGGER_TARGET_CONFIDENCE": 0.7,
            "TRIGGER_MOVEMENT_COMPENSATION": False,
            "TRIGGER_MOVEMENT_THRESHOLD": 10,
            "TRIGGER_MOVEMENT_FACTOR": 0.5,
            "TRIGGER_HEALTH_CHECK": False,
            "TRIGGER_HEALTH_THRESHOLD": 0.3,
            "TRIGGER_AMMO_CHECK": False,
            "TRIGGER_AMMO_THRESHOLD": 5,
            "TRIGGER_SOUND_DETECTION": False,
            "TRIGGER_SOUND_THRESHOLD": 0.5,
            "TRIGGER_VIBRATION_FEEDBACK": False,
            "TRIGGER_VIBRATION_INTENSITY": 0.5,
            "TRIGGER_DEBUG_MODE": False,
            "TRIGGER_DEBUG_LEVEL": 1,  # 1=basic, 2=detailed, 3=verbose
            "TRIGGER_STATISTICS": True,
            "TRIGGER_STATS_WINDOW": 100,  # frames
            "TRIGGER_PERFORMANCE_MODE": False,
            "TRIGGER_PERFORMANCE_THRESHOLD": 0.8,
            "FOV_RESOLUTION": "256x256",
            "UDP_HOST": "0.0.0.0",
            "UDP_PORT": 8080,
            "UDP_RCVBUF_MB": 64,
            "UDP_TURBOJPEG": True,
        }
        # Active, mutable settings for this process. Start with defaults and
        # immediately layer hardcoded keys; then load from disk.
        self.settings = self.defaults.copy()
        self.settings.update(self.hardcoded_settings)
        self.load_from(self.default_filename, is_default=True)

    def get(self, key, default=None):
        """Thread-safe getter for any key in the settings dictionary."""
        with self.lock:
            return self.settings.get(key, default)

    def set(self, key, value):
        """Thread-safe setter that ignores attempts to override hardcoded keys."""
        if key in self.hardcoded_settings:
            return
        with self.lock:
            self.settings[key] = value

    def get_hsv_lower(self):
        """Return lower HSV bound as a NumPy array for OpenCV masking."""
        with self.lock:
            return np.array(
                [
                    self.settings["LOWER_YELLOW_H"],
                    self.settings["LOWER_YELLOW_S"],
                    self.settings["LOWER_YELLOW_V"],
                ]
            )

    def get_hsv_upper(self):
        """Return upper HSV bound as a NumPy array for OpenCV masking."""
        with self.lock:
            return np.array(
                [
                    self.settings["UPPER_YELLOW_H"],
                    self.settings["UPPER_YELLOW_S"],
                    self.settings["UPPER_YELLOW_V"],
                ]
            )

    def get_dilate_kernel(self):
        """Return a rectangular kernel for cv2.dilate based on current settings."""
        with self.lock:
            return np.ones(
                (
                    int(self.settings["DILATE_KERNEL_HEIGHT"]),
                    int(self.settings["DILATE_KERNEL_WIDTH"]),
                ),
                np.uint8,
            )

    def get_erode_kernel(self):
        """Return a rectangular kernel for cv2.erode based on current settings."""
        with self.lock:
            return np.ones(
                (
                    int(self.settings["ERODE_KERNEL_HEIGHT"]),
                    int(self.settings["ERODE_KERNEL_WIDTH"]),
                ),
                np.uint8,
            )

    def load_from(self, filepath, is_default=False):
        """Load settings from a JSON file.

        Behavior:
        - If the file does not exist on first run, it will be created from
          defaults. For explicit loads, a missing file is an error.
        - The merge order is: defaults -> file values -> hardcoded settings.
        """
        if not os.path.exists(filepath):
            if is_default:
                self.save_to(filepath)
            else:
                logging.getLogger(__name__).error(
                    f"Config file not found at '{filepath}'"
                )
                return False
        try:
            with open(filepath, "r") as f:
                loaded_settings = json.load(f)
            with self.lock:
                # Reset to defaults first, then apply the file values, then re-apply hardcoded keys
                self.settings.update(self.defaults)
                for key, value in loaded_settings.items():
                    if key in self.settings and key not in self.hardcoded_settings:
                        self.settings[key] = value
                self.settings.update(self.hardcoded_settings)
            self.current_filepath = filepath
            logging.getLogger(__name__).info(
                f"Settings loaded from '{os.path.basename(filepath)}'"
            )
            return True
        except Exception as e:
            logging.getLogger(__name__).exception(
                f"Error reading config file '{filepath}'"
            )
            return False

    def save_to(self, filepath):
        """Persist a curated subset of settings to disk in a stable key order."""
        with self.lock:
            settings_to_save = {
                key: self.settings.get(key, self.defaults.get(key))
                for key in self.key_order
                if key in self.settings
            }
        with open(filepath, "w") as f:
            json.dump(settings_to_save, f, indent=4)
        self.current_filepath = filepath
        logging.getLogger(__name__).info(
            f"Settings saved to '{os.path.basename(filepath)}'"
        )
