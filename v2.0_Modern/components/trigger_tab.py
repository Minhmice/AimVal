"""Trigger Bot tab component with comprehensive configuration options."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class TriggerTabComponent:
    """Comprehensive trigger bot tab with advanced features and configurations."""
    
    def __init__(self, parent, config, widget_vars, callbacks):
        self.config = config
        self.widget_vars = widget_vars
        self.callbacks = callbacks
        
        # Create main container with scrollable content
        self._create_scrollable_container(parent)
        
        # Create all sections
        self._create_basic_settings()
        self._create_advanced_modes()
        self._create_weapon_settings()
        self._create_accuracy_settings()
        self._create_target_settings()
        self._create_compensation_settings()
        self._create_safety_settings()
        self._create_feedback_settings()
        self._create_debug_settings()
        self._create_statistics_section()
    
    def _create_scrollable_container(self, parent):
        """Create scrollable container for the tab."""
        # Create canvas and scrollbar
        self.canvas = tk.Canvas(parent, highlightthickness=0, bg="#f0f0f0")
        self.scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        def configure_scroll_region(event=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
        self.scrollable_frame.bind("<Configure>", configure_scroll_region)
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Pack canvas and scrollbar
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.scrollbar.pack(side=RIGHT, fill=Y)
        
        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        def _bind_mousewheel(event):
            self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        def _unbind_mousewheel(event):
            self.canvas.unbind_all("<MouseWheel>")
        
        self.canvas.bind("<Enter>", _bind_mousewheel)
        self.canvas.bind("<Leave>", _unbind_mousewheel)
        
        # Configure grid weights
        self.scrollable_frame.grid_columnconfigure(0, weight=1)
    
    def _create_basic_settings(self):
        """Create basic trigger bot settings section."""
        basic_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Basic Trigger Settings", padding=8
        )
        basic_frame.pack(fill=X, pady=5, padx=5)
        
        # Enable/Disable trigger bot
        enable_frame = ttk.Frame(basic_frame)
        enable_frame.pack(fill=X, pady=2)
        
        self.trigger_enabled_var = tk.BooleanVar(
            value=self.config.get("TRIGGERBOT_ENABLED")
        )
        self.widget_vars["TRIGGERBOT_ENABLED"] = self.trigger_enabled_var
        
        ttk.Checkbutton(
            enable_frame,
            text="Enable Trigger Bot",
            variable=self.trigger_enabled_var,
            bootstyle="round-toggle",
            command=self._on_trigger_enabled_change,
        ).pack(side=LEFT)
        
        # Basic timing controls
        timing_frame = ttk.Frame(basic_frame)
        timing_frame.pack(fill=X, pady=2)
        
        self._create_slider(timing_frame, "TRIGGERBOT_DELAY_MS", "Trigger Delay (ms)", 0, 100)
        self._create_slider(timing_frame, "SHOT_DURATION", "Shot Duration (s)", 0.01, 0.5, is_float=True)
        self._create_slider(timing_frame, "SHOT_COOLDOWN", "Shot Cooldown (s)", 0.01, 0.5, is_float=True)
    
    def _create_advanced_modes(self):
        """Create advanced trigger modes section."""
        modes_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Advanced Trigger Modes", padding=8
        )
        modes_frame.pack(fill=X, pady=5, padx=5)
        
        # Trigger mode selection
        mode_frame = ttk.Frame(modes_frame)
        mode_frame.pack(fill=X, pady=2)
        
        ttk.Label(mode_frame, text="Trigger Mode:", width=15).pack(side=LEFT)
        
        self.trigger_mode_var = tk.StringVar(value=self.config.get("TRIGGER_MODE"))
        self.widget_vars["TRIGGER_MODE"] = self.trigger_mode_var
        
        mode_combo = ttk.Combobox(
            mode_frame,
            textvariable=self.trigger_mode_var,
            values=["instant", "burst", "adaptive"],
            state="readonly",
            width=15,
        )
        mode_combo.pack(side=LEFT, padx=(5, 0))
        mode_combo.bind("<<ComboboxSelected>>", self._on_trigger_mode_change)
        
        # Burst mode settings
        burst_frame = ttk.LabelFrame(modes_frame, text="Burst Mode Settings", padding=5)
        burst_frame.pack(fill=X, pady=2)
        
        self._create_slider(burst_frame, "TRIGGER_BURST_COUNT", "Burst Count", 1, 10)
        self._create_slider(burst_frame, "TRIGGER_BURST_DELAY", "Burst Delay (s)", 0.01, 0.2, is_float=True)
        
        # Adaptive mode settings
        adaptive_frame = ttk.LabelFrame(modes_frame, text="Adaptive Mode Settings", padding=5)
        adaptive_frame.pack(fill=X, pady=2)
        
        self.adaptive_delay_var = tk.BooleanVar(value=self.config.get("TRIGGER_ADAPTIVE_DELAY"))
        self.widget_vars["TRIGGER_ADAPTIVE_DELAY"] = self.adaptive_delay_var
        
        ttk.Checkbutton(
            adaptive_frame,
            text="Enable Adaptive Delay",
            variable=self.adaptive_delay_var,
            command=self._on_adaptive_delay_change,
        ).pack(anchor=W)
        
        self._create_slider(adaptive_frame, "TRIGGER_SIZE_FACTOR", "Size Factor", 0.1, 2.0, is_float=True)
        self._create_slider(adaptive_frame, "TRIGGER_DISTANCE_FACTOR", "Distance Factor", 0.1, 2.0, is_float=True)
        self._create_slider(adaptive_frame, "TRIGGER_MAX_DELAY_MS", "Max Delay (ms)", 10, 200)
    
    def _create_weapon_settings(self):
        """Create weapon-specific settings section."""
        weapon_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Weapon Settings", padding=8
        )
        weapon_frame.pack(fill=X, pady=5, padx=5)
        
        # Weapon mode selection
        weapon_mode_frame = ttk.Frame(weapon_frame)
        weapon_mode_frame.pack(fill=X, pady=2)
        
        ttk.Label(weapon_mode_frame, text="Weapon Mode:", width=15).pack(side=LEFT)
        
        self.weapon_mode_var = tk.StringVar(value=self.config.get("TRIGGER_WEAPON_MODE"))
        self.widget_vars["TRIGGER_WEAPON_MODE"] = self.weapon_mode_var
        
        weapon_combo = ttk.Combobox(
            weapon_mode_frame,
            textvariable=self.weapon_mode_var,
            values=["auto", "single", "burst", "spray"],
            state="readonly",
            width=15,
        )
        weapon_combo.pack(side=LEFT, padx=(5, 0))
        weapon_combo.bind("<<ComboboxSelected>>", self._on_weapon_mode_change)
        
        # Weapon timing presets
        timing_presets_frame = ttk.LabelFrame(weapon_frame, text="Weapon Timing Presets", padding=5)
        timing_presets_frame.pack(fill=X, pady=2)
        
        # Create grid for weapon settings
        weapons = ["auto", "single", "burst", "spray"]
        for i, weapon in enumerate(weapons):
            row = i // 2
            col = (i % 2) * 2
            
            ttk.Label(timing_presets_frame, text=weapon.title(), width=8).grid(row=row, column=col, padx=2, pady=2)
            
            # Delay setting
            delay_key = f"TRIGGER_WEAPON_DELAY_{weapon.upper()}"
            self._create_slider(timing_presets_frame, delay_key, "Delay", 0.01, 0.2, is_float=True, 
                              grid=True, row=row, column=col+1)
    
    def _create_accuracy_settings(self):
        """Create accuracy and precision settings section."""
        accuracy_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Accuracy & Precision", padding=8
        )
        accuracy_frame.pack(fill=X, pady=5, padx=5)
        
        # Accuracy mode
        acc_mode_frame = ttk.Frame(accuracy_frame)
        acc_mode_frame.pack(fill=X, pady=2)
        
        ttk.Label(acc_mode_frame, text="Accuracy Mode:", width=15).pack(side=LEFT)
        
        self.accuracy_mode_var = tk.StringVar(value=self.config.get("TRIGGER_ACCURACY_MODE"))
        self.widget_vars["TRIGGER_ACCURACY_MODE"] = self.accuracy_mode_var
        
        acc_combo = ttk.Combobox(
            acc_mode_frame,
            textvariable=self.accuracy_mode_var,
            values=["normal", "high", "low"],
            state="readonly",
            width=15,
        )
        acc_combo.pack(side=LEFT, padx=(5, 0))
        
        # Random delay settings
        random_frame = ttk.LabelFrame(accuracy_frame, text="Randomization", padding=5)
        random_frame.pack(fill=X, pady=2)
        
        self.random_delay_var = tk.BooleanVar(value=self.config.get("TRIGGER_RANDOM_DELAY"))
        self.widget_vars["TRIGGER_RANDOM_DELAY"] = self.random_delay_var
        
        ttk.Checkbutton(
            random_frame,
            text="Enable Random Delay",
            variable=self.random_delay_var,
        ).pack(anchor=W)
        
        self._create_slider(random_frame, "TRIGGER_RANDOM_MIN", "Min Random (ms)", 0, 50)
        self._create_slider(random_frame, "TRIGGER_RANDOM_MAX", "Max Random (ms)", 0, 100)
        
        # Smoothing settings
        smoothing_frame = ttk.LabelFrame(accuracy_frame, text="Smoothing", padding=5)
        smoothing_frame.pack(fill=X, pady=2)
        
        self.smoothing_var = tk.BooleanVar(value=self.config.get("TRIGGER_SMOOTHING"))
        self.widget_vars["TRIGGER_SMOOTHING"] = self.smoothing_var
        
        ttk.Checkbutton(
            smoothing_frame,
            text="Enable Smoothing",
            variable=self.smoothing_var,
        ).pack(anchor=W)
        
        self._create_slider(smoothing_frame, "TRIGGER_SMOOTHING_FACTOR", "Smoothing Factor", 0.1, 1.0, is_float=True)
    
    def _create_target_settings(self):
        """Create target detection and filtering settings section."""
        target_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Target Detection & Filtering", padding=8
        )
        target_frame.pack(fill=X, pady=5, padx=5)
        
        # Target priority
        priority_frame = ttk.Frame(target_frame)
        priority_frame.pack(fill=X, pady=2)
        
        ttk.Label(priority_frame, text="Target Priority:", width=15).pack(side=LEFT)
        
        self.target_priority_var = tk.StringVar(value=self.config.get("TRIGGER_TARGET_PRIORITY"))
        self.widget_vars["TRIGGER_TARGET_PRIORITY"] = self.target_priority_var
        
        priority_combo = ttk.Combobox(
            priority_frame,
            textvariable=self.target_priority_var,
            values=["center", "closest", "largest"],
            state="readonly",
            width=15,
        )
        priority_combo.pack(side=LEFT, padx=(5, 0))
        
        # Target filtering
        filter_frame = ttk.LabelFrame(target_frame, text="Target Filtering", padding=5)
        filter_frame.pack(fill=X, pady=2)
        
        self.target_filter_var = tk.BooleanVar(value=self.config.get("TRIGGER_TARGET_FILTER"))
        self.widget_vars["TRIGGER_TARGET_FILTER"] = self.target_filter_var
        
        ttk.Checkbutton(
            filter_frame,
            text="Enable Target Filtering",
            variable=self.target_filter_var,
        ).pack(anchor=W)
        
        self._create_slider(filter_frame, "TRIGGER_MIN_TARGET_SIZE", "Min Target Size", 1, 50)
        self._create_slider(filter_frame, "TRIGGER_MAX_TARGET_SIZE", "Max Target Size", 10, 200)
        self._create_slider(filter_frame, "TRIGGER_TARGET_CONFIDENCE", "Target Confidence", 0.1, 1.0, is_float=True)
    
    def _create_compensation_settings(self):
        """Create movement compensation and prediction settings section."""
        comp_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Movement Compensation", padding=8
        )
        comp_frame.pack(fill=X, pady=5, padx=5)
        
        # Movement compensation
        movement_frame = ttk.LabelFrame(comp_frame, text="Movement Compensation", padding=5)
        movement_frame.pack(fill=X, pady=2)
        
        self.movement_comp_var = tk.BooleanVar(value=self.config.get("TRIGGER_MOVEMENT_COMPENSATION"))
        self.widget_vars["TRIGGER_MOVEMENT_COMPENSATION"] = self.movement_comp_var
        
        ttk.Checkbutton(
            movement_frame,
            text="Enable Movement Compensation",
            variable=self.movement_comp_var,
        ).pack(anchor=W)
        
        self._create_slider(movement_frame, "TRIGGER_MOVEMENT_THRESHOLD", "Movement Threshold", 1, 50)
        self._create_slider(movement_frame, "TRIGGER_MOVEMENT_FACTOR", "Movement Factor", 0.1, 1.0, is_float=True)
        
        # Prediction settings
        prediction_frame = ttk.LabelFrame(comp_frame, text="Target Prediction", padding=5)
        prediction_frame.pack(fill=X, pady=2)
        
        self.prediction_var = tk.BooleanVar(value=self.config.get("TRIGGER_PREDICTION"))
        self.widget_vars["TRIGGER_PREDICTION"] = self.prediction_var
        
        ttk.Checkbutton(
            prediction_frame,
            text="Enable Target Prediction",
            variable=self.prediction_var,
        ).pack(anchor=W)
        
        self._create_slider(prediction_frame, "TRIGGER_PREDICTION_TIME", "Prediction Time (s)", 0.01, 0.5, is_float=True)
        
        # Anti-pattern settings
        anti_pattern_frame = ttk.LabelFrame(comp_frame, text="Anti-Pattern Detection", padding=5)
        anti_pattern_frame.pack(fill=X, pady=2)
        
        self.anti_pattern_var = tk.BooleanVar(value=self.config.get("TRIGGER_ANTI_PATTERN"))
        self.widget_vars["TRIGGER_ANTI_PATTERN"] = self.anti_pattern_var
        
        ttk.Checkbutton(
            anti_pattern_frame,
            text="Enable Anti-Pattern Detection",
            variable=self.anti_pattern_var,
        ).pack(anchor=W)
        
        self._create_slider(anti_pattern_frame, "TRIGGER_ANTI_PATTERN_TIME", "Pattern Time (s)", 0.1, 2.0, is_float=True)
    
    def _create_safety_settings(self):
        """Create safety and health check settings section."""
        safety_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Safety & Health Checks", padding=8
        )
        safety_frame.pack(fill=X, pady=5, padx=5)
        
        # Health check
        health_frame = ttk.LabelFrame(safety_frame, text="Health Monitoring", padding=5)
        health_frame.pack(fill=X, pady=2)
        
        self.health_check_var = tk.BooleanVar(value=self.config.get("TRIGGER_HEALTH_CHECK"))
        self.widget_vars["TRIGGER_HEALTH_CHECK"] = self.health_check_var
        
        ttk.Checkbutton(
            health_frame,
            text="Enable Health Check",
            variable=self.health_check_var,
        ).pack(anchor=W)
        
        self._create_slider(health_frame, "TRIGGER_HEALTH_THRESHOLD", "Health Threshold", 0.1, 1.0, is_float=True)
        
        # Ammo check
        ammo_frame = ttk.LabelFrame(safety_frame, text="Ammo Monitoring", padding=5)
        ammo_frame.pack(fill=X, pady=2)
        
        self.ammo_check_var = tk.BooleanVar(value=self.config.get("TRIGGER_AMMO_CHECK"))
        self.widget_vars["TRIGGER_AMMO_CHECK"] = self.ammo_check_var
        
        ttk.Checkbutton(
            ammo_frame,
            text="Enable Ammo Check",
            variable=self.ammo_check_var,
        ).pack(anchor=W)
        
        self._create_slider(ammo_frame, "TRIGGER_AMMO_THRESHOLD", "Ammo Threshold", 1, 30)
    
    def _create_feedback_settings(self):
        """Create feedback and notification settings section."""
        feedback_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Feedback & Notifications", padding=8
        )
        feedback_frame.pack(fill=X, pady=5, padx=5)
        
        # Sound detection
        sound_frame = ttk.LabelFrame(feedback_frame, text="Sound Detection", padding=5)
        sound_frame.pack(fill=X, pady=2)
        
        self.sound_detection_var = tk.BooleanVar(value=self.config.get("TRIGGER_SOUND_DETECTION"))
        self.widget_vars["TRIGGER_SOUND_DETECTION"] = self.sound_detection_var
        
        ttk.Checkbutton(
            sound_frame,
            text="Enable Sound Detection",
            variable=self.sound_detection_var,
        ).pack(anchor=W)
        
        self._create_slider(sound_frame, "TRIGGER_SOUND_THRESHOLD", "Sound Threshold", 0.1, 1.0, is_float=True)
        
        # Vibration feedback
        vibration_frame = ttk.LabelFrame(feedback_frame, text="Vibration Feedback", padding=5)
        vibration_frame.pack(fill=X, pady=2)
        
        self.vibration_var = tk.BooleanVar(value=self.config.get("TRIGGER_VIBRATION_FEEDBACK"))
        self.widget_vars["TRIGGER_VIBRATION_FEEDBACK"] = self.vibration_var
        
        ttk.Checkbutton(
            vibration_frame,
            text="Enable Vibration Feedback",
            variable=self.vibration_var,
        ).pack(anchor=W)
        
        self._create_slider(vibration_frame, "TRIGGER_VIBRATION_INTENSITY", "Vibration Intensity", 0.1, 1.0, is_float=True)
    
    def _create_debug_settings(self):
        """Create debug and logging settings section."""
        debug_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Debug & Logging", padding=8
        )
        debug_frame.pack(fill=X, pady=5, padx=5)
        
        # Debug mode
        debug_mode_frame = ttk.Frame(debug_frame)
        debug_mode_frame.pack(fill=X, pady=2)
        
        self.debug_mode_var = tk.BooleanVar(value=self.config.get("TRIGGER_DEBUG_MODE"))
        self.widget_vars["TRIGGER_DEBUG_MODE"] = self.debug_mode_var
        
        ttk.Checkbutton(
            debug_mode_frame,
            text="Enable Debug Mode",
            variable=self.debug_mode_var,
        ).pack(side=LEFT)
        
        # Debug level
        ttk.Label(debug_mode_frame, text="Debug Level:", width=12).pack(side=LEFT, padx=(20, 5))
        
        self.debug_level_var = tk.StringVar(value=str(self.config.get("TRIGGER_DEBUG_LEVEL")))
        self.widget_vars["TRIGGER_DEBUG_LEVEL"] = self.debug_level_var
        
        debug_level_combo = ttk.Combobox(
            debug_mode_frame,
            textvariable=self.debug_level_var,
            values=["1", "2", "3"],
            state="readonly",
            width=5,
        )
        debug_level_combo.pack(side=LEFT)
        
        # Performance mode
        perf_frame = ttk.Frame(debug_frame)
        perf_frame.pack(fill=X, pady=2)
        
        self.performance_mode_var = tk.BooleanVar(value=self.config.get("TRIGGER_PERFORMANCE_MODE"))
        self.widget_vars["TRIGGER_PERFORMANCE_MODE"] = self.performance_mode_var
        
        ttk.Checkbutton(
            perf_frame,
            text="Enable Performance Mode",
            variable=self.performance_mode_var,
        ).pack(side=LEFT)
        
        self._create_slider(perf_frame, "TRIGGER_PERFORMANCE_THRESHOLD", "Performance Threshold", 0.1, 1.0, is_float=True)
    
    def _create_statistics_section(self):
        """Create statistics and monitoring section."""
        stats_frame = ttk.LabelFrame(
            self.scrollable_frame, text="Statistics & Monitoring", padding=8
        )
        stats_frame.pack(fill=X, pady=5, padx=5)
        
        # Statistics toggle
        stats_toggle_frame = ttk.Frame(stats_frame)
        stats_toggle_frame.pack(fill=X, pady=2)
        
        self.statistics_var = tk.BooleanVar(value=self.config.get("TRIGGER_STATISTICS"))
        self.widget_vars["TRIGGER_STATISTICS"] = self.statistics_var
        
        ttk.Checkbutton(
            stats_toggle_frame,
            text="Enable Statistics Collection",
            variable=self.statistics_var,
        ).pack(side=LEFT)
        
        # Statistics settings
        self._create_slider(stats_frame, "TRIGGER_STATS_WINDOW", "Stats Window (frames)", 10, 1000)
        
        # Statistics display (read-only)
        stats_display_frame = ttk.LabelFrame(stats_frame, text="Current Statistics", padding=5)
        stats_display_frame.pack(fill=X, pady=2)
        
        self.stats_text = tk.Text(stats_display_frame, height=6, width=50, state=tk.DISABLED)
        self.stats_text.pack(fill=X, pady=2)
        
        # Update statistics button
        ttk.Button(
            stats_display_frame,
            text="Update Statistics",
            command=self._update_statistics_display,
        ).pack(pady=2)
    
    def _create_slider(self, parent, key, text, from_, to, is_float=False, grid=False, row=0, column=0):
        """Create a labeled slider with +/- nudge buttons bound to a config key."""
        if grid:
            container = ttk.Frame(parent)
            container.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
        else:
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
    
    def _on_trigger_enabled_change(self):
        """Handle trigger bot enable/disable change."""
        enabled = self.trigger_enabled_var.get()
        self.config.set("TRIGGERBOT_ENABLED", enabled)
        print(f"Trigger bot {'enabled' if enabled else 'disabled'}")
    
    def _on_trigger_mode_change(self, event=None):
        """Handle trigger mode change."""
        mode = self.trigger_mode_var.get()
        self.config.set("TRIGGER_MODE", mode)
        print(f"Trigger mode changed to: {mode}")
    
    def _on_adaptive_delay_change(self):
        """Handle adaptive delay change."""
        enabled = self.adaptive_delay_var.get()
        self.config.set("TRIGGER_ADAPTIVE_DELAY", enabled)
        print(f"Adaptive delay {'enabled' if enabled else 'disabled'}")
    
    def _on_weapon_mode_change(self, event=None):
        """Handle weapon mode change."""
        mode = self.weapon_mode_var.get()
        self.config.set("TRIGGER_WEAPON_MODE", mode)
        print(f"Weapon mode changed to: {mode}")
    
    def _update_statistics_display(self):
        """Update the statistics display."""
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        
        # Sample statistics (replace with real data)
        stats_data = f"""Trigger Bot Statistics:
Shots Fired: 0
Hit Rate: 0.0%
Average Delay: {self.config.get('TRIGGERBOT_DELAY_MS')}ms
Current Mode: {self.config.get('TRIGGER_MODE')}
Weapon Mode: {self.config.get('TRIGGER_WEAPON_MODE')}
Accuracy Mode: {self.config.get('TRIGGER_ACCURACY_MODE')}
Target Priority: {self.config.get('TRIGGER_TARGET_PRIORITY')}
Status: {'Active' if self.config.get('TRIGGERBOT_ENABLED') else 'Inactive'}"""
        
        self.stats_text.insert(1.0, stats_data)
        self.stats_text.config(state=tk.DISABLED)
