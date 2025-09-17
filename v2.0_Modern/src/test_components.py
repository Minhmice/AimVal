#!/usr/bin/env python3
"""Test component imports and basic functionality."""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test all component imports."""
    print("Testing component imports...")
    
    try:
        from components.header import HeaderComponent
        print("✓ HeaderComponent imported successfully")
    except ImportError as e:
        print(f"✗ HeaderComponent import failed: {e}")
        return False
    
    try:
        from components.main_tab import MainTabComponent
        print("✓ MainTabComponent imported successfully")
    except ImportError as e:
        print(f"✗ MainTabComponent import failed: {e}")
        return False
    
    try:
        from components.aiming_tab import AimingTabComponent
        print("✓ AimingTabComponent imported successfully")
    except ImportError as e:
        print(f"✗ AimingTabComponent import failed: {e}")
        return False
    
    try:
        from components.detection_tab import DetectionTabComponent
        print("✓ DetectionTabComponent imported successfully")
    except ImportError as e:
        print(f"✗ DetectionTabComponent import failed: {e}")
        return False
    
    try:
        from components.advanced_tab import AdvancedTabComponent
        print("✓ AdvancedTabComponent imported successfully")
    except ImportError as e:
        print(f"✗ AdvancedTabComponent import failed: {e}")
        return False
    
    try:
        from components.controls import SliderControl, SpinboxControl, ComboboxControl, CheckboxControl
        print("✓ Control classes imported successfully")
    except ImportError as e:
        print(f"✗ Control classes import failed: {e}")
        return False
    
    return True

def test_core_imports():
    """Test core module imports."""
    print("\nTesting core module imports...")
    
    try:
        from config import SharedConfig
        print("✓ SharedConfig imported successfully")
    except ImportError as e:
        print(f"✗ SharedConfig import failed: {e}")
        return False
    
    try:
        from core import TriggerbotCore
        print("✓ TriggerbotCore imported successfully")
    except ImportError as e:
        print(f"✗ TriggerbotCore import failed: {e}")
        return False
    
    try:
        from hardware import MakcuController
        print("✓ MakcuController imported successfully")
    except ImportError as e:
        print(f"✗ MakcuController import failed: {e}")
        return False
    
    try:
        from udp_source import UdpFrameSource
        print("✓ UdpFrameSource imported successfully")
    except ImportError as e:
        print(f"✗ UdpFrameSource import failed: {e}")
        return False
    
    try:
        from logger import setup_logging
        print("✓ setup_logging imported successfully")
    except ImportError as e:
        print(f"✗ setup_logging import failed: {e}")
        return False
    
    return True

def test_basic_ui():
    """Test basic UI creation."""
    print("\nTesting basic UI creation...")
    
    try:
        import tkinter as tk
        from ttkbootstrap import ttk, Style
        
        # Create test window
        root = tk.Tk()
        root.title("Component Test")
        root.geometry("400x300")
        
        # Apply theme
        style = Style(theme="darkly")
        
        # Create test frame
        frame = ttk.Frame(root)
        frame.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Test label
        label = ttk.Label(frame, text="Component Test - UI Working!")
        label.pack(pady=20)
        
        # Test button
        button = ttk.Button(frame, text="Test Button")
        button.pack(pady=10)
        
        print("✓ Basic UI creation successful")
        
        # Close window immediately
        root.after(1000, root.destroy)
        root.mainloop()
        
        return True
        
    except Exception as e:
        print(f"✗ Basic UI creation failed: {e}")
        return False

def main():
    """Run all tests."""
    print("AimVal Tracker - Component Test")
    print("=" * 40)
    
    # Test imports
    component_ok = test_imports()
    core_ok = test_core_imports()
    ui_ok = test_basic_ui()
    
    print("\n" + "=" * 40)
    print("Test Results:")
    print(f"Components: {'PASS' if component_ok else 'FAIL'}")
    print(f"Core Modules: {'PASS' if core_ok else 'FAIL'}")
    print(f"Basic UI: {'PASS' if ui_ok else 'FAIL'}")
    
    if component_ok and core_ok and ui_ok:
        print("\n🎉 All tests passed! Components are ready to use.")
        return True
    else:
        print("\n❌ Some tests failed. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
