# AimVal Professional - Project Structure

## 📊 Architecture Overview

```
AimVal_Professional/
├── 📁 v1.0_Legacy/                    # Legacy Monolithic Version
│   ├── 📁 src/                        # Source Code
│   │   ├── 🐍 config.py              # Configuration Management
│   │   ├── 🐍 controller.py          # Hardware Controller
│   │   ├── 🐍 mapping.py             # Input Mapping
│   │   ├── 🐍 smoothing.py           # Mouse Smoothing
│   │   ├── 🐍 tracker.py             # Main Tracking Logic
│   │   ├── 🐍 ui.py                  # User Interface
│   │   ├── 🐍 utils.py               # Utility Functions
│   │   └── 🐍 webui.py               # Web Interface
│   ├── 📁 config/                     # Configuration Files
│   ├── 📁 docs/                       # Documentation
│   │   └── 📄 README.md
│   ├── 📁 scripts/                    # Executable Scripts
│   │   ├── 🐍 run_tracker.py         # Main Entry Point
│   │   └── 🐍 udp_viewer.py          # UDP Stream Viewer
│   ├── 📁 tests/                      # Test Files
│   └── 📄 requirements.txt            # Dependencies
│
├── 📁 v2.0_Modern/                    # Modern Component-Based Version
│   ├── 📁 src/                        # Main Application Source
│   │   ├── 🐍 main.py                # Main Application Entry Point
│   │   ├── 🐍 run_components.py      # Component Launcher
│   │   ├── 🐍 test_components.py     # Component Tests
│   │   └── 🐍 tracker.py             # Legacy Tracker Compatibility
│   ├── 📁 core/                       # Core Functionality
│   │   ├── 🐍 core.py                # Main Trigger Bot Core
│   │   ├── 🐍 detection.py           # Target Detection Algorithms
│   │   ├── 🐍 aiming.py              # Aiming Algorithms
│   │   ├── 🐍 hardware.py            # Hardware Control
│   │   └── 🐍 udp_source.py          # UDP Frame Source
│   ├── 📁 components/                 # UI Components
│   │   ├── 🐍 header.py              # Header Component
│   │   ├── 🐍 main_tab.py            # Main Settings Tab
│   │   ├── 🐍 aiming_tab.py          # Aiming Configuration
│   │   ├── 🐍 detection_tab.py       # Detection Settings
│   │   ├── 🐍 advanced_tab.py        # Advanced Settings
│   │   ├── 🐍 trigger_tab.py         # Trigger Bot Settings
│   │   ├── 🐍 controls.py            # Reusable Controls
│   │   └── 📄 README.md              # Component Documentation
│   ├── 📁 config/                     # Configuration Files
│   │   ├── 🐍 config.py              # Configuration Management
│   │   └── 📄 config.json            # Default Configuration
│   ├── 📁 utils/                      # Utility Modules
│   │   └── 🐍 logger.py              # Logging System
│   ├── 📁 docs/                       # Documentation
│   │   ├── 📄 README.md
│   │   ├── 📄 ARCHITECTURE.md
│   │   ├── 📄 FIXES.md
│   │   └── 📄 USER_GUIDE.txt
│   ├── 📁 scripts/                    # Utility Scripts
│   │   ├── 🐍 udp_sender.py
│   │   └── 🐍 udp_viewer_2.py
│   ├── 📁 tests/                      # Test Files
│   └── 📄 requirements2.txt           # Dependencies
│
├── 📁 shared/                         # Shared Resources
│   ├── 📄 config.json                # Global Configuration
│   └── 📄 aim.json                   # Aim Settings
│
├── 📁 docs/                           # Project Documentation
│   ├── 📄 README.md                  # Main Project Documentation
│   └── 📄 PROJECT_STRUCTURE.md       # This File
│
├── 📁 tools/                          # Development Tools
│   ├── 📄 run.bat                    # Windows Batch Runner
│   ├── 📄 run.ps1                    # PowerShell Runner
│   └── 📄 setup.sh                   # Linux Setup Script
│
└── 📁 venv/                           # Python Virtual Environment
```

## 🔄 Version Comparison

| Aspect | v1.0 Legacy | v2.0 Modern |
|--------|-------------|-------------|
| **Architecture** | Monolithic | Component-Based |
| **UI Framework** | Basic Tkinter | Advanced TTKBootstrap |
| **Configuration** | Simple JSON | Comprehensive System |
| **Error Handling** | Basic | Advanced |
| **Performance** | Single-threaded | Multi-threaded |
| **Maintainability** | Low | High |
| **Extensibility** | Limited | High |
| **Trigger Bot** | Basic | Advanced (50+ settings) |
| **Documentation** | Basic | Comprehensive |

## 🎯 Key Features by Version

### v1.0 Legacy Features
- ✅ Basic trigger bot functionality
- ✅ Simple UI with tkinter
- ✅ UDP frame source support
- ✅ Basic detection and aiming algorithms
- ✅ Mouse control via Makcu hardware
- ✅ Web interface support

### v2.0 Modern Features
- ✅ Advanced trigger bot with 50+ settings
- ✅ Component-based UI architecture
- ✅ Multiple firing modes (Instant, Burst, Adaptive)
- ✅ Weapon-specific settings
- ✅ Advanced timing and accuracy controls
- ✅ Target detection and filtering
- ✅ Safety systems and monitoring
- ✅ Performance optimization
- ✅ Comprehensive debugging tools
- ✅ Real-time statistics

## 🚀 Quick Start Guide

### For v1.0 Legacy
```bash
cd v1.0_Legacy
pip install -r requirements.txt
python scripts/run_tracker.py
```

### For v2.0 Modern
```bash
cd v2.0_Modern
pip install -r requirements2.txt
python src/main.py
```

## 📚 Documentation Structure

- **Main Project**: `docs/README.md`
- **v1.0 Documentation**: `v1.0_Legacy/docs/`
- **v2.0 Documentation**: `v2.0_Modern/docs/`
- **Component Documentation**: `v2.0_Modern/components/README.md`
- **Architecture Details**: `v2.0_Modern/docs/ARCHITECTURE.md`

## 🔧 Development Guidelines

### Code Organization
- **v1.0**: Monolithic approach with direct UI binding
- **v2.0**: Component-based with separation of concerns

### Configuration Management
- **v1.0**: Simple JSON files
- **v2.0**: Thread-safe configuration system

### Testing
- **v1.0**: Basic testing approach
- **v2.0**: Component-based testing with comprehensive coverage

## 📈 Future Development

### Planned Features
- Enhanced AI-based target detection
- Machine learning integration
- Cloud configuration sync
- Advanced analytics dashboard
- Plugin system for custom components

### Migration Path
- v1.0 → v2.0: Configuration export/import
- v2.0 → Future: Backward compatibility maintained

## 👨‍💻 Credits
Developed by @minhmice29
