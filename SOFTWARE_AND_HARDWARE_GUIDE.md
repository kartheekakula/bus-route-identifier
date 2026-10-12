# SOFTWARE_AND_HARDWARE_GUIDE.md
Edge-OCR & Audio-Tactile Bus Route Identifier — build, wiring, and deployment guide

---

## 1. OS Configuration & Driver Setup

Target OS: **Raspberry Pi OS Bookworm (Lite, 64-bit)** on a Pi Zero 2 W.
Lite is strongly recommended — no desktop environment means more of the
512MB RAM and the quad-core A53 are available for OCR, and boot-to-ready
time is shorter.

### 1.1 Enable the MAX98357A I2S DAC

The MAX98357A is a class-D I2S amplifier — it needs the Pi's I2S
interface enabled and the matching ALSA overlay loaded, not a generic
"enable audio" setting.

Edit `/boot/firmware/config.txt` (this path replaced `/boot/config.txt`
on current Bookworm images — check `ls /boot/firmware` if unsure) and
add:

```ini
# Disable the onboard PWM audio — it conflicts with the I2S DAC's use
# of shared pins/DMA channels
dtparam=audio=off

# Enable I2S and load the MAX98357A-compatible overlay
dtparam=i2s=on
dtoverlay=hifiberry-dac
```

> `hifiberry-dac` is the overlay the community has standardized on for
> the MAX98357A because it matches the chip's I2S timing and doesn't
> require a hardware volume/mute pin. Some breakout boards ship a gain
> or SD (shutdown) pin — pull `SD` high (3.3V) to enable output, or wire
> it to a spare GPIO if you want software-controlled mute.

Reboot, then confirm the card is detected:

```bash
aplay -l
# Expect a line like:
# card 0: sndrpisimplecar [snd_rpi_simple_card], device 0: ...
```

Update `config.I2S_ALSA_DEVICE` in `config.py` to match whatever
`aplay -l` reports — the card name occasionally differs by overlay/OS
image revision (`sndrpihifiberry`, `sndrpisimplecar`, etc.). Test
directly before trusting the Python layer:

```bash
speaker-test -D plughw:0,0 -c1 -t wav
```

### 1.2 Install core packages

```bash
sudo apt update
sudo apt install -y \
    python3-picamera2 --no-install-recommends \
    tesseract-ocr \
    espeak-ng \
    alsa-utils \
    git

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` matters: `python3-picamera2` is an apt package
tied to the system's libcamera build, not something `pip` can install
correctly in an isolated venv.

### 1.3 Run automatically on boot (systemd)

A ready-made unit file is at `systemd/bus-route-identifier.service`.
Install it:

```bash
sudo cp systemd/bus-route-identifier.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bus-route-identifier.service
sudo systemctl start bus-route-identifier.service

# Check it came up clean:
sudo systemctl status bus-route-identifier.service
journalctl -u bus-route-identifier.service -f
```

Why a long-running service and not a script launched per button press:
**process startup itself costs 300-800ms** on a Zero 2 W (Python
interpreter start, importing OpenCV/Tesseract bindings, opening the
camera). Doing that inside your 1.5s budget on every press is not
survivable — the service must already be running and warm, with the
button only triggering `_on_button_pressed()` inside an already-live
process.

---

## 2. Hardware Integration Diagram & Pin Mapping

All pin numbers are **BCM** (matches `config.py` and gpiozero's
default numbering — not physical pin position).

| Function                     | Pi Zero 2 W Pin (BCM) | Physical Pin | Notes |
|-------------------------------|:---:|:---:|---|
| Push Button (signal)          | GPIO17 | 11 | Other leg of button to GND. Internal pull-up enabled in software (`gpiozero.Button(pull_up=True)`) — no external resistor needed. |
| Vibration Motor (driver base) | GPIO27 | 13 | Drives a transistor/MOSFET gate, **not** the motor directly — see 2.1. |
| Status LED (optional, debug)  | GPIO22 | 15 | Through a ~330Ω resistor to GND. Lights while a capture/OCR cycle is in flight. |
| I2S BCLK (bit clock)          | GPIO18 | 12 | Fixed function — Pi's I2S BCLK pin, not reassignable. |
| I2S LRC (word select)         | GPIO19 | 35 | Fixed function — Pi's I2S LRCLK pin. |
| I2S DIN (data in to DAC)      | GPIO21 | 40 | Fixed function — Pi's I2S DOUT pin (labelled DIN on the MAX98357A board, since it's an input to the DAC). |
| MAX98357A VIN                 | 5V | 2 or 4 | Class-D amp draws more current than the 3.3V rail comfortably supplies. |
| MAX98357A GND                 | GND | 6, 9, 14, 20, 25, 30, 34, or 39 | Any GND pin. |
| MAX98357A SD (shutdown/enable)| 3.3V (or spare GPIO) | 1 or 17 | Tie high to enable; wire to a GPIO instead if you want software mute. |
| Camera (OV2640 / USB cam)     | CSI ribbon connector (or any USB port) | — | OV2640 modules sold for the Pi typically use the CSI ribbon; a USB webcam needs no config.txt changes but has higher capture latency — measure it against the budget. |

