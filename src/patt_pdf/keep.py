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
    return False


SERIF_HINT = re.compile(r"times|serif|georgia|garamond|minion|roman|cambria|book|palat|caslon|baskerv|utopia|cmr|nimbus ?rom|tiempos|publico|exchange|escrow", re.I)


BOLD_HINT = re.compile(r"bold|black|heavy|semibold|demi|-bd|,bd", re.I)


BULLET_RE = re.compile(r"^(?:[▪•·◦●○■□►▶➢✓\-–—*\uf0a7\uf0b7\uf076\uf0d8\uf0fc]|\(?[0-9]{1,2}[.)]|\(?[a-zA-Z][.)]|[ivx]{1,4}[.)])$")


SEP_CHARS = set("|│¦•")
