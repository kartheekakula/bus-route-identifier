# DRISHTICAP: HARDWARE SPECIFICATION & CIRCUIT DESIGN BRIEF
**Document Version:** 2.0  
**Project:** DrishtiCap – Wearable Smart Cap for Visually Impaired Transit Navigation  
**Target Audience:** Electrical Engineer / Circuit Designer (EDA Schematics, Breadboard/Perfboard Wiring, PCB Design)

---

## 1. Executive Summary & System Overview

DrishtiCap is a wearable smart cap designed to provide real-time spatial bus approach detection, bus route reading (YOLOv8 + OCR), and multimodal dual feedback (bone-conduction audio + 6-zone directional haptics) for blind and visually impaired commuters.

The system uses a **dual-processor master-worker architecture**:
1. **Master Compute Brain (Raspberry Pi 4 Model B)**: High-level vision processing (Picamera2, OpenCV, YOLOv8 object detection, Tesseract/PaddleOCR), route database lookup, and text-to-speech audio via 3.5mm jack.
2. **Real-Time I/O Worker (ESP32)**: Low-level sensor acquisition, Time-of-Flight (ToF) multiplexing, single-button multi-gesture state machine, and 6-channel transistor-switched haptic motor control.
3. **Interconnect**: Bidirectional USB Serial link (`115200` baud) between ESP32 and Raspberry Pi 4.

```
                                  ┌─────────────────────────────┐
                                  │   DRISHTICAP SYSTEM POWER   │
                                  │  5V / 3A Power Bank / Batt  │
                                  └──────────────┬──────────────┘
                                                 │ 5V Rail
                       ┌─────────────────────────┴─────────────────────────┐
                       │                                                   │
                       ▼ 5V (USB-C)                                        ▼ 5V (VIN / USB)
          ┌──────────────────────────┐                        ┌──────────────────────────┐
          │  Raspberry Pi 4 Model B  │                        │    ESP32 NodeMCU/DevKit  │
          │  (Compute Master Brain)  │                        │  (Real-Time Sensor Worker)│
          └────────────┬─────────────┘                        └────────────┬─────────────┘
                       │                                                   │
     ┌─────────────────┼─────────────────┐               ┌─────────────────┼─────────────────┐
     │                 │                 │               │                 │                 │
     ▼ (CSI Ribbon)    ▼ (3.5mm Audio)   ▼ (USB Serial)  ▼ (GPIO 18)       ▼ (I2C 0x70)      ▼ (GPIO 12-27)
┌───────────┐    ┌───────────┐           │         ┌───────────┐    ┌───────────┐    ┌───────────┐
│ Pi Camera │    │ Bone-Cond.│           └────────►│ 1x Tactile│    │ TCA9548A  │    │ 6x Haptic │
│ Module v2 │    │ Headphones│  USB-A to Micro/C   │ Pushbutton│    │ 8-Ch Mux  │    │ Drivers   │
└───────────┘    └───────────┘                     └───────────┘    └─────┬─────┘    └─────┬─────┘
                                                                          │                │
                                                       ┌──────┬──────┬────┴─┬──────┐       ▼
                                                       │      │      │      │      │ 6x Coin Motors
                                                       ▼      ▼      ▼      ▼      ▼ (Circular Headband)
                                                      Ch 0   Ch 1   Ch 2   Ch 3
                                                      Left   F-Left F-Right Right
                                                      [4x VL53L0X ToF Sensors]
```

---

## 2. Complete Bill of Materials (BOM)

