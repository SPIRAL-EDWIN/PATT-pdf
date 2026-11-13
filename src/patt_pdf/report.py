"""Human-readable reports and side-by-side comparison images."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from .jobs import ISSUE_STATUS, Workspace


def collect(ws: Workspace, files: list[str]) -> list[dict]:
    rows = []
    for rel in files:
        qp = ws.qa_path(rel); ep = ws.error_path(rel)
        if qp.exists():
            rows.append(json.loads(qp.read_text(encoding="utf-8")))
        elif ep.exists():
            rows.append({"rel": rel, "status": "error", "error": json.loads(ep.read_text(encoding="utf-8"))["error"]})
        else:
            rows.append({"rel": rel, "status": "not rendered"})
    return rows


def _page_reasons(p: dict) -> list[str]:
    why = []
    if p.get("untranslated_units"): why.append(f"{p['untranslated_units']} untranslated unit(s)")
    if p.get("keep_changed"): why.append("kept figures changed: " + ", ".join(str(k[0]) for k in p["keep_changed"][:4]))
    if p.get("residual_en") and len(p["residual_en"]) > 3: why.append("residual English: " + " ".join(p["residual_en"][:8]))
    counts: dict[str, int] = {}
    for i in p.get("issues", []):
        counts[i.get("issue", "?")] = counts.get(i.get("issue", "?"), 0) + 1
    why += [f"{k} ×{v}" for k, v in counts.items()]
    return why


STATUS_TEXT = {"pass": "pass", "review": "needs review", "unverified": "UNVERIFIED", "fail": "FAIL", "error": "ERROR"}


def markdown(ws: Workspace, files: list[str]) -> str:
    rows = collect(ws, files)
    tot = sum(len(r.get("pages", [])) for r in rows)
    by: dict[str, int] = {}
    for r in rows:
        for p in r.get("pages", []):
            by[p.get("status", "?")] = by.get(p.get("status", "?"), 0) + 1
    out = ["# PATT-PDF report", "",
           f"Files: {len(rows)} · pages: {tot} · " + " · ".join(f"{STATUS_TEXT.get(k, k)}: {v}" for k, v in sorted(by.items())), "",
           "Statuses: **pass** = no automatic check found a problem; **needs review** = a human must look "
           "(e.g. figures read by OCR, explicitly accepted limitations); **UNVERIFIED** = a needed check could not run; "
           "**FAIL** = a known problem. Automatic QA does not prove a page is completely or correctly translated — "
           "check renders by eye (`patt-pdf compare`).", "",
           "| File | Status | Pages (pass/review/unverified/fail) | Problems |", "|---|---|---|---|"]
    for r in rows:
        pages = r.get("pages", [])
        cnt = [sum(1 for p in pages if p.get("status") == k) for k in ("pass", "review", "unverified", "fail")]
        probs = []
        for p in pages:
            if p.get("status") in ("review", "unverified", "fail", "error"):
                reasons = [f"{i['issue']}{' (accepted)' if i.get('accepted') else ''}" for i in p.get("issues", [])
                           if i.get("issue") in ISSUE_STATUS]
                probs.append(f"p{p['page']} {p['status']}: " + ", ".join(sorted(set(reasons))))
        st = STATUS_TEXT.get(r.get("status", "?"), r.get("status", "?")) + (f" ({r['error']})" if r.get("error") else "")
        out.append(f"| {r['rel']} | {st} | {'/'.join(map(str, cnt))} | " + ("<br>".join(probs) if probs else "—") + " |")
    review = [(r["rel"], p["page"], i.get("src", "")) for r in rows for p in r.get("pages", [])
              for i in p.get("issues", []) if i.get("issue") == "ocr_digits_review"]
    if review:
        out += ["", "## Figures read by OCR (verify against the original)", ""]
        out += [f"- {rel} p{pg}: {src}" for rel, pg, src in review]
    noinsp = [(r["rel"], p["page"], i["issue"]) for r in rows for p in r.get("pages", []) for i in p.get("issues", [])
              if i.get("issue") in ("image_not_inspected", "image_unverified")]
    if noinsp:
        out += ["", "## Images not verified — may contain untranslated text; check visually", ""]
        out += [f"- {rel} p{pg}: " + ("OCR unavailable" if why == "image_not_inspected" else "OCR found no legible text")
                for rel, pg, why in noinsp]
    left = [(r["rel"], p["page"], i.get("src", "")) for r in rows for p in r.get("pages", []) for i in p.get("issues", [])
            if i.get("issue") in ("image_text_left_english", "textured_background_left_english")]
    if left:
        out += ["", "## English left in place (inside images / textured backgrounds)", ""]
        out += [f"- {rel} p{pg}: {src}" for rel, pg, src in left]
    kept = [(r["rel"], p["page"], i) for r in rows for p in r.get("pages", []) for i in p.get("issues", [])
            if i.get("issue") in ("curved_text_left_english", "translation_left_source")]
    if kept:
        out += ["", "## Source text left in place (curved text; translations that could not be used)", ""]
        out += [f"- {rel} p{pg}: " + (f"{i.get('count')} curved run(s): " if i["issue"].startswith("curved") else "")
                + str(i.get("src", "")) for rel, pg, i in kept]
    acc = ws.state / "accept.json"
    if acc.exists():
        log = json.loads(acc.read_text(encoding="utf-8")).get("log", [])
        if log:
            out += ["", "## Explicitly accepted limitations", ""]
            out += [f"- {e['rel']} p{e['page']}: {e['issue']} — {e['note']} ({e['ts']})" for e in log]
    return "\n".join(out) + "\n"


def compare(ws: Workspace, rel: str, pages: list[int] | None, outdir: str, dpi: int = 80) -> list[Path]:
    """Write `<name>_p<N>.png` images: original (left) | output (right)."""
    from PIL import Image
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    written = []
    if not ws.out_path(rel).exists():
        return []
    with pymupdf.open(ws.path(rel)) as s, pymupdf.open(ws.out_path(rel)) as o:
        if pages is None and ws.qa_path(rel).exists():     # default: the pages that were rendered
            qa = json.loads(ws.qa_path(rel).read_text(encoding="utf-8"))
            pages = [p["page"] for p in qa.get("pages", []) if p.get("page")] or None
        for pno in (pages or range(1, s.page_count + 1)):
            a = s[pno - 1].get_pixmap(dpi=dpi); b = o[pno - 1].get_pixmap(dpi=dpi)
            A = Image.frombytes("RGB", (a.w, a.h), a.samples); B = Image.frombytes("RGB", (b.w, b.h), b.samples)
            C = Image.new("RGB", (a.w + b.w + 8, max(a.h, b.h)), (220, 30, 30))
            C.paste(A, (0, 0)); C.paste(B, (a.w + 8, 0))
            p = outdir / f"{Path(rel).stem}_p{pno}.png"; C.save(p); written.append(p)
    return written
