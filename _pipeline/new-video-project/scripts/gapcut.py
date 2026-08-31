#!/usr/bin/env python3
"""Collapse dead air on AUDIO evidence, not word stamps. Filter: words.json
on stdin -> JSON array of kept [in, out] segments on stdout.

  gapcut.py FOOTAGE --head T --end T [--drop A-B]... [--nocut T]...
            [--onset T=ON]... [--tailv T=END]... [--protect A-B]...
            [--floor 0.30] [--floor-mid 0.18] [--map30 F] [--map35 F]
  gapcut.py FOOTAGE --blips [--map30 F]

Why this tool exists (2026-08-11, the sheets video): Whisper stretches
word stamps across pauses, omits um/uh entirely, and jitters onsets both
ways, so stamp-gap collapsing ships dead air and stamp-guarded cuts clip
onsets. The anchor that works is the merged -30dB silence run: its start
IS the voice end (breathy decay dies with the gap), its end IS the next
onset. -35dB evidence sharpens the in-point pad.

Policy (2026-08-12): the fluency reference is the transcript
itself. Within a sentence the speaker's own inter-word gap is ~0 (median
0.00s in every recording), so a mid-sentence pause is an anomaly.
Collapse every mid-sentence gap >= FLOOR_MID (default 0.18s) to
near-zero residual: out = voice_end + 0.03, in = onset - 0.03 when
-35dB confirms the onset, - 0.06 when only -30dB does. A gap after
terminal punctuation (. ! ?) is a sentence beat: collapse at >= FLOOR
(default 0.30s) but keep a breath: out = voice_end + 0.05, in =
onset - 0.12 verified / - 0.16 not. The words on stdin supply the
sentence boundaries; a zone with no word within 0.6s (dead air, dropped
takes) gets the sentence-beat treatment.

The judgment stays with the caller, expressed as flags:
  --drop A-B     editorial cut with verified bounds (retakes, fillers,
                 verified ums); interval-subtracted from runs, so partial
                 overlaps trim instead of skip
  --nocut T      never cut the run starting at T (kept reactions whose
                 shoulders read as silence)
  --tailv T=END  the run at T begins with a drawled word tail; voice
                 truly ends at END (snippet-verified)
  --onset T=ON   the run at T ends before the real onset; use ON
  --protect A-B  no machine cuts land inside (soft words that dip under
                 -30dB mid-word, emotional closes)
  --head T       first segment starts at T (speech onset - ~0.2)
  --end T        last segment ends at T (include the outro hold)
  --blips        do not cut; print voiced ISLANDS — 0.15-1.0s of sound
                 with a silence run >= FLOOR_MID on BOTH sides (an um, a
                 mumble, a soft word sitting alone in a pause; attached
                 speech is the transcript's job, and a filler glued to its
                 sentence is ultracut's) as "START END BLIP_START BLIP_END"
                 lines (START-END spans both flanking silences), then exit.
                 A missed um SHIPS: Whisper omits um/uh, so neither the
                 re-transcription diff nor the residual gate can see one.
                 Snippet-verify each island (a blip is a word until proven
                 otherwise), then cut with the verdicts as flags.
                 --head/--end are not needed here.

Silence maps come from ffmpeg silencedetect (-30dB:d=0.10 and
-35dB:d=0.25). ingest.py caches them as transcripts/X.sil30.txt and
X.sil35.txt — pass those via --map30/--map35 to skip the ffmpeg runs;
without the flags the tool runs ffmpeg itself. Runs separated by blips
< 0.15s are merged, so a sub-word blip (most ums) dies with its gap.
"""
import argparse
import bisect
import json
import re
import subprocess
import sys


def detect(footage, thresh, dur):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", footage, "-af",
         f"silencedetect=n={thresh}dB:d={dur}", "-f", "null", "-"],
        capture_output=True, text=True)
    return parse_map(r.stderr)


def parse_map(txt):
    return list(zip((float(m) for m in re.findall(r"silence_start: ([-\d.]+)", txt)),
                    (float(m) for m in re.findall(r"silence_end: ([\d.]+)", txt))))


def kv(pairs):
    out = {}
    for p in pairs:
        k, v = p.split("=")
        out[round(float(k), 2)] = float(v)
    return out


def rng(pairs):
    return [tuple(map(float, p.split("-"))) for p in pairs]


