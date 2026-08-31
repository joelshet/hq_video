#!/usr/bin/env python3
"""Apply vocab corrections to a words.json. Filter: stdin -> stdout.

  vocabfix.py --vocab _templates/vocab.json < x.words.json > fixed.words.json

Corrections are regex -> replacement pairs under "corrections" in each vocab
file (repeatable flag; later files override earlier keys). A correction can
span several words ("meta objects" -> "metaobjects"); timestamps stay anchored
to the real audio when word counts change.
"""
import argparse
import json
import re
import sys

from common import read_json


def apply_corrections(text: str, corrections: dict) -> str:
    for pattern, repl in corrections.items():
        text = re.sub(pattern, repl, text)
    return text


def correct_words(words: list, corrections: dict) -> list:
    """Apply corrections across word runs, preserving timestamps.

    Match against the joined text and rebuild the run. When the word count
    changes, merged tokens keep the time span of the words they swallowed.
    """
    if not words or not corrections:
        return words
    joined = " ".join(w["word"].strip() for w in words)
    corrected = apply_corrections(joined, corrections)
    new_tokens = corrected.split()
    if len(new_tokens) == len(words):  # common case: 1:1, keep exact times
        return [{**w, "word": t} for w, t in zip(words, new_tokens)]

    out, i = [], 0
    for token in new_tokens:
        if i >= len(words):
            break
        start, end, consumed = words[i]["start"], words[i]["end"], 1
        # A merged token ("metaobjects") swallows the following words whose
        # letters it still contains; compare letters-only to ignore punctuation.
        key = re.sub(r"\W", "", token).lower()
        acc = re.sub(r"\W", "", words[i]["word"]).lower()
        while acc and key.startswith(acc) and acc != key and i + consumed < len(words):
            nxt = re.sub(r"\W", "", words[i + consumed]["word"]).lower()
            if not key.startswith(acc + nxt):
                break
            acc += nxt
            end = words[i + consumed]["end"]
            consumed += 1
        out.append({"word": token, "start": round(start, 3), "end": round(end, 3)})
        i += consumed
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vocab", action="append", required=True,
                    help="vocab.json with a 'corrections' map (repeatable)")
    args = ap.parse_args()

    corrections = {}
    for path in args.vocab:
        corrections.update(read_json(path, "vocab file").get("corrections", {}))

    doc = json.load(sys.stdin)
    doc["words"] = correct_words(doc.get("words", []), corrections)
    json.dump(doc, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
