"""
config.py
=========
Single source of truth for pin assignments, file paths, and tunable
thresholds. Nothing in this project should hardcode a GPIO number or a
magic threshold outside this file — that's what makes the 1.5s budget
debuggable when you're re-tuning on real hardware.

Pin numbers are BCM numbering (matches gpiozero's default and what's
silkscreened on most Pi Zero 2 W pinout diagrams).
"""
import os
import platform
import shutil
from pathlib import Path

# --------------------------------------------------------------------------
# GPIO PIN MAP (BCM numbering)
# --------------------------------------------------------------------------
BUTTON_PIN = 17          # Push button trigger, wired to GND with internal pull-up
VIBRATION_MOTOR_PIN = 27  # Drives NPN/MOSFET gate for the vibration motor
STATUS_LED_PIN = 22       # Optional: onboard "processing" indicator LED (debug aid)

# --------------------------------------------------------------------------
# BUTTON BEHAVIOUR
# --------------------------------------------------------------------------
BUTTON_BOUNCE_TIME = 0.05      # seconds — debounce window
BUTTON_HOLD_IGNORE_WINDOW = 1.5  # ignore re-triggers while a capture is in flight

# --------------------------------------------------------------------------
# CAMERA
# --------------------------------------------------------------------------
# Kept deliberately small: OCR accuracy on a route board plateaus well
# below full sensor resolution, and every extra megapixel costs you
# milliseconds in both capture and preprocessing.
CAMERA_RESOLUTION = (640, 480)
CAMERA_FORMAT = "RGB888"
# Region of interest as (x, y, w, h) fractions of the frame, if you know
# the board is roughly centered (mount-dependent — tune after field testing).
CAMERA_ROI = None  # e.g. (0.15, 0.25, 0.7, 0.5) to crop to the middle band

# Fallback shared-memory scratch path if you want an on-disk (tmpfs) frame
# for debugging with `raspistill`-style tools. The default pipeline in
# camera.py does NOT write here — it hands preprocessing an in-memory
# numpy array directly, which is faster. This is kept for the debug CLI.
SHM_FRAME_PATH = Path("/dev/shm/bus_frame.jpg")

# --------------------------------------------------------------------------
# PREPROCESSING
# --------------------------------------------------------------------------
CLAHE_CLIP_LIMIT = 3.0
CLAHE_TILE_GRID_SIZE = (8, 8)
ADAPTIVE_THRESH_BLOCK_SIZE = 31   # must be odd
ADAPTIVE_THRESH_C = 12
# Upscale factor applied AFTER cropping to ROI, if the board text is small.
# Keep at 1.0 unless field testing shows OCR missing small boards.
UPSCALE_FACTOR = 1.0

# --------------------------------------------------------------------------
OCR_ENGINE = "tesseract" if os.environ.get("VERCEL") else "paddleocr"


def _detect_tesseract_cmd() -> str:
    """
    Cross-platform Tesseract binary discovery. A hardcoded '/usr/bin/tesseract'
    silently fails on Windows/macOS (pytesseract raises, and the pipeline falls
    back to a weaker OCR engine without telling you why) — so resolve it at
    import time instead:
      1. Whatever 'tesseract' resolves to on PATH (works if you ticked
         "Add to PATH" during install, on any OS).
      2. Common per-OS default install locations.
      3. Fall back to the bare command name so pytesseract's own error message
         clearly says "tesseract not found" instead of pointing at a wrong path.
    """
    found = shutil.which("tesseract")
    if found:
        return found

    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
    elif system == "Darwin":
        candidates = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
    else:
        candidates = ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]

    for c in candidates:
        if Path(c).exists():
            return c
    return "tesseract"


TESSERACT_CMD = _detect_tesseract_cmd()
if TESSERACT_CMD and Path(TESSERACT_CMD).is_file():
    _tess_dir = str(Path(TESSERACT_CMD).parent)
    if _tess_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _tess_dir + os.pathsep + os.environ.get("PATH", "")

TESSERACT_LANG = "eng"
# --psm 7 = "treat the image as a single line of text" — matches route boards.
# --psm 11 is a fallback for sparse/scattered text if psm 7 returns nothing.
TESSERACT_PSM_PRIMARY = 7
TESSERACT_PSM_FALLBACK = 11
TESSERACT_WHITELIST = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/- "
OCR_MIN_CONFIDENCE = 45  # 0-100, Tesseract mean word confidence; below this -> "unclear" feedback

# Route-number pattern: 1-3 digits, optionally followed by a single letter
# suffix (e.g. "12", "21C", "500A"), which may itself carry a branch number
# with or without a separator ("3C/1", "3C1" — boards print both).
#
# The trailing digits are only allowed *after* a letter. Without that
# restriction the pattern would swallow 4-digit licence-plate groups like
# "0385" or "5522", which sit right next to the route board on most buses.
ROUTE_REGEX = r"\b\d{1,3}(?:[A-Z](?:/?\d{1,2})?)?\b"

# Detected text matching this is a vehicle registration plate, never a route.
PLATE_REGEX = r"\b[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{1,4}\b"

