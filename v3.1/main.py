# ============================
# MAIN LAUNCHER V3.1
# ============================
# File này là launcher chính để chọn giữa Developer và User mode
# - Developer Mode: GUI interface đầy đủ tính năng cho development
# - User Mode: CLI interface đơn giản cho end user

import os
import sys


def print_header():
    """In header của ứng dụng"""
    print("=" * 62)
    print("                    AimVal V3.1 Launcher")
    print("=" * 62)
    print()


def print_mode_selection():
    """In menu chọn mode"""
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│                Select Interface Mode                        │")
    print("├─────────────────────────────────────────────────────────────┤")
    print("│                                                             │")
    print("│  [1] Developer Mode (Full Interface)                       │")
    print("│     • Complete visual interface                            │")
    print("│     • All settings with sliders                            │")
    print("│     • Real-time video display                              │")
    print("│     • ESP, UDP settings, advanced features                 │")
    print("│                                                             │")
    print("│  [2] User Mode (Simple CLI)                                │")
    print("│     • Terminal-based interface                             │")
    print("│     • Basic configuration only                             │")
    print("│     • Aimbot, Triggerbot, Anti-Recoil, Mouse settings      │")
    print("│     • No ESP, viewer, or advanced features                 │")
    print("│                                                             │")
    print("│  [0] Exit                                                  │")
    print("└─────────────────────────────────────────────────────────────┘")
    print()


def get_user_choice():
    """Lấy lựa chọn từ user"""
    while True:
        try:
            choice = input("Enter option (0-2): ").strip()
            if choice in ['0', '1', '2']:
                return int(choice)
            else:
                print("Invalid option. Please enter 0, 1, or 2.")
        except KeyboardInterrupt:
            return 0
        except Exception:
            print("Invalid input. Please try again.")


def launch_developer_mode():
    """Launch developer mode (GUI)"""
    try:
        print("Launching Developer Mode...")
        import customtkinter as ctk
        import cv2
        from gui import ViewerApp
        
        ctk.set_appearance_mode("Dark")
        app = ViewerApp()
        app.protocol("WM_DELETE_WINDOW", app._on_close)
        app.mainloop()
    except ImportError as e:
        print(f"Error importing GUI modules: {e}")
        print("Make sure all dependencies are installed:")
        print("pip install customtkinter opencv-python")
    except Exception as e:
        print(f"Error launching Developer Mode: {e}")


def launch_user_mode():
    """Launch user mode (CLI)"""
    try:
        print("Launching User Mode...")
        from main_user import UserCLI
        
        cli = UserCLI()
        cli.run()
    except ImportError as e:
        print(f"Error importing CLI modules: {e}")
        print("Make sure main_user.py is in the same directory")
    except Exception as e:
        print(f"Error launching User Mode: {e}")


def main():
    """Hàm main chính"""
    while True:
        # Xóa màn hình
        os.system('cls' if os.name == 'nt' else 'clear')
        
        # In header và menu
        print_header()
        print_mode_selection()
        
        # Lấy lựa chọn từ user
        choice = get_user_choice()
        
        if choice == 0:
            print("Goodbye!")
            break
        elif choice == 1:
            launch_developer_mode()
        elif choice == 2:
            launch_user_mode()
        
        # Nếu user thoát khỏi một mode, quay lại menu chính
        if choice in [1, 2]:
            input("\nPress Enter to return to main menu...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Unexpected error: {e}")
        input("Press Enter to exit...")
