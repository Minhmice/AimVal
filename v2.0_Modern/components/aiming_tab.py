"""Aiming tab component with mode selection and settings."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class AimingTabComponent:
    """Aiming tab component for aim assist mode and settings."""
    
    def __init__(self, parent, config, widget_vars, callbacks):
        self.config = config
        self.widget_vars = widget_vars
        self.callbacks = callbacks
        
        # Mode selection
        self._create_mode_section(parent)
        
        # Dynamic frame container for mode-specific settings
        self.dynamic_frame_container = ttk.Frame(parent)
        self.dynamic_frame_container.pack(fill=X, pady=0, padx=0)
        
        # Create mode-specific frames
        self._create_mode_frames()
        
        # Common settings
        self._create_common_section(parent)
    
    def _create_mode_section(self, parent):
        """Create aim assist mode selection section."""
        mode_frame = ttk.LabelFrame(parent, text="Aim Assist Mode", padding=8)
        mode_frame.pack(fill=X, pady=5, padx=5)
        
        self.aim_mode_var = tk.StringVar(value=self.config.get("AIM_MODE"))
        self.widget_vars["AIM_MODE"] = self.aim_mode_var
        
        aim_combo = ttk.Combobox(
            mode_frame,
            textvariable=self.aim_mode_var,
            values=["Classic", "WindMouse", "Hybrid"],
            state="readonly",
        )
        aim_combo.pack(fill=X, expand=YES, pady=(0, 2))
        aim_combo.bind("<<ComboboxSelected>>", self.callbacks['on_aim_mode_change'])
    
    def _create_mode_frames(self):
        """Create mode-specific frames."""
        # Classic mode frame
        self.classic_aim_frame = ttk.Frame(self.dynamic_frame_container)
        self._create_classic_section()
        
        # WindMouse mode frame
        self.windmouse_aim_frame = ttk.Frame(self.dynamic_frame_container)
        self._create_windmouse_section()
        
        # Hybrid mode frame
        self.hybrid_aim_frame = ttk.Frame(self.dynamic_frame_container)
        self._create_hybrid_section()
    
    def _create_classic_section(self):
        """Create Classic mode settings."""
        # Acquiring settings
        classic_acquiring_frame = ttk.LabelFrame(
            self.classic_aim_frame, text="Aim Assist (Acquiring Target)", padding=8
        )
        classic_acquiring_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(classic_acquiring_frame, "AIM_ACQUIRING_SPEED", "Acquire Speed", 0.01, 10.0, is_float=True)
        self._create_slider(classic_acquiring_frame, "AIM_ACQUIRING_SMOOTHNESS", "Acquire Smooth", 0.01, 10.0, is_float=True)
        
        # Tracking settings
        classic_tracking_frame = ttk.LabelFrame(
            self.classic_aim_frame, text="Aim Assist (On Target)", padding=8
        )
        classic_tracking_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(classic_tracking_frame, "AIM_TRACKING_SPEED", "Track Speed", 0.01, 10.0, is_float=True)
        self._create_slider(classic_tracking_frame, "AIM_TRACKING_SMOOTHNESS", "Track Smooth", 0.01, 10.0, is_float=True)
        
        # Mouse Speed Controls
        mouse_speed_frame = ttk.LabelFrame(
            self.classic_aim_frame, text="Mouse Speed", padding=8
        )
        mouse_speed_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(mouse_speed_frame, "MOUSE_SPEED_MULTIPLIER", "Speed x", 0.5, 5.0, is_float=True)
        
        # Ease settings
        ease_frame = ttk.Frame(mouse_speed_frame)
        ease_frame.pack(fill=X, pady=2)
        
        self._create_slider(ease_frame, "EASE_OUT_FACTOR", "Ease Out", 0.0, 1.0, is_float=True)
        self._create_slider(ease_frame, "SMOOTHNESS_FACTOR", "Smoothness", 0.0, 1.0, is_float=True)
    
    def _create_windmouse_section(self):
        """Create WindMouse mode settings."""
        windmouse_settings_frame = ttk.LabelFrame(
            self.windmouse_aim_frame,
            text="WindMouse Settings (Full Movement)",
            padding=8,
        )
        windmouse_settings_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_G", "Gravity", 3.0, 20.0, is_float=True)
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_W", "Wind", 0.0, 15.0, is_float=True)
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_M", "Mass", 0.1, 5.0, is_float=True)
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_MAX_STEP", "Max Step", 0.1, 25.0, is_float=True)
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_TARGET_AREA", "Target Area", 0.1, 1.0, is_float=True)
        self._create_slider(windmouse_settings_frame, "WINDMOUSE_EASE_OUT", "Ease Out", 0.0, 1.0, is_float=True)
    
    def _create_hybrid_section(self):
        """Create Hybrid mode settings."""
        # WindMouse settings for hybrid
        hybrid_windmouse_frame = ttk.LabelFrame(
            self.hybrid_aim_frame, text="WindMouse (Flick Settings)", padding=8
        )
        hybrid_windmouse_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_G", "Gravity", 3.0, 20.0, is_float=True)
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_W", "Wind", 0.0, 15.0, is_float=True)
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_M", "Mass", 0.1, 5.0, is_float=True)
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_MAX_STEP", "Max Step", 0.1, 25.0, is_float=True)
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_TARGET_AREA", "Target Area", 0.1, 1.0, is_float=True)
        self._create_slider(hybrid_windmouse_frame, "WINDMOUSE_EASE_OUT", "Ease Out", 0.0, 1.0, is_float=True)
        
        # Classic settings for hybrid
        hybrid_tracking_frame = ttk.LabelFrame(
            self.hybrid_aim_frame, text="Classic (Tracking Settings)", padding=8
        )
        hybrid_tracking_frame.pack(fill=X, pady=2, padx=2)
        
        self._create_slider(hybrid_tracking_frame, "AIM_TRACKING_SPEED", "Track Speed", 0.01, 10.0, is_float=True)
        self._create_slider(hybrid_tracking_frame, "AIM_TRACKING_SMOOTHNESS", "Track Smooth", 0.01, 10.0, is_float=True)
        self._create_slider(hybrid_tracking_frame, "MOUSE_SPEED_MULTIPLIER", "Speed x", 0.5, 5.0, is_float=True)
        self._create_slider(hybrid_tracking_frame, "EASE_OUT_FACTOR", "Ease Out", 0.0, 1.0, is_float=True)
        self._create_slider(hybrid_tracking_frame, "SMOOTHNESS_FACTOR", "Smoothness", 0.0, 1.0, is_float=True)
    
    def _create_common_section(self, parent):
        """Create common aim settings section."""
        common_frame = ttk.LabelFrame(parent, text="Common Aim Settings", padding=8)
        common_frame.pack(fill=X, pady=5, padx=5)
        
        self._create_slider(common_frame, "AIM_ASSIST_RANGE", "Range (px)", 10, 100)
        self._create_slider(common_frame, "AIM_ASSIST_DELAY", "Aim Delay (s)", 0.0, 0.5, is_float=True)
        self._create_slider(common_frame, "DEADZONE", "Deadzone (px)", 1, 12)
        
        # Headshot mode toggle
        headshot_var = tk.BooleanVar(value=self.config.get("AIM_HEADSHOT_MODE"))
        self.widget_vars["AIM_HEADSHOT_MODE"] = headshot_var
        
        ttk.Checkbutton(
            common_frame,
            text="Headshot Mode",
            variable=headshot_var,
            bootstyle="round-toggle",
            command=lambda v=headshot_var: self.config.set("AIM_HEADSHOT_MODE", v.get()),
        ).pack(anchor=W, pady=(5, 5))
        
        self._create_slider(common_frame, "HEADSHOT_OFFSET_PERCENT", "Head %", 5, 30)
    
    def _create_slider(self, parent, key, text, from_, to, is_float=False):
        """Create a labeled slider with +/- nudge buttons bound to a config key."""
        container = ttk.Frame(parent)
        container.pack(fill=X, expand=YES, pady=2)
        
        # Responsive label width
        label_width = 10 if len(text) <= 8 else 12
        ttk.Label(container, text=text, width=label_width).pack(side=LEFT, padx=(0, 2))
        
        var = self.widget_vars.get(key)
        if not var:
            value = self.config.get(key)
            var = tk.DoubleVar(value=value) if is_float else tk.IntVar(value=value)
            self.widget_vars[key] = var
        
        val_label = ttk.Label(
            container, text=f"{var.get():.3f}" if is_float else str(var.get()), width=5
        )
        val_label.pack(side=RIGHT, padx=(2, 0))
        
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
        ).pack(side=RIGHT, fill=X, expand=YES, padx=2)
        
        ttk.Button(
            container,
            text="-",
            width=2,
            bootstyle=SECONDARY,
            command=lambda v=var, s=-(0.01 if is_float else 1): btn_cmd(v, s),
        ).pack(side=RIGHT)
        
        # Update value label when slider changes
        def update_label(*args):
            val_label.config(text=f"{var.get():.3f}" if is_float else str(var.get()))
        
        var.trace_add("write", update_label)
    
    def show_mode_frame(self, mode):
        """Show the appropriate mode frame."""
        # Hide all frames first
        for frame in [self.classic_aim_frame, self.windmouse_aim_frame, self.hybrid_aim_frame]:
            frame.pack_forget()
        
        # Show selected frame
        if mode == "Classic":
            self.classic_aim_frame.pack(fill=X)
        elif mode == "WindMouse":
            self.windmouse_aim_frame.pack(fill=X)
        elif mode == "Hybrid":
            self.hybrid_aim_frame.pack(fill=X)
