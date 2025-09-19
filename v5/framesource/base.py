from typing import Optional, Any, Dict
import time


class FrameSource:
    """Base class for all frame sources with minimal overhead."""
    
    def __init__(self) -> None:
        self.started = False
        self._start_time_ns = 0

    def start(self) -> bool:
        """Start the frame source."""
        self.started = True
        self._start_time_ns = time.monotonic_ns()
        return True

    def stop(self) -> None:
        """Stop the frame source."""
        self.started = False

    def get_latest_frame(self) -> Optional[Any]:
        """Get the latest frame. Must be implemented by subclasses."""
        raise NotImplementedError

    def get_stats(self) -> Dict[str, Any]:
        """Get basic source statistics. Can be overridden by subclasses."""
        uptime_ms = 0.0
        if self.started and self._start_time_ns > 0:
            uptime_ms = (time.monotonic_ns() - self._start_time_ns) / 1e6
        
        return {
            "started": self.started,
            "uptime_ms": uptime_ms,
        }

    def is_connected(self) -> bool:
        """Check if the source is connected/active. Can be overridden by subclasses."""
        return self.started
