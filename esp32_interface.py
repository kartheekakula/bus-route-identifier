"""
esp32_interface.py
==================
Backward compatibility wrapper. Re-exports ArduinoInterface as ESP32Interface.
"""
from arduino_interface import ArduinoInterface, ESP32Interface

__all__ = ["ArduinoInterface", "ESP32Interface"]