# Scene photos are downscaled to this longest edge before detection. Chosen by
# sweep: a route placard occupying ~2% of a 2586x3312 phone photo is still read
# at 2000px (0.59s) but is lost at 1600px, while full resolution only costs
# more time (1.28s) for no extra reads. Camera frames are 640x480 and are never
# downscaled, so this only affects uploaded photos.
OCR_MAX_DIM = 2000

# --------------------------------------------------------------------------
# AUDIO / FEEDBACK
# --------------------------------------------------------------------------
# espeak-ng is the default because it synthesizes in tens of milliseconds
# on a Pi Zero 2 W, which Piper's neural voices generally cannot match on
# this specific board (Piper targets Pi 4/5-class CPUs). See
# SOFTWARE_AND_HARDWARE_GUIDE.md for the measured trade-off and how to
# switch to Piper if you relax the budget or upgrade hardware.
TTS_ENGINE = "espeak-ng"  # "espeak-ng" or "piper"
ESPEAK_VOICE = "en-us"
ESPEAK_SPEED_WPM = 175
PIPER_MODEL_PATH = Path("models/en_US-lessac-low.onnx")
PIPER_BINARY = "/usr/local/bin/piper"

# ALSA device for the MAX98357A I2S DAC. Confirm the card index with
# `aplay -l` after enabling the I2S overlay — see the hardware guide.
I2S_ALSA_DEVICE = "plughw:CARD=sndrpisimplecar,DEV=0"

# Pre-rendered audio cache for common route numbers, so the hot path
# skips TTS synthesis entirely for buses you see often. Populated by
# tools/pregenerate_cache.py.
AUDIO_CACHE_DIR = Path("sounds/cache")
COMMON_ROUTES = ["12", "21C", "45", "100", "500A"]  # seed list — edit to your city's routes

PHRASE_NO_TEXT = "No route detected. Please try again."
PHRASE_LOW_CONFIDENCE = "Unclear. Please hold steady and try again."
PHRASE_ROUTE_TEMPLATE = "Bus {route}"

# --------------------------------------------------------------------------
# ROUTE LOOKUP & DATA
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CITY = "vijayawada"  # Active city data to load
ROUTES_DATA_DIR = BASE_DIR / "data" / "routes"  # Directory containing city CSV datasets
PHRASE_ROUTE_WITH_DESTINATION_TEMPLATE = "Bus {route} to {destination}"


# --------------------------------------------------------------------------
# HAPTIC FEEDBACK PATTERNS (seconds, on/off pairs)
# --------------------------------------------------------------------------
HAPTIC_SUCCESS_PATTERN = [(0.15, 0.1)]              # single short pulse
HAPTIC_LOW_CONFIDENCE_PATTERN = [(0.08, 0.08)] * 2  # two quick pulses
HAPTIC_ERROR_PATTERN = [(0.4, 0.0)]                 # one long pulse

# --------------------------------------------------------------------------
# PERFORMANCE BUDGET (seconds) — used by main.py to log stage timings
# --------------------------------------------------------------------------
BUDGET_TOTAL = 1.5
BUDGET_CAPTURE = 0.25
BUDGET_PREPROCESS = 0.15
BUDGET_OCR = 0.70
BUDGET_FEEDBACK = 0.40

# On serverless (Vercel / AWS Lambda), the root filesystem is read-only — write to /tmp instead
_is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
LOG_PATH = Path("/tmp/logs/run_timings.csv") if _is_serverless else (BASE_DIR / "logs" / "run_timings.csv")


# --------------------------------------------------------------------------
# POWER MANAGEMENT
# --------------------------------------------------------------------------
# Battery monitoring is OFF by default because it needs an ADC (this repo
# assumes an ADS1115 over I2C) that isn't in the original bill of
# materials. Flip this on once you've added a voltage-divider + ADC
# between the LiPo and a spare I2C channel — see
# SOFTWARE_AND_HARDWARE_GUIDE.md, section 4.
POWER_MONITORING_ENABLED = False
BATTERY_ADC_CHANNEL = 0          # ADS1115 input channel the divider is wired to
BATTERY_VOLTAGE_DIVIDER_RATIO = 2.0  # (R1+R2)/R2 — set to match your resistors
BATTERY_CHECK_INTERVAL_S = 60    # how often to poll, NOT on the capture hot path
BATTERY_LOW_VOLTAGE = 3.55       # ~20% remaining on a typical 1S LiPo
BATTERY_CRITICAL_VOLTAGE = 3.4   # ~5% remaining — announce urgently, then keep polling
PHRASE_LOW_BATTERY = "Battery low. Please recharge soon."
PHRASE_CRITICAL_BATTERY = "Battery critical. Recharge now."
HAPTIC_LOW_BATTERY_PATTERN = [(0.5, 0.2)] * 2  # two long pulses, distinct from OCR feedback

# Idle CPU/peripheral power saving is handled OUTSIDE this Python process
# (governor + HDMI/BT disable happen at boot, before main.py even starts)
# — see scripts/power_saving.sh and systemd/power-saving.service. There is
# no in-app "sleep mode" for the Pi itself: the Zero 2 W has no supported
# deep-sleep state without extra PMIC hardware (e.g. PiSugar, TPL5110),
# and gpiozero's Button is already interrupt-driven, so the CPU is not
# busy-polling while idle — the biggest easy win is disabling peripherals
# you aren't using, not scripting a sleep/wake cycle.
