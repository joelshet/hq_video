#!/usr/bin/env python3
"""Build ultra-tight spine segments from a words.json. Filter: stdin -> stdout.

  ultracut.py --duration 294.02 [--drop-range 216.0-234.7] < x.words.json

Emits {"segments": [{"in", "out"}...], "edits": [...]} — the spine of an
"ultra" cut list. The caller owns overlays/markers (remap times through the
segments). Edit log also goes to stderr, one line per cut, for review.

What gets removed:
  - words inside any --drop-range (retakes; find them by reading the transcript)
  - filler words: um/uh anywhere; sentence-initial So/Okay; "you know" asides;
    immediate word stutters ("it's it's" -> keep the last)
  - silence: any inter-word gap > --gap-max, collapsed to a short breath

Seam safety: Whisper word boundaries are approximate. --pad-in keeps lead-in
before the next word's onset (clipping a word onset is far worse than leaving
40ms of a filler's tail, so forced cuts may overlap a dropped word's stamped
end by up to 50ms). --pad-out / --pad-out-sentence keep tails after kept words.
"""
import argparse
import json
import re
import sys

FILLER_ANY = re.compile(r"^(um|uh|erm)[,.]?$", re.I)
FILLER_SENTENCE_START = re.compile(r"^(So|Okay)[,.]?$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, required=True, help="source length, seconds")
    ap.add_argument("--drop-range", action="append", default=[], metavar="A-B",
                    help="drop all words starting in [A,B] (repeatable; retakes)")
    ap.add_argument("--keep", action="append", type=float, default=[], metavar="T",
                    help="exempt the filler word starting near T from dropping "
                         "(repeatable; the editorial override - a reaction "
                         "'Okay' or load-bearing 'So' is a beat, not filler)")
    ap.add_argument("--explain", action="store_true",
                    help="attach +-6 words of transcript context to each edit "
                         "so filler candidates can be judged from this output "
                         "alone, without re-reading the transcript")
    ap.add_argument("--gap-max", type=float, default=0.6)
    ap.add_argument("--pad-in", type=float, default=0.15)
    ap.add_argument("--pad-out", type=float, default=0.18)
    ap.add_argument("--pad-out-sentence", type=float, default=0.30)
    ap.add_argument("--head-pad", type=float, default=0.5)
    ap.add_argument("--tail-pad", type=float, default=1.3)
    args = ap.parse_args()

    words = json.load(sys.stdin)["words"]
    ranges = [tuple(map(float, r.split("-"))) for r in args.drop_range]

    def norm(w):
        return re.sub(r"[^a-z']", "", w.strip().lower())

    def context(i, span=6):
        lo, hi = max(0, i - span), min(len(words), i + span + 1)
        return " ".join(f">>{words[j]['word'].strip()}<<" if j == i
                        else words[j]["word"].strip() for j in range(lo, hi))

    drop, edits = set(), []
    for i, x in enumerate(words):
        ws = x["word"].strip()
        if any(a <= x["start"] <= b for a, b in ranges):
            drop.add(i)
            continue
        if any(abs(x["start"] - k) <= 0.2 for k in args.keep):
            edits.append(("kept", x["start"], ws, i))
            continue
        if FILLER_ANY.match(ws):
            drop.add(i); edits.append(("filler", x["start"], ws, i))
        elif FILLER_SENTENCE_START.match(ws):
            starts_sentence = (i == 0
                               or re.search(r"[.!?]$", words[i - 1]["word"].strip())
                               or x["start"] - words[i - 1]["end"] > 0.5)
            if starts_sentence:
                drop.add(i); edits.append(("filler", x["start"], ws, i))
        elif norm(ws) == "know" and i and norm(words[i - 1]["word"]) == "you":
            drop.update((i - 1, i))
            edits.append(("filler", words[i - 1]["start"], "you know", i))
        elif (i and norm(ws) and norm(ws) == norm(words[i - 1]["word"])
              and i - 1 not in drop and x["start"] - words[i - 1]["end"] < 0.4):
            drop.add(i - 1)  # stutter: keep the LAST instance
            edits.append(("stutter", words[i - 1]["start"], f"{ws} {ws}", i - 1))
    for a, b in ranges:
        edits.append(("retake", a, f"dropped words in {a}-{b}", None))

    kept, buf, pairs = [], [], []
    for i, x in enumerate(words):
        if i in drop:
            buf.append(x)
        else:
            pairs.append((x, buf))
            kept.append(x)
            buf = []
    if not kept:
        sys.exit("nothing left after drops")

    segs, log = [], []
    cur = max(0.0, kept[0]["start"] - args.head_pad)
    prev = pairs[0][0]
    for x, dropped in pairs[1:]:
        gap = x["start"] - prev["end"]
        if gap > args.gap_max or dropped:
            pad_out = (args.pad_out_sentence
                       if re.search(r"[.!?]$", prev["word"].strip()) else args.pad_out)
            cut_from = prev["end"] + pad_out
            cut_to = x["start"] - args.pad_in
            if dropped:
                cut_from = min(cut_from, dropped[0]["start"])
                # never clip the next word's onset to protect a filler's tail
                cut_to = max(cut_to, dropped[-1]["end"] - 0.05)
            cut_to = min(cut_to, x["start"])
            if cut_to - cut_from > 0.06 and cut_from > cur:
                segs.append({"in": round(cur, 2), "out": round(cut_from, 2)})
                what = " ".join(d["word"].strip() for d in dropped) or f"{gap:.2f}s gap"
                log.append((cut_from, round(cut_to - cut_from, 2), what))
                cur = cut_to
        prev = x
    segs.append({"in": round(cur, 2),
                 "out": round(min(args.duration, prev["end"] + args.tail_pad), 2)})

    for t, d, what in log:
        print(f"cut at {t:8.2f}  -{d:6.2f}s  {what}", file=sys.stderr)
    total = sum(s["out"] - s["in"] for s in segs)
    print(f"{len(segs)} segments, {len(segs)-1} cuts, {total:.1f}s kept "
          f"of {args.duration}s", file=sys.stderr)
    def edit_obj(k, t, w, i):
        e = {"kind": k, "at": t, "what": w}
        if args.explain and i is not None:
            e["context"] = context(i)
        return e

    json.dump({"segments": segs,
               "edits": [edit_obj(*e) for e in sorted(edits, key=lambda e: e[1])]},
              sys.stdout, indent=1)


if __name__ == "__main__":
    main()
