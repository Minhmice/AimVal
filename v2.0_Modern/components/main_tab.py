"""Main tab component with config profile and core settings."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class MainTabComponent:
    """Main tab component for config profile and core settings."""
    
    def __init__(self, parent, config, widget_vars, callbacks):
        self.config = config
        self.widget_vars = widget_vars
        self.callbacks = callbacks
        
        # Config Profile section
        self._create_config_section(parent)
        
        # Core Settings section
        self._create_core_section(parent)
        
        # FOV section
        self._create_fov_section(parent)
    
    def _create_config_section(self, parent):
        """Create config profile section."""
        config_frame = ttk.LabelFrame(parent, text="Config Profile", padding=8)
        config_frame.pack(fill=X, pady=5, padx=5)
        
        self.config_entry_var = tk.StringVar(
            value=self.config.current_filepath.split('/')[-1] if self.config.current_filepath else "config.json"
        )
        self.config_entry = ttk.Entry(config_frame, textvariable=self.config_entry_var)
        self.config_entry.pack(side=LEFT, expand=YES, fill=X, padx=(0, 2))
        
        ttk.Button(
            config_frame, text="Save", command=self.callbacks['save_config']
        ).pack(side=LEFT, padx=(0, 2))
        
        ttk.Button(
            config_frame, text="Load", command=self.callbacks['load_config']
        ).pack(side=LEFT)
    
    def _create_core_section(self, parent):
        """Create core settings section."""
        core_frame = ttk.LabelFrame(parent, text="Core Settings", padding=8)
        core_frame.pack(fill=X, pady=5, padx=5)
        
        # FPS Limit slider
        self._create_slider(core_frame, "FPS_LIMIT", "FPS Limit", 100, 240)
    
    def _create_fov_section(self, parent):
        """Create FOV section."""
        fov_frame = ttk.LabelFrame(
            parent, text="Capture FOV (Restart Required)", padding=8
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
