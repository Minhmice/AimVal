# AimVal V3.1

## 🎯 Overview
AimVal V3.1 là phiên bản cải tiến với 2 interface riêng biệt:
- **Developer Mode**: GUI interface đầy đủ tính năng cho development
- **User Mode**: CLI interface đơn giản cho end user

## 🚀 Quick Start

### Chạy ứng dụng:
```bash
python main.py
```

### Chọn mode:
1. **Developer Mode** - Interface đầy đủ với GUI
2. **User Mode** - Interface đơn giản với CLI

## 📁 File Structure

```
v3.1/
├── main.py                 # Launcher chính (chọn mode)
├── main_developer.py       # Developer mode (GUI)
├── main_user.py           # User mode (CLI)
├── gui.py                 # GUI interface
├── aim.py                 # Aimbot logic
├── anti_recoil.py         # Anti-recoil system
├── trigger.py             # Triggerbot logic
├── detection.py           # AI detection
├── mouse.py               # Mouse control
├── config.py              # Configuration
├── configs/               # Config files
│   ├── default.json
│   ├── best_config.json
│   └── ...
└── requirements.txt       # Dependencies
```

## 🎮 Features

### Developer Mode (GUI)
- ✅ Complete visual interface
- ✅ Real-time video display
- ✅ All settings with sliders
- ✅ ESP, UDP settings
- ✅ Advanced features
- ✅ Config management
- ✅ Performance monitoring
- ✅ **Auto-start UDP on port 8080**

### User Mode (CLI)
- ✅ Simple terminal interface
- ✅ Basic configuration only
- ✅ Aimbot settings
- ✅ Triggerbot settings
- ✅ Anti-recoil settings
- ✅ Mouse settings
- ✅ Config save/load
- ✅ Real-time status display
- ✅ **Auto-start UDP on port 8080**
- ✅ **UDP Stream status indicator**
- ✅ **Auto-refresh status every 1 second**

## ⚙️ Configuration

### Aimbot Settings
- X/Y Speed (0.1-2000.0)
- FOV Size (1-1000)
- Smoothing (1-30)
- Smoothing FOV (1-30)
- Enable/Disable toggle

### Triggerbot Settings
- FOV Size (1-300)
- Delay (0.0-1.0 seconds)
- Fire Rate (10-1000 ms)
- Enable/Disable toggle

### Anti-Recoil Settings
- Compensation Strength (0-100%)
- Start Delay (0-1000 ms)
- Duration per Level (10-200 ms)
- Y Recoil (-50 to 50)
- Jitter X/Y (0-20)
- Enable/Disable toggle

### Mouse Settings
- Mouse DPI (100-32000)
- In-game Sensitivity (0.1-2000.0)
- Max Speed (100-5000)

## 🔧 Installation

1. Clone repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run application:
```bash
python main.py
```

## 📋 Requirements

- Python 3.7+
- OpenCV
- CustomTkinter
- NumPy
- Other dependencies in requirements.txt

## 🎯 Usage

### Developer Mode
1. Chọn option [1] từ main menu
2. Sử dụng GUI interface đầy đủ
3. Tất cả tính năng development có sẵn

### User Mode
1. Chọn option [2] từ main menu
2. Sử dụng menu số đơn giản (1-6)
3. Chỉ config các tính năng cơ bản

### Config Management
- **Save**: Lưu cấu hình hiện tại
- **Load**: Tải cấu hình từ file
- **Auto-save**: Tự động lưu khi thay đổi

## 🔒 Security

### User Mode Limitations
- ❌ No ESP/viewer access
- ❌ No UDP port configuration
- ❌ No advanced debugging
- ❌ No model management
- ✅ Basic functionality only

### Developer Mode
- ✅ Full access to all features
- ✅ Advanced debugging
- ✅ Model management
- ✅ Performance monitoring

## 📊 Performance

- **Target FPS**: 80 FPS
- **UDP Port**: 8080 (auto-start - không cần config)
- **Memory Usage**: ~245 MB
- **CPU Usage**: ~15%
- **Detection Accuracy**: 94%+

## 🚀 Auto-Start Features

### UDP Auto-Start
- ✅ Tự động khởi động UDP khi mở ứng dụng
- ✅ Port mặc định: 8080
- ✅ Không cần config hay chọn gì cả
- ✅ Hoạt động cho cả GUI và CLI mode
- ✅ Tự động kết nối với video stream

## 🆕 V3.1 Updates

- ✅ Dual interface system (GUI + CLI)
- ✅ Simplified user experience
- ✅ **Auto-start UDP (không cần config)**
- ✅ Enhanced config management
- ✅ Improved performance
- ✅ Better error handling
- ✅ Real-time status monitoring

## 📞 Support

For issues or questions:
1. Check README.md
2. Review configuration files
3. Check console output for errors
4. Ensure all dependencies are installed

## 📄 License

Private use only. Not for distribution.
