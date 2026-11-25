# Gas Saver — Multi-Room Gas Leak Detection

A real gas-leak detection system built from an Arduino UNO and an MQ gas sensor, plus a Tkinter desktop app, a phone-first web dashboard, and a 3-minute English presentation video.

## Repository layout

| Path | Contents |
| --- | --- |
| `gas_sensor_app/` | Desktop app (`gas_monitor.py`), web dashboard (`web/`), Arduino sketches (`arduino/`), install/run scripts. See [its README](gas_sensor_app/README.md). |
| `gas_saver_video/` | 3-minute English presentation video (`Gas_Saver_3min_English.mp4`) and the Python script that builds it. |
| `vibe_images/` | AI-generated stills used in the video. |

## Quick start

```bash
cd gas_sensor_app
install.bat          # pip install pyserial plyer requests
run_app.bat          # python gas_monitor.py
run_web_dashboard.bat  # optional: http://localhost:8080
```

## Video

`gas_saver_video/Gas_Saver_3min_English.mp4` — 3:00, 1080p, English voiceover, burned-in captions.

Rebuild it with:

```bash
pip install imageio-ffmpeg pillow
python gas_saver_video/build_video.py
```

## Hardware notes

- The bench rig is an Arduino UNO clone + one MQ sensor module + piezo buzzer + green LED, wired AO to A0, buzzer to D8, LED to D13.
- No relay is installed: the "gas valve" and "exhaust fan" are software states shown in the app and dashboard, not physical actuators.
- `gas_sensor_app/config.json` is created on first close of the app and stores your email/Telegram credentials, so it is gitignored. The expected shape is documented in `gas_sensor_app/config.example.json`.
