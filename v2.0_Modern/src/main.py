"""AimVal 2.0 - Modern UI Application with Dark Theme."""

import tkinter as tk
import os
import logging
import threading
import time
from ttkbootstrap import ttk, Style
from ttkbootstrap.constants import *

# Import components
try:
    import sys
    import os

    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from components.header import HeaderComponent
    from components.main_tab import MainTabComponent
    from components.aiming_tab import AimingTabComponent
    from components.detection_tab import DetectionTabComponent
    from components.advanced_tab import AdvancedTabComponent
    from components.trigger_tab import TriggerTabComponent
except ImportError as e:
    print(f"Component import error: {e}")
    print("Make sure components directory exists and has __init__.py")
    exit(1)

# Import core modules
try:
    import sys
    import os

    # Add parent directory to path for imports
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(parent_dir)

    from config import SharedConfig
    from core import TriggerbotCore, MakcuController, UdpFrameSource
    from utils import setup_logging
except ImportError as e:
    print(f"Core module import error: {e}")
    print("Make sure all core modules are available")
    exit(1)


class AimValTrackerApp:
    """Modern AimVal 2.0 application with dark theme and professional layout."""

    def __init__(self):
        # Setup logging
        setup_logging()
        self.logger = logging.getLogger(__name__)
        self._attach_gui_logger()

        # Initialize config
        self.config = SharedConfig()

        # Initialize core modules
        self.bot_instance = None
        self.mouse_controller = None
        self.udp_source = None

        # Initialize UI
        self._setup_modern_ui()
        self._setup_callbacks()

        # Initialize components
        self._create_components()

        # Start background tasks
        self._start_background_tasks()
    def _attach_gui_logger(self):
        class TextHandler(logging.Handler):
            def __init__(self, outer):
                super().__init__()
                self.outer = outer
            def emit(self, record):
                try:
                    msg = self.format(record)
                    level = record.levelname
                    # Avoid recursion if output_text not ready yet
                    if hasattr(self.outer, 'output_text'):
                        self.outer._log_output(msg, level)
                except Exception:
                    pass
        try:
            handler = TextHandler(self)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            logging.getLogger().addHandler(handler)
        except Exception:
            pass

    def _setup_modern_ui(self):
        """Setup modern UI with dark theme and professional layout."""
        # Create main window with exact dimensions from CSS
        self.root = tk.Tk()
        self.root.title("AimVal 2.0 - @minhmice29")
        self.root.geometry("1710x1080")
        self.root.minsize(1280, 800)
        self.root.configure(bg="#0A0A0A")

        # Apply custom dark theme
        self.style = Style(theme="darkly")

        # Configure custom colors to match CSS
        self.style.configure("Custom.TFrame", background="#1F1F1F")
        self.style.configure(
            "Custom.TLabel",
            background="#1F1F1F",
            foreground="#FFFFFF",
            font=("Montserrat", 24, "bold"),
        )
        self.style.configure(
            "Header.TLabel",
            background="#1F1F1F",
            foreground="#FFFFFF",
            font=("Montserrat", 24, "bold"),
        )

        # Create main container using grid for responsive layout
        self.main_container = tk.Frame(self.root, bg="#0A0A0A")
        self.main_container.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Define 2-column responsive layout: center | right (no sidebar)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)  # center grows
        self.main_container.grid_columnconfigure(
            1, weight=0, minsize=400
        )  # right fixed

        # Build columns (no sidebar)
        self._create_center_column()
        self._create_right_column()

        # Setup close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _create_sidebar(self):
        """Sidebar removed as requested (no-op)."""
        pass

    def _create_center_column(self):
        """Create center column containing dashboard, performance and output as in design."""
        self.center_container = tk.Frame(self.main_container, bg="#1F1F1F")
        self.center_container.grid(
            row=0, column=0, sticky="nsew", pady=10, padx=(10, 10)
        )
        self.center_container.grid_rowconfigure(0, weight=1)
        self.center_container.grid_rowconfigure(1, weight=1)
        self.center_container.grid_columnconfigure(0, weight=1)

        # Dashboard header
        dashboard_header = tk.Frame(self.center_container, bg="#1F1F1F")
        dashboard_header.grid(row=0, column=0, sticky="new")

        dashboard_title = tk.Label(
            dashboard_header,
            text="Dashboard",
            font=("Montserrat", 18, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        dashboard_title.pack(anchor=W)
        tk.Frame(dashboard_header, height=1, bg="#FFFFFF").pack(fill=X, pady=(5, 0))

        # Top: Vision | Mask
        self._create_dashboard_content_grid()
        # Bottom: Performance | Output
        self._create_bottom_center_grid()

    def _create_dashboard_content_grid(self):
        """Top row with Vision and Mask side-by-side (responsive)."""
        content_frame = tk.Frame(self.center_container, bg="#1F1F1F")
        content_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=(10, 5))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        self.vision_frame = tk.LabelFrame(
            content_frame,
            text="Vision",
            font=("Montserrat", 16, "bold"),
            fg="#FFFFFF",
            bg="#0A0A0A",
            relief=FLAT,
        )
        self.vision_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.vision_frame.grid_propagate(True)
        self.vision_canvas = tk.Canvas(
            self.vision_frame, bg="#0A0A0A", highlightthickness=0
        )
        self.vision_canvas.pack(fill=BOTH, expand=True, padx=10, pady=(40, 10))
        self.vision_canvas.create_text(
            10,
            10,
            anchor="nw",
            text="Vision Feed\n(UDP Stream)",
            font=("Montserrat", 12),
            fill="#666666",
            justify="left",
        )
        self.vision_canvas_image = None
        self.vision_canvas.bind("<Configure>", self._enforce_square_canvases)

        self.mask_frame = tk.LabelFrame(
            content_frame,
            text="Mask",
            font=("Montserrat", 16, "bold"),
            fg="#FFFFFF",
            bg="#0A0A0A",
            relief=FLAT,
        )
        self.mask_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.mask_frame.grid_propagate(True)
        self.mask_canvas = tk.Canvas(
            self.mask_frame, bg="#0A0A0A", highlightthickness=0
        )
        self.mask_canvas.pack(fill=BOTH, expand=True, padx=10, pady=(40, 10))
        self.mask_canvas.create_text(
            10,
            10,
            anchor="nw",
            text="Mask Feed\n(Detection Overlay)",
            font=("Montserrat", 12),
            fill="#666666",
            justify="left",
        )
        self.mask_canvas_image = None
        self.mask_canvas.bind("<Configure>", self._enforce_square_canvases)

    def _enforce_square_canvases(self, event=None):
        try:
            # Compute square side for each canvas based on min(width, height)
            for canvas in [self.vision_canvas, self.mask_canvas]:
                if not canvas:
                    continue
                w = max(1, canvas.winfo_width())
                h = max(1, canvas.winfo_height())
                side = min(w, h)
                # Center the drawing area by using internal offsets when rendering images
                canvas.square_side = side  # attach for renderer
                canvas.offset_x = (w - side) // 2
                canvas.offset_y = (h - side) // 2
        except Exception:
            pass

    def _create_bottom_center_grid(self):
        """Bottom row with Performance (left) and Output (right)."""
        bottom_frame = tk.Frame(self.center_container, bg="#1F1F1F")
        bottom_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=(10, 0))
        bottom_frame.grid_columnconfigure(0, weight=0)
        bottom_frame.grid_columnconfigure(1, weight=1)
        bottom_frame.grid_rowconfigure(0, weight=1)

        # Performance (left, fixed min width)
        self._build_performance_panel(bottom_frame)
        self.performance_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        self.performance_frame.configure(width=400)
        self.performance_frame.grid_propagate(True)

        # Output (right, expands)
        self._build_output_log(bottom_frame)
        self.output_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.output_frame.grid_propagate(True)

    def _create_right_column(self):
        """Create right column with Controls (top) and Config (bottom)."""
        self.right_container = tk.Frame(self.main_container, bg="#1F1F1F", width=400)
        self.right_container.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.right_container.grid_propagate(False)
        self.right_container.grid_rowconfigure(0, weight=0)
        self.right_container.grid_rowconfigure(1, weight=1)
        self.right_container.grid_columnconfigure(0, weight=1)

        # Controls (row 0)
        self._build_controls_panel(self.right_container)
        self.controls_frame.grid(row=0, column=0, sticky="new")
        # Config (row 1)
        self._build_config_panel(self.right_container)
        self.config_panel.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _create_navigation_menu(self):
        """Create navigation menu in sidebar."""
        nav_frame = tk.Frame(self.sidebar, bg="#1F1F1F")
        nav_frame.pack(fill=X, padx=10, pady=20)

        # Navigation buttons with gaming icons
        nav_buttons = [
            ("🎯 Dashboard", self._show_dashboard),
            ("🎮 Aiming", self._show_aiming),
            ("🔍 Detection", self._show_detection),
            ("⚡ Trigger Bot", self._show_trigger_bot),
            ("⚙️ Advanced", self._show_advanced),
            ("🔧 Settings", self._show_settings),
            ("👤 Account", self._show_account),
        ]

        self.nav_buttons = {}
        for text, command in nav_buttons:
            btn = tk.Button(
                nav_frame,
                text=text,
                font=("Montserrat", 12, "normal"),
                fg="#FFFFFF",
                bg="#2A2A2A",
                activebackground="#3A3A3A",
                activeforeground="#FFFFFF",
                relief=FLAT,
                command=command,
                anchor=W,
                padx=20,
                pady=10,
            )
            btn.pack(fill=X, pady=2)
            self.nav_buttons[text] = btn

        # Set default active button
        self._set_active_nav("Dashboard")

    def _create_dashboard(self):
        """Deprecated: kept for backward compatibility (no-op)."""
        pass

    def _create_dashboard_content(self):
        """Deprecated: replaced by grid version."""
        pass

    def _create_performance_panel(self):
        """Deprecated: replaced by grid version."""
        pass

    def _build_performance_panel(self, parent):
        """Create performance monitoring panel into provided parent."""
        self.performance_frame = tk.Frame(parent, bg="#1F1F1F")
        perf_header = tk.Frame(self.performance_frame, bg="#1F1F1F")
        perf_header.pack(fill=X, padx=10, pady=10)
        perf_title = tk.Label(
            perf_header,
            text="Performance",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        perf_title.pack(anchor=W)
        tk.Frame(perf_header, height=1, bg="#FFFFFF").pack(fill=X, pady=(5, 0))
        self._create_performance_metrics()

    def _create_performance_metrics(self):
        """Create performance metrics display."""
        metrics_frame = tk.Frame(self.performance_frame, bg="#1F1F1F")
        metrics_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Left column metrics
        left_frame = tk.Frame(metrics_frame, bg="#1F1F1F")
        left_frame.pack(side=LEFT, fill=Y, expand=True)

        # Right column metrics
        right_frame = tk.Frame(metrics_frame, bg="#1F1F1F")
        right_frame.pack(side=RIGHT, fill=Y, expand=True)

        # FPS
        self.fps_label = tk.Label(
            left_frame,
            text="FPS: --",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.fps_label.pack(anchor=W, pady=5)

        # CPU
        self.cpu_label = tk.Label(
            left_frame,
            text="CPU: --%",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.cpu_label.pack(anchor=W, pady=5)

        # Makcu connection
        self.makcu_label = tk.Label(
            left_frame,
            text="Makcu: Disconnect",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.makcu_label.pack(anchor=W, pady=5)

        # Video connection
        self.video_label = tk.Label(
            left_frame,
            text="Video: Disconnect",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.video_label.pack(anchor=W, pady=5)

        # RAM
        self.ram_label = tk.Label(
            right_frame,
            text="RAM: --MB",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.ram_label.pack(anchor=W, pady=5)

        # Latency
        self.latency_label = tk.Label(
            right_frame,
            text="Ms: --",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.latency_label.pack(anchor=W, pady=5)

        # GPU (if available)
        self.gpu_label = tk.Label(
            right_frame,
            text="GPU: --%",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.gpu_label.pack(anchor=W, pady=5)

        # Temperature (if available)
        self.temp_label = tk.Label(
            right_frame,
            text="Temp: --°C",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        self.temp_label.pack(anchor=W, pady=5)

    def _create_output_log(self):
        """Deprecated: replaced by grid version."""
        pass

    def _build_output_log(self, parent):
        """Create output/log area with filter levels into provided parent."""
        self.output_frame = tk.Frame(parent, bg="#1F1F1F")
        output_header = tk.Frame(self.output_frame, bg="#1F1F1F")
        output_header.pack(fill=X, padx=10, pady=10)
        output_title = tk.Label(
            output_header,
            text="Output",
            font=("Montserrat", 16, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        output_title.pack(anchor=W)
        tk.Frame(output_header, height=1, bg="#FFFFFF").pack(fill=X, pady=(5, 0))
        filter_frame = tk.Frame(self.output_frame, bg="#1F1F1F")
        filter_frame.pack(fill=X, padx=10, pady=(0, 5))
        self.filter_buttons = {}
        filter_levels = [
            ("ALL", "#FFFFFF", self._filter_all),
            ("INFO", "#00FF00", self._filter_info),
            ("WARNING", "#FFFF00", self._filter_warning),
            ("ERROR", "#FF0000", self._filter_error),
        ]
        for level, color, command in filter_levels:
            btn = tk.Button(
                filter_frame,
                text=level,
                font=("Montserrat", 10, "bold"),
                fg=color,
                bg="#2A2A2A",
                activebackground="#3A3A3A",
                relief=FLAT,
                command=command,
                padx=10,
                pady=2,
            )
            btn.pack(side=LEFT, padx=(0, 5))
            self.filter_buttons[level] = btn
        clear_btn = tk.Button(
            filter_frame,
            text="CLEAR",
            font=("Montserrat", 10, "bold"),
            fg="#FF6666",
            bg="#2A2A2A",
            activebackground="#3A3A3A",
            relief=FLAT,
            command=self._clear_log,
            padx=10,
            pady=2,
        )
        clear_btn.pack(side=RIGHT)
        text_frame = tk.Frame(self.output_frame, bg="#1F1F1F")
        text_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.output_text = tk.Text(
            text_frame,
            font=("Consolas", 10),
            fg="#00FF00",
            bg="#0A0A0A",
            relief=FLAT,
            wrap=WORD,
            state=DISABLED,
        )
        self.output_text.pack(side=LEFT, fill=BOTH, expand=True)
        output_scrollbar = tk.Scrollbar(
            text_frame, orient=VERTICAL, command=self.output_text.yview
        )
        output_scrollbar.pack(side=RIGHT, fill=Y)
        self.output_text.config(yscrollcommand=output_scrollbar.set)
        self.current_filter = "ALL"
        self._filter_all()

    def _create_controls_panel(self):
        """Deprecated: replaced by grid version."""
        pass

    def _build_controls_panel(self, parent):
        """Create controls panel into provided parent."""
        self.controls_frame = tk.Frame(parent, bg="#1F1F1F", height=260)
        self.controls_frame.pack_propagate(False)
        controls_header = tk.Frame(self.controls_frame, bg="#1F1F1F")
        controls_header.pack(fill=X, padx=10, pady=10)
        controls_title = tk.Label(
            controls_header,
            text="Controls",
            font=("Montserrat", 14, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        controls_title.pack(anchor=W)
        tk.Frame(controls_header, height=1, bg="#FFFFFF").pack(fill=X, pady=(5, 0))
        self._create_controls_content()

    def _create_controls_content(self):
        """Create controls content with Start button and toggles."""
        content_frame = tk.Frame(self.controls_frame, bg="#1F1F1F")
        content_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Start Button
        self.start_btn = tk.Button(
            content_frame,
            text="Start",
            font=("Montserrat", 24, "bold"),
            fg="#FFFFFF",
            bg="#0A0A0A",
            activebackground="#1A1A1A",
            relief=FLAT,
            command=self.start_bot,
            width=12,
            height=1,
        )
        self.start_btn.pack(pady=(8, 12))

        # TriggerBot Toggle
        trigger_frame = tk.Frame(content_frame, bg="#0A0A0A", height=32)
        trigger_frame.pack(fill=X, pady=5)
        trigger_frame.pack_propagate(False)

        self.trigger_label = tk.Label(
            trigger_frame,
            text="TriggerBot",
            font=("Montserrat", 18, "bold"),
            fg="#1F1F1F",
            bg="#0A0A0A",
        )
        self.trigger_label.pack(side=LEFT, padx=10, pady=5)

        self.trigger_toggle = tk.Button(
            trigger_frame,
            text="Off",
            font=("Montserrat", 12, "bold"),
            fg="#1F1F1F",
            bg="#1F1F1F",
            activebackground="#2F2F2F",
            relief=FLAT,
            command=self.toggle_trigger_bot,
            width=3,
            height=1,
        )
        self.trigger_toggle.pack(side=RIGHT, padx=10, pady=5)

        # AimAssist Toggle
        aim_frame = tk.Frame(content_frame, bg="#0A0A0A", height=32)
        aim_frame.pack(fill=X, pady=5)
        aim_frame.pack_propagate(False)

        self.aim_label = tk.Label(
            aim_frame,
            text="AimAssist",
            font=("Montserrat", 18, "bold"),
            fg="#FFFFFF",
            bg="#0A0A0A",
        )
        self.aim_label.pack(side=LEFT, padx=10, pady=5)

        self.aim_toggle = tk.Button(
            aim_frame,
            text="On",
            font=("Montserrat", 12, "bold"),
            fg="#FFFFFF",
            bg="#FFFFFF",
            activebackground="#CCCCCC",
            relief=FLAT,
            command=self.toggle_aim_assist,
            width=3,
            height=1,
        )
        self.aim_toggle.pack(side=RIGHT, padx=10, pady=5)

    def _create_config_panel(self):
        """Deprecated: replaced by grid version."""
        pass

    def _build_config_panel(self, parent):
        """Create right configuration panel into provided parent."""
        self.config_panel = tk.Frame(parent, bg="#1F1F1F")
        config_header = tk.Frame(self.config_panel, bg="#1F1F1F")
        config_header.pack(fill=X, padx=10, pady=10)
        config_title = tk.Label(
            config_header,
            text="Config",
            font=("Montserrat", 16, "bold"),
            fg="#FFFFFF",
            bg="#1F1F1F",
        )
        config_title.pack(anchor=W)
        tk.Frame(config_header, height=1, bg="#FFFFFF").pack(fill=X, pady=(5, 0))
        self._create_config_content()

    def _create_config_content(self):
        """Create configuration content stacked in a single scrollable column."""
        # Scroll container
        container = tk.Frame(self.config_panel, bg="#1F1F1F")
        container.pack(fill=BOTH, expand=True, padx=10, pady=10)
        canvas = tk.Canvas(container, bg="#1F1F1F", highlightthickness=0)
        vscroll = tk.Scrollbar(container, orient=VERTICAL, command=canvas.yview)
        self.config_stack = tk.Frame(canvas, bg="#1F1F1F")
        self.config_stack.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.config_stack, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        vscroll.pack(side=RIGHT, fill=Y)

        # Mouse wheel support for scrolling
        def _on_mousewheel(event):
            try:
                delta = int(event.delta)
                canvas.yview_scroll(-1 * (delta // 120), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Create sections
        self._create_config_tabs()
        # Buttons
        self._create_config_buttons()

    def _create_config_tabs(self):
        """Create configuration sections stacked vertically."""

        def section(title: str) -> tk.Frame:
            header = tk.Label(
                self.config_stack,
                text=title,
                font=("Montserrat", 12, "bold"),
                fg="#FFFFFF",
                bg="#1F1F1F",
            )
            header.pack(anchor=W, pady=(6, 2))
            tk.Frame(self.config_stack, height=1, bg="#2A2A2A").pack(
                fill=X, pady=(0, 6)
            )
            frame = tk.Frame(self.config_stack, bg="#1F1F1F")
            frame.pack(fill=X, expand=YES)
            return frame

        main_tab = section("Main")
        aiming_tab = section("Aiming")
        detection_tab = section("Detection")
        trigger_tab = section("Trigger")
        advanced_tab = section("Advanced")
        self.config_tabs = {
            "main": main_tab,
            "aiming": aiming_tab,
            "detection": detection_tab,
            "trigger": trigger_tab,
            "advanced": advanced_tab,
        }

    def _create_config_buttons(self):
        """Create save/load config buttons."""
        button_frame = tk.Frame(self.config_stack, bg="#1F1F1F")
        button_frame.pack(fill=X, padx=0, pady=(10, 0))

        # Save button
        save_btn = tk.Button(
            button_frame,
            text="💾 Save Config",
            font=("Montserrat", 12, "bold"),
            fg="#FFFFFF",
            bg="#00AA00",
            activebackground="#00CC00",
            relief=FLAT,
            command=self._save_config,
            padx=15,
            pady=5,
        )
        save_btn.pack(side=LEFT, padx=(0, 10))

        # Load button
        load_btn = tk.Button(
            button_frame,
            text="📁 Load Config",
            font=("Montserrat", 12, "bold"),
            fg="#FFFFFF",
            bg="#0066AA",
            activebackground="#0088CC",
            relief=FLAT,
            command=self._load_config,
            padx=15,
            pady=5,
        )
        load_btn.pack(side=LEFT)

    def _save_config(self):
        """Save current configuration."""
        try:
            self.config.save()
            self._log_output("Configuration saved successfully", "INFO")
        except Exception as e:
            self._log_output(f"Failed to save configuration: {e}", "ERROR")

    def _load_config(self):
        """Load configuration from file."""
        try:
            self.config.load()
            self._log_output("Configuration loaded successfully", "INFO")
        except Exception as e:
            self._log_output(f"Failed to load configuration: {e}", "ERROR")

    def _setup_callbacks(self):
        """Setup callback functions for components."""
        self.callbacks = {
            "save_config": self._save_config_from_entry,
            "load_config": self._load_config_dialog,
            "on_aim_mode_change": self._on_aim_mode_change,
            "on_color_profile_change": self._on_color_profile_change,
            "start_bot": self.start_bot,
            "stop_bot": self.stop_bot,
        }

    def _create_components(self):
        """Create all UI components."""
        # Widget variables storage
        self.widget_vars = {}

        # Create components for each config tab
        for tab_name, tab_frame in self.config_tabs.items():
            if tab_name == "main":
                self.main_component = MainTabComponent(
                    tab_frame, self.config, self.widget_vars, self.callbacks
                )
            elif tab_name == "aiming":
                self.aiming_component = AimingTabComponent(
                    tab_frame, self.config, self.widget_vars, self.callbacks
                )
            elif tab_name == "detection":
                self.detection_component = DetectionTabComponent(
                    tab_frame, self.config, self.widget_vars, self.callbacks
                )
            elif tab_name == "trigger":
                self.trigger_component = TriggerTabComponent(
                    tab_frame, self.config, self.widget_vars, self.callbacks
                )
            elif tab_name == "advanced":
                self.advanced_component = AdvancedTabComponent(
                    tab_frame, self.config, self.widget_vars, self.callbacks
                )

    def _set_active_nav(self, active_button):
        """Set active navigation button."""
        for name, btn in self.nav_buttons.items():
            # Extract button name without icon for comparison
            button_name = name.split(" ", 1)[1] if " " in name else name
            if button_name == active_button:
                btn.config(bg="#3A3A3A")
            else:
                btn.config(bg="#2A2A2A")

    def _show_dashboard(self):
        """Show dashboard view."""
        self._set_active_nav("Dashboard")
        # Dashboard is always visible, no need to hide/show

    def _show_aiming(self):
        """Show aiming configuration."""
        self._set_active_nav("Aiming")
        if hasattr(self, "config_notebook"):
            self.config_notebook.select(1)  # Aiming tab

    def _show_detection(self):
        """Show detection configuration."""
        self._set_active_nav("Detection")
        if hasattr(self, "config_notebook"):
            self.config_notebook.select(2)  # Detection tab

    def _show_trigger_bot(self):
        """Show trigger bot configuration."""
        self._set_active_nav("Trigger Bot")
        if hasattr(self, "config_notebook"):
            self.config_notebook.select(3)  # Trigger tab

    def _show_advanced(self):
        """Show advanced configuration."""
        self._set_active_nav("Advanced")
        if hasattr(self, "config_notebook"):
            self.config_notebook.select(4)  # Advanced tab

    def _show_settings(self):
        """Show settings."""
        self._set_active_nav("Settings")
        self.config_notebook.select(0)  # Main tab

    def _show_account(self):
        """Show account settings."""
        self._set_active_nav("Account")
        self.config_notebook.select(0)  # Main tab

    def toggle_trigger_bot(self):
        """Toggle trigger bot on/off."""
        current_state = self.config.get("TRIGGERBOT_ENABLED", False)
        new_state = not current_state
        self.config.set("TRIGGERBOT_ENABLED", new_state)

        # Update toggle button
        if hasattr(self, "trigger_toggle"):
            self.trigger_toggle.config(
                text="On" if new_state else "Off",
                fg="#FFFFFF" if new_state else "#1F1F1F",
                bg="#FFFFFF" if new_state else "#1F1F1F",
            )

        # Keep label color consistent (white)
        if hasattr(self, "trigger_label"):
            self.trigger_label.config(fg="#FFFFFF")

        self._log_output(
            f"Trigger bot {'enabled' if new_state else 'disabled'}", "INFO"
        )

    def toggle_aim_assist(self):
        """Toggle aim assist on/off."""
        current_state = self.config.get("AIM_ASSIST_ENABLED", False)
        new_state = not current_state
        self.config.set("AIM_ASSIST_ENABLED", new_state)

        # Update toggle button
        if hasattr(self, "aim_toggle"):
            self.aim_toggle.config(
                text="On" if new_state else "Off",
                fg="#FFFFFF" if new_state else "#1F1F1F",
                bg="#FFFFFF" if new_state else "#1F1F1F",
            )

        # Keep label color consistent (white)
        if hasattr(self, "aim_label"):
            self.aim_label.config(fg="#FFFFFF")

        self._log_output(f"Aim assist {'enabled' if new_state else 'disabled'}", "INFO")

    def _log_output(self, message, level="INFO"):
        """Add message to output log with level filtering."""
        timestamp = time.strftime("%H:%M:%S")

        # Determine color based on level
        colors = {
            "INFO": "#00FF00",
            "WARNING": "#FFFF00",
            "ERROR": "#FF0000",
            "DEBUG": "#00FFFF",
        }

        log_message = f"[{timestamp}] [{level}] {message}\n"

        # Enable text widget for editing
        self.output_text.config(state=tk.NORMAL)

        # Insert message
        self.output_text.insert(tk.END, log_message)
        try:
            self.logger.log(getattr(logging, level, logging.INFO), message)
        except Exception:
            pass

        # Apply color formatting
        start_line = self.output_text.index("end-2l")
        end_line = self.output_text.index("end-1l")

        # Tag the line with appropriate color
        self.output_text.tag_add(level, start_line, end_line)
        self.output_text.tag_config(level, foreground=colors.get(level, "#FFFFFF"))

        # Auto-scroll to bottom
        self.output_text.see(tk.END)

        # Disable text widget
        self.output_text.config(state=tk.DISABLED)

        # Limit log size
        lines = self.output_text.get("1.0", tk.END).split("\n")
        if len(lines) > 1000:
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete("1.0", "100.0")
            self.output_text.config(state=tk.DISABLED)

    def _filter_all(self):
        """Show all log messages."""
        self.current_filter = "ALL"
        self._update_filter_buttons()
        self._apply_filter()

    def _filter_info(self):
        """Show only INFO messages."""
        self.current_filter = "INFO"
        self._update_filter_buttons()
        self._apply_filter()

    def _filter_warning(self):
        """Show only WARNING messages."""
        self.current_filter = "WARNING"
        self._update_filter_buttons()
        self._apply_filter()

    def _filter_error(self):
        """Show only ERROR messages."""
        self.current_filter = "ERROR"
        self._update_filter_buttons()
        self._apply_filter()

    def _update_filter_buttons(self):
        """Update filter button states."""
        for level, btn in self.filter_buttons.items():
            if level == self.current_filter:
                btn.config(bg="#3A3A3A")
            else:
                btn.config(bg="#2A2A2A")

    def _apply_filter(self):
        """Apply current filter to log display."""
        # This is a simplified version - in a real implementation,
        # you would need to store log messages separately and filter them
        pass

    def _clear_log(self):
        """Clear the output log."""
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _create_control_buttons(self):
        """Create start/stop control buttons."""
        control_frame = ttk.Frame(self.main_container)
        control_frame.pack(fill=X, pady=(0, 5))

        self.start_button = ttk.Button(
            control_frame,
            text="Start Bot",
            command=self.start_bot,
            bootstyle=SUCCESS,
        )
        self.start_button.pack(side=LEFT, padx=(0, 5))

        self.stop_button = ttk.Button(
            control_frame,
            text="Stop Bot",
            command=self.stop_bot,
            bootstyle=DANGER,
        )
        self.stop_button.pack(side=LEFT)

    def _start_background_tasks(self):
        """Start background monitoring tasks."""
        self._health_log_tick()

    def _health_log_tick(self):
        """Update health metrics and bot status."""
        try:
            if self.bot_instance and self.mouse_controller and self.udp_source:
                # Get performance metrics
                fps = getattr(self.bot_instance, "fps", 0)
                latency = getattr(self.bot_instance, "latency", 0)
                cpu = getattr(self.bot_instance, "cpu_percent", 0)
                ram = getattr(self.bot_instance, "ram_percent", 0)

                # Update performance labels with color coding
                self.fps_label.config(
                    text=f"FPS: {fps}",
                    fg=(
                        "#00FF00"
                        if fps >= 60
                        else "#FFFF00" if fps >= 30 else "#FF0000"
                    ),
                )
                self.cpu_label.config(
                    text=f"CPU: {cpu}%",
                    fg=(
                        "#00FF00"
                        if cpu <= 50
                        else "#FFFF00" if cpu <= 80 else "#FF0000"
                    ),
                )
                self.ram_label.config(
                    text=f"RAM: {ram}MB",
                    fg=(
                        "#00FF00"
                        if ram <= 4000
                        else "#FFFF00" if ram <= 8000 else "#FF0000"
                    ),
                )
                self.latency_label.config(
                    text=f"Ms: {latency}",
                    fg=(
                        "#00FF00"
                        if latency <= 10
                        else "#FFFF00" if latency <= 30 else "#FF0000"
                    ),
                )

                # Update connection status
                makcu_connected = self.mouse_controller.is_connected
                pc1_ip = getattr(self.udp_source, "last_pc1_ip", None)

                self.makcu_label.config(
                    text=f"Makcu: {'Connected' if makcu_connected else 'Disconnect'}",
                    fg="#00FF00" if makcu_connected else "#FF0000",
                )
                self.video_label.config(
                    text=f"Video: {'Connected' if pc1_ip else 'Disconnect'}",
                    fg="#00FF00" if pc1_ip else "#FF0000",
                )

            # Schedule next update
            self.root.after(1500, self._health_log_tick)

        except Exception as e:
            self.logger.error(f"Health log error: {e}")
            self.root.after(1500, self._health_log_tick)

    def _on_window_resize(self, event):
        """Handle window resize to make UI responsive."""
        if event.widget == self.root:
            try:
                self.root.update_idletasks()
            except Exception:
                pass

    def start_bot(self):
        """Start the bot instance."""
        try:
            if not self.bot_instance:
                # Initialize core modules
                self.mouse_controller = MakcuController(self.config)
                self.udp_source = UdpFrameSource(self.config)

                # Initialize bot
                self.bot_instance = TriggerbotCore(self.config)

                # Setup bot with dependencies
                if not self.bot_instance.setup():
                    self.logger.error("Failed to setup bot core")
                    self.bot_instance = None
                    return

                # Set running flag
                self.config.set("is_running", True)

                # Start bot loop
                self._start_bot_loop()

                # Update header reference if it exists
                if hasattr(self, "header"):
                    self.header.bot_instance = self.bot_instance

                self.logger.info("Bot started successfully")
                self._log_output("Bot started successfully", "INFO")

                # Update UI
                if hasattr(self, "start_btn"):
                    self.start_btn.config(text="Stop", command=self.stop_bot)
            else:
                self.logger.warning("Bot is already running")

        except Exception as e:
            self.logger.error(f"Failed to start bot: {e}")
            self._log_output(f"Failed to start bot: {e}")

    def _start_bot_loop(self):
        """Start the bot processing loop in a separate thread."""

        def bot_loop():
            while self.bot_instance and self.config.get("is_running", False):
                try:
                    self.bot_instance.run_one_frame()
                    # After each frame, if debug frames available, render into canvases
                    try:
                        import cv2
                        from PIL import Image, ImageTk  # type: ignore

                        # Helper to render into a square canvas
                        def render_to_canvas(canvas, bgr, storage_attr):
                            if bgr is None or canvas is None:
                                return
                            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(rgb)
                            side = getattr(
                                canvas,
                                "square_side",
                                min(
                                    max(1, canvas.winfo_width()),
                                    max(1, canvas.winfo_height()),
                                ),
                            )
                            if side > 0:
                                img = img.resize((side, side))
                            tkimg = ImageTk.PhotoImage(img)
                            setattr(self, storage_attr, tkimg)
                            canvas.delete("all")
                            offset_x = getattr(canvas, "offset_x", 0)
                            offset_y = getattr(canvas, "offset_y", 0)
                            canvas.create_image(
                                offset_x, offset_y, anchor="nw", image=tkimg
                            )

                        # Render vision and mask
                        render_to_canvas(
                            self.vision_canvas,
                            getattr(self.bot_instance, "latest_vision_bgr", None),
                            "vision_canvas_image",
                        )
                        render_to_canvas(
                            self.mask_canvas,
                            getattr(self.bot_instance, "latest_mask_bgr", None),
                            "mask_canvas_image",
                        )
                    except Exception:
                        pass
                    time.sleep(0.001)  # Small delay to prevent 100% CPU usage
                except Exception as e:
                    self.logger.error(f"Bot loop error: {e}")
                    break

        # Start bot loop in separate thread
        self.bot_thread = threading.Thread(target=bot_loop, daemon=True)
        self.bot_thread.start()

    def stop_bot(self):
        """Stop the bot instance."""
        try:
            if self.bot_instance:
                # Stop bot loop
                self.config.set("is_running", False)

                # Wait for bot thread to finish
                if hasattr(self, "bot_thread") and self.bot_thread.is_alive():
                    self.bot_thread.join(timeout=1.0)

                # Cleanup bot
                self.bot_instance.cleanup()
                self.bot_instance = None
                self.logger.info("Bot stopped")
                self._log_output("Bot stopped", "INFO")

                # Update UI
                if hasattr(self, "start_btn"):
                    self.start_btn.config(text="Start", command=self.start_bot)
            else:
                self.logger.warning("Bot is not running")

        except Exception as e:
            self.logger.error(f"Failed to stop bot: {e}")
            self._log_output(f"Failed to stop bot: {e}")

    def _save_config_from_entry(self):
        """Save config from entry field."""
        try:
            filename = self.main_component.config_entry_var.get()
            if not filename.endswith(".json"):
                filename += ".json"

            filepath = os.path.join(os.getcwd(), filename)
            self.config.save_to_file(filepath)
            self.logger.info(f"Config saved to {filepath}")

        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def _load_config_dialog(self):
        """Load config from file dialog."""
        try:
            from tkinter import filedialog

            filepath = filedialog.askopenfilename(
                title="Load Config",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )

            if filepath:
                self.config.load_from_file(filepath)
                self._update_gui_from_config()
                self.logger.info(f"Config loaded from {filepath}")

        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")

    def _on_aim_mode_change(self, event=None):
        """Handle aim mode change."""
        try:
            mode = self.aiming_component.aim_mode_var.get()
            self.config.set("AIM_MODE", mode)
            self.aiming_component.show_mode_frame(mode)
            self.logger.info(f"Aim mode changed to {mode}")

        except Exception as e:
            self.logger.error(f"Failed to change aim mode: {e}")

    def _on_color_profile_change(self, event=None):
        """Handle color profile change."""
        try:
            profile_name = self.detection_component.color_profile_var.get()
            if profile := self.config.color_profiles.get(profile_name):
                self.config.set("ACTIVE_COLOR_PROFILE", profile_name)
                self._update_color_profile_values(profile)
                self.logger.info(f"Color profile set to '{profile_name}'")

        except Exception as e:
            self.logger.error(f"Failed to change color profile: {e}")

    def _update_color_profile_values(self, profile):
        """Update color profile values in GUI."""
        hsv_keys = {
            "LOWER_YELLOW_H": profile["lower"][0],
            "LOWER_YELLOW_S": profile["lower"][1],
            "LOWER_YELLOW_V": profile["lower"][2],
            "UPPER_YELLOW_H": profile["upper"][0],
            "UPPER_YELLOW_S": profile["upper"][1],
            "UPPER_YELLOW_V": profile["upper"][2],
        }

        for key, value in hsv_keys.items():
            self.config.set(key, value)
            if key in self.widget_vars:
                self.widget_vars[key].set(value)

    def _update_gui_from_config(self):
        """Update GUI elements from config values."""
        try:
            for key, var in self.widget_vars.items():
                if hasattr(var, "set"):
                    var.set(self.config.get(key))

        except Exception as e:
            self.logger.error(f"Failed to update GUI from config: {e}")

    def on_closing(self):
        """Handle application closing."""
        try:
            if self.bot_instance:
                self.stop_bot()
            self.root.destroy()

        except Exception as e:
            self.logger.error(f"Error during closing: {e}")
            self.root.destroy()

    def run(self):
        """Start the application main loop."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.logger.info("Application interrupted by user")
        except Exception as e:
            self.logger.error(f"Application error: {e}")
        finally:
            self.on_closing()


def main():
    """Main entry point."""
    try:
        app = AimValTrackerApp()
        app.run()
    except Exception as e:
        print(f"Failed to start application: {e}")


if __name__ == "__main__":
    main()