| Category | Component Description | Quantity | Key Specifications / Part Number | Notes |
| :--- | :--- | :---: | :--- | :--- |
| **Compute** | Raspberry Pi 4 Model B | 1 | Quad Cortex-A72 @ 1.5GHz, 2GB/4GB RAM | Handles Camera, YOLOv8, OCR, TTS |
| **Microcontroller** | ESP32-WROOM-32 DevKit | 1 | 30-pin or 38-pin NodeMCU form-factor | 3.3V logic, handles buttons, ToF & haptics |
| **Vision** | Raspberry Pi Camera Module | 1 | v2 (8MP Sony IMX219) or v3, CSI ribbon | Mounted centrally on cap visor |
| **Audio** | Bone-Conduction Headphones | 1 | 3.5mm stereo audio plug | Keeps user ear canals open to traffic |
| **Distance Sensing**| VL53L0X Time-of-Flight Sensor | 4 | 940nm VCSEL laser, up to 2m range, I2C 0x29 | Angled at -60°, -20°, +20°, +60° |
| **I2C Expansion** | TCA9548A I2C Multiplexer | 1 | 8-channel bidirectional multiplexer, 0x70 | Required to resolve 0x29 address conflict |
| **Haptics** | Coin Vibration Motor | 6 | 10 mm dia × 2.7 mm, 3.0V DC, 70-85 mA | Arranged radially around cap headband |
| **Transistors** | 2N2222 or BC547 NPN Transistor | 6 | TO-92 package, $I_C \ge 200\text{ mA}$, NPN | Low-side motor switches |
| **Flyback Diodes**| 1N4148 or 1N5819 Schottky Diode | 6 | DO-35 axial package, fast recovery | Inductive spike suppression across motors |
| **Base Resistors** | 1 kΩ Resistor ($1/4\text{ W}$) | 6 | Metal film or carbon film | Limits ESP32 GPIO base current to ~2.6mA |
| **Controls** | Tactile Push Buttons | 2 | 6×6 mm or 12×12 mm SPST momentary | 1 Active button (Multi-gesture), 1 Spare |
| **Wiring & Board** | Perfboard / Stripboard | 1 | Single-sided or double-sided 5×7 cm | Houses transistor drivers & multiplexer |
| **Hookup Wire** | Silicone Hookup Wire | 1 set | 26 AWG or 28 AWG, flexible stranded | Lightweight routing through cap fabric |
| **Protection** | Heat-shrink Tubing | 1 set | 1.5 mm, 2.5 mm, and 4.0 mm diameter | Insulation for motor & diode joints |

---

## 3. Power Architecture & Distribution

### 3.1 Voltage Rails
* **5.0V Main Power Rail (VBUS / VIN)**:
  * Sourced from a high-current 5V / 3A USB power bank or 3.7V Li-Ion battery pack with a 5V/3A synchronous boost converter.
  * Powers Raspberry Pi 4 via USB-C.
  * Powers ESP32 via its 5V / VIN pin.
* **3.3V Regulated Rail**:
  * Sourced from the ESP32 onboard 3.3V LDO regulator (e.g., AMS1117-3.3 / ME6211, rated up to 800mA peak).
  * Powers TCA9548A multiplexer ($V_{DD} = 3.3\text{V}$, $\sim 10\text{ \mu A}$).
  * Powers 4x VL53L0X distance sensors ($V_{DD} = 3.3\text{V}$, $\sim 19\text{ mA}$ each active, total $\sim 76\text{ mA}$).
  * Powers the positive terminal of the 6 coin vibration motors ($3.0\text{V} - 3.3\text{V}$, max 2 active simultaneously $\approx 150\text{ mA}$).
  * **Total 3.3V current requirement:** $< 250\text{ mA}$ (well within the 500–800mA limit of ESP32 DevKit LDO).
* **Common System Ground (GND)**:
  * **MANDATORY:** Raspberry Pi 4 GND, ESP32 GND, TCA9548A GND, all 4 VL53L0X GNDs, all 6 transistor emitter grounds, and the pushbutton ground MUST be tied to a unified **Common Star Ground**.

---

## 4. Pinout & Interconnection Table

### 4.1 ESP32 Complete Pin Allocations

