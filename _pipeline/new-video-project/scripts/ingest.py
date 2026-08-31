#!/usr/bin/env python3
"""Phase-1 driver: everything mechanical between "recording done" and the
edit. One command, no judgment calls. When it finishes, EVERY piece of
evidence the edit needs is a file — the edit sitting reads them once and
writes cut lists once, with no tool runs in between.

  ingest.py [INBOX_FOLDER] [--slug SLUG] [--mask x0:y0:x1:y1]... [--vocab V]...

Given a "YYYY-MM-DD Topic" folder (default: newest folder in <root>/_inbox,
or loose inbox files), it scaffolds Projects/<slug>/, moves media to
footage/, copies the template .drp, and writes per clip X into transcripts/:

  X.raw.words.json   exactly what Whisper heard — IMMUTABLE evidence
  X.words.json       derived working transcript (raw -> vocabfix -> wordfix;
                     rebuild any time with derive.py; per-video judgments
                     live in X.fixes.json, never in hand edits)
  X.srt / X.reading.md / X.pauses.json   pinned editor formats
  X.activity.json    screen-activity bursts (video clips; --mask overrides
                     the standard PIP+chrome masks)
  X.sil30.txt        silencedetect -30dB:d=0.10 map (gapcut --map30)
  X.sil35.txt        silencedetect -35dB:d=0.25 map (gapcut --map35)
  X.candidates.json  filler/stutter candidates with transcript context
                     (ultracut --explain), ready to judge
  X.audit.md         speech onset/end numbers + every suspect zone
                     (transcribe warnings, gapcut --blips) re-transcribed
                     in isolation by snip.py, ready to verdict
  X.contact.jpg      timestamped frame grid (layout, PIP, faces)

Editorial work (sections, concepts, cut lists) stays with the agent — this
script only prepares the evidence.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from common import ffprobe_media

ROOT = Path(__file__).resolve().parents[3]
VENV_PY = ROOT / ".venv" / "bin" / "python"
if not VENV_PY.exists():
    VENV_PY = Path(sys.executable)
MEDIA_EXTS = {".mov", ".mp4", ".mkv", ".m4v", ".wav"}
DEFAULT_MASKS = ["1449:615:1881:1045", "0:0:1920:120"]


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def capture(cmd, stdin_text=None):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    return subprocess.run([str(c) for c in cmd], input=stdin_text,
                          capture_output=True, text=True, check=True).stdout


def kebab(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def derive_slug(folder: Path, media: list) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ _-]*(.*)", folder.name)
    if m and m.group(2):
        return f"{m.group(1)}-{kebab(m.group(2))}"
    if m:
        return m.group(1)
    date = datetime.date.fromtimestamp(media[0].stat().st_mtime).isoformat()
    topic = kebab(folder.name) or "untitled"
    return f"{date}-{topic}"


def silencemap(src: Path, db: int, dur: float, out: Path) -> str:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af",
         f"silencedetect=n={db}dB:d={dur}", "-f", "null", "-"],
        capture_output=True, text=True)
    out.write_text(r.stderr)
    print(f"+ silencedetect {db}dB:d={dur} -> {out.name}", file=sys.stderr)
    return r.stderr


def speech_bounds(map_text: str, duration: float) -> tuple:
    """(onset, last_voice): where speech starts and ends per this map."""
    starts = [float(m) for m in re.findall(r"silence_start: ([-\d.]+)", map_text)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", map_text)]
    onset = ends[0] if starts and starts[0] <= 0.1 and ends else 0.0
    tail = (starts and
            (len(ends) < len(starts) or duration - ends[-1] < 0.2))
    return round(onset, 2), round(starts[-1] if tail else duration, 2)


def build_audit(f: Path, wj: Path, sil30: Path, sil35: Path,
                scripts: Path, info: dict) -> tuple:
    doc = json.loads(wj.read_text())
    words = doc["words"]
    warnings = doc.get("warnings", [])

    blip_out = capture(["python3", scripts / "gapcut.py", f, "--blips",
                        "--map30", sil30], stdin_text=json.dumps(doc))
    blips = []
    for line in blip_out.splitlines():
        zs, ze, bs, be = (float(t) for t in line.split())
        if any(w["start"] <= bs and be <= w["end"] for w in warnings):
            continue  # already covered by a warning zone
        blips.append((zs, ze, bs, be))

    zones = ([(w["start"], w["end"]) for w in warnings]
             + [(bs, be) for _, _, bs, be in blips])
    snips = {}
    if zones:
        out = capture([VENV_PY, scripts / "snip.py", f,
                       *(f"{a:.2f}-{b:.2f}" for a, b in zones)])
        for line in out.splitlines():
            zone, _, text = line.partition(": ")
            snips[zone] = text

    def snip_of(a, b):
        return snips.get(f"{a:.2f}-{b:.2f}", "(snip failed)")

    def main_pass(a, b):
        hit = [w["word"].strip() for w in words
               if a - 0.05 <= (w["start"] + w["end"]) / 2 <= b + 0.05]
        return " ".join(hit) if hit else "(nothing — untranscribed)"

    dur = info["duration"]
    on35, end35 = speech_bounds(sil35.read_text(), dur)
    on30, end30 = speech_bounds(sil30.read_text(), dur)
    L = [f"# {f.stem} — audio audit",
         f"file {dur:.2f}s; speech -35dB onset {on35} last voice {end35}; "
         f"-30dB onset {on30} last voice {end30}",
         "",
         "Verdict EVERY zone while reading, before authoring cuts: an um or",
         "noise dies with its gap; a real word becomes --nocut/--tailv/",
         "--onset; '(no speech)' confirms a hallucination — record a delete",
         f"op in {f.stem}.fixes.json and re-run derive.py (words.json is",
         "derived, never hand-edited; raw.words.json is immutable).",
         "",
         "## transcribe warnings"]
    if not warnings:
        L.append("(none)")
    for w in warnings:
        L += [f"- {w['start']:.2f}-{w['end']:.2f} {w['kind']}: {w['note']}",
              f"  isolated: {snip_of(w['start'], w['end'])}"]
    L += ["", "## voiced blips in silence (gapcut --blips)"]
    if not blips:
        L.append("(none)")
    for zs, ze, bs, be in blips:
        L += [f"- {bs:.2f}-{be:.2f} in zone {zs:.2f}-{ze:.2f}; "
              f"main pass: {main_pass(bs, be)}",
              f"  isolated: {snip_of(bs, be)}"]
    (wj.parent / f"{f.stem}.audit.md").write_text("\n".join(L) + "\n")
    return len(warnings), len(blips)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", help="inbox folder (default: newest in _inbox)")
    ap.add_argument("--slug", help="override the derived YYYY-MM-DD-topic slug")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--mask", action="append", default=[],
                    help="activity mask x0:y0:x1:y1 (default: standard PIP+chrome)")
    ap.add_argument("--vocab", action="append", default=[],
                    help="extra vocab.json merged over _templates/vocab.json")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    scripts = Path(__file__).parent
    inbox = root / "_inbox"

    if args.folder:
        src = Path(args.folder).expanduser()
    else:
        folders = sorted((d for d in inbox.iterdir() if d.is_dir()),
                         key=lambda d: d.name) if inbox.exists() else []
        src = folders[-1] if folders else inbox
    media = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in MEDIA_EXTS) if src.exists() else []
    if not media:
        sys.exit(f"no media in {src} — ask the user where the recording is")

    slug = args.slug or derive_slug(src, media)
    P = root / "Projects" / slug
    for d in ("footage", "transcripts", "graphics/cards/anim", "resolve", "exports"):
        (P / d).mkdir(parents=True, exist_ok=True)

    footage = []
    for m in media:
        dest = P / "footage" / m.name
        m.rename(dest)
        footage.append(dest)
    if src != inbox and not any(src.iterdir()):
        src.rmdir()
    drp = P / "resolve" / f"{slug}.drp"
    template = next(iter((root / "_templates").glob("*.drp")), None)
    if template and not drp.exists():
        drp.write_bytes(template.read_bytes())

    tdir = P / "transcripts"
    if args.vocab:
        # extra vocab becomes part of the project so derive.py reproduces it
        merged = {"prompt_terms": [], "corrections": {}}
        for v in map(Path, args.vocab):
            data = json.loads(v.expanduser().read_text())
            merged["prompt_terms"] += data.get("prompt_terms", [])
            merged["corrections"].update(data.get("corrections", {}))
            if data.get("prompt_style"):
                merged["prompt_style"] = data["prompt_style"]
        (tdir / "vocab.json").write_text(json.dumps(merged, indent=1))

    vocab_flags = ["--vocab", root / "_templates" / "vocab.json"]
    if (tdir / "vocab.json").exists():
        vocab_flags += ["--vocab", tdir / "vocab.json"]
    run([VENV_PY, scripts / "transcribe.py", *footage, *vocab_flags, "-o", tdir])

    masks = args.mask or DEFAULT_MASKS
    report = []
    for f in footage:
        run(["python3", scripts / "derive.py", P, f.stem, "--root", root])
        wj = tdir / f"{f.stem}.words.json"

        info = ffprobe_media(f)
        if info["has_video"]:
            mask_flags = [x for m in masks for x in ("--mask", m)]
            with open(tdir / f"{f.stem}.activity.json", "w") as o:
                run(["python3", scripts / "activity.py", f, *mask_flags],
                    stdout=o)
            run(["python3", scripts / "contactsheet.py", f,
                 "-o", tdir / f"{f.stem}.contact.jpg"])

        sil30 = tdir / f"{f.stem}.sil30.txt"
        sil35 = tdir / f"{f.stem}.sil35.txt"
        silencemap(f, -30, 0.10, sil30)
        silencemap(f, -35, 0.25, sil35)

        cand = json.loads(capture(
            ["python3", scripts / "ultracut.py", "--explain",
             "--duration", f"{info['duration']:.2f}"],
            stdin_text=wj.read_text()))["edits"]
        (tdir / f"{f.stem}.candidates.json").write_text(json.dumps(cand, indent=1))

        n_warn, n_blip = build_audit(f, wj, sil30, sil35, scripts, info)

        n_words = len(json.loads(wj.read_text())["words"])
        report.append((f.stem, info["duration"], n_words,
                       len(cand), n_warn + n_blip))

    print(f"\n{P}")
    for stem, dur, n, nc, nz in report:
        print(f"  {stem}: {dur:.1f}s, {n} words, {nc} filler candidates, "
              f"{nz} audit zones")
    print("\nMaterials complete. Follow _pipeline/new-video-project/EDIT.md: "
          "read ALL of transcripts/ once (reading.md, audit.md, "
          "candidates.json, pauses.json, activity.json, contact.jpg), then "
          "author resolve/make_cutlists.py in the same sitting.")


if __name__ == "__main__":
    main()
