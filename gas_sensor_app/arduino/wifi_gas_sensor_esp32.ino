/*
  Gas Saver Pro — WiFi Gas Sensor (ESP32 / ESP8266)
  ==================================================
  Sends calibrated gas severity to the Gas Saver desktop app over WiFi.

  Wiring (typical):
    MQ sensor VCC -> 5V (ESP32 VIN / ESP8266 VIN), GND -> GND
    MQ AO         -> ESP32 GPIO34 (ADC1) / ESP8266 A0 (through a divider)
    Status LED    -> GPIO2 (ESP32) / built-in LED (ESP8266)

  Why not "raw / 1023 * 100"? ADC counts are not a gas percentage. An MQ
  sensor's useful signal is its heater resistance Rs relative to the value
  measured in clean air (R0):

      Rs    = RL * (Vcc - Vout) / Vout
      ratio = Rs / R0          (1.0 = clean air, lower = more gas)
      pct   = 0 %   when ratio >= 1.0
              100 % when ratio <= DANGER_RATIO
              linear in between

  Calibration:
    AUTO_CALIBRATE = true  -> R0 is measured for CALIBRATION_MS at every boot.
                              Power the board up in CLEAN AIR!
    AUTO_CALIBRATE = false -> uses MANUAL_R0 (set it from a previous boot's log).
  MQ sensors need 24-48 h of burn-in for stable readings.

  ADC notes:
    ESP32 GPIO34 is 12-bit (0-4095). The MQ output can reach 5 V, so use a
    1:2 divider (ADC_DIVIDER = 2.0) or power the heater from 3.3 V.
    ESP8266 A0 is 10-bit and accepts max 1.0 V, so a divider is mandatory
    (e.g. 20k / 10k -> ADC_DIVIDER = 3.0).
    Because R0 is measured with the same divider, the Rs/R0 ratio — and thus
    the severity percentage — stays correct even if the divider is imperfect.

  Endpoints:
    GET  http://<sensor-ip>/gas        -> current reading as JSON
    POST http://<PC-IP>:5000/api/sensor -> pushed automatically every second
*/

#if defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WebServer.h>
  WebServer server(80);
  const int GAS_ANALOG_PIN = 34;   // ADC1 pin
  const int LED_PIN = 2;
  const int ADC_MAX_RAW = 4095;
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <ESP8266WebServer.h>
  ESP8266WebServer server(80);
  const int GAS_ANALOG_PIN = A0;
  const int LED_PIN = LED_BUILTIN;
  const int ADC_MAX_RAW = 1023;
#else
  #error "This sketch targets ESP32 or ESP8266"
#endif

// ── WiFi Credentials (CHANGE THESE) ─────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ── Gas Saver PC Hub ─────────────────────────────────────────────────────────
const char* GAS_SAVER_PC_IP = "192.168.1.100";  // shown in the app / WiFi Hub dialog
const int   GAS_SAVER_PORT  = 5000;
const int   ROOM_ID         = 0;
const char* ROOM_NAME       = "Kitchen";

// ── Sensor / ADC configuration ───────────────────────────────────────────────
const float VCC_VOLTS     = 3.3;      // ADC reference voltage of the board
const float RL_OHMS       = 10000.0;  // load resistor on the MQ module
const float ADC_DIVIDER   = 1.0;      // voltage divider factor (see notes above)

// ── Calibration ──────────────────────────────────────────────────────────────
const bool          AUTO_CALIBRATE  = true;
const unsigned long CALIBRATION_MS  = 20000;
const float         MANUAL_R0       = 10000.0;

// ── Severity curve ───────────────────────────────────────────────────────────
const float DANGER_RATIO = 0.35;      // ratio at which severity reaches 100 %

const unsigned long SEND_INTERVAL_MS = 1000;
const unsigned long RECONNECT_MS     = 10000;

unsigned long lastSendTime = 0;
unsigned long lastReconnect = 0;
float r0 = MANUAL_R0;

// ── Measurements ─────────────────────────────────────────────────────────────
int readGasRaw() {
  long sum = 0;
  for (int i = 0; i < 16; i++) sum += analogRead(GAS_ANALOG_PIN);
  return (int)(sum / 16);
}

float rawToVolts(int raw) {
  return (raw / (float)ADC_MAX_RAW) * VCC_VOLTS * ADC_DIVIDER;
}

float voltsToRs(float v) {
  if (v < 0.01f) return 1e9f;                 // rail low -> no conduction
  if (v > VCC_VOLTS * 0.99f) return 1.0f;     // rail high -> sensor shorted
  return RL_OHMS * (VCC_VOLTS - v) / v;
}

float severityFromRatio(float ratio) {
  if (ratio >= 1.0f) return 0.0f;
  if (ratio <= DANGER_RATIO) return 100.0f;
  return (1.0f - ratio) / (1.0f - DANGER_RATIO) * 100.0f;
}

