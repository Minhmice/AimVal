#!/usr/bin/env python3
"""
AimVal v5 - Simple UDP Viewer with basic config UI
"""

import customtkinter as ctk
import tkinter as tk
import json
import os
# Imports removed - all handled by pure_udp_viewer.py

try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None  # type: ignore

# Import core UDP components directly for integration
import socket
import threading
import time
import select
from typing import Optional
import numpy as np
import cv2

try:
    from turbojpeg import TurboJPEG  # type: ignore
except Exception:
    TurboJPEG = None  # type: ignore

# Constants from v2
HOST = "0.0.0.0"
PORT = 8080
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

def decode_jpeg_cv2(buf: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img

class FrameBuffer:
    """Thread-safe storage for the latest complete JPEG frame bytes."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: Optional[bytes] = None

    def set_latest(self, data: bytes) -> None:
        with self._lock:
            self._buf = data

    def get_latest(self) -> Optional[bytes]:
        with self._lock:
            return self._buf

class ReceiverThread(threading.Thread):
    def __init__(self, sock: socket.socket, max_buffer_bytes: int, frame_store: FrameBuffer) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.max_buffer_bytes = max_buffer_bytes
        self.frame_store = frame_store
        self._stop = threading.Event()
        self._buffer = bytearray()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            # Drain socket
            rlist, _, _ = select.select([self.sock], [], [], 0.002)
            while rlist and not self._stop.is_set():
                try:
                    data, _ = self.sock.recvfrom(65535)
                    self._buffer.extend(data)
                except BlockingIOError:
                    break
                rlist, _, _ = select.select([self.sock], [], [], 0.0)

            # Extract all complete JPEGs; keep only the latest
            latest: Optional[bytes] = None
            while True:
                start = self._buffer.find(SOI)
                if start == -1:
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer.clear()
                    break
                end = self._buffer.find(EOI, start + 2)
                if end == -1:
                    if len(self._buffer) > self.max_buffer_bytes:
                        self._buffer[:] = self._buffer[-(2 * 1024 * 1024) :]
                    break
                latest = bytes(self._buffer[start : end + 2])
                del self._buffer[: end + 2]

            if latest is not None:
                self.frame_store.set_latest(latest)

class IntegratedUdpViewer:
    """
    Integrated UDP Viewer with detection, aim, and trigger capabilities
    Combines pure UDP streaming with AI features
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, rcvbuf_mb: int = 64):
        self.host = host
        self.port = port
        self.rcvbuf_mb = rcvbuf_mb
        
        # Core UDP components
        self.sock: Optional[socket.socket] = None
        self.max_buffer_bytes = 64 * 1024 * 1024
        self.store = FrameBuffer()
        self.recv_thread: Optional[ReceiverThread] = None
        
        # TurboJPEG setup - Always on
        self.use_turbo = False
        self.jpeg_decoder = None
        if TurboJPEG is not None:
            try:
                self.jpeg_decoder = TurboJPEG()
                self.use_turbo = True
                print("[INFO] TurboJPEG enabled (always on)")
            except Exception as e:
                print(f"[WARN] TurboJPEG init failed: {e}")
        
        # Metrics tracking
        self.tty_prev_ns: Optional[int] = None
        self.tty_first_ns: Optional[int] = None
        self.tty_total_ns: int = 0
        self.tty_frames: int = 0
        self.started = False
        
        # AI/Detection components (will be initialized later)
        self.detection_enabled = False
        self.aim_enabled = False
        self.trigger_enabled = False

    def start(self) -> bool:
        """Start integrated UDP viewer"""
        if self.started:
            return True
            
        try:
            # Socket setup
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_mb * 1024 * 1024)
            except OSError:
                pass
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)

            # Start receiver thread
            self.recv_thread = ReceiverThread(self.sock, self.max_buffer_bytes, self.store)
            self.recv_thread.start()
            
            self.started = True
            print(f"[INFO] Integrated UDP viewer started on {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to start UDP viewer: {e}")
            self.stop()
            return False

    def stop(self):
        """Stop integrated UDP viewer"""
        self.started = False
        
        if self.recv_thread:
            self.recv_thread.stop()
            self.recv_thread.join(timeout=1.0)
            self.recv_thread = None
            
        if self.sock:
            self.sock.close()
            self.sock = None

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get latest frame with optional AI processing"""
        if not self.started:
            return None
            
        buf = self.store.get_latest()
        if buf is None:
            return None

        # Decode frame
        if self.use_turbo and self.jpeg_decoder is not None:
            try:
                frame = self.jpeg_decoder.decode(buf)
            except Exception:
                frame = decode_jpeg_cv2(buf)
        else:
            frame = decode_jpeg_cv2(buf)

        if frame is not None:
            # Update metrics
            now_ns = time.monotonic_ns()
            if self.tty_prev_ns is None:
                self.tty_prev_ns = now_ns
                self.tty_first_ns = now_ns
            self.tty_prev_ns = now_ns
            self.tty_frames += 1
            if self.tty_first_ns is not None:
                self.tty_total_ns = now_ns - self.tty_first_ns
            
            # Apply AI processing if enabled
            frame = self._process_frame(frame)

        return frame
    
    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Process frame with detection, aim, and trigger"""
        processed_frame = frame.copy()
        
        # Detection processing
        if self.detection_enabled:
            processed_frame = self._apply_detection(processed_frame)
        
        # Aim processing  
        if self.aim_enabled:
            processed_frame = self._apply_aim(processed_frame)
            
        # Trigger processing
        if self.trigger_enabled:
            self._apply_trigger(processed_frame)
        
        return processed_frame
    
    def _apply_detection(self, frame: np.ndarray) -> np.ndarray:
        """Apply detection algorithms"""
        # Placeholder for detection logic
        # Will integrate with detectors/hsv_color.py and other detection modules
        return frame
    
    def _apply_aim(self, frame: np.ndarray) -> np.ndarray:
        """Apply aiming algorithms"""
        # Placeholder for aim logic  
        # Will integrate with aiming algorithms
        return frame
    
    def _apply_trigger(self, frame: np.ndarray):
        """Apply trigger logic"""
        # Placeholder for trigger logic
        # Will integrate with actions/aim_trigger.py
        pass

    def get_fps(self) -> tuple[float, float]:
        """Get FPS metrics"""
        if self.tty_prev_ns is None or self.tty_first_ns is None or self.tty_frames == 0:
            return 0.0, 0.0
            
        now_ns = time.monotonic_ns()
        
        # Real-time FPS
        if self.tty_prev_ns and now_ns > self.tty_prev_ns:
            dt_ns = now_ns - self.tty_prev_ns
            if dt_ns > 0:
                rt_fps = 1e9 / dt_ns
            else:
                rt_fps = 0.0
        else:
            rt_fps = 0.0
            
        # Average FPS
        total_ns = now_ns - self.tty_first_ns
        if total_ns > 0:
            avg_fps = self.tty_frames / (total_ns / 1e9)
        else:
            avg_fps = 0.0
            
        return rt_fps, avg_fps

    def get_stats(self) -> dict:
        """Get comprehensive stats"""
        rt_fps, avg_fps = self.get_fps()
        return {
            "rt_fps": rt_fps,
            "avg_fps": avg_fps,
            "started": self.started,
            "use_turbo": self.use_turbo,
            "frames": self.tty_frames,
            "detection_enabled": self.detection_enabled,
            "aim_enabled": self.aim_enabled,
            "trigger_enabled": self.trigger_enabled
        }

