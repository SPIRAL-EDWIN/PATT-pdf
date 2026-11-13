"""Quality checks. They flag problems; passing them does NOT prove a page is fully
and correctly translated — compare renders by eye (``patt-pdf compare``).

Migrated from prototype jobs module (numbers, _tgt_values, _expand_ranges,
number_check, residual_english, residual_english_ocr, keep_integrity). Changes:
* keep_integrity renders from FRESH document handles (see docs/BASELINE.md: a clipped
  render after a full render of the same Page object can differ → false positives);
* corpus-specific suppressions (e.g. "catch-22", "Finance 101") moved to an explicit,
  documented list instead of being hidden inside number_check.
"""
from __future__ import annotations

import re

import numpy as np
import pymupdf

# ------------------------------------------------------------------ numbers
_NUM = re.compile(r"(?i)(?<![A-Za-z0-9.])[-−–(]?[$€£¥]?\s?\d[\d,]*(?:\.\d+)?\s?"
                  r"(?:%|(?:trillion|billion|million|thousand|tn|bn|mn|b|m|k)(?![A-Za-z0-9])|[多余]?(?:万亿|亿|万|千|百万|十亿))?\)?")
# NOTE: the scale words end with an ASCII-only lookahead, not \b: "540B提示" has no \b after
# the B (CJK characters are \w), so the same token read 5.4e11 in English and 540 in Chinese.
# NOTE: the lookbehind must be ASCII-only — Python's \w matches CJK characters, which
# would hide every digit that directly follows Chinese text ("第1项").
_SCALE = {"b": 1e9, "trillion": 1e12, "tn": 1e12, "万亿": 1e12, "billion": 1e9, "bn": 1e9, "million": 1e6,
          "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3, "亿": 1e8, "万": 1e4, "千": 1e3, "百万": 1e6, "十亿": 1e9}
_ZH_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
_RANGE = re.compile(r"(?i)([$€£]\s?\d[\d,.]*)\s*(?:to|-|–)\s*[$€£]?\s?\d[\d,.]*\s*(trillion|billion|million|thousand|bn|mn)")

# Idioms that contain digits but are not quantities. Extend with care; each entry hides
# real errors in matching sentences.
NON_QUANTITY_IDIOMS = [r"catch-\s?22", r"\b\w+ 101\b"]


def numbers(s: str):
    out = []
    for m in _NUM.finditer(s):
        t = m.group(0)
        neg = t.lstrip()[:1] in "-−–(" and (t.rstrip().endswith(")") or t.lstrip()[:1] != "(")
        sc = 1.0
        tl = t.rstrip(")").rstrip().lower()
        for k in sorted(_SCALE, key=len, reverse=True):
            if tl.endswith(k):
                sc = _SCALE[k]; break
        d = re.sub(r"[^\d.]", "", t.split("%")[0]).strip(".")
        if not d:
            continue
        try:
            v = float(d.replace(",", ""))
        except ValueError:
            continue
        out.append((round(v * sc, 6), neg, "%" in t))
    return out


def _tgt_values(tgt: str):
    vals = [x[0] for x in numbers(tgt)]
    for m in re.finditer(r"(\d{2})世纪(\d0)年代", tgt):                 # 20世纪90年代 = 1990s
        vals.append(float((int(m.group(1)) - 1) * 100 + int(m.group(2))))
    for m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", tgt):       # 2018年12月20日 = 20.12.2018
        y, mo, d = m.groups()
        vals += [float(f"{int(d)}.{int(mo):02d}"), float(f"{int(mo)}.{int(d):02d}"), float(d), float(mo)]
    for ch, v in _ZH_NUM.items():
        if ch in tgt:
            vals.append(float(v))
    return vals


def _expand_ranges(src: str) -> str:
    """'$125 to $150 million' -> the scale word applies to both figures."""
    return _RANGE.sub(lambda m: m.group(1) + " " + m.group(2) + " " + m.group(0)[len(m.group(1)):], src)


def number_check(src: str, tgt: str) -> list[str]:
    """Every quantity in `src` must appear in `tgt` (after scale conversion such as
    '$2.3 billion' = '23亿美元'). Returns human-readable issues; empty = no finding."""
    if tgt.strip() == "<KEEP>":
        return []
    src = _expand_ranges(src)
    src = re.sub(r"(?<=[a-z.)”\"])(\d{1,3}(?:,\d{1,3})+)(?=\s)", lambda m: m.group(0).replace(",", " "), src)  # footnote marks
    src = re.sub(r"(?i)\b(\d+)\s?M\s+(USD|EUR|CHF)\b", r"\1-month \2", src)                           # "3 M USD LIBOR"
    src = re.sub(r"(?<=\d),\s(?=\d{3}(?!\d))", ",", src)          # TeX thin space: "2, 000" = 2,000
    # reference marks such as "Coyle1,2,3": groups of one or two digits cannot be a thousands
    # grouping; read them as separate numbers on both sides
    marks = lambda x: re.sub(r"(?<![\d.,])\d{1,2}(?:,\d{1,2})+(?![\d.,]|\s?%)", lambda m: m.group(0).replace(",", " "), x)
    src, tgt = marks(src), marks(tgt)
    for pat in NON_QUANTITY_IDIOMS:
        src = re.sub(pat, " ", src, flags=re.I)
    s, t = numbers(src), numbers(tgt)
    tv = _tgt_values(tgt)
    issues = []
    for v, neg, pct in s:
        if not any(abs(v - w) <= 1e-6 * max(1, abs(v)) for w in tv):
            issues.append(f"missing {v:g}{'%' if pct else ''}")
    if sum(1 for x in s if x[1]) > sum(1 for x in t if x[1]) and not re.search(r"[（(]", tgt):
        issues.append("sign/parentheses lost")
    if src.count("%") > tgt.count("%"):
        issues.append("percent sign lost")
    for cur, zh in (("$", "美元"), ("£", "英镑"), ("€", "欧元"), ("CHF", "瑞士法郎")):
        if cur in src and cur not in tgt and zh not in tgt:
            issues.append(f"currency {cur} lost")
    return issues


URL_IN_TEXT = re.compile(r"(?:https?:/+|www\.)\S+|\S+\.(?:pdf|htm|html)\b")


def url_check(src: str, tgt: str) -> list[str]:
    """URLs must survive translation verbatim (DeepL sometimes translates or re-cases them)."""
    return [f"url altered: {u[:60]}" for u in (x.rstrip(".,;:") for x in URL_IN_TEXT.findall(src)) if u not in tgt]


# ------------------------------------------------------------------ residual English
def residual_english(page, plan, tgts):
    """Latin words (>=3 letters) on the output text layer outside kept regions and not
    part of the Chinese targets (brand names in targets are allowed)."""
    allowed = {w.lower() for t in tgts for w in re.findall(r"[A-Za-z]{3,}", t)}
    keep_rects = [pymupdf.Rect(k[:4]) for k in plan.keeps]
    res = []
    for w in page.get_text("words"):
        if not re.search(r"[A-Za-z]{3,}", w[4]):
            continue
        r = pymupdf.Rect(w[:4])
        if any(r.intersects(k) for k in keep_rects):
            continue
        res += [tok for tok in re.findall(r"[A-Za-z]{3,}", w[4]) if tok.lower() not in allowed]
    return res


def residual_english_ocr(page, plan, tgts, dpi=200):
    """OCR the rendered OUTPUT page; low-confidence source regions are not excluded."""
    from .ocr import _tesseract_multi, render_rgb
    arr, png = render_rgb(page, dpi)
    words = _tesseract_multi(arr, png)
    allowed = {w.lower() for t in tgts for w in re.findall(r"[A-Za-z]{3,}", t)}
    keep_rects = [pymupdf.Rect(k[:4]) for k in plan.keeps]
    sc = dpi / 72; res = []
    for w in words:
        if w["conf"] < 70 or not re.fullmatch(r"[\"'“(]?[A-Za-z'’\-]{3,}[.,;:!?)”\"]?", w["text"]):
            continue
        r = pymupdf.Rect(w["x"] / sc, w["y"] / sc, (w["x"] + w["w"]) / sc, (w["y"] + w["h"]) / sc)
        if any(r.intersects(k) for k in keep_rects):
            continue
        tok = re.sub(r"[^A-Za-z]", "", w["text"])
        if tok.lower() not in allowed:
            res.append(tok)
    return res


# ------------------------------------------------------------------ kept regions
def _crop(path, pno, rect, dpi):
    with pymupdf.open(path) as d:                 # fresh handle per check (see module doc)
        pg = d[pno]
        r = pymupdf.Rect(rect) & pg.rect
        if r.is_empty or r.width < 1 or r.height < 1:
            return None
        pm = pg.get_pixmap(dpi=dpi, clip=r, colorspace=pymupdf.csRGB, alpha=False)
        return np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.h, pm.w, 3).astype(int).mean(axis=2)


def keep_integrity(src_path, out_path, pno, plan, dpi=110, threshold=0.15):
    """A kept item (figure, page no., separator) counts as changed when >15 % of its
    original ink pixels differ in the output — catches erased, shifted or over-printed
    digits, while new text merely passing through the box padding is tolerated."""
    bad = []
    for k in plan.keeps:
        a = _crop(src_path, pno, k[:4], dpi); b = _crop(out_path, pno, k[:4], dpi)
        if a is None or b is None:
            continue
        if a.shape != b.shape:
            bad.append([str(k[4])[:20], "shape"]); continue
        bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]))
        ink = np.abs(a - bg) > 60
        if ink.sum() < 3:
            continue
        changed = float((np.abs(a - b)[ink] > 60).mean())
        if changed > threshold:
            bad.append([str(k[4])[:20], round(changed, 2)])
    return bad
