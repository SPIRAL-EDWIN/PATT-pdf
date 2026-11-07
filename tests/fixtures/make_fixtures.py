"""Generate the synthetic test corpus for PATT-PDF.

Every PDF here is produced by this script from scratch (PyMuPDF base-14 fonts and
drawing primitives). The themes (a fictional birding society, a community observatory,
a coastal trail) and all names, figures, dates and URLs are invented for these tests;
nothing is derived from third-party documents, so the fixtures are freely
redistributable under the project licence.

Usage:  python tests/fixtures/make_fixtures.py OUTDIR
Each fixture is described in FIXTURES; tests read the ground truth written next to the
PDFs (truth.json) and the fixed translations (manual_tm.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

A4 = (595, 842)

# Fixed, offline "translations" for every translatable sentence in the fixtures.
# Used by the `manual` backend in tests (no network, no quota).
MANUAL_TM: dict[str, str] = {
    # toc
    "Contents": "目录",
    "Getting started": "入门",
    "Where to look? Seasonal patterns": "去哪里观察？季节规律",
    "Where to look?": "去哪里观察？",
    "Seasonal patterns": "季节规律",
    "Identification tips": "识别要点",
    "Glossary": "术语表",
    "Northwind Birding Society": "北风观鸟协会",
    # financial (budget table)
    "Observatory Budget (in dollars)": "天文台预算（单位：美元）",
    "Telescope upkeep": "望远镜维护",
    "Visitor programmes": "访客项目",
    "Library subscriptions": "图书订阅",
    "Currency adjustment": "汇率调整",
    "Total spending": "支出合计",
    "Visitors rose to 14.2 thousand in 2024, up 8.5% from 2023.": "2024年访客增至1.42万人次，较2023年增长8.5%。",
    # two columns
    "Migrating shorebirds rest on tidal flats at high water. "
    "Volunteers count them from the dike at dawn.":
        "迁徙的滨鸟在涨潮时停歇在潮滩上。志愿者在黎明时从堤坝上清点它们。",
    "Light pollution reduces the number of visible stars near towns.":
        "光污染减少了城镇附近可见星星的数量。",
    # rotated / misc
    "Day 1: Arrival": "第1天：抵达",
    "Notes for volunteers": "志愿者须知",
    "Scanned note: the gate opens 60 minutes before sunrise.": "扫描便条：大门在日出前60分钟开放。",
    "Image caption text": "图片说明文字",
    # table
    "Monthly visits": "每月到访",
    "Site": "地点",
    "Ticket sales": "门票收入",
    "Change": "变动",
    "Date": "日期",
    "North dike": "北堤",
    "Old lighthouse": "旧灯塔",
    "Salt marsh": "盐沼",
    "Page 7": "第7页",
    "Page 3 of 9": "第3页，共9页",
    # decorations, page 1 (cases PATT-PDF handles)
    "FIELD NOTES SUMMARY": "野外记录摘要",
    "Map": "步道地图",
    "Volunteers should read the safety rules before the first guided walk along the coast.":
        "志愿者在第一次沿海岸的导览步行之前，应当仔细阅读安全守则，并确认集合时间、路线、天气预报以及紧急联系方式。",
    "Night sky checklist": "夜空观测清单",
    "Read the field guide": "阅读野外指南",
    "Contact: info@example.org": "联系方式：info@example.org",
    "Old meeting point": "旧集合点",
    "Heron count": "苍鹭数",
    "Egret count": "白鹭数",
    # decorations, page 2 (cases PATT-PDF only reports)
    "Bring warm clothes and a torch.": "请带上保暖衣物和手电筒。",
    "See the map for opening hours.": "开放时间请参阅地图。",
    "Meet at the north gate.": "在北门集合。",
    # scanned underline
    "Scanned notice: quiet zone": "扫描告示：静区",
}


def _text(page, xy, s, size=11, font="helv", color=(0, 0, 0), rotate=0):
    page.insert_text(xy, s, fontsize=size, fontname=font, color=color, rotate=rotate)


def _w(s, font="helv", size=11):
    return pymupdf.get_text_length(s, fontname=font, fontsize=size)


def toc(out: Path):
    """Big bold section numbers as separate spans next to titles (BabelDOC merged these)."""
    doc = pymupdf.open(); pg = doc.new_page(width=842, height=595)
    _text(pg, (25, 44), "Contents", 22)
    items = [(1, 140, "Getting started", "hebo"), (2, 205, None, "helv"), (3, 270, "Identification tips", "helv")]
    for n, y, title, f in items:
        _text(pg, (44, y), str(n), 26, "hebo")
        if title:
            _text(pg, (75, y - 4), title, 16, f)
    _text(pg, (75, 194), "Where to look?", 16)
    _text(pg, (75, 213), "Seasonal patterns", 16)
    _text(pg, (387, 140), "5", 26, "hebo"); _text(pg, (417, 136), "Glossary", 16)
    _text(pg, (120, 523), "Northwind Birding Society", 8)
    _text(pg, (689, 523), "2", 8)
    doc.save(out / "toc.pdf")
    return {"keep": ["1", "2", "3", "5"], "translate": ["Contents", "Getting started", "Glossary"]}


FIN_ROWS = [("Telescope upkeep", "$", "48,210", "45,975"),
            ("Visitor programmes", "", "31,604", "29,388"),
            ("Library subscriptions", "", "7,950", "—"),
            ("Currency adjustment", "", "(2,317)", "(1,846)"),
            ("Total spending", "$", "85,447", "73,517")]


def financial(out: Path):
    """Budget table: $, thousands separators, parenthesised negatives, em-dash."""
    doc = pymupdf.open(); pg = doc.new_page(width=A4[0], height=A4[1])
    _text(pg, (40, 60), "Observatory Budget (in dollars)", 13, "hebo")
    y = 100
    for label, cur, a, b in FIN_ROWS:
        _text(pg, (40, y), label, 9)
        if cur: _text(pg, (330, y), cur, 9)
        _text(pg, (380 - _w(a, size=9) + 40, y), a, 9)
        _text(pg, (500 - _w(b, size=9) + 40, y), b, 9)
        pg.draw_line((40, y + 3), (555, y + 3), color=(0.8, 0.8, 0.8), width=0.4)
        y += 16
    _text(pg, (40, 220), "Visitors rose to 14.2 thousand in 2024, up 8.5% from 2023.", 10)
    _text(pg, (40, 800), "Page 7 | https://example.com/report?id=42", 7)
    doc.save(out / "financial.pdf")
    return {"keep": ["48,210", "45,975", "(2,317)", "(1,846)", "85,447", "73,517", "—"],
            "numbers_sentence": "Visitors rose to 14.2 thousand in 2024, up 8.5% from 2023."}


PARA = ("Migrating shorebirds rest on tidal flats at high water. "
        "Volunteers count them from the dike at dawn.")


def two_column_cropbox(out: Path):
    """Two columns, page CropBox offset inside a larger MediaBox (journal-style)."""
    doc = pymupdf.open(); pg = doc.new_page(width=842, height=1191)
    pg.set_cropbox(pymupdf.Rect(42, 47, 586, 789))      # crop in unrotated page coordinates
    left = pymupdf.Rect(84, 120, 300, 400); right = pymupdf.Rect(330, 120, 546, 400)
    pg.insert_textbox(left, PARA + " " + PARA, fontsize=10, fontname="tiro")
    pg.insert_textbox(right, "Light pollution reduces the number of visible stars near towns. " * 3,
                      fontsize=10, fontname="tiro")
    _text(pg, (84, 700), "doi:10.0000/example.2026.001", 7, "tiro")
    doc.save(out / "two_column_cropbox.pdf")
    return {"cropbox_offset": True, "keep": ["doi:10.0000/example.2026.001"]}


def rotated(out: Path):
    doc = pymupdf.open(); pg = doc.new_page(width=842, height=595)
    _text(pg, (40, 300), "Day 1: Arrival", 10, "hebo", rotate=90)
    _text(pg, (120, 100), "Notes for volunteers", 12)
    doc.save(out / "rotated.pdf")
    return {"rotated": ["Day 1: Arrival"]}


def _outline(sp):
    """Convert a page to outlines (like 'Microsoft: Print To PDF'): no text layer."""
    svg = sp.get_svg_image(text_as_path=True)
    vec = pymupdf.open("svg", svg.encode())
    return pymupdf.open("pdf", vec.convert_to_pdf())


def vector_glyphs(out: Path):
    src = pymupdf.open(); sp = src.new_page(width=A4[0], height=A4[1])
    _text(sp, (60, 100), "Light pollution reduces the number of visible stars near towns.", 12, "tiro")
    _text(sp, (60, 130), "Page 3 of 9", 9, "tiro")
    _outline(sp).save(out / "vector_glyphs.pdf")
    return {"vector": True, "keep": ["3", "9"]}


def _rasterize(sp, out_file, dpi=200, seed=7):
    import numpy as np
    pm = sp.get_pixmap(dpi=dpi)
    arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.h, pm.w, pm.n).copy()
    rng = np.random.default_rng(seed)
    arr = np.clip(arr.astype(int) + rng.integers(-6, 7, arr.shape), 0, 255).astype(np.uint8)
    noisy = pymupdf.Pixmap(pymupdf.csRGB, pm.w, pm.h, arr.tobytes(), False)
    doc = pymupdf.open(); pg = doc.new_page(width=sp.rect.width, height=sp.rect.height)
    pg.insert_image(pg.rect, stream=noisy.tobytes("jpg", jpg_quality=80))
    doc.save(out_file, deflate=True)


def scanned(out: Path, dpi=200):
    """Raster-only page with light noise and a pale highlighter band."""
    src = pymupdf.open(); sp = src.new_page(width=A4[0], height=A4[1])
    sp.draw_rect(pymupdf.Rect(55, 88, 470, 106), color=None, fill=(1, 0.95, 0.6))
    _text(sp, (60, 100), "Scanned note: the gate opens 60 minutes before sunrise.", 12, "helv")
    _text(sp, (60, 140), "2026-11-06", 10, "helv")
    _rasterize(sp, out / "scanned.pdf", dpi)
    return {"raster": True}


def image_text(out: Path):
    """A text page with a photo-like textured image that contains English text."""
    import numpy as np
    doc = pymupdf.open(); pg = doc.new_page(width=A4[0], height=A4[1])
    _text(pg, (40, 60), "Notes for volunteers", 12)
    rng = np.random.default_rng(3)
    tex = (rng.random((200, 400, 3)) * 255).astype(np.uint8)
    pm = pymupdf.Pixmap(pymupdf.csRGB, 400, 200, tex.tobytes(), False)
    tmp = pymupdf.open(); tp = tmp.new_page(width=400, height=200)
    tp.insert_image(tp.rect, pixmap=pm)
    _text(tp, (30, 110), "Image caption text", 28, "hebo", color=(1, 1, 1))
    img = tp.get_pixmap(dpi=72)
    pg.insert_image(pymupdf.Rect(40, 100, 440, 300), pixmap=img)
    doc.save(out / "image_text.pdf")
    return {"image_text": ["Image caption text"]}


def damaged(out: Path):
    # truncated after the header: PyMuPDF "repairs" it into a 0-page document
    (out / "damaged.pdf").write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >>\ngarbage-not-a-pdf")
    # a real PDF cut in half (xref lost)
    whole = pymupdf.open(); _text(whole.new_page(), (72, 72), "Truncated file", 12)
    data = whole.tobytes(); (out / "truncated.pdf").write_bytes(data[: len(data) // 2])
    return {"damaged": True}


def encrypted(out: Path):
    """Password-protected PDF (AES-256, user password 'secret')."""
    doc = pymupdf.open(); _text(doc.new_page(), (72, 72), "Encrypted content", 12)
    doc.save(out / "encrypted.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    return {"encrypted": True}


def table(out: Path):
    """Ruled table with header row, percentages, negative values in parentheses and dates."""
    doc = pymupdf.open(); pg = doc.new_page(width=A4[0], height=A4[1])
    _text(pg, (40, 60), "Monthly visits", 12, "hebo")
    cols = [40, 220, 330, 440]
    rows = [("Site", "Ticket sales", "Change", "Date"),
            ("North dike", "$1,204.5", "(3.2%)", "31.03.2025"),
            ("Old lighthouse", "EUR 812.0", "4.7%", "31.03.2025"),   # base-14 fonts cannot encode "€"
            ("Salt marsh", "¥9,870", "-1.5%", "2025-03-31")]
    y = 90
    for r in rows:
        for x, cell in zip(cols, r):
            _text(pg, (x + 4, y), cell, 9, "hebo" if y == 90 else "helv")
        pg.draw_line((40, y + 4), (555, y + 4), color=(0, 0, 0), width=0.5)
        y += 18
    for x in cols + [555]:
        pg.draw_line((x, 78), (x, y - 14), color=(0, 0, 0), width=0.5)
    doc.save(out / "table.pdf")
    return {"keep": ["$1,204.5", "(3.2%)", "EUR 812.0", "4.7%", "¥9,870", "-1.5%", "31.03.2025", "2025-03-31"]}


def unicode_name(out: Path):
    """Non-ASCII file name with spaces (path handling on all platforms)."""
    doc = pymupdf.open(); _text(doc.new_page(), (72, 72), "Notes for volunteers", 12)
    doc.save(out / "报告 2026 – résumé.pdf")
    return {"unicode_name": True}


def decorations(out: Path):
    """Underlines, a strike-through line, links, a table grid and a separator.

    Page 1: cases PATT-PDF moves (expected QA `pass`).
    Page 2: cases it can only report (expected QA `review`)."""
    doc = pymupdf.open(); pg = doc.new_page(width=A4[0], height=A4[1])
    truth = {"lines": {}, "links": {}, "untouched": []}

    def underline(name, x0, x1, y, width=0.8, color=(0, 0, 0)):
        pg.draw_line((x0, y), (x1, y), color=color, width=width)
        truth["lines"][name] = dict(x0=x0, x1=x1, y=y, t=width, color=list(color))

    # 1 shorter translation, black 1 pt underline
    _text(pg, (60, 80), "FIELD NOTES SUMMARY", 14, "hebo")
    underline("heading", 60, 60 + _w("FIELD NOTES SUMMARY", "hebo", 14), 83, 1.0)
    # 2 longer translation on one line (free space to the right)
    _text(pg, (60, 130), "Map", 11)
    underline("map", 60, 60 + _w("Map"), 132.2, 0.7)
    # 3 two underlined lines whose translation wraps differently
    l1, l2 = "Volunteers should read the safety rules before the", "first guided walk along the coast."
    _text(pg, (60, 185), l1, 11, color=(0, 0, 0.7)); _text(pg, (60, 198.2), l2, 11, color=(0, 0, 0.7))
    underline("wrap1", 60, 60 + _w(l1), 187.2, 0.8, (0, 0, 0.7))
    underline("wrap2", 60, 60 + _w(l2), 200.4, 0.8, (0, 0, 0.7))
    # 4 underline drawn as a thin filled rectangle (common in office exports), dark red
    _text(pg, (60, 260), "Night sky checklist", 12, "hebo", color=(0.55, 0, 0))
    wn = _w("Night sky checklist", "hebo", 12)
    pg.draw_rect(pymupdf.Rect(60, 262, 60 + wn, 263.4), color=None, fill=(0.55, 0, 0))
    truth["lines"]["fillrect"] = dict(x0=60, x1=60 + wn, y=262.7, t=1.4, color=[0.55, 0, 0])
    # 5 whole phrase is a link, underlined
    _text(pg, (60, 315), "Read the field guide", 11, color=(0, 0, 0.8))
    wg = _w("Read the field guide")
    underline("guide", 60, 60 + wg, 317.2, 0.6, (0, 0, 0.8))
    pg.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(60, 305, 60 + wg, 319),
                    "uri": "https://example.org/field-guide"})
    truth["links"]["guide"] = "https://example.org/field-guide"
    # 6 only the e-mail inside a sentence is underlined and linked
    _text(pg, (60, 370), "Contact: info@example.org", 11)
    xe = 60 + _w("Contact: "); we = _w("info@example.org")
    underline("email", xe, xe + we, 372.2, 0.6, (0, 0, 0.8))
    pg.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(xe, 360, xe + we, 374),
                    "uri": "mailto:info@example.org"})
    truth["links"]["email"] = "mailto:info@example.org"
    # 7 strike-through
    _text(pg, (60, 425), "Old meeting point", 11)
    underline("strike", 60, 60 + _w("Old meeting point"), 421.5, 0.7)
    # 8 table grid drawn cell by cell: the bottom border of the first cell hugs "Heron count"
    #   (within the underline tolerance), so only the "joined to a vertical line" rule keeps it
    gx0, gx1, gx2 = 60, 60 + _w("Heron count", "helv", 9) + 4, 220
    _text(pg, (gx0 + 2, 494), "Heron count", 9); _text(pg, (gx1 + 24, 494), "14", 9)
    _text(pg, (gx0 + 2, 516), "Egret count", 9); _text(pg, (gx1 + 24, 516), "9", 9)
    for yy in (481, 499, 521):
        for xa, xb in ((gx0, gx1), (gx1, gx2)):
            pg.draw_line((xa, yy), (xb, yy), color=(0, 0, 0), width=0.5)
            truth["untouched"].append([xa, yy, xb, yy])
    for xx in (gx0, gx1, gx2):
        pg.draw_line((xx, 481), (xx, 521), color=(0, 0, 0), width=0.5)
        truth["untouched"].append([xx, 481, xx, 521])
    # 9 full-width separator under a short heading-like line
    pg.draw_line((60, 560), (535, 560), color=(0.5, 0.5, 0.5), width=0.8)
    truth["untouched"].append([60, 560, 535, 560])

    # ---- page 2: cases that are reported, not changed
    p2 = doc.new_page(width=A4[0], height=A4[1])
    _text(p2, (60, 80), "Bring warm clothes and a torch.", 11)
    xw = 60 + _w("Bring "); ww = _w("warm clothes")
    p2.draw_line((xw, 82.2), (xw + ww, 82.2), color=(0, 0, 0), width=0.7)
    _text(p2, (60, 120), "See the map for opening hours.", 11)
    xm = 60 + _w("See the "); wm = _w("map")
    p2.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(xm, 110, xm + wm, 124),
                    "uri": "https://example.org/map"})
    _text(p2, (60, 160), "Meet at the north gate.", 11)
    p2.add_underline_annot(pymupdf.Rect(60, 150, 60 + _w("Meet at the north gate."), 163))
    truth["links"]["map"] = "https://example.org/map"
    doc.save(out / "decorations.pdf")
    return truth


def decor_scan(out: Path, dpi=200):
    """A scanned line with an underline in the pixels: can only be reported."""
    src = pymupdf.open(); sp = src.new_page(width=A4[0], height=300)
    _text(sp, (60, 100), "Scanned notice: quiet zone", 14, "helv")
    sp.draw_line((60, 104), (60 + _w("Scanned notice: quiet zone", "helv", 14), 104), color=(0, 0, 0), width=1.2)
    _rasterize(sp, out / "decor_scan.pdf", dpi, seed=11)
    return {"raster": True}


FIXTURES = [toc, financial, two_column_cropbox, rotated, vector_glyphs, scanned, image_text, damaged,
            encrypted, table, unicode_name, decorations, decor_scan]


def load_truth(path) -> dict:
    """truth.json and manual_tm.json are UTF-8 (they contain 中文, ¥, –, é). Never rely on the
    platform default encoding (cp1252/cp936 on many Windows systems)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(outdir: str) -> None:
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    truth = {}
    for f in FIXTURES:
        truth[f.__name__] = f(out)
    (out / "truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "manual_tm.json").write_text(json.dumps(MANUAL_TM, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(FIXTURES)} fixtures to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/out")
