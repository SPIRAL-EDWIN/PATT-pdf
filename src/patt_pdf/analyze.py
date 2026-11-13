"""Document planning: classify each page and extract translation units.

``plan_document`` migrated from the private prototype.
"""
from __future__ import annotations

import re

import pymupdf

from .classify import classify_page
from .extract_text import plan_text_page
from .model import PagePlan


IMAGE_MIN_FRACTION = 0.03     # images smaller than 3 % of the page are not inspected


def inspect_images(pg, ocr: bool) -> list[dict]:
    """List embedded images on a text page. With OCR available, also report whether
    legible English is inside them. Image text is never translated in v0.1; this only
    makes the omission visible in the report."""
    out = []
    area = pg.rect.width * pg.rect.height
    for info in pg.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & pg.rect
        if r.is_empty or r.width * r.height < IMAGE_MIN_FRACTION * area:
            continue
        entry = {"bbox": [round(v, 1) for v in r], "english": None}
        if ocr:
            try:
                from .ocr import _tesseract_multi, render_rgb
                arr, png = render_rgb(pg, 200, clip=r)
                words = [w["text"] for w in _tesseract_multi(arr, png)
                         if w["conf"] >= 70 and re.fullmatch(r"[A-Za-z]{3,}[.,:;!?]?", w["text"])]
                entry["english"] = " ".join(words)[:120]
            except Exception as e:              # OCR missing/failing: keep the entry, say why
                entry["english"] = None; entry["ocr_error"] = f"{type(e).__name__}: {e}"[:160]
        out.append(entry)
    return out


def page_needs_ocr(pg) -> bool:
    """True when planning this page will call Tesseract (seconds, not milliseconds): pages
    without a usable text layer and text pages that carry an image worth inspecting."""
    kind = classify_page(pg)
    if kind == "blank":
        return False
    if kind in ("vector", "raster", "vector_few"):
        return True
    area = pg.rect.width * pg.rect.height
    for info in pg.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & pg.rect
        if not r.is_empty and r.width * r.height >= IMAGE_MIN_FRACTION * area:
            return True
    return False


def plan_page(pg, pno: int, ocr: bool = True) -> PagePlan:
    kind = classify_page(pg)
    if kind == "text":
        plan = plan_text_page(pg, pno)
        imgs = inspect_images(pg, ocr)
        if imgs:
            plan.notes.append({"images": imgs})
        return plan
    if kind == "vector_few":
        return _plan_vector_few(pg, pno, ocr)
    if kind == "graphics":
        imgs = inspect_images(pg, ocr)
        return PagePlan(pno, "graphics", [], [], [{"images": imgs}] if imgs else [])
    if kind in ("vector", "raster"):
        if not ocr:
            return PagePlan(pno, kind, [], [], [{"skipped": "ocr disabled"}])
        from .ocr import OCRUnavailable, ocr_dependency_problem, plan_ocr_page
        missing = ocr_dependency_problem()
        if missing:                                # e.g. opencv not installed / no wheel for this CPU
            return PagePlan(pno, kind, [], [], [{"skipped": missing}])
        try:
            return plan_ocr_page(pg, pno, kind)
        except OCRUnavailable as e:
            return PagePlan(pno, kind, [], [], [{"skipped": f"OCR unavailable: {e}"}])
    return PagePlan(pno, "blank", [], [])


def _plan_vector_few(pg, pno, ocr):
    """A handful of outline glyphs and no text layer: maybe a short outlined label."""
    why = "a few outline glyphs and no text layer (possibly short outlined text)"
    if not ocr:
        return PagePlan(pno, "graphics", [], [], [{"unverified": why + "; OCR disabled"}])
    try:
        from .ocr import OCRUnavailable, plan_ocr_page
        plan = plan_ocr_page(pg, pno, "vector")
    except ImportError as e:
        return PagePlan(pno, "graphics", [], [], [{"unverified": why + f"; OCR dependencies missing ({e.name})"}])
    except OCRUnavailable as e:
        return PagePlan(pno, "graphics", [], [], [{"unverified": why + f"; OCR unavailable: {e}"}])
    if plan.units:
        return plan
    plan.kind = "graphics"; plan.notes.append({"ocr_found_no_text": True})
    return plan


def plan_document(doc, pages=None, ocr: bool = True) -> list[PagePlan]:
    return [plan_page(doc[pno], pno, ocr) for pno in (pages if pages is not None else range(len(doc)))]
