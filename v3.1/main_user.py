# ============================
# MAIN USER - CLI INTERFACE FOR END USERS
# ============================
# File này là CLI interface đơn giản cho end user
# Chỉ có các tính năng cơ bản: aimbot, triggerbot, anti-recoil, mouse config
# Không có ESP, viewer, UDP settings - chỉ config cơ bản

import os
import sys
import time
import threading
import json
from config import config
from aim import AimTracker
from anti_recoil import AntiRecoil
from trigger import TriggerBot
from esp import DetectionEngine
from viewer import (
    _LatestBytesStore,
    _Decoder,
    _Receiver,
    SimpleFrameStore,
    DisplayThread,
)

# ========== MAPPING CÁC NÚT CHUỘT ==========
BUTTONS = {
    0: "Left Mouse Button",
    1: "Right Mouse Button",
    2: "Middle Mouse Button",
    3: "Side Mouse 4 Button",
    4: "Side Mouse 5 Button",
}

# Reverse mapping để tìm button code từ tên
BUTTON_NAMES_TO_CODE = {v: k for k, v in BUTTONS.items()}


class UserCLI:
    """
    CLI INTERFACE CHO END USER
    - Interface đơn giản với menu số
    - Chỉ config các tính năng cơ bản
    - Không có ESP, viewer, UDP settings
    - Real-time status display
    """
    
    def __init__(self):
        """Khởi tạo CLI interface"""
        self.running = True
        self.connected = False
        
        # Status metrics (khởi tạo mặc định)
        self.current_fps = 0
        self.current_latency = 0
        self.stream_active = False  # Trạng thái UDP stream
        self.last_frame_time = 0    # Thời gian nhận frame cuối
        self.in_menu = True         # Đang ở main menu hay không
        self.last_status_update = time.time()  # Lần update cuối
        
        # UDP và video (ẩn khỏi user)
        self.receiver = None
        self.rx_store = _LatestBytesStore()
        self.decoder = _Decoder()
        self.last_decoded_seq = -1
        self.last_bgr = None
        
        # Các module chính
        self.detection_engine = DetectionEngine()
        self.tracker = AimTracker(app=self, detection_engine=self.detection_engine, target_fps=80)
        self.anti_recoil = AntiRecoil(app=self)
        self.triggerbot = TriggerBot(self.detection_engine)
        
        # Status monitoring
        self.status_thread = None
        self.start_status_monitoring()
        
        # Tự động start UDP (ẩn khỏi user)
        self._start_udp_auto()
    
    def _start_udp_auto(self):
        """
        HÀM TỰ ĐỘNG KHỞI ĐỘNG UDP
        Tự động start UDP với port mặc định (8080) khi khởi động CLI
        User không cần phải chọn hay config gì cả
        """
        try:
            port = 8080  # Port mặc định
            rcvbuf = 256
            max_assembly = 256 * 1024 * 1024
            
            print(f"[CLI] Auto-starting UDP on port {port}...")
            
            self.rx_store = _LatestBytesStore()
            self.decoder = _Decoder()
            self.last_decoded_seq = -1
            self.last_bgr = None
            
            self.receiver = _Receiver("0.0.0.0", port, rcvbuf, max_assembly, self.rx_store)
            self.receiver.start()
            self.connected = True
            print(f"[CLI] ✓ UDP auto-started successfully on port {port}")
            print(f"[CLI] Waiting for video stream... (FPS will show when data arrives)")
        except Exception as e:
            self.connected = False
            print(f"[CLI] ✗ UDP auto-start failed: {e}")
    
    def start_status_monitoring(self):
        """Bắt đầu monitoring status"""
        self.status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self.status_thread.start()
    
    def _status_loop(self):
        """Vòng lặp monitoring status"""
        while self.running:
            try:
                if self.receiver is not None:
                    self.connected = True
                    buf, seq, avg_ms, avg_fps = self.rx_store.get_latest()
                    
                    # Kiểm tra có stream data không
                    if buf is not None and len(buf) > 0:
                        self.stream_active = True
                        self.last_frame_time = time.time()
                    else:
                        # Nếu không nhận frame trong 2 giây → stream inactive
                        if time.time() - self.last_frame_time > 2.0:
                            self.stream_active = False
                    
                    if avg_ms is not None and avg_fps is not None:
                        self.current_fps = avg_fps
                        self.current_latency = avg_ms
                        # Debug: Print FPS update
                        # print(f"[CLI Status] FPS: {avg_fps:.1f}, Latency: {avg_ms:.1f}ms")
                    else:
                        self.current_fps = 0
                        self.current_latency = 0
                else:
                    self.connected = False
                    self.stream_active = False
                    self.current_fps = 0
                    self.current_latency = 0
            except Exception as e:
                self.connected = False
                self.stream_active = False
                self.current_fps = 0
                self.current_latency = 0
                # Debug: Print error
                # print(f"[CLI Status Error] {e}")
            
            time.sleep(0.5)  # Update mỗi 500ms
    
    def get_latest_frame(self):
        """Lấy frame mới nhất từ UDP"""
        try:
            buf, seq, _, _ = self.rx_store.get_latest()
            if buf is None:
                return None
            if seq == self.last_decoded_seq and self.last_bgr is not None:
                return self.last_bgr
            frame = self.decoder.decode_bgr(buf)
            if frame is None or frame.size == 0:
                return None
            self.last_decoded_seq = seq
            self.last_bgr = frame
            return frame
        except Exception:
            return None
    
    def clear_screen(self):
        """Xóa màn hình"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_header(self):
        """In header của ứng dụng"""
        print("=" * 62)
        print("                    AimVal V3.1 User")
        print("=" * 62)
        print()
    
    def print_status(self):
        """In status hiện tại"""
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│                Client Status                                │")
        print("├─────────────────────────────────────────────────────────────┤")
        
        # UDP Stream Status
        if self.stream_active:
            stream_status = "● Receiving"
        else:
            stream_status = "○ Waiting..."
        print(f"│  UDP Stream: [{stream_status}]")
        
        # FPS và Latency
        fps_text = f"{self.current_fps:.1f}" if hasattr(self, 'current_fps') and self.current_fps > 0 else "--"
        latency_text = f"{self.current_latency:.1f}" if hasattr(self, 'current_latency') and self.current_latency > 0 else "--"
        print(f"│  FPS: {fps_text:<8} Latency: {latency_text}ms")
        
        # Aimbot status
        aim_status = "● Active" if getattr(config, "enableaim", False) else "○ Inactive"
        print(f"│  Aimbot: [{aim_status}]")
        
        # Triggerbot status
        trigger_status = "● Active" if getattr(config, "enabletb", False) else "○ Inactive"
        print(f"│  Triggerbot: [{trigger_status}]")
        
        # Anti-Recoil status
        recoil_status = "● Active" if getattr(config, "anti_recoil_enabled", False) else "○ Inactive"
        print(f"│  Anti-Recoil: [{recoil_status}]")
        
        # Thời gian cập nhật
        import datetime
        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"│  Last Update: {current_time}                                    │")
        
        print("└─────────────────────────────────────────────────────────────┘")
        print()
    
    def print_main_menu(self):
        """In main menu"""
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│                Config Panel                                 │")
        print("├─────────────────────────────────────────────────────────────┤")
        print("│  [1] Aimbot Settings                                       │")
        print("│  [2] Triggerbot Settings                                   │")
        print("│  [3] Anti-Recoil Settings                                  │")
        print("│  [4] Mouse Settings                                        │")
        print("│  [5] Save Config                                           │")
        print("│  [6] Load Config                                           │")
        print("│  [R] Manual Refresh                                        │")
        print("│  [0] Exit                                                  │")
        print("└─────────────────────────────────────────────────────────────┘")
        print("  ⟳ Status auto-updates every 1 second")
        print()
    
    def get_input(self, prompt, input_type=str, min_val=None, max_val=None):
        """Lấy input từ user với validation"""
        while True:
            try:
                user_input = input(prompt).strip()
                
                # Xử lý phím đặc biệt
                if user_input.upper() == 'R' and input_type == int:
                    return -1  # Signal để refresh
                
                if input_type == int:
                    value = int(user_input)
                elif input_type == float:
                    value = float(user_input)
                else:
                    value = user_input
                
                if min_val is not None and value < min_val:
                    print(f"Value must be at least {min_val}")
                    continue
                if max_val is not None and value > max_val:
                    print(f"Value must be at most {max_val}")
                    continue
                
                return value
            except ValueError:
                if user_input.upper() == 'R':
                    return -1  # Signal để refresh
                print("Invalid input. Please try again.")
            except KeyboardInterrupt:
                return None
    
    def aimbot_menu(self):
        """Menu cài đặt Aimbot"""
        while True:
            self.clear_screen()
            self.print_header()
            
            # Current settings
            print("┌─────────────────────────────────────────────────────────────┐")
            print("│                    Aimbot Settings                          │")
            print("├─────────────────────────────────────────────────────────────┤")
            print("│                                                             │")
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Current Settings                         │ │")
            print("│  │                                                         │ │")
            
            aim_enabled = "Enabled" if getattr(config, "enableaim", False) else "Disabled"
            aim_btn1 = BUTTONS.get(getattr(config, 'aim_button_1', 1), "Right Mouse Button")
            aim_btn2 = BUTTONS.get(getattr(config, 'aim_button_2', 2), "Middle Mouse Button")
            
            print(f"│  │  Status: [{'●' if getattr(config, 'enableaim', False) else '○'}] {aim_enabled:<40} │ │")
            print(f"│  │  X Speed: {getattr(config, 'normal_x_speed', 0.5):<45} │ │")
            print(f"│  │  Y Speed: {getattr(config, 'normal_y_speed', 0.5):<45} │ │")
            print(f"│  │  FOV Size: {getattr(config, 'fovsize', 300):<44} │ │")
            print(f"│  │  Smoothing: {getattr(config, 'normalsmooth', 10):<42} │ │")
            print(f"│  │  Smoothing FOV: {getattr(config, 'normalsmoothfov', 10):<38} │ │")
            print(f"│  │  Aim Button 1: {aim_btn1:<41} │ │")
            print(f"│  │  Aim Button 2: {aim_btn2:<41} │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("│                                                             │")
            
            # Menu options
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Adjust Settings                          │ │")
            print("│  │                                                         │ │")
            print("│  │  [1] Toggle Enable/Disable                             │ │")
            print("│  │  [2] Set X Speed (0.1-2000.0)                          │ │")
            print("│  │  [3] Set Y Speed (0.1-2000.0)                          │ │")
            print("│  │  [4] Set FOV Size (1-1000)                             │ │")
            print("│  │  [5] Set Smoothing (1-30)                              │ │")
            print("│  │  [6] Set Smoothing FOV (1-30)                          │ │")
            print("│  │  [7] Set Aim Button 1                                  │ │")
            print("│  │  [8] Set Aim Button 2                                  │ │")
            print("│  │  [0] Back to Main Menu                                 │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("└─────────────────────────────────────────────────────────────┘")
            print()
            
            choice = self.get_input("Enter option (0-8): ", int, 0, 8)
            if choice is None:
                return
            
            if choice == 0:
                return
            elif choice == 1:
                # Toggle enable/disable
                current = getattr(config, "enableaim", False)
                config.enableaim = not current
                status = "enabled" if not current else "disabled"
                print(f"Aimbot {status}")
                input("Press Enter to continue...")
            elif choice == 2:
                # Set X Speed
                new_value = self.get_input("Enter new X Speed (0.1-2000.0): ", float, 0.1, 2000.0)
                if new_value is not None:
                    config.normal_x_speed = new_value
                    self.tracker.normal_x_speed = new_value
                    print(f"X Speed updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 3:
                # Set Y Speed
                new_value = self.get_input("Enter new Y Speed (0.1-2000.0): ", float, 0.1, 2000.0)
                if new_value is not None:
                    config.normal_y_speed = new_value
                    self.tracker.normal_y_speed = new_value
                    print(f"Y Speed updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 4:
                # Set FOV Size
                new_value = self.get_input("Enter new FOV Size (1-1000): ", float, 1, 1000)
                if new_value is not None:
                    config.fovsize = new_value
                    self.tracker.fovsize = new_value
                    print(f"FOV Size updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 5:
                # Set Smoothing
                new_value = self.get_input("Enter new Smoothing (1-30): ", float, 1, 30)
                if new_value is not None:
                    config.normalsmooth = new_value
                    self.tracker.normalsmooth = new_value
                    print(f"Smoothing updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 6:
                # Set Smoothing FOV
                new_value = self.get_input("Enter new Smoothing FOV (1-30): ", float, 1, 30)
                if new_value is not None:
                    config.normalsmoothfov = new_value
                    self.tracker.normalsmoothfov = new_value
                    print(f"Smoothing FOV updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 7:
                # Set Aim Button 1
                print("\nSelect Aim Button 1:")
                for code, name in BUTTONS.items():
                    print(f"  [{code}] {name}")
                btn_choice = self.get_input("Enter button number (0-4): ", int, 0, 4)
                if btn_choice is not None:
                    config.aim_button_1 = btn_choice
                    self.tracker.aim_button_1 = btn_choice
                    print(f"Aim Button 1 updated to {BUTTONS[btn_choice]}")
                    input("Press Enter to continue...")
            elif choice == 8:
                # Set Aim Button 2
                print("\nSelect Aim Button 2:")
                for code, name in BUTTONS.items():
                    print(f"  [{code}] {name}")
                btn_choice = self.get_input("Enter button number (0-4): ", int, 0, 4)
                if btn_choice is not None:
                    config.aim_button_2 = btn_choice
                    self.tracker.aim_button_2 = btn_choice
                    print(f"Aim Button 2 updated to {BUTTONS[btn_choice]}")
                    input("Press Enter to continue...")
    
    def triggerbot_menu(self):
        """Menu cài đặt Triggerbot"""
        while True:
            self.clear_screen()
            self.print_header()
            
            # Current settings
            print("┌─────────────────────────────────────────────────────────────┐")
            print("│                    Triggerbot Settings                      │")
            print("├─────────────────────────────────────────────────────────────┤")
            print("│                                                             │")
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Current Settings                         │ │")
            print("│  │                                                         │ │")
            
            trigger_enabled = "Enabled" if getattr(config, "enabletb", False) else "Disabled"
            trigger_btn = BUTTONS.get(getattr(config, 'trigger_button', 1), "Right Mouse Button")
            
            print(f"│  │  Status: [{'●' if getattr(config, 'enabletb', False) else '○'}] {trigger_enabled:<40} │ │")
            print(f"│  │  FOV Size: {getattr(config, 'tbfovsize', 70):<44} │ │")
            print(f"│  │  Delay: {getattr(config, 'tbdelay', 0.08):.3f} seconds{'':<32} │ │")
            print(f"│  │  Fire Rate: {getattr(config, 'trigger_fire_rate_ms', 100):<41} ms │ │")
            print(f"│  │  Trigger Button: {trigger_btn:<39} │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("│                                                             │")
            
            # Menu options
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Adjust Settings                          │ │")
            print("│  │                                                         │ │")
            print("│  │  [1] Toggle Enable/Disable                             │ │")
            print("│  │  [2] Set FOV Size (1-300)                              │ │")
            print("│  │  [3] Set Delay (0.0-1.0 seconds)                       │ │")
            print("│  │  [4] Set Fire Rate (10-1000 ms)                        │ │")
            print("│  │  [5] Set Trigger Button                                │ │")
            print("│  │  [0] Back to Main Menu                                 │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("└─────────────────────────────────────────────────────────────┘")
            print()
            
            choice = self.get_input("Enter option (0-5): ", int, 0, 5)
            if choice is None:
                return
            
            if choice == 0:
                return
            elif choice == 1:
                # Toggle enable/disable
                current = getattr(config, "enabletb", False)
                config.enabletb = not current
                status = "enabled" if not current else "disabled"
                print(f"Triggerbot {status}")
                input("Press Enter to continue...")
            elif choice == 2:
                # Set FOV Size
                new_value = self.get_input("Enter new FOV Size (1-300): ", float, 1, 300)
                if new_value is not None:
                    config.tbfovsize = new_value
                    self.tracker.tbfovsize = new_value
                    print(f"FOV Size updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 3:
                # Set Delay
                new_value = self.get_input("Enter new Delay (0.0-1.0): ", float, 0.0, 1.0)
                if new_value is not None:
                    config.tbdelay = new_value
                    self.tracker.tbdelay = new_value
                    print(f"Delay updated to {new_value} seconds")
                    input("Press Enter to continue...")
            elif choice == 4:
                # Set Fire Rate
                new_value = self.get_input("Enter new Fire Rate (10-1000): ", float, 10, 1000)
                if new_value is not None:
                    config.trigger_fire_rate_ms = new_value
                    self.tracker.fire_rate_ms = new_value
                    print(f"Fire Rate updated to {new_value} ms")
                    input("Press Enter to continue...")
            elif choice == 5:
                # Set Trigger Button
                print("\nSelect Trigger Button:")
                for code, name in BUTTONS.items():
                    print(f"  [{code}] {name}")
                btn_choice = self.get_input("Enter button number (0-4): ", int, 0, 4)
                if btn_choice is not None:
                    config.trigger_button = btn_choice
                    self.tracker.trigger_button = btn_choice
                    print(f"Trigger Button updated to {BUTTONS[btn_choice]}")
                    input("Press Enter to continue...")
    
    def anti_recoil_menu(self):
        """Menu cài đặt Anti-Recoil"""
        while True:
            self.clear_screen()
            self.print_header()
            
            # Current settings
            print("┌─────────────────────────────────────────────────────────────┐")
            print("│                    Anti-Recoil Settings                     │")
            print("├─────────────────────────────────────────────────────────────┤")
            print("│                                                             │")
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Current Settings                         │ │")
            print("│  │                                                         │ │")
            
            recoil_enabled = "Enabled" if getattr(config, "anti_recoil_enabled", False) else "Disabled"
            recoil_btn1 = BUTTONS.get(getattr(config, 'anti_recoil_key_1', 3), "Side Mouse 4 Button")
            recoil_btn2 = BUTTONS.get(getattr(config, 'anti_recoil_key_2', 4), "Side Mouse 5 Button")
            
            print(f"│  │  Status: [{'●' if getattr(config, 'anti_recoil_enabled', False) else '○'}] {recoil_enabled:<40} │ │")
            print(f"│  │  Compensation Strength: {getattr(config, 'anti_recoil_compensation_strength', 70):<30}% │ │")
            print(f"│  │  Start Delay: {getattr(config, 'anti_recoil_start_delay', 120):<42} ms │ │")
            print(f"│  │  Duration per Level: {getattr(config, 'anti_recoil_duration_per_level', 40):<34} ms │ │")
            print(f"│  │  Y Recoil: {getattr(config, 'anti_recoil_y', 0):<47} │ │")
            print(f"│  │  Jitter X: {getattr(config, 'anti_recoil_jitter_x', 0):<46} │ │")
            print(f"│  │  Jitter Y: {getattr(config, 'anti_recoil_jitter_y', 0):<46} │ │")
            print(f"│  │  Anti-Recoil Key 1: {recoil_btn1:<36} │ │")
            print(f"│  │  Anti-Recoil Key 2: {recoil_btn2:<36} │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("│                                                             │")
            
            # Menu options
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Adjust Settings                          │ │")
            print("│  │                                                         │ │")
            print("│  │  [1] Toggle Enable/Disable                             │ │")
            print("│  │  [2] Set Compensation Strength (0-100%)                │ │")
            print("│  │  [3] Set Start Delay (0-1000 ms)                       │ │")
            print("│  │  [4] Set Duration per Level (10-200 ms)                │ │")
            print("│  │  [5] Set Y Recoil (-50 to 50)                          │ │")
            print("│  │  [6] Set Jitter X (0-20)                               │ │")
            print("│  │  [7] Set Jitter Y (0-20)                               │ │")
            print("│  │  [8] Set Anti-Recoil Key 1                             │ │")
            print("│  │  [9] Set Anti-Recoil Key 2                             │ │")
            print("│  │  [0] Back to Main Menu                                 │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("└─────────────────────────────────────────────────────────────┘")
            print()
            
            choice = self.get_input("Enter option (0-9): ", int, 0, 9)
            if choice is None:
                return
            
            if choice == 0:
                return
            elif choice == 1:
                # Toggle enable/disable
                current = getattr(config, "anti_recoil_enabled", False)
                config.anti_recoil_enabled = not current
                self.anti_recoil.update_config()
                status = "enabled" if not current else "disabled"
                print(f"Anti-Recoil {status}")
                input("Press Enter to continue...")
            elif choice == 2:
                # Set Compensation Strength
                new_value = self.get_input("Enter compensation strength (0-100): ", float, 0, 100)
                if new_value is not None:
                    config.anti_recoil_compensation_strength = new_value
                    self.anti_recoil.update_config()
                    print(f"Compensation strength updated to {new_value}%")
                    input("Press Enter to continue...")
            elif choice == 3:
                # Set Start Delay
                new_value = self.get_input("Enter start delay (0-1000): ", float, 0, 1000)
                if new_value is not None:
                    config.anti_recoil_start_delay = new_value
                    self.anti_recoil.update_config()
                    print(f"Start delay updated to {new_value} ms")
                    input("Press Enter to continue...")
            elif choice == 4:
                # Set Duration per Level
                new_value = self.get_input("Enter duration per level (10-200): ", float, 10, 200)
                if new_value is not None:
                    config.anti_recoil_duration_per_level = new_value
                    self.anti_recoil.update_config()
                    print(f"Duration per level updated to {new_value} ms")
                    input("Press Enter to continue...")
            elif choice == 5:
                # Set Y Recoil
                new_value = self.get_input("Enter Y Recoil (-50 to 50): ", float, -50, 50)
                if new_value is not None:
                    config.anti_recoil_y = new_value
                    self.anti_recoil.y_recoil = new_value
                    print(f"Y Recoil updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 6:
                # Set Jitter X
                new_value = self.get_input("Enter Jitter X (0-20): ", float, 0, 20)
                if new_value is not None:
                    config.anti_recoil_jitter_x = new_value
                    self.anti_recoil.random_jitter_x = new_value
                    print(f"Jitter X updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 7:
                # Set Jitter Y
                new_value = self.get_input("Enter Jitter Y (0-20): ", float, 0, 20)
                if new_value is not None:
                    config.anti_recoil_jitter_y = new_value
                    self.anti_recoil.random_jitter_y = new_value
                    print(f"Jitter Y updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 8:
                # Set Anti-Recoil Key 1
                print("\nSelect Anti-Recoil Key 1:")
                for code, name in BUTTONS.items():
                    print(f"  [{code}] {name}")
                btn_choice = self.get_input("Enter button number (0-4): ", int, 0, 4)
                if btn_choice is not None:
                    config.anti_recoil_key_1 = btn_choice
                    self.anti_recoil.anti_recoil_key_1 = btn_choice
                    print(f"Anti-Recoil Key 1 updated to {BUTTONS[btn_choice]}")
                    input("Press Enter to continue...")
            elif choice == 9:
                # Set Anti-Recoil Key 2
                print("\nSelect Anti-Recoil Key 2:")
                for code, name in BUTTONS.items():
                    print(f"  [{code}] {name}")
                btn_choice = self.get_input("Enter button number (0-4): ", int, 0, 4)
                if btn_choice is not None:
                    config.anti_recoil_key_2 = btn_choice
                    self.anti_recoil.anti_recoil_key_2 = btn_choice
                    print(f"Anti-Recoil Key 2 updated to {BUTTONS[btn_choice]}")
                    input("Press Enter to continue...")
    
    def mouse_menu(self):
        """Menu cài đặt Mouse"""
        while True:
            self.clear_screen()
            self.print_header()
            
            # Current settings
            print("┌─────────────────────────────────────────────────────────────┐")
            print("│                    Mouse Settings                           │")
            print("├─────────────────────────────────────────────────────────────┤")
            print("│                                                             │")
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Current Settings                         │ │")
            print("│  │                                                         │ │")
            print(f"│  │  Mouse DPI: {getattr(config, 'mouse_dpi', 800):<45} │ │")
            print(f"│  │  In-game Sensitivity: {getattr(config, 'in_game_sens', 0.235):<34} │ │")
            print(f"│  │  Max Speed: {getattr(config, 'max_speed', 1000):<45} │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("│                                                             │")
            
            # Menu options
            print("│  ┌─────────────────────────────────────────────────────────┐ │")
            print("│  │                Adjust Settings                          │ │")
            print("│  │                                                         │ │")
            print("│  │  [1] Set Mouse DPI (100-32000)                         │ │")
            print("│  │  [2] Set In-game Sensitivity (0.1-2000.0)              │ │")
            print("│  │  [3] Set Max Speed (100-5000)                          │ │")
            print("│  │  [0] Back to Main Menu                                 │ │")
            print("│  └─────────────────────────────────────────────────────────┘ │")
            print("└─────────────────────────────────────────────────────────────┘")
            print()
            
            choice = self.get_input("Enter option (0-3): ", int, 0, 3)
            if choice is None:
                return
            
            if choice == 0:
                return
            elif choice == 1:
                # Set Mouse DPI
                new_value = self.get_input("Enter Mouse DPI (100-32000): ", int, 100, 32000)
                if new_value is not None:
                    config.mouse_dpi = new_value
                    self.tracker.mouse_dpi = new_value
                    print(f"Mouse DPI updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 2:
                # Set In-game Sensitivity
                new_value = self.get_input("Enter In-game Sensitivity (0.1-2000.0): ", float, 0.1, 2000.0)
                if new_value is not None:
                    config.in_game_sens = new_value
                    self.tracker.in_game_sens = new_value
                    print(f"In-game Sensitivity updated to {new_value}")
                    input("Press Enter to continue...")
            elif choice == 3:
                # Set Max Speed
                new_value = self.get_input("Enter Max Speed (100-5000): ", float, 100, 5000)
                if new_value is not None:
                    config.max_speed = new_value
                    self.tracker.max_speed = new_value
                    print(f"Max Speed updated to {new_value}")
                    input("Press Enter to continue...")
    
    def save_config_menu(self):
        """Menu lưu config"""
        self.clear_screen()
        self.print_header()
        
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│                    Save Config                              │")
        print("├─────────────────────────────────────────────────────────────┤")
        print("│                                                             │")
        
        config_name = input("Enter config name (without .json): ").strip()
        if not config_name:
            print("Config name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        config_path = f"configs/{config_name}.json"
        
        # Tạo thư mục configs nếu chưa có
        os.makedirs("configs", exist_ok=True)
        
        # Lưu config
        try:
            config_data = {
                # Aimbot settings
                "enableaim": getattr(config, "enableaim", False),
                "normal_x_speed": getattr(config, "normal_x_speed", 0.5),
                "normal_y_speed": getattr(config, "normal_y_speed", 0.5),
                "fovsize": getattr(config, "fovsize", 300),
                "normalsmooth": getattr(config, "normalsmooth", 10),
                "normalsmoothfov": getattr(config, "normalsmoothfov", 10),
                "aim_button_1": getattr(config, "aim_button_1", 1),
                "aim_button_2": getattr(config, "aim_button_2", 2),
                
                # Triggerbot settings
                "enabletb": getattr(config, "enabletb", False),
                "tbfovsize": getattr(config, "tbfovsize", 70),
                "tbdelay": getattr(config, "tbdelay", 0.08),
                "trigger_fire_rate_ms": getattr(config, "trigger_fire_rate_ms", 100),
                "trigger_button": getattr(config, "trigger_button", 1),
                
                # Anti-recoil settings
                "anti_recoil_enabled": getattr(config, "anti_recoil_enabled", False),
                "anti_recoil_compensation_strength": getattr(config, "anti_recoil_compensation_strength", 70),
                "anti_recoil_start_delay": getattr(config, "anti_recoil_start_delay", 120),
                "anti_recoil_duration_per_level": getattr(config, "anti_recoil_duration_per_level", 40),
                "anti_recoil_y": getattr(config, "anti_recoil_y", 0),
                "anti_recoil_jitter_x": getattr(config, "anti_recoil_jitter_x", 0),
                "anti_recoil_jitter_y": getattr(config, "anti_recoil_jitter_y", 0),
                "anti_recoil_key_1": getattr(config, "anti_recoil_key_1", 3),
                "anti_recoil_key_2": getattr(config, "anti_recoil_key_2", 4),
                
                # Mouse settings
                "mouse_dpi": getattr(config, "mouse_dpi", 800),
                "in_game_sens": getattr(config, "in_game_sens", 0.235),
                "max_speed": getattr(config, "max_speed", 1000),
            }
            
            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=4)
            
            print(f"Config saved successfully: {config_path}")
            
        except Exception as e:
            print(f"Error saving config: {e}")
        
        input("Press Enter to continue...")
    
    def load_config_menu(self):
        """Menu tải config"""
        self.clear_screen()
        self.print_header()
        
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│                    Load Config                              │")
        print("├─────────────────────────────────────────────────────────────┤")
        print("│                                                             │")
        
        # Hiển thị danh sách config có sẵn
        configs_dir = "configs"
        if os.path.exists(configs_dir):
            config_files = [f[:-5] for f in os.listdir(configs_dir) if f.endswith(".json")]
            if config_files:
                print("│  Available configs:")
                for i, config_file in enumerate(config_files, 1):
                    print(f"│  [{i}] {config_file}")
                print("│  [0] Back to Main Menu")
                print("│                                                             │")
                
                choice = self.get_input("Select config (0-{}): ".format(len(config_files)), int, 0, len(config_files))
                if choice is None or choice == 0:
                    return
                
                if 1 <= choice <= len(config_files):
                    config_name = config_files[choice - 1]
                    self.load_config(config_name)
            else:
                print("│  No config files found!")
                input("Press Enter to continue...")
        else:
            print("│  Configs directory not found!")
            input("Press Enter to continue...")
    
    def load_config(self, config_name):
        """Tải config từ file"""
        config_path = f"configs/{config_name}.json"
        
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
            
            # Áp dụng config
            for key, value in config_data.items():
                setattr(config, key, value)
            
            # Cập nhật các module
            self.tracker.normal_x_speed = getattr(config, "normal_x_speed", 0.5)
            self.tracker.normal_y_speed = getattr(config, "normal_y_speed", 0.5)
            self.tracker.fovsize = getattr(config, "fovsize", 300)
            self.tracker.normalsmooth = getattr(config, "normalsmooth", 10)
            self.tracker.normalsmoothfov = getattr(config, "normalsmoothfov", 10)
            self.tracker.tbfovsize = getattr(config, "tbfovsize", 70)
            self.tracker.tbdelay = getattr(config, "tbdelay", 0.08)
            self.tracker.mouse_dpi = getattr(config, "mouse_dpi", 800)
            self.tracker.in_game_sens = getattr(config, "in_game_sens", 0.235)
            self.tracker.max_speed = getattr(config, "max_speed", 1000)
            
            # Cập nhật button configs
            if hasattr(self.tracker, 'aim_button_1'):
                self.tracker.aim_button_1 = getattr(config, "aim_button_1", 1)
            if hasattr(self.tracker, 'aim_button_2'):
                self.tracker.aim_button_2 = getattr(config, "aim_button_2", 2)
            if hasattr(self.tracker, 'trigger_button'):
                self.tracker.trigger_button = getattr(config, "trigger_button", 1)
            
            self.anti_recoil.update_config()
            
            print(f"Config loaded successfully: {config_name}")
            
        except Exception as e:
            print(f"Error loading config: {e}")
        
        input("Press Enter to continue...")
    
    def run(self):
        """Chạy CLI interface"""
        try:
            # Bắt đầu auto-refresh thread
            refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
            refresh_thread.start()
            
            while self.running:
                self.in_menu = True
                self.clear_screen()
                self.print_header()
                self.print_status()
                self.print_main_menu()
                
                choice = self.get_input("Enter option (0-6, R to refresh): ", int, 0, 6)
                if choice is None:
                    break
                
                self.in_menu = False  # Đã rời khỏi main menu
                
                # Xử lý refresh (R key)
                if choice == -1:
                    continue  # Refresh main menu
                
                if choice == 0:
                    break
                elif choice == 1:
                    self.aimbot_menu()
                elif choice == 2:
                    self.triggerbot_menu()
                elif choice == 3:
                    self.anti_recoil_menu()
                elif choice == 4:
                    self.mouse_menu()
                elif choice == 5:
                    self.save_config_menu()
                elif choice == 6:
                    self.load_config_menu()
        
        except KeyboardInterrupt:
            pass
        
        finally:
            self.cleanup()
    
    def _auto_refresh_loop(self):
        """Thread tự động refresh status mỗi 1 giây khi đang ở main menu"""
        while self.running:
            try:
                time.sleep(1)  # Chờ 1 giây
                
                # Chỉ refresh khi đang ở main menu và đã qua 1 giây từ lần update cuối
                if self.in_menu and (time.time() - self.last_status_update >= 1.0):
                    # Clear và re-print status
                    self._refresh_status_display()
                    self.last_status_update = time.time()
            except Exception:
                pass
    
    def _refresh_status_display(self):
        """Refresh status display tại chỗ (không clear toàn màn hình)"""
        try:
            # Di chuyển cursor về đầu status section
            # ANSI escape codes: move cursor up
            import sys
            
            # Save cursor position, clear screen, print status
            sys.stdout.write('\033[s')  # Save cursor position
            sys.stdout.write('\033[H')  # Move to top
            
            self.print_header()
            self.print_status()
            self.print_main_menu()
            
            sys.stdout.write('\033[u')  # Restore cursor position
            sys.stdout.flush()
        except Exception:
            pass  # Nếu lỗi thì bỏ qua
    
    def cleanup(self):
        """Dọn dẹp khi thoát"""
        self.running = False
        try:
            if self.receiver is not None:
                self.receiver.stop()
                self.receiver.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.tracker.stop()
        except Exception:
            pass
        print("\nGoodbye!")


if __name__ == "__main__":
    cli = UserCLI()
    cli.run()
