#!/usr/bin/env python3
"""Screen-activity map: find WHEN and WHERE things change in a screen recording.

Diffs consecutive frames (downscaled gray) and groups changed frames into
bursts. Each burst is a user action or UI event: click, page flip, typing,
paste, toast, streaming text, cursor move. Use it to place shot windows on
real actions (shorts beats, punch-in zooms) instead of guessing from the
transcript, and to aim crops at the changing region.

Usage:
  activity.py SRC [--mask x0:y0:x1:y1 ...]

Bursts go to stdout as a JSON array (summary on stderr) so burst windows
pipe straight into shot lists and cut lists.

Always mask the webcam PIP (it changes constantly) and the browser chrome
(tab spinners, recording indicator). Example for the standard layout:
  --mask 1449:615:1881:1045 --mask 0:0:1920:120

Reading the report:
  peak > 3000   page/view change (click that navigated, window switch)
  peak > 300    dialog, toast, scroll
  long + small  typing, streaming text, selection sweep, cursor glide
  ~9 px @ fixed spot every 0.5s   a blinking caret (tells you where focus is)
"""
import argparse, json, subprocess, sys
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("src")
p.add_argument("--mask", action="append", default=[],
               help="x0:y0:x1:y1 in source pixels, repeatable")
p.add_argument("--fps", type=float, default=10)
a = p.parse_args()

MIN_PIX = 4    # changed pixels for a frame to count as active
THRESH = 14    # per-pixel gray delta

probe = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height", "-of", "csv=p=0", a.src],
    capture_output=True, text=True)
sw, sh = map(int, probe.stdout.strip().split(","))
W = 480
H = round(sh * W / sw / 2) * 2
SX, SY = sw / W, sh / H

cmd = ["ffmpeg", "-loglevel", "error",
       "-i", a.src, "-vf", f"fps={a.fps},scale={W}:{H}",
       "-f", "rawvideo", "-pix_fmt", "gray", "-"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

mask = np.ones((H, W), dtype=bool)
for m in a.mask:
    x0, y0, x1, y1 = map(int, m.split(":"))
    mask[int(y0/SY):int(y1/SY)+1, int(x0/SX):int(x1/SX)+1] = False

prev, rows, i = None, [], 0
while True:
    buf = proc.stdout.read(W * H)
    if len(buf) < W * H:
        break
    f = np.frombuffer(buf, dtype=np.uint8).reshape(H, W).astype(np.int16)
    if prev is not None:
        d = np.abs(f - prev)
        ch = (d > THRESH) & mask
        n = int(ch.sum())
        t = i / a.fps
        if n:
            ys, xs = np.nonzero(ch)
            rows.append((t, n, xs.min()*SX, ys.min()*SY, xs.max()*SX, ys.max()*SY))
        else:
            rows.append((t, 0, 0, 0, 0, 0))
    prev = f
    i += 1
proc.wait()

bursts, cur, quiet = [], None, 0
GAP = 3
for r in rows:
    if r[1] >= MIN_PIX:
        if cur is None:
            cur = {"t0": r[0], "t1": r[0], "peak": 0, "fr": []}
        cur["t1"] = r[0]
        cur["peak"] = max(cur["peak"], r[1])
        cur["fr"].append(r)
        quiet = 0
    elif cur:
        quiet += 1
        if quiet > GAP:
            bursts.append(cur); cur = None; quiet = 0
if cur:
    bursts.append(cur)

records = []
for b in bursts:
    fr = b["fr"]
    bx0 = min(f[2] for f in fr); by0 = min(f[3] for f in fr)
    bx1 = max(f[4] for f in fr); by1 = max(f[5] for f in fr)
    dur = b["t1"] - b["t0"]
    peak = b["peak"]
    if peak > 3000:
        kind = "PAGE/VIEW CHANGE"
    elif peak > 300:
        kind = "big (dialog/toast/scroll)"
    elif dur >= 1.0:
        kind = "sustained small (typing/stream/cursor)"
    else:
        kind = "small (click/caret/cursor)"
    records.append({"t0": round(b["t0"], 1), "t1": round(b["t1"], 1),
                    "dur": round(dur, 1), "peak": peak,
                    "box": [round(bx0), round(by0), round(bx1), round(by1)],
                    "kind": kind})

summary = (f"{len(rows)} frames, {len(bursts)} bursts  (npix >= {MIN_PIX}, "
           f"delta > {THRESH}, {a.fps} fps, analysis {W}x{H})")
print(summary, file=sys.stderr)
json.dump(records, sys.stdout, indent=1)
print()
