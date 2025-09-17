#!/usr/bin/env python3
"""Run the component-based AimVal Tracker application."""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main_new import main
    main()
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure all dependencies are installed:")
    print("pip install ttkbootstrap psutil opencv-python numpy")
except Exception as e:
    print(f"Error starting application: {e}")
    import traceback
    traceback.print_exc()
