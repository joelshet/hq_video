#!/usr/bin/env python3
"""Apply per-video transcript fixes. Filter: stdin words.json -> stdout.

  wordfix.py --fixes X.fixes.json

Fixes are DATA — the per-video counterpart of the global vocab regexes.
The fixes file is a JSON list of ops, each carrying its reason; it IS the
record of transcript judgment, the way make_cutlists.py is the record of
cut judgment:

[
 {"op": "delete", "start": 137.2, "end": 139.05,
  "why": "hallucinated 'Thank you.' — audit snippet says (no speech)"},
 {"op": "insert", "words": [{"word": "Go", "start": 38.12, "end": 38.3}],
  "why": "dropped speech recovered by snip"},
 {"op": "replace", "start": 12.3, "end": 12.9,
  "words": [{"word": "Acme", "start": 12.31, "end": 12.88}],
  "why": "misheard as 'well sink'; snippet-verified"}
]

delete   removes words whose midpoint lies in [start, end]
insert   splices the given words in at their timestamps
replace  delete then insert
A missing --fixes file is a passthrough (the normal state early on).
Never edit words.json by hand: it is derived (see derive.py), and a fix
recorded here survives re-transcription.
"""
import argparse
import json
import sys
from pathlib import Path


def apply(words: list, ops: list) -> list:
    for op in ops:
        kind = op["op"]
        if kind not in ("delete", "insert", "replace"):
            sys.exit(f"wordfix: unknown op {kind!r}")
        if kind in ("delete", "replace"):
            a, b = op["start"], op["end"]
            words = [w for w in words
                     if not a <= (w["start"] + w["end"]) / 2 <= b]
        if kind in ("insert", "replace"):
            words += [{"word": w["word"], "start": w["start"], "end": w["end"]}
                      for w in op["words"]]
    return sorted(words, key=lambda w: w["start"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixes", required=True,
                    help="X.fixes.json (missing file = passthrough)")
    args = ap.parse_args()

    doc = json.load(sys.stdin)
    path = Path(args.fixes).expanduser()
    if path.exists():
        ops = json.loads(path.read_text())
        doc["words"] = apply(doc.get("words", []), ops)
        print(f"wordfix: {len(ops)} op(s) applied", file=sys.stderr)
    json.dump(doc, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
