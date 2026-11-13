"""Underlines, strike-through lines and link areas attached to translated text.

A PDF has no "underline" text attribute. Underlines are separate vector lines (or thin
filled rectangles) drawn near a text baseline, and link areas are annotation rectangles.
Neither moves when PATT-PDF replaces the text, so a short Chinese title keeps an underline
of the English length, and MuPDF's redaction step deletes every link annotation that
overlaps an erased glyph.

What this module does, and what it deliberately does not do:

* A *decoration* is a single thin horizontal segment (stroked line or filled rectangle,
  thickness <= max(2.5 pt, 0.2 x font size)) lying between 0.55 x size above and 0.45 x
  size below a translated line's baseline, that does not reach more than
  max(3 pt, 0.8 x size) past the text on either side and is not joined to a vertical line
  at either end. Long rules (separators, table borders) and grid lines are therefore
  ignored, i.e. left exactly as they are.
* Full-line decorations (covering >= 85 % of the line) are removed and redrawn under every
  line of the translation with the same colour, thickness, dash pattern and baseline
  offset (offset scaled if the text was shrunk).
* Partial decorations (e.g. an underlined e-mail address inside a sentence) are moved only
  if the underlined source words occur verbatim in the translation; otherwise they are
  left in place and the page becomes `review`.
* Links are snapshotted before editing and restored afterwards; their target never
  changes. Link rectangles over translated text are remapped like decorations; when that
  is not possible the original rectangle is kept and the page becomes `review`. A link
  whose target disappeared is a `fail`.
* Underlines inside images (scans) and under outlined (vector) glyphs, markup
  annotations (Underline/StrikeOut/Squiggly/Highlight) and decorations drawn as part of a
  larger path are only *reported* (`review`); nothing is changed.

Visual misplacement in general (e.g. a box or arrow pointing at a word that moved) is not
detected.
"""
from __future__ import annotations

import numpy as np
import pymupdf

from .fonts import font

TOL_END = (3.0, 0.8)      # max overhang past the text: max(3 pt, 0.8 x size)
FULL = 0.85               # share of the line a full-line decoration must cover
_MARKUP = {pymupdf.PDF_ANNOT_UNDERLINE, pymupdf.PDF_ANNOT_STRIKE_OUT,
           pymupdf.PDF_ANNOT_SQUIGGLY, pymupdf.PDF_ANNOT_HIGHLIGHT}


def _segments(pg):
    """Thin horizontal segments and vertical segments of all drawings on the page."""
    hs, vs = [], []
    for di, d in enumerate(pg.get_drawings()):
        items = d.get("items", [])
        single = len(items) == 1
        if not single and _one_horizontal_line(items):
            # a line drawn there and back again (e.g. a closed path "m l h" from some generators)
            # is still one line: treat it as a single segment
            xs = [pt.x for it in items for pt in it[1:3]]
            y = items[0][1].y
            items = [("l", pymupdf.Point(min(xs), y), pymupdf.Point(max(xs), y))]
            single = True
        for it in items:
            op = it[0]
            if op == "l":
                p1, p2 = it[1], it[2]
                w = d.get("width") or 1.0
                if abs(p1.y - p2.y) < 0.3 and d.get("color") is not None:
                    x0, x1 = sorted((p1.x, p2.x))
                    hs.append(dict(x0=x0, x1=x1, y=(p1.y + p2.y) / 2, t=w, color=d.get("color"),
                                   fill=None, dashes=d.get("dashes"), cap=d.get("lineCap"),
                                   opacity=d.get("stroke_opacity", 1), single=single, di=di, op="l"))
                elif abs(p1.x - p2.x) < 0.3:
                    vs.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
            elif op in ("re", "qu"):
                r = it[1] if op == "re" else it[1].rect
                r = pymupdf.Rect(r)
                if r.height <= 2.5 and r.width > 3 * r.height and d.get("fill") is not None:
                    hs.append(dict(x0=r.x0, x1=r.x1, y=(r.y0 + r.y1) / 2, t=r.height, color=None,
                                   fill=d.get("fill"), dashes=None, cap=None,
                                   opacity=d.get("fill_opacity", 1), single=single, di=di, op="re"))
                elif r.width <= 2.5 and r.height > 3 * r.width:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    return hs, vs


def _one_horizontal_line(items) -> bool:
    """All items are horizontal line segments on the same y that overlap each other."""
    if not items or any(it[0] != "l" for it in items):
        return False
    y = items[0][1].y
    if any(abs(pt.y - y) > 0.3 for it in items for pt in it[1:3]):
        return False
    spans = sorted(tuple(sorted((it[1].x, it[2].x))) for it in items)
    reach = spans[0][1]
    for a, b in spans[1:]:
        if a > reach + 0.3:
            return False                     # a gap: dashes or separate lines, not one line
        reach = max(reach, b)
    return True


