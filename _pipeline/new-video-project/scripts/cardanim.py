#!/usr/bin/env python3
"""Render an ANIMATED full-screen title card as a ProRes .mov. One per call.

  cardanim.py "Add write scopes" --eyebrow "step 6" --variant rise \
      --brand _templates/brand.json -o card.mov

Same layout as `titlecard.py --style full` (opaque brand background, content
centered, wordmark at the foot) so animated and static cards match. Import the
.mov into Resolve like any clip; it holds its final frame until the clip ends.

Variants (cycle them across a video's cards):
  words  all words sit dimmed, then brighten one by one   (the reference move)
  rise   words fade in and rise into place, staggered
  track  title fades in while letter-spacing tightens
  type   eyebrow types on with a block caret, then title brightens

Hook cards use the thumbnail treatment (SEO/API-first): --marks a.png,b.png
(row with a thin arrow), --pre "Connect to the", the dominant title in the
product's brand color via --title-color, sized up via --title-scale, and
--subtitle "No Python. Just Claude." Step/end cards keep --eyebrow.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from titlecard import (FULL_GAP_EYEBROW, FULL_GAP_SUBTITLE, WM_FOOT, WM_HEIGHT,
                       draw_tracked, ink_height, ink_top, load_brand, load_font,
                       load_logo, scaled_logo, stack_ys, tracked_width)


def ease_out(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def lerp(a, b, p):
    return tuple(int(x + (y - x) * p) for x, y in zip(a, b))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("title")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--eyebrow", default="")
    ap.add_argument("--pre", default="", help="small sentence-case line above title")
    ap.add_argument("--marks", default="", help="comma-separated PNGs, drawn as a row")
    ap.add_argument("--title-color", default="", help="hex like FF7A59")
    ap.add_argument("--title-scale", type=float, default=1.0)
    ap.add_argument("--variant", default="words",
                    choices=["words", "rise", "track", "type"])
    ap.add_argument("--brand", action="append", default=[],
                    help="brand.json (repeatable: base first, then variant deltas)")
    ap.add_argument("--size", default=None, help="WxH, default brand canvas")
    ap.add_argument("--duration", type=float, default=3.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("-o", "--out", required=True, help="output .mov path")
    args = ap.parse_args()

    brand, brand_dir = load_brand(args.brand)
    w, h = brand["canvas"]
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
    gscale = h / brand["canvas"][1]

    title_size = int(brand["title_size"] * gscale * args.title_scale)
    subtitle_size = int(brand["subtitle_size"] * gscale)
    eyebrow_size = max(14, int(brand["eyebrow_size"] * gscale))
    tf = load_font(brand["fonts"], title_size)
    sf = load_font(brand.get("fonts_regular", brand["fonts"]), subtitle_size)
    ef = load_font(brand.get("fonts_mono", brand["fonts"]), eyebrow_size)
    eyebrow = args.eyebrow.upper()
    t_track = brand["title_tracking"] * title_size
    e_track = brand["eyebrow_tracking"] * eyebrow_size

    wordmark = load_logo(brand, "wordmark", brand_dir)
    wm = scaled_logo(wordmark, int(WM_HEIGHT * gscale)) if wordmark else None

    bg = tuple(brand["panel_color"][:3]) + (255,)
    if args.title_color:
        c = args.title_color.lstrip("#")
        bright = tuple(int(c[i:i+2], 16) for i in (0, 2, 4)) + (255,)
    else:
        bright = tuple(brand["text_color"])
    dim = lerp(bg, bright, 0.32) + (255,)
    pre_col = (185, 206, 220, 255)
    arrow_col = (94, 140, 165, 255)
    marks = []
    if args.marks:
        for mp in args.marks.split(","):
            m = Image.open(Path(mp).expanduser()).convert("RGBA")
            mh = int(56 * gscale)
            marks.append(m.resize((int(m.width * mh / m.height), mh), Image.LANCZOS))
    pf = load_font(brand["fonts"], int(brand["subtitle_size"] * 1.15 * gscale))
    ey_col = tuple(brand["eyebrow_color"])
    sub_col = tuple(brand["subtitle_color"])

    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    words = args.title.split()
    word_w = [tracked_width(meas, wd, tf, t_track) for wd in words]
    space_w = meas.textlength(" ", font=tf) + t_track
    tw = sum(word_w) + space_w * (len(words) - 1)
    sw = meas.textlength(args.subtitle, font=sf) if args.subtitle else 0
    ew = tracked_width(meas, eyebrow, ef, e_track)
    th = ink_height(meas, args.title, tf)
    sh = ink_height(meas, args.subtitle, sf) if args.subtitle else 0
    eh = ink_height(meas, eyebrow, ef) if eyebrow else 0
    ph = ink_height(meas, args.pre, pf) if args.pre else 0
    arrow_gap = int(22 * gscale)
    mrow_w = sum(m.width for m in marks) + (len(marks) - 1) * (arrow_gap * 2 + int(40 * gscale)) if marks else 0
    mh = marks[0].height if marks else 0
    gap_m = int(44 * gscale) if marks else 0
    gap_p = int(22 * gscale) if args.pre else 0
    gap_e = int(FULL_GAP_EYEBROW * gscale) if eyebrow else 0
    gap_s = int(FULL_GAP_SUBTITLE * gscale) if args.subtitle else 0
    y_marks, y_pre, y_eyebrow, y_title, y_subtitle = stack_ys(
        h, [(mh, gap_m), (ph, gap_p), (eh, gap_e), (th, gap_s), (sh, 0)])

    # timings (seconds); animation settles by ~1.2s, holds to --duration
    if args.variant == "type":
        e_t0, e_dur = 0.08, 0.022 * max(1, len(eyebrow))   # per-char typing
        w_t0, w_stag, w_dur = e_t0 + e_dur + 0.10, 0.08, 0.26
    else:
        e_t0, e_dur = 0.04, 0.25
        w_t0, w_stag, w_dur = 0.25, 0.10, 0.30
    s_t0 = w_t0 + w_stag * max(0, len(words) - 1) + w_dur * 0.6
    m_t0 = s_t0 + 0.18

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (w, h), bg)
        d = ImageDraw.Draw(img)

        head_p = ease_out((t - e_t0) / 0.3)
        if marks and head_p > 0:
            x = (w - mrow_w) / 2
            for i, m in enumerate(marks):
                fm = m.copy()
                fm.putalpha(fm.getchannel("A").point(lambda a: int(a * head_p)))
                img.alpha_composite(fm, (int(x), int(y_marks + (mh - m.height) / 2)))
                x += m.width
                if i < len(marks) - 1:
                    aw = int(40 * gscale)
                    ay = y_marks + mh // 2
                    d.line([(x + arrow_gap, ay), (x + arrow_gap + aw, ay)],
                           fill=arrow_col[:3] + (int(255 * head_p),),
                           width=max(3, int(5 * gscale)))
                    ah = int(9 * gscale)
                    d.polygon([(x + arrow_gap + aw, ay - ah),
                               (x + arrow_gap + aw + ah * 1.5, ay),
                               (x + arrow_gap + aw, ay + ah)],
                              fill=arrow_col[:3] + (int(255 * head_p),))
                    x += arrow_gap * 2 + aw
        if args.pre and head_p > 0:
            pw = meas.textlength(args.pre, font=pf)
            d.text(((w - pw) / 2, y_pre - ink_top(d, args.pre, pf)), args.pre,
                   font=pf, fill=pre_col[:3] + (int(255 * head_p),))

        if eyebrow:
            if args.variant == "type":
                n = int(max(0.0, t - e_t0) / 0.022) if t >= e_t0 else 0
                shown = eyebrow[:n]
                if shown:
                    draw_tracked(d, ((w - ew) / 2, y_eyebrow - ink_top(d, eyebrow, ef)),
                                 shown, ef, ey_col, e_track)
                if n < len(eyebrow):  # block caret
                    cx = (w - ew) / 2 + tracked_width(d, shown, ef, e_track) \
                        + (e_track if shown else 0)
                    d.rectangle([cx, y_eyebrow, cx + eyebrow_size * 0.55,
                                 y_eyebrow + eh], fill=ey_col)
            else:
                p = ease_out((t - e_t0) / e_dur)
                if p > 0:
                    draw_tracked(d, ((w - ew) / 2, y_eyebrow - ink_top(d, eyebrow, ef)),
                                 eyebrow, ef, ey_col[:3] + (int(255 * p),), e_track)

        if args.variant == "track":
            p = ease_out((t - w_t0) / 0.55)
            if p > 0:
                cur = (0.10 + (brand["title_tracking"] - 0.10) * p) * title_size
                cw = sum(tracked_width(d, wd, tf, cur) for wd in words) \
                    + (meas.textlength(" ", font=tf) + cur) * (len(words) - 1)
                draw_tracked(d, ((w - cw) / 2, y_title - ink_top(d, args.title, tf)),
                             " ".join(words), tf, bright[:3] + (int(255 * p),), cur)
        else:
            x = (w - tw) / 2
            it_full = ink_top(d, args.title, tf)  # shared so baselines align
            for i, wd in enumerate(words):
                p = ease_out((t - (w_t0 + i * w_stag)) / w_dur)
                if args.variant in ("words", "type"):
                    fill = lerp(dim[:3], bright[:3], p) + (255,)
                    dy = 0
                else:  # rise
                    fill = bright[:3] + (int(255 * p),)
                    dy = int((1 - p) * 26 * gscale)
                if p > 0 or args.variant in ("words", "type"):
                    draw_tracked(d, (x, y_title + dy - it_full),
                                 wd, tf, fill, t_track)
                x += word_w[i] + space_w

        if args.subtitle:
            p = ease_out((t - s_t0) / 0.3)
            if p > 0:
                d.text(((w - sw) / 2, y_subtitle - ink_top(d, args.subtitle, sf)),
                       args.subtitle, font=sf, fill=sub_col[:3] + (int(255 * p),))
        if wm:
            p = ease_out((t - m_t0) / 0.3)
            if p > 0:
                fader = wm.copy()
                fader.putalpha(fader.getchannel("A").point(lambda a: int(a * p)))
                img.alpha_composite(fader, ((w - wm.width) // 2,
                                            h - wm.height - int(WM_FOOT * gscale)))
        return img

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(args.duration * args.fps)
    with tempfile.TemporaryDirectory() as td:
        for i in range(n_frames):
            frame(i / args.fps).convert("RGB").save(f"{td}/f{i:04d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(args.fps),
                        "-i", f"{td}/f%04d.png", "-c:v", "prores", "-profile:v", "2",
                        "-pix_fmt", "yuv422p10le", str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
