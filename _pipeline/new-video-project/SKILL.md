---
name: new-video-project
description: >
  Set up a DaVinci Resolve project from a fresh recording. Use when the
  user says things like "new video in inbox", "I just finished recording",
  "set up the DaVinci project", or drops footage in _inbox. First action,
  before reading anything else: start
  `python3 _pipeline/new-video-project/scripts/ingest.py` (from the repo
  root) in the background, then read EDIT.md in this skill's directory
  while it runs.
---

# New video project: entry

One action, then reading. Start the gather in the background NOW (from the
repo root):

    python3 _pipeline/new-video-project/scripts/ingest.py

It picks the newest folder in `_inbox` ("YYYY-MM-DD Topic", several short
clips, one narrative beat each; retakes are deleted files, the folder name
names the project). `--slug S` overrides the derived name, `--mask
x0:y0:x1:y1` overrides the standard PIP+chrome activity masks, `--vocab
V.json` layers extra vocab. It scaffolds `Projects/<slug>/`, moves media,
copies the template .drp, and turns the recording into the complete
evidence set in `transcripts/` (immutable raw transcript + derived working
transcript and formats, silence maps, filler candidates, snippet-verified
audit, activity map, contact sheet). Takes minutes (Whisper); its final
message lists the materials and the next step.

While it runs:

- Read `_pipeline/new-video-project/EDIT.md`. The whole pipeline from here
  (the edit sitting, build, gates, report, thumbnails) lives there.
- If `_inbox` is empty, ask the user where the recording is.
- If the folder name doesn't say what the video is about, ask now.
- Spelling fixes grow `_templates/vocab.json` (prompt_terms seed Whisper,
  corrections patch what it still misses), never hand-edits to transcripts.

Root: the repo root (this file lives in `_pipeline/new-video-project/`).
Everything runs with plain `python3`; `transcribe.py`/`snip.py` need the
mlx-whisper venv at `<root>/.venv/bin/python` (see the README's one-time
setup), and ingest calls them itself.
