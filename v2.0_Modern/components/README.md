# Components Architecture

This directory contains modular UI components for the AimVal Tracker application.

## Structure

```
components/
├── __init__.py              # Package initialization
├── header.py                # Header component with performance metrics
├── main_tab.py              # Main tab component
├── aiming_tab.py            # Aiming tab component  
├── detection_tab.py         # Detection tab component
├── advanced_tab.py          # Advanced tab component
├── controls.py              # Reusable UI controls
└── README.md               # This file
```

## Components

### HeaderComponent (`header.py`)
- **Purpose**: Displays performance metrics and bot status
- **Features**:
  - FPS, latency, CPU, RAM display
  - Connection status (Makcu, PC1)
  - Bot status (Aim, Mouse1, Mouse2)
- **Methods**:
  - `update_performance(fps, latency, cpu, ram)`
  - `update_connection_status(makcu_connected, pc1_ip)`
  - `update_bot_status(aim_active, mouse1_active, mouse2_active)`

### MainTabComponent (`main_tab.py`)
- **Purpose**: Main tab with config profile and core settings
- **Features**:
  - Config file save/load
  - FPS limit setting
  - FOV resolution selection
- **Dependencies**: `controls.py` for sliders

### AimingTabComponent (`aiming_tab.py`)
- **Purpose**: Aiming tab with mode selection and settings
- **Features**:
  - Mode selection (Classic, WindMouse, Hybrid)
  - Mode-specific settings
  - Common aim settings
- **Methods**:
  - `show_mode_frame(mode)` - Switch between mode frames

### DetectionTabComponent (`detection_tab.py`)
- **Purpose**: Detection tab with morphology and color settings
- **Features**:
  - Basic detection settings
  - Noise processing (responsive grid)
  - Verification settings
  - Color profile selection
- **Dependencies**: `controls.py` for sliders and spinboxes

### AdvancedTabComponent (`advanced_tab.py`)
- **Purpose**: Advanced tab with fire control and mouse settings
- **Features**:
  - Fire control settings
  - Mouse button configuration
  - Trigger delays
- **Dependencies**: `controls.py` for sliders

### Controls (`controls.py`)
- **Purpose**: Reusable UI controls
- **Classes**:
  - `SliderControl` - Slider with +/- buttons
  - `SpinboxControl` - Integer spinbox
  - `ComboboxControl` - Dropdown selection
  - `CheckboxControl` - Boolean checkbox

## Usage

```python
from components.header import HeaderComponent
from components.main_tab import MainTabComponent

# Create component
header = HeaderComponent(parent, config, bot_instance)

# Update component
header.update_performance(fps=60, latency=16, cpu=25, ram=45)
```

## Benefits

1. **Modularity**: Each component is self-contained
2. **Reusability**: Controls can be reused across components
3. **Maintainability**: Easy to modify individual components
4. **Testability**: Components can be tested independently
5. **Responsive**: Components adapt to window size changes

## Dependencies

- `tkinter` - Base GUI framework
- `ttkbootstrap` - Modern theme and widgets
- `config.py` - Configuration management
- `core.py` - Bot core logic
- `hardware.py` - Hardware interface
