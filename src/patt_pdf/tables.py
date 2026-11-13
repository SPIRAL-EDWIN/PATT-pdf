"""Column boundaries for table rows, so that each cell becomes its own translation unit.

Without this, a header row such as "params  dimension  n heads  n layers" is one sentence
for the translator whenever the gaps between its cells are narrower than the general
tab-stop threshold (1.6 × font size); the translation comes back without columns.

Two sources, both read from the page itself:

* ruled tables: vertical rules. Text on both sides of a rule belongs to different cells.
* tables without rules (three-line tables in papers): the rows of the table body. Rows
  that sit on the same columns, at least two rows of at least three cells, define gutters;
  a neighbouring row (the header) is cut where its own gaps fall into those gutters.

PyMuPDF's `find_tables` was tried first. It is reliable for ruled tables but picked a chart
legend instead of the table on a real paper page, so the body rows are used instead.

`line_cuts(pg, rawdict)` returns {(block index, line index): {"cuts": [x, ...], "L": bool,
"R": bool}}: x positions inside a gap of that line where a cell ends, and whether the line
itself ends at a cell boundary on its left / right (PDF producers often store every cell
as a line of its own; such neighbours must not be joined into one sentence either).
"""
from __future__ import annotations

import math

import pymupdf

MIN_COLS = 3            # fewer columns look like ordinary two-column text
MIN_BODY_ROWS = 2
GAP_FACTOR = 1.6        # same tab-stop rule as extract_text
MIN_CELL_GAP = 0.45     # × font size; a word space is 0.25-0.33


def vertical_rules(pg) -> list[tuple[float, float, float]]:
    """(x, y0, y1) of vertical rules: lines, thin filled rectangles, edges of stroked boxes."""
    out = []
    for d in pg.get_drawings():
        stroked = d.get("color") is not None
        for it in d.get("items", []):
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) < 0.3 and abs(p1.y - p2.y) > 2:
                    out.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
            elif it[0] in ("re", "qu"):
                r = pymupdf.Rect(it[1] if it[0] == "re" else it[1].rect)
                if r.width <= 2.5 and r.height > 3 * max(r.width, 0.1):
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif stroked and r.width > 4 and r.height > 4:
                    out.append((r.x0, r.y0, r.y1)); out.append((r.x1, r.y0, r.y1))
    return out


