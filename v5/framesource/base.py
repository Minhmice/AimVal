from dataclasses import dataclass
from typing import Optional, Any, Dict
import time


@dataclass
class SourceStats:
    frames: int = 0
    rt_fps: float = 0.0
    avg_fps: float = 0.0
    last_frame_ns: int = 0
    last_sender_ip: Optional[str] = None


class FrameSource:
    def __init__(self) -> None:
        self.started = False
        self._t0_ns = 0
        self._frames = 0
        self.stats = SourceStats()

    def start(self) -> bool:
        self.started = True
        self._t0_ns = time.monotonic_ns()
        return True

    def stop(self) -> None:
        self.started = False

    def get_latest_frame(self) -> Optional[Any]:
        raise NotImplementedError

    def get_stats(self) -> Dict[str, Any]:
        return {
            "frames": self.stats.frames,
            "rt_fps": self.stats.rt_fps,
            "avg_fps": self.stats.avg_fps,
            "last_frame_ns": self.stats.last_frame_ns,
            "last_sender_ip": self.stats.last_sender_ip,
        }
