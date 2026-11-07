"""Page classification: text / vector (outlined glyphs) / raster (scan) / vector_few /
graphics / blank.

Origin: the prototype's classify_page. Changed after the synthetic baseline
(docs/BASELINE.md), where short pages were wrongly skipped as "blank":
* a page is "text" as soon as its text layer has >= 3 Latin letters (was: >= 40 chars);
* "vector" is detected from many *small, filled* paths (glyph outlines) instead of a
  fixed total-drawing count of 150, so short outlined pages are no longer skipped;
* "raster" requires images covering > 60 % of the page with (almost) no text layer.
A page with both a real text layer and a large image stays "text"; text inside the
image is then reported (not translated) by the image-text policy.

v0.2 (review finding): pages without a text layer were "blank" (QA pass, no checks) even
when they carried a few outlined glyphs, e.g. a two-word label printed to outlines.
* "vector_few": 3-19 glyph-like paths and no text layer: possibly short outlined text;
  OCR'd when available, otherwise reported as unverified.
* "graphics": drawings or small images but no text layer and no glyph-like paths
  (charts, rules, logos); embedded images are still inspected.
* "blank": nothing on the page at all.
"""
from __future__ import annotations

import re

import pymupdf

LATIN = re.compile(r"[A-Za-z]")


def _image_fraction(pg) -> float:
    area = pg.rect.width * pg.rect.height
    img = 0.0
    for info in pg.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & pg.rect
        if not r.is_empty:
            img += r.width * r.height
    return img / area if area else 0.0


def _glyph_like_paths(pg) -> int:
    """Count small filled paths (typical of text converted to outlines)."""
    n = 0
    for d in pg.get_cdrawings():
        r = pymupdf.Rect(d["rect"])
        if d.get("fill") is not None and 0 < r.width < 40 and 0 < r.height < 40:
            n += 1
    return n


def classify_page(pg) -> str:
    txt = pg.get_text()
    latin = len(LATIN.findall(txt))
    imgfrac = _image_fraction(pg)
    if latin >= 3 and not (imgfrac > 0.6 and latin < 40):
        return "text"
    if imgfrac > 0.6:
        return "raster"
    glyphs = _glyph_like_paths(pg)
    if glyphs >= 20:
        return "vector"
    if latin >= 1:
        return "text"
    if imgfrac >= 0.05:
        return "raster"
    if glyphs >= 3:
        return "vector_few"
    if pg.get_cdrawings() or pg.get_image_info():
        return "graphics"
    return "blank"
