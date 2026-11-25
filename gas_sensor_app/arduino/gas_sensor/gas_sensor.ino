/*
  Gas Sensor Monitor — Arduino (USB Serial + optional Bluetooth)
  ==============================================================
  Wiring:
    Sensor VCC -> 5V
    Sensor GND -> GND
    Sensor AO  -> A0
    LED        -> D13 (add a 220-330 ohm series resistor if using an
                  external LED; D13 of most UNO boards also drives the
                  onboard LED directly)
    Buzzer     -> D8

  Optional Bluetooth (HC-05 / HC-06 "ZS-040" module) — same data stream,
  no USB cable needed:
    Module VCC -> 5V          (ZS-040 breakout has its own regulator)
    Module GND -> GND
    Module TXD -> D10         (module -> Arduino, 3.3 V output is fine)
    Module RXD -> D11 via a divider: 1 kOhm in series, 2 kOhm to GND
                    (the module's RX is 3.3 V logic — don't feed it 5 V)
    Leave EN/KEY unconnected for normal use.
  Pair it once in Windows (PIN 1234, name HC-05), then select the outgoing
  "Standard Serial over Bluetooth link" COM port in the app, 9600 baud.
  Set BT_ENABLED = false if no module is attached.

  Upload at 9600 baud.

  Stream: 16-sample averaged raw ADC (0-1023) every 200 ms, e.g. "512".
  The app ignores non-numeric lines, so "GAS_MONITOR_READY" and the
  occasional "# raw=..." diagnostics are safe to print.

  Gas Saver maps the value to a severity % with Settings -> Raw Sensor
  Calibration (clean-air ADC and danger ADC), so no re-flashing is needed
  when you adjust sensitivity.

  Local LED/buzzer thresholds below are derived from the app's default
  calibration (clean air 250, danger 800) and add hysteresis, so the
  alarm can't chatter right at a boundary. Patterns are non-blocking
  (millis based), so readings keep flowing at a steady rate while an
  alarm is active.

  Note: MQ sensors need 24-48 h of burn-in for stable readings, and each
  board has slightly different Rs/R0 behaviour. The ESP32 sketch performs
  proper Rs/R0 calibration; this USB sketch leaves calibration to the app.
*/

#include <SoftwareSerial.h>

const uint8_t GAS_PIN    = A0;
const uint8_t LED_PIN    = 13;   // onboard LED on most UNO/Nano boards
const uint8_t BUZZER_PIN = 8;

// Bluetooth mirror of the serial stream (HC-05/HC-06 on D10/D11).
// Readings are printed to USB and Bluetooth simultaneously.
const bool    BT_ENABLED = true;
const uint8_t BT_RX_PIN  = 10;   // module TXD -> D10
const uint8_t BT_TX_PIN  = 11;   // module RXD <- D11 (through 1k/2k divider)
SoftwareSerial btSerial(BT_RX_PIN, BT_TX_PIN);

// Local alarm thresholds on the averaged raw ADC (0-1023), matching the
// app defaults: 40 % = 250 + 0.40 * 550 = 470, 70 % = 250 + 0.70 * 550 = 635.
const int WARN_RAW   = 470;
const int DANGER_RAW = 635;
const int HYST_RAW   = 35;   // must fall this far below a threshold to clear it

const unsigned long SAMPLE_INTERVAL_MS = 200;
const unsigned long DANGER_BLINK_MS    = 80;
const unsigned long WARN_BLINK_MS      = 500;
const unsigned long BEEP_PERIOD_MS     = 300;
const unsigned long BEEP_LEN_MS        = 110;
const unsigned long DIAG_INTERVAL_MS   = 10000;

enum AlarmLevel : uint8_t { LVL_SAFE, LVL_WARN, LVL_DANGER };

unsigned long lastSample = 0;
unsigned long lastBlink  = 0;
unsigned long lastBeep   = 0;
unsigned long lastDiag   = 0;
int lastValue = 0;
int diagMin   = 1023;
int diagMax   = 0;
bool ledOn    = false;
AlarmLevel level = LVL_SAFE;

void sayln(const __FlashStringHelper* msg) {
  Serial.println(msg);
  if (BT_ENABLED) btSerial.println(msg);
}

void sayInt(int v) {
  Serial.println(v);
  if (BT_ENABLED) btSerial.println(v);
}

void sayDiag() {
  Print* outs[2] = { &Serial, BT_ENABLED ? &btSerial : nullptr };
  for (Print* out : outs) {
    if (!out) continue;
    out->print(F("# raw=")); out->print(lastValue);
    out->print(F(" min="));  out->print(diagMin);
    out->print(F(" max="));  out->println(diagMax);
  }
}

void setup() {
  Serial.begin(9600);
  if (BT_ENABLED) btSerial.begin(9600);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  delay(800);  // let the port settle after the DTR reset (burn-in takes days)
  sayln(F("GAS_MONITOR_READY"));
  sayln(F("# gas_monitor: raw ADC every 200 ms, 16-sample average"));
}

int readGasRaw() {
  int sum = 0;
  for (uint8_t i = 0; i < 16; i++) sum += analogRead(GAS_PIN);
  return (sum + 8) / 16;  // rounded average
}

AlarmLevel levelFor(int v) {
  if (v >= DANGER_RAW) return LVL_DANGER;
  if (level == LVL_DANGER && v >= DANGER_RAW - HYST_RAW) return LVL_DANGER;
  if (v >= WARN_RAW) return LVL_WARN;
  if (level == LVL_WARN && v >= WARN_RAW - HYST_RAW) return LVL_WARN;
  return LVL_SAFE;
}

void updateAlarm(unsigned long now, AlarmLevel newLevel) {
  if (newLevel != level) {
    level = newLevel;
    if (level != LVL_DANGER) noTone(BUZZER_PIN);  // cut any in-flight beep
    lastBlink = now - WARN_BLINK_MS;              // turn on immediately
  }

  if (level == LVL_SAFE) {
    if (ledOn) {
      digitalWrite(LED_PIN, LOW);
      ledOn = false;
    }
    return;
  }

  const unsigned long period = (level == LVL_DANGER) ? DANGER_BLINK_MS : WARN_BLINK_MS;
  if (now - lastBlink >= period) {
    lastBlink = now;
    ledOn = !ledOn;
    digitalWrite(LED_PIN, ledOn ? HIGH : LOW);
  }

  if (level == LVL_DANGER && now - lastBeep >= BEEP_PERIOD_MS) {
    lastBeep = now;
    tone(BUZZER_PIN, 1000, BEEP_LEN_MS);  // non-blocking: stops by itself
  }
}

void loop() {
  unsigned long now = millis();

  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    lastValue = readGasRaw();
    if (lastValue < diagMin) diagMin = lastValue;
    if (lastValue > diagMax) diagMax = lastValue;
    sayInt(lastValue);
    updateAlarm(now, levelFor(lastValue));
  }

  if (now - lastDiag >= DIAG_INTERVAL_MS) {
    lastDiag = now;
    sayDiag();
    diagMin = 1023;
    diagMax = 0;
  }
}
