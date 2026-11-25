# ☣ Gas Saver Pro — Advanced Multi-Room WiFi Gas Monitor

A real-time, multi-room gas safety & monitoring system with **WiFi (ESP32/ESP8266)**, **USB Serial (Arduino)**, and **Simulated** sensor connectivity, automated safety valves, and multi-channel alerts (Sirens, Windows Toast, Email, Telegram).

It ships with a **desktop app** (Tkinter) and a **phone-first web dashboard** that connects to the desktop app's live data hub. Sensor readings are calibrated (Rs/R0 for WiFi sensors), offline sensors are clearly flagged instead of showing fake data, and settings/rooms/logs persist between runs.

---

## 🚀 Quick Start

**Requirements:** Windows 10/11, Python 3.10+ (Tkinter included). `pyserial`, `plyer` (toast
notifications) and `requests` (WiFi modes, email/Telegram alerts) are the only extra packages.

### 1. Install Dependencies
Double-click **`install.bat`** or run:
```bash
pip install pyserial plyer requests
```

### 2. Launch the App
Double-click **`run_app.bat`** or run:
```bash
python gas_monitor.py
```

### 3. (Optional) Launch the Web Dashboard
Keep the desktop app running, then double-click **`run_web_dashboard.bat`** and open `http://localhost:8080`.
The dashboard automatically pulls **live data** from the desktop hub on port 5000. If the hub can't be
reached it clearly switches to **DEMO (SIMULATED)** mode — tap the ⚙ button to point it at another hub,
e.g. your phone connecting to `http://<PC-IP>:8080`.

Every reading is also streamed to **`gas_log.csv`** while the app runs, and your rooms, thresholds and
notification settings are saved in **`config.json`** (created on first close).

---

## 📶 Connecting Gas Sensors via WiFi (ESP32 / ESP8266)

You can connect unlimited wireless gas sensors throughout your building over local WiFi!

### Hardware Setup
| Sensor Pin | ESP32 Pin | ESP8266 Pin | Notes |
|:---:|:---:|:---:|:---|
| **VCC** | 5V / VIN | 5V / VIN | Power supply |
| **GND** | GND | GND | Ground |
| **AO (Analog)** | GPIO 34 (A0) | A0 | Gas reading signal |
| **Status LED** | GPIO 2 | D4 | Built-in LED indicator |

Compatible sensors: **MQ-2** (LPG/Smoke), **MQ-4** (Natural Gas), **MQ-7** (CO), **MQ-9** (CO/Flammable), **MQ-135** (Air Quality/VOC).

---

### Which connection mode should I use?

| Mode | Best for | How it works |
|---|---|---|
| 🔹 **WiFi Push (A)** | One sensor per room, lowest latency | The sensor POSTs to the PC every second — set `ROOM_ID` / `ROOM_NAME` in the sketch |
| 🔹 **WiFi HTTP Poll (B)** | Any device that can reach the sensor's IP | The app GETs `http://<sensor-ip>/gas` once per second |
| 🔌 **USB Serial** | Arduino UNO/Nano plugged into this PC | Serial stream at 9600 baud, 5 readings/s, calibration in the app |

All modes report the same 0–100 % severity. Unreachable sensors are flagged **OFFLINE** after ~12 s — the app never fakes a reading.

---

### Two Supported WiFi Connection Modes:

