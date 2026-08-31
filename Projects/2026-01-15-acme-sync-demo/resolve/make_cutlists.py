#!/usr/bin/env python3
"""Cut lists for 2026-01-15-acme-sync-demo (the synthetic sample project).

Decisions (from the evidence in transcripts/):
- Fillers: "So," (6.08) and "um," (6.72) both CUT — scene-settles before
  "let's start with the schema". Audit blips 6.19-6.60 and 6.83-7.11 both
  snippet-confirmed as the fillers themselves. Drop starts INSIDE the
  preceding silence (voice end 5.92 + 0.03) so gapcut's onset pad can't
  keep a sliver of the "So" — the first gate pass shipped one.
- Retake: "Every table gets a field mapping..." recorded twice
  (8.82-13.62, then 13.88-18.84). Last take is the keeper; drop from
  inside the preceding silence (voice end 8.61 + 0.04) to 13.73 (0.26s
  lead-in to the kept onset). Same sliver lesson as the fillers.
- Head 0.0 (speech starts at the first frame), end 25.98 (last word ends
  25.58 + 0.4s outro pad).
- Sections: Intro (0), Set up the schema (src 7.24), Watch a record sync
  (src 19.12). Info marker carries the YouTube title + description.
"""
import json
import subprocess
import sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent
S = P.parents[1] / "_pipeline" / "new-video-project" / "scripts"
T = P / "transcripts"

words = (T / "demo.words.json").read_text()
segs = json.loads(subprocess.run(
    [sys.executable, S / "gapcut.py", P / "footage" / "demo.mp4",
     "--head", "0", "--end", "25.98",
     "--drop", "5.95-7.11", "--drop", "8.65-13.73",
     "--map30", T / "demo.sil30.txt", "--map35", T / "demo.sil35.txt"],
    input=words, capture_output=True, text=True, check=True).stdout)
print(f"gapcut: {len(segs)} segments", file=sys.stderr)


def tl(src_t):
    """Source time -> ultra timeline time."""
    acc = 0.0
    for a, b in segs:
        if src_t <= b:
            return round(acc + max(0.0, src_t - a), 2)
        acc += b - a
    return round(acc, 2)


TITLE = "How Acme Sync moves records between two apps"
DESC = ("A 30-second tour of Acme Sync: map a schema once, then watch a "
        "webhook land a record in Postgres in about a second.")

ultra = {
    "name": "2026-01-15-acme-sync-demo-ultra",
    "spine": [{"src": "footage/demo.mp4", "in": a, "out": b}
              for a, b in segs],
    "markers": [
        {"at": 0, "name": "Intro"},
        {"at": tl(7.24), "name": "Set up the schema"},
        {"at": tl(19.12), "name": "Watch a record sync"},
        {"at": 1, "name": TITLE, "note": DESC},
    ],
}

full = {
    "name": "2026-01-15-acme-sync-demo-full",
    "spine": [{"src": "footage/demo.mp4"}],
    "markers": [
        {"at": 6.08, "name": "Filler: So, um"},
        {"at": 8.82, "name": "RETAKE: field mapping take 1"},
    ],
}

for name, cut in [("cutlist-ultra.json", ultra), ("cutlist.json", full)]:
    (P / "resolve" / name).write_text(json.dumps(cut, indent=1) + "\n")
    print(f"wrote resolve/{name}", file=sys.stderr)
