/*
 * drishticap_arduino.ino
 * ======================
 * DrishtiCap Real-Time Assistive Wearable Firmware for Arduino
 * (Compatible with Arduino Uno, Nano, Mega, Pro Micro, Leonardo).
 *
 * HARDWARE WIRING:
 * ----------------
 * 1. Pushbutton:
 *    - One side to Pin D2 (INPUT_PULLUP, active LOW)
 *    - Other side to GND
 * 2. Haptic Vibration Motor / Buzzer:
 *    - Pin D3 (via 2N2222 / BC547 NPN transistor base resistor 1k or MOSFET gate)
 * 3. Distance Sensor (Optional HC-SR04 Ultrasonic or ToF):
 *    - TRIG: Pin D7
 *    - ECHO: Pin D8
 *    - VCC: 5V, GND: GND
 *
 * SERIAL PROTOCOL:
 * ----------------
 * Baud rate: 115200 (or 9600)
 * Sends JSON to Host:
 *   {"event":"single_click"}   -> Trigger camera capture + OCR
 *   {"event":"double_click"}   -> Replay last spoken announcement
 *   {"event":"long_press", "direction":"front", "distance_cm":50} -> Distance check
 * Receives JSON from Host:
 *   {"haptic":"success"}       -> 150ms single pulse
 *   {"haptic":"low_conf"}      -> Two 80ms pulses
 *   {"haptic":"error"}         -> 400ms long pulse
 */

const int BUTTON_PIN = 2;       // Tactile push button (Active LOW)
const int HAPTIC_PIN = 3;       // Vibration motor / PWM buzzer
const int TRIG_PIN   = 7;       // Optional Ultrasonic Trig
const int ECHO_PIN   = 8;       // Optional Ultrasonic Echo

// Button Timing Parameters
const unsigned long DEBOUNCE_MS     = 40;
const unsigned long DOUBLE_CLICK_MS = 350;
const unsigned long LONG_PRESS_MS   = 1000;

// State Machine Variables
int buttonState = HIGH;
int lastReading = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long pressStartTime  = 0;
bool isPressed = false;
bool longPressTriggered = false;
int clickCount = 0;
unsigned long lastReleaseTime = 0;

// Function Prototypes
void triggerHaptic(int durationMs);
void triggerDoubleHaptic();
void triggerErrorHaptic();
long measureDistanceCm();
void handleIncomingSerial();

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000); // Wait for native USB if Leonardo/Micro

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(HAPTIC_PIN, OUTPUT);
  digitalWrite(HAPTIC_PIN, LOW);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Power-on welcome buzz (80ms)
  triggerHaptic(80);

  Serial.println("{\"status\":\"ready\",\"device\":\"DrishtiCap-Arduino\",\"version\":\"1.0\"}");
}

void loop() {
  int reading = digitalRead(BUTTON_PIN);
  unsigned long now = millis();

  // Debounce filter
  if (reading != lastReading) {
    lastDebounceTime = now;
  }

  if ((now - lastDebounceTime) > DEBOUNCE_MS) {
    if (reading != buttonState) {
      buttonState = reading;

      if (buttonState == LOW) {
        // Button Pressed
        isPressed = true;
        pressStartTime = now;
        longPressTriggered = false;
      } else {
        // Button Released
        if (isPressed && !longPressTriggered) {
          clickCount++;
          lastReleaseTime = now;
        }
        isPressed = false;
      }
    }
  }

  // Check for Long Press (held down for >= 1s)
  if (isPressed && !longPressTriggered && (now - pressStartTime >= LONG_PRESS_MS)) {
    longPressTriggered = true;
    clickCount = 0; // Cancel single/double click

    // Measure distance
    long distCm = measureDistanceCm();
    String direction = "front";
    if (distCm > 200 || distCm <= 0) {
      direction = "clear";
    }

    // Acknowledge long press with short haptic pulse
    triggerHaptic(120);

    // Send long press telemetry to Host
    Serial.print("{\"event\":\"long_press\",\"direction\":\"");
    Serial.print(direction);
    Serial.print("\",\"distance_cm\":");
    Serial.print(distCm);
    Serial.println("}");
  }

  // Multi-click evaluation after release timeout
  if (clickCount > 0 && (now - lastReleaseTime > DOUBLE_CLICK_MS) && !isPressed) {
    if (clickCount == 1) {
      // 1 Click (Short): Capture & OCR
      triggerHaptic(60);
      Serial.println("{\"event\":\"single_click\"}");
    } else if (clickCount >= 2) {
      // 2 Clicks (Double): Replay Announcement
      triggerDoubleHaptic();
      Serial.println("{\"event\":\"double_click\"}");
    }
    clickCount = 0;
  }

  lastReading = reading;

  // Process Host Haptic Commands
  handleIncomingSerial();
}

// Measure distance in cm using ultrasonic sensor
long measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 25000); // 25ms timeout (~4m max)
  if (duration == 0) return 250; // Timeout = clear
  return duration * 0.034 / 2;
}

// Single haptic pulse
void triggerHaptic(int durationMs) {
  digitalWrite(HAPTIC_PIN, HIGH);
  delay(durationMs);
  digitalWrite(HAPTIC_PIN, LOW);
}

// Two quick pulses for low confidence or double click
void triggerDoubleHaptic() {
  digitalWrite(HAPTIC_PIN, HIGH);
  delay(80);
  digitalWrite(HAPTIC_PIN, LOW);
  delay(80);
  digitalWrite(HAPTIC_PIN, HIGH);
  delay(80);
  digitalWrite(HAPTIC_PIN, LOW);
}

// Long error pulse
void triggerErrorHaptic() {
  digitalWrite(HAPTIC_PIN, HIGH);
  delay(400);
  digitalWrite(HAPTIC_PIN, LOW);
}

// Parse incoming serial JSON or plaintext tokens from Host PC / Pi
void handleIncomingSerial() {
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    if (line.indexOf("success") >= 0 || line.indexOf("SUCCESS") >= 0) {
      triggerHaptic(150);
    } else if (line.indexOf("low_conf") >= 0 || line.indexOf("LOW_CONF") >= 0) {
      triggerDoubleHaptic();
    } else if (line.indexOf("error") >= 0 || line.indexOf("ERROR") >= 0) {
      triggerErrorHaptic();
    }
  }
}
