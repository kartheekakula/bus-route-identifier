#ifndef HAPTIC_DRIVER_H
#define HAPTIC_DRIVER_H

#include <Arduino.h>
#include "ToFManager.h"

#define NUM_HAPTIC_MOTORS 6

class HapticDriver {
public:
    // Pin layout:
    // 0: Left (25), 1: Front-Left (26), 2: Front-Center (27),
    // 3: Front-Right (14), 4: Right (12), 5: Rear (13)
    HapticDriver(const uint8_t pins[NUM_HAPTIC_MOTORS]) {
        for (int i = 0; i < NUM_HAPTIC_MOTORS; i++) {
            m_pins[i] = pins[i];
        }
    }

    void begin() {
        for (int i = 0; i < NUM_HAPTIC_MOTORS; i++) {
            pinMode(m_pins[i], OUTPUT);
            digitalWrite(m_pins[i], LOW);
        }
    }

    void buzzMotor(uint8_t index, uint16_t durationMs) {
        if (index >= NUM_HAPTIC_MOTORS) return;
        digitalWrite(m_pins[index], HIGH);
        delay(durationMs);
        digitalWrite(m_pins[index], LOW);
    }

    void buzzAll(uint16_t durationMs) {
        for (int i = 0; i < NUM_HAPTIC_MOTORS; i++) digitalWrite(m_pins[i], HIGH);
        delay(durationMs);
        for (int i = 0; i < NUM_HAPTIC_MOTORS; i++) digitalWrite(m_pins[i], LOW);
    }

    void playWelcomeSweep() {
        for (int i = 0; i < NUM_HAPTIC_MOTORS; i++) {
            digitalWrite(m_pins[i], HIGH);
            delay(40);
            digitalWrite(m_pins[i], LOW);
        }
    }

    void playSuccessTap() {
        buzzMotor(2, 140); // 140ms front pulse
    }

    void playReplayTap() {
        buzzMotor(2, 60);
        delay(50);
        buzzMotor(2, 60);
    }

    void playErrorPulse() {
        buzzAll(350); // 350ms long alert pulse
    }

    void playLowConfidence() {
        buzzMotor(2, 80);
        delay(60);
        buzzMotor(2, 80);
    }

    void playDirectionWave(ApproachDirection dir) {
        switch (dir) {
            case ApproachDirection::LEFT:
                // Sweep Left (0) -> Front-Left (1)
                digitalWrite(m_pins[0], HIGH);
                delay(90);
                digitalWrite(m_pins[0], LOW);
                digitalWrite(m_pins[1], HIGH);
                delay(120);
                digitalWrite(m_pins[1], LOW);
                break;

            case ApproachDirection::RIGHT:
                // Sweep Right (4) -> Front-Right (3)
                digitalWrite(m_pins[4], HIGH);
                delay(90);
                digitalWrite(m_pins[4], LOW);
                digitalWrite(m_pins[3], HIGH);
                delay(120);
                digitalWrite(m_pins[3], LOW);
                break;

            case ApproachDirection::FRONT:
                // Dual pinch: Front-Left (1) & Front-Right (3) -> Front-Center (2)
                digitalWrite(m_pins[1], HIGH);
                digitalWrite(m_pins[3], HIGH);
                delay(80);
                digitalWrite(m_pins[1], LOW);
                digitalWrite(m_pins[3], LOW);
                digitalWrite(m_pins[2], HIGH);
                delay(140);
                digitalWrite(m_pins[2], LOW);
                break;

            case ApproachDirection::CLEAR:
            default:
                buzzMotor(2, 50);
                delay(50);
                buzzMotor(2, 50);
                break;
        }
    }

private:
    uint8_t m_pins[NUM_HAPTIC_MOTORS];
};

#endif // HAPTIC_DRIVER_H
