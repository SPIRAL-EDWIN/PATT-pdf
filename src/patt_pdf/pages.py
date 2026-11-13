"""Page selection: ``--pages 7``, ``7-9``, ``7,9``, ``1-3,7,10-`` (1-based, as printed).

A selection is a comma-separated list; each item is one page or a range. An open range
(``10-`` = to the last page, ``-3`` = the first three) is allowed. Duplicates and order do
not matter. Anything else is an error: nothing is guessed.
"""
from __future__ import annotations

import re

_ITEM = re.compile(r"^(?:(\d+)|(\d+)-(\d+)|(\d+)-|-(\d+))$")


class PageSelectionError(ValueError):
    """The --pages value is malformed or does not fit the document."""


def parse(spec: str) -> list[tuple[int | None, int | None]]:
    """Syntax check only. Returns [(first, last)] with None for an open end (1-based)."""
    if spec is None or not str(spec).strip():
        raise PageSelectionError("--pages is empty (examples: 7   7-9   7,9   1-3,7,10-)")
    out = []
    for raw in str(spec).split(","):
        item = raw.strip()
        m = _ITEM.match(item)
        if not m:
            raise PageSelectionError(f"--pages: cannot read {item!r} (examples: 7   7-9   7,9   1-3,7,10-)")
        one, a, b, start, end = m.groups()
        if one:
            lo = hi = int(one)
        elif a:
            lo, hi = int(a), int(b)
        elif start:
            lo, hi = int(start), None
        else:
            lo, hi = None, int(end)
        if lo == 0 or hi == 0:
            raise PageSelectionError("--pages: page numbers start at 1")
        if lo is not None and hi is not None and lo > hi:
            raise PageSelectionError(f"--pages: range {item!r} runs backwards")
        out.append((lo, hi))
    return out


def resolve(spec: str, page_count: int) -> list[int]:
    """Sorted, de-duplicated 0-based page indexes of `spec` in a document of `page_count` pages."""
    sel: set[int] = set()
    for lo, hi in parse(spec):
        lo = 1 if lo is None else lo
        hi = page_count if hi is None else hi
        if lo > page_count or hi > page_count:
            raise PageSelectionError(f"--pages: the document has {page_count} page(s); "
                                     f"{max(lo, hi)} is outside it")
        sel.update(range(lo - 1, hi))
    return sorted(sel)


def label(indexes) -> str:
    """Compact text for a selection of 0-based indexes: [0,1,2,6] -> '1-3,7' (file names, messages)."""
    nums = sorted({i + 1 for i in indexes})
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(parts)
