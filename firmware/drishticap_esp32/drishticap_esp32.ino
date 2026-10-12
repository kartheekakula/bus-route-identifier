/*
 * drishticap_esp32.ino
 * ====================
 * DrishtiCap Real-Time I/O Firmware (ESP32 - Modular C++)
 *
 * Modules:
 *   - ButtonManager: Single-button 3-gesture state machine (1-click, 2-clicks, long-press)
 *   - ToFManager: TCA9548A I2C Multiplexer + 4x VL53L0X Distance Sensors
 *   - HapticDriver: 6-Zone Transistor-driven Headband Vibration Motors
 *
 * Hardware Map:
 *   - Button: GPIO 18 (PULLUP)
 *   - I2C (TCA9548A): SDA=GPIO 21, SCL=GPIO 22
 *   - 6 Haptic Motors: GPIO 25, 26, 27, 14, 12, 13
 *   - USB Serial to Pi 4: 115200 baud
 */

#include "ButtonManager.h"
#include "ToFManager.h"
#include "HapticDriver.h"

// -----------------------------------------------------------------------------
// HARDWARE INSTANCES
// -----------------------------------------------------------------------------
#define BUTTON_PIN 18
const uint8_t HAPTIC_PINS[NUM_HAPTIC_MOTORS] = {25, 26, 27, 14, 12, 13};

ButtonManager button(BUTTON_PIN, 40, 350, 1000);
ToFManager    tof;
HapticDriver  haptics(HAPTIC_PINS);

// -----------------------------------------------------------------------------
// SETUP
// -----------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);

    button.begin();
    haptics.begin();
    tof.begin();

    // Haptic self-test circular sweep
    haptics.playWelcomeSweep();

    Serial.println("{\"status\":\"ready\",\"device\":\"DrishtiCap-ESP32\",\"core\":\"cpp-modular\",\"version\":\"2.1\"}");
}

// -----------------------------------------------------------------------------
// MAIN LOOP
// -----------------------------------------------------------------------------
void loop() {
    // 1. Update Button Gesture State Machine
    ButtonGesture gesture = button.update();

    if (gesture == ButtonGesture::SINGLE_CLICK) {
        // --- 1 CLICK: Capture Image & Run OCR ---
        haptics.playSuccessTap();
        Serial.println("{\"event\":\"single_click\",\"action\":\"capture_ocr\"}");
    }
    else if (gesture == ButtonGesture::DOUBLE_CLICK) {
        // --- 2 CLICKS: Replay Last Audio ---
        haptics.playReplayTap();
        Serial.println("{\"event\":\"double_click\",\"action\":\"replay_audio\"}");
    }
    else if (gesture == ButtonGesture::LONG_PRESS) {
        // --- LONG PRESS: ToF Bus Direction Detection ---
        haptics.buzzMotor(2, 60); // feedback tap confirming scan start

        ToFScanResult scan = tof.scanDirection();

        // Trigger spatial directional wave on the cap headband
        haptics.playDirectionWave(scan.direction);

        // Send telemetry to Raspberry Pi 4
        Serial.print("{\"event\":\"long_press\",\"action\":\"detect_direction\",\"direction\":\"");
        Serial.print(scan.directionStr);
        Serial.print("\",\"distance_cm\":");
        Serial.print(scan.minDistanceCm);
        Serial.print(",\"closest_channel\":");
        Serial.print(scan.closestChannel);
        Serial.print(",\"sensors\":[");
        for (int i = 0; i < NUM_TOF_SENSORS; i++) {
            Serial.print(scan.distancesCm[i]);
            if (i < NUM_TOF_SENSORS - 1) Serial.print(",");
        }
        Serial.println("]}");
    }

    // 2. Process incoming commands from Raspberry Pi 4
    if (Serial.available() > 0) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd.indexOf("\"haptic\":\"success\"") >= 0) {
            haptics.playSuccessTap();
        } else if (cmd.indexOf("\"haptic\":\"error\"") >= 0) {
            haptics.playErrorPulse();
        } else if (cmd.indexOf("\"haptic\":\"low_conf\"") >= 0) {
            haptics.playLowConfidence();
        }
    }

    delay(5);
}