def _joined_to_vertical(s, vs):
    for x, y0, y1 in vs:
        if y0 - 1.5 <= s["y"] <= y1 + 1.5 and (abs(x - s["x0"]) < 1.5 or abs(x - s["x1"]) < 1.5):
            return True
    return False


def _words_in(pg_words, line, x0, x1):
    lx0, ly0, lx1, ly1 = line[:4]
    ws = [w for w in pg_words if (w[1] + w[3]) / 2 > ly0 - 0.5 and (w[1] + w[3]) / 2 < ly1 + 0.5
          and x0 - 1 <= (w[0] + w[2]) / 2 <= x1 + 1]
    return " ".join(w[4] for w in sorted(ws, key=lambda w: w[0]))


def find(pg, units):
    """Decorations attached to translated, horizontal text units (call BEFORE editing)."""
    hs, vs = _segments(pg)
    # lines that are the appearance of a markup annotation are reported by markup_annotations()
    marks = [pymupdf.Rect(a.rect) + (-1, -1, 1, 1) for a in (pg.annots() or []) if a.type[0] in _MARKUP]
    hs = [s for s in hs if not any(pymupdf.Rect(s["x0"], s["y"] - 0.1, s["x1"], s["y"] + 0.1) in m for m in marks)]
    words = pg.get_text("words")
    found, used = [], set()
    for u in units:
        if not u.tgt or u.kind == "keep":
            continue
        for li, line in enumerate(u.lines):
            lx0, ly0, lx1, ly1, base = line[:5]
            tol = max(TOL_END[0], TOL_END[1] * u.size)
            for si, s in enumerate(hs):
                if si in used or s["t"] > max(2.5, 0.2 * u.size):
                    continue
                if not (base - 0.55 * u.size <= s["y"] <= base + 0.45 * u.size):
                    continue
                if s["x0"] < lx0 - tol or s["x1"] > lx1 + tol or s["x1"] - s["x0"] < 2:
                    continue
                if _joined_to_vertical(s, vs):
                    continue
                cover = (min(s["x1"], lx1) - max(s["x0"], lx0)) / max(lx1 - lx0, 1e-6)
                if cover <= 0.05:
                    continue
                used.add(si)
                d = dict(s, uid=u.uid, line=li, offset=s["y"] - base, full=cover >= FULL)
                if not d["full"]:
                    d["words"] = _words_in(words, line, s["x0"], s["x1"])
                found.append(d)
    return found


def flag_unhandled(pg, units, decos):
    """Report decorations PATT-PDF does not move: under rotated or outlined text, in images,
    or drawn as part of a larger path. Returns issues; the matching decos are dropped."""
    issues, keep = [], []
    by_uid = {u.uid: u for u in units}
    for d in decos:
        u = by_uid[d["uid"]]
        why = None
        if u.angle:
            why = "rotated text"
        elif u.kind != "text":
            why = f"{u.kind} text"
        elif not d["single"]:
            why = "part of a larger drawing"
        if why:
            issues.append({"issue": "decoration_not_adjusted", "uid": u.uid, "why": why,
                           "rect": [round(d["x0"], 1), round(d["y"], 1), round(d["x1"], 1)]})
        else:
            keep.append(d)
    return issues, keep


def remove(pg, decos):
    """Remove the given decorations (single-item paths only). Returns the ones that are gone."""
    if not decos:
        return []
    for d in decos:
        # MuPDF removes line art only if the *stroked* box is covered: round or square caps
        # extend half the line width past the end points, so pad by that much horizontally too
        h = d["t"] / 2 + 0.4
        pg.add_redact_annot(pymupdf.Rect(d["x0"] - h, d["y"] - h, d["x1"] + h, d["y"] + h),
                            fill=False, cross_out=False)
    pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                        graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                        text=pymupdf.PDF_REDACT_TEXT_NONE)
    hs, _ = _segments(pg)
    gone = []
    for d in decos:
        still = any(abs(s["y"] - d["y"]) < 0.3 and abs(s["x0"] - d["x0"]) < 0.3 and abs(s["x1"] - d["x1"]) < 0.3
                    for s in hs)
        if not still:
            gone.append(d)
    return gone


def _locate(u, text):
    """Spans [(x0, x1, baseline, size, line_index)] where `text` is drawn in the translation."""
    if not text or not getattr(u, "_drawn", None):
        return []
    fnt = font(u.family, u.bold)
    for i, (x, ln, base, s) in enumerate(u._drawn):
        k = ln.find(text)
        if k >= 0:
            a = x + fnt.text_length(ln[:k], fontsize=s)
            return [(a, a + fnt.text_length(text, fontsize=s), base, s, i)]
    return []


