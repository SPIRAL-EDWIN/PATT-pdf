"""Chinese line wrapping and box fitting.

Migrated verbatim from prototype layout module (_wrap, fit_unit); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import re

from .fonts import font

_NO_LINE_START = set("，。、；：！？）】》」』”’%,.;:!?)]")


_NO_LINE_END = set("（【《「『“‘([")


_TOKEN = re.compile(r"[A-Za-z0-9$€£¥%.,'’\-/&+()]+[ ]?|\s|.", re.S)


def _wrap(text, fnt, size, width):
    if "\n" in text:
        return [l for part in text.split("\n") for l in _wrap(part, fnt, size, width)]
    toks = _TOKEN.findall(text)
    lines, cur, w = [], "", 0.0
    for t in toks:
        tw = fnt.text_length(t, fontsize=size)
        if cur and w + tw > width + 0.01 and not (t[:1] in _NO_LINE_START and len(t) == 1):
            carry = ""
            while cur and cur.rstrip()[-1:] in _NO_LINE_END:      # don't leave "（" dangling
                carry = cur.rstrip()[-1] + carry; cur = cur.rstrip()[:-1]
            lines.append(cur.rstrip()); cur = (carry + t).lstrip(); w = fnt.text_length(cur, fontsize=size)
        else:
            cur += t; w += tw
    if cur.strip(): lines.append(cur.rstrip())
    lines = [l for l in lines if l.strip()]
    return lines


def fit_unit(u, page_rect, obstacles=(), solid=None):
    """Return (fontsize, lines, pitch, box, ok). Shrinks font if needed; may widen
    single-line boxes to the right if free space exists."""
    fnt = font(u.family, u.bold)
    x0, y0, x1, y1 = u.bbox
    n0 = len(u.lines)
    pitch_ratio = 1.2
    if n0 >= 2:
        bases = [l[4] for l in u.lines]
        pitch_ratio = max(1.05, min(2.0, (bases[-1] - bases[0]) / (n0 - 1) / u.size))
    width = x1 - x0; height = y1 - y0
    tries = [(width, height)]
    wide = None
    if n0 in (2, 3) and u.align == "center":
        # a short label set in centred lines ("San" over "Francisco"): its translation reads
        # better on one line than broken to the width of the shortest source line
        need_w = fnt.text_length(u.tgt, fontsize=u.size)
        if width < need_w <= 3.2 * width and "\n" not in u.tgt:
            ext = (need_w - width) / 2 + 0.5
            cand = (x0 - ext, y0, x1 + ext, y1)
            if cand[0] > page_rect.x0 + 9 and cand[2] < page_rect.x1 - 9 and not any(
                    o[0] < cand[2] and o[2] > cand[0] and o[1] < y1 and o[3] > y0
                    and not (o[0] >= x0 - 0.01 and o[2] <= x1 + 0.01 and o[1] >= y0 - 0.01 and o[3] <= y1 + 0.01)
                    for o in (obstacles if solid is None else solid)):
                wide = cand
    if wide is not None:
        return u.size, [u.tgt], u.size * pitch_ratio, wide, True
    if n0 == 1:   # allow extension to the right (free space checked by caller)
        right = [o[0] for o in obstacles if o[0] >= x1 - 0.5 and o[1] < y1 and o[3] > y0]
        # stop short of the neighbour (a table cell, a label): text that touches it reads as one word
        free_r = min([o - 0.35 * u.size for o in right] + [page_rect.x1 - 18])
        if free_r > x1 + 2: tries.append((free_r - x0, height))
    s = u.size
    while s >= 0.55 * u.size:
        for wdt, hgt in tries:
            ls = _wrap(u.tgt, fnt, s, wdt)
            need = (len(ls) - 1) * s * pitch_ratio + s * 1.0
            if need <= hgt + 0.35 * u.size and (n0 > 1 or len(ls) == 1):
                return s, ls, s * pitch_ratio, (x0, y0, x0 + wdt, y1), True
        s *= 0.95
    s = 0.55 * u.size
    ls = _wrap(u.tgt, fnt, s, width)
    return s, ls, s * pitch_ratio, (x0, y0, x1, y1), False