def _lines(d):
    """Horizontal text lines with their non-space characters, gaps and tab-stop segments."""
    out = []
    for bi, b in enumerate(d["blocks"]):
        if b.get("type") != 0:
            continue
        for li, l in enumerate(b["lines"]):
            if abs(l["dir"][1]) > 0.05:
                continue
            chars = [(c["bbox"][0], c["bbox"][2], sp["size"], c["origin"][1])
                     for sp in l["spans"] for c in sp["chars"] if c["c"].strip()]
            if not chars:
                continue
            chars.sort()
            size = sorted(c[2] for c in chars)[len(chars) // 2]
            gaps, segs, start = [], [], chars[0][0]
            for a, b_ in zip(chars, chars[1:]):
                g = b_[0] - a[1]
                if g > 0:
                    gaps.append((a[1], b_[0]))
                if g > GAP_FACTOR * max(a[2], b_[2]):
                    segs.append((start, a[1])); start = b_[0]
            segs.append((start, chars[-1][1]))
            out.append(dict(key=(bi, li), y0=l["bbox"][1], y1=l["bbox"][3], base=chars[0][3], size=size,
                            x0=chars[0][0], x1=chars[-1][1], gaps=gaps, segs=segs))
    return out


def _rows(lines):
    """Visual rows: lines on one baseline, whatever block they are in."""
    rows = []
    for ln in sorted(lines, key=lambda l: (l["base"], l["x0"])):
        r = rows[-1] if rows else None
        if r is not None and abs(r["base"] - ln["base"]) < 0.35 * max(r["size"], ln["size"]):
            r["lines"].append(ln); r["segs"] = sorted(r["segs"] + ln["segs"])
            r["x0"] = min(r["x0"], ln["x0"]); r["x1"] = max(r["x1"], ln["x1"])
        else:
            rows.append(dict(base=ln["base"], size=ln["size"], lines=[ln], segs=sorted(ln["segs"]),
                             x0=ln["x0"], x1=ln["x1"]))
    return rows


def _aligned(a, b, size) -> bool:
    """Two rows sit on the same columns."""
    if len(a) != len(b):
        return False
    for (a0, a1), (b0, b1) in zip(a, b):
        if min(a1, b1) - max(a0, b0) <= 0 and abs((a0 + a1) / 2 - (b0 + b1) / 2) > 1.0 * size:
            return False
    return True


def _bodies(rows):
    """Runs of at least MIN_BODY_ROWS rows with the same >= MIN_COLS columns."""
    out, used = [], set()
    for i, r in enumerate(rows):
        if i in used or len(r["segs"]) < MIN_COLS:
            continue
        run = [i]
        for j in range(i + 1, len(rows)):
            last = rows[run[-1]]
            if rows[j]["base"] - last["base"] > 3.2 * r["size"]:
                break
            if j not in used and abs(rows[j]["size"] - r["size"]) < 0.3 * r["size"] \
                    and _aligned(r["segs"], rows[j]["segs"], r["size"]):
                run.append(j)
        if len(run) >= MIN_BODY_ROWS:
            used.update(run); out.append(run)
    return out


def line_cuts(pg, d) -> dict:
    lines = _lines(d)
    info: dict = {}

    def entry(ln):
        return info.setdefault(ln["key"], {"cuts": [], "L": False, "R": False})

    def add(ln, x):
        entry(ln)["cuts"].append(x)

    def split_row(r):
        """Neighbouring lines of one row are separate cells."""
        ls = sorted(r["lines"], key=lambda l: l["x0"])
        for a, b in zip(ls, ls[1:]):
            entry(a)["R"] = True; entry(b)["L"] = True

    rows = _rows(lines)
    # ---- ruled tables
    rules = vertical_rules(pg)
    if rules:
        for ln in lines:
            mid, h = (ln["y0"] + ln["y1"]) / 2, ln["y1"] - ln["y0"]
            for x, y0, y1 in rules:
                if y0 <= mid <= y1 and y1 - y0 >= 0.8 * h and ln["x0"] < x < ln["x1"]:
                    for g0, g1 in ln["gaps"]:
                        if g0 - 0.5 <= x <= g1 + 0.5:
                            add(ln, (g0 + g1) / 2); break
        for r in rows:
            ls = sorted(r["lines"], key=lambda l: l["x0"])
            for a, b in zip(ls, ls[1:]):
                mid = (max(a["y0"], b["y0"]) + min(a["y1"], b["y1"])) / 2
                if any(a["x1"] - 0.5 <= x <= b["x0"] + 0.5 and y0 <= mid <= y1 for x, y0, y1 in rules):
                    entry(a)["R"] = True; entry(b)["L"] = True
    # ---- tables without rules
    for run in _bodies(rows):
        body = [rows[i] for i in run]
        size = body[0]["size"]
        n = len(body[0]["segs"])
        gutters = []
        for k in range(n - 1):
            left = max(r["segs"][k][1] for r in body); right = min(r["segs"][k + 1][0] for r in body)
            if right - left > 0.3 * size:
                gutters.append((left, right))
        if len(gutters) < MIN_COLS - 1:
            continue
        for r in body:
            split_row(r)
        x0 = min(r["x0"] for r in body); x1 = max(r["x1"] for r in body)
        top, bottom = body[0]["base"], body[-1]["base"]
        inrun = set(run)
        need = max(2, math.ceil(0.6 * len(gutters)))
        for i, r in enumerate(rows):
            if i in inrun or not (top - 3.5 * size <= r["base"] <= bottom + 3.5 * size):
                continue
            if abs(r["size"] - size) > 0.3 * size or r["x0"] < x0 - 2 * size or r["x1"] > x1 + 2 * size:
                continue
            found = []                                    # per gutter that this row respects
            for left, right in gutters:
                best = None
                for ln in r["lines"]:
                    for g0, g1 in ln["gaps"]:
                        if g1 - g0 > MIN_CELL_GAP * size and min(g1, right) - max(g0, left) > 0:
                            if best is None or g1 - g0 > best[2]:
                                best = (ln, (g0 + g1) / 2, g1 - g0)
                if best is None:                          # the row may be stored as one line per cell
                    edges = sorted((ln["x0"], ln["x1"]) for ln in r["lines"])
                    if any(b[0] - a[1] > 0 and min(b[0], right) - max(a[1], left) > 0 for a, b in zip(edges, edges[1:])):
                        found.append(None)
                else:
                    found.append(best)
            if len(found) >= need:
                split_row(r)
                for f in found:
                    if f is not None:
                        add(f[0], f[1])
    for v in info.values():
        v["cuts"] = sorted(set(round(x, 2) for x in v["cuts"]))
    return info
