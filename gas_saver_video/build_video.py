import glob
import json
import os
import re
import subprocess
import sys
import wave

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(os.path.dirname(BASE), "vibe_images")
WORK = os.path.join(BASE, "build")
AUDIO = os.path.join(BASE, "audio")
OUT = os.path.join(BASE, "Gas_Saver_3min_English.mp4")
FF = imageio_ffmpeg.get_ffmpeg_exe()

for d in (WORK, AUDIO):
    os.makedirs(d, exist_ok=True)

NARRATION = [
    "Every day, gas silently fills homes with danger. You cannot always see it. And by the time you notice it, it may be too late. A single spark can turn a quiet night into a disaster. This project asks one simple question: what if your home could sense the danger before you do?",
    "Meet Gas Saver: an affordable gas leak detection system built around an Arduino Uno. At its heart is an M-Q gas sensor that samples the air continuously and measures gas concentration. The Arduino turns that reading into a real-time severity percentage, and the moment gas passes the safe limit, a buzzer and a red LED sound the alarm. The safety core keeps working, even without internet.",
    "But detection is only half the story. Gas Saver also warns you wherever you are. When a sensor trips, the software raises a desktop notification, sends an email, and pushes a Telegram message to your phone. Every room is monitored separately, so you know exactly where the danger is, and how severe it has become.",
    "And it acts automatically. The gas valve shuts itself off, and the exhaust fan clears the air. The software locks the valve closed until someone opens it manually, so the danger can never restart on its own. Sense, decide, alert, shut off. The whole chain happens in seconds.",
    "Everything is visible on a phone-first web dashboard. Each room shows live readings, severity levels, and status: safe, warning, danger, or offline. You can review history, calibrate sensors, and confirm alerts in real time. It runs on an ordinary computer, or a small server at home, so no expensive hardware is needed.",
    "Gas Saver turns a hidden, deadly risk into a problem you can see and stop. It is built from parts almost any student can afford: one Arduino, one gas sensor, a buzzer, and some smart software. This is engineering that protects the people you love. Gas Saver. Breathe easy, because your home is watching.",
]

CAPTIONS = [
    ("A gas leak is silent. Invisible. Deadly.", "It strikes when everyone is asleep."),
    ("Built on an Arduino Uno and an MQ gas sensor.", "Live severity readings, instant buzzer and LED alarm."),
    ("When gas rises, every alert fires at once.", "Desktop toast, email, and Telegram on your phone."),
    ("The gas valve shuts off automatically.", "The exhaust fan clears the air. The valve stays locked."),
    ("A phone-first dashboard for every room.", "Live severity, history, and sensor calibration."),
    ("From a hidden risk to a problem you can stop.", "Gas Saver. Breathe easy."),
]

FPS = 30
W, H = 1920, 1080

FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_REG = "C:/Windows/Fonts/arial.ttf"
if not os.path.exists(FONT_BOLD):
    FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
if not os.path.exists(FONT_REG):
    FONT_REG = "C:/Windows/Fonts/segoeui.ttf"


def find_img(prefix):
    hits = glob.glob(os.path.join(IMG_DIR, prefix + "*.png"))
    if not hits:
        sys.exit("missing image: " + prefix)
    return sorted(hits)[0]


def cover_1080(img):
    img = img.convert("RGB")
    w, h = img.size
    target = W / H
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w + nw) // 2, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h + nh) // 2))
    return img.resize((W, H), Image.LANCZOS)


def caption_overlay(text):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    band = 240
    for y in range(H - band, H):
        a = int(175 * (y - (H - band)) / band)
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))

    font = ImageFont.truetype(FONT_BOLD, 54)
    max_w = 1560
    words, lines, cur = text.split(), [], ""
    for word in words:
        t = (cur + " " + word).strip()
        if font.getlength(t) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)

    y = H - 46 - len(lines) * 68
    for line in lines:
        x = (W - font.getlength(line)) / 2
        d.text((x + 2, y + 3), line, font=font, fill=(0, 0, 0, 210))
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += 68
    return ov


def spaced_text(draw, xy, text, font, fill, gap):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + gap
    return x