# Use integrated viewer
SimpleUdpViewer = IntegratedUdpViewer


class App(ctk.CTk):
    """Comprehensive config UI với slider + input"""

    def __init__(self):
        super().__init__()
        self.title("AimVal v5 - Advanced Config")
        ctk.set_appearance_mode("Dark")
        self.geometry("600x800")  # Single column layout

        # Load config
        cfg_path = os.path.join(os.path.dirname(__file__), "configs", "default.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        # UDP Viewer
        udp_cfg = self.cfg.get("udp", {})
        port = int(udp_cfg.get("mjpeg_port", 8080))
        self.viewer = SimpleUdpViewer("0.0.0.0", port, 64)

        # Integrated viewer with AI capabilities
        self.viewer_window_active = False

        self._build_ui()
        self._tick()

    def _build_ui(self):
        # Single column layout
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(expand=True, fill="both", padx=10, pady=10)
        main_frame.grid_rowconfigure(0, weight=0)  # Title
        main_frame.grid_rowconfigure(1, weight=0)  # Control button
        main_frame.grid_rowconfigure(2, weight=0)  # Status
        main_frame.grid_rowconfigure(3, weight=0)  # UDP Config
        main_frame.grid_rowconfigure(4, weight=1)  # Tabs
        main_frame.grid_columnconfigure(0, weight=1)

        # Title
        title = ctk.CTkLabel(
            main_frame, text="🎯 AimVal v5", font=ctk.CTkFont(size=24, weight="bold")
        )
        title.grid(row=0, column=0, pady=15)

        # Single control button (Start/Stop toggle)
        self.is_running = False
        self.control_btn = ctk.CTkButton(
            main_frame,
            text="🚀 Start",
            command=self._toggle_start_stop,
            width=200,
            height=40,
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.control_btn.grid(row=1, column=0, pady=10)

        # Status display
        self.status_var = tk.StringVar(value="Status: Stopped")
        self.fps_var = tk.StringVar(value="FPS: --")

        status_frame = ctk.CTkFrame(main_frame)
        status_frame.grid(row=2, column=0, sticky="ew", pady=5)

        ctk.CTkLabel(status_frame, textvariable=self.status_var).pack(
            side="left", padx=10
        )
        ctk.CTkLabel(status_frame, textvariable=self.fps_var).pack(
            side="right", padx=10
        )

        # UDP Config
        udp_config_frame = ctk.CTkFrame(main_frame)
        udp_config_frame.grid(row=3, column=0, sticky="ew", pady=10)

        ctk.CTkLabel(
            udp_config_frame,
            text="📡 UDP Config",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=5)

        # Port setting
        port_frame = ctk.CTkFrame(udp_config_frame)
        port_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(port_frame, text="Port:").pack(side="left", padx=5)
        self.port_var = tk.StringVar(
            value=str(self.cfg.get("udp", {}).get("mjpeg_port", 8080))
        )
        ctk.CTkEntry(port_frame, textvariable=self.port_var, width=100).pack(
            side="left", padx=5
        )
        ctk.CTkButton(
            port_frame, text="Apply", command=self._apply_port, width=60
        ).pack(side="left", padx=5)

        # Buffer setting
        buffer_frame = ctk.CTkFrame(udp_config_frame)
        buffer_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(buffer_frame, text="Buffer (MB):").pack(side="left", padx=5)
        self.buffer_var = tk.StringVar(
            value=str(self.cfg.get("udp", {}).get("rcvbuf_mb", 64))
        )
        ctk.CTkEntry(buffer_frame, textvariable=self.buffer_var, width=100).pack(
            side="left", padx=5
        )

        # TurboJPEG always enabled - no need to display

        # Configuration tabs
        tabs = ctk.CTkTabview(main_frame)
        tabs.grid(row=4, column=0, sticky="nsew", pady=10)

        tab_aim = tabs.add("Aim")
        tab_detection = tabs.add("Detection")
        tab_trigger = tabs.add("Trigger")
        tab_advance = tabs.add("Advance")

        self._build_tab_aim(tab_aim)
        self._build_tab_detection(tab_detection)
        self._build_tab_trigger(tab_trigger)
        self._build_tab_advance(tab_advance)

    def add_slider_with_input(
        self, parent, label, min_v, max_v, init_v, step=0.001, precision=3
    ):
        """Helper function để tạo slider + input với float precision"""
        row = ctk.CTkFrame(parent)
        row.pack(fill="x", pady=4)

        # Label
        ctk.CTkLabel(row, text=label, width=140, anchor="w").pack(side="left", padx=6)

        # Input entry
        entry = ctk.CTkEntry(row, width=80)
        entry.insert(0, f"{float(init_v):.{precision}f}")
        entry.pack(side="right", padx=6)

        # Value display
        value_label = ctk.CTkLabel(row, text=f"{float(init_v):.{precision}f}", width=70)
        value_label.pack(side="right", padx=6)

        # Slider
        slider = ctk.CTkSlider(
            row,
            from_=min_v,
            to=max_v,
            number_of_steps=max(1, int((max_v - min_v) / step)),
        )
        slider.set(float(init_v))
        slider.pack(fill="x", expand=True, padx=6)

        def on_slider_change(v):
            try:
                val = float(v)
                value_label.configure(text=f"{val:.{precision}f}")
                entry.delete(0, tk.END)
                entry.insert(0, f"{val:.{precision}f}")
            except Exception:
                pass

        def on_entry_change(event=None):
            try:
                val = float(entry.get())
                val = max(min_v, min(max_v, val))  # Clamp value
                slider.set(val)
                value_label.configure(text=f"{val:.{precision}f}")
            except Exception:
                pass

        slider.configure(command=on_slider_change)
        entry.bind("<Return>", on_entry_change)
        entry.bind("<FocusOut>", on_entry_change)

        return slider, entry

    def _build_tab_aim(self, parent):
        """Aim tab với slider + input controls"""
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)

        # Enable checkbox
        act = self.cfg.get("actions", {})
        self.var_aim = tk.BooleanVar(value=bool(act.get("aim_enabled", False)))
        ctk.CTkCheckBox(
            frm,
            text="🎯 Enable Aim Assist",
            variable=self.var_aim,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", pady=(0, 10))

        # Mouse Settings
        ctk.CTkLabel(
            frm, text="🖱️ Mouse Settings", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(15, 5))

        self.msens_s, self.msens_e = self.add_slider_with_input(
            frm,
            "Mouse Sensitivity",
            0.001,
            2.0,
            float(act.get("mouse_sensitivity", 0.35)),
            step=0.001,
            precision=3,
        )
        self.msmooth_s, self.msmooth_e = self.add_slider_with_input(
            frm,
            "Mouse Smoothness",
            0.01,
            1.0,
            float(act.get("mouse_smoothness", 0.8)),
            step=0.01,
            precision=3,
        )

        # Aim Parameters
        ctk.CTkLabel(
            frm, text="🎯 Aim Parameters", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(15, 5))

        self.aim_range_s, self.aim_range_e = self.add_slider_with_input(
            frm,
            "Aim Range",
            1.0,
            1000.0,
            float(self.cfg.get("AIM_ASSIST_RANGE", 23)),
            step=1.0,
            precision=1,
        )
        self.deadzone_s, self.deadzone_e = self.add_slider_with_input(
            frm,
            "Deadzone",
            0.0,
            50.0,
            float(self.cfg.get("DEADZONE", 2)),
            step=0.1,
            precision=1,
        )

        # Apply button
        ctk.CTkButton(
            frm,
            text="🔄 Apply Aim Settings",
            command=self._apply_aim_settings,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=35,
        ).pack(anchor="e", padx=6, pady=15)

    def _build_tab_detection(self, parent):
        """Detection tab với HSV controls"""
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)

        # Enable checkbox
        self.var_hsv_enabled = tk.BooleanVar(
            value=bool(self.cfg.get("hsv", {}).get("enabled", True))
        )
        ctk.CTkCheckBox(
            frm,
            text="🎯 Enable HSV Detection",
            variable=self.var_hsv_enabled,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", pady=(0, 10))

        # HSV Color Range
        ctk.CTkLabel(
            frm, text="🌈 HSV Color Range", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(15, 5))

        hsv_cfg = self.cfg.get("hsv", {})
        lower = hsv_cfg.get("lower", [20, 100, 100])
        upper = hsv_cfg.get("upper", [35, 255, 255])

        self.h_l_s, self.h_l_e = self.add_slider_with_input(
            frm, "H Lower", 0, 179, lower[0], step=1, precision=0
        )
        self.s_l_s, self.s_l_e = self.add_slider_with_input(
            frm, "S Lower", 0, 255, lower[1], step=1, precision=0
        )
        self.v_l_s, self.v_l_e = self.add_slider_with_input(
            frm, "V Lower", 0, 255, lower[2], step=1, precision=0
        )
        self.h_u_s, self.h_u_e = self.add_slider_with_input(
            frm, "H Upper", 0, 179, upper[0], step=1, precision=0
        )
        self.s_u_s, self.s_u_e = self.add_slider_with_input(
            frm, "S Upper", 0, 255, upper[1], step=1, precision=0
        )
        self.v_u_s, self.v_u_e = self.add_slider_with_input(
            frm, "V Upper", 0, 255, upper[2], step=1, precision=0
        )

        # Morphology
        ctk.CTkLabel(
            frm, text="🔧 Morphology", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(15, 5))

        self.morph_k_s, self.morph_k_e = self.add_slider_with_input(
            frm,
            "Morph Kernel",
            1.0,
            15.0,
            float(hsv_cfg.get("morph_kernel", 3)),
            step=0.5,
            precision=1,
        )
        self.min_area_s, self.min_area_e = self.add_slider_with_input(
            frm,
            "Min Area",
            0.0,
            10000.0,
            float(hsv_cfg.get("min_area", 150)),
            step=10.0,
            precision=1,
        )

        # Apply button
        ctk.CTkButton(
            frm,
            text="🔄 Apply Detection Settings",
            command=self._apply_detection_settings,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=35,
        ).pack(anchor="e", padx=6, pady=15)

    def _build_tab_trigger(self, parent):
        """Trigger tab với timing controls"""
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)

        # Enable checkbox
        act = self.cfg.get("actions", {})
        self.var_trg = tk.BooleanVar(value=bool(act.get("trigger_enabled", False)))
        ctk.CTkCheckBox(
            frm,
            text="🔫 Enable Trigger Bot",
            variable=self.var_trg,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", pady=(0, 10))

        # Trigger Settings
        ctk.CTkLabel(
            frm, text="⏱️ Trigger Settings", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", pady=(15, 5))

        self.tdelay_s, self.tdelay_e = self.add_slider_with_input(
            frm,
            "Trigger Delay (ms)",
            0.0,
            500.0,
            float(act.get("trigger_delay_ms", 10)),
            step=0.1,
            precision=1,
        )
        self.tcd_s, self.tcd_e = self.add_slider_with_input(
            frm,
            "Trigger Cooldown (s)",
            0.0,
            2.0,
            float(act.get("trigger_cooldown", 0.15)),
            step=0.001,
            precision=3,
        )

        # Apply button
        ctk.CTkButton(
            frm,
            text="🔄 Apply Trigger Settings",
            command=self._apply_trigger_settings,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=35,
        ).pack(anchor="e", padx=6, pady=15)

    def _build_tab_advance(self, parent):
        """Advanced settings từ v2, v3, v4"""
        frm = ctk.CTkScrollableFrame(parent)
        frm.pack(expand=True, fill="both", padx=8, pady=8)

        # Fire Control từ v2
        ctk.CTkLabel(
            frm, text="🔥 Fire Control (v2)", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(15, 10))

        self.shot_duration_s, self.shot_duration_e = self.add_slider_with_input(
            frm,
            "Shot Duration (s)",
            0.01,
            1.0,
            float(self.cfg.get("SHOT_DURATION", 0.1)),
            step=0.001,
            precision=3,
        )

        # Movement & Offset từ v3
        ctk.CTkLabel(
            frm,
            text="🎮 Movement & Offset (v3)",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", pady=(20, 10))

        self.offset_x_s, self.offset_x_e = self.add_slider_with_input(
            frm,
            "Offset X",
            -50.0,
            50.0,
            float(self.cfg.get("offsetX", -2)),
            step=0.1,
            precision=1,
        )
        self.offset_y_s, self.offset_y_e = self.add_slider_with_input(
            frm,
            "Offset Y",
            -50.0,
            50.0,
            float(self.cfg.get("offsetY", 3)),
            step=0.1,
            precision=1,
        )

        # Speed settings từ v3
        self.normal_x_speed_s, self.normal_x_speed_e = self.add_slider_with_input(
            frm,
            "Normal X Speed",
            0.1,
            10.0,
            float(self.cfg.get("normal_x_speed", 3)),
            step=0.1,
            precision=1,
        )
        self.normal_y_speed_s, self.normal_y_speed_e = self.add_slider_with_input(
            frm,
            "Normal Y Speed",
            0.1,
            10.0,
            float(self.cfg.get("normal_y_speed", 3)),
            step=0.1,
            precision=1,
        )

        # Apply button
        ctk.CTkButton(
            frm,
            text="🔄 Apply Advanced Settings",
            command=self._apply_advance_settings,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=35,
        ).pack(anchor="e", padx=6, pady=15)

    def _apply_aim_settings(self):
        """Apply aim settings"""
        try:
            # Update config với giá trị từ slider
            if not hasattr(self.cfg, "actions"):
                self.cfg["actions"] = {}

            self.cfg["actions"]["aim_enabled"] = self.var_aim.get()
            if hasattr(self, "msens_s"):
                self.cfg["actions"]["mouse_sensitivity"] = float(self.msens_s.get())
            if hasattr(self, "msmooth_s"):
                self.cfg["actions"]["mouse_smoothness"] = float(self.msmooth_s.get())
            if hasattr(self, "aim_range_s"):
                self.cfg["AIM_ASSIST_RANGE"] = float(self.aim_range_s.get())
            if hasattr(self, "deadzone_s"):
                self.cfg["DEADZONE"] = float(self.deadzone_s.get())

            self._save_config()
            self.status_var.set("Applied aim settings")
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _apply_detection_settings(self):
        """Apply detection settings"""
        try:
            if not hasattr(self.cfg, "hsv"):
                self.cfg["hsv"] = {}

            self.cfg["hsv"]["enabled"] = self.var_hsv_enabled.get()

            if hasattr(self, "h_l_s"):
                lower = [
                    int(self.h_l_s.get()),
                    int(self.s_l_s.get()),
                    int(self.v_l_s.get()),
                ]
                upper = [
                    int(self.h_u_s.get()),
                    int(self.s_u_s.get()),
                    int(self.v_u_s.get()),
                ]
                self.cfg["hsv"]["lower"] = lower
                self.cfg["hsv"]["upper"] = upper

            if hasattr(self, "morph_k_s"):
                self.cfg["hsv"]["morph_kernel"] = float(self.morph_k_s.get())
            if hasattr(self, "min_area_s"):
                self.cfg["hsv"]["min_area"] = float(self.min_area_s.get())

            self._save_config()
            self.status_var.set("Applied detection settings")
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _apply_trigger_settings(self):
        """Apply trigger settings"""
        try:
            if not hasattr(self.cfg, "actions"):
                self.cfg["actions"] = {}

            self.cfg["actions"]["trigger_enabled"] = self.var_trg.get()
            if hasattr(self, "tdelay_s"):
                self.cfg["actions"]["trigger_delay_ms"] = float(self.tdelay_s.get())
            if hasattr(self, "tcd_s"):
                self.cfg["actions"]["trigger_cooldown"] = float(self.tcd_s.get())

            self._save_config()
            self.status_var.set("Applied trigger settings")
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _apply_advance_settings(self):
        """Apply advanced settings"""
        try:
            if hasattr(self, "shot_duration_s"):
                self.cfg["SHOT_DURATION"] = float(self.shot_duration_s.get())
            if hasattr(self, "offset_x_s"):
                self.cfg["offsetX"] = float(self.offset_x_s.get())
            if hasattr(self, "offset_y_s"):
                self.cfg["offsetY"] = float(self.offset_y_s.get())
            if hasattr(self, "normal_x_speed_s"):
                self.cfg["normal_x_speed"] = float(self.normal_x_speed_s.get())
            if hasattr(self, "normal_y_speed_s"):
                self.cfg["normal_y_speed"] = float(self.normal_y_speed_s.get())

            self._save_config()
            self.status_var.set("Applied advanced settings")
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _save_config(self):
        """Save config to file"""
        try:
            cfg_path = os.path.join(
                os.path.dirname(__file__), "configs", "default.json"
            )
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def _toggle_start_stop(self):
        """Toggle Start/Stop with auto viewer launch"""
        if not self.is_running:
            # Start UDP streaming
            if self.viewer.start():
                self.is_running = True
                self.control_btn.configure(
                    text="⏹️ Stop", fg_color="red", hover_color="darkred"
                )
                self.status_var.set("Status: Running")

                # Auto-launch external viewer
                self._launch_viewer()
            else:
                self.status_var.set("Status: Failed to start")
        else:
            # Stop UDP streaming and close viewer
            self.viewer.stop()
            self.is_running = False
            self.control_btn.configure(
                text="🚀 Start",
                fg_color=["#3B8ED0", "#1F6AA5"],
                hover_color=["#36719F", "#144870"],
            )
            self.status_var.set("Status: Stopped")

            # Close external viewer windows
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:
                pass

    def _apply_port(self):
        """Apply new port setting"""
        try:
            new_port = int(self.port_var.get())
            if new_port != self.viewer.port:
                was_running = self.viewer.started
                if was_running:
                    self.viewer.stop()
                self.viewer = SimpleUdpViewer(
                    "0.0.0.0", new_port, self.viewer.rcvbuf_mb
                )
                if was_running:
                    self.viewer.start()
                self.status_var.set(f"Port changed to {new_port}")
        except ValueError:
            self.status_var.set("Invalid port number")

    def _launch_viewer(self):
        """Launch integrated viewer with OpenCV display"""
        try:
            # Create OpenCV window for integrated viewer
            cv2.namedWindow("AimVal v5 - Integrated Viewer", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("AimVal v5 - Integrated Viewer", 800, 600)
            cv2.moveWindow("AimVal v5 - Integrated Viewer", 100, 100)
            self.status_var.set("Integrated viewer window created")
            self.viewer_window_active = True
        except Exception as e:
            self.status_var.set(f"Viewer launch failed: {e}")
            self.viewer_window_active = False

    def _tick(self):
        try:
            if self.viewer.started:
                rt_fps, avg_fps = self.viewer.get_fps()
                self.fps_var.set(f"FPS: {rt_fps:.1f} ({avg_fps:.1f})")

                # Display frame in integrated viewer window
                if self.viewer_window_active:
                    frame = self.viewer.get_latest_frame()
                    if frame is not None:
                        # Add overlay information
                        h, w = frame.shape[:2]
                        cv2.rectangle(frame, (10, 10), (w-10, h-10), (0, 255, 0), 2)
                        
                        # Add FPS and status info
                        cv2.putText(frame, f"FPS: {rt_fps:.1f} ({avg_fps:.1f})", (20, 40), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        cv2.putText(frame, f"Detection: {'ON' if self.viewer.detection_enabled else 'OFF'}", (20, 80), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                        cv2.putText(frame, f"Aim: {'ON' if self.viewer.aim_enabled else 'OFF'}", (20, 110), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                        cv2.putText(frame, f"Trigger: {'ON' if self.viewer.trigger_enabled else 'OFF'}", (20, 140), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                        
                        # Display frame
                        try:
                            cv2.imshow("AimVal v5 - Integrated Viewer", frame)
                            if cv2.waitKey(1) & 0xFF == ord('q'):
                                self.viewer_window_active = False
                                cv2.destroyWindow("AimVal v5 - Integrated Viewer")
                        except cv2.error:
                            self.viewer_window_active = False

                # Update button state if needed
                if not self.is_running:
                    self.is_running = True
                    self.control_btn.configure(
                        text="⏹️ Stop", fg_color="red", hover_color="darkred"
                    )
            else:
                # Update button state if needed
                if self.is_running:
                    self.is_running = False
                    self.control_btn.configure(
                        text="🚀 Start",
                        fg_color=["#3B8ED0", "#1F6AA5"],
                        hover_color=["#36719F", "#144870"],
                    )

        except Exception:
            pass
        self.after(100, self._tick)

    # AI Control Methods
    def _toggle_detection(self):
        """Toggle detection on/off"""
        self.viewer.detection_enabled = not self.viewer.detection_enabled
        self.status_var.set(f"Detection: {'ON' if self.viewer.detection_enabled else 'OFF'}")
    
    def _toggle_aim(self):
        """Toggle aim on/off"""
        self.viewer.aim_enabled = not self.viewer.aim_enabled
        self.status_var.set(f"Aim: {'ON' if self.viewer.aim_enabled else 'OFF'}")
    
    def _toggle_trigger(self):
        """Toggle trigger on/off"""
        self.viewer.trigger_enabled = not self.viewer.trigger_enabled
        self.status_var.set(f"Trigger: {'ON' if self.viewer.trigger_enabled else 'OFF'}")

    def on_closing(self):
        self.viewer.stop()
        # Close OpenCV windows
        if self.viewer_window_active:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
