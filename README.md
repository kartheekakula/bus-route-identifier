---
title: Bus Route Identifier
emoji: 🚌
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# bus-route-identifier

Edge-OCR & audio-tactile bus route identifier for a Raspberry Pi Zero 2 W.
Press a button, get the route number of the oncoming bus spoken aloud
and confirmed with a haptic buzz — fully offline, budgeted to run
end-to-end in under 1.5 seconds.

## Repository layout

```
bus-route-identifier/
├── main.py              # event loop & button handler
├── camera.py            # Picamera2 in-memory frame capture
├── preprocessing.py     # OpenCV: grayscale, CLAHE, adaptive threshold
├── ocr_engine.py        # Tesseract wrapper + route-number regex parsing
├── feedback.py          # TTS (espeak-ng/Piper) + GPIO haptic driver
├── power.py             # battery monitoring & low-battery alerts
├── config.py            # all pins, paths, and tunable thresholds
├── requirements.txt
├── scripts/
│   └── power_saving.sh        # OS-level idle power reduction (boot-time)
├── tools/
│   ├── pregenerate_cache.py   # pre-render audio for common routes
│   ├── benchmark.py           # offline accuracy/latency testing
│   └── analyze_logs.py        # research-paper-ready stats from field logs
├── sounds/cache/         # pre-rendered route audio clips (generated)
├── systemd/
│   ├── bus-route-identifier.service
│   └── power-saving.service
├── logs/                 # per-run timing CSV (generated)
├── docs/
│   └── BUILD_SUMMARY_AND_ANTIGRAVITY_GUIDE.md  # what's built + how to run it in Antigravity
└── SOFTWARE_AND_HARDWARE_GUIDE.md
```

## Quick start (on the Pi)

```bash
sudo apt update
sudo apt install -y python3-picamera2 tesseract-ocr espeak-ng --no-install-recommends
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
# libgl1 is needed by opencv-python (pulled in by rapidocr)
sudo apt install -y libgl1
pip install -r requirements.txt -r requirements-ocr.txt

python3 tools/pregenerate_cache.py   # warm the audio cache for common routes
python3 main.py                      # run in foreground first, confirm it works
```

Once it runs cleanly, install it as a boot service — see
`SOFTWARE_AND_HARDWARE_GUIDE.md`.

## Developing off-Pi

`camera.MockCamera` and dev-mode fallbacks in `feedback.py`/`main.py`
let you run the OCR + preprocessing pipeline on a laptop against static
test photos, so you're not tethered to the hardware for every change:

```python
from camera import MockCamera
cam = MockCamera("test_images/board_01.jpg")
```

Use `tools/benchmark.py` to measure accuracy and timing against a set
of labeled test photos before deploying to hardware.


## Pi 4 notes (DrishtiCap Rev B)

- Set the audio device in `config.py` (`I2S_ALSA_DEVICE`, or env `ALSA_DEVICE`) from `aplay -l`.
- Camera is 1280x720; expect OCR latency of several seconds on a Pi 4 until measured with `tools/benchmark_ocr.py`.
- ESP32 firmware uses Rev B pins (motors on GPIO 25,26,27,32,33,23; I2C at 100 kHz).

## Hybrid Mode (Offline-First with Online Fallback)

The system features a hybrid OCR pipeline: an **offline engine** (RapidOCR PP-OCRv4 / Tesseract) as the primary, edge-local recognizer, paired with **Google Cloud Vision** as an online fallback for challenging images.

### Pipeline Modes (`OCR_MODE`)

The operating mode is configured via `config.OCR_MODE` or the `OCR_MODE` environment variable:

- **`auto` (Default on Pi / Desktop)**:
  Runs the offline engine first. If offline OCR finds no route number or returns confidence below `OFFLINE_MIN_CONFIDENCE` (default 45%), the pipeline automatically calls Google Cloud Vision. If the online call also yields no route, the system gracefully falls back to the standard "No route detected" audio/haptic advisory.
- **`offline`**:
  Strictly runs the local offline engine only (RapidOCR / Tesseract). Zero network requests are made.
- **`online` (Default on Vercel Serverless)**:
  Directly routes image frames to Google Cloud Vision API. Optimized for cloud serverless runtimes where headless OpenCV and native binaries are unavailable.

Every result reports which engine produced the answer:
`{"route": "12", "engine": "offline", "latency_ms": 140.2}` or `{"route": "12A", "engine": "online", "latency_ms": 320.5}`.

### Setting up `.env` Credentials

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Configure your Google Cloud Vision API key in `.env`:
   ```env
   OCR_MODE=auto
   ONLINE_TIMEOUT_S=3.0
   GOOGLE_VISION_API_KEY=your_google_cloud_vision_api_key_here
   ```
   *(Note: `.env` and `*credentials*.json` are strictly added to `.gitignore` to prevent secret leakage).*

3. Run the application:
   ```bash
   python web_app.py
   ```
   The UI will show the route number large, with a subtle line underneath: `Engine: offline (140ms)` or `Engine: online (320ms)`.