#### 🔹 Mode A: WiFi Push (Recommended)
1. Open [`arduino/wifi_gas_sensor_esp32.ino`](file:///c:/Users/steam/Desktop/stem%20c/gas_sensor_app/arduino/wifi_gas_sensor_esp32.ino) in Arduino IDE.
2. Enter your **WiFi SSID & Password**.
3. Set `GAS_SAVER_PC_IP` to your PC's IP address (shown in the app header or under **Rooms -> 📶 WiFi Hub & Setup**).
4. Set `ROOM_ID` to the room number shown in the app (first room = `0`) and `ROOM_NAME` to its label, e.g. `"Kitchen"`.
5. Flash the board. The sensor will automatically POST live gas values to your PC every second!

> **Calibration:** the sketch powers up in **clean air** and measures the sensor's baseline
> resistance `R0` for 20 s (set `AUTO_CALIBRATE = false` + `MANUAL_R0` if the unit may boot in a
> gassy room). Readings are sent as an Rs/R0 ratio mapped to 0–100 % severity, which is far more
> meaningful than raw ADC counts. See the comments at the top of the sketch for ADC wiring details
> (voltage dividers matter on ESP32/ESP8266).

#### 🔹 Mode B: WiFi HTTP Poll
1. Flash the ESP32 sketch as in Mode A — it runs a mini web server that answers on your LAN.
2. Open `http://<ESP32_IP>/gas` in a browser (phone or PC). You should see JSON like
   `{"room_id":0,"value":512,"ratio":0.91,"pct":6.8,"status":"OK"}`. The Serial Monitor prints the IP at boot.
3. In the Gas Saver app:
   - Click **Rooms (📡)** on the sidebar -> **➕ Add Room**.
   - Choose **Connection: 📶 WiFi HTTP Poll**.
   - Enter your sensor's IP address (e.g. `192.168.1.120` — `/gas` is appended automatically).
   - Click **⚡ Ping WiFi Sensor** to test connection, then click **Save Room**!

> The app polls once per second and reads `pct` (or `ratio`) from the JSON, so the calibration done on
> the board at boot carries straight through. If the IP was assigned by DHCP, reserve it in your router —
> otherwise the room goes **OFFLINE** the next time the router numbers the devices differently.

---

## 🔌 Connecting via USB Cable (Standard Arduino)

1. Open [`arduino/gas_sensor/gas_sensor.ino`](file:///c:/Users/steam/Desktop/stem%20c/gas_sensor_app/arduino/gas_sensor/gas_sensor.ino) in Arduino IDE.
2. Wire it up: sensor **VCC → 5V**, **GND → GND**, **AO → A0**; buzzer → **D8**; LED → **D13** (onboard LED works, external one needs a 220–330 Ω resistor).
3. Upload to your board at **9600 baud**.
4. Open the Serial Monitor (9600) — you should see `GAS_MONITOR_READY`, then a raw ADC value 5×/second
   (`512`, `507`, …) and a `# raw=… min=… max=…` line every 10 s.
5. In Gas Saver, click **➕ Add Room** -> choose **🔌 USB Serial COM Port** -> select your COM port (e.g. `COM3`).
6. Once readings arrive, calibrate in **Settings → Raw Sensor Calibration**: note the ADC value in clean air
   (that's your *clean-air ADC*) and the value with gas applied (that's your *danger ADC*).

> Keep the Serial Monitor closed while the app is connected — Windows allows only one program per COM port.

### 🔵 Optional: cut the cable with HC-05 / HC-06 (Bluetooth)

The blue "ZS-040" Bluetooth module carries the exact same 9600-baud stream, and Windows turns it into a
normal COM port — so Gas Saver treats it like any USB Arduino.

| Module pin | Arduino UNO |
|---|---|
| VCC | 5V (the breakout has its own 3.3 V regulator) |
| GND | GND |
| TXD | **D10** (3.3 V output is fine for the Arduino) |
| RXD | **D11** — through a divider: 1 kΩ in series, 2 kΩ to GND (RX is 3.3 V logic!) |
| STATE / EN | leave unconnected |

1. Flash the USB sketch — it already mirrors every reading to Bluetooth (`BT_ENABLED = true`).
2. In Windows: **Settings → Bluetooth → Add device → HC-05**, PIN **1234**. Two "Standard Serial over
   Bluetooth link" ports appear; use the **outgoing** one in Gas Saver.
3. Add the room as **🔌 USB Serial COM Port**, pick the Bluetooth COM port, 9600 baud.

---

## 🏠 Key Application Features

| Feature | Description |
|---|---|
| 🏢 **Multi-Room System** | Monitor Kitchen, Living Room, Bedrooms, Garage, Boiler, Basement, etc. |
| 📶 **WiFi Hub** | Built-in local HTTP receiver on port 5000, plus a `/api/state` feed for the web dashboard. |
| 🎛 **Dashboard Switcher** | Quick-switch bar on top of Dashboard to focus any room. |
| 🛡 **Smart Auto-Shutoff** | On DANGER the room's valve closes and the fan turns on automatically; it stays closed until you re-open it, and the fan stops once all rooms are safe. |
| 📈 **Real-Time Graph** | 60-second scrolling graph with shaded safety zones (Safe/Warn/Danger). |
| 🚨 **Multi-Channel Alerts** | Windows Toast, Audio Sirens, Emergency Popup, Email (SMTP), and Telegram. |
| 🔌 **Offline Detection** | An unreachable sensor is shown as **OFFLINE** — the app never fakes hardware readings. |
| 📱 **Live Web Dashboard** | Phone-first UI that mirrors real data and can control valves/fan/auto-shutoff. |
| 💾 **Persistent Logger** | Every reading is streamed to `gas_log.csv`; rooms & settings persist in `config.json`. |

> **Valve & fan are software state.** The app tracks, logs and auto-toggles them, and the web dashboard
> can control them — but nothing is switched physically until you wire a relay/servo to your Arduino and
> handle the command in your sketch.

---

## 🛠 Troubleshooting

| Symptom | Fix |
|---|---|
| App won't start / `Address already in use` | An older Gas Saver instance is still running — close its window (check Task Manager for `python.exe`) and relaunch `run_app.bat`. |
| Dashboard stuck on **CONNECTING** | Hub unreachable. Start the desktop app first; the default hub is `<this PC>:5000`. Tap ⚙ to set another hub. |
| Phone can't open `http://<PC-IP>:8080` | Phone and PC must be on the same Wi-Fi, and Windows Firewall must allow Python on private networks. |
| A room shows **OFFLINE** | Serial: port unplugged/wrong COM or Serial Monitor holding the port. WiFi: wrong IP, or DHCP gave the sensor a new address. |
| Raw value sticks at `0` or `1023` | Sensor **AO** not connected to A0 (or DO was used instead), or the module lacks 5 V power. |
| Alarm beeps but app reads SAFE | Local LED/buzzer thresholds in the sketch differ from the app's calibration — adjust `WARN_RAW`/`DANGER_RAW` or the calibration values in Settings. |

---

## 📂 Project Structure
```
gas_sensor_app/
├── gas_monitor.py                       ← Main desktop app with WiFi Hub + state API
├── config.json                          ← Auto-created: rooms, thresholds, notifications
├── gas_log.csv                          ← Continuous reading log (auto-saved)
├── install.bat                          ← Dependency installer
├── run_app.bat                          ← 1-click desktop launcher
├── run_web_dashboard.bat                ← 1-click web dashboard launcher
├── README.md                            ← Documentation
├── web/
│   ├── index.html                       ← Phone-first dashboard (LIVE via hub, else DEMO)
│   ├── server.py                        ← Static server on port 8080
│   └── vercel.json                      ← Static deployment config
└── arduino/
    ├── gas_sensor/gas_sensor.ino        ← Standard Arduino USB firmware (non-blocking)
    └── wifi_gas_sensor_esp32.ino        ← ESP32 / ESP8266 WiFi firmware (Rs/R0 calibrated)
```
