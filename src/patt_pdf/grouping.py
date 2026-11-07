"""Line/cell → paragraph grouping shared by text and OCR pages.

Migrated verbatim from prototype layout module (_rgb, _join, _uid, _merge_inline, _group_cells, _para_to_unit, mark_rows); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import hashlib
import re

import numpy as np

from .keep import BULLET_RE
from .model import Unit

def _rgb(c):
    if isinstance(c, int):
        return [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255]
    return list(c)


def _join(parts):
    """join line texts of a paragraph, repairing end-of-line hyphenation."""
    out = ""
    for p in parts:
        p = p.strip()
        if not out: out = p; continue
        if re.search(r"[A-Za-z]-$", out) and re.match(r"^[a-z]", p):
            out = out[:-1] + p
        elif re.search(r"\d-$", out) and re.match(r"^[A-Za-z]", p):
            out = out + p
        else:
            out += " " + p
    return re.sub(r"\s+", " ", out).strip()


def _uid(page, kind, i, src):
    h = hashlib.sha1(src.encode()).hexdigest()[:6]
    return f"p{page+1}-{kind}-{i}-{h}"


def _merge_inline(a, b):
    m = dict(a)
    m["text"] = a["text"].rstrip() + ("" if b["text"][:1] in "⁰¹²³⁴⁵⁶⁷⁸⁹,.;:)" else " ") + b["text"].lstrip()
    m["x1"] = max(a["x1"], b["x1"]); m["y0"] = min(a["y0"], b["y0"]); m["y1"] = max(a["y1"], b["y1"])
    m["erase"] = a.get("erase", [[a["x0"], a["y0"], a["x1"], a["y1"]]]) + b.get("erase", [[b["x0"], b["y0"], b["x1"], b["y1"]]])
    m["rownum"] = a.get("rownum") or b.get("rownum")
    return m


def _group_cells(cells, para_gap=0.75):
    """cells: dicts with x0,y0,x1,y1,size,bold,color,text,base,block. -> paragraphs"""
    """mode 'text': strict style equality, PyMuPDF block must match.
       mode 'ocr' : size tolerance 18 %, tesseract paragraph id is a strong hint."""
    ocr = para_gap >= 1.0
    bx1 = {}
    for c in cells:
        bx1[c.get("block")] = max(bx1.get(c.get("block"), 0), c["x1"])
    body = float(np.median([c["size"] for c in cells])) if cells else 10.0
    # typical line gap for body text on this page (double spacing etc.)
    gaps = []
    for a, b in zip(cells, cells[1:]):
        if abs(a["size"] - b["size"]) < 0.6 and abs(a["x0"] - b["x0"]) < 2.5 * b["size"]:
            g = b["y0"] - a["y1"]
            if 0 <= g < 3 * b["size"]: gaps.append(g / b["size"])
    typ = float(np.median(gaps)) if len(gaps) >= 4 else 0.0
    gap_lim = max(para_gap, min(2.6, typ * 1.3)) if typ > para_gap * 0.8 else para_gap
    paras = []
    for c in cells:
        p = paras[-1] if paras else None
        if p is not None:
            last = p[-1]
            s = max(c["size"], last["size"])
            if ocr:
                same_style = abs(last["size"] - c["size"]) < 0.18 * s and last["bold"] == c["bold"]
            else:
                same_style = abs(last["size"] - c["size"]) < 0.6 and last["bold"] == c["bold"]
            same_block = last.get("block") == c.get("block")
            vgap = c["y0"] - last["y1"]
            xover = min(last["x1"], c["x1"]) - max(last["x0"], c["x0"])
            # OCR: tesseract blocks can span body + sidebar, so measure the margin on the column itself
            ref = bx1[last.get("block")] if not ocr else max([x["x1"] for x in p] + [c["x1"]])
            wrapped = last["x1"] >= ref - 3.5 * s                    # previous line ran to the margin
            lt, nt = last["text"].strip(), c["text"].strip()
            heading = s >= 1.3 * body
            cont = (bool(re.match(r"^[a-z0-9(\"“'‘$%&,-]", nt)) or not re.search(r"[.:;!?)]$", lt)
                    or (heading and not re.search(r"[.:;!?]$", lt)))
            if c.get("bullet"):
                paras.append([c]); continue
            row_end = last.get("rownum", False)                       # table row with figures
            geom = (-0.35 * s < vgap < gap_lim * s and xover > 0 and abs(last["x0"] - c["x0"]) < 2.5 * s)
            same_line = abs(last["base"] - c["base"]) < 0.35 * s and 0 <= c["x0"] - last["x1"] < 1.6 * s
            if same_line and abs(last["size"] - c["size"]) < 0.25 * s and not (last.get("sepR") or c.get("sepL")):
                c = dict(c); p[-1] = _merge_inline(last, c); continue
            new_par_indent = (c["x0"] - last["x0"] > 0.6 * s and c["x0"] - last["x0"] < 4 * s
                              and (not wrapped or re.search(r"[.:!?]$", lt)) and len(p) >= 1)
            if new_par_indent and not ocr:
                paras.append([c]); continue
            if ocr and same_block and geom and abs(last["size"] - c["size"]) < 0.18 * s:
                p.append(c); continue
            # OCR: tesseract split one paragraph into several "pars" -> same region & block,
            # same size, tight pitch, left-aligned, previous line ran to the margin, no sentence end
            if (ocr and last.get("block", (None,))[:1] == c.get("block", (None,))[:1] and geom
                    and abs(last["size"] - c["size"]) < 0.12 * s and abs(last["x0"] - c["x0"]) < 0.8 * s
                    and wrapped and not re.search(r"[.!?:”\"]$", lt)):
                p.append(c); continue
            indent_first = len(p) == 1 and 0 < last["x0"] - c["x0"] < 4 * s
            near_block = same_block or (vgap < gap_lim * s and (abs(last["x0"] - c["x0"]) < 1.5 or indent_first))
            if same_style and geom and wrapped and cont and (not row_end or re.match(r"^[a-z]", nt)) and (near_block or ocr):
                p.append(c); continue
        paras.append([c])
    return paras


def _para_to_unit(page, kind, idx, para, family=None):
    src = _join([c["text"] for c in para])
    x0 = min(c["x0"] for c in para); y0 = min(c["y0"] for c in para)
    x1 = max(c["x1"] for c in para); y1 = max(c["y1"] for c in para)
    sizes = sorted(c["size"] for c in para)
    fam = family or para[0].get("family", "sans")
    align = "left"
    if len(para) >= 2:
        cs = [(c["x0"] + c["x1"]) / 2 for c in para]; ls = [c["x0"] for c in para]
        if max(cs) - min(cs) < 2.5 and max(ls) - min(ls) > 6: align = "center"
    erase = []
    for c in para: erase.extend(c.get("erase", [[c["x0"], c["y0"], c["x1"], c["y1"]]]))
    return Unit(uid=_uid(page, kind, idx, src), page=page, kind=kind, src=src,
                bbox=[x0, y0, x1, y1],
                lines=[[c["x0"], c["y0"], c["x1"], c["y1"], c["base"]] for c in para],
                size=sizes[len(sizes) // 2], bold=para[0]["bold"], family=fam,
                color=max(para, key=lambda c: sum(len(x["text"]) for x in para if x["color"] == c["color"]))["color"],
                align=align, erase=erase)


def mark_rows(cells, keeps):
    """flag cells that sit on a table row carrying figures to their right, and cells that
    start right after a bullet / list number (each list item = its own paragraph)"""
    for c in cells:
        h = c["y1"] - c["y0"]
        for k in keeps:
            if BULLET_RE.match(str(k[4]).strip()) and k[2] <= c["x0"] + 1 and c["x0"] - k[2] < 3 * c["size"]:
                ov = min(c["y1"], k[3]) - max(c["y0"], k[1])
                if ov > 0.4 * min(h, k[3] - k[1]): c["bullet"] = True; break
    for c in cells:
        h = c["y1"] - c["y0"]
        for k in keeps:
            if k[0] > c["x1"] and re.search(r"\d", str(k[4])):
                ov = min(c["y1"], k[3]) - max(c["y0"], k[1])
                if ov > 0.5 * min(h, k[3] - k[1]):
                    c["rownum"] = True; break
    return cells
