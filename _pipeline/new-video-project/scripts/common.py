"""Shared helpers for the pipeline tools: media probing, time math, JSON I/O."""
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def read_json(path, what="file"):
    """Load a JSON file, exiting with a one-line error when it's missing."""
    p = Path(path).expanduser()
    if not p.exists():
        sys.exit(f"{what} not found: {p}")
    return json.loads(p.read_text())


def ffprobe_media(path) -> dict:
    """fps (string fraction), width, height, duration, has_audio, has_video."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    info = {"path": str(path), "fps": None, "width": None, "height": None,
            "duration": None, "has_audio": False, "has_video": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"] = s.get("width")
            info["height"] = s.get("height")
            info["fps"] = s.get("r_frame_rate") or s.get("avg_frame_rate") or "30/1"
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    dur = data.get("format", {}).get("duration")
    info["duration"] = float(dur) if dur else 0.0
    return info


def fps_fraction(fps_str: str) -> Fraction:
    if "/" in fps_str:
        num, den = fps_str.split("/")
        return Fraction(int(num), int(den))
    return Fraction(fps_str)


def sec_to_rational(seconds: float, fps: Fraction) -> str:
    """Seconds -> frame-aligned FCPXML rational time string."""
    frames = round(seconds * fps)
    t = Fraction(frames, 1) / fps
    return f"{t.numerator}/{t.denominator}s" if t.denominator != 1 else f"{t.numerator}s"


def parse_timecode(tc) -> float:
    """Accept float seconds, 'SS', 'MM:SS', 'HH:MM:SS(.ms)' -> seconds."""
    if isinstance(tc, (int, float)):
        return float(tc)
    parts = [float(p) for p in str(tc).strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s
