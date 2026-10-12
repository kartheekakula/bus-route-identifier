# Build Summary & Antigravity Execution Guide
Edge-OCR & Audio-Tactile Bus Route Identifier

This document is a record of everything built for this project so far,
plus a concrete walkthrough of how to run the rest of the build inside
Google Antigravity.

---

## 1. What has been built

### 1.1 Repository structure

```
bus-route-identifier/
├── main.py                  # event loop & button handler
├── camera.py                # Picamera2 in-memory frame capture
├── preprocessing.py         # OpenCV: grayscale, CLAHE, adaptive threshold
├── ocr_engine.py            # Tesseract wrapper + route-number regex parsing
├── feedback.py               # TTS (espeak-ng/Piper) + GPIO haptic driver
├── power.py                  # battery-level monitoring & low-battery alerts
├── config.py                 # every pin, path, and tunable threshold
├── requirements.txt
├── scripts/
│   └── power_saving.sh       # OS-level idle power reduction (boot-time)
├── tools/
│   ├── pregenerate_cache.py  # pre-render audio for common routes
│   ├── benchmark.py          # offline accuracy/latency testing
│   └── analyze_logs.py       # research-paper-ready stats from field logs
├── systemd/
│   ├── bus-route-identifier.service
│   └── power-saving.service
├── sounds/cache/              # pre-rendered route audio clips (generated)
├── logs/                      # per-run timing CSV (generated)
├── README.md
└── SOFTWARE_AND_HARDWARE_GUIDE.md
```

### 1.2 Core pipeline (button → capture → OCR → feedback)

- **`camera.py`** — Picamera2 opened once at boot and kept warm;
  `capture_array()` used instead of writing a JPEG to `/dev/shm`, which
  skips encode/decode entirely (~80–150ms saved on a Zero 2 W). A
  `MockCamera` class lets you develop the rest of the pipeline on a
  laptop against static test photos.
- **`preprocessing.py`** — grayscale → CLAHE (fixes uneven outdoor
  lighting/glare) → adaptive threshold (handles boards lit unevenly
  from one side). No blur/denoise step by default — it costs
  milliseconds for a benefit Tesseract rarely needs on a route board.
- **`ocr_engine.py`** — Tesseract in `--psm 7` (single-line) mode with
  a character whitelist and a regex (`\b\d{1,3}[A-Z]?(?:/\d{1,2})?\b`)
  to pull the route token out of noisy OCR text. Falls back to `--psm
  11` (sparse text) if the primary pass finds nothing. An EasyOCR path
  exists behind a config flag for future hardware upgrades.
- **`feedback.py`** — espeak-ng by default (tens of milliseconds
  synthesis); Piper wired in as a config-toggleable upgrade path.
  Checks a pre-rendered audio cache first, before synthesizing anything
  live. GPIO haptic pulses run on a background thread so they never
  block audio playback.
- **`main.py`** — ties it together, guards against overlapping runs
  from button bounce/impatient re-presses, and logs every stage's
  timing to `logs/run_timings.csv` for later analysis.

### 1.3 Efficiency features added (this round)

| Feature | File(s) | Why |
|---|---|---|
| Pre-rendered audio cache | `feedback.py`, `tools/pregenerate_cache.py` | Skips TTS synthesis entirely for routes announced often — the single biggest latency win available |
| Warm, always-on process via systemd | `systemd/bus-route-identifier.service`, `main.py` | Avoids the 300–800ms cost of a cold Python/OpenCV/Tesseract start on every button press |
| Confidence-gated feedback | `ocr_engine.py`, `main.py`, `feedback.py` | A wrong route number is worse than "unclear, try again" for a blind user |
| In-memory frame capture | `camera.py` | Skips JPEG encode/decode vs. the original `/dev/shm` file-based brief |
| **Battery-level monitoring & alerts** | `power.py`, `config.py`, `feedback.py` | Warns before the device dies mid-journey — added this round; polls off the hot path (every 60s by default), not per button press |
| **OS-level idle power reduction** | `scripts/power_saving.sh`, `systemd/power-saving.service` | Disables HDMI/Bluetooth, sets an `ondemand` CPU governor — the realistic power win on a Zero 2 W, since true sleep/wake needs extra PMIC hardware this board doesn't have |
| **Field-log analysis for the research paper** | `tools/analyze_logs.py` | Turns `logs/run_timings.csv` from real usage into mean/median/p95 latency and detection-rate numbers — ready for an evaluation section |
| Offline benchmark harness | `tools/benchmark.py` | Test accuracy/latency against a labeled photo set before ever touching hardware |

### 1.4 Documented but intentionally NOT auto-enabled

- **EasyOCR** — heavier/more accurate, but PyTorch's load and inference
  cost is too high for a Zero 2 W's 512MB/no-GPU spec. Left as a
  config flag (`config.OCR_ENGINE = "easyocr"`) for if you move to a
  Pi 4/5 or add an accelerator.
- **Piper TTS** — higher voice quality than espeak-ng, but real
  synthesis-time risk against the 1.5s budget on this specific board.
  Left as a config flag (`config.TTS_ENGINE = "piper"`).
