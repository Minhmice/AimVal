from typing import Optional

try:
    from makcu import create_controller, MouseButton  # type: ignore
except Exception:
    create_controller = None  # type: ignore
    MouseButton = None  # type: ignore


class MakcuController:
    def __init__(self):
        self.dev = None
        if create_controller is not None:
            try:
                self.dev = create_controller(auto_reconnect=True, debug=False)
            except Exception:
                self.dev = None

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self.dev and self.dev.is_connected())
        except Exception:
            return False

    def move(self, dx: float, dy: float):
        try:
            if self.is_connected:
                self.dev.move(int(dx), int(dy))
        except Exception:
            pass

    def click_left(self):
        try:
            if self.is_connected and MouseButton is not None:
                self.dev.click(MouseButton.LEFT)
        except Exception:
            pass

    def press_left(self):
        try:
            if self.is_connected and MouseButton is not None:
                self.dev.press(MouseButton.LEFT)
        except Exception:
            pass

    def release_left(self):
        try:
            if self.is_connected and MouseButton is not None:
                self.dev.release(MouseButton.LEFT)
        except Exception:
            pass

    def is_button_pressed(self, name: str) -> bool:
        try:
            if not self.is_connected or MouseButton is None:
                return False
            mapping = {
                "left": MouseButton.LEFT,
                "right": MouseButton.RIGHT,
                "middle": MouseButton.MIDDLE,
                "mouse4": getattr(MouseButton, "MOUSE4", None),
                "mouse5": getattr(MouseButton, "MOUSE5", None),
            }
            btn = mapping.get(name.lower())
            if btn is None:
                return False
            return bool(self.dev.is_pressed(btn))
        except Exception:
            return False

    def disconnect(self):
        try:
            if self.dev:
                self.dev.disconnect()
        except Exception:
            pass
        self.dev = None