float calibrateR0() {
  Serial.printf("Calibrating R0 in clean air for %lu s...\n", CALIBRATION_MS / 1000);
  unsigned long start = millis();
  double sum = 0.0;
  int n = 0;
  int lastTick = -1;
  while (millis() - start < CALIBRATION_MS) {
    float rs = voltsToRs(rawToVolts(readGasRaw()));
    if (rs > 0 && rs < 1e8f) { sum += rs; n++; }
    int tick = (millis() - start) / 1000;
    if (tick != lastTick) {
      lastTick = tick;
      Serial.printf("  %ds  Rs=%.0f ohm\n", tick, rs);
    }
    delay(100);
  }
  if (n == 0) {
    Serial.println("Calibration failed — using MANUAL_R0");
    return MANUAL_R0;
  }
  float measured = (float)(sum / n);
  Serial.printf("R0 = %.0f ohm (%d samples)\n", measured, n);
  return measured;
}

struct Reading {
  int raw;
  float volts;
  float rs;
  float ratio;
  float pct;
};

void sendReadingToHub(const Reading& r);

Reading takeReading() {
  Reading r;
  r.raw = readGasRaw();
  r.volts = rawToVolts(r.raw);
  r.rs = voltsToRs(r.volts);
  r.ratio = r.rs / max(r0, 1.0f);
  r.pct = severityFromRatio(r.ratio);
  return r;
}

String readingToJson(const Reading& r, bool withStatus) {
  String j = "{";
  j += "\"room_id\":" + String(ROOM_ID) + ",";
  j += "\"room_name\":\"" + String(ROOM_NAME) + "\",";
  j += "\"value\":" + String(r.raw) + ",";
  j += "\"volts\":" + String(r.volts, 3) + ",";
  j += "\"rs\":" + String(r.rs, 1) + ",";
  j += "\"r0\":" + String(r0, 1) + ",";
  j += "\"ratio\":" + String(r.ratio, 3) + ",";
  j += "\"pct\":" + String(r.pct, 1);
  if (withStatus) j += ",\"status\":\"OK\"";
  j += "}";
  return j;
}

// ── Web Server Route: http://<sensor-ip>/gas ─────────────────────────────────
void handleGetGas() {
  Reading r = takeReading();
  server.send(200, "application/json", readingToJson(r, true));
}

void connectWiFi() {
  Serial.printf("Connecting to WiFi: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(400);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_PIN, HIGH);
    Serial.print("Connected! Sensor IP: ");
    Serial.println(WiFi.localIP());
    Serial.println("Tip: this IP works directly in Gas Saver -> Add Room -> WiFi Poll.");
  } else {
    Serial.println("WiFi not connected yet — will keep retrying.");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  delay(1000);

  #if defined(ESP32)
    analogReadResolution(12);
    #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
      analogSetAttenuation(ADC_ATTEN_DB_11);
    #else
      analogSetAttenuation(ADC_11db);
    #endif
  #endif

  Serial.println("\n======================================");
  Serial.println("  Gas Saver — WiFi Sensor Starting...");
  Serial.println("======================================");

  connectWiFi();

  if (AUTO_CALIBRATE) {
    r0 = calibrateR0();
  } else {
    r0 = MANUAL_R0;
    Serial.printf("Using MANUAL_R0 = %.0f ohm\n", r0);
  }

  server.on("/gas", HTTP_GET, handleGetGas);
  server.on("/", HTTP_GET, handleGetGas);
  server.begin();
  Serial.println("HTTP web server running on port 80");
}

void loop() {
  server.handleClient();

  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED && now - lastReconnect >= RECONNECT_MS) {
    lastReconnect = now;
    Serial.println("[WiFi] Reconnecting...");
    WiFi.reconnect();
  }

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    Reading r = takeReading();

    // Heartbeat LED: short blink when safe, fast blink on danger
    if (r.pct >= 70.0f) {
      digitalWrite(LED_PIN, (now / 100) % 2);
    } else {
      digitalWrite(LED_PIN, (now % 2000) < 30 ? HIGH : LOW);
    }

    sendReadingToHub(r);
  }
}

// ── Send reading automatically via HTTP POST to Gas Saver ────────────────────
void sendReadingToHub(const Reading& r) {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  String url = "http://" + String(GAS_SAVER_PC_IP) + ":" + String(GAS_SAVER_PORT) + "/api/sensor";

  http.begin(client, url);
  http.setTimeout(2000);
  http.addHeader("Content-Type", "application/json");

  int httpCode = http.POST(readingToJson(r, false));

  if (httpCode > 0) {
    Serial.printf("[WiFi Post] raw=%d ratio=%.3f pct=%.1f%% -> %s [Code %d]\n",
                  r.raw, r.ratio, r.pct, GAS_SAVER_PC_IP, httpCode);
  } else {
    Serial.printf("[WiFi Post Error] Code: %d (%s)\n", httpCode, http.errorToString(httpCode).c_str());
  }

  http.end();
}
