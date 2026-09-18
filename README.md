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
sudo apt install -y python3-picamera2 tesseract-ocr espeak-ng libgl1 --no-install-recommends
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-ocr.txt

python3 tools/pregenerate_cache.py   # warm the audio cache for common routes
python3 main.py                      # run in foreground first, confirm it works
```

`requirements-ocr.txt` holds the text-detection engine and is a separate file
only because it pulls in `opencv-python`, which needs `libGL.so.1` and so
cannot be installed on serverless hosts. Skip it and OCR falls back to
Tesseract, which reads 1 of the 8 benchmark photos instead of 7 — check with
`python3 tools/benchmark_ocr.py`.

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
