#!/usr/bin/env python3
"""
Test script to verify scrolling functionality works correctly.
Run this to test the UI without needing full hardware setup.
"""

import customtkinter as ctk
import tkinter as tk
import sys
import os

# Add current directory to path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config import config
    from main import ViewerApp
    
    def test_scrolling():
        """Test the scrolling functionality of the tabs."""
        print("Testing scrollable tabs...")
        
        # Set appearance
        ctk.set_appearance_mode("Dark")
        
        # Create and run the app
        app = ViewerApp()
        
        # Add some test instructions
        print("\n" + "="*50)
        print("SCROLLING TEST INSTRUCTIONS:")
        print("="*50)
        print("1. Click on each tab (Detection, Aimbot, Triggerbot, etc.)")
        print("2. Try scrolling with your mouse wheel in each tab")
        print("3. Check that all controls are accessible")
        print("4. The Detection tab should have 20 sliders + 1 checkbox")
        print("5. All tabs should be scrollable if content exceeds window size")
        print("6. Close the window when done testing")
        print("="*50)
        
        app.protocol("WM_DELETE_WINDOW", app._on_close)
        app.mainloop()
        
        print("Scrolling test completed!")

    if __name__ == "__main__":
        test_scrolling()
        
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running this from the v3.0_outsider directory")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
