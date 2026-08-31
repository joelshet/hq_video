# hq_video — automated DaVinci project setup

Say "I just finished recording, set up the DaVinci project" to Claude
(Claude Code or Cowork) from this folder and the pipeline does the rest.
The included Zed task ("Go" in `.zed/tasks.json`) runs
`claude "New video in inbox"` in a new terminal for one-keystroke starts.

## Folder layout

```
_inbox/       drop recordings here: one "YYYY-MM-DD Topic" folder of clips per project
_templates/   template .drp + brand.json (title card style) + vocab.json (jargon)
_pipeline/    skills: new-video-project/ (Resolve pipeline) + ordinal-batch/
              (X/LinkedIn scheduling); each is a SKILL.md recipe, mirrored
              into .claude/skills/ by symlink so Claude Code lists them
_social/      one batch doc per Ordinal scheduling run: paths + paste-ready copy
_archive/     retired or abandoned projects (gitignored)
Projects/     generated projects: 2026-07-22-topic/
                footage/  transcripts/  graphics/cards/  resolve/  exports/
              ships with one synthetic sample project showing the layout
              (media itself is gitignored, so only the text artifacts are here)
```

## Design

Unix-style: each tool does one thing, takes explicit args or stdin/stdout,
and holds no state — there is no manifest, no config, no root-finding magic.
The filesystem is the state; Claude is the shell. Layout, naming, and all
editorial judgment (sections, cards, cut lists) live in SKILL.md prose.

```
ingest.py [FOLDER]                       phase 1: scaffold+transcribe+formats
transcribe.py FILE...                    media -> FILE.words.json  (mlx-whisper)
vocabfix.py --vocab V < words.json       fix product-name spellings
words2.py srt|reading|pauses             render words.json as editor formats
cardanim.py "Title" -o card.mov          animated full-screen card (4 variants)
activity.py REC                          screen-change bursts: when AND where
ultracut.py --duration S < words.json    filler/pause/retake cuts as segments
cut2fcpxml.py < cutlist.json             cut list -> Resolve-importable timeline
gapcut.py FOOTAGE --head --end ..         audio-anchored gap collapse -> segments
cut2wav.py --media-root D -o OUT.wav     cut list -> the edit's audio (the gate medium)
editgate PROJECT [CUTLIST]               audio gates: duration, residuals, re-transcribe diff
previewbuild.py --project P              watchable preview mp4s (on request only)
renderjob.py --timeline T ...            Resolve console paste: import + queue
```

The cut list is the interesting interface: cut2fcpxml knows nothing about
title cards or transcripts — a shorts timeline is just another cut list, and
an animated card is just another spine clip. Each project ships full
(safety net), ultra (the master you edit), a 9:16 short, and a 1:1
square, each audio-gated by editgate before import; brand-heavy videos add the
card-weave master. The pipeline runs in two phases: `ingest.py` does
everything mechanical, then the track decides: SEO tutorials go straight
to the ultra cut, brand videos get 2–3 pitched concepts and the expensive
edit work happens only on the one you pick.

## The ritual (after Claude runs the pipeline)

1. Double-click `Projects/<slug>/resolve/<slug>.drp` → Resolve opens the project
2. Workspace → Console → Py3 → paste `resolve/setup.py` → the timelines
   import with footage (ultra master, short, square; brand videos add the
   cards weave), each pinned to its own format, and the render jobs land
   in the Deliver queue: YouTube 1080p (filename = the video title, so
   YouTube Studio pre-fills it), 1080x1920, and 1080x1080
3. Edit, then RE-PASTE the same `resolve/setup.py` — imports and queued
   jobs are skipped, and your section markers become Blue ruler chapters
   at their edited positions
4. Render + upload: tick "Chapters from Markers" (Blue) in the YouTube
   dialog; title/description copy from the info marker (double-click it)
   or from `exports/youtube-metadata.txt`

Optional: other timelines (`.fcpxml`, `-ultra`) import via File → Import →
Timeline; captions via media pool right-click → Import Subtitle →
`transcripts/*.srt` (timings match the FULL timeline only).

## One-time setup

- In Resolve: File → Export Project → save as `_templates/template.drp`
  (set up your bins/timeline/color preferences first — every project inherits
  them). Any `*.drp` in `_templates/` is picked up.
- Transcription uses mlx-whisper (Apple Silicon). Create the venv at the
  repo root: `python3 -m venv .venv && .venv/bin/pip install mlx-whisper`.
  The scripts find it there on their own; models are cached on first run,
  so it works offline afterward.
- `pip3 install pillow numpy` for cards + activity maps (Claude Code can
  do this)
- Tweak the title card look in `_templates/brand.json` (placeholder tokens;
  colors are RGBA, fonts are tried in order — list your brand font first,
  the system fallbacks already work). Point `wordmark` at a PNG in
  `_templates/assets/` to foot every card with your logo.
- Product names and jargon live in `_templates/vocab.json` (shipped with
  placeholder examples). Add a term to `prompt_terms` so Whisper spells it
  right the first time, and a `corrections` regex to fix it when Whisper
  still gets it wrong. For names specific to one video, pass a second
  `--vocab` file: it merges on top.
- `brand-hook.json` is a DELTA file over brand.json
  (pass both: `--brand brand.json --brand brand-hook.json`). Colors and
  fonts are stated once, in brand.json.
- `brew install moreutils` (for `sponge`, used by the in-place vocabfix step)
- This folder is a git repo with media gitignored: scripts, cut lists,
  transcripts, and docs are tracked, so edits diff and roll back. Commit
  after each project.

## Manual runs

See the Recipe in `_pipeline/new-video-project/SKILL.md` — every step is a
plain shell command you can run yourself.
