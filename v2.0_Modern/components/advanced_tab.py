"""Advanced tab component with fire control and mouse button settings."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class AdvancedTabComponent:
    """Advanced tab component for trigger durations, delays, and mouse button settings."""
    
    def __init__(self, parent, config, widget_vars, callbacks):
        self.config = config
        self.widget_vars = widget_vars
        self.callbacks = callbacks
        
        # Fire Control section
        self._create_fire_control_section(parent)
        
        # Mouse Button Settings section
        self._create_mouse_button_section(parent)
    
    def _create_fire_control_section(self, parent):
        """Create fire control section."""
        fire_control_frame = ttk.LabelFrame(parent, text="Fire Control", padding=8)
        fire_control_frame.pack(fill=X, pady=5, padx=5)
        
        self._create_slider(
            fire_control_frame, "SHOT_DURATION", "Duration", 0.25, 0.6, is_float=True
        )
        self._create_slider(
            fire_control_frame, "SHOT_COOLDOWN", "Cooldown", 0.25, 0.6, is_float=True
        )
        self._create_slider(
            fire_control_frame, "TRIGGERBOT_DELAY_MS", "Trig. Delay", 0, 120
        )
    
    def _create_mouse_button_section(self, parent):
        """Create mouse button settings section."""
        mouse_button_frame = ttk.LabelFrame(parent, text="Mouse Buttons", padding=8)
        mouse_button_frame.pack(fill=X, pady=5, padx=5)
        
        # Mouse 1 button
        mouse1_frame = ttk.Frame(mouse_button_frame)
        mouse1_frame.pack(fill=X, pady=2)
        
        ttk.Label(mouse1_frame, text="Mouse 1", width=12).pack(side=LEFT)
        
        self.mouse1_var = tk.StringVar(value=self.config.get("MOUSE_1_BUTTON"))
        self.widget_vars["MOUSE_1_BUTTON"] = self.mouse1_var
        
        ttk.Combobox(
            mouse1_frame,
            textvariable=self.mouse1_var,
            values=["left", "right", "mid", "mouse4", "mouse5", "disable"],
            state="readonly",
            width=8,
        ).pack(side=LEFT, padx=(0, 5))
        
        self.mouse1_mode_var = tk.StringVar(value=self.config.get("MOUSE_1_MODE"))
        self.widget_vars["MOUSE_1_MODE"] = self.mouse1_mode_var
        
        ttk.Combobox(
            mouse1_frame,
            textvariable=self.mouse1_mode_var,
            values=["toggle", "hold"],
            state="readonly",
            width=8,
        ).pack(side=LEFT, padx=(0, 10))
        
        # Mouse 2 button
        mouse2_frame = ttk.Frame(mouse_button_frame)
        mouse2_frame.pack(fill=X, pady=2)
        
        ttk.Label(mouse2_frame, text="Mouse 2", width=12).pack(side=LEFT)
        
        self.mouse2_var = tk.StringVar(value=self.config.get("MOUSE_2_BUTTON"))
        self.widget_vars["MOUSE_2_BUTTON"] = self.mouse2_var
        
        ttk.Combobox(
            mouse2_frame,
            textvariable=self.mouse2_var,
            values=["left", "right", "mid", "mouse4", "mouse5", "disable"],
            state="readonly",
            width=8,
        ).pack(side=LEFT, padx=(0, 5))
        
        self.mouse2_mode_var = tk.StringVar(value=self.config.get("MOUSE_2_MODE"))
        self.widget_vars["MOUSE_2_MODE"] = self.mouse2_mode_var
        
        ttk.Combobox(
            mouse2_frame,
            textvariable=self.mouse2_mode_var,
            values=["toggle", "hold"],
            state="readonly",
            width=8,
        ).pack(side=LEFT, padx=(0, 10))
        
        # Bind change events
        self.mouse1_var.trace_add(
            "write",
            lambda *args: self.config.set("MOUSE_1_BUTTON", self.mouse1_var.get())
        )
        self.mouse1_mode_var.trace_add(
            "write",
            lambda *args: self.config.set("MOUSE_1_MODE", self.mouse1_mode_var.get())
        )
        self.mouse2_var.trace_add(
            "write",
            lambda *args: self.config.set("MOUSE_2_BUTTON", self.mouse2_var.get())
        )
        self.mouse2_mode_var.trace_add(
            "write",
            lambda *args: self.config.set("MOUSE_2_MODE", self.mouse2_mode_var.get())
        )
    
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
