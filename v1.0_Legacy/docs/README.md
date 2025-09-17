# AimVal v1.0 - Legacy Version

## 📋 Overview
This is the original AimVal tracker implementation with a traditional monolithic architecture. This version is maintained for legacy support and compatibility with older systems.

## 🏗️ Architecture
- **Monolithic Design**: All functionality integrated into single files
- **Direct UI Binding**: UI directly controls core functionality
- **Simple Configuration**: Basic JSON configuration system
- **Single-threaded**: Sequential processing approach

## 📁 File Structure
```
v1.0_Legacy/
├── src/                        # Source code
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py              # Configuration management
│   ├── controller.py           # Hardware controller
│   ├── mapping.py              # Input mapping
│   ├── smoothing.py            # Mouse smoothing
│   ├── tracker.py              # Main tracking logic
│   ├── ui.py                  # User interface
│   ├── utils.py               # Utility functions
│   └── webui.py               # Web interface
├── config/                     # Configuration files
├── docs/                       # Documentation
├── scripts/                    # Executable scripts
│   ├── run_tracker.py         # Main entry point
│   └── udp_viewer.py          # UDP stream viewer
├── tests/                      # Test files
└── requirements.txt            # Python dependencies
```

## 🚀 Installation
1. Install Python 3.8+
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python scripts/run_tracker.py`

## 🎮 Features
- Basic trigger bot functionality
- Simple UI with tkinter
- UDP frame source support
- Basic detection and aiming algorithms
- Mouse control via Makcu hardware
- Web interface support

## ⚙️ Configuration
Configuration is managed through simple JSON files:
- Basic detection settings
- Mouse sensitivity
- Trigger timing
- Hardware settings

## 🔧 Usage
1. Launch the application
2. Configure detection settings
3. Enable trigger bot
4. Start tracking

## ⚠️ Limitations
- Single-threaded architecture
- Limited configuration options
- Basic error handling
- No component separation
- Limited extensibility

## 📊 Performance
- Suitable for basic use cases
- Lower resource usage
- Simpler debugging
- Limited scalability

## 🔄 Migration to v2.0
To migrate to the modern version:
1. Export your configuration
2. Install v2.0 dependencies
3. Import configuration
4. Enjoy enhanced features

## 📝 Status
⚠️ **Legacy Version** - No longer actively developed. Use v2.0 for new features and improvements.

## 👨‍💻 Credits
Developed by @minhmice29