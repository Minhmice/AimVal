from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from makcu import create_async_controller, MouseButton

from .config import ControllerConfig


class MakcuAsyncController:
    def __init__(self, cfg: ControllerConfig) -> None:
        self.cfg = cfg
        self._ctrl = None
        self._current_pos: Optional[Tuple[float, float]] = None

    async def __aenter__(self):
        self._ctrl = await create_async_controller(
            debug=self.cfg.debug, auto_reconnect=self.cfg.auto_reconnect
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._ctrl is not None:
            try:
                await self._ctrl.disconnect()
            except Exception:
                pass
            self._ctrl = None

    def set_estimated_cursor(self, x: float, y: float) -> None:
        self._current_pos = (x, y)

    def get_estimated_cursor(self) -> Optional[Tuple[float, float]]:
        return self._current_pos

    async def move_delta(self, dx: int, dy: int) -> None:
        if self._ctrl is None:
            return
        if dx == 0 and dy == 0:
            return
        await self._ctrl.move(int(dx), int(dy))
        # Update estimate if known
        if self._current_pos is not None:
            x, y = self._current_pos
            self._current_pos = (x + dx, y + dy)

    async def click(self, button: MouseButton = MouseButton.LEFT) -> None:
        if self._ctrl is None:
            return
        await self._ctrl.click(button)
