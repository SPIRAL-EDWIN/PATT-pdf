"""Erase translated glyphs, draw Chinese, restore displaced keeps.

Migrated verbatim from prototype layout module (patch_background, _patch_inpaint, screen_units, erase_units, draw_units, restore_keeps, normalize_boxes, _keep_positions, _keeps_moved, _capture_keep_spans, apply_plan); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import math
import re

import numpy as np
import pymupdf

from .grouping import _rgb
from .keep import BOLD_HINT, font_family
from .ocr import render_rgb
from . import decor
from .fonts import font
from .typeset import fit_unit

TRANSLATE_IMAGE_TEXT = False   # text inside photos/banners: default leave + report


def patch_background(pg, rect, dpi=200):
    """inspect background around a text line. returns (mode, bg_rgb01, std)."""
    clip = (pymupdf.Rect(rect) + (-2, -2, 2, 2)) & pg.rect
    arr, _ = render_rgb(pg, dpi, clip=clip)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]]).astype(float)
    bg = np.median(border, axis=0)
    dist = np.abs(border - bg).sum(axis=1)
    inl = border[dist < 45]; out_frac = 1 - len(inl) / max(1, len(border))
    std = float(inl.std(axis=0).max()) if len(inl) > 10 else 99.0
    if std < 8 and out_frac < 0.25: mode = "fill"
    elif std < 20 and out_frac < 0.45: mode = "inpaint"
    else: mode = "textured"
    return mode, [float(x) / 255 for x in bg], std


def _patch_inpaint(pg, rect, dpi=200):
    import cv2
    clip = (pymupdf.Rect(rect) + (-2, -2, 2, 2)) & pg.rect
    arr, _ = render_rgb(pg, dpi, clip=clip)
    a = arr.copy()
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(a.astype(int) - bg).sum(axis=2)
    mask = (diff > 30).astype(np.uint8) * 255                      # include anti-aliased edges
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    out = cv2.inpaint(a, mask, 4, cv2.INPAINT_TELEA)
    ok, buf = cv2.imencode(".png", out[:, :, ::-1])
    pg.insert_image(clip, stream=buf.tobytes(), overlay=True)


def screen_units(pg, units):
    """mark raster/imgtext units whose background cannot be repaired cleanly; they are
    left in English and reported instead of producing smears."""
    skipped = []
    for u in units:
        if u.kind == "imgtext" and u.tgt and not TRANSLATE_IMAGE_TEXT:
            skipped.append({"uid": u.uid, "issue": "image_text_left_english", "src": u.src[:60],
                            "bbox": [round(v, 1) for v in u.bbox]})
            u.tgt = ""; continue
        if u.kind in ("raster", "imgtext") and u.tgt:
            modes = [patch_background(pg, pymupdf.Rect(l[:4]))[0] for l in u.lines]
            if "textured" in modes:
                skipped.append({"uid": u.uid, "issue": "textured_background_left_english", "src": u.src[:60],
                                "bbox": [round(v, 1) for v in u.bbox]})
                u.tgt = ""
        if u.tgt and u.tgt.strip() == "<KEEP>":
            u.tgt = ""; u.kind = "keep"
    return skipped


def _slanted_chars(pg, skip=()):
    """Non-space characters of slanted lines, except those at the positions in `skip`.
    Each has its upright bounding box ("bbox", what MuPDF tests redactions against) and a few
    points on the glyph itself ("pts"): the box of a slanted letter is much larger than its ink."""
    out = []
    for b_ in pg.get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]:
        for l_ in b_.get("lines", []):
            if abs(l_["dir"][1]) <= 0.05:
                continue
            dx, dy = l_["dir"]
            for sp_ in l_["spans"]:
                chars = sp_["chars"]
                for i_, c_ in enumerate(chars):
                    if not c_["c"].strip():
                        continue
                    cr = pymupdf.Rect(c_["bbox"])
                    if any(abs(m.x0 - cr.x0) < 0.05 and abs(m.y0 - cr.y0) < 0.05 for m in skip):
                        continue
                    ox, oy = c_["origin"]; size = sp_["size"]
                    adv = 0.5 * size
                    if i_ + 1 < len(chars):
                        nx, ny = chars[i_ + 1]["origin"]
                        adv = min(max(math.hypot(nx - ox, ny - oy), 0.2 * size), 1.1 * size)
                    pts = [(ox + dx * adv * a + dy * size * h, oy + dy * adv * a - dx * size * h)
                           for a in (0.05, 0.5, 0.95) for h in (-0.15, 0.2, 0.5, 0.75)]
                    out.append(dict(c=c_["c"], origin=(ox, oy), size=size, font=sp_["font"],
                                    flags=sp_["flags"], color=sp_["color"], bbox=cr, pts=pts,
                                    angle=math.degrees(math.atan2(-dy, dx))))
    return out


def _safe_point(r, boxes, half=0.4):
    """A small rectangle inside the glyph box `r` that touches none of `boxes` (boxes of slanted
    letters that must stay). None: `r` touches none of them. False: no such place exists."""
    hit = [g for g in boxes if g.intersects(r)]
    if not hit:
        return None
    for fy in (0.5, 0.3, 0.7, 0.15, 0.85):
        for fx in (0.5, 0.25, 0.75, 0.1, 0.9):
            cx, cy = r.x0 + fx * r.width, r.y0 + fy * r.height
            q = pymupdf.Rect(cx - half, cy - half, cx + half, cy + half)
            if not any(g.intersects(q + (-0.2, -0.2, 0.2, 0.2)) for g in hit):
                return q
    return False


def _lines_hit(rects, guard, margin=0.5):
    """True if a point of a kept slanted letter lies inside one of the line rectangles."""
    for r in rects:
        rr = r + (-margin, -margin, margin, margin)
        for g in guard:
            if g["bbox"].intersects(rr) and any(rr.x0 <= x <= rr.x1 and rr.y0 <= y <= rr.y1 for x, y in g["pts"]):
                return True
    return False


def _solid(units, keeps):
    """Obstacles for widening a short centred label: what is really in the way. The upright
    box of slanted text is mostly empty, so translated slanted units count along their
    baseline only, and slanted text that stays is left to place_near_slanted (it tests the
    letters themselves)."""
    out = []
    for u in units:
        if not getattr(u, "angle", 0):
            out.append(list(u.bbox)); continue
        ox, oy = u.lines[0][0], u.lines[0][4]
        L = math.hypot(u.bbox[2] - u.bbox[0], u.bbox[3] - u.bbox[1])
        a = math.radians(u.angle); h = 0.7 * u.size
        n = max(2, int(L / max(h, 1.0)) + 1)
        for i in range(n + 1):
            x, y = ox + math.cos(a) * L * i / n, oy - math.sin(a) * L * i / n
            out.append([x - h, y - h, x + h, y + h])
    out += [list(k[:4]) for k in keeps if not str(k[4]).startswith("[rotated]")]
    return out


def place_near_slanted(pg, units, keeps, guard):
    """Translations must not be printed over slanted text that stays on the page (labels along
    curves). For every upright unit whose area such a letter enters, look for a placement inside
    the unit's own box that is clear of those letters: the lines of the original, smaller
    sizes, centred or flush. If there is none, the unit keeps its source text (reported).
    Units away from slanted text are not touched."""
    from .typeset import _wrap
    report = []
    if not guard:
        return report
    obstacles = [u.bbox for u in units] + [list(k[:4]) for k in keeps]
    solid = _solid(units, keeps)
    for u in units:
        if not u.tgt or u.angle or u.kind != "text":
            continue
        fnt = font(u.family, u.bold)
        s0, ls0, pitch0, box0, ok0 = fit_unit(u, pg.rect, obstacles, solid)
        area = (pymupdf.Rect(u.bbox) | pymupdf.Rect(box0)) + (-0.5 * u.size, -0.3 * u.size, 0.5 * u.size, 0.3 * u.size)
        near = [g for g in guard if g["bbox"].intersects(area)]
        if not near:
            continue
        n0 = len(u.lines)
        chosen = None
        for scale in (1.0, 0.9, 0.8):
            s_ = s0 * scale
            ls = ls0 if scale == 1.0 else _wrap(u.tgt, fnt, s_, box0[2] - box0[0])
            if not ls or len(ls) > n0:
                continue                                       # never more lines than the source had
            pitch = pitch0 * scale
            starts = [u.lines[i][4] for i in range(0, max(1, n0 - len(ls) + 1))]
            if u.align == "center" and len(ls) < n0:           # fewer lines than the source: centred first
                starts = [u.lines[0][4] + (n0 - len(ls)) * pitch / 2] + starts
            for base0 in starts:
                if base0 + (len(ls) - 1) * pitch > u.bbox[3] + 0.35 * u.size:
                    continue
                for how in ([u.align] + [h for h in ("center", "left", "right") if h != u.align]):
                    xs = []
                    for ln in ls:
                        w = fnt.text_length(ln, fontsize=s_)
                        x = box0[0] if how == "left" else (box0[2] - w if how == "right" else (box0[0] + box0[2]) / 2 - w / 2)
                        xs.append((x, w))
                    rects = [pymupdf.Rect(x, base0 + i * pitch - 0.88 * s_, x + w, base0 + i * pitch + 0.15 * s_)
                             for i, (x, w) in enumerate(xs)]
                    if any(r.x0 < min(u.bbox[0], box0[0]) - 0.6 * u.size for r in rects):
                        continue                               # stay inside the unit's own area
                    if not _lines_hit(rects, near):
                        chosen = (s_, ls, pitch, base0, [x for x, _ in xs]); break
                if chosen: break
            if chosen: break
        if chosen:
            u._place = chosen
            if chosen[0] < 0.8 * u.size:
                report.append({"uid": u.uid, "issue": "shrunk", "scale": round(chosen[0] / u.size, 2), "src": u.src[:60]})
        else:
            report.append({"uid": u.uid, "issue": "label_left_source", "src": u.src[:60],
                           "detail": "no room next to text that follows a curve; the source text was kept"})
            u._kept_src = True; u.tgt = ""; u.kind = "keep"
    return report


def _page_font(pg, name):
    """The font the page itself uses for `name`, if it can draw text by character code."""
    for f in pg.get_fonts(full=True):
        base = f[3].split("+")[-1]
        if base == name or f[3] == name:
            try:
                buf = pg.parent.extract_font(f[0])[3]
                if buf:
                    return pymupdf.Font(fontbuffer=buf)
            except Exception:
                return None
    return None


def _restore_slanted(pg, guard):
    """Redraw the remembered slanted letters that are no longer on the page, each at its own
    origin and angle. The page's own font is used when it can draw the letter; otherwise a
    base font of the same family. Returns the letters that were redrawn."""
    key = lambda g: (g["c"], round(g["origin"][0], 1), round(g["origin"][1], 1))
    have = {key(g) for g in _slanted_chars(pg)}
    gone = [g for g in guard if key(g) not in have]
    fonts = {}
    for g in gone:
        if g["font"] not in fonts:
            fonts[g["font"]] = _page_font(pg, g["font"])
        fnt = fonts[g["font"]]
        if fnt is None or not fnt.has_glyph(ord(g["c"])):
            serif = font_family(g["font"], g["flags"]) == "serif"
            bold = bool(g["flags"] & 16) or bool(BOLD_HINT.search(g["font"])); ital = bool(g["flags"] & 2)
            base = (("tibi" if ital else "tibo") if bold else ("tiit" if ital else "tiro")) if serif else \
                   (("hebi" if ital else "hebo") if bold else ("heit" if ital else "helv"))
            fnt = pymupdf.Font(base)
            if not fnt.has_glyph(ord(g["c"])):
                fnt = font("serif" if serif else "sans", bold)
        tw = pymupdf.TextWriter(pg.rect, color=_rgb(g["color"]))
        o = pymupdf.Point(g["origin"])
        tw.append(o, g["c"], font=fnt, fontsize=g["size"])
        tw.write_text(pg, morph=(o, pymupdf.Matrix(g["angle"])))
    return gone


def erase_units(pg, units, keeps=(), report=None, guard=None):
    textr, vecr, patch = [], [], []
    conflicts = []
    keep_rects = [pymupdf.Rect(k[:4]) for k in keeps]
    for u in units:
        if not u.tgt: continue
        if u.kind == "text" and u.angle:
            for e in u.erase:
                r = pymupdf.Rect(e); c = (r.tl + r.br) / 2
                textr.append([pymupdf.Rect(c.x - 0.4, c.y - 0.4, c.x + 0.4, c.y + 0.4), "pt"])
        elif u.kind == "text":
            for e in u.erase:
                r = pymupdf.Rect(e)
                textr.append([r, 0.5])                 # [glyph box, strip height fraction]
        elif u.kind == "vector":
            padx = max(1.2, 0.22 * u.size); pady = max(1.2, 0.12 * u.size)
            r = pymupdf.Rect(u.bbox) + (-padx, -pady, padx, pady)
            for k in keep_rects:                      # never grow over a kept figure
                if r.intersects(k) and not pymupdf.Rect(u.bbox).intersects(k):
                    if k.x1 <= u.bbox[0]: r.x0 = max(r.x0, k.x1 + 0.3)
                    elif k.x0 >= u.bbox[2]: r.x1 = min(r.x1, k.x0 - 0.3)
                    elif k.y1 <= u.bbox[1]: r.y0 = max(r.y0, k.y1 + 0.3)
                    elif k.y0 >= u.bbox[3]: r.y1 = min(r.y1, k.y0 - 0.3)
            vecr.append(r)
        else:
            for l in u.lines: patch.append(pymupdf.Rect(l[:4]) + (-0.8, -0.8, 0.8, 0.8))
    if textr:
        # Slanted text that stays on the page (curved map labels) often runs across upright
        # labels. MuPDF removes a glyph when the redaction touches its upright bounding box,
        # and that box is large for a slanted letter: removing "Francisco" also removed the
        # "r" of the curved "San Francisco Bay". Such letters are remembered here and put
        # back after the removal (_restore_slanted).
        if guard is None:
            mine = [pymupdf.Rect(e) for u in units if u.tgt for e in u.erase]
            guard = _slanted_chars(pg, skip=mine)
        # ...but first try not to remove them at all: where the glyph to erase has a spot that
        # lies outside the boxes of those letters, a small redaction there removes only it.
        gboxes = [g["bbox"] for g in guard]
        if gboxes:
            glyphs = None                    # upright glyph boxes of the page, read once when needed
            new = []
            for item in textr:
                r = item[0]
                if item[1] == "pt" or not any(g.intersects(r) for g in gboxes):
                    new.append(item); continue
                if glyphs is None:
                    glyphs = [pymupdf.Rect(c_["bbox"]) for b_ in pg.get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]
                              for l_ in b_.get("lines", []) if abs(l_["dir"][1]) <= 0.05
                              for sp_ in l_["spans"] for c_ in sp_["chars"] if c_["c"].strip()]
                # an erase rectangle can cover a whole word: go glyph by glyph inside it
                inside = [gl for gl in glyphs if gl.intersects(r) and (gl & r).get_area() > 0.6 * max(gl.get_area(), 0.01)]
                pts = [_safe_point(gl, gboxes) for gl in inside]
                if not inside or any(q is False for q in pts):
                    new.append(item); continue           # no safe spot: remove as before, redraw afterwards
                for gl, q in zip(inside, pts):
                    if q is None:
                        c = (gl.tl + gl.br) / 2
                        q = pymupdf.Rect(c.x - 0.4, c.y - 0.4, c.x + 0.4, c.y + 0.4)
                    new.append([q, "pt"])
            textr[:] = new

        def strip(r, f):
            if f == "pt": return r
            if f == 0.5:
                h = r.height; return pymupdf.Rect(r.x0 + 0.3, r.y0 + 0.3 * h, r.x1 - 0.3, r.y1 - 0.3 * h)
            y = r.y0 + f * r.height; return pymupdf.Rect(r.x0 + 0.3, y - 0.2, r.x1 - 0.3, y + 0.2)
        def lost_keeps(rects):
            # trial on a scratch copy of the page: which kept figures would vanish?
            tmp = pymupdf.open(); tmp.insert_pdf(pg.parent, from_page=pg.number, to_page=pg.number)
            tp = tmp[0]
            for rr in rects: tp.add_redact_annot(rr, fill=False, cross_out=False)
            tp.apply_redactions(images=0, graphics=0, text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            out = []
            for k, kr in zip(keeps, keep_rects):
                want = re.sub(r"\s", "", str(k[4]))
                if not want or str(k[4]).startswith("[rotated]"): continue
                if want not in re.sub(r"\s", "", tp.get_textbox(kr + (-0.5, -0.5, 0.5, 0.5))): out.append(kr)
            return out
        FR = [0.5, 0.62, 0.38, 0.75, 0.25, 0.86, 0.14, 0.94, 0.06]
        base_lost = set()
        risky = [kr for kr in keep_rects if any(kr.intersects(strip(r, f)) for r, f in textr)]
        if risky:
            keeps_r = [(k, kr) for k, kr in zip(keeps, keep_rects) if kr in risky]
            keeps, keep_rects = [k for k, _ in keeps_r], [kr for _, kr in keeps_r]
            # keeps that are already not extractable in the source are ignored
            for k, kr in zip(keeps, keep_rects):
                want = re.sub(r"\s", "", str(k[4]))
                if want and want not in re.sub(r"\s", "", pg.get_textbox(kr + (-0.5, -0.5, 0.5, 0.5))): base_lost.add(id(kr))
            for _ in range(len(FR)):
                lost = [kr for kr in lost_keeps([strip(r, f) for r, f in textr]) if id(kr) not in base_lost]
                if not lost: break
                moved = False
                for item in textr:
                    r, f = item
                    if f != "pt" and any(kr.intersects(r) for kr in lost):
                        i = FR.index(f)
                        if i + 1 < len(FR): item[1] = FR[i + 1]; moved = True
                if not moved: break
            else:
                lost = []
            for kr in lost: conflicts.append([round(v, 1) for v in kr])
        # duplicated glyph outlines: some PDFs draw the same label both as text and as small
        # vector paths (outlined/stroked glyphs). Detect glyph-sized paths inside translated
        # line boxes BEFORE removing the text, then remove them with a covered-only line-art pass.
        dup_boxes = []
        units_text = [u for u in units if u.kind == "text" and u.tgt and not u.angle]
        if units_text:
            para_r = [pymupdf.Rect(u.bbox) + (-0.35 * u.size, -0.25 * u.size, 0.35 * u.size, 0.25 * u.size) for u in units_text]
            drs = [pymupdf.Rect(d_["rect"]) for d_ in pg.get_drawings()]
            # same test as before, on arrays: maps carry tens of thousands of paths, and a
            # Python loop over all of them for every paragraph took most of the render time
            D = np.array([[r.x0, r.y0, r.x1, r.y1] for r in drs], dtype=float).reshape(-1, 4)
            Dw, Dh = D[:, 2] - D[:, 0], D[:, 3] - D[:, 1]
            Dok = (Dw > 0) & (Dh > 0)
            Darea = np.maximum(Dw * Dh, 0.01)
            for pr, u in zip(para_r, units_text):
                iw = np.minimum(D[:, 2], pr.x1) - np.maximum(D[:, 0], pr.x0)
                ih = np.minimum(D[:, 3], pr.y1) - np.maximum(D[:, 1], pr.y0)
                hit = Dok & (Dw < 2.5 * u.size) & (Dh < 2.5 * u.size) & (iw > 0) & (ih > 0) & (iw * ih > 0.6 * Darea)
                inside = [drs[i] for i in np.flatnonzero(hit)]
                if len(inside) >= max(3, len(re.sub(r"\s", "", u.src)) // 3):   # glyph-like cluster
                    box = pymupdf.Rect(pr)
                    for rr in inside: box |= rr
                    dup_boxes.append(box)
        for r, f in textr: pg.add_redact_annot(strip(r, f), fill=False, cross_out=False)
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                            text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        if guard:
            back = _restore_slanted(pg, guard)
            if back and report is not None:
                report.append({"issue": "keep_restored", "text": "".join(g["c"] for g in back)[:30],
                               "detail": f"{len(back)} slanted letter(s) crossed by translated text were redrawn"})
        if dup_boxes:
            seen = set()
            for lr in dup_boxes:
                k = tuple(round(v, 1) for v in lr)
                if k in seen: continue
                seen.add(k)
                pg.add_redact_annot(lr + (-0.6, -0.6, 0.6, 0.6), fill=False, cross_out=False)
            pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                text=pymupdf.PDF_REDACT_TEXT_NONE)
            # outlines that are sub-paths of a larger compound path can't be removed one by one:
            # paint them out with the local (flat) background, only if the background really is flat
            left = [pymupdf.Rect(d_["rect"]) for d_ in pg.get_drawings()]     # once, after the removal
            left = [r for r in left if not r.is_empty and r.width < 40]
            for lr in dup_boxes:
                rest = [r for r in left if r.intersects(lr) and (r & lr).get_area() > 0.6 * max(r.get_area(), 0.01)]
                if not rest: continue
                box = pymupdf.Rect(rest[0])
                for rr in rest[1:]: box |= rr
                mode, bg, std = patch_background(pg, box + (-0.8, -0.8, 0.8, 0.8))
                if mode == "fill":
                    pg.draw_rect((box + (-0.8, -0.8, 0.8, 0.8)) & pg.rect, color=None, fill=bg, overlay=True)
    if vecr:
        for r in vecr: pg.add_redact_annot(r, fill=False, cross_out=False)
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                            graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                            text=pymupdf.PDF_REDACT_TEXT_NONE)
    noisy = []
    for r in patch:
        mode, bg, std = patch_background(pg, r)
        if mode == "fill":
            pg.draw_rect((r + (-1.2, -1.2, 1.2, 1.2)) & pg.rect, color=None, fill=bg, overlay=True)
        else:
            _patch_inpaint(pg, r)
    if conflicts: noisy.append({"keep_conflict": conflicts})
    return noisy


def draw_units(pg, units, keeps=()):
    report = []
    obstacles = [u.bbox for u in units] + [list(k[:4]) for k in keeps]
    solid = _solid(units, keeps)
    tws = {}
    rot_tw = []
    for u in units:
        if not u.tgt: continue
        if u.angle:
            fnt = font(u.family, u.bold)
            L0 = sum(math.hypot(1, 0) for _ in [0]) and max(1.0, math.hypot(u.bbox[2] - u.bbox[0], u.bbox[3] - u.bbox[1]))
            s_ = u.size; w = fnt.text_length(u.tgt, fontsize=s_)
            while w > L0 * 1.05 and s_ > 0.6 * u.size: s_ *= 0.95; w = fnt.text_length(u.tgt, fontsize=s_)
            o = pymupdf.Point(u.lines[0][0], u.lines[0][4])
            tw = pymupdf.TextWriter(pg.rect, color=tuple(u.color))
            tw.append(o, u.tgt.replace("\n", " "), font=fnt, fontsize=s_)
            u._drawn = None                            # rotated: decorations are not moved
            rot_tw.append((tw, o, u.angle))
            if w > L0 * 1.05 or s_ < u.size * 0.8:     # same reporting as for upright text
                report.append({"uid": u.uid, "issue": "overflow" if w > L0 * 1.05 else "shrunk",
                               "scale": round(s_ / u.size, 2), "src": u.src[:60], "angle": round(u.angle, 1)})
            continue
        fnt = font(u.family, u.bold)
        placed = getattr(u, "_place", None)
        if placed:                                     # chosen by place_near_slanted
            s, ls, pitch, base0, xs = placed
            col = tuple(max(0.0, min(1.0, c)) for c in u.color)
            tw = tws.setdefault(col, pymupdf.TextWriter(pg.rect, color=col))
            u._drawn = []
            for i, ln in enumerate(ls):
                tw.append((xs[i], base0 + i * pitch), ln, font=fnt, fontsize=s)
                u._drawn.append((xs[i], ln, base0 + i * pitch, s))
            continue
        s, ls, pitch, box, ok = fit_unit(u, pg.rect, obstacles, solid)
        # don't start on top of a kept glyph sitting just left of / under the box start ("|", bullets)
        for k in keeps:
            if (k[0] - 0.5 < box[0] < k[2] + 0.6 * s) and min(box[3], k[3]) - max(box[1], k[1]) > 0.3 * s and k[2] - k[0] < 3 * s:
                shift = k[2] + 0.35 * s - box[0]
                if shift > 0: box = (box[0] + shift, box[1], box[2] + shift, box[3])
        col = tuple(max(0.0, min(1.0, c)) for c in u.color)
        tw = tws.setdefault(col, pymupdf.TextWriter(pg.rect, color=col))
        # first baseline: original first baseline if the size is unchanged, else top-aligned
        # a single line that stays a single line keeps its baseline even when it was shrunk:
        # it usually sits in a row (table header, labels) and must line up with its neighbours
        one_line = len(u.lines) == 1 and len(ls) == 1
        base0 = u.lines[0][4] if (abs(s - u.size) < 0.01 or one_line) else box[1] + fnt.ascender * s * 0.98
        if u.align == "center" and len(ls) < len(u.lines) and abs(s - u.size) < 0.01:
            base0 += (len(u.lines) - len(ls)) * pitch / 2       # fewer lines than the source: keep the block centred
        u._drawn = []                                   # (x, text, baseline, size) per drawn line
        for i, ln in enumerate(ls):
            x = box[0]
            if u.align == "center":
                x = (box[0] + box[2]) / 2 - fnt.text_length(ln, fontsize=s) / 2
            tw.append((x, base0 + i * pitch), ln, font=fnt, fontsize=s)
            u._drawn.append((x, ln, base0 + i * pitch, s))
        if not ok or s < u.size * 0.8:
            report.append({"uid": u.uid, "issue": "overflow" if not ok else "shrunk",
                           "scale": round(s / u.size, 2), "src": u.src[:60]})
    for tw in tws.values(): tw.write_text(pg)
    for tw, o, ang in rot_tw:
        tw.write_text(pg, morph=(o, pymupdf.Matrix(ang)))
    return report


def restore_keeps(pg, plan):
    """Re-draw kept text that the redaction rewrite moved or deleted. Displaced copies of it
    are removed first (only those NOT at their original box)."""
    kp = getattr(plan, "_kp", []); spans = getattr(plan, "_keep_spans", {})
    moved = _keeps_moved(pg, kp)
    if not moved: return []
    rep = []
    # remove displaced copies: same text found elsewhere on the page, not overlapping any kept box
    keep_boxes = [r for _, r, _ in kp]
    for t, r, k in moved:
        want = str(k[4]).strip()
        # search_for ignores case and matches inside words: for a one- or two-character keep
        # ("A", "*") it would hit that letter in every word of the page and erase it there.
        # Such keeps are only re-drawn at their own position; nothing else is touched.
        if len(t) < 3:
            continue
        for hit in pg.search_for(want):
            if re.sub(r"\s", "", pg.get_textbox(hit + (-0.5, -0.5, 0.5, 0.5))) != t:
                continue                    # part of a longer word or different case: not a copy
            if not any(hit.intersects(kb) for kb in keep_boxes):
                h = hit.height
                pg.add_redact_annot(pymupdf.Rect(hit.x0 + 0.3, hit.y0 + 0.3 * h, hit.x1 - 0.3, hit.y1 - 0.3 * h), fill=False)
    pg.apply_redactions(images=0, graphics=0, text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for t, r, k in _keeps_moved(pg, kp):
        sp = spans.get(t)
        if not sp: rep.append({"issue": "keep_lost", "text": t[:30]}); continue
        for s_ in sp:
            fam = font_family(s_["font"], s_["flags"])
            bold = bool(s_["flags"] & 16) or bool(BOLD_HINT.search(s_["font"]))
            try:
                fnt = pymupdf.Font("tiro" if fam == "serif" else "helv") if not re.search(r"[^\x00-\x7f]", s_["text"]) else font(fam, bold)
            except Exception:
                fnt = font(fam, bold)
            tw = pymupdf.TextWriter(pg.rect, color=_rgb(s_["color"]))
            tw.append(s_["origin"], s_["text"], font=fnt, fontsize=s_["size"])
            tw.write_text(pg)
        rep.append({"issue": "keep_restored", "text": t[:30]})
    return rep


def normalize_boxes(pg):
    """Pages whose CropBox is offset inside a larger MediaBox make TextWriter output land
    off-page. Setting MediaBox := CropBox (in PDF space) keeps all visible coordinates."""
    mb, cb = pg.mediabox, pg.cropbox
    if abs(cb.x0 - mb.x0) > 0.5 or abs(cb.y0 - mb.y0) > 0.5 or abs(cb.x1 - mb.x1) > 0.5 or abs(cb.y1 - mb.y1) > 0.5:
        pg.set_mediabox(pymupdf.Rect(cb.x0, mb.y1 - cb.y1, cb.x1, mb.y1 - cb.y0))
        return True
    return False


def _keep_positions(pg, keeps):
    out = []
    for k in keeps:
        t = re.sub(r"\s", "", str(k[4]))
        if not t or str(k[4]).startswith("[rotated]"): continue
        out.append((t, pymupdf.Rect(k[:4]), k))
    return out


def _keeps_moved(pg, kp):
    moved = []
    for t, r, k in kp:
        here = re.sub(r"\s", "", pg.get_textbox(r + (-0.8, -0.8, 0.8, 0.8)))
        if t not in here: moved.append((t, r, k))
    return moved


def _capture_keep_spans(pg, kp):
    """remember exact glyph runs (text, origin, size, font, colour) of kept text before editing"""
    spans = {}
    d = pg.get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
    for b in d["blocks"]:
        for l in b.get("lines", []):
            for sp in l["spans"]:
                r = pymupdf.Rect(sp["bbox"])
                for t, kr, k in kp:
                    if kr.intersects(r) and (r & kr).get_area() > 0.5 * max(r.get_area(), 0.01):
                        spans.setdefault(t, []).append(dict(text="".join(c["c"] for c in sp["chars"]),
                            origin=sp["chars"][0]["origin"] if sp["chars"] else sp["origin"], size=sp["size"],
                            font=sp["font"], flags=sp["flags"], color=sp["color"], dir=l["dir"]))
    return spans


def apply_plan(pg, plan):
    """Erase + draw. clean_contents() first (some producers re-emit deleted text otherwise).
    MuPDF's redaction rewrite can still shift or drop a kept line that relies on implicit
    text-advance operators (' and T*), so every kept text is verified afterwards and any
    that moved or vanished is restored at its original position (see restore_keeps)."""
    kp = _keep_positions(pg, plan.keeps)
    base_missing = {t for t, r, k in _keeps_moved(pg, kp)}
    kp = [x for x in kp if x[0] not in base_missing]
    plan._kp = kp
    plan._keep_spans = _capture_keep_spans(pg, kp)
    try: pg.clean_contents()
    except Exception: pass
    strategy = "clean"
    plan.notes.append({"content_strategy": strategy})
    if normalize_boxes(pg): plan.notes.append({"normalized_cropbox": True})
    for u in plan.units:
        if u.tgt and u.tgt.strip() == "<KEEP>": u.tgt = ""; u.kind = "keep"
    skipped = screen_units(pg, plan.units)
    # underlines / links attached to translated text: snapshot BEFORE any redaction
    # (MuPDF's redaction deletes overlapping link annotations)
    links = decor.link_texts(pg, decor.snapshot_links(pg))
    decos = decor.find(pg, plan.units)
    vrules = decor.vertical_rules(pg)
    rep_d, decos = decor.flag_unhandled(pg, plan.units, decos)
    rep_d += decor.markup_annotations(pg, plan.units) + decor.image_underlines(pg, plan.units)
    restored = []
    mine = [pymupdf.Rect(e) for u in plan.units if u.tgt for e in u.erase]
    guard = _slanted_chars(pg, skip=mine)              # slanted text that stays on the page
    skipped += place_near_slanted(pg, plan.units, plan.keeps, guard)
    noisy = erase_units(pg, plan.units, plan.keeps, report=restored, guard=guard)
    removed = decor.remove(pg, decos)
    not_removed = [d for d in decos if d not in removed]
    rep = skipped + restored + draw_units(pg, [u for u in plan.units if u.kind != "keep"], plan.keeps)
    rep += restore_keeps(pg, plan)
    iss, specs = decor.redraw(pg, plan.units, removed, not_removed)
    rep += rep_d + iss
    link_iss, remapped = decor.restore_links(pg, links, plan.units)
    rep += link_iss + decor.verify(pg, specs) + decor.crossings(plan.units, vrules)
    if specs or remapped:
        plan.notes.append({"decorations_redrawn": len(specs), "links_remapped": remapped})
    if noisy: rep.append({"issue": "patch_on_textured_background", "rects": noisy})
    return rep
