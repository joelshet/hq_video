# The edit: read once, author once

Gather already ran (`ingest.py`); every piece of evidence is a file in
`transcripts/`. Two beats remain, and the first is the job:

1. **Read once, author once.** Read all the evidence in one contiguous
   sitting, then write the whole edit down while the transcript is the
   freshest thing in context. An edit authored later, from notes, ships
   duplicated sections. If anything separates the read from the authoring,
   read again.
2. **Build and gate.** One chained command renders timelines and runs
   `editgate` on the audio.

The gates verify the edit against the plan, never the plan's content, so a
wrong plan passes green. Content correctness is yours alone. The turn
budget is roughly one per beat plus the report; spend the savings on
reading. You are the orchestrator: the tools are small and dumb, and
layout, naming, and editorial policy live here. Run mechanics as chained
commands (`&&`, pipes), not one call per turn. Tools are frozen during a
build; route around breakage and fix it between projects.

Tools: `<root>/_pipeline/new-video-project/scripts/`. Each tool's docstring
is its contract; read it before reaching for flags. `snip.py` runs with
`<root>/.venv/bin/python`; the rest is plain `python3`.

```
gapcut.py FOOTAGE --head T --end T [verdict flags]   stdin words.json ->
        kept [in,out] segments; sentence-aware gap collapse on -30dB audio
        truth; always pass ingest's cached --map30/--map35
snip.py FILE A-B...                re-transcribe zones in isolation (venv)
editgate P [CUTLIST] [--allow-src T]..  audio gates: duration, residual
        silence, re-transcription diff, fcpxml parse; nonzero on FAIL
cut2fcpxml.py --media-root P       stdin cut list -> fcpxml (schema, zoom
        and crop math in the docstring)
cardanim.py "Title" [--variant ..] -o O.mov  animated full-screen card
renderjob.py --timeline T --fcpxml F --outdir D --name N  paste-ready
        Resolve console block (import, pin format, queue render)
previewbuild.py --project P        preview mp4, on request only
derive.py P [STEM..]               rebuild words.json + editor formats from
        raw.words.json through vocab + X.fixes.json (wordfix.py ops —
        transcript judgment as data; never hand-edit words.json, raw is
        immutable, diff raw vs derived shows every change)
```

## 1. Read everything once

One contiguous sitting. No cards, no thumbnails, no tool work before the
edit exists. Read all of it:

- Every `reading.md` in full. These words are what the viewer hears; wrong
  words make wrong cuts. Identify the hook, 3-7 sections, and retakes
  (repeated phrasings; the last take is the keeper). Clips can play in
  narrative order, which may differ from recording order; a clip opening
  "It's also..." continues whatever it names.
- Every `audit.md`, verdict per zone: an um or noise dies with its gap, a
  real word becomes `--nocut`/`--tailv`/`--onset`, "(no speech)" confirms a
  hallucination: record a delete op (with its why) in `X.fixes.json` and
  re-run `derive.py $P`. Recovered dropped speech is an insert op. Whisper
  omits um/uh entirely, so an untranscribed blip is normal, and a missed
  um ships: nothing downstream can hear it.
