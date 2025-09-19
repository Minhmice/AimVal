#!/usr/bin/env python3
"""
Test script to verify the fixed UI works correctly.
Only Detection tab should have smooth scrolling, other tabs should have normal UI.
"""

import customtkinter as ctk
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from main import ViewerApp
    
    def test_fixed_ui():
        """Test the fixed UI with proper scrolling only on Detection tab."""
        print("Testing FIXED UI...")
        
        # Set appearance
        ctk.set_appearance_mode("Dark")
        
        # Create app
        app = ViewerApp()
        
        print("\n" + "="*60)
        print("FIXED UI TEST INSTRUCTIONS:")
        print("="*60)
        print("✅ General Tab: Should have NORMAL UI (no scrolling)")
        print("✅ Aimbot Tab: Should have NORMAL UI (no scrolling)")
        print("✅ Triggerbot Tab: Should have NORMAL UI (no scrolling)")
        print("✅ Detection Tab: Should have SMOOTH SCROLLING (20 sliders)")
        print("✅ Config Tab: Should have NORMAL UI (no scrolling)")
        print()
        print("🎯 Test Detection tab scrolling:")
        print("   - Mouse wheel should scroll smoothly")
        print("   - All 20 sliders should be accessible")
        print("   - Scrollbar should appear on the right")
        print("   - No UI layout issues")
        print()
        print("🔍 Check other tabs:")
        print("   - Should look normal and work properly")
        print("   - No scrolling or canvas issues")
        print("="*60)
        
        app.protocol("WM_DELETE_WINDOW", app._on_close)
        app.mainloop()
        
        print("✅ Fixed UI test completed!")

    if __name__ == "__main__":
        test_fixed_ui()
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
