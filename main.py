"""
main.py
=======
Event loop: button press -> capture -> preprocess -> OCR -> feedback.

Key design choices for the 1.5s budget:
  - The camera, GPIO, and (if used) Piper are all initialized ONCE at
    startup and kept warm. Re-initializing any of them per press would
    blow the budget by itself.
  - The button callback (gpiozero's `when_pressed`) already runs on a
    background thread internally, so it doesn't block edge detection —
    but we ALSO guard with `_processing` so a bounce or an impatient
    second press mid-pipeline doesn't launch overlapping runs.
  - Every stage logs its own timing (see config.BUDGET_*), and the total
    is written to logs/run_timings.csv so you can catch budget creep
    over many real-world presses, not just your test bench.
  - This is meant to run under the systemd service described in
    SOFTWARE_AND_HARDWARE_GUIDE.md, so it should start cleanly on boot
    with no terminal attached and restart itself if it crashes.
"""
import csv
import logging
import time
from pathlib import Path

import config
from camera import CameraController
from preprocessing import preprocess
from ocr_engine import extract_route
from feedback import (
    HapticMotor,
    announce_route,
    announce_low_confidence,
    announce_no_text,
    announce_low_battery,
    announce_critical_battery,
    speak,
)
from power import BatteryMonitor
from routes import RouteLookup
from arduino_interface import ArduinoInterface, ESP32Interface

try:
    from gpiozero import Button
except ImportError:
    Button = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bus_route.main")


