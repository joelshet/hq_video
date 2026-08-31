#!/usr/bin/env python3
"""Derive the working transcript from the immutable raw one.

  derive.py PROJECT [STEM...]

For each transcripts/X.raw.words.json (all of them, or just the named
stems), runs the correction chain and re-renders the editor formats:

  X.raw.words.json  what Whisper heard; never modified
    -> vocabfix     _templates/vocab.json (+ transcripts/vocab.json if the
                    project has extra vocab)
    -> wordfix      transcripts/X.fixes.json (per-video judgment as data)
    -> X.words.json + X.srt / X.reading.md / X.pauses.json

Corrections are data, so `diff` of raw against derived shows every change,
re-running is idempotent, and a re-transcription never loses judgments.
Edit vocab.json or X.fixes.json, re-run this, done — never words.json.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

FORMATS = [("srt", ".srt"), ("reading", ".reading.md"), ("pauses", ".pauses.json")]


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--root",
                    default=str(Path(__file__).resolve().parents[3]))
    args = ap.parse_args()

    P = Path(args.project).expanduser().resolve()
    root = Path(args.root).expanduser()
    scripts = Path(__file__).parent
    tdir = P / "transcripts"

    vocab_flags = ["--vocab", root / "_templates" / "vocab.json"]
    if (tdir / "vocab.json").exists():
        vocab_flags += ["--vocab", tdir / "vocab.json"]

    raws = ([tdir / f"{s}.raw.words.json" for s in args.stems]
            or sorted(tdir.glob("*.raw.words.json")))
    if not raws:
        sys.exit(f"no *.raw.words.json in {tdir}")
    for raw in raws:
        if not raw.exists():
            sys.exit(f"not found: {raw}")
        stem = raw.name.removesuffix(".raw.words.json")
        out = tdir / f"{stem}.words.json"
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as mid:
            with open(raw) as i:
                run(["python3", scripts / "vocabfix.py", *vocab_flags],
                    stdin=i, stdout=mid)
            mid.seek(0)
            with open(out, "w") as o:
                run(["python3", scripts / "wordfix.py",
                     "--fixes", tdir / f"{stem}.fixes.json"],
                    stdin=mid, stdout=o)
        for fmt, ext in FORMATS:
            with open(out) as i, open(tdir / f"{stem}{ext}", "w") as o:
                run(["python3", scripts / "words2.py", fmt], stdin=i, stdout=o)
        print(f"{out.name} derived (+{', '.join(e for _, e in FORMATS)})")


if __name__ == "__main__":
    main()
