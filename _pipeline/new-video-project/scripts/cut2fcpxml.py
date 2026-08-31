#!/usr/bin/env python3
"""Convert a cut list to an FCPXML timeline. Filter: stdin -> stdout.

  cut2fcpxml.py --media-root Projects/slug < cutlist.json > timeline.fcpxml

Knows nothing about title cards, transcripts, or projects — it just converts.
The cut list is the editorial artifact; whoever writes it holds the policy.

Cut list schema (times are seconds or "HH:MM:SS(.ms)"):
{
  "name": "my-timeline",
  "fps": "60/1",          // optional: probed from first spine clip
  "width": 3564,          // optional: probed
  "height": 2304,         // optional: probed
  "spine": [              // played back to back, in order
    {"src": "footage/rec.mov", "in": 0, "out": 122.5},  // in/out optional (full clip)
    {"src": "footage/rec.mov", "in": 122.5, "out": 140,
     "zoom": {"scale": 1.6, "x": -280, "y": 120}},      // punch-in
    {"src": "footage/rec.mov", "in": 5, "out": 9,       // face cell for
     "crop": {"left": 1449, "top": 615},                // shorts: px trimmed
     "zoom": {"scale": 2.2, "x": 0, "y": -400}}         // from source edges
  ],
  "overlays": [           // connected clips above the spine (stills or video)
    {"src": "graphics/cards/hook.png", "at": 0, "duration": 5,
     "lane": 1, "name": "Hook"},
    {"src": "footage/rec.mov", "at": 0, "duration": 4, "in": 12.5,
     "lane": 1, "crop": {"left": 1449, "top": 615},     // face cell: source
     "zoom": {"scale": 2.4, "x": 0, "y": -600}}         // in + crop + zoom
  ],
  "markers": [           // CLIP markers: they ride with the clip in Resolve
    {"at": 131, "name": "Get the API key"},              // chapter: name only,
                                                         // sentence case, NO numbers
    {"at": 1, "name": "<YT title>", "note": "<YT description>"}  // info marker:
                                                         // note = description ("\n" ok);
                                                         // note-carrying markers are
                                                         // never converted to chapters
  ]
}

Zoom units: "x"/"y" are the pixels the image moves at timeline resolution,
screen convention (+x right, +y down), applied after "scale" with a center
anchor. To center source point (cx, cy) at scale s:
  x = (width/2 - cx) * s,  y = (height/2 - cy) * s
Converted internally to Resolve's FCPXML units (percent of frame height,
+y up); calibrated 2026-08-04 against Resolve import tests (zoom-cal).

Crop units: "crop" trims pixels from the SOURCE frame's edges (left/top/
right/bottom, omitted edges 0). Calibrated 2026-08-04 (crop-cal tests 3+4):
Resolve's trim-rect is asymmetric — top/bottom percent of source height,
left/right percent of timeline height in display space — and the converter
compensates, so cut lists just author source pixels. Verified in the 1:1
and vertical (shorts) configs; the square config extrapolates the same
rule (crop-cal-3 will confirm it on the next calibration pass).

Flags:
  --media-root DIR   resolve relative srcs for probing (default: cwd)
  --url-root PATH    base for file:// URLs in the XML (default: media-root).
                     Use when generating in a sandbox whose mount path differs
                     from the real path Resolve will see.
"""
import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from xml.sax.saxutils import escape

from common import ffprobe_media, fps_fraction, sec_to_rational, parse_timecode

