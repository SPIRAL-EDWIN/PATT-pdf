"""Keep rules: text that must never be translated or moved (figures, ratings, URLs...).

Migrated verbatim from prototype layout module (is_keep and regexes); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

import re

_KEEP_WORDS = r"(?:USD|CHF|EUR|GBP|JPY|CNY|RMB|HKD|SGD|AUD|CAD|US\$|bn|mn|mln|m|k|x|bp|bps|p\.a\.|Q[1-4]|H[12]|FY|YTD|LIBOR|SOFR|EBITDA|EBIT|EPS|ROE|ROA|ROIC|DPO|DSO|DIO|CCC|SCF|AR|AP|vs\.?|No\.|n/a|N/A|NM|nm|AM|PM|am|pm|a\.m\.|p\.m\.|ET|PT|GMT)"


KEEP_RE = re.compile(r"^(?:[\s\d.,:;%()\[\]{}+\-–—−/\\$€£¥#*&@•·°§|<>=~'\"’‘“”…^_®©™]|" + _KEEP_WORDS + r"\b)*$")


URL_RE = re.compile(r"^\s*(https?://\S+|www\.\S+|\S+@\S+\.\w+)\s*$", re.I)


HAS_LATIN = re.compile(r"[A-Za-z]")


RATING_RE = re.compile(r"^(?:AAA|AA|A|BBB|BB|B|CCC|CC|C|D|Aaa|Aa[1-3]|A[1-3]|Baa[1-3]|Ba[1-3]|B[1-3]|Caa[1-3])[+\-–−]?$")


def is_keep(text):
    t = text.strip()
    if not t: return True
    if RATING_RE.match(t): return True
    if not HAS_LATIN.search(t): return True                 # already Chinese / symbols only
    if URL_RE.match(t): return True
    if " " not in t and re.search(r"[?=/&_]|\.(com|org|net|htm|html|pdf|aspx)\b", t) and not re.search(r"[一-鿿]", t):
        return True                       # URL fragment / file name (e.g. "?mod=article_inline")
    if KEEP_RE.match(t): return True
    if len(re.sub(r"[^A-Za-z]", "", t)) <= 1 and len(t) <= 4: return True   # "a)", "B", footnote marks
    if NUM_UNIT_RE.match(t) and not ORDINAL_RE.search(t): return True      # "13.0B", "1.4T", "3.0e-4", "4M"
    return False


# A table cell or label that is only a figure with a short unit suffix. Sending it to a
# translator rewrites the figure ("13.0B" -> "130亿") and breaks the column; it is kept as is.
NUM_UNIT_RE = re.compile(r"^[-+−–~≈<>≤≥]?\s?[$€£¥]?\d[\d.,]*(?:\s?[eE×x]\s?[-+−–]?\d+)?\s?[A-Za-z%°µ]{0,2}$")
ORDINAL_RE = re.compile(r"\d(?:st|nd|rd|th)$", re.I)


SERIF_HINT = re.compile(r"times|serif|georgia|garamond|minion|roman|cambria|book|palat|caslon|baskerv|utopia|cmr|nimbus ?rom|tiempos|publico|exchange|escrow", re.I)


# Font names that are sans-serif although the PDF "serif" flag is set or the name contains a
# serif hint ("HelveticaNeue-Roman", "Avenir-Book"). Checked BEFORE SERIF_HINT.
SANS_HINT = re.compile(r"sans|helvet|arial|univers|calibri|gothic|grotes|frutiger|myriad|verdana|tahoma|segoe|roboto|"
                       r"lato|futura|avenir|gill|cmss|inter\b|montserrat|ubuntu|fira|optima|trebuc|akzidenz|\bdin|"
                       r"franklin|swiss|interstate|proxima|museo|nunito|poppins|raleway|oswald|candara|corbel|"
                       r"courier|mono|consol|inconsolata|menlo|cmtt|typewriter|code", re.I)


def font_family(name: str, flags: int = 0) -> str:
    """'sans' or 'serif' for a PDF font. The name decides when it is recognisable; the PDF
    serif flag (bit 4) is only a fallback, because many producers set it for every font
    (Helvetica, Univers and Arial carried it in real documents)."""
    if SANS_HINT.search(name or ""): return "sans"
    if SERIF_HINT.search(name or ""): return "serif"
    return "serif" if flags & 4 else "sans"


BOLD_HINT = re.compile(r"bold|black|heavy|semibold|demi|-bd|,bd", re.I)


BULLET_RE = re.compile(r"^(?:[▪•·◦●○■□►▶➢✓\-–—*\uf0a7\uf0b7\uf076\uf0d8\uf0fc]|\(?[0-9]{1,2}[.)]|\(?[a-zA-Z][.)]|[ivx]{1,4}[.)])$")


SEP_CHARS = set("|│¦•")