def subtract(run, ranges):
    frags = [tuple(run)]
    for a, b in ranges:
        nxt = []
        for ss, se in frags:
            if b <= ss or a >= se:
                nxt.append((ss, se)); continue
            if ss < a:
                nxt.append((ss, a))
            if b < se:
                nxt.append((b, se))
        frags = nxt
    return frags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("footage")
    ap.add_argument("--drop", action="append", default=[], metavar="A-B")
    ap.add_argument("--nocut", action="append", type=float, default=[], metavar="T")
    ap.add_argument("--tailv", action="append", default=[], metavar="T=END")
    ap.add_argument("--onset", action="append", default=[], metavar="T=ON")
    ap.add_argument("--protect", action="append", default=[], metavar="A-B")
    ap.add_argument("--head", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--floor", type=float, default=0.30)
    ap.add_argument("--floor-mid", dest="floor_mid", type=float, default=0.18)
    ap.add_argument("--map30", help="cached silencedetect -30dB output")
    ap.add_argument("--map35", help="cached silencedetect -35dB output")
    ap.add_argument("--blips", action="store_true")
    args = ap.parse_args()

    data = json.load(sys.stdin)
    words = data["words"] if isinstance(data, dict) else data
    ends = sorted((w["end"], w["word"].strip().rstrip('"\')')) for w in words)

    def sentence_beat(t):
        # the word whose end sits nearest t decides mid-sentence vs beat
        i = bisect.bisect_left(ends, (t,))
        near = min(ends[max(0, i - 1):i + 1], key=lambda c: abs(c[0] - t),
                   default=None)
        if near is None or abs(near[0] - t) > 0.6:
            return True
        return near[1].endswith((".", "!", "?"))

    s30 = parse_map(open(args.map30).read()) if args.map30 else detect(args.footage, -30, 0.10)

    if args.blips:
        # voiced islands: short sound flanked by real silence on both sides
        for (ss, se), (nss, nse) in zip(s30, s30[1:]):
            if (0.15 <= nss - se < 1.0 and se - ss >= args.floor_mid
                    and nse - nss >= args.floor_mid):
                print(f"{ss:.2f} {nse:.2f} {se:.2f} {nss:.2f}")
        return
    if args.head is None or args.end is None:
        ap.error("--head and --end are required (except with --blips)")

    s35 = parse_map(open(args.map35).read()) if args.map35 else detect(args.footage, -35, 0.25)

    merged = [list(s30[0])]
    for a, b in s30[1:]:
        if a - merged[-1][1] < 0.15:
            merged[-1][1] = b
        else:
            merged.append([a, b])

    drops, protect = rng(args.drop), rng(args.protect)
    tailv, onset_ovr = kv(args.tailv), kv(args.onset)
    nocut = {round(t, 2) for t in args.nocut}

    cuts = list(drops)
    n_mid = n_beat = 0
    for run in merged:
        if run[1] <= args.head or run[0] >= args.end - 1.4:
            continue
        if any(a <= run[0] <= b for a, b in protect):
            continue
        for ss, se in subtract(run, drops):
            key = round(ss, 2)
            if key in nocut:
                continue
            ve = tailv.get(key, ss)
            mid = not sentence_beat(ve)
            if se - ve < (args.floor_mid if mid else args.floor):
                continue
            verified = any(abs(e - se) < 0.25 for _, e in s35)
            if mid:
                out = ve + (0.04 if key in tailv else 0.03)
                pad = 0.03 if verified else 0.06
                ovr_pad = 0.03
            else:
                out = ve + (0.06 if key in tailv else 0.05)
                pad = 0.12 if verified else 0.16
                ovr_pad = 0.12
            inp = onset_ovr.get(key, se) - (ovr_pad if key in onset_ovr else pad)
            if inp - out < 0.06:
                continue
            cuts.append((round(out, 2), round(inp, 2)))
            n_mid, n_beat = n_mid + mid, n_beat + (not mid)
    cuts.sort()

    segs, cur = [], args.head
    for o, ip in cuts:
        if o <= cur:
            cur = max(cur, ip); continue
        segs.append((round(cur, 2), o))
        cur = ip
    segs.append((round(cur, 2), args.end))
    segs = [(a, b) for a, b in segs if b - a > 0.12]
    json.dump([[a, b] for a, b in segs], sys.stdout)
    sys.stdout.write("\n")
    total = sum(b - a for a, b in segs)
    print(f"{len(segs)} segments, {total:.1f}s "
          f"({n_mid} mid-sentence cuts, {n_beat} sentence-beat cuts)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
