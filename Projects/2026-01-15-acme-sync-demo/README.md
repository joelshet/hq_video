# Sample project: 2026-01-15-acme-sync-demo

A synthetic project showing what the pipeline generates. The footage is a
27-second macOS-TTS narration over an ffmpeg test pattern, dropped in
`_inbox/2026-01-15 Acme Sync Demo/` and run through `ingest.py` for real:
every file in `transcripts/` is genuine pipeline output, and the recording
was written to contain one filler pair ("So, um,") and one retake (the
"Every table gets a field mapping" sentence, recorded twice) so the
evidence has something to catch.

What's here:

- `transcripts/` — the complete evidence set: immutable raw transcript,
  derived working transcript and editor formats, silence maps, filler
  candidates, snippet-verified audit, activity map, contact sheet
- `resolve/make_cutlists.py` — the authored edit; its docstring records
  the decisions (both fillers cut, take one dropped), its body runs
  gapcut with those verdicts as flags and emits the cut lists
- `resolve/cutlist.json` + `cutlist-ultra.json` — full safety net and the
  27.3s -> 19.3s master, both gated green by `editgate`
- `exports/youtube-metadata.txt` — the paste-ready metadata shape

Not here, by design: the media itself (`footage/*.mp4` is gitignored;
regenerate any test clip you like), the `.fcpxml` timelines and
`resolve/setup.py` (both embed absolute local paths — rebuild with
`python3 resolve/make_cutlists.py`, then `cut2fcpxml.py` and
`renderjob.py` per `_pipeline/new-video-project/EDIT.md`), and the `.drp`
(created once you export a template, see the root README).