STILL_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-root", default=".")
    ap.add_argument("--url-root", default=None)
    args = ap.parse_args()

    media_root = Path(args.media_root).expanduser().resolve()
    url_root = args.url_root or str(media_root)

    cut = json.load(sys.stdin)
    spine_in = cut.get("spine") or sys.exit("cut list needs a non-empty 'spine'")

    def probe(rel: str) -> dict:
        p = Path(rel)
        return ffprobe_media(p if p.is_absolute() else media_root / rel)

    def file_url(rel: str) -> str:
        p = PurePosixPath(rel)
        full = str(p) if p.is_absolute() else f"{url_root.rstrip('/')}/{p}"
        return "file://" + quote(full)

    # --- format: fps/size from cut list, else probed from the first spine
    # clip that has video (an audio-only spine, e.g. a voiceover, falls back
    # to the cut list values or 1080p30) ---
    first = {"fps": None, "width": None, "height": None}
    for c in spine_in:
        if "src" not in c:
            continue
        info = probe(c["src"])
        if info["has_video"]:
            first = info
            break
    fps = fps_fraction(cut.get("fps") or first["fps"] or "30/1")
    width = cut.get("width") or first["width"] or 1920
    height = cut.get("height") or first["height"] or 1080
    fd = 1 / fps
    fd_str = f"{fd.numerator}/{fd.denominator}s"

    def rt(sec: float) -> str:
        return sec_to_rational(sec, fps)

    # --- spine clips: compute source ranges and timeline positions ---
    # Timeline positions accumulate in FRAME-EXACT fractions: rounding each
    # duration and each offset independently from float sums left +-1-frame
    # offset/duration mismatches, which Resolve imports as literal one-frame
    # gaps (7 of them in a 43-clip timeline, found 2026-08-05). Quantize
    # every duration to the frame grid first, then chain offsets from the
    # quantized durations so offset[i+1] == offset[i] + duration[i] exactly.
    from fractions import Fraction
    clips, t = [], Fraction(0)
    for c in spine_in:
        info = probe(c["src"])
        src_in = parse_timecode(c.get("in", 0))
        src_out = parse_timecode(c["out"]) if "out" in c else (info["duration"] or 0)
        dur = Fraction(round(max(0.0, src_out - src_in) * fps)) / fps
        clips.append({"src": c["src"], "name": c.get("name", Path(c["src"]).stem),
                      "in": src_in, "dur": float(dur), "tl": float(t),
                      "has_audio": info["has_audio"], "zoom": c.get("zoom"),
                      "crop": c.get("crop"),
                      "sw": info["width"] or width, "sh": info["height"] or height})
        t += dur
    total = float(t)

    overlays = [{**o, "at": parse_timecode(o.get("at", 0)),
                 "duration": parse_timecode(o.get("duration", 5)),
                 "in": parse_timecode(o.get("in", 0)),
                 "lane": o.get("lane", 1),
                 "name": o.get("name", Path(o["src"]).stem)}
                for o in cut.get("overlays", [])]
    for o in overlays:
        if o.get("crop") or o.get("zoom"):
            info = probe(o["src"])
            o["sw"], o["sh"] = info["width"] or width, info["height"] or height
    markers = [{"at": parse_timecode(m.get("at", 0)), "name": m.get("name", ""),
                "note": m.get("note")}
               for m in cut.get("markers", [])]

    # --- resources ---
    res = [f'<format id="r1" frameDuration="{fd_str}" '
           f'width="{width}" height="{height}"/>']
    asset_ids, next_id = {}, 2

    def asset_for(rel: str) -> str:
        nonlocal next_id
        if rel in asset_ids:
            return asset_ids[rel]
        aid = f"a{next_id}"
        next_id += 1
        asset_ids[rel] = aid
        still = Path(rel).suffix.lower() in STILL_EXTS
        if still:
            attrs = 'start="0/1s" duration="0s" hasVideo="1"'
        else:
            info = probe(rel)
            parts = [f'start="0/1s" duration="{rt(info["duration"] or 0)}"']
            if info["has_video"]:
                parts.append('hasVideo="1"')
            if info["has_audio"]:
                parts.append('hasAudio="1" audioSources="1" audioChannels="2"')
            attrs = " ".join(parts)
        res.append(f'<asset id="{aid}" name="{escape(Path(rel).name)}" {attrs} '
                   f'format="r1"><media-rep kind="original-media" '
                   f'src="{escape(file_url(rel))}"/></asset>')
        return aid

    for c in clips:
        c["aid"] = asset_for(c["src"])
    for o in overlays:
        o["aid"] = asset_for(o["src"])

    # --- spine: overlays/markers attach to the clip whose span contains them
    # (boundary times resolve to the LATER element). Child offsets and marker
    # starts are in the parent's SOURCE time:
    # local = clip.in + (timeline_time - clip.tl)
    def owner(at):
        best = 0
        for i, c in enumerate(clips):
            if c["tl"] <= at + 1e-3:
                best = i
        return best

    for o in overlays:
        o["clip"] = owner(o["at"])
    for m in markers:
        m["clip"] = owner(m["at"])

    def adjust_children(item, sw, sh):
        """adjust-crop / adjust-transform children for a clip dict."""
        out = []
        cr = item.get("crop")
        if cr:
            # Resolve's trim-rect units, measured (crop-cal tests 3+4,
            # 2026-08-04): top/bottom = percent of SOURCE height in source
            # space; left/right = percent of TIMELINE height in DISPLAY
            # space after the fit-width conform — i.e. one horizontal unit
            # is (sw/tw)*(th/100) source px. Asymmetric but consistent
            # across the 1:1 and vertical configs. Applied before the
            # transform. Cut lists author all edges in source pixels.
            hx = 100 * width / (sw * height)   # units per source px, x
            out.append('<adjust-crop mode="trim"><trim-rect '
                       f'left="{cr.get("left", 0) * hx:g}" '
                       f'right="{cr.get("right", 0) * hx:g}" '
                       f'top="{cr.get("top", 0) * 100 / sh:g}" '
                       f'bottom="{cr.get("bottom", 0) * 100 / sh:g}"'
                       '/></adjust-crop>')
        z = item.get("zoom")
        if z:
            s = z.get("scale", 1.0)
            # Resolve reads FCPXML position as percent-of-frame-HEIGHT on
            # both axes, +y UP, center anchor, applied AFTER scale (verified
            # 2026-08-04: _reference/resolve-import-tests/zoom-cal). Cut
            # lists author in screen pixels, +y down.
            ux = z.get("x", 0) * 100 / height
            uy = -z.get("y", 0) * 100 / height
            out.append(f'<adjust-transform position="{ux:g} {uy:g}" '
                       f'scale="{s} {s}"/>')
        return out

    spine = []
    for ci, c in enumerate(clips):
        children = adjust_children(c, c["sw"], c["sh"])
        for o in overlays:
            if o["clip"] == ci:
                local = c["in"] + max(0.0, o["at"] - c["tl"])
                still = Path(o["src"]).suffix.lower() in STILL_EXTS
                tag = "video" if still else "asset-clip"
                inner = "".join(adjust_children(o, o.get("sw", width),
                                                o.get("sh", height)))
                head = (f'<{tag} lane="{o["lane"]}" ref="{o["aid"]}" '
                        f'offset="{rt(local)}" duration="{rt(o["duration"])}" '
                        f'start="{rt(o["in"])}" name="{escape(o["name"])}"')
                children.append(f"{head}>{inner}</{tag}>" if inner
                                else f"{head}/>")
        for m in markers:
            if m["clip"] == ci:
                local = c["in"] + max(0.0, m["at"] - c["tl"])
                # XML attribute parsing folds literal newlines to spaces, so
                # note line breaks must travel as &#10; entities
                note = (' note="' + escape(m["note"], {'"': "&quot;"})
                        .replace("\n", "&#10;") + '"') if m.get("note") else ""
                children.append(f'<marker start="{rt(local)}" duration="{fd_str}" '
                                f'value="{escape(m["name"])}"{note}/>')
        spine.append(
            f'<asset-clip ref="{c["aid"]}" offset="{rt(c["tl"])}" '
            f'name="{escape(c["name"])}" start="{rt(c["in"])}" '
            f'duration="{rt(c["dur"])}" format="r1" tcFormat="NDF">'
            + "".join(children) + "</asset-clip>")

    name = escape(cut.get("name", "timeline"))
    sys.stdout.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    {chr(10).join('    ' + r for r in res).strip()}
  </resources>
  <library>
    <event name="{name}">
      <project name="{name}">
        <sequence format="r1" duration="{rt(total)}" tcStart="0/1s" tcFormat="NDF">
          <spine>
            {chr(10).join('            ' + s for s in spine).strip()}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
""")
    print(f"{name}: {len(clips)} spine clips, {len(overlays)} overlays, "
          f"{len(markers)} markers, {total:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
