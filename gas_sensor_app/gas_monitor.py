"""
Gas Saver Pro — Advanced Multi-Room WiFi & IoT Gas Monitor
============================================================
Features:
  • Multi-Room & Multi-Sensor System (Kitchen, Living Room, Bedrooms, Garage, Boiler, etc.)
  • WiFi Sensor Connectivity (ESP32, ESP8266, NodeMCU, Arduino WiFi)
    - Mode A (WiFi Poll): App connects directly to sensor's IP address (HTTP GET)
    - Mode B (WiFi Push): Built-in local HTTP Receiver Server (Port 5000)
    - Mode C (USB Serial): Direct Arduino COM port connection
    - Mode D (Demo): Realistic simulation
  • WiFi Hub & Setup panel with local IP display & scanner
  • Dynamic Room Management: Add rooms via WiFi, USB, or Demo
  • Real-time animated gauge & 60-second scrolling line graph
  • Room-specific auto-shutoff valves & exhaust fan triggers
  • Audible sirens, Windows notifications, Email (SMTP), and Telegram alerts
  • Data logging with CSV export
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading, time, random, queue, math, csv, os, smtplib, socket, json
from datetime import datetime
from email.mime.text import MIMEText
from collections import deque

# ── Optional Libraries ────────────────────────────────────────────────────────
try:
    import serial, serial.tools.list_ports
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False

try:
    from plyer import notification
    PLYER_OK = True
except ImportError:
    PLYER_OK = False

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    import winsound
    SOUND_OK = True
except ImportError:
    SOUND_OK = False

# ── Palette ───────────────────────────────────────────────────────────────────
BG1        = "#080C18"
BG2        = "#0D1526"
GLASS      = "#111D34"
GLASS2     = "#162240"
BORDER     = "#1E2D50"
SIDEBAR    = "#090E1C"
NEON_GREEN = "#00FFB2"
NEON_BLUE  = "#00C8FF"
NEON_YLW   = "#FFD600"
NEON_RED   = "#FF2D55"
PURPLE     = "#9B6DFF"
ORANGE     = "#FF8C00"
WHITE      = "#FFFFFF"
GREY1      = "#8898B0"
GREY2      = "#1E2D50"
GREY3      = "#2A3A5C"

LOG_FILE    = os.path.join(os.path.dirname(__file__), "gas_log.csv")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
WIFI_PORT   = 5000

OFFLINE_TIMEOUT = 12          # seconds without a reading before a hardware sensor is OFFLINE
CSV_HEADER      = ["timestamp", "sensor_id", "pct", "level", "room_name"]
DANGER_RATIO    = 0.35        # Rs/R0 at which severity reaches 100% (matches firmware)

# Live, mutable thresholds so every widget agrees with the Settings page
THRESHOLDS = {"warn": 40, "danger": 70}

# ── Detect Active Hardware Ports ──────────────────────────────────────────────
ACTIVE_COM_PORT = "COM3"
if SERIAL_OK:
    _found = [p.device for p in serial.tools.list_ports.comports()]
    # Prefer a real USB-connected board over built-in UARTs (/dev/ttyS*)
    _usb = [d for d in _found
            if any(k in d for k in ("ttyACM", "ttyUSB", "usbmodem", "usbserial"))]
    if _usb:
        ACTIVE_COM_PORT = _usb[0]
    elif _found:
        ACTIVE_COM_PORT = _found[0]

# ── Default Rooms ─────────────────────────────────────────────────────────────
# Only physically connected sensors belong here. Add more rooms from the app.
DEFAULT_ROOMS = [
    {"id": 0, "name": "Kitchen (Arduino)", "icon": "🍳", "sensor": "MQ Sensor", "gas": "LPG / Smoke / Gas", "conn_type": "SERIAL", "port": ACTIVE_COM_PORT, "valve": True, "auto_shut": True, "base": 18.0},
]


# ══════════════════════════════════════════════════════════════════════════════
#  NETWORKING & HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _maximize_window(root):
    """Maximize the window on Windows, X11 (Linux) and macOS."""
    try:
        root.state("zoomed")          # Windows / some X11 WMs
        return
    except tk.TclError:
        pass
    try:
        root.attributes("-zoomed", True)  # most X11 window managers
        return
    except tk.TclError:
        pass
    try:
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
    except tk.TclError:
        root.geometry("1280x800")

def rr(canvas, x1, y1, x2, y2, r=14, **kw):
    pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
           x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
           x1,y2, x1,y2-r, x1,y1+r, x1,y1]
    return canvas.create_polygon(pts, smooth=True, **kw)

def blend(c1, c2, t):
    r1,g1,b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1*(1-t)+r2*t), int(g1*(1-t)+g2*t), int(b1*(1-t)+b2*t))

def level_color(pct):
    if pct >= THRESHOLDS["danger"]: return NEON_RED
    if pct >= THRESHOLDS["warn"]:   return NEON_YLW
    return NEON_GREEN

def level_name(pct):
    if pct >= THRESHOLDS["danger"]: return "DANGER"
    if pct >= THRESHOLDS["warn"]:   return "WARNING"
    return "SAFE"

def ratio_to_pct(ratio):
    """Severity from Rs/R0 (1.0 = clean air, lower = more gas). Shared with the firmware."""
    if ratio >= 1.0: return 0.0
    if ratio <= DANGER_RATIO: return 100.0
    return (1.0 - ratio) / (1.0 - DANGER_RATIO) * 100.0


# ══════════════════════════════════════════════════════════════════════════════
#  BUILT-IN WIFI SENSOR RECEIVER SERVER (Port 5000)
# ══════════════════════════════════════════════════════════════════════════════
class WiFiSensorServer(threading.Thread):
    def __init__(self, data_queue, ctrl_queue, raw_to_pct, state_provider, port=WIFI_PORT):
        super().__init__(daemon=True)
        self.data_queue = data_queue
        self.ctrl_queue = ctrl_queue
        self.raw_to_pct = raw_to_pct
        self.state_provider = state_provider
        self.port = port
        self.server = None

    def run(self):
        data_q, ctrl_q = self.data_queue, self.ctrl_queue
        raw_to_pct, state_provider = self.raw_to_pct, self.state_provider

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress console log spam

            def _send_json(self, obj, code=200):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                # CORS preflight for the web dashboard's JSON POSTs
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/api/state":
                    try:
                        state = state_provider()
                    except Exception as e:
                        self._send_json({"status": "error", "message": str(e)}, 500)
                        return
                    self._send_json(state)
                    return
                self._send_json({"status": "Gas Saver WiFi Hub Online",
                                 "time": datetime.now().isoformat()})

            def do_POST(self):
                path = self.path.split("?")[0]
                try:
                    content_len = int(self.headers.get("Content-Length", 0) or 0)
                    raw = self.rfile.read(content_len) if content_len else b"{}"
                    data = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._send_json({"status": "error", "message": "invalid JSON body"}, 400)
                    return

                try:
                    if path == "/api/valve":
                        ctrl_q.put(("valve", int(data.get("room_id", 0)), bool(data.get("open", False))))
                        self._send_json({"status": "queued"})
                        return
                    if path == "/api/fan":
                        ctrl_q.put(("fan", -1, bool(data.get("on", False))))
                        self._send_json({"status": "queued"})
                        return
                    if path == "/api/auto":
                        ctrl_q.put(("auto", int(data.get("room_id", 0)), bool(data.get("on", True))))
                        self._send_json({"status": "queued"})
                        return

                    room_id = int(data.get("room_id", 0))
                    if "pct" in data:
                        pct = float(data["pct"])
                    elif "ratio" in data:
                        pct = ratio_to_pct(float(data["ratio"]))
                    elif "value" in data or "gas" in data:
                        pct = raw_to_pct(float(data.get("value", data.get("gas", 0))))
                    else:
                        pct = 0.0

                    data_q.put((room_id, max(0.0, min(100.0, pct)), time.time()))
                    self._send_json({"status": "success", "received": True})
                except Exception as e:
                    self._send_json({"status": "error", "message": str(e)}, 400)

        try:
            self.server = HTTPServer(("0.0.0.0", self.port), Handler)
            self.server.serve_forever()
        except Exception as e:
            print(f"[hub] Could not start WiFi hub on port {self.port}: {e}")

    def stop(self):
        if self.server:
            self.server.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
#  SENSOR READER THREAD (Multi-Mode: WiFi Poll, Push, Serial, Demo)
# ══════════════════════════════════════════════════════════════════════════════
class SensorReader(threading.Thread):
    def __init__(self, q, raw_to_pct, port="DEMO", conn_type="DEMO", baud=9600,
                 sensor_id=0, base=15.0):
        super().__init__(daemon=True)
        self.q = q
        self.raw_to_pct = raw_to_pct
        self.port = str(port)
        self.conn_type = conn_type
        self.baud = baud
        self.sensor_id = sensor_id
        self.base = base
        self.running = False
        self._offline_sent = False

    def _mark_offline(self):
        # Sentinel (-1) tells the UI this sensor is unreachable — never fake a reading
        if not self._offline_sent:
            self.q.put((self.sensor_id, -1.0, time.time()))
            self._offline_sent = True

    def run(self):
        self.running = True
        if self.conn_type == "SERIAL":
            self._serial()
        elif self.conn_type == "WIFI_POLL" or (self.port.startswith("http") or ("." in self.port and not self.port.upper().startswith("COM") and self.port != "DEMO")):
            self._wifi_poll()
        elif self.conn_type == "WIFI_PUSH":
            while self.running:
                time.sleep(1)
        else:
            self._demo()

    def _demo(self):
        base = self.base
        while self.running:
            spike = random.random() < 0.035
            val = random.uniform(72, 96) if spike else max(3, min(65, base + random.uniform(-2.2, 2.2)))
            if not spike: base = val
            self.q.put((self.sensor_id, round(val, 1), time.time()))
            time.sleep(1)

    def _wifi_poll(self):
        """Polls ESP32 / ESP8266 mini web server via WiFi HTTP GET"""
        url = self.port if self.port.startswith("http://") or self.port.startswith("https://") else f"http://{self.port}"
        if not any(url.endswith(s) for s in ("/gas", "/json", "/data")) and ":" not in url[7:]:
            url = f"{url}/gas"

        while self.running:
            if not REQUESTS_OK:
                self._mark_offline()
                time.sleep(2)
                continue
            try:
                resp = requests.get(url, timeout=1.8)
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                try:
                    d = resp.json()
                    if "pct" in d:
                        pct = float(d["pct"])
                    elif "ratio" in d:
                        pct = ratio_to_pct(float(d["ratio"]))
                    elif "value" in d or "gas" in d:
                        pct = self.raw_to_pct(d.get("value", d.get("gas", 0)))
                    else:
                        pct = float(list(d.values())[0])
                except Exception:
                    v = float(resp.text.strip().split(":")[-1].strip())
                    pct = self.raw_to_pct(v)

                self.q.put((self.sensor_id, max(0.0, min(100.0, pct)), time.time()))
                self._offline_sent = False
            except Exception:
                self._mark_offline()
            time.sleep(1)

    def _serial(self):
        while self.running:
            ser = None
            try:
                ser = serial.Serial(self.port, self.baud, timeout=2)
                time.sleep(1.5)
                while self.running:
                    try:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            raw = float(line.split(":")[-1].strip())
                            self.q.put((self.sensor_id, self.raw_to_pct(raw), time.time()))
                            self._offline_sent = False
                    except (ValueError, UnicodeDecodeError):
                        pass
            except Exception:
                self._mark_offline()
                time.sleep(2)
            finally:
                if ser and ser.is_open:
                    try: ser.close()
                    except Exception: pass
            time.sleep(1)

    def stop(self):
        self.running = False


# ══════════════════════════════════════════════════════════════════════════════
#  GAUGE WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class Gauge(tk.Canvas):
    def __init__(self, parent, size=360, **kw):
        self.SZ = size
        super().__init__(parent, width=size, height=size,
                         bg=BG1, highlightthickness=0, **kw)
        self._pct = 12.0
        self._anim = 12.0
        self._level = "SAFE"
        self._col_override = None
        self._draw()

    def set_value(self, pct, level, color=None):
        self._pct, self._level, self._col_override = pct, level, color
        self._tick()

    def _tick(self):
        diff = self._pct - self._anim
        if abs(diff) > 0.4:
            self._anim += diff * 0.22
            self._draw()
            self.after(16, self._tick)
        else:
            self._anim = self._pct
            self._draw()

    def _draw(self):
        self.delete("all")
        cx = cy = self.SZ // 2
        R = int(self.SZ * 0.42)
        m = cx - R
        col = self._col_override or level_color(self._pct)

        for rad, fc in [(R+22,"#0B1220"),(R+12,"#0E1830"),(R+4,"#111E38")]:
            self.create_oval(cx-rad,cy-rad,cx+rad,cy+rad,fill=fc,outline="")
        self.create_oval(cx-R,cy-R,cx+R,cy+R,fill="#09111F",outline=BORDER,width=2)

        self.create_arc(m,m,cx+R,cy+R,start=-135,extent=-270,
                        style="arc",outline=GREY2,width=16)

        sweep = max(0, self._anim/100*270)
        if sweep > 0:
            for w, t in [(28,0.12),(22,0.25),(16,0.5)]:
                self.create_arc(m,m,cx+R,cy+R,start=-135,extent=-sweep,
                                style="arc",outline=blend(col,BG1,1-t),width=w)
            self.create_arc(m,m,cx+R,cy+R,start=-135,extent=-sweep,
                            style="arc",outline=col,width=10)

        for i in range(11):
            ang = math.radians(135 + i*27)
            big = i%5==0
            r1,r2 = R-2, R-(12 if big else 6)
            self.create_line(cx+r1*math.cos(ang),cy+r1*math.sin(ang),
                             cx+r2*math.cos(ang),cy+r2*math.sin(ang),
                             fill=GREY1 if big else BORDER,width=2 if big else 1)
            if big:
                lr = r1-22
                self.create_text(cx+lr*math.cos(ang),cy+lr*math.sin(ang),
                                 text=str(i*10),fill=GREY1,font=("Helvetica",8))

        if sweep > 0:
            ea = math.radians(135+sweep)
            self.create_oval(cx+R*math.cos(ea)-8,cy+R*math.sin(ea)-8,
                             cx+R*math.cos(ea)+8,cy+R*math.sin(ea)+8,
                             fill=col,outline=WHITE,width=2)

        IR = int(self.SZ*0.26)
        for gi in range(5,0,-1):
            gc = blend(col,BG1,1-gi/8)
            self.create_oval(cx-gi*5,cy-gi*5,cx+gi*5,cy+gi*5,fill=gc,outline="")
        self.create_oval(cx-IR,cy-IR,cx+IR,cy+IR,fill="#07101E",outline=BORDER,width=1)

        self.create_text(cx, cy-32, text="GAS LEVEL",
                         fill=GREY1, font=("Helvetica",int(self.SZ*0.033),"bold"))
        self.create_text(cx, cy+6,  text=f"{self._anim:.0f}%",
                         fill=col,  font=("Helvetica",int(self.SZ*0.115),"bold"))
        self.create_text(cx, cy+40, text=self._level,
                         fill=col,  font=("Helvetica",int(self.SZ*0.04),"bold"))


# ══════════════════════════════════════════════════════════════════════════════
#  TOGGLE SWITCH
# ══════════════════════════════════════════════════════════════════════════════
class Toggle(tk.Canvas):
    def __init__(self, parent, on=False, on_color=NEON_GREEN,
                 W=60, H=30, command=None, **kw):
        self.TW, self.TH = W, H
        super().__init__(parent, width=W, height=H,
                         highlightthickness=0, **kw)
        self._on, self._col, self._cmd = on, on_color, command
        self.bind("<Button-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        track = self._col if self._on else GREY3
        r = self.TH//2
        for x1,x2 in [(0,self.TH),(self.TW-self.TH,self.TW)]:
            self.create_oval(x1,0,x2,self.TH,fill=track,outline="")
        self.create_rectangle(r,0,self.TW-r,self.TH,fill=track,outline="")
        p = 3
        kx = self.TW-self.TH+p if self._on else p
        self.create_oval(kx,p,kx+self.TH-2*p,self.TH-p,fill=WHITE,outline="")

    def _click(self,_=None):
        self._on = not self._on; self._draw()
        if self._cmd: self._cmd(self._on)

    def set(self,on): self._on=on; self._draw()

    @property
    def value(self): return self._on


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE GRAPH
# ══════════════════════════════════════════════════════════════════════════
class LiveGraph(tk.Canvas):
    POINTS = 60

    def __init__(self, parent, title="GAS LEVEL — LAST 60 SECONDS", **kw):
        super().__init__(parent, bg=GLASS, highlightthickness=0, **kw)
        self.data = deque([0.0]*self.POINTS, maxlen=self.POINTS)
        self.graph_title = title
        self.bind("<Configure>", lambda e: self.redraw())

    def push(self, val):
        self.data.append(val)
        self.redraw()

    def set_title(self, title):
        self.graph_title = title
        self.redraw()

    def redraw(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 10 or H < 10: return
        pad = 44

        for i in range(5):
            y = pad + (H-2*pad)*i//4
            self.create_line(pad,y,W-pad,y,fill=BORDER,dash=(4,4))
            self.create_text(pad-6,y,text=str(100-i*25),
                             fill=GREY1,font=("Helvetica",8),anchor="e")

        dy = pad + int((H-2*pad)*0.3)
        wy = pad + int((H-2*pad)*0.6)
        self.create_rectangle(pad,pad,W-pad,dy,fill=blend(NEON_RED,BG1,0.88),outline="")
        self.create_rectangle(pad,dy,W-pad,wy,fill=blend(NEON_YLW,BG1,0.9),outline="")
        self.create_rectangle(pad,wy,W-pad,H-pad,fill=blend(NEON_GREEN,BG1,0.92),outline="")

        self.create_text(W-pad+2, pad+8, text="DANGER", fill=NEON_RED, font=("Helvetica",7,"bold"), anchor="w")
        self.create_text(W-pad+2, dy+8, text="WARN", fill=NEON_YLW, font=("Helvetica",7,"bold"), anchor="w")
        self.create_text(W-pad+2, wy+8, text="SAFE", fill=NEON_GREEN, font=("Helvetica",7,"bold"), anchor="w")

        for i in range(0, self.POINTS+1, 10):
            x = pad + int(i/(self.POINTS)*(W-2*pad))
            self.create_text(x, H-pad+12, text=f"-{self.POINTS-i}s",
                             fill=GREY1, font=("Helvetica",7))
            self.create_line(x,H-pad,x,H-pad+4,fill=GREY1)

        self.create_line(pad,pad,pad,H-pad,fill=GREY1,width=1)
        self.create_line(pad,H-pad,W-pad,H-pad,fill=GREY1,width=1)

        pts = list(self.data)
        xs = [pad + int(i/(self.POINTS-1)*(W-2*pad)) for i in range(self.POINTS)]
        ys = [pad + int((1-v/100)*(H-2*pad)) for v in pts]

        poly = []
        for x,y in zip(xs,ys): poly += [x,y]
        poly += [xs[-1],H-pad, xs[0],H-pad]
        if len(poly) >= 6:
            self.create_polygon(poly, fill=blend(NEON_BLUE,BG1,0.75), outline="")

        line_pts = []
        for x,y in zip(xs,ys): line_pts += [x,y]
        if len(line_pts) >= 4:
            self.create_line(line_pts, fill=NEON_BLUE, width=2, smooth=True)

        if xs and ys:
            lx,ly = xs[-1],ys[-1]
            col = level_color(pts[-1])
            self.create_oval(lx-6,ly-6,lx+6,ly+6,fill=col,outline=WHITE,width=2)

        self.create_text(pad, 14, text=self.graph_title,
                         fill=GREY1, font=("Helvetica",9,"bold"), anchor="w")


# ══════════════════════════════════════════════════════════════════════════════
#  ROOM CARD (in Rooms Grid)
# ══════════════════════════════════════════════════════════════════════════════
class RoomCard(tk.Frame):
    def __init__(self, parent, room_info, on_select=None, on_toggle_valve=None, **kw):
        super().__init__(parent, bg=GLASS, padx=16, pady=14, **kw)
        self.config(highlightbackground=BORDER, highlightthickness=1)
        self.room_info = room_info
        self.on_select = on_select
        self.on_toggle_valve = on_toggle_valve

        # Top row: Icon + Name + Connection Badge
        top = tk.Frame(self, bg=GLASS)
        top.pack(fill="x")
        tk.Label(top, text=f"{room_info['icon']}  {room_info['name']}",
                 fg=WHITE, bg=GLASS, font=("Helvetica", 12, "bold")).pack(side="left")

        # Connection type tag
        conn_t = room_info.get("conn_type", "DEMO")
        badge_text, badge_col = "🟢 SIM", NEON_GREEN
        if conn_t == "WIFI_POLL":
            badge_text, badge_col = f"📶 WiFi ({room_info.get('port','IP')})", NEON_BLUE
        elif conn_t == "WIFI_PUSH":
            badge_text, badge_col = "📥 WiFi Push", PURPLE
        elif conn_t == "SERIAL":
            badge_text, badge_col = f"🔌 {room_info.get('port','COM')}", ORANGE

        sensor_tag = tk.Label(top, text=f" {badge_text} ",
                              fg=badge_col, bg=GLASS2, font=("Helvetica", 8, "bold"))
        sensor_tag.pack(side="right")

        # Subtitle: Sensor model + Target Gas
        tk.Label(self, text=f"{room_info['sensor']} · {room_info['gas']}",
                 fg=GREY1, bg=GLASS, font=("Helvetica", 8)).pack(anchor="w", pady=(2, 6))

        # Percentage + Level Status
        mid = tk.Frame(self, bg=GLASS)
        mid.pack(fill="x", pady=(2, 6))
        self._pct_lbl = tk.Label(mid, text="— %", fg=NEON_GREEN, bg=GLASS,
                                 font=("Helvetica", 24, "bold"))
        self._pct_lbl.pack(side="left")
        self._lvl_lbl = tk.Label(mid, text="SAFE", fg=NEON_GREEN, bg=GLASS2,
                                 font=("Helvetica", 9, "bold"), padx=8, pady=3)
        self._lvl_lbl.pack(side="right")

        # Mini progress bar
        self._bar = tk.Canvas(self, height=6, bg=GLASS, highlightthickness=0)
        self._bar.pack(fill="x", pady=(4, 10))

        # Footer row: Valve status + Focus action
        foot = tk.Frame(self, bg=GLASS)
        foot.pack(fill="x")
        self._valve_btn = tk.Button(foot, text="VALVE: OPEN",
                                    bg=blend(NEON_GREEN, BG1, 0.8), fg=NEON_GREEN,
                                    font=("Helvetica", 8, "bold"), relief="flat", padx=8, pady=3,
                                    command=self._toggle_valve_click)
        self._valve_btn.pack(side="left")

        select_btn = tk.Button(foot, text="🔍 Focus",
                               bg=GLASS2, fg=WHITE, font=("Helvetica", 8),
                               relief="flat", padx=10, pady=3,
                               command=lambda: self.on_select(self.room_info['id']) if self.on_select else None)
        select_btn.pack(side="right")

    def _toggle_valve_click(self):
        new_state = not self.room_info.get('valve', True)
        self.room_info['valve'] = new_state
        if self.on_toggle_valve:
            self.on_toggle_valve(self.room_info['id'], new_state)
        self.update_valve(new_state)

    def update_valve(self, is_open):
        if is_open:
            self._valve_btn.config(text="VALVE: OPEN", fg=NEON_GREEN,
                                   bg=blend(NEON_GREEN, BG1, 0.8))
        else:
            self._valve_btn.config(text="VALVE: CLOSED", fg=NEON_RED,
                                   bg=blend(NEON_RED, BG1, 0.8))

    def update_reading(self, pct, online=True):
        self._bar.delete("all")
        W = self._bar.winfo_width() or 180
        self._bar.create_rectangle(0, 0, W, 6, fill=GREY2, outline="")

        if not online:
            self._pct_lbl.config(text="—", fg=GREY1)
            self._lvl_lbl.config(text="OFFLINE", fg=GREY1)
            return

        col = level_color(pct)
        self._pct_lbl.config(text=f"{pct:.0f}%", fg=col)
        self._lvl_lbl.config(text=level_name(pct), fg=col)
        fw = max(4, int(pct / 100.0 * W))
        self._bar.create_rectangle(0, 0, fw, 6, fill=col, outline="")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════
class GasSaverApp:
    PAGES = ["Dashboard", "Rooms", "Graph", "Alerts", "Log", "Settings"]
    PAGE_ICONS = ["⬡", "📡", "📈", "🔔", "📋", "⚙"]

    def __init__(self, root):
        self.root = root
        root.title("Gas Saver Pro — Advanced Multi-Room WiFi Gas Monitor")
        root.configure(bg=BG1)
        _maximize_window(root)
        root.update_idletasks()

        # ── State ──
        self.q = queue.Queue()
        self.ctrl_q = queue.Queue()
        self.local_ip = get_local_ip()

        self.rooms = [dict(r) for r in DEFAULT_ROOMS]
        self.active_room_id = 0

        # ── Settings ──
        self.cfg = {
            "facility_name": "Smart Facility",
            "warn_thresh":   40,
            "danger_thresh": 70,
            "cooldown":      30,
            "baseline_raw":  250,   # clean-air ADC value (0–1023 scale)
            "danger_raw":    800,   # ADC value that counts as 100% severity
            "email_to":      "",
            "email_from":    "",
            "email_pass":    "",
            "smtp_host":     "smtp.gmail.com",
            "smtp_port":     "587",
            "tg_token":      "",
            "tg_chat_id":    "",
        }
        self._load_state()
        THRESHOLDS["warn"] = int(self.cfg["warn_thresh"])
        THRESHOLDS["danger"] = int(self.cfg["danger_thresh"])

        self.readers = []
        self.sensor_pcts = {r["id"]: 0.0 for r in self.rooms}
        self.history = {r["id"]: deque([0.0]*60, maxlen=60) for r in self.rooms}
        self.last_seen = {}
        self.offline = {r["id"]: r.get("conn_type", "DEMO") != "DEMO" for r in self.rooms}

        self.alert_log = []
        self.csv_rows = deque(maxlen=1000)
        self._csv_file = None
        self._csv_writer = None
        self.last_alert_time = 0
        self.alert_count = 0
        self.start_time = time.time()
        self._room_alert_ts = {}
        self._room_state = {}

        self.fan_on = False
        self._fan_auto = False
        self.sound_on = True
        self._flash_id = None
        self._active_page = tk.StringVar(value="Dashboard")

        self._open_log_file()
        self.wifi_server = WiFiSensorServer(self.q, self.ctrl_q, self.raw_to_pct,
                                            self._build_state, port=WIFI_PORT)
        self.wifi_server.start()

        self._build_shell()
        self._show_page("Dashboard")
        self._start_all_readers()
        self.root.after(300, self._poll)
        self.root.after(1000, self._tick_clock)

    # ══════════════════════════════════════════════════════════════════════════
    #  PERSISTENCE & LOGGING
    # ══════════════════════════════════════════════════════════════════════════
    def _load_state(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            cfg = data.get("cfg", {})
            if isinstance(cfg, dict):
                for k in self.cfg:
                    if k in cfg:
                        self.cfg[k] = cfg[k]
            for key in ("warn_thresh", "danger_thresh", "cooldown", "baseline_raw", "danger_raw"):
                try:
                    self.cfg[key] = int(self.cfg[key])
                except (TypeError, ValueError):
                    pass

            rooms = data.get("rooms")
            if isinstance(rooms, list) and rooms:
                clean = []
                for r in rooms:
                    if not isinstance(r, dict) or "name" not in r or "id" not in r:
                        continue
                    merged = {"icon": "📡", "sensor": "MQ Sensor", "gas": "General Gas",
                              "conn_type": "DEMO", "port": "DEMO", "valve": True,
                              "auto_shut": True, "base": 12.0}
                    merged.update(r)
                    clean.append(merged)
                if clean:
                    # This build shows real hardware rooms only.
                    clean = [r for r in clean if r.get("conn_type") != "DEMO"]
                    if SERIAL_OK:
                        available = {p.device for p in serial.tools.list_ports.comports()}
                        for r in clean:
                            if r.get("conn_type") == "SERIAL" and available \
                                    and r.get("port") not in available:
                                r["port"] = ACTIVE_COM_PORT
                    if clean:
                        self.rooms = clean

            try:
                self.active_room_id = int(data.get("active_room_id", 0))
            except (TypeError, ValueError):
                self.active_room_id = 0
            if self.active_room_id not in {r["id"] for r in self.rooms}:
                self.active_room_id = self.rooms[0]["id"]
        except Exception as e:
            print(f"[config] Could not load {CONFIG_FILE}: {e}")

    def _save_state(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"cfg": self.cfg, "rooms": self.rooms,
                           "active_room_id": self.active_room_id}, f, indent=2)
        except Exception as e:
            print(f"[config] Could not save {CONFIG_FILE}: {e}")

    def _open_log_file(self, truncate=False):
        try:
            if self._csv_file:
                self._csv_file.close()
        except Exception:
            pass
        try:
            if truncate:
                mode, needs_header = "w", True
            else:
                mode = "a"
                needs_header = not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0
                if not needs_header:
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        if f.readline().strip() != ",".join(CSV_HEADER):
                            # Old/incompatible format — keep the old data, start fresh
                            os.replace(LOG_FILE, LOG_FILE + ".old")
                            needs_header = True
            self._csv_file = open(LOG_FILE, mode, newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv_file)
            if needs_header:
                self._csv_writer.writerow(CSV_HEADER)
                self._csv_file.flush()
        except Exception as e:
            print(f"[log] Could not open {LOG_FILE}: {e}")
            self._csv_file = None
            self._csv_writer = None

    def _record_row(self, row):
        self.csv_rows.append(row)
        if self._csv_writer:
            try:
                self._csv_writer.writerow(row)
                self._csv_file.flush()
            except Exception:
                pass
        if hasattr(self, "_log_text"):
            self._append_log(row)

    def _clear_log(self):
        self.csv_rows.clear()
        self._open_log_file(truncate=True)
        if hasattr(self, "_log_text"):
            self._log_text.config(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.config(state="disabled")
        self._status("Log cleared", GREY1)

    def raw_to_pct(self, raw):
        """Map an ADC value (0–1023 scale) to 0–100% severity using the clean-air baseline."""
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            return 0.0
        base = float(self.cfg.get("baseline_raw", 250))
        danger = float(self.cfg.get("danger_raw", 800))
        if danger <= base:
            danger = base + 1.0
        return max(0.0, min(100.0, (raw - base) / (danger - base) * 100.0))

    def _build_state(self):
        """Snapshot served to the web dashboard over GET /api/state."""
        rooms = []
        for r in list(self.rooms):
            rid = r["id"]
            pct = self.sensor_pcts.get(rid, 0.0)
            online = not self.offline.get(rid, True)
            rooms.append({
                "id": rid,
                "name": r.get("name", f"Room {rid}"),
                "icon": r.get("icon", "📡"),
                "sensor": r.get("sensor", "MQ Sensor"),
                "gas": r.get("gas", "General Gas"),
                "conn_type": r.get("conn_type", "DEMO"),
                "pct": round(pct, 1),
                "level": level_name(pct) if online else "OFFLINE",
                "online": online,
                "valve": bool(r.get("valve", True)),
                "auto_shut": bool(r.get("auto_shut", True)),
            })
        return {
            "rooms": rooms,
            "fan": bool(self.fan_on),
            "warn": THRESHOLDS["warn"],
            "danger": THRESHOLDS["danger"],
            "facility": self.cfg.get("facility_name", ""),
            "hub": f"{self.local_ip}:{WIFI_PORT}",
            "time": datetime.now().isoformat(timespec="seconds"),
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  SHELL & NAVIGATION
    # ══════════════════════════════════════════════════════════════════════════
    def _build_shell(self):
        self._hdr = tk.Canvas(self.root, height=66, bg=GLASS, highlightthickness=0)
        self._hdr.pack(fill="x", side="top")
        self._hdr.bind("<Configure>", self._draw_header)

        main = tk.Frame(self.root, bg=BG1)
        main.pack(fill="both", expand=True)

        self._sb = tk.Frame(main, bg=SIDEBAR, width=110)
        self._sb.pack(side="left", fill="y")
        self._sb.pack_propagate(False)
        self._build_sidebar()

        self._pages_frame = tk.Frame(main, bg=BG1)
        self._pages_frame.pack(side="left", fill="both", expand=True)

        self._status_bar = tk.Frame(self.root, bg=BG2, height=30)
        self._status_bar.pack(fill="x", side="bottom")
        self._status_bar.pack_propagate(False)
        self._build_statusbar()

    def _draw_header(self, event=None):
        c = self._hdr
        c.delete("all")
        W = c.winfo_width() or 1280
        c.create_rectangle(0, 0, W, 4, fill=NEON_BLUE, outline="")
        c.create_text(50, 34, text="⬡", fill=NEON_BLUE, font=("Helvetica", 28))
        c.create_text(50, 34, text="✦", fill=NEON_GREEN, font=("Helvetica", 13, "bold"))
        c.create_text(118, 24, text="Gas Saver Pro", fill=WHITE,
                      font=("Helvetica", 22, "bold"), anchor="w")

        total_rooms = len(self.rooms)
        online_ids = [rid for rid in self.sensor_pcts if not self.offline.get(rid, False)]
        danger_count = sum(1 for rid in online_ids if self.sensor_pcts[rid] >= THRESHOLDS["danger"])
        warn_count = sum(1 for rid in online_ids if THRESHOLDS["warn"] <= self.sensor_pcts[rid] < THRESHOLDS["danger"])
        offline_count = sum(1 for v in self.offline.values() if v)

        status_text = f"{total_rooms} Rooms Monitored  ·  📶 WiFi Hub: {self.local_ip}:{WIFI_PORT}"
        if offline_count:
            status_text += f"  ·  🔌 {offline_count} Offline"
        if danger_count > 0:
            status_text += f"  ·  🚨 {danger_count} ROOM IN DANGER!"
        elif warn_count > 0:
            status_text += f"  ·  ⚠️ {warn_count} Room Elevated"

        c.create_text(118, 48, text=status_text,
                      fill=NEON_RED if danger_count else (NEON_YLW if warn_count else GREY1),
                      font=("Helvetica", 10), anchor="w")

        rr(c, W-160, 16, W-14, 48, r=14, fill=blend(NEON_GREEN, BG1, 0.88),
           outline=NEON_GREEN, width=1)
        c.create_text(W-20, 32, text="⬤  LIVE", fill=NEON_GREEN,
                      font=("Helvetica", 11, "bold"), anchor="e")

        up = int(time.time() - self.start_time)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        c.create_text(W-180, 32, text=f"⏱ {h:02d}:{m:02d}:{s:02d}",
                      fill=GREY1, font=("Helvetica", 9), anchor="e")

    def _build_sidebar(self):
        tk.Frame(self._sb, bg=SIDEBAR, height=12).pack()
        self._sb_btns = {}
        for icon, name in zip(self.PAGE_ICONS, self.PAGES):
            f = tk.Frame(self._sb, bg=SIDEBAR, cursor="hand2")
            f.pack(fill="x", pady=2)
            ic = tk.Label(f, text=icon, bg=SIDEBAR, fg=GREY1,
                          font=("Helvetica", 18), pady=4)
            ic.pack()
            lbl = tk.Label(f, text=name, bg=SIDEBAR, fg=GREY1,
                           font=("Helvetica", 8, "bold"), pady=0)
            lbl.pack()
            for w in (f, ic, lbl):
                w.bind("<Button-1>", lambda e, n=name: self._show_page(n))
                w.bind("<Enter>", lambda e, ww=f: ww.config(bg=GLASS))
                w.bind("<Leave>", lambda e, ww=f, n=name:
                       ww.config(bg=GLASS if self._active_page.get() == n else SIDEBAR))
            self._sb_btns[name] = (f, ic, lbl)

    def _build_statusbar(self):
        self._status_lbl = tk.Label(self._status_bar, text=f"● WiFi Hub Listening on {self.local_ip}:{WIFI_PORT}",
                                    fg=NEON_GREEN, bg=BG2, font=("Helvetica", 8, "bold"))
        self._status_lbl.pack(side="left", padx=12)
        self._clock_lbl = tk.Label(self._status_bar, text="",
                                   fg=GREY1, bg=BG2, font=("Helvetica", 8))
        self._clock_lbl.pack(side="right", padx=12)
        self._last_alert_lbl = tk.Label(self._status_bar, text="No alerts recorded",
                                        fg=GREY1, bg=BG2, font=("Helvetica", 8))
        self._last_alert_lbl.pack(side="right", padx=20)

    def _show_page(self, name):
        self._active_page.set(name)
        for w in self._pages_frame.winfo_children():
            w.destroy()
        # Drop references to widgets belonging to the destroyed page, otherwise the
        # background poll loop keeps configuring dead widgets and stops rescheduling.
        for attr in ("_room_chips", "_room_cards", "_gauge", "_bar_cv", "_stat_widgets",
                     "_dash_graph", "_full_graph", "_graph_stat_labels", "_log_text",
                     "_alert_listbox", "_valve_lbl", "_valve_tog", "_close_cv",
                     "_fan_tog", "_auto_tog", "_snd_tog", "_active_room_title",
                     "_badge_total", "_badge_danger", "_badge_warn", "_badge_safe",
                     "_graph_sel_var", "_cfg_vars"):
            if hasattr(self, attr):
                delattr(self, attr)
        for n, (f, ic, lbl) in self._sb_btns.items():
            active = (n == name)
            col = GLASS if active else SIDEBAR
            tc = WHITE if active else GREY1
            f.config(bg=col)
            ic.config(bg=col, fg=tc)
            lbl.config(bg=col, fg=tc)

        builder = getattr(self, f"_page_{name.lower()}", None)
        if builder: builder(self._pages_frame)

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: DASHBOARD (Active Room Focus)
    # ══════════════════════════════════════════════════════════════════════════
    def _page_dashboard(self, parent):
        strip_frame = tk.Frame(parent, bg=GLASS, highlightbackground=BORDER, highlightthickness=1)
        strip_frame.pack(fill="x", padx=20, pady=(12, 6))

        tk.Label(strip_frame, text="ROOMS:", fg=GREY1, bg=GLASS,
                 font=("Helvetica", 9, "bold")).pack(side="left", padx=(14, 8), pady=8)

        chip_canvas = tk.Canvas(strip_frame, height=36, bg=GLASS, highlightthickness=0)
        chip_canvas.pack(side="left", fill="x", expand=True)

        chip_inner = tk.Frame(chip_canvas, bg=GLASS)
        chip_win = chip_canvas.create_window((0, 0), window=chip_inner, anchor="nw")
        chip_inner.bind("<Configure>", lambda e: chip_canvas.configure(scrollregion=chip_canvas.bbox("all")))

        self._room_chips = {}
        for r in self.rooms:
            rid = r["id"]
            is_active = (rid == self.active_room_id)
            cf = tk.Frame(chip_inner, bg=GLASS2 if is_active else BG2,
                          highlightbackground=NEON_BLUE if is_active else BORDER,
                          highlightthickness=1, padx=10, pady=4, cursor="hand2")
            cf.pack(side="left", padx=4)

            pct_val = self.sensor_pcts.get(rid, 0.0)
            is_off = self.offline.get(rid, False)
            col = GREY1 if is_off else level_color(pct_val)

            icon_lbl = tk.Label(cf, text=f"{r['icon']} {r['name']}",
                                fg=WHITE if is_active else GREY1, bg=GLASS2 if is_active else BG2,
                                font=("Helvetica", 8, "bold"))
            icon_lbl.pack(side="left", padx=(0, 6))

            val_lbl = tk.Label(cf, text="OFFLINE" if is_off else f"{pct_val:.0f}%", fg=col,
                               bg=GLASS2 if is_active else BG2, font=("Helvetica", 8, "bold"))
            val_lbl.pack(side="left")

            for w in (cf, icon_lbl, val_lbl):
                w.bind("<Button-1>", lambda e, target_id=rid: self._select_room(target_id))

            self._room_chips[rid] = (cf, icon_lbl, val_lbl)

        body = tk.Frame(parent, bg=BG1)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        cur_room = self._get_active_room()
        rh = tk.Frame(left, bg=BG1)
        rh.pack(fill="x", pady=(0, 4))

        conn_str = cur_room.get("conn_type", "DEMO")
        conn_tag = "📶 WiFi" if "WIFI" in conn_str else ("🔌 USB" if "SERIAL" in conn_str else "🟢 SIM")
        self._active_room_title = tk.Label(
            rh, text=f"{cur_room['icon']} {cur_room['name']} — {cur_room['sensor']} [{conn_tag}]",
            fg=WHITE, bg=BG1, font=("Helvetica", 14, "bold"))
        self._active_room_title.pack(side="left")

        gf = tk.Frame(left, bg=BG1)
        gf.pack(expand=True)
        self._gauge = Gauge(gf, size=380)
        self._gauge.pack()
        act_pct = self.sensor_pcts.get(self.active_room_id, 0.0)
        if self.offline.get(self.active_room_id, False):
            self._gauge.set_value(act_pct, "OFFLINE", GREY1)
        else:
            self._gauge.set_value(act_pct, level_name(act_pct))

        self._bar_cv = tk.Canvas(left, height=12, bg=BG1, highlightthickness=0)
        self._bar_cv.pack(fill="x", padx=20, pady=(6, 12))
        self._bar_cv.bind("<Configure>", lambda e: self._draw_bar(
            self.sensor_pcts.get(self.active_room_id, 0.0), e.width))

        sf = tk.Frame(left, bg=BG1)
        sf.pack(fill="x", pady=(0, 6))
        self._stat_widgets = {}
        for label, key, col in [("ROOM MAX", "max", NEON_RED),
                                ("ROOM AVG", "avg", NEON_BLUE),
                                ("ROOM MIN", "min", NEON_GREEN),
                                ("SYSTEM ALERTS", "alerts", NEON_YLW)]:
            card = tk.Frame(sf, bg=GLASS, padx=12, pady=10,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", expand=True, fill="x", padx=4)
            tk.Label(card, text=label, fg=GREY1, bg=GLASS, font=("Helvetica", 8)).pack(anchor="w")
            v = tk.Label(card, text="—", fg=col, bg=GLASS, font=("Helvetica", 16, "bold"))
            v.pack(anchor="w")
            self._stat_widgets[key] = v

        right = tk.Frame(body, bg=BG1)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self._build_valve_card(right)

        ctrl = tk.Frame(right, bg=GLASS, highlightbackground=BORDER, highlightthickness=1)
        ctrl.pack(fill="x", pady=(10, 0))
        ci = tk.Frame(ctrl, bg=GLASS, padx=18, pady=14)
        ci.pack(fill="x")
        tk.Label(ci, text="ROOM AUTOMATION", fg=GREY1, bg=GLASS,
                 font=("Helvetica", 9, "bold")).pack(anchor="w", pady=(0, 8))
        self._build_toggle_row(ci, "✦  Exhaust Fan", self.fan_on,
                               NEON_BLUE, self._on_fan, "_fan_tog")
        self._build_toggle_row(ci, "⬡  Room Auto-Shutoff", cur_room.get("auto_shut", True),
                               NEON_GREEN, self._on_room_auto, "_auto_tog")
        self._build_toggle_row(ci, "🔊  Audio Sirens", self.sound_on,
                               PURPLE, self._on_sound, "_snd_tog")

        tk.Label(right, text=f"LAST 60s — {cur_room['name'].upper()}",
                 fg=GREY1, bg=BG1, font=("Helvetica", 8, "bold")).pack(anchor="w", pady=(10, 2))
        self._dash_graph = LiveGraph(right, height=130, title=f"{cur_room['name']} Readings")
        self._dash_graph.pack(fill="x")
        for v in list(self.history.get(self.active_room_id, [])):
            self._dash_graph.push(v)

    def _select_room(self, room_id):
        self.active_room_id = room_id
        if self._active_page.get() == "Dashboard":
            self._show_page("Dashboard")

    def _get_active_room(self):
        for r in self.rooms:
            if r["id"] == self.active_room_id:
                return r
        return self.rooms[0]

    def _build_valve_card(self, parent):
        vc = tk.Frame(parent, bg=GLASS, highlightbackground=BORDER, highlightthickness=1)
        vc.pack(fill="x")
        vi = tk.Frame(vc, bg=GLASS, padx=18, pady=16)
        vi.pack(fill="x")

        cur_room = self._get_active_room()
        lv = tk.Frame(vi, bg=GLASS)
        lv.pack(side="left")
        tk.Label(lv, text=f"{cur_room['name'].upper()} GAS VALVE",
                 fg=GREY1, bg=GLASS, font=("Helvetica", 9, "bold")).pack(anchor="w")

        v_state = cur_room.get("valve", True)
        self._valve_lbl = tk.Label(lv, text="OPEN" if v_state else "CLOSED",
                                   fg=NEON_GREEN if v_state else NEON_RED,
                                   bg=GLASS, font=("Helvetica", 24, "bold"))
        self._valve_lbl.pack(anchor="w")

        self._valve_tog = Toggle(lv, on=v_state, on_color=NEON_GREEN,
                                 W=68, H=32, bg=GLASS, command=self._on_room_valve)
        self._valve_tog.pack(anchor="w", pady=(6, 0))

        cb = tk.Canvas(vi, width=150, height=62, bg=GLASS,
                       highlightthickness=0, cursor="hand2")
        cb.pack(side="right")
        self._close_cv = cb
        self._draw_close_btn()
        cb.bind("<Button-1>", lambda _: self._close_current_valve())
        cb.bind("<Enter>",    lambda _: self._draw_close_btn(hover=True))
        cb.bind("<Leave>",    lambda _: self._draw_close_btn(hover=False))

    def _build_toggle_row(self, parent, label, default, color, command, tog_attr):
        row = tk.Frame(parent, bg=GLASS)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, fg=GREY1, bg=GLASS, font=("Helvetica", 9)).pack(side="left")
        tog = Toggle(row, on=default, on_color=color, W=54, H=26, bg=GLASS, command=command)
        tog.pack(side="right")
        setattr(self, tog_attr, tog)

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: ROOMS & SENSORS (WiFi Hub + Grid)
    # ══════════════════════════════════════════════════════════════════════════
    def _page_rooms(self, parent):
        top_bar = tk.Frame(parent, bg=BG1)
        top_bar.pack(fill="x", padx=24, pady=(16, 8))

        tk.Label(top_bar, text=f"ALL ROOMS & SENSORS ({len(self.rooms)} Active)",
                 fg=WHITE, bg=BG1, font=("Helvetica", 14, "bold")).pack(side="left")

        # Top action buttons
        tk.Button(top_bar, text="➕  Add Room", command=self._dialog_add_room,
                  bg=NEON_BLUE, fg=BG1, font=("Helvetica", 9, "bold"),
                  relief="flat", padx=14, pady=6, cursor="hand2").pack(side="right")

        tk.Button(top_bar, text="📶  WiFi Hub & Setup", command=self._dialog_wifi_hub,
                  bg=PURPLE, fg=WHITE, font=("Helvetica", 9, "bold"),
                  relief="flat", padx=12, pady=6, cursor="hand2").pack(side="right", padx=8)

        tk.Button(top_bar, text="🚨  Emergency Shut All", command=self._shut_all_valves,
                  bg=NEON_RED, fg=WHITE, font=("Helvetica", 9, "bold"),
                  relief="flat", padx=12, pady=6, cursor="hand2").pack(side="right", padx=8)

        # Scrollable room card grid
        cv = tk.Canvas(parent, bg=BG1, highlightthickness=0)
        sb = tk.Scrollbar(parent, command=cv.yview)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        cv.configure(yscrollcommand=sb.set)

        grid_frame = tk.Frame(cv, bg=BG1)
        grid_win = cv.create_window((0, 0), window=grid_frame, anchor="nw")
        grid_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(grid_win, width=e.width))

        grid_frame.columnconfigure((0, 1, 2), weight=1)

        self._room_cards = {}
        for idx, r in enumerate(self.rooms):
            row_idx, col_idx = divmod(idx, 3)
            card = RoomCard(grid_frame, r,
                            on_select=self._on_card_focus,
                            on_toggle_valve=self._on_card_valve_toggle)
            card.grid(row=row_idx, column=col_idx, sticky="nsew", padx=10, pady=10)
            self._room_cards[r["id"]] = card
            card.update_reading(self.sensor_pcts.get(r["id"], 0.0),
                                online=not self.offline.get(r["id"], False))

    def _on_card_focus(self, room_id):
        self.active_room_id = room_id
        self._show_page("Dashboard")

    def _on_card_valve_toggle(self, room_id, is_open):
        self._set_room_valve(room_id, is_open)

    def _shut_all_valves(self):
        for r in self.rooms:
            self._set_room_valve(r["id"], False, silent=True)
        self._status("🚨 ALL GAS VALVES CLOSED EMERGENCY!", NEON_RED)
        messagebox.showwarning("Emergency", "All room gas valves have been CLOSED!")

    # ── WiFi Hub & Setup Dialog ──
    def _dialog_wifi_hub(self):
        d = tk.Toplevel(self.root)
        d.title("WiFi Sensor Hub & Setup")
        d.geometry("520x500")
        d.configure(bg=GLASS)
        d.attributes("-topmost", True)
        d.resizable(False, False)

        tk.Label(d, text="📶  WiFi Sensor Hub & Network Setup", fg=WHITE, bg=GLASS,
                 font=("Helvetica", 13, "bold")).pack(pady=(16, 8))

        f = tk.Frame(d, bg=GLASS, padx=24)
        f.pack(fill="both", expand=True)

        # Server Info Box
        info_box = tk.Frame(f, bg=GLASS2, padx=16, pady=14,
                            highlightbackground=BORDER, highlightthickness=1)
        info_box.pack(fill="x", pady=(0, 12))

        tk.Label(info_box, text=f"Your PC Local WiFi IP:  {self.local_ip}",
                 fg=NEON_BLUE, bg=GLASS2, font=("Helvetica", 11, "bold")).pack(anchor="w")
        tk.Label(info_box, text=f"HTTP Webhook Receiver:  http://{self.local_ip}:{WIFI_PORT}/api/sensor",
                 fg=WHITE, bg=GLASS2, font=("Courier", 9)).pack(anchor="w", pady=(4, 2))
        tk.Label(info_box, text=f"Web Dashboard API:  http://{self.local_ip}:{WIFI_PORT}/api/state",
                 fg=WHITE, bg=GLASS2, font=("Courier", 9)).pack(anchor="w", pady=(0, 2))
        tk.Label(info_box, text=f"Receiver Status:  🟢 Active & Listening on Port {WIFI_PORT}",
                 fg=NEON_GREEN, bg=GLASS2, font=("Helvetica", 9, "bold")).pack(anchor="w")

        # Instruction Guide
        guide = tk.Label(f, text=(
            "How to connect an ESP32 / ESP8266 WiFi Sensor:\n\n"
            "• Option 1 (WiFi Push): Flash the provided sketch onto your ESP32.\n"
            "  The sensor will automatically POST live gas values to this PC!\n\n"
            "• Option 2 (WiFi Poll): Put your ESP32's IP address into Gas Saver.\n"
            "  Gas Saver will poll http://<sensor-ip>/gas every second!\n\n"
            "• The web dashboard (run_web_dashboard.bat) connects to this hub\n"
            "  automatically and shows LIVE data; without it, it runs DEMO data."
        ), fg=GREY1, bg=GLASS, justify="left", font=("Helvetica", 9))
        guide.pack(anchor="w", pady=(0, 14))

        # Action Buttons
        btn_row = tk.Frame(f, bg=GLASS)
        btn_row.pack(fill="x", pady=6)

        def open_arduino_code():
            sketch_path = os.path.join(os.path.dirname(__file__), "arduino", "wifi_gas_sensor_esp32.ino")
            if not os.path.exists(sketch_path):
                messagebox.showinfo("Arduino Code", f"Sketch is located at:\n{sketch_path}")
                return
            try:
                if hasattr(os, "startfile"):
                    os.startfile(sketch_path)          # Windows
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", sketch_path])  # Linux
            except Exception:
                messagebox.showinfo("Arduino Code", f"Sketch is located at:\n{sketch_path}")

        tk.Button(btn_row, text="📝 Open ESP32/ESP8266 Arduino Sketch",
                  command=open_arduino_code,
                  bg=NEON_BLUE, fg=BG1, font=("Helvetica", 9, "bold"),
                  relief="flat", padx=12, pady=6).pack(side="left")

        def test_hub_ping():
            if not REQUESTS_OK:
                messagebox.showwarning("Hub Status", "Install the 'requests' package to run this test.")
                return
            try:
                r = requests.get(f"http://127.0.0.1:{WIFI_PORT}/", timeout=2)
                if r.status_code == 200:
                    messagebox.showinfo("Hub Status", f"✔ WiFi Receiver is working perfectly on port {WIFI_PORT}!")
                else:
                    messagebox.showwarning("Hub Status", f"Hub replied with HTTP {r.status_code}.")
            except Exception as e:
                messagebox.showerror("Hub Status", f"Error connecting to local hub: {e}")

        tk.Button(btn_row, text="⚡ Test Local Hub",
                  command=test_hub_ping,
                  bg=GLASS2, fg=WHITE, font=("Helvetica", 9),
                  relief="flat", padx=12, pady=6).pack(side="left", padx=8)

        tk.Button(d, text="Close", command=d.destroy,
                  bg=GLASS2, fg=GREY1, font=("Helvetica", 9),
                  relief="flat", padx=16, pady=4).pack(pady=(6, 16))

    # ── Add New Room Dialog (WiFi, Serial, or Demo) ──
    def _dialog_add_room(self):
        d = tk.Toplevel(self.root)
        d.title("Add New Room & Gas Sensor")
        d.geometry("460x440")
        d.configure(bg=GLASS)
        d.attributes("-topmost", True)
        d.resizable(False, False)

        tk.Label(d, text="➕  Add Monitored Room & Sensor", fg=WHITE, bg=GLASS,
                 font=("Helvetica", 13, "bold")).pack(pady=(16, 12))

        f = tk.Frame(d, bg=GLASS, padx=24)
        f.pack(fill="both", expand=True)

        def add_field(label, default=""):
            row = tk.Frame(f, bg=GLASS)
            row.pack(fill="x", pady=5)
            tk.Label(row, text=label, fg=GREY1, bg=GLASS, width=15, anchor="w",
                     font=("Helvetica", 9)).pack(side="left")
            entry = tk.Entry(row, bg=GLASS2, fg=WHITE, relief="flat", font=("Helvetica", 9),
                             insertbackground=WHITE)
            entry.insert(0, default)
            entry.pack(side="left", fill="x", expand=True)
            return entry

        e_name = add_field("Room Name:", "Attic / Storage")
        e_icon = add_field("Icon Emoji:", "🏚️")

        # Sensor Model
        r_model = tk.Frame(f, bg=GLASS)
        r_model.pack(fill="x", pady=5)
        tk.Label(r_model, text="Sensor Model:", fg=GREY1, bg=GLASS, width=15,
                 anchor="w", font=("Helvetica", 9)).pack(side="left")
        v_model = tk.StringVar(value="MQ-2")
        cb_model = ttk.Combobox(r_model, textvariable=v_model,
                                values=["MQ-2 (LPG/Smoke)", "MQ-4 (Natural Gas)",
                                        "MQ-7 (Carbon Monoxide)", "MQ-9 (CO/Flammable)",
                                        "MQ-135 (Air Quality)", "MQ-3 (Alcohol/Vapor)"],
                                font=("Helvetica", 9))
        cb_model.pack(side="left", fill="x", expand=True)

        e_gas = add_field("Target Gas:", "Methane / Smoke")

        # Connection Type (WiFi Poll, WiFi Push, Serial COM, Demo)
        r_type = tk.Frame(f, bg=GLASS)
        r_type.pack(fill="x", pady=5)
        tk.Label(r_type, text="Connection:", fg=GREY1, bg=GLASS, width=15,
                 anchor="w", font=("Helvetica", 9)).pack(side="left")
        v_type = tk.StringVar(value="🔌 USB Serial COM Port (Arduino)")
        cb_type = ttk.Combobox(r_type, textvariable=v_type,
                               values=["🔌 USB Serial COM Port (Arduino)",
                                       "📶 WiFi HTTP Poll (ESP32 / ESP8266)",
                                       "📥 WiFi Push (Sensor posts to PC)"],
                               font=("Helvetica", 9))
        cb_type.pack(side="left", fill="x", expand=True)

        # Port / IP Address field
        r_port = tk.Frame(f, bg=GLASS)
        r_port.pack(fill="x", pady=5)
        lbl_port = tk.Label(r_port, text="Serial Port:", fg=GREY1, bg=GLASS, width=15,
                            anchor="w", font=("Helvetica", 9))
        lbl_port.pack(side="left")
        e_port = tk.Entry(r_port, bg=GLASS2, fg=WHITE, relief="flat", font=("Helvetica", 9),
                          insertbackground=WHITE)
        e_port.insert(0, ACTIVE_COM_PORT)
        e_port.pack(side="left", fill="x", expand=True)

        # Ping Button
        btn_ping = tk.Button(f, text="⚡ Ping WiFi Sensor", bg=GLASS2, fg=NEON_BLUE,
                             font=("Helvetica", 8), relief="flat", padx=8, pady=3)

        def on_type_change(event=None):
            sel = v_type.get()
            if "WiFi HTTP Poll" in sel:
                lbl_port.config(text="Sensor IP / URL:")
                e_port.delete(0, "end")
                e_port.insert(0, "192.168.1.120")
                btn_ping.pack(anchor="w", pady=(2, 6))
            elif "WiFi Push" in sel:
                lbl_port.config(text="Assigned Port:")
                e_port.delete(0, "end")
                e_port.insert(0, f"Push (Port {WIFI_PORT})")
                btn_ping.pack_forget()
            elif "USB" in sel:
                lbl_port.config(text="Serial Port:")
                e_port.delete(0, "end")
                ports = [p.device for p in serial.tools.list_ports.comports()] if SERIAL_OK else []
                e_port.insert(0, ports[0] if ports else "COM3")
                btn_ping.pack_forget()
            else:
                lbl_port.config(text="Mode:")
                e_port.delete(0, "end")
                e_port.insert(0, "DEMO")
                btn_ping.pack_forget()

        cb_type.bind("<<ComboboxSelected>>", on_type_change)

        def test_sensor_ping():
            if not REQUESTS_OK:
                messagebox.showwarning("WiFi Ping", "Install the 'requests' package to use sensor pings.")
                return
            ip_val = e_port.get().strip()
            url = ip_val if ip_val.startswith("http") else f"http://{ip_val}"
            try:
                r = requests.get(url, timeout=2.0)
                if r.status_code == 200:
                    messagebox.showinfo("WiFi Ping Result", f"✔ Connection Successful!\nSensor responded from {ip_val}")
                else:
                    messagebox.showwarning("WiFi Ping Result", f"Sensor replied with HTTP Code {r.status_code}")
            except Exception as ex:
                messagebox.showerror("WiFi Ping Failed", f"Could not reach {url}:\n{ex}\n\nTip: You can still save this room. Readings will start once the sensor powers on!")

        btn_ping.config(command=test_sensor_ping)

        def save():
            name = e_name.get().strip() or "New Room"
            icon = e_icon.get().strip() or "📡"
            model = v_model.get().split()[0]
            gas = e_gas.get().strip() or "General Gas"
            conn_sel = v_type.get()
            port = e_port.get().strip() or "DEMO"

            conn_code = "DEMO"
            if "WiFi HTTP Poll" in conn_sel:
                conn_code = "WIFI_POLL"
            elif "WiFi Push" in conn_sel:
                conn_code = "WIFI_PUSH"
            elif "USB" in conn_sel:
                conn_code = "SERIAL"

            new_id = max([r["id"] for r in self.rooms], default=0) + 1
            new_room = {
                "id": new_id, "name": name, "icon": icon,
                "sensor": model, "gas": gas, "conn_type": conn_code,
                "port": port, "valve": True, "auto_shut": True, "base": 12.0
            }
            self.rooms.append(new_room)
            self.sensor_pcts[new_id] = 0.0
            self.history[new_id] = deque([0.0]*60, maxlen=60)
            self.offline[new_id] = conn_code != "DEMO"

            reader = SensorReader(self.q, self.raw_to_pct, port=port, conn_type=conn_code,
                                  sensor_id=new_id, base=12.0)
            reader.start()
            self.readers.append(reader)
            self._save_state()

            d.destroy()
            self._show_page("Rooms")
            self._status(f"✔ Room '{name}' added via {conn_code}!", NEON_GREEN)

        tk.Button(d, text="Save Room", bg=NEON_BLUE, fg=BG1,
                  font=("Helvetica", 10, "bold"), relief="flat", padx=16, pady=6,
                  command=save).pack(pady=16)

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: GRAPH
    # ══════════════════════════════════════════════════════════════════════════
    def _page_graph(self, parent):
        top_f = tk.Frame(parent, bg=BG1)
        top_f.pack(fill="x", padx=24, pady=(16, 8))

        tk.Label(top_f, text="REAL-TIME ROOM GRAPH", fg=WHITE, bg=BG1,
                 font=("Helvetica", 12, "bold")).pack(side="left")

        tk.Label(top_f, text="Select Room:", fg=GREY1, bg=BG1,
                 font=("Helvetica", 9)).pack(side="left", padx=(24, 6))

        room_names = [f"{r['icon']} {r['name']} ({r['sensor']})" for r in self.rooms]
        ids = [r["id"] for r in self.rooms]
        sel_name = room_names[ids.index(self.active_room_id)] if self.active_room_id in ids else room_names[0]
        self._graph_sel_var = tk.StringVar(value=sel_name)
        cb = ttk.Combobox(top_f, textvariable=self._graph_sel_var, values=room_names,
                          width=30, font=("Helvetica", 9))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self._on_graph_room_switch)

        self._full_graph = LiveGraph(parent, title=f"Real-Time Readings: {self._graph_sel_var.get()}")
        self._full_graph.pack(fill="both", expand=True, padx=20, pady=12)

        cur_id = self.active_room_id
        for v in list(self.history.get(cur_id, [])):
            self._full_graph.push(v)

        sf = tk.Frame(parent, bg=BG1)
        sf.pack(fill="x", padx=20, pady=(0, 14))
        self._graph_stat_labels = {}
        for label, col in [("CURRENT LEVEL", NEON_BLUE), ("RECORDED PEAK", NEON_RED),
                           ("RECORDED LOW", NEON_GREEN), ("STD DEVIATION", PURPLE)]:
            card = tk.Frame(sf, bg=GLASS, padx=16, pady=10,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", expand=True, fill="x", padx=4)
            tk.Label(card, text=label, fg=GREY1, bg=GLASS, font=("Helvetica", 8)).pack(anchor="w")
            lbl = tk.Label(card, text="—", fg=col, bg=GLASS, font=("Helvetica", 16, "bold"))
            lbl.pack(anchor="w")
            self._graph_stat_labels[label] = lbl

    def _on_graph_room_switch(self, event=None):
        val = self._graph_sel_var.get()
        room_names = [f"{r['icon']} {r['name']} ({r['sensor']})" for r in self.rooms]
        try:
            sel_idx = self.rooms[room_names.index(val)]["id"]
        except ValueError:
            sel_idx = self.active_room_id
        self.active_room_id = sel_idx
        self._full_graph.set_title(f"Real-Time Readings: {val}")
        self._full_graph.data = deque(self.history.get(sel_idx, [0.0]*60), maxlen=60)
        self._full_graph.redraw()

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: ALERTS
    # ══════════════════════════════════════════════════════════════════════════
    def _page_alerts(self, parent):
        hf = tk.Frame(parent, bg=BG1)
        hf.pack(fill="x", padx=24, pady=(16, 8))
        tk.Label(hf, text="🔔  SYSTEM INCIDENTS & ALERTS", fg=WHITE, bg=BG1,
                 font=("Helvetica", 12, "bold")).pack(side="left")
        tk.Button(hf, text="🗑 Clear Alerts", command=self._clear_alerts,
                  bg=GLASS, fg=GREY1, font=("Helvetica", 8), relief="flat", padx=10).pack(side="right")

        badge_f = tk.Frame(parent, bg=BG1)
        badge_f.pack(fill="x", padx=20, pady=(0, 10))
        for label, col, attr in [
            ("TOTAL ALERTS", NEON_YLW, "_badge_total"),
            ("DANGER ALERTS", NEON_RED, "_badge_danger"),
            ("WARNINGS", NEON_YLW, "_badge_warn"),
            ("RESOLVED", NEON_GREEN, "_badge_safe")]:
            card = tk.Frame(badge_f, bg=GLASS, padx=16, pady=10,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", expand=True, fill="x", padx=4)
            tk.Label(card, text=label, fg=GREY1, bg=GLASS, font=("Helvetica", 8)).pack(anchor="w")
            lbl = tk.Label(card, text="0", fg=col, bg=GLASS, font=("Helvetica", 20, "bold"))
            lbl.pack(anchor="w")
            setattr(self, attr, lbl)
        self._refresh_alert_badges()

        cols = tk.Frame(parent, bg=GLASS2)
        cols.pack(fill="x", padx=20)
        for txt, w in [("TIMESTAMP", 20), ("LEVEL", 12), ("READING", 10), ("ROOM / SENSOR", 26), ("ACTION TAKEN", 30)]:
            tk.Label(cols, text=txt, fg=GREY1, bg=GLASS2, font=("Helvetica", 8, "bold"),
                     width=w, anchor="w").pack(side="left", padx=4)

        list_f = tk.Frame(parent, bg=BG1)
        list_f.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        sb = tk.Scrollbar(list_f)
        sb.pack(side="right", fill="y")
        self._alert_listbox = tk.Listbox(
            list_f, bg=GLASS, fg=WHITE, yscrollcommand=sb.set,
            font=("Courier", 9), relief="flat", borderwidth=0)
        self._alert_listbox.pack(fill="both", expand=True)
        sb.config(command=self._alert_listbox.yview)
        self._populate_alert_list()

    def _refresh_alert_badges(self):
        total = len(self.alert_log)
        d = sum(1 for a in self.alert_log if a["level"] == "DANGER")
        w = sum(1 for a in self.alert_log if a["level"] == "WARNING")
        s = total - d - w
        for attr, val in [("_badge_total", total), ("_badge_danger", d),
                          ("_badge_warn", w), ("_badge_safe", s)]:
            if hasattr(self, attr): getattr(self, attr).config(text=str(val))

    def _populate_alert_list(self):
        if not hasattr(self, "_alert_listbox"): return
        self._alert_listbox.delete(0, "end")
        for a in reversed(self.alert_log[-200:]):
            room_name = a.get("room_name", f"Sensor {a['sensor']+1}")
            line = f"  {a['time']:19s}  {a['level']:10s}  {a['pct']:5.1f}%     {room_name:24s}  {a['action']}"
            self._alert_listbox.insert("end", line)
            col = {"DANGER": NEON_RED, "WARNING": NEON_YLW}.get(a["level"], NEON_GREEN)
            self._alert_listbox.itemconfig("end", fg=col)

    def _clear_alerts(self):
        self.alert_log.clear()
        self.alert_count = 0
        self._populate_alert_list()
        self._refresh_alert_badges()

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: LOG & EXPORT
    # ══════════════════════════════════════════════════════════════════════════
    def _page_log(self, parent):
        hf = tk.Frame(parent, bg=BG1)
        hf.pack(fill="x", padx=24, pady=(16, 8))
        tk.Label(hf, text="📋  SYSTEM DATA LOG", fg=WHITE, bg=BG1,
                 font=("Helvetica", 12, "bold")).pack(side="left")
        tk.Button(hf, text="💾 Export CSV", command=self._export_csv,
                  bg=NEON_BLUE, fg=BG1, font=("Helvetica", 8, "bold"),
                  relief="flat", padx=12, pady=4).pack(side="right")
        tk.Button(hf, text="🗑 Clear Log", command=self._clear_log,
                  bg=GLASS, fg=GREY1, font=("Helvetica", 8), relief="flat", padx=10, pady=4).pack(side="right", padx=8)

        self._log_text = scrolledtext.ScrolledText(
            parent, bg=GLASS, fg=NEON_GREEN, font=("Courier", 9),
            relief="flat", state="disabled")
        self._log_text.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        for row in list(self.csv_rows)[-500:]:
            self._append_log(row)

    def _append_log(self, row):
        if not hasattr(self, "_log_text"): return
        self._log_text.config(state="normal")
        room_name = row[4] if len(row) > 4 else f"Sensor {row[1]}"
        line = f"[{row[0]}] {room_name:18s} {row[2]:>5.1f}%  {row[3]:8s}\n"
        self._log_text.insert("end", line)
        self._log_text.see("end")
        if int(self._log_text.index("end-1c").split(".")[0]) > 1200:
            self._log_text.delete("1.0", "200.0")
        self._log_text.config(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGE: SETTINGS
    # ══════════════════════════════════════════════════════════════════════════
    def _page_settings(self, parent):
        canvas = tk.Canvas(parent, bg=BG1, highlightthickness=0)
        sb = tk.Scrollbar(parent, command=canvas.yview)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=BG1)
        win = canvas.create_window(0, 0, anchor="nw", window=inner)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        def section(label):
            f = tk.Frame(inner, bg=GLASS, highlightbackground=BORDER, highlightthickness=1)
            f.pack(fill="x", padx=24, pady=(12, 0))
            tk.Label(f, text=label, fg=NEON_BLUE, bg=GLASS,
                     font=("Helvetica", 10, "bold")).pack(anchor="w", padx=16, pady=(10, 6))
            body = tk.Frame(f, bg=GLASS, padx=16)
            body.pack(fill="x", pady=(0, 12))
            return body

        def row(parent, label, var, width=22):
            r = tk.Frame(parent, bg=GLASS)
            r.pack(fill="x", pady=4)
            tk.Label(r, text=label, fg=GREY1, bg=GLASS, font=("Helvetica", 9), width=24, anchor="w").pack(side="left")
            e = tk.Entry(r, textvariable=var, font=("Helvetica", 9), bg=GLASS2, fg=WHITE, relief="flat", width=width)
            e.pack(side="left", padx=8)
            return e

        tk.Label(inner, text="⚙  SYSTEM CONFIGURATION", fg=WHITE, bg=BG1,
                 font=("Helvetica", 12, "bold")).pack(anchor="w", padx=24, pady=(16, 4))

        self._cfg_vars = {}
        gen = section("🏠  Facility Profile")
        for key, label in [("facility_name", "Facility Name")]:
            v = tk.StringVar(value=self.cfg[key])
            self._cfg_vars[key] = v
            row(gen, label, v)

        thr = section("🎚  Thresholds & Timing")
        for key, label in [("warn_thresh", "Warning Level (%)"),
                           ("danger_thresh", "Danger Trigger (%)"),
                           ("cooldown", "Alert Cooldown (sec)")]:
            v = tk.StringVar(value=str(self.cfg[key]))
            self._cfg_vars[key] = v
            row(thr, label, v, 8)

        adc = section("📐  Raw Sensor Calibration (USB serial only)")
        for key, label in [("baseline_raw", "Clean-Air ADC (0–1023)"),
                           ("danger_raw", "Danger ADC (0–1023)")]:
            v = tk.StringVar(value=str(self.cfg[key]))
            self._cfg_vars[key] = v
            row(adc, label, v, 8)
        tk.Label(adc, text="WiFi sensors calibrated on the ESP32 report severity directly and ignore these.",
                 fg=GREY1, bg=GLASS, font=("Helvetica", 8), wraplength=620, justify="left").pack(anchor="w", pady=(2, 0))

        notif = section("📧  Email Notifications (SMTP)")
        for key, label in [("email_to", "Recipient Email"),
                           ("email_from", "Sender Email"),
                           ("email_pass", "App Password"),
                           ("smtp_host", "SMTP Server"),
                           ("smtp_port", "SMTP Port")]:
            v = tk.StringVar(value=self.cfg[key])
            self._cfg_vars[key] = v
            row(notif, label, v)
        tk.Button(notif, text="📧 Test Email", command=self._test_email,
                  bg=GLASS2, fg=NEON_BLUE, font=("Helvetica", 9), relief="flat", padx=10, pady=4).pack(anchor="w", pady=(6, 0))

        tg = section("✈  Telegram Instant Alerts")
        for key, label in [("tg_token", "Telegram Bot Token"),
                           ("tg_chat_id", "Target Chat ID")]:
            v = tk.StringVar(value=self.cfg[key])
            self._cfg_vars[key] = v
            row(tg, label, v)
        tk.Button(tg, text="✈ Test Telegram", command=self._test_telegram,
                  bg=GLASS2, fg=PURPLE, font=("Helvetica", 9), relief="flat", padx=10, pady=4).pack(anchor="w", pady=(6, 0))

        tk.Button(inner, text="💾  SAVE CONFIGURATION", command=self._save_settings,
                  bg=NEON_BLUE, fg=BG1, font=("Helvetica", 11, "bold"),
                  relief="flat", padx=20, pady=10, cursor="hand2").pack(pady=20)

    # ══════════════════════════════════════════════════════════════════════════
    #  CONTROLS & LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def _set_room_valve(self, room_id, is_open, silent=False):
        room = next((r for r in self.rooms if r["id"] == room_id), None)
        if room is None:
            return
        room["valve"] = is_open
        if hasattr(self, "_room_cards") and room_id in self._room_cards:
            self._room_cards[room_id].update_valve(is_open)
        if room_id == self.active_room_id:
            if hasattr(self, "_valve_tog"):
                self._valve_tog.set(is_open)
            if hasattr(self, "_valve_lbl"):
                self._valve_lbl.config(text="OPEN" if is_open else "CLOSED",
                                       fg=NEON_GREEN if is_open else NEON_RED)
        if not silent:
            self._status(f"{room['name']} valve set to {'OPEN' if is_open else 'CLOSED'}",
                         NEON_GREEN if is_open else NEON_RED)

    def _on_room_valve(self, on):
        self._set_room_valve(self.active_room_id, on)

    def _close_current_valve(self):
        self._set_room_valve(self.active_room_id, False)

    def _on_room_auto(self, on):
        self._get_active_room()["auto_shut"] = on

    def _on_fan(self, on):
        self.fan_on = on
        self._fan_auto = False
        self._status(f"Exhaust fan {'ACTIVATED' if on else 'OFF'}", NEON_BLUE)

    def _on_sound(self, on):
        self.sound_on = on

    def _draw_close_btn(self, hover=False):
        if not hasattr(self, "_close_cv"): return
        c = self._close_cv; c.delete("all")
        bg = "#FF5577" if hover else NEON_RED
        rr(c, 0, 0, 150, 62, r=12, fill=bg, outline="")
        c.create_text(75, 22, text="CLOSE VALVE", fill=WHITE, font=("Helvetica", 9, "bold"))
        c.create_text(75, 40, text="NOW  ⚡", fill=WHITE, font=("Helvetica", 11, "bold"))

    def _draw_bar(self, pct, W=None):
        if not hasattr(self, "_bar_cv"): return
        c = self._bar_cv; c.delete("all")
        W = W or (c.winfo_width() or 500)
        rr(c, 0, 0, W, 12, r=6, fill=GREY2, outline="")
        fw = max(8, int(pct / 100.0 * W))
        col = level_color(pct)
        rr(c, 0, 0, fw, 12, r=6, fill=col, outline="")
        for thresh, tc in [(self.cfg["warn_thresh"], NEON_YLW), (self.cfg["danger_thresh"], NEON_RED)]:
            tx = int(thresh / 100.0 * W)
            c.create_line(tx, 0, tx, 12, fill=tc, width=2)

    def _save_settings(self):
        int_keys = ("warn_thresh", "danger_thresh", "cooldown", "baseline_raw", "danger_raw")
        for key, var in self._cfg_vars.items():
            val = var.get().strip()
            if key in int_keys:
                try:
                    self.cfg[key] = int(float(val))
                except ValueError:
                    messagebox.showerror("Invalid value", f"{key.replace('_', ' ').title()} must be a number.")
                    return
            else:
                self.cfg[key] = val

        if not (0 < self.cfg["warn_thresh"] < self.cfg["danger_thresh"] <= 100):
            messagebox.showerror("Invalid thresholds",
                                 "Warning must be lower than Danger, and both within 1–100%.")
            return
        if self.cfg["baseline_raw"] >= self.cfg["danger_raw"]:
            messagebox.showerror("Invalid calibration",
                                 "Clean-air ADC must be lower than the Danger ADC value.")
            return
        if self.cfg["cooldown"] < 5:
            self.cfg["cooldown"] = 5

        THRESHOLDS["warn"] = self.cfg["warn_thresh"]
        THRESHOLDS["danger"] = self.cfg["danger_thresh"]
        self._save_state()
        self._draw_header()
        self._status("✔ Settings saved to config.json", NEON_GREEN)
        messagebox.showinfo("Saved", "Settings saved and applied.")

    def _test_email(self):
        if not (self.cfg["email_to"] and self.cfg["email_from"] and self.cfg["email_pass"]):
            messagebox.showwarning("Email not configured",
                                   "Fill in recipient, sender and app password, then Save Configuration first.")
            return
        threading.Thread(target=self._send_email,
                         args=("TEST ALERT — Gas Saver Pro", "Test notification from multi-room gas monitor."),
                         daemon=True).start()

    def _test_telegram(self):
        if not (self.cfg["tg_token"] and self.cfg["tg_chat_id"]):
            messagebox.showwarning("Telegram not configured",
                                   "Fill in the bot token and chat ID, then Save Configuration first.")
            return
        threading.Thread(target=self._send_telegram,
                         args=("🧪 *Gas Saver Pro* — Telegram connection verified!",),
                         daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  POLL & ENGINE
    # ══════════════════════════════════════════════════════════════════════════
    def _start_all_readers(self):
        for r in self.rooms:
            reader = SensorReader(self.q, self.raw_to_pct, port=r.get("port", "DEMO"),
                                  conn_type=r.get("conn_type", "DEMO"),
                                  sensor_id=r["id"], base=r.get("base", 15.0))
            reader.start()
            self.readers.append(reader)

    def _poll(self):
        updated = set()
        try:
            while True:
                sid, pct, ts = self.q.get_nowait()
                if sid == -1:
                    continue
                if pct < 0:                      # offline sentinel — never fake a reading
                    if not self.offline.get(sid, False):
                        self.offline[sid] = True
                        updated.add(sid)
                    continue

                self.last_seen[sid] = time.time()
                if self.offline.get(sid, True):
                    self.offline[sid] = False
                    updated.add(sid)

                self.sensor_pcts[sid] = pct
                if sid not in self.history:
                    self.history[sid] = deque([0.0]*60, maxlen=60)
                self.history[sid].append(pct)
                updated.add(sid)

                room = next((r for r in self.rooms if r["id"] == sid), None)
                room_name = room["name"] if room else f"Room {sid+1}"
                row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       sid, round(pct, 1), level_name(pct), room_name]
                self._record_row(row)
        except queue.Empty:
            pass

        self._drain_controls()

        if updated:
            self._update_ui(updated)

        self.root.after(300, self._poll)

    def _drain_controls(self):
        """Apply commands sent by the web dashboard (valve / fan / auto)."""
        while True:
            try:
                cmd, rid, val = self.ctrl_q.get_nowait()
            except queue.Empty:
                return
            if cmd == "valve":
                self._set_room_valve(rid, val)
            elif cmd == "fan":
                self.fan_on = val
                self._fan_auto = False
                if hasattr(self, "_fan_tog"):
                    self._fan_tog.set(val)
                self._status(f"Exhaust fan {'ACTIVATED' if val else 'OFF'} (web dashboard)", NEON_BLUE)
            elif cmd == "auto":
                room = next((r for r in self.rooms if r["id"] == rid), None)
                if room is not None:
                    room["auto_shut"] = val
                    self._status(f"{room['name']} auto-shutoff {'ENABLED' if val else 'DISABLED'}",
                                 NEON_GREEN if val else GREY1)

    def _update_ui(self, updated):
        act_id = self.active_room_id
        act_pct = self.sensor_pcts.get(act_id, 0.0)
        act_offline = self.offline.get(act_id, False)

        if hasattr(self, "_room_chips"):
            for rid, (cf, icon_lbl, val_lbl) in self._room_chips.items():
                v = self.sensor_pcts.get(rid, 0.0)
                if self.offline.get(rid, False):
                    val_lbl.config(text="OFFLINE", fg=GREY1)
                else:
                    val_lbl.config(text=f"{v:.0f}%", fg=level_color(v))

        if hasattr(self, "_gauge"):
            if act_offline:
                self._gauge.set_value(act_pct, "OFFLINE", GREY1)
            else:
                self._gauge.set_value(act_pct, level_name(act_pct))
        if hasattr(self, "_bar_cv"):
            self._draw_bar(0 if act_offline else act_pct)

        if act_id in updated and not act_offline:
            if hasattr(self, "_dash_graph"):
                self._dash_graph.push(act_pct)
            if hasattr(self, "_full_graph"):
                self._full_graph.push(act_pct)

        vals = list(self.history.get(act_id, []))
        if hasattr(self, "_stat_widgets") and vals:
            self._stat_widgets["max"].config(text="—" if act_offline else f"{max(vals):.0f}%")
            self._stat_widgets["min"].config(text="—" if act_offline else f"{min(vals):.0f}%")
            self._stat_widgets["avg"].config(text="—" if act_offline else f"{sum(vals)/len(vals):.0f}%")
            self._stat_widgets["alerts"].config(text=str(self.alert_count))
        if hasattr(self, "_graph_stat_labels") and vals:
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            self._graph_stat_labels["CURRENT LEVEL"].config(text="—" if act_offline else f"{act_pct:.0f}%")
            self._graph_stat_labels["RECORDED PEAK"].config(text=f"{max(vals):.0f}%")
            self._graph_stat_labels["RECORDED LOW"].config(text=f"{min(vals):.0f}%")
            self._graph_stat_labels["STD DEVIATION"].config(text=f"{std:.1f}")

        if hasattr(self, "_room_cards"):
            for rid, card in self._room_cards.items():
                if rid in updated:
                    card.update_reading(self.sensor_pcts.get(rid, 0.0),
                                        online=not self.offline.get(rid, True))

        for r in self.rooms:
            rid = r["id"]
            if rid not in updated or self.offline.get(rid, False):
                continue
            pct = self.sensor_pcts[rid]
            lvl = level_name(pct)

            if lvl == "DANGER":
                if r.get("auto_shut", True) and r.get("valve", True):
                    self._set_room_valve(rid, False, silent=True)
                self._fire_alert(pct, rid, lvl, r["name"],
                                 f"Valve closed in {r['name']}, fan ON")
                self._flash(NEON_RED)
            elif lvl == "WARNING":
                self._fire_alert(pct, rid, lvl, r["name"], f"Elevated reading in {r['name']}")
                self._flash(NEON_YLW)

            prev = self._room_state.get(rid, "SAFE")
            if lvl == "SAFE" and prev in ("WARNING", "DANGER"):
                self._log_alert_entry(pct, rid, "SAFE", r["name"], "Reading back to normal")
                self._room_alert_ts.pop((rid, "WARNING"), None)
                self._room_alert_ts.pop((rid, "DANGER"), None)
            self._room_state[rid] = lvl

        # Automatic exhaust fan follows the worst reading across all online rooms
        any_danger = any(p >= THRESHOLDS["danger"]
                         for rid, p in self.sensor_pcts.items()
                         if not self.offline.get(rid, False))
        if any_danger and not self.fan_on:
            self.fan_on = True
            self._fan_auto = True
            if hasattr(self, "_fan_tog"):
                self._fan_tog.set(True)
            self._status("Exhaust fan AUTO-ON (danger detected)", NEON_RED)
        elif not any_danger and self._fan_auto and self.fan_on:
            self.fan_on = False
            self._fan_auto = False
            if hasattr(self, "_fan_tog"):
                self._fan_tog.set(False)
            self._status("All rooms back to safe — exhaust fan auto-off", NEON_GREEN)

    def _flash(self, color):
        dim = blend(color, BG1, 0.82)
        self.root.configure(bg=dim)
        if self._flash_id: self.root.after_cancel(self._flash_id)
        self._flash_id = self.root.after(500, lambda: self.root.configure(bg=BG1))

    def _status(self, msg, col=GREY1):
        if hasattr(self, "_status_lbl"):
            self._status_lbl.config(text=msg, fg=col)

    def _tick_clock(self):
        now = datetime.now().strftime("%A, %d %b %Y  %H:%M:%S")
        if hasattr(self, "_clock_lbl"):
            self._clock_lbl.config(text=now)
        self._refresh_online_flags()
        self._draw_header()
        if self.alert_log and hasattr(self, "_last_alert_lbl"):
            ago = int(time.time() - self.last_alert_time)
            self._last_alert_lbl.config(text=f"Last alert: {ago}s ago")
        self.root.after(1000, self._tick_clock)

    def _refresh_online_flags(self):
        """Hardware rooms with no fresh reading for OFFLINE_TIMEOUT go OFFLINE.
        Push-only rooms (no reader thread) depend entirely on this check."""
        now = time.time()
        changed = set()
        for r in self.rooms:
            rid = r["id"]
            ct = r.get("conn_type", "DEMO")
            online = True if ct == "DEMO" else (now - self.last_seen.get(rid, 0.0) <= OFFLINE_TIMEOUT)
            if online != self.offline.get(rid, False):
                self.offline[rid] = online
                changed.add(rid)
                self._status(f"{r['name']} is {'ONLINE' if online else 'OFFLINE'}",
                             NEON_GREEN if online else ORANGE)
        if changed:
            self._update_ui(changed)

    # ══════════════════════════════════════════════════════════════════════════
    #  ALERTS
    # ══════════════════════════════════════════════════════════════════════════
    def _log_alert_entry(self, pct, sensor_id, level, room_name, action):
        self.alert_log.append({
            "time":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pct":       pct,
            "level":     level,
            "sensor":    sensor_id,
            "room_name": room_name,
            "action":    action,
        })
        if len(self.alert_log) > 500:
            del self.alert_log[:200]
        if hasattr(self, "_alert_listbox"):
            self._populate_alert_list()
        self._refresh_alert_badges()

    def _fire_alert(self, pct, sensor_id, level, room_name, action):
        now = time.time()
        cooldown = self.cfg.get("cooldown", 30)

        # Per-room, per-level cooldown: one room's alert no longer mutes another room
        key = (sensor_id, level)
        if now - self._room_alert_ts.get(key, 0) < cooldown:
            return
        self._room_alert_ts[key] = now
        self.last_alert_time = now
        self.alert_count += 1
        self._log_alert_entry(pct, sensor_id, level, room_name, action)

        msg = f"GAS {level} in {room_name}!\nReading: {pct:.0f}%\nAction: {action}"

        if self.sound_on and SOUND_OK:
            threading.Thread(target=self._beep, daemon=True).start()

        if PLYER_OK:
            # Run in a worker so a stuck toast never blocks the UI thread
            def _toast():
                try:
                    notification.notify(title=f"🚨 GAS {level} — {room_name}",
                                        message=msg, app_name="Gas Saver Pro", timeout=10)
                except Exception:
                    pass
            threading.Thread(target=_toast, daemon=True).start()

        if self.cfg["email_to"] and self.cfg["email_pass"]:
            threading.Thread(target=self._send_email,
                             args=(f"GAS {level} ALERT — {room_name}", msg), daemon=True).start()

        if self.cfg["tg_token"] and self.cfg["tg_chat_id"]:
            threading.Thread(target=self._send_telegram,
                             args=(f"🚨 *GAS {level} ALERT*\n*Location:* {room_name}\n*Level:* {pct:.0f}%\n*Action:* {action}",),
                             daemon=True).start()

        if level == "DANGER":
            self.root.after(0, lambda: self._popup(pct, room_name))

    def _beep(self):
        if SOUND_OK:
            for _ in range(3):
                winsound.Beep(1200, 250)
                time.sleep(0.08)

    def _ui_status(self, msg, color):
        # Safe to call from worker threads
        self.root.after(0, lambda: self._status(msg, color))

    def _send_email(self, subject, body):
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.cfg["email_from"]
            msg["To"] = self.cfg["email_to"]
            port = int(self.cfg["smtp_port"])
            if port == 465:
                server = smtplib.SMTP_SSL(self.cfg["smtp_host"], port, timeout=10)
            else:
                server = smtplib.SMTP(self.cfg["smtp_host"], port, timeout=10)
            with server as s:
                if port != 465:
                    s.starttls()
                s.login(self.cfg["email_from"], self.cfg["email_pass"])
                s.send_message(msg)
            self._ui_status("📧 Email alert dispatched!", NEON_GREEN)
        except Exception as e:
            self._ui_status(f"Email error: {e}", NEON_RED)

    def _send_telegram(self, text):
        if not REQUESTS_OK:
            self._ui_status("Telegram needs the 'requests' package", NEON_RED)
            return
        try:
            url = f"https://api.telegram.org/bot{self.cfg['tg_token']}/sendMessage"
            requests.post(url, data={"chat_id": self.cfg["tg_chat_id"], "text": text,
                                     "parse_mode": "Markdown"}, timeout=8)
            self._ui_status("✈ Telegram alert dispatched!", NEON_GREEN)
        except Exception as e:
            self._ui_status(f"Telegram error: {e}", NEON_RED)

    def _popup(self, pct, room_name):
        pop = tk.Toplevel(self.root)
        pop.title("⚠ CRITICAL GAS ALERT")
        pop.configure(bg="#0A0005")
        pop.geometry("440x240")
        pop.attributes("-topmost", True)
        pop.resizable(False, False)
        c = tk.Canvas(pop, width=440, height=240, bg="#0A0005", highlightthickness=0)
        c.pack()
        rr(c, 8, 8, 432, 232, r=18, fill="#18000E", outline=NEON_RED, width=2)
        c.create_text(220, 52, text="🚨  CRITICAL GAS DANGER", fill=NEON_RED, font=("Helvetica", 16, "bold"))
        c.create_text(220, 88, text=f"Location: {room_name}", fill=WHITE, font=("Helvetica", 14, "bold"))
        c.create_text(220, 118, text=f"Gas Level: {pct:.0f}%  —  AUTO-SHUTOFF TRIGGERED", fill=NEON_YLW, font=("Helvetica", 10, "bold"))
        c.create_text(220, 146, text="Room valve auto-closed. Ventilate & evacuate area.", fill=GREY1, font=("Helvetica", 9))
        btn = tk.Button(pop, text="✔  ACKNOWLEDGE", bg=NEON_RED, fg=WHITE,
                        font=("Helvetica", 11, "bold"), relief="flat", pady=7, padx=24,
                        command=pop.destroy, cursor="hand2")
        c.create_window(220, 196, window=btn)
        pop.after(25000, pop.destroy)

    def _export_csv(self):
        try:
            if self._csv_file:
                self._csv_file.flush()
            self._status(f"💾 Log saved to {LOG_FILE}", NEON_GREEN)
            messagebox.showinfo("Log Saved",
                                f"Readings are recorded continuously to:\n{LOG_FILE}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════════════════
def main():
    root = tk.Tk()
    app = GasSaverApp(root)
    def on_close():
        for r in app.readers:
            r.stop()
        app.wifi_server.stop()
        app._save_state()
        try:
            if app._csv_file:
                app._csv_file.flush()
                app._csv_file.close()
        except Exception:
            pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
