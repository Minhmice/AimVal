from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    label: str = "unknown"
    score: float = 1.0
    source: str = "unknown"  # hsv | ai | fused
    track_id: Optional[int] = None

    def as_xyxy(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class Keypoint:
    x: int
    y: int
    score: float


class Detector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def infer(self, bgr: Any) -> Tuple[List[Box], Dict[str, Any]]:
        """
        Perform detection on a BGR frame.
        Returns (boxes, debug) where debug may contain intermediate artifacts (e.g., mask).
        """
        raise NotImplementedError
