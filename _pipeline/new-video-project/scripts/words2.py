#!/usr/bin/env python3
"""Render a words.json as an editor-facing format. Filter: stdin -> stdout.

  words2.py srt      < x.words.json > x.srt         readable subtitles (<=2 lines)
  words2.py reading  < x.words.json > x.reading.md  timecoded paragraphs
  words2.py pauses   < x.words.json                 long silences as JSON
                                                    (dead air / retake starts)
"""
import argparse
import json
import sys

import captions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("format", choices=["srt", "reading", "pauses"])
    args = ap.parse_args()

    words = json.load(sys.stdin).get("words", [])
    if args.format == "srt":
        sys.stdout.write(captions.readable_srt(words))
    elif args.format == "reading":
        sys.stdout.write(captions.reading_transcript(words))
    elif args.format == "pauses":
        json.dump(captions.silence_markers(words), sys.stdout, indent=1)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
