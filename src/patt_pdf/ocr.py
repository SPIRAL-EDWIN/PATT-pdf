"""OCR pages (vector glyphs and scans) via the Tesseract CLI (optional dependency).

Migrated verbatim from prototype layout module (_tesseract, _tesseract_multi, _recover_missed_words, _ocr_cells, render_rgb, plan_ocr_page); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import numpy as np
import pymupdf

from .grouping import _group_cells, _para_to_unit, mark_rows
from .keep import HAS_LATIN, is_keep
from .model import PagePlan

class OCRUnavailable(RuntimeError):
    """Tesseract (or its English data) is missing or failed."""


OCR_TIMEOUT_S = float(os.environ.get("PATT_PDF_OCR_TIMEOUT", "120"))


def ocr_dependency_problem() -> str | None:
    """Why OCR cannot run here, or None. OpenCV is imported lazily by the OCR functions, so an
    ImportError at module import time never happens; check it explicitly (it is missing e.g. on
    Windows arm64, where opencv-python-headless publishes no wheel)."""
    try:
        import importlib
        importlib.import_module("cv2")
    except ImportError as e:
        return (f"OCR dependencies missing ({e.name or 'cv2'}): install patt-pdf[ocr] "
                "(opencv-python-headless has no wheel for some platforms, e.g. Windows arm64)")
    return None


def tesseract_cmd() -> str:
    """Tesseract executable (osenv.find_tesseract): $PATT_PDF_TESSERACT, else PATH, else the
    default install folders of the OS. Raises OCRUnavailable with the reason."""
    from .osenv import find_tesseract
    exe, how = find_tesseract()
    if not exe:
        raise OCRUnavailable(f"{how}: install Tesseract or set PATT_PDF_TESSERACT to the executable")
    return exe


def _tesseract(png_bytes, psm=3):
    """Run Tesseract on a PNG; bounded by OCR_TIMEOUT_S. The child process is killed on
    timeout (subprocess.run does this) and the temp dir is always removed."""
    cmd = tesseract_cmd()
    env = dict(os.environ, OMP_THREAD_LIMIT="1")          # avoid thread oversubscription
    with tempfile.TemporaryDirectory(prefix="pattpdf-ocr-") as td:
        ip = os.path.join(td, "i.png")
        with open(ip, "wb") as fh:
            fh.write(png_bytes)
        try:
            res = subprocess.run([cmd, ip, "stdout", "-l", "eng", "--psm", str(psm), "tsv"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=OCR_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            raise OCRUnavailable(f"tesseract timed out after {OCR_TIMEOUT_S:.0f}s") from None
        except OSError as e:
            raise OCRUnavailable(f"tesseract could not be started: {e}") from None
        if res.returncode != 0:
            tail = (res.stderr or "").strip().splitlines()[-1:] or [""]
            raise OCRUnavailable(f"tesseract failed (exit {res.returncode}): {tail[0][:200]}")
        out = res.stdout
    rows = []
    for ln in out.splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip(): continue
        rows.append(dict(block=int(f[2]), par=int(f[3]), line=int(f[4]),
                         x=int(f[6]), y=int(f[7]), w=int(f[8]), h=int(f[9]),
                         conf=float(f[10]), text=f[11]))
    return rows


def _tesseract_multi(img_rgb, png_bytes):
    """3 passes: plain, local-adaptive binarized (light-grey text), inverted (white on dark).
    Words from later passes are added only where no earlier word overlaps."""
    import cv2
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    passes = [png_bytes,
              cv2.imencode(".png", cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15))[1].tobytes(),
              cv2.imencode(".png", cv2.adaptiveThreshold(255 - g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15))[1].tobytes()]
    words = []
    for k, pb in enumerate(passes):
        for w in _tesseract(pb):
            if k and (w["conf"] < 50 or not re.search(r"[A-Za-z0-9]", w["text"])): continue
            x0, y0, x1, y1 = w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"]
            clash = []
            for o in words:
                ix = min(x1, o["x"] + o["w"]) - max(x0, o["x"]); iy = min(y1, o["y"] + o["h"]) - max(y0, o["y"])
                if ix > 0 and iy > 0 and ix * iy > 0.25 * min(w["w"] * w["h"], o["w"] * o["h"]): clash.append(o)
            if clash:
                if all(w["conf"] > o["conf"] + 20 for o in clash):     # better reading of the same spot
                    words = [o for o in words if not any(o is c for c in clash)]
                else:
                    continue
            w["pass"] = k
            if k:
                # attach to the first-pass line it sits on (same text line), else keep as own line
                best, bov = None, 0.0
                for o in words:
                    if o.get("pass"): continue
                    ov = min(y1, o["y"] + o["h"]) - max(y0, o["y"])
                    if ov > 0.5 * min(w["h"], o["h"]) and abs(x0 - (o["x"] + o["w"] / 2)) < 40 * max(w["h"], o["h"]):
                        if ov > bov: best, bov = o, ov
                if best is not None:
                    w["block"], w["par"], w["line"] = best["block"], best["par"], best["line"]
                else:
                    w["block"] += 1000 * k
            words.append(w)
    return words


def _recover_missed_words(gray, img_rgb, ws, hmed, left_x):
    """Tesseract sometimes drops a short word (e.g. "of", "his") although its ink is there.
    For every inter-word gap / line-start gap that contains ink, OCR just that strip."""
    import cv2
    ly0 = int(min(w["y"] for w in ws)); ly1 = int(max(w["y"] + w["h"] for w in ws))
    pad = int(0.15 * hmed)
    cands = []
    first = ws[0]
    if first["x"] - left_x > 0.8 * hmed:
        cands.append((int(left_x), int(first["x"]), 0))
    for i, (a, b) in enumerate(zip(ws, ws[1:])):
        g0, g1 = a["x"] + a["w"], b["x"]
        if g1 - g0 > 0.9 * hmed: cands.append((g0, g1, i + 1))
    added = []
    for g0, g1, pos in cands:
        strip = gray[max(ly0 - pad, 0):ly1 + pad, g0 + 2:g1 - 2]
        if strip.size == 0: continue
        bgv = np.median(strip)
        ink = np.abs(strip - bgv) > 70
        if ink.mean() < 0.03 or ink.sum() < 25: continue
        cols = np.where(ink.any(axis=0))[0]
        x0 = g0 + 2 + int(cols[0]); x1 = g0 + 2 + int(cols[-1]) + 1
        crop = img_rgb[max(ly0 - pad, 0):ly1 + pad, max(x0 - pad, 0):x1 + pad]
        crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=[int(bgv)] * 3)
        ok, buf = cv2.imencode(".png", crop)
        for w in _tesseract(buf.tobytes(), psm=7):
            if w["conf"] >= 40 and re.search(r"[A-Za-z]", w["text"]):
                added.append((pos, dict(w, x=x0, y=ly0, w=x1 - x0, h=ly1 - ly0, block=ws[0]["block"], par=ws[0]["par"],
                                         line=ws[0]["line"], recovered=True)))
                break
    if not added: return ws
    out = list(ws)
    for pos, w in sorted(added, key=lambda t: -t[0]): out.insert(pos, w)
    return out


def _ocr_cells(img_rgb, png_bytes, scale, origin=(0, 0), region_id=0, min_conf=55):
    """OCR an RGB array; return cells in PDF coords plus keep regions."""
    words = _tesseract_multi(img_rgb, png_bytes)
    gray = img_rgb.mean(axis=2)
    lines = {}
    for w in words:
        lines.setdefault((w["block"], w["par"], w["line"]), []).append(w)
    cells, keeps, lowconf = [], [], []
    ox, oy = origin
    par_left = {}
    for k, v in lines.items():
        par_left[k[:2]] = min(par_left.get(k[:2], 1e9), min(w["x"] for w in v))
    for key in sorted(lines, key=lambda k: (k[0], k[1], k[2])):
        ws = sorted(lines[key], key=lambda w: w["x"])
        hmed = float(np.median([w["h"] for w in ws]))
        ws = _recover_missed_words(gray, img_rgb, ws, hmed, par_left[key[:2]])
        groups, cur = [], [ws[0]]
        for w in ws[1:]:
            prev = cur[-1]
            gx0, gx1 = prev["x"] + prev["w"], w["x"]
            if w["text"] in ("|", "¦") or prev["text"] in ("|", "¦"):
                groups.append(cur); cur = [w]; continue
            if gx1 - gx0 > 0.8 * hmed:
                # a dash Tesseract didn't read? look for a thin horizontal ink run in the gap
                ly0 = min(prev["y"], w["y"]); ly1 = max(prev["y"] + prev["h"], w["y"] + w["h"])
                gap = gray[ly0:ly1, gx0 + 1:gx1 - 1]
                dash = False
                if gap.size:
                    bgv = np.median(gap)
                    ink = np.abs(gap - bgv) > 60
                    rows = ink.mean(axis=1)
                    if rows.size and rows.max() > 0.45 and (rows > 0.2).sum() <= max(3, 0.25 * len(rows)):
                        dash = True
                # blank wide gap between two lowercase-flow words mid-line: an em dash whose glyph
                # was lost in the source (browser "print to PDF" drops U+2014 in some fonts)
                spaces = [b["x"] - (a["x"] + a["w"]) for a, b in zip(ws, ws[1:]) if 0 < b["x"] - (a["x"] + a["w"]) < 1.2 * hmed]
                sp = float(np.median(spaces)) if spaces else 0.3 * hmed
                blank = gap.size == 0 or float((np.abs(gap - np.median(gap)) > 60).mean()) < 0.002
                if (not dash and blank and gx1 - gx0 > 2.4 * sp and gx1 - gx0 < 2.2 * hmed
                        and re.search(r"[a-z,]$", prev["text"]) and re.match(r"^[a-zA-Z“\"']", w["text"])):
                    dash = True
                if dash:
                    w = dict(w); w["text"] = "— " + w["text"]; cur.append(w)
                elif gx1 - gx0 > 2.2 * hmed:
                    groups.append(cur); cur = [w]
                else:
                    cur.append(w)
            else:
                cur.append(w)
        groups.append(cur)
        for g in groups:
            text = re.sub(r"\s+— ", " — ", " ".join(w["text"] for w in g))
            # WSJ/stock-ticker arrows (▲▼) are OCR'd as a lone "4"/"v" right after a percentage
            text = re.sub(r"(\d%)\s+[4vV](?=\s|$)", r"\1", text)
            px0 = min(w["x"] for w in g); py0 = min(w["y"] for w in g)
            px1 = max(w["x"] + w["w"] for w in g); py1 = max(w["y"] + w["h"] for w in g)
            r = [ox + px0 / scale, oy + py0 / scale, ox + px1 / scale, oy + py1 / scale]
            conf = float(np.mean([w["conf"] for w in g]))
            if is_keep(text):
                keeps.append(r + [text]); continue
            if conf < min_conf or not HAS_LATIN.search(text):
                lowconf.append(r + [text, round(conf)]); continue
            crop = gray[py0:py1, px0:px1]
            bgv = np.median(np.concatenate([gray[max(py0 - 2, 0), px0:px1], gray[min(py1 + 1, gray.shape[0] - 1), px0:px1]]))
            ink = np.abs(crop - bgv) > 60
            dens = float(ink.mean()) if ink.size else 0
            col = img_rgb[py0:py1, px0:px1][ink].mean(axis=0) / 255 if ink.any() else np.array([0, 0, 0])
            # font size from ink box: tallest words (asc+desc) ~ 0.95em, cap-only ~0.72em
            hs = sorted(w["h"] for w in g)
            has_desc = any(re.search(r"[gjpqy,;]", w["text"]) for w in g)
            # word boxes inflated by highlighter / underline marks: use the median word height
            hmed_g = float(np.median([w["h"] for w in g]))
            tall = hs[-1] if hs[-1] < 1.35 * hmed_g else hmed_g * 1.1
            em = (tall / scale) / (0.95 if has_desc else 0.74)
            xw = [w["h"] for w in g if re.fullmatch(r"[acemnorsuvwxz]{2,}[.,]?", w["text"]) and w["conf"] > 70]
            if xw:                                   # x-height words: ink height ≈ 0.50 em
                em_x = (float(np.median(xw)) / scale) / 0.50
                em = min(em, em_x) if em > 1.15 * em_x else (em + em_x) / 2
            base = r[3] - (0.21 * em if has_desc else 0)
            cells.append(dict(x0=r[0], y0=r[1], x1=r[2], y1=r[3], text=text, block=(region_id,) + key[:2],
                              size=round(em, 1), base=base, dens=dens, color=[float(x) for x in col],
                              conf=conf, bold=False))
    # bold / serif from stroke geometry (calibrated on HBR sans + CIT serif samples):
    #   stroke width / em  > 0.135 -> bold ; ridge-width CV > 0.30 -> serif (size >= 9 only)
    import cv2
    for c in cells:
        x0, y0, x1, y1 = [int(v) for v in ((c["x0"] - ox) * scale, (c["y0"] - oy) * scale, (c["x1"] - ox) * scale, (c["y1"] - oy) * scale)]
        g = gray[y0:y1, x0:x1]
        c["family"] = None
        if g.size == 0: continue
        bgv = np.median(np.concatenate([g[0], g[-1]]))
        ink = (np.abs(g - bgv) > 80).astype(np.uint8)
        if ink.sum() < 20: continue
        dt = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
        ridge = (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8))) & (ink > 0) & (dt > 0.8)
        v = dt[ridge]
        if v.size < 10: continue
        sw = 2 * float(np.median(v)) / (c["size"] * scale); cv = float(v.std() / v.mean())
        c["bold"] = sw > 0.135
        if c["size"] >= 9: c["family"] = "serif" if cv > 0.30 else "sans"
    # snap noisy per-line size estimates: lines within ±30 % of the page's body size ARE body text
    long_ = [c["size"] for c in cells if len(c["text"]) >= 25]
    if len(long_) >= 3:
        body = float(np.median(long_))
        for c in cells:
            if abs(c["size"] - body) <= 0.30 * body:
                c["size"] = round(body, 1); c["snapped"] = True
            elif c["size"] > 1.3 * body and len(c["text"]) >= 40:
                # long line at "headline" size is implausible: OCR box was inflated (highlight)
                c["size"] = round(body, 1); c["snapped"] = True
        # bold is only trusted for clearly non-body lines (headings) or whole paragraphs
        for c in cells:
            if c.get("snapped") and len(c["text"]) >= 25: c["bold"] = False
    fams = [c["family"] for c in cells if c["family"]]
    major = max(set(fams), key=fams.count) if fams else "sans"
    for c in cells:
        if not c["family"]: c["family"] = major
    return cells, keeps, lowconf


def render_rgb(pg, dpi, clip=None):
    pm = pg.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.h, pm.w, 3)
    return arr, pm.tobytes("png")


def plan_ocr_page(pg, pno, kind, dpi=300, family="serif"):
    arr, png = render_rgb(pg, dpi)
    cells, keeps, low = _ocr_cells(arr, png, dpi / 72)
    # cells lying over embedded images -> image text (patch method)
    imgs = [pymupdf.Rect(i["bbox"]) for i in pg.get_image_info()] if kind == "vector" else []
    for c in cells:
        r = pymupdf.Rect(c["x0"], c["y0"], c["x1"], c["y1"])
        c["on_image"] = kind == "raster" or any((r & ir).get_area() > 0.5 * r.get_area() for ir in imgs)
    mark_rows(cells, keeps)
    # order cells by visual column: a cell joins a column if its left edge is within ~1.5 em
    # of the column's left edge and their x-ranges overlap by >50 %. Sidebars then no longer
    # interleave with body lines and break paragraph chains.
    colz = []                      # [x0, x1, [cells]]
    for c in sorted(cells, key=lambda c: (c["y0"], c["x0"])):
        best = None
        for col in colz:
            ov = min(col[1], c["x1"]) - max(col[0], c["x0"])
            if abs(col[0] - c["x0"]) < 1.5 * c["size"] and ov > 0.5 * min(col[1] - col[0], c["x1"] - c["x0"]):
                best = col; break
        if best is None: colz.append([c["x0"], c["x1"], [c]])
        else: best[2].append(c); best[1] = max(best[1], c["x1"])
    ordered = []
    for col in sorted(colz, key=lambda col: (min(x["y0"] for x in col[2]), col[0])):
        ordered.extend(col[2])
    cells = ordered
    paras = _group_cells(cells, para_gap=1.0)
    units = []
    for i, p in enumerate(paras):
        sub = "raster" if p[0]["on_image"] else kind
        if kind == "vector" and p[0]["on_image"]: sub = "imgtext"
        u = _para_to_unit(pno, sub, i, p)
        units.append(u)
    plan = PagePlan(pno, kind, units, keeps)
    if low: plan.notes.append({"lowconf_ocr": low})
    return plan
