"""Text-layer pages: character-level extraction into translation units + keeps.

Migrated verbatim from prototype layout module (_pieces, plan_text_page); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import math
import re

import pymupdf

from .grouping import _group_cells, _para_to_unit, _rgb, _uid, mark_rows
from .keep import BOLD_HINT, HAS_LATIN, SEP_CHARS, font_family, is_keep
from .model import PagePlan, Unit
from .tables import line_cuts

def _pieces(line, cuts=()):
    """rawdict line -> list of pseudo-spans, split at visual separators like '|' and at
    table-cell boundaries (`cuts`: x positions from tables.line_cuts)."""
    out = []
    spans = line["spans"]
    last_ink = None                       # right edge of the last non-space character of the line
    for si, sp in enumerate(spans):
        cur = []
        cut_next = [False]
        def flush():
            if cur:
                t = "".join(c["c"] for c in cur)
                r = pymupdf.Rect(cur[0]["bbox"])
                for c in cur[1:]: r |= c["bbox"]
                out.append(dict(text=t, bbox=tuple(r), size=sp["size"], font=sp["font"], flags=sp["flags"],
                                color=sp["color"], origin=cur[0]["origin"], sep=t.strip() in SEP_CHARS,
                                cut=cut_next[0]))
                cut_next[0] = False
        prev = None
        for ch in sp["chars"]:
            if cuts and ch["c"].strip():
                if last_ink is not None and any(last_ink - 0.5 <= x <= ch["bbox"][0] + 0.5 for x in cuts):
                    while cur and not cur[-1]["c"].strip(): cur.pop()      # the space belongs to neither cell
                    flush(); cur = []; cut_next[0] = True; prev = None
                last_ink = ch["bbox"][2]
            if ch["c"] in SEP_CHARS:
                flush(); cur = [ch]; flush(); cur = []
            else:
                # PDFs without space glyphs: infer a word break from the horizontal gap
                if (prev is not None and cur and ch["c"] != " " and prev["c"] != " "
                        and ch["bbox"][0] - prev["bbox"][2] > 0.17 * sp["size"]):
                    cur.append(dict(c=" ", bbox=prev["bbox"], origin=prev["origin"]))
                cur.append(ch)
            prev = ch
        flush()
    return [o for o in out if o["text"].strip()]


def plan_text_page(pg, pno):
    d = pg.get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
    cells, keeps, rotated, rot_ends = [], [], [], []
    line_keep_cands = []
    cuts = line_cuts(pg, d)                 # table cells, see tables.py
    for bi, b in enumerate(d["blocks"]):
        if b.get("type") != 0: continue
        for li, l in enumerate(b["lines"]):
            tinfo = cuts.get((bi, li)) or {"cuts": (), "L": False, "R": False}
            spans = _pieces(l, tinfo["cuts"])
            if not spans: continue
            if abs(l["dir"][1]) > 0.05:      # rotated label -> own unit, drawn along the same angle
                t = re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip()
                if is_keep(t):
                    keeps.append(list(l["bbox"]) + [t]); continue
                chars = [c for sp in l["spans"] for c in sp["chars"]]
                o = chars[0]["origin"]; sp0 = l["spans"][0]
                ang = math.degrees(math.atan2(-l["dir"][1], l["dir"][0]))
                rotated.append(Unit(uid=_uid(pno, "rot", len(rotated), t), page=pno, kind="text", src=t,
                                    bbox=list(l["bbox"]), lines=[[o[0], o[1], o[0], o[1], o[1]]],
                                    size=sp0["size"], bold=bool(sp0["flags"] & 16) or bool(BOLD_HINT.search(sp0["font"])),
                                    family=font_family(sp0["font"], sp0["flags"]),
                                    color=_rgb(sp0["color"]), erase=[list(c["bbox"]) for c in chars if c["c"].strip()],
                                    angle=ang))
                last = chars[-1]["bbox"]
                rot_ends.append(((o[0], o[1]), ((last[0] + last[2]) / 2, (last[1] + last[3]) / 2)))
                continue
            # footnote markers: small raised spans -> unicode superscript, merged into neighbour
            SUP = str.maketrans("0123456789,-*†‡abcdefghijklmnopqrstuvwxyz", "⁰¹²³⁴⁵⁶⁷⁸⁹'⁻*†‡ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ")
            if len(spans) > 1:
                big = max(sp["size"] for sp in spans)
                for sp in spans:
                    t = sp["text"].strip()
                    if (sp["size"] < 0.8 * big and len(t) <= 4 and re.fullmatch(r"[0-9a-z,*†‡\-]+", t)
                            and sp["origin"][1] < max(o["origin"][1] for o in spans) - 0.15 * big):
                        sp["text"] = t.translate(SUP); sp["size"] = big; sp["sup"] = True
            # split a line into cells at wide gaps (tables / tab stops), size jumps, separators
            groups, cur = [], [spans[0]]
            for s in spans[1:]:
                gap = s["bbox"][0] - cur[-1]["bbox"][2]
                if (gap > 1.6 * max(s["size"], cur[-1]["size"]) or s["sep"] or cur[-1]["sep"] or s.get("cut")
                        or abs(s["size"] - cur[-1]["size"]) > 0.35 * cur[-1]["size"]):
                    groups.append(cur); cur = [s]
                else:
                    cur.append(s)
            groups.append(cur)
            for gi, g in enumerate(groups):
                # a table-cell boundary separates like a drawn separator: never re-joined later
                sepL = (gi > 0 and (groups[gi - 1][-1].get("sep") or g[0].get("cut"))) or (gi == 0 and tinfo["L"])
                sepR = ((gi + 1 < len(groups) and (groups[gi + 1][0].get("sep") or groups[gi + 1][0].get("cut")))
                        or (gi + 1 == len(groups) and tinfo["R"]))
                text = g[0]["text"]
                for a_, b_ in zip(g, g[1:]):
                    gap_ = b_["bbox"][0] - a_["bbox"][2]
                    sep_ = " " if (gap_ > 0.15 * b_["size"] and not text.endswith(" ") and not b_["text"].startswith(" ")
                                   and not b_.get("sup")) else ""
                    text += sep_ + b_["text"]
                text = re.sub(r"\s+", " ", text)
                r = pymupdf.Rect(g[0]["bbox"])
                for s in g[1:]: r |= s["bbox"]
                main = max([x for x in g if not x.get("sup")] or g, key=lambda s: len(s["text"].strip()))
                if is_keep(text):
                    if len(groups) == 1 and HAS_LATIN.search(text) is None and re.search(r"\d", text) and len(text.strip()) <= 12:
                        # whole-line figure: may be the tail of a wrapped sentence ("1988).") -> decide later
                        fname = main["font"]
                        line_keep_cands.append((len(keeps), dict(
                            x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, text=text, block=bi,
                            size=round(main["size"], 2), base=main["origin"][1],
                            bold=bool(main["flags"] & 16) or bool(BOLD_HINT.search(fname)),
                            family=font_family(fname, main["flags"]),
                            color=_rgb(main["color"]), erase=[list(x["bbox"]) for x in g])))
                    keeps.append([r.x0, r.y0, r.x1, r.y1, text.strip()]); continue
                fname = main["font"]
                cells.append(dict(
                    x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, text=text, block=bi,
                    size=round(main["size"], 2), base=main["origin"][1],
                    bold=bool(main["flags"] & 16) or bool(BOLD_HINT.search(fname)),
                    family=font_family(fname, main["flags"]),
                    color=_rgb(max(((sum(len(x["text"]) for x in g if x["color"] == c_), c_) for c_ in set(x["color"] for x in g)))[1]),
                    erase=[list(s["bbox"]) for s in g], sepL=bool(sepL), sepR=bool(sepR)))
    # absorb a whole-line figure into the paragraph it ends: a wrapped text line of the same
    # block/size directly above it, left-aligned with it
    drop = set()
    for ki, c in line_keep_cands:
        above = [x for x in cells if x["block"] == c["block"] and abs(x["size"] - c["size"]) < 0.6
                 and abs(x["x0"] - c["x0"]) < 2.5 * c["size"] and -0.4 * c["size"] < c["y0"] - x["y1"] < 0.8 * c["size"]]
        if above and not any(re.search(r"[.!?:]$", a["text"].strip()) for a in above):
            cells.append(c); drop.add(ki)
    if drop:
        keeps = [k for i, k in enumerate(keeps) if i not in drop]
        cells.sort(key=lambda x: (x["block"], x["y0"], x["x0"]))
    mark_rows(cells, keeps)
    units = [_para_to_unit(pno, "text", i, p) for i, p in enumerate(_group_cells(cells))]
    notes = []
    curved = curved_labels(rotated, rot_ends)
    if curved:
        # text set along a curve arrives as many short runs at different angles; translated
        # run by run it overlaps. It stays as it is and is listed in the report.
        notes.append({"curved_text": [rotated[i].src[:60] for i in sorted(curved)][:40], "curved_count": len(curved)})
        keeps += [list(rotated[i].bbox) + ["[rotated] " + rotated[i].src] for i in sorted(curved)]
        rotated = [u for i, u in enumerate(rotated) if i not in curved]
    return PagePlan(pno, "text", units + rotated, keeps, notes)


def curved_labels(rotated, ends) -> set:
    """Indexes of slanted runs that belong to text set along a curve. A straight slanted
    label (an arrow caption, an axis title) is one run, or several runs at one angle; it is
    translated at its angle. Curved text shows as runs that continue each other (the end of
    one is near the start of the next) while the angle changes, or as letter-spaced runs."""
    out = set()

    def axis(a):
        return min(abs(a % 90), 90 - abs(a % 90)) < 1.5

    for i, u in enumerate(rotated):
        if axis(u.angle):
            continue
        toks = u.src.split()
        if len(toks) >= 4 and sum(len(t) == 1 for t in toks) >= 0.6 * len(toks):
            out.add(i); continue                      # "S A N  A N D R E A S"
        for j, v in enumerate(rotated):
            if i == j or axis(v.angle):
                continue
            d = abs(u.angle - v.angle) % 360
            d = min(d, 360 - d)
            if not 0.8 < d < 45:
                continue
            reach = 3.0 * max(u.size, v.size)
            (us, ue), (vs, ve) = ends[i], ends[j]
            if math.hypot(ue[0] - vs[0], ue[1] - vs[1]) < reach or math.hypot(ve[0] - us[0], ve[1] - us[1]) < reach:
                out.add(i); break
    return out
