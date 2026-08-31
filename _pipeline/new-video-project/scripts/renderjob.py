#!/usr/bin/env python3
"""Emit a paste-ready Resolve console snippet: import timeline + queue render.

  renderjob.py --timeline 2026-07-29-topic-cards \
      --fcpxml ~/hq_video/Projects/2026-07-29-topic/resolve/2026-07-29-topic-cards.fcpxml \
      --outdir ~/hq_video/Projects/2026-07-29-topic/exports \
      --name 2026-07-29-topic-youtube > setup.py

Resolve free has no external scripting, but Workspace -> Console -> Py3 runs
the same API. Pasting the output imports the fcpxml timeline (with source
clips) if it is not already in the project, selects it, pins its format, and
adds a fully configured job (mp4 / H.264 / resolution / bitrate / target dir
/ filename) to the Deliver queue - you only press Render All. Re-pasting
is safe AND expected: an existing timeline is reused (and re-pinned), an
already-queued job is skipped, and the master block refreshes the Blue
chapter markers from the section CLIP markers. The ritual is paste-twice:
once before editing (import + queue), once after picture lock (chapters
land at the edited positions).

PINNING (found 2026-08-06, WP project: "the timelines are all square"):
Resolve's FCPXML import adopts the imported timeline's format as the
PROJECT resolution - last import wins - while imported timelines keep "use
project settings" on. Three mixed-format imports in one paste therefore all
display at the LAST format. Every block now pins its timeline to its own
--width/--height/--fps via useCustomSettings, which also repairs a timeline
that imported wrong on an earlier paste. --project-format additionally
restores the project default; pass it on the master (cards) block.

Defaults target YouTube: 1080p, H.264 mp4, 12000 Kb/s (YouTube's 1080p60
recommendation), AAC 48kHz. --no-preset skips the YouTube preset search and
configures explicit dimensions - use it for vertical (1080x1920) and square
(1080x1080) jobs, where a landscape preset would be wrong. --import-only
imports and pins the timeline but queues no render job (the ultra safety
net rides the same paste this way).

Snippets append cleanly: generate one per timeline with >> to build a single
setup.py that imports and queues every deliverable in one paste.
"""
import argparse
import json
import re
import textwrap

TEMPLATE = '''\
# Paste into DaVinci Resolve: Workspace -> Console -> Py3 (whole block)
pm = resolve.GetProjectManager()
proj = pm.GetCurrentProject()
tl = None
for i in range(1, int(proj.GetTimelineCount()) + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == {timeline}:
        tl = t
        break
if not tl and {fcpxml}:
    tl = proj.GetMediaPool().ImportTimelineFromFile({fcpxml},
        {{"timelineName": {timeline}, "importSourceClips": True}})
    print("imported timeline:", tl.GetName() if tl else "FAILED")
if not tl:
    print("no timeline - check the fcpxml path and re-paste")
else:
    proj.SetCurrentTimeline(tl)
    # FCPXML import adopts the imported format as the PROJECT resolution
    # (last import wins) and the new timeline follows project settings.
    # Pin this timeline to its own format so mixed-format imports coexist.
    tl.SetSetting("useCustomSettings", "1")
    ok = (tl.SetSetting("timelineResolutionWidth", {tw})
          and tl.SetSetting("timelineResolutionHeight", {th})
          and tl.SetSetting("timelineFrameRate", {tfps}))
    print("pinned", tl.GetName(), "to", {fmt_label}, "-", "ok" if ok else "FAILED (set Timeline Settings by hand)")
{project_format}{render}'''

PROJECT_FORMAT = '''\
    proj.SetSetting("timelineResolutionWidth", {tw})
    proj.SetSetting("timelineResolutionHeight", {th})
    proj.SetSetting("timelineFrameRate", {tfps})
    print("project default restored to", {fmt_label})
'''

RENDER = '''\
    jobs = proj.GetRenderJobList() or []
    if any((j.get("TimelineName") or "") == tl.GetName()
           and (j.get("TargetDir") or "") == {outdir} for j in jobs):
        print("render job already queued for", tl.GetName(), "- skipped")
    else:
{codec_setup}
        settings.update({{"SelectAllFrames": True, "TargetDir": {outdir},
                         "CustomName": {name}}})
        proj.SetRenderSettings(settings)
        job = proj.AddRenderJob()
        print("queued", job, "->", {dest})
{note}'''