- **True sleep/wake power cycling** — not implemented because the
  Zero 2 W has no supported deep-sleep state without extra hardware
  (a PiSugar module, TPL5110 timer, etc.). Documented as the next
  hardware step in `SOFTWARE_AND_HARDWARE_GUIDE.md` §4.1 rather than
  faked in software.
- **Wi-Fi disable in `power_saving.sh`** — left commented out by
  default so you don't lock yourself out of SSH mid-development.

### 1.5 Offline Route-to-Destination Lookup

This feature enriches spoken announcements with destination names (e.g. "Bus 21C to Vijayawada Bus Stand") and corrects noisy OCR readouts (e.g. "2lC" -> "21C") using local datasets. It is fully offline and requires no internet connection or GPS hardware.

- **Adding a new city**: Create `data/routes/<city_name>.csv` with a header `route,destination` and populate the rows.
- **Selection**: Specify `CITY = "<city_name>"` in `config.py` to target the corresponding CSV file.
- **Pre-rendered cache**: Run `python tools/pregenerate_cache.py` to pre-render the full route-and-destination announcements for common routes.

---


## 2. How to execute this in Antigravity

Antigravity's value here isn't writing code from a blank page — that
part is already done and sitting in the zip. Its value is in
**verified, phased execution on real hardware**, where you can review
an Artifact (task list, diff, terminal output) before trusting the
next step. Treat each phase below as one Antigravity task, not one
giant prompt.

### 2.1 One-time setup

1. Install Antigravity and open the extracted `bus-route-identifier/`
   folder as a project (Editor View).
2. Set up terminal access to the Pi from your dev machine — Antigravity
   agents can run local terminal commands, so the simplest path is:
   `ssh pi@<pi-ip>` reachable from your machine, and let the agent
   `scp`/`rsync` files and run remote commands through that terminal
   session. Confirm this manually once before delegating it to an
   agent.
3. In the Manager Surface, create your first task. Antigravity works
   best when the task description names its own success criteria —
   e.g. "confirm `libcamera-still` produces a usable JPEG on the Pi,
   copy it back for review" rather than "set up the camera."

### 2.2 Phase-by-phase tasks

Give these to the agent one at a time, and use the Artifact review
step (comment on the plan/diff before it proceeds) rather than letting
it run all phases unattended:

1. **Hardware bring-up verification.** Task: SSH to the Pi, run
   `libcamera-hello --list-cameras`, `libcamera-still -o test.jpg`,
   `aplay -l`, `speaker-test`; pull results/files back for you to
   inspect. This is pure verification — no code changes — and catches
   wiring problems before they get blamed on software.
2. **Dependency install.** Task: install the apt + pip packages from
   `SOFTWARE_AND_HARDWARE_GUIDE.md` §1.2 inside a `--system-site-packages`
   venv, and report the venv's `pip list` back as the Artifact.
3. **Deploy the repo, run `main.py` in the foreground.** Task: rsync
   the repo to the Pi, run `python3 main.py` in the foreground (not
   yet as a service), and — this is the important part — have the
   agent watch `logs/run_timings.csv` after a manual test press and
   report the stage timings, rather than just reporting "it ran."
4. **Calibration loop.** Task: with a handful of test photos of real
   route boards, run `tools/benchmark.py` and report accuracy. If
   accuracy is low, this is where you iterate on `config.CAMERA_ROI`,
   `ADAPTIVE_THRESH_BLOCK_SIZE`, and `UPSCALE_FACTOR` — give the agent
   one variable to sweep at a time and have it report accuracy deltas,
   rather than asking it to "improve accuracy" unboundedly.
5. **Audio cache + systemd install.** Task: run
   `tools/pregenerate_cache.py` with your city's actual route numbers,
   install both systemd units (§4.1 of the guide), reboot the Pi fully
   (not just restart the service), and confirm via `journalctl` that
   the service came up clean with no terminal attached.
6. **Battery hardware (optional).** Only after the core loop is solid:
   wire the ADS1115 per §4.2, flip `POWER_MONITORING_ENABLED = True`,
   and have the agent verify a simulated low-voltage reading triggers
   the correct alert before trusting it on the real battery.
7. **Enclosure + final field test.** Task: after physical mounting,
   re-run `tools/benchmark.py` against freshly taken photos through the
   finished enclosure. Lens angle/position changes after assembly are
   the most common cause of a working prototype regressing — treat
   this as a required verification step, not optional polish.

### 2.3 Practical notes on delegating to the agent

- **Review before executing anything that touches `/boot/firmware/config.txt`
  or GPIO wiring instructions.** A misapplied overlay can leave the Pi
  needing a fresh SD card flash. Have the agent show you the diff/command
  before running it, not after.
- **Don't let the agent browse the web mid-task for "the right overlay"
  or similar and then immediately execute what it finds.** There's a
  documented indirect-prompt-injection risk in agentic coding tools
  broadly (an instruction hidden in a fetched page influencing what the
  agent does next) — keep hardware-config web research and command
  execution as separate, reviewed steps rather than one uninterrupted
  agent action.
- **Commit per phase**, not one giant PR at the end — it gives you real
  rollback points if a later phase (e.g. calibration) needs to revisit
  an earlier one's config values.