| ESP32 Pin | Function / Target | Signal Type | Electrical Characteristic | Circuit Detail |
| :--- | :--- | :--- | :--- | :--- |
| **GPIO 18** | Push Button 1 (User Trigger) | Digital Input | Pulled HIGH internally / active LOW | Other pin of button to GND |
| **GPIO 19** | Push Button 2 (Spare / Aux) | Digital Input | Pulled HIGH internally / active LOW | Other pin of button to GND |
| **GPIO 21** | I2C Data (SDA) | Digital Bi-directional | 3.3V Open-drain, 400 kHz | Connects to TCA9548A `SDA` pin |
| **GPIO 22** | I2C Clock (SCL) | Digital Output | 3.3V Open-drain, 400 kHz | Connects to TCA9548A `SCL` pin |
| **GPIO 25** | Haptic Motor 0 (Left) | PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q0 |
| **GPIO 26** | Haptic Motor 1 (Front-Left) | PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q1 |
| **GPIO 27** | Haptic Motor 2 (Front-Center)| PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q2 |
| **GPIO 14** | Haptic Motor 3 (Front-Right) | PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q3 |
| **GPIO 12** | Haptic Motor 4 (Right) | PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q4 |
| **GPIO 13** | Haptic Motor 5 (Rear) | PWM / Digital Out | 3.3V Logic, $I_{base} \approx 2.6\text{ mA}$ | Through 1kΩ to Base of NPN Transistor Q5 |
| **USB Port** | Serial Bridge to Pi 4 | UART over USB | 115200 baud, 8-N-1 | Plugs into Pi 4 USB 2.0 Port (`/dev/ttyUSB0`)|
| **VIN** | 5V Power Input | Power | 5.0V DC | From System 5V Rail / USB |
| **3V3** | 3.3V Power Output | Power | 3.3V DC (Up to 500mA) | Powers ToF sensors, Mux, Motor positive |
| **GND** | System Ground | Power | 0V Reference | Common Ground Bus |

---

## 5. Detailed Schematic Subsystems

### 5.1 Subsystem A: Haptic Motor Transistor Drivers (Repeated ×6)

Each of the 6 coin vibration motors requires a discrete low-side driver stage to prevent drawing excessive current directly from ESP32 GPIOs and to clamp inductive flyback voltages.

```
                  +3.3V System Rail
                         │
                         ├────────────────────────┐
                         │                        │
                       ┌─┴─┐                     ┌┴┐
                       │ M │ Coin Motor        ▲ │ 1N4148 Diode
                       │   │ 10mm / 3V          │─│ (Cathode to +3.3V,
                       └─┬─┘                    │ │  Anode to Collector)
                         │                       │
                         ├───────────────────────┘
                         │
                     Collector
                         │
                   ┌─────┴─────┐
ESP32 GPIO ──[1 kΩ]─┤ Q1 NPN    │ (2N2222 / BC547)
                    │ (Base)    │
                    └─────┬─────┘
                       Emitter
                         │
                        GND (Common Ground)
```

#### Engineering Specifications:
* **Base Drive Current:**
  $$I_B = \frac{V_{GPIO} - V_{BE}}{R_{Base}} = \frac{3.3\text{ V} - 0.7\text{ V}}{1000\text{ }\Omega} = 2.6\text{ mA}$$
  *(Completely safe for ESP32 pins, which are rated for 12–20mA max).*
* **Collector Saturation:**
  At $I_B = 2.6\text{ mA}$, a 2N2222 with $h_{FE(sat)} \approx 30$ can comfortably switch:
  $$I_{C(sat)} = h_{FE} \times I_B = 30 \times 2.6\text{ mA} = 78\text{ mA}$$
  *(Matches the 70–85mA full-speed coin motor operating draw with $V_{CE(sat)} < 0.2\text{V}$).*
* **Inductive Protection:**
  When the transistor shuts off, the collapsing magnetic field in the motor coils generates a reverse voltage spike ($V = -L \frac{di}{dt}$). The **1N4148 diode** clamps this spike to $V_{CC} + 0.7\text{V}$, preventing transistor breakdown.

---

### 5.2 Subsystem B: TCA9548A I2C Multiplexer & 4x VL53L0X Sensors

The 4 VL53L0X distance sensors share the exact same I2C address (`0x29`). The **TCA9548A** multiplexer operates at address `0x70` and acts as an electronic switch.

