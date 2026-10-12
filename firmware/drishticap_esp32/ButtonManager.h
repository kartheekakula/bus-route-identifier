#ifndef BUTTON_MANAGER_H
#define BUTTON_MANAGER_H

#include <Arduino.h>

enum class ButtonGesture {
    NONE,
    SINGLE_CLICK,
    DOUBLE_CLICK,
    LONG_PRESS
};

class ButtonManager {
public:
    ButtonManager(uint8_t pin, unsigned long debounceMs = 40, unsigned long doubleClickMs = 350, unsigned long longPressMs = 1000)
        : m_pin(pin), m_debounceMs(debounceMs), m_doubleClickMs(doubleClickMs), m_longPressMs(longPressMs),
          m_buttonState(HIGH), m_lastReading(HIGH), m_lastDebounceTime(0),
          m_pressStartTime(0), m_isPressing(false), m_longPressFired(false),
          m_clickCount(0), m_lastReleaseTime(0) {}

    void begin() {
        pinMode(m_pin, INPUT_PULLUP);
    }

    ButtonGesture update() {
        unsigned long now = millis();
        int reading = digitalRead(m_pin);

        // Software debouncing
        if (reading != m_lastReading) {
            m_lastDebounceTime = now;
        }

        if ((now - m_lastDebounceTime) > m_debounceMs) {
            if (reading != m_buttonState) {
                m_buttonState = reading;

                // Button Transition: Pressed Down (LOW)
                if (m_buttonState == LOW) {
                    m_isPressing = true;
                    m_pressStartTime = now;
                    m_longPressFired = false;
                }
                // Button Transition: Released (HIGH)
                else {
                    if (m_isPressing && !m_longPressFired) {
                        m_clickCount++;
                        m_lastReleaseTime = now;
                    }
                    m_isPressing = false;
                }
            }
        }
        m_lastReading = reading;

        // 1. Long Press Detection
        if (m_isPressing && !m_longPressFired && (now - m_pressStartTime >= m_longPressMs)) {
            m_longPressFired = true;
            m_clickCount = 0; // Cancel pending click gestures
            return ButtonGesture::LONG_PRESS;
        }

        // 2. Click Window Expiration (Single vs Double Click)
        if (m_clickCount > 0 && !m_isPressing && (now - m_lastReleaseTime > m_doubleClickMs)) {
            ButtonGesture gesture = (m_clickCount >= 2) ? ButtonGesture::DOUBLE_CLICK : ButtonGesture::SINGLE_CLICK;
            m_clickCount = 0;
            return gesture;
        }

        return ButtonGesture::NONE;
    }

private:
    uint8_t m_pin;
    unsigned long m_debounceMs;
    unsigned long m_doubleClickMs;
    unsigned long m_longPressMs;

    int m_buttonState;
    int m_lastReading;
    unsigned long m_lastDebounceTime;

    unsigned long m_pressStartTime;
    bool m_isPressing;
    bool m_longPressFired;
    int m_clickCount;
    unsigned long m_lastReleaseTime;
};

#endif // BUTTON_MANAGER_H
