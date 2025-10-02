"""
Serial-backed mouse integration for supported USB-UART devices (e.g. MAKCU, CH34x, CP2102).

This module discovers a compatible device, establishes a high-speed serial link,
listens for button states, and exposes a small API to move/click the mouse via
simple commands understood by the device firmware.
"""
import threading
import serial
from serial.tools import list_ports
import time

# Global serial handle to the active device (opened Serial instance)
makcu = None
makcu_lock = threading.Lock()
# In-memory button state mirror: indices 0..4 map to LMB/RMB/MMB/X1/X2
button_states = {i: False for i in range(5)}
button_states_lock = threading.Lock()
# Connection flag toggled after a successful open/handshake
is_connected = False
last_value = 0

SUPPORTED_DEVICES = [
    ("1A86:55D3", "MAKCU"),
    ("1A86:5523", "CH343"),
    ("1A86:7523", "CH340"),
    ("1A86:5740", "CH347"),
    ("10C4:EA60", "CP2102"),
]
BAUD_RATES = [4_000_000, 2_000_000, 115_200]
BAUD_CHANGE_COMMAND = bytearray([0xDE, 0xAD, 0x05, 0x00, 0xA5, 0x00, 0x09, 0x3D, 0x00])


def find_com_ports():
    """Scan COM ports and return list of (device_path, device_name) for supported devices.

    Matches either VID:PID in the port HWID or a friendly name in the description.
    """
    found = []
    for port in list_ports.comports():
        hwid = port.hwid.upper()
        desc = port.description.upper()
        for vidpid, name in SUPPORTED_DEVICES:
            if vidpid in hwid or name.upper() in desc:
                found.append((port.device, name))
                break
    return found


def km_version_ok(ser):
    """Probe current serial link with a lightweight `km.version()` request.

    Returns True if the device responds with an identifying string (e.g. "km.MAKCU").
    """
    try:
        ser.reset_input_buffer()
        ser.write(b"km.version()\r")
        ser.flush()
        time.sleep(0.1)
        resp = b""
        start = time.time()
        while time.time() - start < 0.3:
            if ser.in_waiting:
                resp += ser.read(ser.in_waiting)
                if b"km.MAKCU" in resp or b"MAKCU" in resp:
                    return True
            time.sleep(0.01)
        return False
    except Exception as e:
        print(f"[WARN] km_version_ok: {e}")
        return False


