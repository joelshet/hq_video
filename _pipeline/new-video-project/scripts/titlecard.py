#!/usr/bin/env python3
"""Card layout module: brand loading, fonts, tracked text, wordmark placement.

Not a CLI. cardanim.py imports these helpers and constants so animated cards
have one source of truth for the full-card layout (opaque brand background,
content centered, wordmark at the foot).

Brand keys (all optional, defaults below): colors are RGBA arrays; "wordmark"
is a PNG path relative to the brand.json; "fonts" (title), "fonts_regular"
(subtitle), "fonts_mono" (eyebrow) are tried in order; "title_tracking"/
"eyebrow_tracking" are letter-spacing in em (site uses -0.05em on headings,
+0.05em on eyebrows). Brand files merge over the defaults in order, later
wins — variant files (brand-hook.json) hold only their deltas and are passed
AFTER brand.json.
"""
import sys
from pathlib import Path

from PIL import Image, ImageFont

from common import read_json

DEFAULT_BRAND = {
    "canvas": [1920, 1080],
    # Placeholder tokens; _templates/brand.json overrides with the real brand
    "panel_color": [20, 22, 26, 247],
    "panel_border_color": [58, 63, 72, 255],
    "text_color": [255, 255, 255, 255],
    "subtitle_color": [190, 196, 205, 255],
    "accent_color": [235, 184, 75, 255],
    "eyebrow_color": [235, 184, 75, 255],
    "title_size": 92,
    "subtitle_size": 42,
    "eyebrow_size": 26,
    "title_tracking": -0.04,
    "eyebrow_tracking": 0.10,
    "corner_radius": 28,
    "wordmark": None,   # PNG path relative to brand.json (center/full cards)
    "fonts": [
        "~/Library/Fonts/Geist-SemiBold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Neue Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "fonts_regular": [
        "~/Library/Fonts/Geist-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ],
    "fonts_mono": [
        "~/Library/Fonts/GeistMono-Medium.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
    ],
}

# Full-card layout constants shared with cardanim.py — one source of truth so
# animated and static full-screen cards stay pixel-identical.
FULL_GAP_EYEBROW = 34   # eyebrow -> title
FULL_GAP_SUBTITLE = 30  # title -> subtitle
WM_HEIGHT = 30          # wordmark height
WM_FOOT = 80            # wordmark distance from the bottom edge


def load_brand(paths):
    """Merge brand JSONs over DEFAULT_BRAND in order (later wins).

    Returns (brand, brand_dir); logo paths resolve relative to brand_dir
    (the last file's parent). Variant files hold only their deltas.
    """
    brand = dict(DEFAULT_BRAND)
    brand_dir = Path.cwd()
    for path in paths or []:
        brand.update(read_json(path, "brand file"))
        brand_dir = Path(path).expanduser().parent
    return brand, brand_dir


def stack_ys(total_h, rows):
    """Vertically center a stack of (height, gap_after) rows in total_h.

    Returns each row's y. Absent rows pass (0, 0) and land harmlessly on
    their neighbor's y.
    """
    block = sum(rh + gap for rh, gap in rows)
    y = (total_h - block) // 2
    ys = []
    for rh, gap in rows:
        ys.append(y)
        y += rh + gap
    return ys


def load_font(candidates, size):
    for path in candidates:
        p = Path(path).expanduser()
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    print("WARNING: no brand font found, using PIL default", file=sys.stderr)
    return ImageFont.load_default(size)


def tracked_width(d, text, font, tracking_px):
    if not text:
        return 0
    return sum(d.textlength(c, font=font) for c in text) + tracking_px * (len(text) - 1)


def draw_tracked(d, xy, text, font, fill, tracking_px):
    x, y = xy
    for c in text:
        d.text((x, y), c, font=font, fill=fill)
        x += d.textlength(c, font=font) + tracking_px


def ink_top(d, text, font):
    """y offset from draw origin to the first ink pixel (for optical stacking)."""
    return d.textbbox((0, 0), text, font=font)[1]


def ink_height(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


def load_logo(brand, key, brand_dir):
    rel = brand.get(key)
    if not rel:
        return None
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = brand_dir / rel
    if not p.exists():
        print(f"WARNING: {key} not found at {p}", file=sys.stderr)
        return None
    return Image.open(p).convert("RGBA")


def scaled_logo(logo, height):
    w = int(logo.width * height / logo.height)
    return logo.resize((w, int(height)), Image.LANCZOS)

