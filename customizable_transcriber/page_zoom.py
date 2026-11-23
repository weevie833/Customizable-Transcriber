"""Page zoom: send a two-page spread to Gemini as the full photo plus a
full-resolution crop of each page.

Why: a provider shrinks a large photo before the model reads it, so on a
high-resolution photo of two facing pages each letter loses most of its
pixels. Cropping each page lets the model see about twice the detail per
page. Measured 2026-09-24 on real registers (Gemini 3.1 Pro, 3 runs per
variant): Grimaldi Morti (4624x3472) went from 17 to 18-20 of 26 entries
with both names right; Montalto Uffugo Morti (3264x2448) from 12-14 to
17-18 of 23 surnames read correctly (mostly misread capital letters). Claude
Opus 5.5 showed no gain on Grimaldi, so the option only applies to Gemini.
One crop run of the six on Grimaldi skipped an entry, which is why this is
opt-in rather than a default.

The full photo is still sent first: without it, sending each page in its
own call cost twice as much with no accuracy gain in the same test.

Pillow only (no numpy/OpenCV) -- the gutter search runs on a small
grayscale thumbnail, so it's fast enough to run on every image.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Appended to the normal user instruction when the crops are sent.
PAGE_ZOOM_INSTRUCTION = (
    "\n\nYou are given three images of the SAME photograph. Image 1 is the full two-page "
    "spread, for layout and reading order only. Image 2 is a full-resolution crop of the LEFT "
    "page and Image 3 of the RIGHT page (they overlap slightly at the gutter). Read the "
    "handwriting from the crops. Transcribe each entry exactly once, in the same order and "
    "format you would use for the single full image."
)

# A gutter is a narrow dark line between two lighter pages, so it's scored
# as how much darker a ~1% wide strip is than the page on either side of it
# (broad stains and shadows score low), and each side on its own must be at
# least GUTTER_MIN_SIDE_CONTRAST lighter (the edge of a broad stain is dark
# on one side). Calibrated 2026-09-24 on 1,756 photos from six registers:
# 83-100% of each register's two-page photos cleared GUTTER_MIN_SCORE (the
# rest are sent whole), and 1 of 210 single-page photos did. Photos with the
# binding in frame put the gutter off-center, outside GUTTER_SEARCH_RANGE,
# and are mostly sent whole.
GUTTER_MIN_SCORE = 0.075
GUTTER_MIN_SIDE_CONTRAST = 0.02
# Only look for the gutter in the middle of the photo.
GUTTER_SEARCH_RANGE = (0.38, 0.62)
# Each page crop reaches this far (as a fraction of the photo's width) past
# the gutter, so a word written into the gutter isn't cut in half.
CROP_OVERLAP = 0.03
# Below this long edge the provider barely shrinks the photo, so there is
# little detail for the crops to recover (Montalto, 3264px, still gained).
SUGGEST_MIN_LONG_EDGE = 3000

_PROFILE_WIDTH = 800
# Analysis bounds (reviews/CODEX_REVIEW_8.md M-8): a photo narrower than the
# profile is never enlarged, a very tall or very wide one is not treated as
# a spread, and nothing over MAX_ANALYZE_PIXELS is decoded for the check.
MAX_SPREAD_ASPECT = 3.0
MAX_ANALYZE_PIXELS = 120_000_000


@dataclass(frozen=True)
class SpreadInfo:
    width: int
    height: int
    gutter_x: int | None  # in full-image pixels; None when no clear gutter

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)


def _column_profile(image: Image.Image) -> list[float]:
    """Mean brightness of each column of a small grayscale copy, ignoring
    the top and bottom 12% (hands, book edges, background)."""
    gray = image.convert("L")
    height = max(1, round(gray.height * _PROFILE_WIDTH / gray.width))
    gray = gray.resize((_PROFILE_WIDTH, height), Image.BILINEAR)
    band = gray.crop((0, int(height * 0.12), _PROFILE_WIDTH, max(int(height * 0.88), int(height * 0.12) + 1)))
    # A 1-pixel-tall box resize averages each column.
    row = band.resize((_PROFILE_WIDTH, 1), Image.BOX)
    return [float(row.getpixel((x, 0))) for x in range(_PROFILE_WIDTH)]


def _find_gutter(columns: list[float]) -> tuple[float, float]:
    """(position as a fraction of width, score) of the narrowest, darkest
    valley in the search range."""
    width = len(columns)
    inner, outer = 6, 24
    best_pos, best_score = 0.5, 0.0
    for x in range(int(width * GUTTER_SEARCH_RANGE[0]), int(width * GUTTER_SEARCH_RANGE[1])):
        center = sum(columns[x - 2 : x + 3]) / 5
        left = columns[max(0, x - outer) : x - inner]
        right = columns[x + inner + 1 : x + outer + 1]
        if not left or not right:
            continue
        left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
        darker_side = min(left_mean, right_mean)
        if (darker_side - center) / max(darker_side, 1.0) < GUTTER_MIN_SIDE_CONTRAST:
            continue
        side = (left_mean + right_mean) / 2
        score = (side - center) / max(side, 1.0)
        if score > best_score:
            best_pos, best_score = x / width, score
    return best_pos, best_score


def _analysable(width: int, height: int) -> bool:
    if width < _PROFILE_WIDTH or height < 1:
        return False
    return max(width / height, height / width) <= MAX_SPREAD_ASPECT


def analyze_spread(image: Image.Image) -> SpreadInfo:
    width, height = image.size
    if not _analysable(width, height):
        return SpreadInfo(width, height, None)
    position, score = _find_gutter(_column_profile(image))
    gutter = round(position * width) if score >= GUTTER_MIN_SCORE else None
    return SpreadInfo(width, height, gutter)


def analyze_file(path: Path) -> SpreadInfo:
    """Cheap check for Preflight: JPEG draft mode decodes at reduced size,
    so this doesn't decode the full photo."""
    with Image.open(path) as image:
        full_size = image.size
        # The header gives the size without decoding; refuse to decode a
        # photo too large, or of a shape that can't be a spread.
        if full_size[0] * full_size[1] > MAX_ANALYZE_PIXELS or not _analysable(*full_size):
            return SpreadInfo(full_size[0], full_size[1], None)
        # Draft decode to about a quarter size, but never below the profile
        # width, so analyze_spread() never has to enlarge it.
        target_width = max(_PROFILE_WIDTH, image.width // 4)
        image.draft("L", (target_width, max(1, round(image.height * target_width / image.width))))
        info = analyze_spread(image)
    scale = full_size[0] / info.width
    gutter = round(info.gutter_x * scale) if info.gutter_x is not None else None
    return SpreadInfo(full_size[0], full_size[1], gutter)


def page_crops(data: bytes) -> tuple[bytes, bytes] | None:
    """JPEG bytes of the left and right page, or None when the photo has no
    clear gutter (the caller then sends the full photo alone)."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        info = analyze_spread(image)
        if info.gutter_x is None:
            return None
        pad = round(CROP_OVERLAP * image.width)
        left = image.crop((0, 0, min(image.width, info.gutter_x + pad), image.height))
        right = image.crop((max(0, info.gutter_x - pad), 0, image.width, image.height))
        return _jpeg(left), _jpeg(right)


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=92)
    return buffer.getvalue()
