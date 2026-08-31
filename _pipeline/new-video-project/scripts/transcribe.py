#!/usr/bin/env python3
"""Transcribe media files with mlx-whisper (Apple Silicon GPU). One job:
audio in, canonical word timestamps out.

For each FILE, writes FILE.raw.words.json beside it (or into -o DIR):
  {"source": "<filename>", "language": "en", "words": [{word,start,end}, ...],
   "warnings": [{kind, start, end, note}, ...]}

The raw file is exactly what Whisper heard and is IMMUTABLE: corrections
are data applied downstream (vocabfix.py regexes, wordfix.py fix ops) by
derive.py, which produces the working FILE.words.json. Diff raw against
derived to see every change.

Warnings are the self-audit against silencedetect — "hallucination" (words
inside real silence) and "dropped" (voiced audio with no words). They ride
in the JSON so downstream tools (ingest's audit step) can snippet-verify
each zone without re-deriving it; they also print to stderr.

Everything else is a downstream filter:
  vocabfix.py  — apply vocab corrections to a words.json
  words2.py    — render words.json as srt / beats / reading / txt / pauses

A vocab file (--vocab, repeatable) seeds Whisper's initial prompt so product
names and jargon are spelled right the first time; corrections belong to
vocabfix, not here. Prompt style matters: full sentences keep casing and
punctuation intact through long recordings (Whisper reads ~224 prompt tokens).

Usage:
  transcribe.py FILE... [--vocab vocab.json] [--language en] [-o DIR]
Engine: mlx_whisper — run with the repo venv, <root>/.venv/bin/python.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from common import read_json

# Cached under ~/.cache/huggingface. ~1 min per 13 min of video.
#
# Engine bake-off, 2026-08-14, on a 13-minute demo recording (known ground
# truth: two snippet-confirmed fillers, a 6-word tail hallucination, the
# product names, the -30dB/-35dB maps). Six locally-installed configs:
#   THIS ONE          full content, 20/20 product names, 16s. Costs: omits
#                     every um/uh, and prompt + conditioning invent a
#                     "Thank you." tail (the audit catches it every time).
#   mlx, no prompt    no filler gain, 10 mangled names. Pointless.
#   faster-whisper large-v3-turbo, no prompt: the ONLY config that writes
#                     fillers (7), but 15 mangled names and 2x slower — and
#                     5 of its 7 sit in zones gapcut --blips ALREADY flags;
#                     the other 2 no isolated decode can confirm.
#   faster-whisper + initial_prompt/hotwords: CATASTROPHIC (0.363 similarity,
#                     229 words wrong or missing). Never prompt this engine.
#   faster-whisper + vad_filter: drops real speech (0.664). Same failure as
#                     the mlx VAD attempt below.
#   faster-whisper medium: slower, no filler gain, nothing better.
# Conclusion: the engine is not the bottleneck — the audit layer is what
# finds fillers, and it already finds them. Swapping engines trades product
# names for duplicated coverage. Re-run the bake-off before revisiting.
MODEL_REPO = "mlx-community/whisper-large-v3-turbo"


def load_vocab(paths: list) -> dict:
    """Merge vocab files in order (later wins for style, unions terms)."""
    vocab = {"prompt_style": "", "prompt_terms": []}
    for path in paths:
        data = read_json(path, "vocab file")
        vocab["prompt_style"] = data.get("prompt_style") or vocab["prompt_style"]
        vocab["prompt_terms"] += data.get("prompt_terms", [])
    return vocab


def build_prompt(vocab: dict) -> str | None:
    terms = ", ".join(dict.fromkeys(vocab["prompt_terms"]))
    if not terms:
        return vocab["prompt_style"] or None
    style = vocab["prompt_style"] or "This is a product demo."
    return f"{style} Terms used: {terms}."


def detect_silences(wav: Path, noise_db: int, min_dur: float) -> list:
    """ffmpeg silencedetect -> [(start, end), ...] over the whole file."""
    out = subprocess.run(
        ["ffmpeg", "-i", str(wav), "-af",
         f"silencedetect=n={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
    if len(ends) < len(starts):  # file ends inside a silence
        ends.append(wav_duration(wav))
    return list(zip(starts, ends))


def wav_duration(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def audit_words(wav: Path, words: list) -> list:
    """Warn where transcript and audio disagree — the two Whisper failure
    modes are words inside silence (hallucination) and voiced audio with no
    words (dropped speech). Warnings only; the human judges."""
    warnings = []
    silences = detect_silences(wav, -35, 1.0)
    dur = wav_duration(wav)
    # Hallucinated words live mostly inside real silence. >60% of a word's
    # duration in silence beats a fully-inside test: Whisper's stamps drift
    # ~0.1s, and a fake word straddling a silence edge must still flag.
    for s, e in silences:
        inside = []
        for w in words:
            length = max(w["end"] - w["start"], 0.01)
            overlap = min(e, w["end"]) - max(s, w["start"])
            if overlap / length > 0.6:
                inside.append(w)
        if inside:
            text = " ".join(w["word"].strip() for w in inside[:6])
            more = f" (+{len(inside) - 6} more)" if len(inside) > 6 else ""
            note = f"{len(inside)} word(s) inside silence: {text!r}{more}"
            warnings.append({"kind": "hallucination", "start": round(s, 2),
                             "end": round(e, 2), "note": note})
            print(f"  WARNING: {note} at {s:.1f}-{e:.1f}s", file=sys.stderr)
    # Dropped speech: a wordless stretch >=1.5s WITHIN voiced audio. Checked
    # per gap, not per span — a drop at the head of a long voiced span must
    # not be excused by words later in the same span.
    cursor = 0.0
    voiced = []
    for s, e in silences:
        if s > cursor:
            voiced.append((cursor, s))
        cursor = e
    if dur > cursor:
        voiced.append((cursor, dur))
    for s, e in voiced:
        span_words = sorted((w for w in words
                             if w["start"] < e and w["end"] > s),
                            key=lambda w: w["start"])
        gap_from = s
        for w in span_words + [{"start": e, "end": e}]:
            if w["start"] - gap_from >= 1.5:
                warnings.append({"kind": "dropped", "start": round(gap_from, 2),
                                 "end": round(w["start"], 2),
                                 "note": "voiced audio has no words"})
                print(f"  WARNING: voiced audio {gap_from:.1f}-"
                      f"{w['start']:.1f}s has no words (dropped speech?)",
                      file=sys.stderr)
            gap_from = max(gap_from, w["end"])
    return warnings


def transcribe_file(src: Path, model_repo: str, language: str, prompt: str | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-ac", "1", "-ar", "16000", str(wav)],
            check=True,
        )
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(wav),
            path_or_hf_repo=model_repo,
            language=language,
            word_timestamps=True,
            initial_prompt=prompt,
            # Silence is where Whisper invents "Thank you." / "um um um" loops.
            # (Tried VAD clip_timestamps 2026-08-12: fixed the silence
            # hallucinations but clip boundaries caused a repetition loop, a
            # dropped negation, and casing loss — worse than the disease.
            # Whole-file decode + audit_words warnings is the working shape.)
            hallucination_silence_threshold=2.0,
            # Keep conditioning on: it is what carries the prompt's casing
            # through a 13-minute take. Temperature fallback breaks real loops.
            condition_on_previous_text=True,
        )
        words = [w for seg in result["segments"] for w in (seg.get("words") or [])]
        result["warnings"] = audit_words(wav, words)
        return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="media files to transcribe")
    ap.add_argument("--vocab", action="append", default=[],
                    help="vocab.json to seed the prompt (repeatable, later wins)")
    ap.add_argument("--language", default="en")
    ap.add_argument("-o", "--out-dir", default=None,
                    help="write words.json here instead of beside each input")
    args = ap.parse_args()

    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        sys.exit("mlx_whisper not importable. Run this script with the venv that "
                 "has it:\n  <root>/.venv/bin/python transcribe.py FILE...")

    prompt = build_prompt(load_vocab(args.vocab))

    for f in args.files:
        src = Path(f).expanduser().resolve()
        if not src.is_file():
            sys.exit(f"not a file: {src}")
        print(f"Transcribing {src.name} ...", file=sys.stderr)
        result = transcribe_file(src, MODEL_REPO, args.language, prompt)

        words = []
        for seg in result["segments"]:
            for w in (seg.get("words") or []):
                words.append({"word": w["word"].strip(),
                              "start": round(w["start"], 3),
                              "end": round(w["end"], 3)})

        out_dir = Path(args.out_dir).expanduser() if args.out_dir else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{src.stem}.raw.words.json"
        out.write_text(json.dumps(
            {"source": src.name, "language": result.get("language", args.language),
             "words": words, "warnings": result["warnings"]}, indent=1),
            encoding="utf-8")
        print(f"  -> {out} ({len(words)} words)", file=sys.stderr)
        print(out)


if __name__ == "__main__":
    main()
