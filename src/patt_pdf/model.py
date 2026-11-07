"""Data model: translation units and per-page plans.

Migrated verbatim from prototype layout module (Unit, PagePlan); changes listed in docs/MIGRATION.md."""
from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class Unit:
    uid: str                 # stable id: page-kind-index
    page: int
    kind: str                # text | vector | raster | imgtext
    src: str                 # source text (normalized, one paragraph)
    bbox: list               # union rect (PDF pt)
    lines: list              # [[x0,y0,x1,y1, baseline_y], ...] per original line
    size: float
    bold: bool
    family: str              # sans | serif
    color: list              # rgb 0..1
    align: str = "left"
    erase: list = field(default_factory=list)   # rects to remove
    angle: float = 0.0       # degrees, for rotated labels (origin = lines[0][0], lines[0][4])
    tgt: str = ""


@dataclass
class PagePlan:
    page: int
    kind: str
    units: list
    keeps: list              # [[x0,y0,x1,y1,text]] regions that must stay identical
    notes: list = field(default_factory=list)
