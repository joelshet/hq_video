#!/usr/bin/env python3
"""Tile a recording into one timestamped contact sheet image.

  contactsheet.py SRC -o OUT.jpg [--interval S] [--cols 6] [--tile-width 320]

One glance answers the layout questions that otherwise cost a probe each:
where the PIP sits, which stretches are full-cam vs screen, when the big
scene changes happen, which intro frames have a usable face. Default
interval targets ~48 tiles (clamped 2-15s); each tile is labeled M:SS.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import ffprobe_media

FONTS = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Helvetica.ttc"]


def load_font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--interval", type=float,
                    help="seconds between tiles (default: duration/48, 2-15s)")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--tile-width", type=int, default=320)
    args = ap.parse_args()

    info = ffprobe_media(args.src)
    if not info["has_video"]:
        sys.exit(f"no video stream in {args.src}")
    interval = args.interval or min(15.0, max(2.0, info["duration"] / 48))

    tw = args.tile_width
    th = round(tw * info["height"] / info["width"] / 2) * 2
    band = 16
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", args.src,
             "-vf", f"fps=1/{interval},scale={tw}:{th}",
             f"{tmp}/f%04d.jpg"], check=True)
        frames = sorted(Path(tmp).glob("f*.jpg"))
        if not frames:
            sys.exit("no frames extracted")
        cols = args.cols
        rows = -(-len(frames) // cols)
        sheet = Image.new("RGB", (cols * tw, rows * (th + band)), "black")
        draw = ImageDraw.Draw(sheet)
        font = load_font(12)
        for k, f in enumerate(frames):
            x, y = (k % cols) * tw, (k // cols) * (th + band)
            sheet.paste(Image.open(f), (x, y))
            t = k * interval
            draw.text((x + 4, y + th + 2), f"{int(t // 60)}:{int(t % 60):02d}",
                      fill="white", font=font)
        sheet.save(args.out, quality=85)
    print(f"{args.out}: {len(frames)} tiles @ {interval:.1f}s, "
          f"{cols}x{rows}, {sheet.width}x{sheet.height}", file=sys.stderr)


if __name__ == "__main__":
    main()
