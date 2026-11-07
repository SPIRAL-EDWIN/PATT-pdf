"""Erase translated glyphs, draw Chinese, restore displaced keeps.

Migrated verbatim from prototype layout module (patch_background, _patch_inpaint, screen_units, erase_units, draw_units, restore_keeps, normalize_boxes, _keep_positions, _keeps_moved, _capture_keep_spans, apply_plan); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import math
import re

import numpy as np
import pymupdf

from .grouping import _rgb
from .keep import BOLD_HINT, SERIF_HINT
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


def erase_units(pg, units, keeps=()):
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
            for pr, u in zip(para_r, units_text):
                inside = [rr for rr in drs if not rr.is_empty and rr.width < 2.5 * u.size and rr.height < 2.5 * u.size
                          and (rr & pr).get_area() > 0.6 * max(rr.get_area(), 0.01)]
                if len(inside) >= max(3, len(re.sub(r"\s", "", u.src)) // 3):   # glyph-like cluster
                    box = pymupdf.Rect(pr)
                    for rr in inside: box |= rr
                    dup_boxes.append(box)
        for r, f in textr: pg.add_redact_annot(strip(r, f), fill=False, cross_out=False)
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                            text=pymupdf.PDF_REDACT_TEXT_REMOVE)
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
            for lr in dup_boxes:
                rest = [pymupdf.Rect(d_["rect"]) for d_ in pg.get_drawings()
                        if not pymupdf.Rect(d_["rect"]).is_empty and pymupdf.Rect(d_["rect"]).width < 40
                        and (pymupdf.Rect(d_["rect"]) & lr).get_area() > 0.6 * max(pymupdf.Rect(d_["rect"]).get_area(), 0.01)]
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
            continue
        s, ls, pitch, box, ok = fit_unit(u, pg.rect, obstacles)
        fnt = font(u.family, u.bold)
        # don't start on top of a kept glyph sitting just left of / under the box start ("|", bullets)
        for k in keeps:
            if (k[0] - 0.5 < box[0] < k[2] + 0.6 * s) and min(box[3], k[3]) - max(box[1], k[1]) > 0.3 * s and k[2] - k[0] < 3 * s:
                shift = k[2] + 0.35 * s - box[0]
                if shift > 0: box = (box[0] + shift, box[1], box[2] + shift, box[3])
        col = tuple(max(0.0, min(1.0, c)) for c in u.color)
        tw = tws.setdefault(col, pymupdf.TextWriter(pg.rect, color=col))
        # first baseline: original first baseline if the size is unchanged, else top-aligned
        base0 = u.lines[0][4] if abs(s - u.size) < 0.01 else box[1] + fnt.ascender * s * 0.98
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
        for hit in pg.search_for(str(k[4]).strip()):
            if not any(hit.intersects(kb) for kb in keep_boxes):
                h = hit.height
                pg.add_redact_annot(pymupdf.Rect(hit.x0 + 0.3, hit.y0 + 0.3 * h, hit.x1 - 0.3, hit.y1 - 0.3 * h), fill=False)
    pg.apply_redactions(images=0, graphics=0, text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for t, r, k in _keeps_moved(pg, kp):
        sp = spans.get(t)
        if not sp: rep.append({"issue": "keep_lost", "text": t[:30]}); continue
        for s_ in sp:
            fam = "serif" if (s_["flags"] & 4 or SERIF_HINT.search(s_["font"])) else "sans"
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
    noisy = erase_units(pg, plan.units, plan.keeps)
    removed = decor.remove(pg, decos)
    not_removed = [d for d in decos if d not in removed]
    rep = skipped + draw_units(pg, [u for u in plan.units if u.kind != "keep"], plan.keeps)
    rep += restore_keeps(pg, plan)
    iss, specs = decor.redraw(pg, plan.units, removed, not_removed)
    rep += rep_d + iss
    link_iss, remapped = decor.restore_links(pg, links, plan.units)
    rep += link_iss + decor.verify(pg, specs) + decor.crossings(plan.units, vrules)
    if specs or remapped:
        plan.notes.append({"decorations_redrawn": len(specs), "links_remapped": remapped})
    if noisy: rep.append({"issue": "patch_on_textured_background", "rects": noisy})
    return rep
