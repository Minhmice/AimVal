"""Common UI controls and widgets."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class SliderControl:
    """Reusable slider control with +/- buttons and value display."""
    
    def __init__(self, parent, key, text, from_, to, config, widget_vars, is_float=False):
        self.config = config
        self.widget_vars = widget_vars
        self.key = key
        self.is_float = is_float
        
        # Create container
        self.container = ttk.Frame(parent)
        self.container.pack(fill=X, expand=YES, pady=2)
        
        # Label
        label_width = 10 if len(text) <= 8 else 12
        ttk.Label(self.container, text=text, width=label_width).pack(side=LEFT, padx=(0, 2))
        
        # Get or create variable
        self.var = self.widget_vars.get(key)
        if not self.var:
            value = self.config.get(key)
            self.var = tk.DoubleVar(value=value) if is_float else tk.IntVar(value=value)
            self.widget_vars[key] = self.var
        
        # Value label
        self.val_label = ttk.Label(
            self.container, 
            text=f"{self.var.get():.3f}" if is_float else str(self.var.get()), 
            width=5
        )
        self.val_label.pack(side=RIGHT, padx=(2, 0))
        
        # Buttons and slider
        self._create_buttons()
        self._create_slider(from_, to)
        
        # Bind variable changes
        self.var.trace_add("write", self._update_label)
    
    def _create_buttons(self):
        """Create +/- buttons."""
        def btn_cmd(s):
            self.var.set(round(self.var.get() + s, 3 if self.is_float else 0))
        
        ttk.Button(
            self.container,
            text="+",
            width=2,
            bootstyle=SECONDARY,
            command=lambda s=(0.01 if self.is_float else 1): btn_cmd(s),
        ).pack(side=RIGHT)
        
        ttk.Button(
            self.container,
            text="-",
            width=2,
            bootstyle=SECONDARY,
            command=lambda s=-(0.01 if self.is_float else 1): btn_cmd(s),
        ).pack(side=RIGHT)
    
    def _create_slider(self, from_, to):
        """Create the slider."""
        ttk.Scale(
            self.container,
            from_=from_,
            to=to,
            orient=HORIZONTAL,
            variable=self.var,
            bootstyle=SECONDARY,
            command=self._on_slider_change,
        ).pack(side=RIGHT, fill=X, expand=YES, padx=2)
    
    def _on_slider_change(self, value):
        """Handle slider value change."""
        self.config.set(
            self.key, 
            float(value) if self.is_float else int(float(value))
        )
    
    def _update_label(self, *args):
        """Update the value label."""
        self.val_label.config(
            text=f"{self.var.get():.3f}" if self.is_float else str(self.var.get())
        )


class SpinboxControl:
    """Reusable spinbox control."""
    
    def __init__(self, parent, key, from_, to, config, widget_vars):
        self.config = config
        self.widget_vars = widget_vars
        self.key = key
        
        # Get or create variable
        self.var = self.widget_vars.get(key)
        if not self.var:
            value = self.config.get(key)
            self.var = tk.IntVar(value=value)
            self.widget_vars[key] = self.var
        
        # Create spinbox
        self.spinbox = ttk.Spinbox(
            parent,
            from_=from_,
            to=to,
            textvariable=self.var,
            width=5,
            command=self._on_change,
        )
        self.spinbox.pack(side=LEFT, padx=2, pady=2)
        
        # Bind variable changes
        self.var.trace_add("write", self._on_change)
    
    def _on_change(self, *args):
        """Handle value change."""
        self.config.set(self.key, self.var.get())


class ComboboxControl:
    """Reusable combobox control."""
    
    def __init__(self, parent, key, values, config, widget_vars, width=None, state="readonly"):
        self.config = config
        self.widget_vars = widget_vars
        self.key = key
        
        # Get or create variable
        self.var = self.widget_vars.get(key)
        if not self.var:
            value = self.config.get(key)
            self.var = tk.StringVar(value=value)
            self.widget_vars[key] = self.var
        
        # Create combobox
        self.combobox = ttk.Combobox(
            parent,
            textvariable=self.var,
            values=values,
            state=state,
            width=width,
        )
        self.combobox.pack(side=LEFT, padx=2, pady=2)
        
        # Bind variable changes
        self.var.trace_add("write", self._on_change)
    
    def _on_change(self, *args):
        """Handle value change."""
        self.config.set(self.key, self.var.get())


class CheckboxControl:
    """Reusable checkbox control."""
    
    def __init__(self, parent, key, text, config, widget_vars, command=None, **kwargs):
        self.config = config
        self.widget_vars = widget_vars
        self.key = key
        
        # Get or create variable
        self.var = self.widget_vars.get(key)
        if not self.var:
            value = self.config.get(key)
            self.var = tk.BooleanVar(value=value)
            self.widget_vars[key] = self.var
        
        # Create checkbox
        self.checkbox = ttk.Checkbutton(
            parent,
            text=text,
            variable=self.var,
            command=self._on_change if not command else command,
            **kwargs
        )
        self.checkbox.pack(side=LEFT, padx=2, pady=2)
        
        # Bind variable changes if no custom command
        if not command:
            self.var.trace_add("write", self._on_change)
    
    def _on_change(self, *args):
        """Handle value change."""
        self.config.set(self.key, self.var.get())