```
 ESP32                  TCA9548A Multiplexer (0x70)                 VL53L0X Sensors (0x29)
┌────────┐             ┌─────────────────────────┐
│        │             │                         │
│ GPIO 21├────────────►│ SDA (Main)              │
│ (SDA)  │             │                         │
│        │             │                         │
│ GPIO 22├────────────►│ SCL (Main)         SD0 ├────────────────► Sensor #0 SDA (Left 60°)
│ (SCL)  │             │                    SC0 ├────────────────► Sensor #0 SCL (Left 60°)
│        │             │                         │
│  3.3V  ├──────┬─────►│ VDD                SD1 ├────────────────► Sensor #1 SDA (F-Left 20°)
│        │      │      │                    SC1 ├────────────────► Sensor #1 SCL (F-Left 20°)
│        │     ┌┴┐     │                         │
│        │     │R│ 10k │                    SD2 ├────────────────► Sensor #2 SDA (F-Right 20°)
│        │     └┬┘     │                    SC2 ├────────────────► Sensor #2 SCL (F-Right 20°)
│        │      │      │                         │
│        │      └─────►│ RESET              SD3 ├────────────────► Sensor #3 SDA (Right 60°)
│        │             │                    SC3 ├────────────────► Sensor #3 SCL (Right 60°)
│   GND  ├────────────►│ GND, A0, A1, A2         │
└────────┘             └─────────────────────────┘
```

#### Engineering Specifications:
* **Address Configuration:** Address pins `A0`, `A1`, `A2` of TCA9548A are tied to **GND** $\implies$ I2C address is `0x70`.
* **Reset Pin:** `RESET` must be pulled HIGH to **3.3V** through a 10kΩ pull-up resistor to prevent floating resets.
* **Sensor Pins per VL53L0X:**
  * `VIN` $\to$ Connect to **3.3V Rail**.
  * `GND` $\to$ Connect to **Common Ground**.
  * `SDA` $\to$ Connect to corresponding `SDx` pin on TCA9548A.
  * `SCL` $\to$ Connect to corresponding `SCx` pin on TCA9548A.
  * `XSHUT` $\to$ Leave unconnected (pulled high on breakout).
  * `GPIO1` $\to$ Leave unconnected.

---

### 5.3 Subsystem C: Tactile Push Button Interface

DrishtiCap uses a single tactile button to control all primary functions using an internal state machine.

```
       ESP32 (GPIO 18)
             │
             ├───[ Optional 100nF Cap to GND for ESD / HW Debounce ]
             │
       ┌─────┴─────┐
       │   Push    │
       │  Button   │ (Momentary Tactile Switch)
       └─────┬─────┘
             │
            GND (Common Ground)
```

#### Gesture Mapping (Firmware Controlled):
1. **Single Click (< 400ms hold, 1 pulse)**:
   * Event: `capture_ocr`
   * Pi 4 triggers camera capture $\to$ YOLOv8 bus crop $\to$ Tesseract OCR $\to$ Speaks route & destination.
2. **Double Click (2 clicks within 350ms window)**:
   * Event: `replay_audio`
   * Pi 4 replays the last stored audio announcement without re-running OCR.
3. **Long Press (Held $\ge 1.0\text{s}$ continuously)**:
   * Event: `detect_direction`
   * ESP32 cycles the 4 ToF sensors, computes approach angle, buzzes the directional headband motors, and Pi 4 announces the bus approach sector.

---

## 6. Mechanical Mounting & Spatial Layout on the Cap

```
                                      FRONT OF CAP (VISOR)
                             ┌──────────────────────────────────────┐
                             │               [CAMERA]               │
                             │         Pi Camera Module v2          │
     ToF Sensor #0           │                                      │           ToF Sensor #3
    Angle: -60° (LEFT)       │     ToF #1                ToF #2     │        Angle: +60° (RIGHT)
            \                │  Angle: -20°            Angle: +20°  │                /
             \               └──────────────────────────────────────┘               /
              \                                                                    /
               \               ┌──────────────────────────────────┐               /
                \              │         CAP HEADBAND RING        │              /
                               │                                  │
                               │   Motor 1 (FL)    Motor 3 (FR)   │
                               │        \              /          │
            Motor 0 (Left) ───┤          Motor 2 (FC)            ├─── Motor 4 (Right)
                               │                                  │
                               │                                  │
                               │          Motor 5 (Rear)          │
                               │                 │                │
                               └─────────────────┴────────────────┘
                                           BACK OF CAP
```

