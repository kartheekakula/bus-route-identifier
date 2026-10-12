"""
esp32_interface.py
==================
Serial communication interface between Raspberry Pi 4 and ESP32.

Receives 1-button gestures from ESP32:
  - single_click -> triggers camera capture & OCR pipeline
  - double_click -> replays last audio announcement
  - long_press   -> receives directional bus detection results & announces via TTS

Sends haptic commands back to ESP32:
  - {"haptic": "success" | "low_conf" | "error"}
"""
import glob
import json
import logging
import platform
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("drishticap.serial")

try:
    import serial
except ImportError:
    serial = None


class ESP32Interface:
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
        system = platform.system()
        if system == "Linux":
            candidates = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
            if candidates:
                return candidates[0]
        elif system == "Windows":
            candidates = [f"COM{i}" for i in range(1, 25)]
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
            logger.warning("pyserial is not installed — running in mock serial mode.")
            return

        port = self._find_port()
        if not port:
            logger.warning("ESP32 not found on USB Serial — running in mock serial dev mode.")
            return

        try:
            self._ser = serial.Serial(port, self.baudrate, timeout=1.0)
            time.sleep(1.0)  # allow ESP32 to reset after DTR assert
            logger.info("Connected to ESP32 on port %s @ %d baud", port, self.baudrate)
        except Exception as e:
            logger.warning("Could not open serial port %s: %s (dev mode active)", port, e)
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

                logger.debug("ESP32 raw: %s", line)
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
                    event = data.get("event")

                    if event == "single_click" and self.on_capture_ocr:
                        logger.info("ESP32 Event: SINGLE CLICK -> Triggering Capture & OCR")
                        self.on_capture_ocr()
                    elif event == "double_click" and self.on_replay_audio:
                        logger.info("ESP32 Event: DOUBLE CLICK -> Replaying Audio")
                        self.on_replay_audio()
                    elif event == "long_press" and self.on_direction_detected:
                        logger.info("ESP32 Event: LONG PRESS -> Direction Detected: %s", data.get("direction"))
                        self.on_direction_detected(data)
            except Exception as e:
                logger.error("Error reading from ESP32 serial: %s", e)
                time.sleep(0.1)

    def send_haptic(self, pattern: str):
        """Sends haptic feedback command to ESP32: 'success', 'low_conf', or 'error'."""
        if not self._ser or not self._ser.is_open:
            logger.debug("Mock send_haptic('%s')", pattern)
            return
        try:
            msg = f'{{"haptic":"{pattern}"}}\n'
            self._ser.write(msg.encode("utf-8"))
        except Exception as e:
            logger.warning("Failed to send haptic command to ESP32: %s", e)
