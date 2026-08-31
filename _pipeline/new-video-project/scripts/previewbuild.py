#!/usr/bin/env python3
"""Render watchable preview mp4s from cut lists with ffmpeg. One tool, any project.

  previewbuild.py --project $P
  previewbuild.py --project $P cutlist-short.json:short-preview.mp4

Each argument is CUTLIST:OUTPUT (cut list read from $P/resolve/, output written
to $P/exports/). With no pairs, builds cards-preview.mp4 — the cards timeline
is the ultra edit plus cards, so one preview covers both. The frame size comes
from the cut list's width/height (default 1920x1080), so vertical and square
cut lists preview correctly.

Spine shapes (both supported):
  {"src", "in", "out"}   footage slice
  {"src"}                whole file (cards as spine asset clips)

Mixed aspect: sources conform fit-plus-pad (letterbox), never a distorting
squeeze. Lane overlays sized to the canvas (caption bands) composite over
the program; footage-cell overlays are skipped — crop/zoom geometry is
authored for Resolve and judged there, not in previews.

Loudness: single-pass loudnorm pumps card room tone, so pass 1 renders at
native level, ebur128 measures integrated loudness, pass 2 applies flat
volume to -14 LUFS with a limiter. All paths absolute; cwd-independent.

Room-tone bed: the mic gates between takes (pauses sit near -67 to -80dB
against a -50dB in-speech floor), so a looped bed (roomtone.wav, -60dB
mean) runs under the whole program to keep clip-join air from dropping to
the gated floor.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ACONF = ("asetpts=PTS-STARTPTS,"
         "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")


def media_duration(path: str) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip())


def media_size(path: str) -> tuple:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return tuple(int(x) for x in out.split(",")) if out else (0, 0)


def build(root: Path, roomtone: Path, cutlist: str, out_name: str) -> None:
    cut = json.loads((root / "resolve" / cutlist).read_text())
    w, h = cut.get("width", 1920), cut.get("height", 1080)
    # fit + center-pad, never distort: mixed-aspect sources (a 16:9 recording
    # in a 9:16 or 1:1 cut list) letterbox instead of squeezing
    vconf = (f"setpts=PTS-STARTPTS,fps=30,format=yuv420p,"
             f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")

    inputs, chains, t = [], [], 0.0
    for item in cut["spine"]:
        i = len(inputs)
        inputs.append(str(root / item["src"]))
        if "in" in item:
            a, b = item["in"], item["out"]
            chains.append(
                f"[{i}:v]trim={a}:{b},{vconf}[v{i}];"
                f"[{i}:a]atrim={a}:{b},{ACONF}[a{i}]")
            t += b - a
        else:
            chains.append(
                f"[{i}:v]{vconf}[v{i}];"
                f"[{i}:a]{ACONF}[a{i}]")
            t += media_duration(inputs[-1])

    # lane overlays: composite the ones sized to the canvas (caption bands);
    # skip footage cells — crop/zoom geometry is judged in Resolve, not here
    bands, skipped = [], []
    for ov in cut.get("overlays", []):
        src = str(root / ov["src"])
        (bands if media_size(src) == (w, h) else skipped).append((ov, src))
    for ov, _ in skipped:
        print(f"  note: overlay {ov.get('name', ov['src'])} not composited "
              "(footage cell — geometry is judged in Resolve)", file=sys.stderr)

    n = len(inputs)
    pads = "".join(f"[v{i}][a{i}]" for i in range(n))
    graph = (";".join(chains)
             + f";{pads}concat=n={n}:v=1:a=1[vcat][acat]"
             + f";[{n}:a]{ACONF}[rt]"
             + ";[acat][rt]amix=inputs=2:duration=first:normalize=0[a]")
    vlabel = "vcat"
    for j, (ov, _) in enumerate(bands):
        at, dur = ov.get("at", 0.0), ov["duration"]
        graph += (f";[{n + 1 + j}:v]setpts=PTS-STARTPTS+{at}/TB[b{j}]"
                  f";[{vlabel}][b{j}]overlay=0:0:format=auto:"
                  f"enable='between(t,{at},{at + dur})'[vb{j}]")
        vlabel = f"vb{j}"
    graph += f";[{vlabel}]format=yuv420p[v]"

    inter = root / "exports" / f".{out_name}.pass1.mp4"
    final = root / "exports" / out_name
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in inputs:
        cmd += ["-i", p]
    cmd += ["-stream_loop", "-1", "-i", str(roomtone)]
    for _, src in bands:
        cmd += ["-i", src]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", str(inter)]
    subprocess.run(cmd, check=True)

    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(inter),
         "-af", "ebur128=framelog=verbose", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.findall(r"I:\s*(-?[\d.]+) LUFS", probe.stderr)
    i_lufs = float(m[-1]) if m else sys.exit(f"no ebur128 reading for {inter}")
    gain = -14.0 - i_lufs

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(inter),
         "-c:v", "copy", "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89",
         "-c:a", "aac", "-b:a", "192k", str(final)], check=True)
    inter.unlink()
    print(f"{final.name}: {t:.1f}s, measured {i_lufs} LUFS, gain {gain:+.1f}dB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="project root dir")
    ap.add_argument("pairs", nargs="*",
                    default=["cutlist-cards.json:cards-preview.mp4"],
                    help="CUTLIST:OUTPUT, cut list in resolve/, output in exports/")
    args = ap.parse_args()

    root = Path(args.project).expanduser().resolve()
    if not (root / "resolve").is_dir():
        sys.exit(f"not a project (no resolve/): {root}")
    roomtone = root / "graphics/cards/anim/roomtone.wav"
    if not roomtone.exists():
        sys.exit(f"no room-tone bed at {roomtone} — harvest it first "
                 "(cards must never sit on digital silence)")

    for pair in args.pairs:
        cutlist, _, out_name = pair.partition(":")
        if not out_name:
            sys.exit(f"expected CUTLIST:OUTPUT, got {pair!r}")
        build(root, roomtone, cutlist, out_name)


if __name__ == "__main__":
    main()
