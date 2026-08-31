#!/usr/bin/env python3
"""Re-transcribe short zones of a recording in isolation. One line per zone.

  snip.py FILE A-B [A-B...] [--pad 0.15]

Whisper's full-file pass hallucinates near long silences and omits um/uh
entirely, so any suspect zone (a warning from transcribe.py, a voiced blip
from gapcut --blips) gets decoded ALONE: extract the zone, transcribe it
with no prompt and no surrounding context, print what is actually there.

  54.00-64.00: and then that's it you can use that in uh um and
  99.85-100.29: (no speech)

The verdict stays with the caller: an um dies with its gap, a real word
becomes a --nocut/--tailv/--onset flag, empty audio confirms a
hallucination. ingest.py runs this over every suspect zone and files the
results in transcripts/X.audit.md; run it by hand for one-off checks
(editgate JUDGE lines, seam doubts).

Engine: mlx_whisper — run with the repo venv, <root>/.venv/bin/python.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL_REPO = "mlx-community/whisper-large-v3-turbo"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("zones", nargs="+", metavar="A-B")
    ap.add_argument("--pad", type=float, default=0.15,
                    help="context kept on each side of the zone")
    ap.add_argument("--language", default="en")
    args = ap.parse_args()

    try:
        import mlx_whisper
    except ImportError:
        sys.exit("mlx_whisper not importable. Run:\n"
                 "  <root>/.venv/bin/python snip.py FILE A-B...")

    src = Path(args.file).expanduser()
    with tempfile.TemporaryDirectory() as tmp:
        for zone in args.zones:
            a, b = (float(t) for t in zone.split("-"))
            start = max(0.0, a - args.pad)
            wav = Path(tmp) / "zone.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}",
                 "-t", f"{b - start + args.pad:.3f}", "-i", str(src),
                 "-ac", "1", "-ar", "16000", str(wav)],
                check=True)
            text = mlx_whisper.transcribe(
                str(wav), path_or_hf_repo=MODEL_REPO,
                language=args.language)["text"].strip()
            print(f"{a:.2f}-{b:.2f}: {text or '(no speech)'}")


if __name__ == "__main__":
    main()