def _full_spans(u):
    fnt = font(u.family, u.bold)
    return [(x, x + fnt.text_length(ln, fontsize=s), base, s, i) for i, (x, ln, base, s) in enumerate(u._drawn)]


def redraw(pg, units, removed, not_removed):
    """Draw removed decorations at the new text position. Returns (issues, drawn_specs)."""
    by_uid = {u.uid: u for u in units}
    issues, specs = [], []
    for d in not_removed:
        issues.append({"issue": "decoration_not_adjusted", "uid": d["uid"], "why": "could not be removed safely",
                       "rect": [round(d["x0"], 1), round(d["y"], 1), round(d["x1"], 1)]})
    done = set()
    for d in removed:
        u = by_uid[d["uid"]]
        if d["full"]:
            key = (d["uid"], round(d["offset"], 1), round(d["t"], 2))
            if key in done:          # one underline per original style, drawn under every new line
                continue
            done.add(key)
            spans = _full_spans(u) if getattr(u, "_drawn", None) else []
        else:
            spans = _locate(u, d.get("words", ""))
        if not spans:
            # cannot map: put the original back exactly where it was and ask for review
            spans = [(d["x0"], d["x1"], None, None, None)]
            issues.append({"issue": "decoration_not_adjusted", "uid": d["uid"],
                           "why": "underlined words not found verbatim in the translation",
                           "rect": [round(d["x0"], 1), round(d["y"], 1), round(d["x1"], 1)]})
        for x0, x1, base, s, _ in spans:
            y = d["y"] if base is None else base + d["offset"] * (s / u.size)
            _draw(pg, d, x0, x1, y)
            specs.append(dict(x0=x0, x1=x1, y=y, t=d["t"], uid=d["uid"]))
    return issues, specs


def _draw(pg, d, x0, x1, y):
    if d["op"] == "l":
        kw = dict(color=d["color"], width=d["t"], stroke_opacity=d["opacity"] if d["opacity"] is not None else 1)
        if d["dashes"] and d["dashes"] not in ("[] 0", "[] 0.0"):
            kw["dashes"] = d["dashes"]
        cap = d["cap"]
        if isinstance(cap, (list, tuple)):
            cap = cap[0]
        if cap is not None:
            kw["lineCap"] = int(cap)
        pg.draw_line((x0, y), (x1, y), **kw)
    else:
        h = d["t"] / 2
        pg.draw_rect(pymupdf.Rect(x0, y - h, x1, y + h), color=None, fill=d["fill"],
                     fill_opacity=d["opacity"] if d["opacity"] is not None else 1)


def verify(pg, specs):
    """Every redrawn decoration must exist in the output with the intended geometry."""
    hs, _ = _segments(pg)
    bad = []
    for sp in specs:
        ok = any(abs(s["y"] - sp["y"]) < 0.6 and abs(s["x0"] - sp["x0"]) < 0.6 and abs(s["x1"] - sp["x1"]) < 0.6
                 and abs(s["t"] - sp["t"]) < 0.15 for s in hs)
        if not ok:
            bad.append({"issue": "decoration_check_failed", "uid": sp["uid"],
                        "rect": [round(sp["x0"], 1), round(sp["y"], 1), round(sp["x1"], 1)]})
    return bad


def vertical_rules(pg):
    """Vertical rules of the source page (call BEFORE editing)."""
    return _segments(pg)[1]


def crossings(units, vs):
    """Translated text drawn across a vertical rule (e.g. a table border) that the source text
    did not cross. PATT-PDF has no table model, so this is detected and reported (fail)."""
    issues = []
    for u in units:
        if not u.tgt or not getattr(u, "_drawn", None):
            continue
        src_spans = [(l[0], l[2], l[1], l[3]) for l in u.lines]
        fnt = font(u.family, u.bold)
        for x, ln, base, s in u._drawn:
            x1 = x + fnt.text_length(ln, fontsize=s)
            for vx, vy0, vy1 in vs:
                # rules span at least a line height; glyph stems of outlined text are shorter
                if vy1 - vy0 < 1.1 * s or not (x + 1 < vx < x1 - 1 and vy0 < base and vy1 > base - 0.7 * s):
                    continue
                if any(a + 1 < vx < b - 1 and vy0 < y1 and vy1 > y0 for a, b, y0, y1 in src_spans):
                    continue            # the source text crossed it too
                issues.append({"issue": "text_crosses_rule", "uid": u.uid, "x": round(vx, 1),
                               "line": ln[:40]})
                break
    return issues


# ---------------------------------------------------------------- links

# "nameddest" is how PyMuPDF reports named destinations (LaTeX/hyperref PDFs: citations,
# footnotes, section references); without it insert_link raises KeyError for LINK_NAMED.
_LINK_KEYS = ("kind", "uri", "page", "to", "file", "name", "nameddest", "zoom")


