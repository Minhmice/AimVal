import logging
from makcu import create_controller, MouseButton, MakcuConnectionError

logger = logging.getLogger(__name__)


class MakcuController:
    """Thin wrapper around makcu-py-lib to issue mouse actions.

    This abstracts the hardware library so the rest of the code interacts with
    a small, resilient API: connect, press/release left, relative move, and
    disconnect. Connection errors toggle the internal flag to prevent further
    calls until reconnected (auto_reconnect is enabled in the library).
    """

    def __init__(self, config):
        self.config = config
        self.makcu_lib = None
        self.is_connected = False
        self._connect()

    def _connect(self):
        """Establish connection to the Makcu device via the vendor library."""
        device_id = self.config.get("MAKCU_VID_PID")
        try:
            self.makcu_lib = create_controller(
                fallback_com_port=device_id, auto_reconnect=True, debug=False
            )
            self.is_connected = self.makcu_lib.is_connected()
            if self.is_connected:
                logger.info(
                    "Successfully connected to Makcu device using makcu-py-lib."
                )
            else:
                logger.error(
                    "Failed to connect via makcu-py-lib. Check device power/connection."
                )
        except MakcuConnectionError as e:
            logger.error(f"Makcu connection failed via makcu-py-lib: {e}")
            self.is_connected = False
        except Exception as e:
            logger.critical(
                f"An unexpected error occurred during makcu-py-lib initialization: {e}"
            )
            self.is_connected = False

    def disconnect(self):
        """Gracefully close the hardware connection."""
        if self.makcu_lib and self.is_connected:
            self.makcu_lib.disconnect()
        self.is_connected = False
        logger.info("Makcu device disconnected.")

    def press_left(self):
        """Press and hold the left mouse button."""
        if not self.is_connected:
            return
        try:
            self.makcu_lib.press(MouseButton.LEFT)
        except MakcuConnectionError:
            self.is_connected = False

    def release_left(self):
        """Release the left mouse button."""
        if not self.is_connected:
            return
        try:
            self.makcu_lib.release(MouseButton.LEFT)
        except MakcuConnectionError:
            self.is_connected = False

    def move(self, dx, dy):
        """Move the mouse cursor by integer deltas (device units)."""
        if not self.is_connected or (dx == 0 and dy == 0):
            return
        try:
            self.makcu_lib.move(int(dx), int(dy))
        except MakcuConnectionError:
            self.is_connected = False
