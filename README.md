# AimVal Professional - Advanced Aiming Assistant

## 🎯 Project Overview
AimVal Professional is a comprehensive aiming assistant system with two distinct versions, each optimized for different use cases and architectural approaches.

## 📁 Project Structure

```
AimVal_Professional/
├── v1.0_Legacy/                 # Legacy Version (Monolithic Architecture)
│   ├── src/                     # Source code
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── config.py            # Configuration management
│   │   ├── controller.py        # Hardware controller
│   │   ├── mapping.py           # Input mapping
│   │   ├── smoothing.py         # Mouse smoothing
│   │   ├── tracker.py           # Main tracking logic
│   │   ├── ui.py               # User interface
│   │   ├── utils.py            # Utility functions
│   │   └── webui.py            # Web interface
│   ├── config/                  # Configuration files
│   ├── docs/                    # Documentation
│   │   └── README.md
│   ├── scripts/                 # Executable scripts
│   │   ├── run_tracker.py
│   │   └── udp_viewer.py
│   ├── tests/                   # Test files
│   └── requirements.txt         # Dependencies
│
├── v2.0_Modern/                 # Modern Version (Component-Based Architecture)
│   ├── src/                     # Main application source
│   │   ├── main.py             # Main application entry point
│   │   ├── run_components.py   # Component launcher
│   │   ├── test_components.py  # Component tests
│   │   └── tracker.py          # Legacy tracker compatibility
│   ├── core/                    # Core functionality
│   │   ├── core.py             # Main trigger bot core
│   │   ├── detection.py        # Target detection algorithms
│   │   ├── aiming.py           # Aiming algorithms
│   │   ├── hardware.py         # Hardware control
│   │   └── udp_source.py       # UDP frame source
│   ├── components/              # UI Components
│   │   ├── __init__.py
│   │   ├── header.py           # Header component
│   │   ├── main_tab.py         # Main settings tab
│   │   ├── aiming_tab.py       # Aiming configuration
│   │   ├── detection_tab.py    # Detection settings
│   │   ├── advanced_tab.py     # Advanced settings
│   │   ├── trigger_tab.py      # Trigger bot settings
│   │   ├── controls.py         # Reusable controls
│   │   └── README.md           # Component documentation
│   ├── config/                  # Configuration files
│   │   ├── config.py           # Configuration management
│   │   └── config.json         # Default configuration
│   ├── utils/                   # Utility modules
│   │   └── logger.py           # Logging system
│   ├── docs/                    # Documentation
│   │   ├── README.md
│   │   ├── ARCHITECTURE.md
│   │   ├── FIXES.md
│   │   └── USER_GUIDE.txt
│   ├── scripts/                 # Utility scripts
│   │   ├── udp_sender.py
│   │   └── udp_viewer_2.py
│   ├── tests/                   # Test files
│   └── requirements2.txt        # Dependencies
│
├── shared/                      # Shared resources
│   ├── config.json             # Global configuration
│   └── aim.json                # Aim settings
│
├── docs/                       # Project documentation
│   └── README.md               # Main project documentation
│
├── tools/                      # Development tools
│   ├── run.bat                 # Windows batch runner
│   ├── run.ps1                 # PowerShell runner
│   └── setup.sh                # Linux setup script
│
└── venv/                       # Python virtual environment
```

## 🚀 Quick Start

### Version 1.0 (Legacy)
```bash
cd v1.0_Legacy
pip install -r requirements.txt
python scripts/run_tracker.py
```

### Version 2.0 (Modern)
```bash
cd v2.0_Modern
pip install -r requirements2.txt
python src/main.py
```

## 🔧 Features Comparison

| Feature | v1.0 Legacy | v2.0 Modern |
|---------|-------------|-------------|
| Architecture | Monolithic | Component-Based |
| UI Framework | Basic Tkinter | Advanced TTKBootstrap |
| Trigger Bot | Basic | Advanced (50+ settings) |
| Configuration | Simple JSON | Comprehensive system |
| Error Handling | Basic | Advanced |
| Performance | Single-threaded | Multi-threaded |
| Maintainability | Low | High |
| Extensibility | Limited | High |

## 🎮 Advanced Trigger Bot Features (v2.0)

### Core Features
- **Multiple Firing Modes**: Instant, Burst, Adaptive
- **Weapon-Specific Settings**: Auto, Single, Burst, Spray
- **Advanced Timing**: Adaptive delays, random injection
- **Target Detection**: Priority selection, filtering, prediction
- **Safety Systems**: Health checks, ammo monitoring
- **Performance Monitoring**: Real-time statistics

### Configuration Options
- 50+ trigger bot settings
- Weapon-specific presets
- Accuracy modes (Normal, High, Low)
- Movement compensation
- Anti-pattern detection
- Debug and logging systems

## 📚 Documentation

- **v1.0 Documentation**: `v1.0_Legacy/docs/`
- **v2.0 Documentation**: `v2.0_Modern/docs/`
- **Project Documentation**: `docs/`
- **Component Documentation**: `v2.0_Modern/components/README.md`

## 🛠️ Development

### Prerequisites
- Python 3.8+
- OpenCV
- NumPy
- TTKBootstrap (v2.0 only)
- Makcu hardware (optional)

### Setup
1. Clone the repository
2. Create virtual environment: `python -m venv venv`
3. Activate virtual environment
4. Install dependencies for desired version
5. Run the application

## 📄 License
This project is developed by @minhmice29

## 🤝 Contributing
Please refer to the individual version documentation for contribution guidelines.

## ⚠️ Disclaimer
This software is for educational purposes only. Use responsibly and in accordance with applicable laws and game terms of service.