### 2.1 Vibration motor driver circuit

Do **not** wire a vibration motor directly to a GPIO pin — even small
coin motors can pull more current than a GPIO pin is rated for (Pi
GPIOs are ~16mA max), and the motor's back-EMF on switch-off can damage
the SoC.

Minimal driver (per motor):

```
3.7V (battery) ──┬── Motor (+)
                  │
             Motor (−) ── Diode (flyback, cathode to +3.7V) ── back to 3.7V
                  │
              Collector (NPN, e.g. 2N2222 / S8050)
                  │
GPIO27 ── 1kΩ resistor ── Base
                  │
              Emitter ── GND (shared with Pi GND)
```

- The flyback diode across the motor is not optional — omit it and
  switching transients will eventually corrupt GPIO state or reset the
  Pi.
- If you have a spare "haptic driver breakout" (e.g. a small
  MOSFET module board) instead of a bare transistor, wiring is the
  same three signals: GPIO → gate/signal, motor power → VCC, GND → GND.

### 2.2 Push button wiring

```
GPIO17 ────────┬──── Button ──── GND
               │
        (internal pull-up,
         set in software)
```

No external resistor is required — `gpiozero.Button(pin, pull_up=True)`
enables the Pi's internal pull-up, so the pin reads HIGH when idle and
LOW when pressed (pulled to GND).

---

## 3. Hardware Deployment Workflow

Step-by-step from a freshly imaged SD card to a working handheld unit:

1. **Flash & headless setup.** Use Raspberry Pi Imager to write
   Raspberry Pi OS Lite (64-bit), pre-configuring Wi-Fi and SSH in the
   imager's advanced options so you never need a monitor/keyboard on
   the Zero 2 W itself.

2. **First boot, base packages.** SSH in, run `sudo apt update && sudo
   apt full-upgrade -y`, reboot, then install the packages listed in
   §1.2.

3. **Enable and verify the camera.**
   ```bash
   libcamera-hello --list-cameras   # confirm the sensor is detected
   libcamera-still -o test.jpg      # confirm a still capture works
   ```
   Pull `test.jpg` off the Pi (`scp`) and eyeball focus/framing before
   writing any code against it.

4. **Enable and verify I2S audio** per §1.1, confirming with
   `speaker-test` before involving Python at all. Debugging "no sound"
   is much faster at the ALSA layer than inside the app.

5. **Wire the button and motor** per §2, testing each independently
   with a 5-line gpiozero script before integrating:
   ```python
   from gpiozero import Button, OutputDevice
   from signal import pause
   b = Button(17, pull_up=True)
   m = OutputDevice(27)
   b.when_pressed = m.on
   b.when_released = m.off
   pause()
   ```

6. **Clone the repository and install dependencies** as in the Quick
   Start section of `README.md`.

7. **Run `main.py` in the foreground** (not yet as a service) and test
   with real bus route boards (or printed mockups) at the mounting
   distance/angle you intend to use in the field. Watch `logs/run_timings.csv`
   for stage-by-stage timing, and adjust `config.CAMERA_ROI`,
   `config.ADAPTIVE_THRESH_BLOCK_SIZE`, and `config.UPSCALE_FACTOR`
   based on what you see.

8. **Pre-render the audio cache** for your city's actual common routes
   (`python3 tools/pregenerate_cache.py --routes 12 21C ...`) — this is
   worth doing again after any wording change to `PHRASE_ROUTE_TEMPLATE`.

