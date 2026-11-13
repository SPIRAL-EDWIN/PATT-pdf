"""Translations that must not reach the page as they came back, and how they are repaired.

Found on real documents: DeepL answered the figure legend "LLaMA 7B LLaMA 13B LLaMA 33B
LLaMA 65B" with the same text plus "简体中文（大陆）" (the name of the target language). A
check that only reports this is not enough: the text would still be drawn. Three layers:

1. prevention: text without anything translatable is never sent (`nothing_to_translate`);
2. detection (`suspicious`) and repair (`strip_labels`, then one retry with context in
   jobs.translate), applied when a translation arrives and again when it is read from the
   translation memory, so entries cached by older versions are repaired without a request;
3. fallback: the source text stays on the page and the page is marked for review.

The rules were checked against the 433 DeepL segments of the first real-document run:
prevention matched 8 (all names, model sizes or figures), detection matched 1 (the legend),
no other translation was touched.
"""
from __future__ import annotations

import re
import unicodedata

KEEP = "<KEEP>"            # translation-memory value meaning "leave the source text in place"

# ------------------------------------------------------------------ 1. prevention
_INNER_CAP = re.compile(r"[a-z][A-Z]")


def _name_token(tok: str) -> bool:
    t = tok.strip(".,;:()[]{}\"'“”‘’")
    if not re.search(r"[A-Za-z]", t):
        return True                                   # figures, symbols
    return bool(re.search(r"\d", t)) or bool(_INNER_CAP.search(t))     # "7B", "W-9", "GPT-3" / "LLaMA", "iPhone"


def nothing_to_translate(src: str) -> bool:
    """True for text made only of model names, codes and figures ("LLaMA 7B", "GPT-3",
    "StrategyQA", "13.0B"): every word carries a digit or inner capital, or has no letters.
    Ordinary words, also in capitals ("NOTE", "Table 2", "20 MILES"), are translated."""
    toks = src.split()
    return bool(toks) and all(_name_token(t) for t in toks) and any(re.search(r"[A-Za-z]", t) for t in toks)


# ------------------------------------------------------------------ 2. detection
_LABEL = re.compile(
    r"简体中文|繁體中文|繁体中文|中文[（(][^）)]{0,8}[）)]|[（(](?:中国)?大陆[）)]|[（(]简体[）)]|"
    r"\b[Zz][Hh][-_](?:CN|cn|Hans|HANS|hans)\b|Simplified Chinese|Chinese \(Simplified\)|Chinese \(simplified\)")
_ABOUT_LANGUAGE = re.compile(r"(?i)chinese|mandarin|language|locale|translat|中文")
_PUNCT = re.compile(r"[\s\W_]+", re.U)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def same_text(src: str, tgt: str) -> bool:
    """The translation is the source itself (names, codes): nothing has to be redrawn."""
    return _norm(src) == _norm(tgt)


def suspicious(src: str, tgt: str) -> list[str]:
    """Reasons why `tgt` should not be drawn for `src`; empty = no finding."""
    if tgt is None or tgt.strip() == KEEP:
        return []
    why = []
    s, t = _norm(src), _norm(tgt)
    if _LABEL.search(t) and not _LABEL.search(s) and not _ABOUT_LANGUAGE.search(s):
        why.append("language_label_added")
    if len(s) >= 4 and t != s:
        extra = None
        if t.startswith(s):
            extra = t[len(s):]
        elif t.endswith(s):
            extra = t[:-len(s)]
        if extra is not None and _PUNCT.sub("", extra):          # more than punctuation was added
            why.append("source_plus_extra_text")
    if len(s.split()) <= 5 and _width(t) > 3 * max(4, _width(s)):
        why.append("far_longer_than_source")
    return why


def strip_labels(tgt: str) -> str:
    """Remove language-name labels and the separators left around them."""
    return _LABEL.sub("", tgt).strip(" \t，,;；:：·-–—/|")


def repair(src: str, tgt: str) -> tuple[str | None, str]:
    """Local repair, no request. Returns (text, how): the usable translation and
    "ok" / "label_removed", or (None, reasons) when only a retry or the source can help."""
    why = suspicious(src, tgt)
    if not why:
        return tgt, "ok"
    cleaned = strip_labels(tgt)
    if cleaned and not suspicious(src, cleaned):
        return cleaned, "label_removed"
    return None, ",".join(why)