CHAPTERS = '''\
    # Chapters: section CLIP markers rode along with the edits; convert
    # them to Blue ruler markers, which the YouTube dialog's "Chapters
    # from Markers" (Blue is its default) ships with the upload. Markers
    # carrying a note (the title/description marker) and markers whose
    # frame was trimmed out are skipped. Re-paste after editing refreshes.
    tl.DeleteMarkersByColor("Blue")
    tstart = int(tl.GetStartFrame())
    chapters = []
    for item in tl.GetItemListInTrack("video", 1):
        for f, m in (item.GetMarkers() or {}).items():
            if m.get("note"):
                continue
            local = int(f) - int(item.GetLeftOffset())
            if 0 <= local < int(item.GetDuration()):
                chapters.append((int(item.GetStart()) + local, m.get("name", "")))
    chapters.sort()
    if chapters and chapters[0][0] > tstart:
        chapters[0] = (tstart, chapters[0][1])  # YouTube needs a 0:00 chapter
    seen = set()
    for rec, cname in chapters:
        if rec - tstart not in seen:
            seen.add(rec - tstart)
            tl.AddMarker(rec - tstart, "Blue", cname, "", 1)
    print(len(seen), "chapters set on", tl.GetName(),
          "- tick Chapters from Markers (Blue) when uploading")
'''

PRESET_SETUP = '''\
    preset = None
    for p in (proj.GetRenderPresetList() or []):
        n = p if isinstance(p, str) else str(p)
        if "youtube" in n.lower():
            preset = n
            if "1080" in n:
                break
    if preset and proj.LoadRenderPreset(preset):
        print("loaded render preset:", preset)
        settings = {{}}
    else:
        print("no YouTube preset found - configuring custom mp4/H264")
        proj.SetCurrentRenderFormatAndCodec("mp4", "H264")
        settings = {{"ExportVideo": True, "ExportAudio": True,
                    "FormatWidth": {width}, "FormatHeight": {height},
                    "VideoQuality": {bitrate}, "AudioCodec": "aac",
                    "AudioSampleRate": 48000}}'''

CUSTOM_SETUP = '''\
    proj.SetCurrentRenderFormatAndCodec("mp4", "H264")
    settings = {{"ExportVideo": True, "ExportAudio": True,
                "FormatWidth": {width}, "FormatHeight": {height},
                "VideoQuality": {bitrate}, "AudioCodec": "aac",
                "AudioSampleRate": 48000}}'''

NOTE = '''\
    print("NOTE: upload Title/Description are not scriptable - double-click")
    print("the info marker on the first clip (title = name, description =")
    print("note) or paste from exports/youtube-metadata.txt.")
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--fcpxml", default="", help="import this if timeline absent")
    ap.add_argument("--outdir", default="", help="render target dir")
    ap.add_argument("--name", default="", help="output filename, no extension")
    ap.add_argument("--title", default="",
                    help="human video title; used as the filename so YouTube "
                         "Studio pre-fills the title on upload")
    ap.add_argument("--width", type=int, default=1920,
                    help="timeline AND render width (they match in practice)")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", default="30", help="timeline frame rate to pin")
    ap.add_argument("--bitrate", type=int, default=12000,
                    help="Kb/s; 0 = let Resolve choose (fallback mode only)")
    ap.add_argument("--no-preset", action="store_true",
                    help="skip the YouTube preset search; configure explicit "
                         "mp4/H264 at --width x --height (vertical/square jobs)")
    ap.add_argument("--project-format", action="store_true",
                    help="also restore the PROJECT default resolution to "
                         "--width x --height (pass on the master block)")
    ap.add_argument("--import-only", action="store_true",
                    help="import and pin the timeline; queue no render job")
    a = ap.parse_args()
    if not a.import_only and not (a.outdir and a.name):
        ap.error("--outdir and --name are required unless --import-only")

    tw, th, tfps = json.dumps(str(a.width)), json.dumps(str(a.height)), \
        json.dumps(str(a.fps))
    fmt_label = json.dumps(f"{a.width}x{a.height}@{a.fps}")
    if a.import_only:
        render = ""
    else:
        name = re.sub(r'[/\\:?*"<>|]', "", a.title).strip() or a.name
        setup = (CUSTOM_SETUP if a.no_preset else PRESET_SETUP).format(
            width=a.width, height=a.height, bitrate=a.bitrate)
        # json.dumps makes each value a valid Python string literal, so a
        # stray quote in a title or path cannot break the pasted snippet.
        # The queue guard wraps the codec/queue code in an else:, one
        # indent level deeper than the templates are written.
        render = RENDER.format(codec_setup=textwrap.indent(setup, "    "),
                               outdir=json.dumps(a.outdir),
                               name=json.dumps(name),
                               dest=json.dumps(f"{a.outdir}/{name}.mp4"),
                               note="" if a.no_preset
                                    else textwrap.indent(NOTE, "    "))
    project_format = PROJECT_FORMAT.format(
        tw=tw, th=th, tfps=tfps, fmt_label=fmt_label) if a.project_format else ""
    chapters = CHAPTERS if a.title else ""
    print(TEMPLATE.format(timeline=json.dumps(a.timeline),
                          fcpxml=json.dumps(a.fcpxml),
                          tw=tw, th=th, tfps=tfps, fmt_label=fmt_label,
                          project_format=project_format,
                          render=render + chapters))


if __name__ == "__main__":
    main()
