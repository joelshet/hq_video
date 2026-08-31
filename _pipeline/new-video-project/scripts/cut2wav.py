#!/usr/bin/env python3
"""Assemble a cut list's audio. Filter: cut list JSON on stdin -> wav.

  cut2wav.py --media-root DIR -o OUT.wav [--rate 16000]

One ffmpeg invocation, atrim/concat filter chains: ~80s for a 200-segment
7-minute cut, where the picture preview took most of an hour. This is the
gate medium — the edit is judged on audio (silence residuals,
re-transcription); picture is judged in Resolve.

Spine segments may pull from any number of source files (the multi-clip
folder drop); each segment is normalized to mono at --rate before concat
so mixed recordings join cleanly. Spine items without "in"/"out" (cards)
carry no source audio and are skipped.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-root", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--rate", type=int, default=16000)
    args = ap.parse_args()

    cut = json.load(sys.stdin)
    segs = [(s["src"], s["in"], s["out"]) for s in cut["spine"] if "in" in s]
    if not segs:
        sys.exit("cut2wav: no footage segments in spine")

    root = Path(args.media_root)
    order = list(dict.fromkeys(src for src, _, _ in segs))
    idx = {src: i for i, src in enumerate(order)}
    inputs = [x for src in order for x in ("-i", str(root / src))]

    parts = ";".join(
        f"[{idx[src]}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:sample_rates={args.rate}:"
        f"channel_layouts=mono[s{i}]"
        for i, (src, a, b) in enumerate(segs))
    script = (parts + ";" + "".join(f"[s{i}]" for i in range(len(segs)))
              + f"concat=n={len(segs)}:v=0:a=1[out]")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script)
        spath = f.name
    subprocess.run(["ffmpeg", "-v", "error", *inputs,
                    "-filter_complex_script", spath, "-map", "[out]",
                    "-ac", "1", "-ar", str(args.rate), "-y", args.out],
                   check=True)
    total = sum(b - a for _, a, b in segs)
    print(f"{args.out}: {len(segs)} segments from {len(order)} source(s), "
          f"{total:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