9. **Install the systemd service** per §1.3, then power-cycle the whole
   unit (not just restart the service) to confirm it comes up clean
   from a cold boot with no SSH session attached — this is the actual
   real-world startup path once it's in an enclosure and running off
   the LiPo battery.

10. **Mount in an enclosure.** Keep the camera lens unobstructed and
    roughly perpendicular to where an oncoming bus's route board will
    be; keep the speaker grille unblocked; route the button to a
    thumb-reachable position. Re-run the benchmark script against a
    fresh batch of photos taken through the finished enclosure — lens
    position/angle changes after final assembly are the most common
    cause of a working prototype regressing.

11. **Battery runtime check.** Measure current draw at idle (waiting
    for a button press) versus during a capture cycle; a Zero 2 W plus
    camera plus amplifier will draw more at idle than people expect
    from "just a Zero" — size the LiPo and expected runtime accordingly.
    See §4 below for the low-battery alert and OS-level power reductions
    now built into the repo.

---

## 4. Power Management

Two separate mechanisms, at two different layers:

### 4.1 OS-level idle power reduction (`scripts/power_saving.sh`)

Runs once at boot, before `main.py` starts, via
`systemd/power-saving.service`:
- Disables HDMI output (unused on a headless handheld device, ~30mA saved)
- Sets the CPU governor to `ondemand` (balances idle draw against the
  need for full clock speed during an OCR burst — avoid `powersave`
  here, it can add enough scheduling latency to threaten the 1.5s budget)
- Disables Bluetooth via `rfkill` (unused by this project)
- Leaves Wi-Fi enabled by default so you keep SSH access — there's a
  commented-out line to disable it once your update workflow no longer
  needs it

Install both units together:
```bash
sudo cp systemd/power-saving.service systemd/bus-route-identifier.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable power-saving.service bus-route-identifier.service
sudo reboot
```

**What this deliberately does NOT do:** put the Pi to sleep. The Zero
2 W has no supported deep-sleep state without extra PMIC hardware (a
PiSugar module, a TPL5110 timer IC, or similar that cuts and restores
power externally). If battery life becomes a real constraint, that's
the hardware addition to research next — it's outside what software
alone can safely do on this board.

### 4.2 Low-battery alerts (`power.py`)

`config.POWER_MONITORING_ENABLED` is `False` by default because it
needs hardware not in the original bill of materials: a simple resistor
voltage divider from the raw LiPo voltage into an ADS1115 I2C ADC
channel (any I2C ADC works — swap `power._read_voltage` if you use a
different one).

Wiring (in addition to the pins in §2):

| Function | Pin | Notes |
|---|---|---|
| ADS1115 VDD | 3.3V | |
| ADS1115 GND | GND | |
| ADS1115 SCL | GPIO3 (physical 5) | Shared I2C bus |
| ADS1115 SDA | GPIO2 (physical 3) | Shared I2C bus |
| Battery+ → divider → ADS1115 A0 | — | Size the divider so max battery voltage (4.2V charged) stays under the ADS1115's input range at your chosen gain |

Once wired, enable it in `config.py`:
```python
POWER_MONITORING_ENABLED = True
BATTERY_VOLTAGE_DIVIDER_RATIO = 2.0  # match your actual resistors
```

`power.BatteryMonitor` polls on its own background thread every
`BATTERY_CHECK_INTERVAL_S` (default 60s) — deliberately off the button-
press hot path — and speaks + buzzes a distinct low-battery pattern
before the device dies mid-use, which for an assistive device matters
more than the battery-life cost of checking.

---

## 5. Offline Route-to-Destination Lookup

This feature enriches spoken announcements with destination names (e.g. "Bus 21C to Vijayawada Bus Stand") and corrects noisy OCR readouts (e.g. "2lC" -> "21C") using local datasets. It is fully offline and requires no internet connection or GPS hardware.

### 5.1 Adding a new city dataset
1. Create a CSV file named `<city_name>.csv` in `data/routes/`.
2. Format the CSV with a header row `route,destination` followed by the mappings:
   ```csv
   route,destination
   21C,Vijayawada Bus Stand
   12,Railway Station
   ```
3. Set the active city in `config.py`:
   ```python
   CITY = "vijayawada"  # Change to your city's CSV file name (all lowercase)
   ```
4. Regenerate the audio cache to pre-render the new verbal destination announcements:
   ```bash
   python tools/pregenerate_cache.py
   ```

