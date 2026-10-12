#ifndef TOF_MANAGER_H
#define TOF_MANAGER_H

#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>

#define TCA9548A_I2C_ADDR 0x70
#define NUM_TOF_SENSORS   4
#define TOF_MAX_RANGE_MM  2000

enum class ApproachDirection {
    CLEAR,
    LEFT,
    FRONT,
    RIGHT
};

struct ToFScanResult {
    ApproachDirection direction;
    const char* directionStr;
    uint16_t minDistanceCm;
    uint8_t closestChannel;
    uint16_t distancesCm[NUM_TOF_SENSORS];
};

class ToFManager {
public:
    ToFManager() {
        for (int i = 0; i < NUM_TOF_SENSORS; i++) {
            m_initialized[i] = false;
        }
    }

    void begin() {
        Wire.begin();
        Wire.setClock(400000); // 400kHz Fast I2C

        for (uint8_t ch = 0; ch < NUM_TOF_SENSORS; ch++) {
            selectChannel(ch);
            m_sensors[ch].setTimeout(100);
            if (m_sensors[ch].init()) {
                m_initialized[ch] = true;
                // High-speed 30ms measurement budget
                m_sensors[ch].setMeasurementTimingBudget(30000);
                m_sensors[ch].startContinuous();
            }
        }
    }

    void selectChannel(uint8_t channel) {
        if (channel > 7) return;
        Wire.beginTransmission(TCA9548A_I2C_ADDR);
        Wire.write(1 << channel);
        Wire.endTransmission();
    }

    ToFScanResult scanDirection() {
        ToFScanResult result;
        result.direction = ApproachDirection::CLEAR;
        result.directionStr = "clear";
        result.minDistanceCm = 200;
        result.closestChannel = 255;

        uint16_t minMm = 8190;
        int closestIdx = -1;

        for (uint8_t ch = 0; ch < NUM_TOF_SENSORS; ch++) {
            result.distancesCm[ch] = 200; // default 2m
            if (!m_initialized[ch]) continue;

            selectChannel(ch);
            uint16_t distMm = m_sensors[ch].readRangeContinuousMillimeters();

            if (distMm < 8000 && !m_sensors[ch].timeoutOccurred()) {
                uint16_t distCm = distMm / 10;
                result.distancesCm[ch] = distCm;

                if (distMm < minMm && distMm > 40) { // filter noise < 40mm
                    minMm = distMm;
                    closestIdx = ch;
                }
            }
        }

        if (closestIdx != -1 && minMm <= TOF_MAX_RANGE_MM) {
            result.minDistanceCm = minMm / 10;
            result.closestChannel = closestIdx;

            // Sector logic
            // Ch 0: Left 60 deg, Ch 1: Front-Left 20 deg, Ch 2: Front-Right 20 deg, Ch 3: Right 60 deg
            if (closestIdx == 0) {
                result.direction = ApproachDirection::LEFT;
                result.directionStr = "left";
            } else if (closestIdx == 1) {
                // If Ch 2 is also within range and close, classify as frontal arrival
                if (result.distancesCm[2] <= 200 && abs((int)result.distancesCm[1] - (int)result.distancesCm[2]) < 30) {
                    result.direction = ApproachDirection::FRONT;
                    result.directionStr = "front";
                } else {
                    result.direction = ApproachDirection::LEFT;
                    result.directionStr = "left";
                }
            } else if (closestIdx == 2) {
                if (result.distancesCm[1] <= 200 && abs((int)result.distancesCm[1] - (int)result.distancesCm[2]) < 30) {
                    result.direction = ApproachDirection::FRONT;
                    result.directionStr = "front";
                } else {
                    result.direction = ApproachDirection::RIGHT;
                    result.directionStr = "right";
                }
            } else if (closestIdx == 3) {
                result.direction = ApproachDirection::RIGHT;
                result.directionStr = "right";
            }
        }

        return result;
    }

    bool isSensorActive(uint8_t ch) const {
        return (ch < NUM_TOF_SENSORS) ? m_initialized[ch] : false;
    }

private:
    VL53L0X m_sensors[NUM_TOF_SENSORS];
    bool m_initialized[NUM_TOF_SENSORS];
};

#endif // TOF_MANAGER_H