def connect_to_makcu():
    """Discover and connect to a supported device.

    Behavior:
    - Prefer the dedicated MAKCU device. If found at 115200, attempt an on-the-fly
      switch to 4,000,000 baud using a short handshake, then reopen at that speed.
    - Otherwise, try the set of fallback USB-UARTs at available baud rates.
    On success, enables button reporting with `km.buttons(1)` and starts listening.
    """
    global makcu, is_connected
    ports = find_com_ports()
    if not ports:
        print("[ERROR] No supported serial devices found.")
        return False

    for port_name, dev_name in ports:
        if dev_name == "MAKCU":
            for baud in BAUD_RATES:
                print(f"[INFO] Probing MAKCU {port_name} @ {baud} with km.version()...")
                ser = None
                try:
                    ser = serial.Serial(port_name, baud, timeout=0.3)
                    time.sleep(0.1)
                    if km_version_ok(ser):
                        if baud == 115_200:
                            print(
                                "[INFO] MAKCU responded at 115200, sending 4M handshake..."
                            )
                            ser.write(BAUD_CHANGE_COMMAND)
                            ser.flush()
                            ser.close()
                            time.sleep(0.15)
                            # --- Always cleanup before opening new connection! ---
                            ser4m = None
                            try:
                                ser4m = serial.Serial(port_name, 4_000_000, timeout=0.3)
                                time.sleep(0.1)
                                if km_version_ok(ser4m):
                                    print(
                                        f"[INFO] MAKCU handshake successful, switching to 4M on {port_name}."
                                    )
                                    ser4m.close()
                                    time.sleep(0.1)
                                    makcu = serial.Serial(
                                        port_name, 4_000_000, timeout=0.1
                                    )
                                    with makcu_lock:
                                        makcu.write(b"km.buttons(1)\r")
                                        makcu.flush()
                                    is_connected = True
                                    return True
                                else:
                                    print(
                                        "[WARN] 4M handshake failed, staying at 115200."
                                    )
                                    ser4m.close()
                                    time.sleep(0.1)
                                    makcu = serial.Serial(
                                        port_name, 115_200, timeout=0.1
                                    )
                                    with makcu_lock:
                                        makcu.write(b"km.buttons(1)\r")
                                        makcu.flush()
                                    is_connected = True
                                    return True
                            except Exception as e:
                                print(f"[WARN] Could not switch to 4M: {e}")
                                if ser4m:
                                    try:
                                        ser4m.close()
                                    except:
                                        pass
                                time.sleep(0.1)
                                makcu = serial.Serial(port_name, 115_200, timeout=0.1)
                                with makcu_lock:
                                    makcu.write(b"km.buttons(1)\r")
                                    makcu.flush()
                                is_connected = True
                                return True
                        else:
                            print(f"[INFO] MAKCU responded at {baud}, using it.")
                            ser.close()
                            time.sleep(0.1)
                            makcu = serial.Serial(port_name, baud, timeout=0.1)
                            with makcu_lock:
                                makcu.write(b"km.buttons(1)\r")
                                makcu.flush()
                            is_connected = True
                            return True
                    ser.close()
                    time.sleep(0.1)
                except Exception as e:
                    print(f"[WARN] Failed MAKCU@{baud}: {e}")
                    if ser:
                        try:
                            ser.close()
                        except:
                            pass
                        time.sleep(0.1)
                    if makcu and makcu.is_open:
                        makcu.close()
                    makcu = None
                    is_connected = False
        else:
            for baud in BAUD_RATES:
                print(f"[INFO] Trying {dev_name} {port_name} @ {baud} ...")
                ser = None
                try:
                    ser = serial.Serial(port_name, baud, timeout=0.1)
                    with makcu_lock:
                        ser.write(b"km.buttons(1)\r")
                        ser.flush()
                    ser.close()
                    time.sleep(0.1)
                    makcu = serial.Serial(port_name, baud, timeout=0.1)
                    is_connected = True
                    print(
                        f"[INFO] Connected to {dev_name} on {port_name} at {baud} baud."
                    )
                    return True
                except Exception as e:
                    print(f"[WARN] Failed {dev_name}@{baud}: {e}")
                    if ser:
                        try:
                            ser.close()
                        except:
                            pass
                        time.sleep(0.1)
                    if makcu and makcu.is_open:
                        makcu.close()
                    makcu = None
                    is_connected = False

    print("[ERROR] Could not connect to any supported device.")
    return False


def count_bits(n: int) -> int:
    """Return the number of 1-bits in integer n (used to validate button frames)."""
    return bin(n).count("1")


def listen_makcu():
    """Background thread that decodes button state frames from the device.

    Protocol:
    - Device sends a single byte where exactly one bit (0..4) is set when a button
      is pressed, or 0 when nothing is pressed.
    - We keep track of edges to set/reset `button_states` atomically.
    """
    global last_value
    while is_connected:
        try:
            if makcu.in_waiting == 0:
                time.sleep(0.001)
                continue
            b = makcu.read(1)
            if not b:
                continue
            v = b[0]
            if v > 31 or (v != 0 and count_bits(v) != 1):
                continue
            pressed = (v ^ last_value) & v
            released = (v ^ last_value) & last_value
            with button_states_lock:
                for i in range(5):
                    if pressed == (1 << i):
                        button_states[i] = True
                    elif released == (1 << i):
                        button_states[i] = False
            last_value = v
        except serial.SerialException as e:
            print(f"[ERROR] Listener serial exception: {e}")
            break


