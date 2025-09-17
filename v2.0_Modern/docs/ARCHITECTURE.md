# AimVal Tracker - Component Architecture

## Overview

The AimVal Tracker has been refactored into a modular, component-based architecture for better maintainability and organization.

## Directory Structure

```
aimval_tracker_2/
├── components/                 # UI Components (NEW)
│   ├── __init__.py
│   ├── header.py              # Header with performance metrics
│   ├── main_tab.py            # Main tab component
│   ├── aiming_tab.py          # Aiming tab component
│   ├── detection_tab.py       # Detection tab component
│   ├── advanced_tab.py        # Advanced tab component
│   ├── controls.py            # Reusable UI controls
│   └── README.md              # Components documentation
├── core/                      # Core Logic (EXISTING)
│   ├── __init__.py
│   ├── config.py              # Configuration management
│   ├── core.py                # Bot core logic
│   ├── detection.py           # Target detection
│   ├── hardware.py            # Hardware interface
│   ├── logger.py              # Logging setup
│   ├── smoothing.py           # Mouse smoothing
│   ├── tracker.py             # Target tracking
│   └── utils.py               # Utility functions
├── main.py                    # Original monolithic app
├── main_new.py                # New component-based app
├── run_components.py          # Component app launcher
├── ARCHITECTURE.md            # This file
└── requirements.txt           # Dependencies
```

## Component Architecture

### 1. Header Component
- **File**: `components/header.py`
- **Purpose**: Top-level status display
- **Features**:
  - Performance metrics (FPS, latency, CPU, RAM)
  - Connection status (Makcu, PC1)
  - Bot status (Aim, Mouse1, Mouse2)

### 2. Tab Components
- **Main Tab**: `components/main_tab.py`
  - Config profile management
  - Core settings (FPS, FOV)
  
- **Aiming Tab**: `components/aiming_tab.py`
  - Mode selection (Classic, WindMouse, Hybrid)
  - Mode-specific settings
  - Common aim settings
  
- **Detection Tab**: `components/detection_tab.py`
  - Basic detection settings
  - Noise processing (responsive grid)
  - Color profile management
  
- **Advanced Tab**: `components/advanced_tab.py`
  - Fire control settings
  - Mouse button configuration

### 3. Reusable Controls
- **File**: `components/controls.py`
- **Classes**:
  - `SliderControl` - Slider with +/- buttons
  - `SpinboxControl` - Integer input
  - `ComboboxControl` - Dropdown selection
  - `CheckboxControl` - Boolean toggle

## Benefits

### 1. Modularity
- Each component is self-contained
- Easy to modify individual features
- Clear separation of concerns

### 2. Reusability
- Controls can be reused across components
- Consistent UI behavior
- Reduced code duplication

### 3. Maintainability
- Smaller, focused files
- Easier to debug and test
- Clear component boundaries

### 4. Responsiveness
- Components adapt to window size
- Responsive grid layouts
- Modern UI design

## Migration Path

### Phase 1: Component Creation ✅
- [x] Create component files
- [x] Extract UI logic from main.py
- [x] Create reusable controls
- [x] Implement component interfaces

### Phase 2: Integration
- [ ] Update main_new.py
- [ ] Test component interactions
- [ ] Fix any integration issues

### Phase 3: Optimization
- [ ] Optimize component performance
- [ ] Add component caching
- [ ] Improve error handling

### Phase 4: Migration
- [ ] Replace main.py with component version
- [ ] Update documentation
- [ ] Add component tests

## Usage

### Running Component-Based App
```bash
python run_components.py
```

### Running Original App
```bash
python main.py
```

## Component Interface

### Standard Component Constructor
```python
def __init__(self, parent, config, widget_vars, callbacks):
    self.config = config
    self.widget_vars = widget_vars
    self.callbacks = callbacks
```

### Standard Callbacks
```python
callbacks = {
    'save_config': save_config_function,
    'load_config': load_config_function,
    'on_aim_mode_change': aim_mode_change_function,
    'on_color_profile_change': color_profile_change_function,
    'start_bot': start_bot_function,
    'stop_bot': stop_bot_function,
}
```

## Future Enhancements

1. **Component Testing**: Unit tests for each component
2. **Component Registry**: Dynamic component loading
3. **Theme System**: Customizable component themes
4. **Plugin System**: Third-party component support
5. **State Management**: Centralized state management
6. **Event System**: Component communication system

## Dependencies

- `tkinter` - Base GUI framework
- `ttkbootstrap` - Modern theme and widgets
- `psutil` - System monitoring
- `opencv-python` - Computer vision
- `numpy` - Numerical computing
- `pynput` - Input handling
- `makcu` - Hardware interface