def title_card(img):
    bg = cover_1080(img)
    shade = Image.new("RGBA", bg.size, (4, 10, 16, 110))
    bg = Image.alpha_composite(bg.convert("RGBA"), shade).convert("RGB")

    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    big = ImageFont.truetype(FONT_BOLD, 148)
    sub = ImageFont.truetype(FONT_REG, 50)
    small = ImageFont.truetype(FONT_BOLD, 32)

    title = "GAS SAVER"
    total_w = sum(big.getlength(c) + 10 for c in title) - 10
    spaced_text(d, ((W - total_w) / 2 + 3, 330 + 4), title, big, (0, 0, 0, 190), 10)
    spaced_text(d, ((W - total_w) / 2, 330), title, big, (255, 255, 255, 255), 10)

    line = "SMART GAS LEAK DETECTION SYSTEM"
    d.text(((W - small.getlength(line)) / 2, 520), line, font=small, fill=(90, 220, 255, 255))

    s1 = "An Arduino and MQ gas sensor project"
    s2 = "Arduino  ·  MQ Sensor  ·  Python  ·  Web Dashboard"
    d.text(((W - sub.getlength(s1)) / 2, 592), s1, font=sub, fill=(235, 235, 235, 255))
    d.text(((W - small.getlength(s2)) / 2, 664), s2, font=small, fill=(170, 180, 190, 255))
    return bg, ov


# ---------- 1. narration text + TTS ----------
for i, text in enumerate(NARRATION, 1):
    with open(os.path.join(AUDIO, "s%d.txt" % i), "w", encoding="utf-8-sig") as f:
        f.write(text)

ps1 = os.path.join(BASE, "tts_gen.ps1")
with open(ps1, "w", encoding="utf-8-sig") as f:
    f.write("""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
$syn.SelectVoice('Microsoft Zira Desktop')
$syn.Rate = -1
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($i in 1..6) {
  $txt = Get-Content -Raw -Encoding UTF8 (Join-Path $base "audio\\s$i.txt")
  $syn.SetOutputToWaveFile((Join-Path $base "audio\\s$i.wav"))
  $syn.Speak($txt)
}
$syn.SetOutputToNull()
$syn.Dispose()
Write-Output "tts done"
""")

subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1], check=True)

durs = []
for i in range(1, 7):
    with wave.open(os.path.join(AUDIO, "s%d.wav" % i)) as w:
        durs.append(w.getnframes() / w.getframerate())
print("narration durations:", [round(x, 1) for x in durs], "sum", round(sum(durs), 1))

# ---------- 2. stills + captions ----------
order = [
    ("title-background_", None),
    ("test-scene_", CAPTIONS[0][0]),
    ("scene1b-family-asleep_", CAPTIONS[0][1]),
    ("scene2a-arduino-macro_", CAPTIONS[1][0]),
    ("scene2b-led-buzzer_", CAPTIONS[1][1]),
    ("scene3a-haze-kitchen_", CAPTIONS[2][0]),
    ("scene3b-red-sensor_", CAPTIONS[2][1]),
    ("scene4a-gas-valve_", CAPTIONS[3][0]),
    ("scene4b-exhaust-fan_", CAPTIONS[3][1]),
    ("scene5a-phone-dashboard_", CAPTIONS[4][0]),
    ("scene5b-phone-closeup_", CAPTIONS[4][1]),
    ("scene6a-family-breakfast_", CAPTIONS[5][0]),
    ("scene6b-coffee-safe_", CAPTIONS[5][1]),
]

frames = []
for idx, (prefix, cap) in enumerate(order):
    img = Image.open(find_img(prefix))
    if cap is None:
        bg, ov = title_card(img)
    else:
        bg, ov = cover_1080(img), caption_overlay(cap)
    bp = os.path.join(WORK, "f%02d.png" % idx)
    op = os.path.join(WORK, "o%02d.png" % idx)
    bg.save(bp)
    ov.save(op)
    frames.append((bp, op))

# ---------- 3. timeline ----------
pad = 2.4
lead = 0.6
title_len = 7.0


def build_lengths(pad_):
    lens = [title_len]
    for d_ in durs:
        c = (d_ + pad_ + 0.8) / 2
        lens += [c, c]
    return lens


def total_for(lens):
    t = lens[0]
    for j in range(len(lens) - 1):
        o = 0.8 if j % 2 == 1 else 1.0
        t += lens[j + 1] - o
    return t


lens = build_lengths(pad)
total = total_for(lens)
print("initial total:", round(total, 1))
if total < 178:
    pad += (178 - total) / 6
elif total > 186:
    pad = max(1.4, pad - (total - 186) / 6)
