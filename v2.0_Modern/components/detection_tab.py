"""Detection tab component with morphology and color settings."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class DetectionTabComponent:
    """Detection tab component for morphology params and color profile selection."""
    
    def __init__(self, parent, config, widget_vars, callbacks):
        self.config = config
        self.widget_vars = widget_vars
        self.callbacks = callbacks
        
        # Create single-column container (all config stacks vertically)
        main_container = ttk.Frame(parent)
        main_container.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Create sections in one column
        self._create_basic_detection_section(main_container)
        self._create_noise_processing_section(main_container)
        self._create_verification_section(main_container)
        self._create_color_profile_section(main_container)
    
    def _create_basic_detection_section(self, parent):
        """Create basic detection section."""
        basic_detection_frame = ttk.LabelFrame(
            parent, text="Basic Detection", padding=8
        )
        basic_detection_frame.pack(fill=X, pady=(0, 5))
        
        self._create_slider(
            basic_detection_frame, "MIN_CONTOUR_AREA", "Min Size", 10, 1000
        )
    
    def _create_noise_processing_section(self, parent):
        """Create noise processing section with responsive grid."""
        noise_frame = ttk.LabelFrame(parent, text="Noise Processing", padding=8)
        noise_frame.pack(fill=X, pady=(0, 5))
        
        # Create 2x3 grid for noise sliders
        noise_grid = ttk.Frame(noise_frame)
        noise_grid.pack(fill=X, expand=YES)
        
        # Row 1: Dilate settings
        dilate_row = ttk.Frame(noise_grid)
        dilate_row.pack(fill=X, pady=2)
        self._create_slider(dilate_row, "DILATE_ITERATIONS", "Dilate Iter", 0.25, 6, is_float=True)
        self._create_slider(dilate_row, "DILATE_KERNEL_WIDTH", "Dilate K-W", 0.25, 10, is_float=True)
        
        # Row 2: Dilate height + Erode settings
        dilate_erode_row = ttk.Frame(noise_grid)
        dilate_erode_row.pack(fill=X, pady=2)
        self._create_slider(dilate_erode_row, "DILATE_KERNEL_HEIGHT", "Dilate K-H", 0.25, 10, is_float=True)
        self._create_slider(dilate_erode_row, "ERODE_ITERATIONS", "Erode Iter", 0.25, 5, is_float=True)
        
        # Row 3: Erode kernel settings
        erode_row = ttk.Frame(noise_grid)
        erode_row.pack(fill=X, pady=2)
        self._create_slider(erode_row, "ERODE_KERNEL_WIDTH", "Erode K-W", 0.25, 10, is_float=True)
        self._create_slider(erode_row, "ERODE_KERNEL_HEIGHT", "Erode K-H", 0.25, 10, is_float=True)
    
    def _create_verification_section(self, parent):
        """Create verification (sandwich) section."""
        verification_frame = ttk.LabelFrame(
            parent, text="Verification (Sandwich)", padding=8
        )
        verification_frame.pack(fill=X, pady=(0, 5))
        
        self._create_slider(
            verification_frame, "SANDWICH_CHECK_HEIGHT", "Sandwich H", 1, 50
        )
        self._create_slider(
            verification_frame, "SANDWICH_CHECK_SCAN_WIDTH", "Sandwich W", 1, 10
        )
    
    def _create_color_profile_section(self, parent):
        """Create color profile section."""
        color_frame = ttk.LabelFrame(parent, text="Color Profile (Enemy)", padding=8)
        color_frame.pack(fill=X, pady=(0, 5))
        
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
        color_combo.bind("<<ComboboxSelected>>", self.callbacks['on_color_profile_change'])
        
        # Color controls in responsive grid
        color_grid = ttk.Frame(color_frame)
        color_grid.pack(fill=X, expand=YES)
        
        # Lower color row
        lower_frame = ttk.Frame(color_grid)
        lower_frame.pack(fill=X, pady=2)
        ttk.Label(lower_frame, text="Lower", width=8).pack(side=LEFT, padx=(0, 5))
        self._create_spinbox(lower_frame, "LOWER_YELLOW_H", 0, 179)
        self._create_spinbox(lower_frame, "LOWER_YELLOW_S", 0, 255)
        self._create_spinbox(lower_frame, "LOWER_YELLOW_V", 0, 255)
        
        # Upper color row
        upper_frame = ttk.Frame(color_grid)
        upper_frame.pack(fill=X, pady=2)
        ttk.Label(upper_frame, text="Upper", width=8).pack(side=LEFT, padx=(0, 5))
        self._create_spinbox(upper_frame, "UPPER_YELLOW_H", 0, 179)
        self._create_spinbox(upper_frame, "UPPER_YELLOW_S", 0, 255)
        self._create_spinbox(upper_frame, "UPPER_YELLOW_V", 0, 255)
    
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
    
    def _create_spinbox(self, parent, key, from_, to):
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