class BusRouteIdentifier:
    def __init__(self):
        self.camera = CameraController()
        self.haptic = HapticMotor()
        try:
            self.button = Button(
                config.BUTTON_PIN,
                pull_up=True,
                bounce_time=config.BUTTON_BOUNCE_TIME,
            ) if Button else None
        except Exception:
            logger.warning("Could not initialize gpiozero Button (no pin factory) — running in no-GPIO dev mode.")
            self.button = None

        self._processing = False
        self._last_trigger_time = 0.0
        self.last_spoken_phrase = None
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_log_header()
        self.battery_monitor = BatteryMonitor(
            on_low=lambda: announce_low_battery(self.haptic),
            on_critical=lambda: announce_critical_battery(self.haptic),
        )
        self.route_lookup = RouteLookup(
            routes_dir=config.ROUTES_DATA_DIR,
            city=config.CITY,
        )
        self.route_lookup.startup_complete = True

        # DrishtiCap Arduino Serial Interface for 1-Button Gestures & ToF Direction
        self.arduino = ArduinoInterface(
            port=config.SERIAL_PORT,
            baudrate=config.SERIAL_BAUDRATE,
            on_capture_ocr=self._on_button_pressed,
            on_replay_audio=self.replay_last_announcement,
            on_direction_detected=self.handle_direction_detected,
        )
        self.esp32 = self.arduino  # backward-compatibility reference

    def _ensure_log_header(self):
        if not config.LOG_PATH.exists():
            with open(config.LOG_PATH, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "capture_s", "preprocess_s", "ocr_s", "feedback_s", "total_s", "route", "confidence"]
                )

    def start(self):
        self.camera.start()
        self.battery_monitor.start()
        self.arduino.start()
        if self.button:
            self.button.when_pressed = self._on_button_pressed
            logger.info("Ready. Waiting for button presses (GPIO %s or Arduino Serial).", config.BUTTON_PIN)
        else:
            logger.info("Ready. Waiting for Arduino Serial 1-button triggers.")

    def stop(self):
        self.camera.stop()
        self.battery_monitor.stop()
        self.arduino.stop()

    def replay_last_announcement(self):
        """Triggered by 2 clicks (double click): replays the last spoken message."""
        if self.last_spoken_phrase:
            logger.info("Replaying last announcement: '%s'", self.last_spoken_phrase)
            self.haptic.success()
            self.esp32.send_haptic("success")
            speak(self.last_spoken_phrase)
        else:
            logger.info("No announcement in buffer to replay.")
            speak("No previous announcement to replay.")

    def handle_direction_detected(self, data: dict):
        """Triggered by long press: announces the approaching bus direction and distance."""
        direction = data.get("direction", "clear")
        dist_cm = data.get("distance_cm", 0)
        dist_m = round(dist_cm / 100.0, 1)

        if direction == "left":
            phrase = config.PHRASE_APPROACH_LEFT.format(dist=dist_m)
        elif direction == "right":
            phrase = config.PHRASE_APPROACH_RIGHT.format(dist=dist_m)
        elif direction == "front":
            phrase = config.PHRASE_APPROACH_FRONT.format(dist=dist_m)
        else:
            phrase = config.PHRASE_APPROACH_CLEAR

        logger.info("Directional Announcement: '%s'", phrase)
        self.last_spoken_phrase = phrase
        speak(phrase)

    def _on_button_pressed(self):
        now = time.monotonic()
        if self._processing:
            logger.debug("Ignoring press — a run is already in flight.")
            return
        if now - self._last_trigger_time < config.BUTTON_HOLD_IGNORE_WINDOW:
            logger.debug("Ignoring press — inside re-trigger cooldown.")
            return
        self._last_trigger_time = now
        self._processing = True
        try:
            self.run_once()
        except Exception:
            logger.exception("Pipeline run failed")
            self.haptic.error()
            self.esp32.send_haptic("error")
        finally:
            self._processing = False

    def run_once(self):
        t_start = time.monotonic()

        t0 = time.monotonic()
        frame = self.camera.capture()
        capture_s = time.monotonic() - t0

        t0 = time.monotonic()
        binary = preprocess(frame)
        preprocess_s = time.monotonic() - t0

        t0 = time.monotonic()
        result = extract_route(binary, raw_frame=frame)
        if result.route:
            corrected = self.route_lookup.correct_route(result.route)
            if corrected != result.route:
                result.route = corrected
        ocr_s = time.monotonic() - t0

        t0 = time.monotonic()
        phrase = None
        if result.route is None:
            phrase = config.PHRASE_NO_TEXT
            self.esp32.send_haptic("error")
            announce_no_text(self.haptic)
        elif result.confidence < config.OCR_MIN_CONFIDENCE:
            phrase = config.PHRASE_LOW_CONFIDENCE
            self.esp32.send_haptic("low_conf")
            announce_low_confidence(self.haptic)
        else:
            destination = self.route_lookup.lookup(result.route)
            if destination:
                phrase = config.PHRASE_ROUTE_WITH_DESTINATION_TEMPLATE.format(route=result.route, destination=destination)
            else:
                phrase = config.PHRASE_ROUTE_TEMPLATE.format(route=result.route)
            self.esp32.send_haptic("success")
            announce_route(result.route, self.haptic, destination)
        feedback_s = time.monotonic() - t0

        if phrase:
            self.last_spoken_phrase = phrase


        total_s = time.monotonic() - t_start
        self._log_run(capture_s, preprocess_s, ocr_s, feedback_s, total_s, result)

        if total_s > config.BUDGET_TOTAL:
            logger.warning("TOTAL run took %.3fs — over the %.3fs budget!", total_s, config.BUDGET_TOTAL)
        else:
            logger.info("Run complete in %.3fs (route=%s, conf=%.1f)", total_s, result.route, result.confidence)

    def _log_run(self, capture_s, preprocess_s, ocr_s, feedback_s, total_s, result):
        with open(config.LOG_PATH, "a", newline="") as f:
            csv.writer(f).writerow(
                [time.time(), f"{capture_s:.3f}", f"{preprocess_s:.3f}", f"{ocr_s:.3f}",
                 f"{feedback_s:.3f}", f"{total_s:.3f}", result.route, f"{result.confidence:.1f}"]
            )


def main():
    app = BusRouteIdentifier()
    app.start()
    try:
        # gpiozero's callback runs on its own thread; keep the main
        # thread alive to receive signals cleanly under systemd.
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