### Spatial Alignment Guidelines:
1. **Camera Module**: Placed dead center on the front visor crown, angled slightly downwards ($\sim 5^\circ - 10^\circ$) to match the typical eye-level height of oncoming bus headboards (1.8m to 2.5m off the ground at a distance of 3–8m).
2. **4 ToF Sensors**:
   * **Sensor 0**: Mounted on the left edge of the visor brim, angled at **60° Left**.
   * **Sensor 1**: Mounted on the left-center of the visor brim, angled at **20° Left**.
   * **Sensor 2**: Mounted on the right-center of the visor brim, angled at **20° Right**.
   * **Sensor 3**: Mounted on the right edge of the visor brim, angled at **60° Right**.
3. **6 Haptic Motors**: Sewn or adhered into the sweatband / inner lining of the cap:
   * `M0`: Left temple
   * `M1`: Front-left forehead
   * `M2`: Center forehead
   * `M3`: Front-right forehead
   * `M4`: Right temple
   * `M5`: Rear nape / back strap

---

## 7. Serial Communication Protocol (ESP32 $\leftrightarrow$ Pi 4)

* **Physical Layer:** USB 2.0 Serial via standard USB-A to Micro-USB cable.
* **Baud Rate:** `115200` baud (8 data bits, no parity, 1 stop bit).
* **Format:** Line-delimited JSON (`\n`).

### Telemetry Sent by ESP32 $\to$ Pi 4:
```json
// Single Click (Trigger OCR)
{"event":"single_click","action":"capture_ocr"}

// Double Click (Replay Audio)
{"event":"double_click","action":"replay_audio"}

// Long Press (Bus Approach Direction Result)
{"event":"long_press","action":"detect_direction","direction":"left","distance_cm":145,"closest_channel":0,"sensors":[145,160,200,200]}
```

### Commands Sent by Pi 4 $\to$ ESP32:
```json
// Success confirmation buzz
{"haptic":"success"}

// Error buzz (no route found)
{"haptic":"error"}

// Low confidence warning buzz
{"haptic":"low_conf"}
```

---

## 8. Assembly & Soldering Instructions (Perfboard Layout)

1. **Step 1 – Transistor Driver Array**:
   * Place the six 2N2222 / BC547 transistors in a neat row on the perfboard.
   * Connect all six **Emitters** together and wire them directly to the common **GND rail**.
   * Solder a **1 kΩ resistor** to the **Base** of each transistor. The other end of each resistor goes to a female header pin or wire leading to ESP32 GPIOs `25, 26, 27, 14, 12, 13`.
   * Across the Collector and 3.3V rail for each channel, solder a **1N4148 diode** with the **cathode (black band) facing the +3.3V rail**.
   * Connect each motor's negative wire (blue/black) to the Collector of its corresponding transistor.
   * Connect each motor's positive wire (red) to the **3.3V rail**.
2. **Step 2 – Multiplexer & Sensor Bus**:
   * Solder male/female header pins for the TCA9548A module on the perfboard.
   * Connect TCA9548A `SDA` to ESP32 `GPIO 21`, and `SCL` to ESP32 `GPIO 22`.
   * Run 4 four-conductor ribbon cables (3.3V, GND, SDA, SCL) from the perfboard channels `0, 1, 2, 3` to the 4 VL53L0X sensors on the visor.
3. **Step 3 – Pushbutton Wiring**:
   * Solder a 2-wire twisted pair from the pushbutton on the cap brim to ESP32 `GPIO 18` and `GND`.
4. **Step 4 – Testing Before Power-On**:
   * Use a digital multimeter in continuity mode to verify:
     1. Zero short-circuits between 5V, 3.3V, and GND.
     2. Transistor diodes are installed with correct polarity (Cathode to 3.3V).
     3. Star ground continuity exists between Pi 4, ESP32, and all peripheral components.
