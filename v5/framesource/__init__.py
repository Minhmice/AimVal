"""
Frame source package - Optimized for maximum streaming performance.
"""

from .base import FrameSource
from .udp_viewer_2 import UdpViewer2Source
from .file_reader import FileReaderSource

__all__ = [
    "FrameSource",
    "UdpViewer2Source", 
    "FileReaderSource",
]