- Every `candidates.json`, verdict per candidate from its context. Default
  is CUT for every so/okay/um. Keeps: a reaction word after an on-screen
  wait ("Okay." when the result lands) and the outro sign-off cadence ("So
  that's it"). Scene-settles are cut; when in doubt, cut.
- `pauses.json` (retakes and card slots hide in long silences, room tone
  harvests there), `activity.json` (the real demo beats), `contact.jpg`
  (layout, PIP position, camera vs screen, faces).

Then pick the track. SEO tutorial (matches the api-key/how-to template):
choose the sections yourself and keep going; no pitch, no cards. Brand
(longer, brand-heavy): pitch 2-3 genuinely different concepts, one screen
each (hook line quoted from the transcript + cold-open visual, section
titles, what gets cut entirely with timestamps, title + thumbnail angle),
then stop for the user's pick. If they already gave the direction, confirm
it as one concept and continue.

## 2. Author everything once

Everything in writing, now:

- `resolve/make_cutlists.py` (this exact name every project; judgment stays
  bespoke, the filename does not). Its docstring records the decisions:
  keepers, drops, filler verdicts, audit verdicts, section starts. Its body
  runs gapcut per clip with the verified flags (`--head`/`--end` from the
  audit's onset and last-voice numbers, `--drop` for retakes and fillers
  with bounds read off the silence maps, the audit verdicts as flags,
  cached `--map30`/`--map35`) and emits the cut lists. Debug to stderr, no
  log files.
- Cut lists: `cutlist.json` (full recording, the safety net, with RETAKE
  and dead-air markers) and `cutlist-ultra.json` (the authored edit; the
  master on the SEO track). Brand adds `cutlist-cards.json` (the master:
  ultra spine + each card .mov as a plain spine clip; set `"fps"`
  explicitly or a 30fps card probed first silently converts 60fps footage).
- Multi-clip joins: incoming clip starts at verified onset - 0.2s (past the
  record click), outgoing ends at verified end + 0.4s; card-adjacent bounds
  widen (+0.3s out, -0.15s in); the last clip before the end card holds
  ~1.2s.
- Markers in the master list: one clip marker per section, named exactly as
  the YouTube chapter (sentence case, no numbers, first at 0), plus one
  info marker at ~1s whose name is the video title and note is the full
  description (note-carrying markers never become chapters).
- `exports/youtube-metadata.txt`: TITLE A / TITLE B / DESCRIPTION / TAGS /
  THUMBS, paste-ready. SEO-first and API-first: the product API is the
  subject, Claude is the method; both titles carry the query ("How to
  connect to the <Product> API with Claude" vs "Connect to the <Product>
  API (no Python, just Claude)"), each naming its A/B axis. Every claim
  must be literally true of the video; when punchy and true conflict, true
  wins. Zero errors from the prose linter, if one is configured. No
  chapter list in the description.
- `resolve/setup.py`: one renderjob.py block per timeline, appended with
  `>>`. The master gets `--title` and `--project-format`; a brand-track
  ultra imports with `--import-only`. Every block SELECTS its timeline,
  so the master's block goes LAST -- after the paste the editor is parked
  on whatever imported last (2026-08-18: the wrong cut got reviewed).

Read the planned edit back, end to end: the kept words in order, every
section exactly once, nothing good missing. This is model attention; no
tool replaces it. Re-do it after any later cut-list change.

## 3. Build and gate

    python3 resolve/make_cutlists.py && for c in resolve/cutlist*.json; do
      n=$(basename "$c" .json)
      python3 "$S/cut2fcpxml.py" --media-root "$P" < "$c" \
        > "resolve/${n/cutlist/$SLUG}.fcpxml"
    done && "$S/editgate" "$P"

Act on every editgate line: fix FAILs; judge each JUDGE by snippet (snip.py
on the assembled wav's source zone) before believing either reading, since
Whisper mishears fast speech and drops soft words at hard seams. Residuals
over 0.55s fail unless a verified drawl is listed via `--allow-src`; record
those in make_cutlists.py. Iterate cut list -> editgate until clean (~2 min
a loop). Picture is judged in Resolve, not previews.

Brand track only, after the edit exists: render cards with one cardanim.py
call each into `graphics/cards/anim/` (titles <= 6 words, sentence case, no
numbers, no eyebrows on section cards; hook card uses the thumbnail
treatment and IS the thumbnail; cycle variants so neighbors differ,
hook=words 2.4s, sections rise/track/type/words 1.8s, end=track 3.5s;
`--size` matches footage; brand deltas layer after `--brand brand.json`).
Cards are never digitally silent: harvest room tone from a pause or clip
head, boost gated air to about -60dB mean, save `anim/roomtone.wav`, mux it
into every card with edge fades (`atrim` + `afade` in, out), and in Resolve
the same wav on A2 gives parity.

## 4. Report: get the editor into Resolve

Lead with "Resolve project ready: <master> cut" (brand: plus the concept
recap), then the ritual:

- When the user is ready (they ask, or confirm the report), run
  `open resolve/<slug>.drp && pbcopy < resolve/setup.py`: Resolve opens
  the project and setup.py is on their clipboard.
- Workspace -> Console -> Py3 -> Cmd-V -> Enter: timelines import
  with source clips, formats pinned, render jobs queued.
- Edit the master, then paste `setup.py` again: imports and queued jobs are
  skipped, and the section clip markers (which rode along with the edits)
  become Blue ruler chapters at the edited positions.
- Render, upload from Resolve: tick Chapters from Markers (Blue), copy
  title + description from the info marker or `exports/youtube-metadata.txt`,
  thumbnail from `exports/thumb-*.png`.

Summarize sections, retakes, and anything they should listen for (seams,
boundary words). Thumbnails are not on this critical path; say they'll land
in `exports/` while they edit.

## 5. Thumbnails, while the editor works

Two candidates to `exports/thumb-a-*.png thumb-b-*.png` (1280x720, <2MB),
one-liners in the THUMBS section of youtube-metadata.txt. Judgment work,
not a template; no thumbnail tool exists on purpose. For an SEO tutorial
series they are relevance confirmation, minimal: flat brand panel, two
product marks with a thin arrow, the title font in sentence case
("Connect to the / <Product> API") with the API phrase dominant in the
product's color, a short counter-positioning line, small wordmark; it
deliberately looks like the video's title card. Variant B = the same stack
with a footage face frame as a full-height right panel (no face vs mainly
face, one variable). Name the search object exactly; the accuracy bar
applies word for word. Compose in HTML/CSS, screenshot with headless
Chrome, real parts only (face frames via the contact sheet, marks from
simpleicons or the product's press kit). Critique at 168px as well as full
size; iterate before showing the user.

## On request only

- **Short (9:16) and square (1:1)**: off the default roster. Teaser beat
  (short) or self-contained beat (square), 30-60s, native tracks: spine =
  screen cell, lane 1 = face cell overlays, lane 2 = one pre-rendered
  karaoke caption .mov (captions mandatory, autoplay is silent). Set
  width/height/fps explicitly; crop/zoom are calibrated, author source
  pixels and trust cut2fcpxml (math in its docstring). Copy the approved
  look and build from the latest project that shipped a short (its
  `make_short.py`).
  Append render blocks to setup.py with `--no-preset --bitrate 10000`.
  Ask before redesigning the format.
- **VO-first** (voiceover recorded in Resolve): ingest the .wav as usual
  (no activity map or contact sheet). Ask the delivery resolution (default
  1920x1080). Spine = the wav, cards woven as spine clips, markers at
  section starts plus every long pause labeled "visual:" for b-roll; set
  width/height/fps in the cut list. No .drp step; the editor imports the
  fcpxml into their existing project.
- **Preview mp4** (`previewbuild.py --project $P`) and a `-tight`
  middle-ground timeline (pauses trimmed, no filler cuts).

## Notes

- This workflow targets Resolve free: the console paste is the only
  automation; never suggest external scripting or the MCP server. If
  mlx_whisper won't import (sandbox), have the user run ingest via Claude
  Code on their Mac.
- This ffmpeg has no libass. Burned-in or karaoke captions are Pillow
  caption-state PNGs on a concat-demuxer alpha track (whole-word pops, the
  better look anyway).
- Seam policy: audio-anchored in-points run tight (0.03-0.06s) by design;
  a clipped onset surfaces in editgate's diff and is fixed with `--onset`/
  `--protect` on that seam, never by widening every pad. Stamp-derived
  drops keep >= 0.15s lead-in to the next kept word.
- No punch-in zooms in master timelines; the demo plays wide. Cut rhythm
  comes from section cards on breath gaps, real content cuts, and
  full-frame speaker segments. Payoff before explanation; callback to the
  hook shot near the end; end card holds ~5s, URL only.
- Cleanup before reporting: transcripts carry only the pinned names, and
  render intermediates (pass1 files, ProRes builds, caption PNG dirs) are
  deleted once their export exists. Ship step (after the upload): on
  request transcribe the final mp4 to `transcripts/<slug>_final.srt`.
- Recording asks: Retina capture, editor/terminal fonts 28pt+, camera as
  its own full-frame file when possible.