def is_button_pressed(idx: int) -> bool:
    """Return True if the button at index `idx` is currently considered pressed."""
    with button_states_lock:
        return button_states.get(idx, False)


def test_move():
    """Send a simple downward move command to validate transport works."""
    if is_connected:
        with makcu_lock:
            makcu.write(b"km.move(0,100)\r")
            makcu.flush()


class Mouse:
    """High-level singleton mouse controller.

    On first instantiation, attempts to connect to a supported device and start the
    background listener. Subsequent instantiations share the same underlying link.
    """
    _instance = None
    _listener = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_inited"):
            if not connect_to_makcu():
                print("[ERROR] Mouse init failed to connect.")
            else:
                Mouse._listener = threading.Thread(target=listen_makcu, daemon=True)
                Mouse._listener.start()
            self._inited = True

    def move(self, x: float, y: float):
        """Move the cursor by a delta in pixels (rounded to integers)."""
        if not is_connected:
            return
        print(f"Ancien x : {x}")
        print(f"Ancien y : {y}")
        dx, dy = round(x), round(y)
        print(f"Après round x : {dx}")
        print(f"Après round y : {dy}")
        with makcu_lock:
            makcu.write(f"km.move({dx},{dy})\r".encode())
            makcu.flush()

    def move_bezier(
        self, x: float, y: float, segments: int, ctrl_x: float, ctrl_y: float
    ):
        """Move the cursor along a cubic-like path approximated on-device.

        segments: number of intermediate steps
        ctrl_x/ctrl_y: control-point deltas shaping the curve
        """
        if not is_connected:
            return
        with makcu_lock:
            cmd = f"km.move({int(x)},{int(y)},{int(segments)},{int(ctrl_x)},{int(ctrl_y)})\r"
            makcu.write(cmd.encode())
            makcu.flush()

    def move_smooth(self, x: float, y: float, segments: int = 5, ctrl_scale: float = 0.35):
        """High-level smooth move using on-device segmented motion.

        segments: number of sub-steps for smoothing (>=1)
        ctrl_scale: control vector scale relative to (x,y) to create a gentle curve
        """
        if not is_connected:
            return
        try:
            seg = max(1, int(segments))
        except Exception:
            seg = 5
        try:
            c = float(ctrl_scale)
        except Exception:
            c = 0.35
        # control vector aims roughly towards 30-40% of total delta
        cx = int(round(x * c))
        cy = int(round(y * c))
        with makcu_lock:
            cmd = f"km.move({int(round(x))},{int(round(y))},{seg},{cx},{cy})\r"
            makcu.write(cmd.encode())
            makcu.flush()

    def click(self):
        """Synthesize a left mouse click (down then up)."""
        if not is_connected:
            return
        with makcu_lock:
            makcu.write(b"km.left(1)\r km.left(0)\r")
            makcu.flush()

    def press(self):
        """Hold left mouse button down."""
        if not is_connected:
            return
        with makcu_lock:
            makcu.write(b"km.left(1)\r")
            makcu.flush()

    def release(self):
        """Release left mouse button."""
        if not is_connected:
            return
        with makcu_lock:
            makcu.write(b"km.left(0)\r")
            makcu.flush()

    def click_with_delay(self, down_up_delay_ms: int = 20):
        """Perform a click with a programmable down→up delay in milliseconds."""
        if not is_connected:
            return
        try:
            d = max(0, int(down_up_delay_ms))
        except Exception:
            d = 20
        self.press()
        time.sleep(d / 1000.0)
        self.release()

    @staticmethod
    def cleanup():
        """Close serial resources and reset singleton state (idempotent)."""
        global is_connected, makcu
        is_connected = False
        if makcu and makcu.is_open:
            makcu.close()
        Mouse._instance = None
        Mouse._listener = None
        print("[INFO] Mouse serial cleaned up.")