pad = max(1.2, min(pad, 4.5))
lens = build_lengths(pad)
total = total_for(lens)

deficit = 180.0 - total
if deficit > 0.2:
    title_len += min(deficit, 6.0)
    lens = build_lengths(pad)
    total = total_for(lens)
print("final pad:", round(pad, 2), "title:", round(title_len, 2), "total:", round(total, 1))

starts = [0.0]
for j in range(len(lens) - 1):
    o = 0.8 if j % 2 == 1 else 1.0
    starts.append(starts[-1] + lens[j] - o)

# ---------- 4. render silent segments ----------
styles = [
    ("in", 0.00055),
    ("panR", 0),
    ("out", 0.00055),
    ("panL", 0),
]

cache_p = os.path.join(WORK, "lens.json")
cache = {}
if os.path.exists(cache_p):
    with open(cache_p) as f:
        cache = json.load(f)

seg_files = []
for j, ((bp, op), L) in enumerate(zip(frames, lens)):
    seg = os.path.join(WORK, "seg%02d.mp4" % j)
    if cache.get(str(j)) is not None and abs(cache[str(j)] - L) < 0.005 and os.path.exists(seg):
        seg_files.append(seg)
        print("seg %02d/%d cached (%.1fs)" % (j + 1, len(frames), L))
        continue
    N = max(2, round(L * FPS))
    style, step = styles[j % 4]
    if style == "in":
        z = "min(zoom+%.5f,1.16)" % step
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == "out":
        z = "if(lte(zoom,1.0),1.16,max(1.001,zoom-%.5f))" % step
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == "panR":
        z = "1.10"
        x, y = "(iw-iw/zoom)*on/%d" % (N - 1), "(ih-ih/zoom)/2"
    else:
        z = "1.10"
        x, y = "(iw-iw/zoom)*(1-on/%d)" % (N - 1), "(ih-ih/zoom)/2"

    fc = (
        "[0:v]scale=3840:2160:flags=lanczos,"
        "zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d[z];"
        "[z][1:v]overlay=0:0,format=yuv420p[o]" % (z, x, y, N, W, H, FPS)
    )
    subprocess.run(
        [FF, "-y", "-loop", "1", "-framerate", str(FPS), "-i", bp,
         "-loop", "1", "-framerate", str(FPS), "-i", op,
         "-filter_complex", fc, "-map", "[o]", "-frames:v", str(N), "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", seg],
        check=True, capture_output=True,
    )
    cache[str(j)] = L
    seg_files.append(seg)
    print("seg %02d/%d rendered (%.1fs)" % (j + 1, len(frames), L))

with open(cache_p, "w") as f:
    json.dump(cache, f)

# ---------- 5. concat + audio ----------
filt = []
cur = "[0:v]"
offset = 0.0
for j in range(len(seg_files) - 1):
    o = 0.8 if j % 2 == 1 else 1.0
    offset = starts[j + 1]
    nxt = "[x%d]" % j
    filt.append("%s[%d:v]xfade=transition=fade:duration=%.2f:offset=%.3f%s" % (cur, j + 1, o, offset, nxt))
    cur = nxt

filt.append("%sfade=t=in:st=0:d=0.8,fade=t=out:st=%.2f:d=1.4,format=yuv420p[v]" % (cur, total - 1.4))

amix_in = []
for k in range(6):
    a_start = starts[2 * k + 1] + lead
    filt.append(
        "[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
        "volume=1.15,adelay=%d:all=1[a%d]" % (len(seg_files) + k, round(a_start * 1000), k)
    )
    amix_in.append("[a%d]" % k)
filt.append(
    "%samix=inputs=6:duration=longest:normalize=0,apad,atrim=0:%.2f[a]" % ("".join(amix_in), total)
)

cmd = [FF, "-y"]
for s in seg_files:
    cmd += ["-i", s]
for k in range(1, 7):
    cmd += ["-i", os.path.join(AUDIO, "s%d.wav" % k)]
cmd += [
    "-filter_complex", ";".join(filt),
    "-map", "[v]", "-map", "[a]",
    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", str(FPS),
    "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
    "-c:a", "aac", "-b:a", "160k",
    "-movflags", "+faststart", "-shortest", OUT,
]
print("final encode...")
subprocess.run(cmd, check=True, capture_output=True)

print(json.dumps({"output": OUT, "seconds": round(total, 1)}))