def snapshot_links(pg):
    return [dict(l, **{"from": pymupdf.Rect(l["from"])}) for l in pg.get_links()]


def restore_links(pg, before, units):
    """Re-create links deleted by redaction; remap rectangles over translated text."""
    issues, notes = [], 0
    tunits = [u for u in units if u.tgt and u.kind == "text" and not u.angle]
    plans = []
    for l in before:
        r = pymupdf.Rect(l["from"])
        new_r = r
        hit = [u for u in tunits if any((pymupdf.Rect(ln[:4]) & r).get_area() > 0.3 * max(min(r.get_area(), pymupdf.Rect(ln[:4]).get_area()), 0.01)
                                        for ln in u.lines)]
        if hit:
            u = hit[0]
            covered = [ln for ln in u.lines if (pymupdf.Rect(ln[:4]) & r).get_area() > 0.6 * pymupdf.Rect(ln[:4]).get_area()]
            fnt = font(u.family, u.bold)
            asc, desc = fnt.ascender, fnt.descender         # descender is negative

            def box(x0, x1, base, s):
                return pymupdf.Rect(x0, base - asc * s, x1, base - desc * s)
            if len(covered) == len(u.lines) and getattr(u, "_drawn", None):
                rects = [box(x0, x1, base, s) for x0, x1, base, s, _ in _full_spans(u)]
                new_r = rects[0]
                for rr in rects[1:]:
                    new_r |= rr
                notes += 1
            else:
                spans = _locate(u, l.get("_text", ""))
                if spans:
                    x0, x1, base, s, _ = spans[0]
                    new_r = box(x0, x1, base, s)
                    notes += 1
                else:
                    issues.append({"issue": "link_area_not_mapped", "uid": u.uid,
                                   "target": str(l.get("uri") or l.get("page")),
                                   "rect": [round(v, 1) for v in r]})
        plans.append((l, new_r))
    current = pg.get_links()
    for c in current:                       # rebuild every link from the snapshot: one source of truth
        pg.delete_link(c)
    for l, new_r in plans:
        d = {k: l[k] for k in _LINK_KEYS if k in l and l[k] is not None}
        d["from"] = new_r
        try:
            pg.insert_link(d)
        except Exception as e:              # one unusual link must not abort the whole file
            issues.append({"issue": "link_lost", "target": str(l.get("uri") or l.get("nameddest") or l.get("page")),
                           "detail": f"could not be re-created ({type(e).__name__})"})
    # newly inserted links are only visible after the page is reloaded, so the target
    # comparison is done on the saved file (jobs._compare_links)
    return issues, notes


def link_texts(pg, links):
    """Attach the source words under each link rectangle (used to find them in the translation)."""
    words = pg.get_text("words")
    for l in links:
        r = pymupdf.Rect(l["from"])
        ws = [w for w in words if pymupdf.Rect(w[:4]).intersects(r)
              and (pymupdf.Rect(w[:4]) & r).get_area() > 0.5 * pymupdf.Rect(w[:4]).get_area()]
        l["_text"] = " ".join(w[4] for w in sorted(ws, key=lambda w: (round(w[3]), w[0])))
    return links


# ---------------------------------------------------------------- reporting only

def markup_annotations(pg, units):
    issues = []
    tunits = [u for u in units if u.tgt]
    for a in pg.annots() or []:
        if a.type[0] in _MARKUP and any(pymupdf.Rect(u.bbox).intersects(a.rect) for u in tunits):
            issues.append({"issue": "markup_annotation_on_translated_text", "type": a.type[1],
                           "rect": [round(v, 1) for v in a.rect]})
    return issues


def image_underlines(pg, units, dpi=150):
    """Scanned/raster lines: look for a long dark horizontal run just under each translated
    line. Only reported (`review`); the pixels are not changed."""
    issues = []
    for u in units:
        if not u.tgt or u.kind not in ("raster", "imgtext"):
            continue
        for line in u.lines:
            x0, y0, x1, y1 = line[:4]
            h = max(y1 - y0, 4)
            clip = pymupdf.Rect(x0, y0 + 0.5 * h, x1, y1 + 0.6 * h) & pg.rect
            if clip.is_empty or clip.width < 10:
                continue
            pm = pg.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csGRAY)
            a = np.frombuffer(pm.samples, np.uint8).reshape(pm.h, pm.w).astype(int)
            bg = np.median(a)
            dark = (a < bg - 60).mean(axis=1)
            if dark.size and dark.max() > 0.7:
                issues.append({"issue": "possible_underline_in_image", "uid": u.uid,
                               "rect": [round(v, 1) for v in (x0, y0, x1, y1)]})
                break
    return issues

