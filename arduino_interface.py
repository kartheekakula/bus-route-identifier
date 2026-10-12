"""
arduino_interface.py
====================
Serial communication interface between Host (PC / Raspberry Pi) and Arduino
(Uno, Nano, Mega, Pro Micro, Leonardo).

Receives 1-button gestures from Arduino:
  - single_click -> triggers camera capture & OCR pipeline
  - double_click -> replays last audio announcement
  - long_press   -> receives directional bus detection results & announces via TTS

Sends haptic / buzzer commands back to Arduino:
  - {"haptic": "success" | "low_conf" | "error"}
  - or plain text: HAPTIC:SUCCESS, HAPTIC:LOW_CONF, HAPTIC:ERROR
"""
import glob
import json
import logging
import platform
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("drishticap.arduino")

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None


class ArduinoInterface:
    """Manages USB Serial connection with Arduino microcontroller."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 115200,
        on_capture_ocr: Optional[Callable[[], None]] = None,
        on_replay_audio: Optional[Callable[[], None]] = None,
        on_direction_detected: Optional[Callable[[dict], None]] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.on_capture_ocr = on_capture_ocr
        self.on_replay_audio = on_replay_audio
        self.on_direction_detected = on_direction_detected

        self._ser: Optional[serial.Serial] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _find_port(self) -> Optional[str]:
        if self.port:
            return self.port
        if serial is None:
            return None

        # 1. Use serial.tools.list_ports to find Arduino by description / VID:PID
        try:
            available_ports = list(serial.tools.list_ports.comports())
            for p in available_ports:
                desc = (p.description or "").lower()
                hwid = (p.hwid or "").lower()
                if any(k in desc or k in hwid for k in ("arduino", "ch340", "cp210", "ftdi", "usb-serial", "nano", "uno")):
                    logger.info("Found Arduino candidate: %s (%s)", p.device, p.description)
                    return p.device
            # If any COM / tty port is available, use the first one
            if available_ports:
                return available_ports[0].device
        except Exception as e:
            logger.debug("Port scanning error: %s", e)

        # 2. Fallback OS-specific scanning
        system = platform.system()
        if system == "Linux":
            # Arduino Uno/Mega typically enumerates as /dev/ttyACM*; Nano as /dev/ttyUSB*
            candidates = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
            if candidates:
                return candidates[0]
        elif system == "Windows":
            candidates = [f"COM{i}" for i in range(1, 30)]
            for c in candidates:
                try:
                    s = serial.Serial(c)
                    s.close()
                    return c
                except Exception:
                    continue
        return None

    def start(self):
        if serial is None:
            logger.warning("pyserial is not installed — running Arduino in mock dev mode.")
            return

        port = self._find_port()
        if not port:
            logger.warning("Arduino not detected on USB Serial — running in mock dev mode.")
            return

        try:
            self._ser = serial.Serial(port, self.baudrate, timeout=1.0)
            # Allow Arduino bootloader auto-reset (DTR toggle) to settle
            time.sleep(1.8)
            logger.info("Connected to Arduino on port %s @ %d baud", port, self.baudrate)
        except Exception as e:
            logger.warning("Could not open Arduino serial port %s: %s (mock dev mode active)", port, e)
            self._ser = None
            return

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass

    def _read_loop(self):
        while self._running and self._ser and self._ser.is_open:
            try:
                line = self._ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                logger.debug("Arduino raw serial: %s", line)

                # Parse JSON protocol: {"event": "single_click" | "double_click" | "long_press", ...}
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        event = data.get("event")
                        if event == "single_click" and self.on_capture_ocr:
                            logger.info("Arduino Event: SINGLE CLICK -> Triggering Capture & OCR")
                            self.on_capture_ocr()
                        elif event == "double_click" and self.on_replay_audio:
                            logger.info("Arduino Event: DOUBLE CLICK -> Replaying Audio")
                            self.on_replay_audio()
                        elif event == "long_press" and self.on_direction_detected:
                            logger.info("Arduino Event: LONG PRESS -> Direction Detected: %s", data.get("direction"))
                            self.on_direction_detected(data)
                        continue
                    except json.JSONDecodeError:
                        pass

                # Fallback: Plain text protocol (easy Arduino debugging)
                line_upper = line.upper()
                if ("SINGLE_CLICK" in line_upper or line_upper == "CLICK" or line_upper == "1") and self.on_capture_ocr:
                    logger.info("Arduino Plaintext: SINGLE CLICK -> Triggering Capture & OCR")
                    self.on_capture_ocr()
                elif ("DOUBLE_CLICK" in line_upper or line_upper == "REPLAY" or line_upper == "2") and self.on_replay_audio:
                    logger.info("Arduino Plaintext: DOUBLE CLICK -> Replaying Audio")
                    self.on_replay_audio()
                elif ("LONG_PRESS" in line_upper or line_upper == "3") and self.on_direction_detected:
                    direction = "front"
                    if "LEFT" in line_upper:
                        direction = "left"
                    elif "RIGHT" in line_upper:
                        direction = "right"
                    elif "CLEAR" in line_upper:
                        direction = "clear"
                    logger.info("Arduino Plaintext: LONG PRESS -> Direction: %s", direction)
                    self.on_direction_detected({"event": "long_press", "direction": direction, "distance_m": 1.0})

            except Exception as e:
                logger.error("Error reading from Arduino serial: %s", e)
                time.sleep(0.1)

    def send_haptic(self, pattern: str):
        """Sends haptic feedback command to Arduino: 'success', 'low_conf', or 'error'."""
        if not self._ser or not self._ser.is_open:
            logger.debug("Mock Arduino send_haptic('%s')", pattern)
            return
        try:
            # Send both JSON and plain-text token for maximum firmware compatibility
            msg = f'{{"haptic":"{pattern}"}}\n'
            self._ser.write(msg.encode("utf-8"))
        except Exception as e:
            logger.warning("Failed to send haptic command to Arduino: %s", e)


# Backward-compatibility alias so existing code importing ESP32Interface works identically
ESP32Interface = ArduinoInterface
