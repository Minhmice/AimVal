# AimVal v2.0 - Modern Component-Based Version

## 📋 Overview
This is the modern AimVal tracker implementation with a component-based architecture, featuring advanced trigger bot capabilities, modular design, and comprehensive configuration options.

## 🏗️ Architecture
- **Component-Based Design**: Modular UI components for easy maintenance
- **Separation of Concerns**: Clear separation between UI, core logic, and hardware
- **Thread-Safe Configuration**: Thread-safe config management
- **Responsive UI**: Modern, responsive interface design
- **Multi-threaded**: Optimized performance with background processing

## 📁 File Structure
```
v2.0_Modern/
├── src/                        # Main application source
│   ├── main.py                # Main application entry point
│   ├── run_components.py      # Component launcher
│   ├── test_components.py     # Component tests
│   └── tracker.py             # Legacy tracker compatibility
├── core/                       # Core functionality
│   ├── core.py                # Main trigger bot core
│   ├── detection.py           # Target detection algorithms
│   ├── aiming.py              # Aiming algorithms
│   ├── hardware.py            # Hardware control
│   └── udp_source.py          # UDP frame source
├── components/                 # UI Components
│   ├── header.py              # Header component
│   ├── main_tab.py            # Main settings tab
│   ├── aiming_tab.py          # Aiming configuration
│   ├── detection_tab.py       # Detection settings
│   ├── advanced_tab.py        # Advanced settings
│   ├── trigger_tab.py         # Trigger bot settings
│   └── controls.py            # Reusable controls
├── config/                     # Configuration files
│   ├── config.py              # Configuration management
│   └── config.json            # Default configuration
├── utils/                      # Utility modules
│   └── logger.py              # Logging system
├── docs/                       # Documentation
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── FIXES.md
│   └── USER_GUIDE.txt
├── scripts/                    # Utility scripts
│   ├── udp_sender.py
│   └── udp_viewer_2.py
├── tests/                      # Test files
└── requirements2.txt           # Dependencies
```

## 🚀 Installation
1. Install Python 3.8+
2. Install dependencies: `pip install -r requirements2.txt`
3. Run: `python src/main.py`

## 🎮 Advanced Features

### Trigger Bot System
- **Multiple Firing Modes**: Instant, Burst, Adaptive
- **Weapon-Specific Settings**: Auto, Single, Burst, Spray
- **Advanced Timing**: Adaptive delays, random injection
- **Target Detection**: Priority selection, filtering, prediction
- **Safety Systems**: Health checks, ammo monitoring
- **Performance Monitoring**: Real-time statistics

### UI Components
- **Header Component**: Performance metrics and status
- **Main Tab**: Basic settings and FOV configuration
- **Aiming Tab**: Aim assist modes and parameters
- **Detection Tab**: Target detection and color profiles
- **Advanced Tab**: Fire control and mouse buttons
- **Trigger Bot Tab**: Comprehensive trigger bot settings

### Configuration System
- **50+ Trigger Bot Settings**: Comprehensive configuration options
- **Weapon Presets**: Pre-configured settings for different weapons
- **Accuracy Modes**: Normal, High, Low precision settings
- **Safety Features**: Health and ammo monitoring
- **Debug Tools**: Extensive debugging and logging

## ⚙️ Configuration

### Basic Settings
- Enable/Disable trigger bot
- Trigger delay configuration
- Shot duration and cooldown

### Advanced Modes
- **Instant Mode**: Immediate firing
- **Burst Mode**: Multiple shots with configurable count and delay
- **Adaptive Mode**: Dynamic delay based on target characteristics

### Weapon Settings
- Auto, Single, Burst, Spray modes
- Weapon-specific timing presets
- Customizable delays and cooldowns

### Accuracy & Precision
- Multiple accuracy modes (Normal, High, Low)
- Random delay injection
- Smoothing algorithms
- Anti-pattern detection

### Target Detection
- Target priority selection (Center, Closest, Largest)
- Target filtering by size and confidence
- Movement compensation
- Target prediction

### Safety Features
- Health monitoring
- Ammo checking
- Performance thresholds
- Safety limits

### Feedback & Notifications
- Sound detection
- Vibration feedback
- Visual indicators
- Statistics display

### Debug & Monitoring
- Debug modes with multiple levels
- Performance monitoring
- Statistics collection
- Real-time metrics

## 🔧 Usage
1. Launch the application
2. Configure detection settings in the Detection tab
3. Set up aiming parameters in the Aiming tab
4. Configure trigger bot settings in the Trigger Bot tab
5. Enable trigger bot and start tracking

## 📊 Performance
- Multi-threaded architecture for better performance
- Optimized detection algorithms
- Efficient memory management
- Real-time performance monitoring
- Responsive UI with smooth interactions

## 🧪 Testing
Run component tests:
```bash
python src/test_components.py
```

## 🔄 Migration from v1.0
1. Export configuration from v1.0
2. Install v2.0 dependencies
3. Import configuration through UI
4. Configure new advanced features
5. Enjoy enhanced functionality

## 📝 Status
✅ **Active Development** - Latest version with ongoing improvements and new features.

## 👨‍💻 Credits
Developed by @minhmice29