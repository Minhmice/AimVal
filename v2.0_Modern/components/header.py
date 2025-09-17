"""Header component with performance metrics and status display."""

import tkinter as tk
from ttkbootstrap import ttk
from ttkbootstrap.constants import *


class HeaderComponent:
    """Header component showing performance metrics and bot status."""
    
    def __init__(self, parent, config, bot_instance):
        self.config = config
        self.bot_instance = bot_instance
        
        # Create header frame
        self.header_frame = ttk.Frame(parent)
        self.header_frame.pack(fill=X, side=TOP, pady=(0, 5))
        
        # Performance metrics frame
        self.perf_frame = ttk.Frame(self.header_frame)
        self.perf_frame.pack(fill=X)
        
        # Performance labels
        self.fps_label = ttk.Label(self.perf_frame, text="FPS: --", font=("Arial", 10, "bold"))
        self.fps_label.pack(side=LEFT, padx=(0, 10))
        
        self.latency_label = ttk.Label(self.perf_frame, text="Latency: --ms", font=("Arial", 10, "bold"))
        self.latency_label.pack(side=LEFT, padx=(0, 10))
        
        self.cpu_label = ttk.Label(self.perf_frame, text="CPU: --%", font=("Arial", 10, "bold"))
        self.cpu_label.pack(side=LEFT, padx=(0, 10))
        
        self.ram_label = ttk.Label(self.perf_frame, text="RAM: --%", font=("Arial", 10, "bold"))
        self.ram_label.pack(side=LEFT, padx=(0, 10))
        
        # Connection status frame
        self.status_frame = ttk.Frame(self.header_frame)
        self.status_frame.pack(fill=X, pady=(2, 0))
        
        self.makcu_status_label = ttk.Label(self.status_frame, text="Makcu: Disconnected", font=("Arial", 9))
        self.makcu_status_label.pack(side=LEFT, padx=(0, 10))
        
        self.pc1_status_label = ttk.Label(self.status_frame, text="PC1: No Signal", font=("Arial", 9))
        self.pc1_status_label.pack(side=LEFT, padx=(0, 10))
        
        # Bot status frame
        self.bot_status_frame = ttk.Frame(self.header_frame)
        self.bot_status_frame.pack(fill=X, pady=(2, 0))
        
        self.header_bot_status_label = ttk.Label(
            self.bot_status_frame, 
            text="Aim: OFF  Mouse1: OFF  Mouse2: OFF", 
            font=("Arial", 9, "bold")
        )
        self.header_bot_status_label.pack(side=LEFT)
    
    def update_performance(self, fps, latency, cpu, ram):
        """Update performance metrics display."""
        self.fps_label.config(text=f"FPS: {fps}")
        self.latency_label.config(text=f"Latency: {latency}ms")
        self.cpu_label.config(text=f"CPU: {cpu}%")
        self.ram_label.config(text=f"RAM: {ram}%")
    
    def update_connection_status(self, makcu_connected, pc1_ip):
        """Update connection status display."""
        makcu_text = "Makcu: Connected" if makcu_connected else "Makcu: Disconnected"
        self.makcu_status_label.config(text=makcu_text)
        
        pc1_text = f"PC1: {pc1_ip}" if pc1_ip else "PC1: No Signal"
        self.pc1_status_label.config(text=pc1_text)
    
    def update_bot_status(self, aim_active, mouse1_active, mouse2_active):
        """Update bot status display."""
        aim_status = "ON" if aim_active else "OFF"
        mouse1_status = "ON" if mouse1_active else "OFF"
        mouse2_status = "ON" if mouse2_active else "OFF"
        
        aim_color = "green" if aim_active else "red"
        self.header_bot_status_label.config(
            text=f"Aim: {aim_status}  Mouse1: {mouse1_status}  Mouse2: {mouse2_status}",
            foreground=aim_color
        )
