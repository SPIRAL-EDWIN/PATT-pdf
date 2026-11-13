"""Slanted text is translated at its angle; text set along a curve stays as it is.

Real case: on a map, fault names follow curved lines. They arrive as dozens of short runs at
different angles; translated run by run they overlapped. Straight slanted labels (captions on
arrows, axis titles) were and are translated. Synthetic pages only.
"""
from __future__ import annotations

import json
import math

import pymupdf

from patt_pdf.jobs import Workspace, load_plan, plan_file, render_file, translate


def _slanted(pg, origin, text, angle, size=10):
    tw = pymupdf.TextWriter(pg.rect)
    tw.append(origin, text, font=pymupdf.Font("helv"), fontsize=size)
    tw.write_text(pg, morph=(pymupdf.Point(origin), pymupdf.Matrix(angle)))


def _arrow_page(path):
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.draw_rect(pymupdf.Rect(40, 200, 140, 250)); pg.draw_rect(pymupdf.Rect(280, 60, 380, 110))
    pg.insert_text((55, 230), "Raw samples", fontsize=11, fontname="helv")
    pg.insert_text((295, 90), "Clean dataset", fontsize=11, fontname="helv")
    pg.draw_line((140, 200), (280, 110))
    _slanted(pg, (170, 172), "filtered and merged", math.degrees(math.atan2(90, 140)))
    _slanted(pg, (60, 150), "rejected rows", -35)
    d.save(path); d.close()


def _curved_page(path, text="SAN ANDREAS FAULT ZONE", spaced=False):
    """Words placed along an arc, each at the tangent angle (as map labels are stored)."""
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.insert_text((40, 40), "Map of active faults", fontsize=12, fontname="helv")
    f = pymupdf.Font("helv"); x, y, ang = 60.0, 230.0, 20.0
    pieces = [" ".join(w) for w in text.split()] if spaced else text.split()
    for w in pieces:
        _slanted(pg, (x, y), w, ang, size=9)
        adv = f.text_length(w + " ", fontsize=9)
        x += adv * math.cos(math.radians(ang)); y -= adv * math.sin(math.radians(ang))
        ang += 9.0
    d.save(path); d.close()


def _run(tmp_path, name, tm):
    from patt_pdf.backends import ManualBackend
    ws = Workspace(tmp_path / "in", tmp_path / "state")
    plan_file(ws, name, ocr=False)
    f = tmp_path / "tm.json"; f.write_text(json.dumps(tm, ensure_ascii=False), encoding="utf-8")
    m = ManualBackend(f)
    s = translate(ws, [name], m, max_chars=9999)
    return ws, render_file(ws, name, m.namespace, ocr_qa=False), s


def _line_angles(path):
    out = {}
    with pymupdf.open(path) as o:
        for b in o[0].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = "".join(s["text"] for s in l["spans"]).strip()
                out[t] = math.degrees(math.atan2(-l["dir"][1], l["dir"][0]))
    return out


def test_slanted_captions_are_translated_at_their_angle(tmp_path, fonts_ready):
    (tmp_path / "in").mkdir(); _arrow_page(tmp_path / "in" / "arrow.pdf")
    ws, qa, _ = _run(tmp_path, "arrow.pdf", {"Raw samples": "原始样本", "Clean dataset": "清洗后的数据集",
                                              "filtered and merged": "过滤并合并", "rejected rows": "被剔除的行"})
    assert qa["status"] == "pass", qa["pages"][0]["issues"]
    ang = _line_angles(ws.out_path("arrow.pdf"))
    assert abs(ang["过滤并合并"] - math.degrees(math.atan2(90, 140))) < 1.0
    assert abs(ang["被剔除的行"] - (-35)) < 1.0
    assert abs(ang["原始样本"]) < 0.1
    with pymupdf.open(ws.out_path("arrow.pdf")) as o:
        assert "filtered" not in o[0].get_text() and "rejected" not in o[0].get_text()


def test_slanted_translation_that_does_not_fit_is_reported(tmp_path, fonts_ready):
    (tmp_path / "in").mkdir(); _arrow_page(tmp_path / "in" / "arrow.pdf")
    long = "经过多轮过滤、去重、合并与人工复核之后得到的全部记录"
    ws, qa, _ = _run(tmp_path, "arrow.pdf", {"Raw samples": "原始样本", "Clean dataset": "清洗后的数据集",
                                              "filtered and merged": long, "rejected rows": "被剔除的行"})
    kinds = {i["issue"] for i in qa["pages"][0]["issues"]}
    assert kinds & {"shrunk", "overflow"} and qa["status"] in ("review", "fail")


def test_text_along_a_curve_is_left_in_place_and_reported(tmp_path, fonts_ready):
    (tmp_path / "in").mkdir(); _curved_page(tmp_path / "in" / "map.pdf")
    ws, qa, s = _run(tmp_path, "map.pdf", {"Map of active faults": "活动断层图", "SAN": "圣", "ANDREAS": "安德烈亚斯",
                                            "FAULT": "断层", "ZONE": "带"})
    assert s["sent_chars"] == len("Map of active faults")                 # the curved words were not sent
    with pymupdf.open(ws.out_path("map.pdf")) as o:
        text = o[0].get_text()
    for w in ("SAN", "ANDREAS", "FAULT", "ZONE"):
        assert w in text
    assert "活动断层图" in text and "断层\n" not in text.replace("活动断层图", "")
    issues = qa["pages"][0]["issues"]
    cur = [i for i in issues if i["issue"] == "curved_text_left_english"]
    assert len(cur) == 1 and cur[0]["count"] == 4 and "ANDREAS" in cur[0]["src"]
    assert qa["status"] == "review"                                       # visible, not a failure
    plans = load_plan(ws, "map.pdf")
    assert not [u for u in plans[0].units if u.angle]


def test_letter_spaced_curved_text_is_recognised(tmp_path, fonts_ready):
    (tmp_path / "in").mkdir(); _curved_page(tmp_path / "in" / "sp.pdf", text="PACIFIC OCEAN", spaced=True)
    ws, qa, _ = _run(tmp_path, "sp.pdf", {"Map of active faults": "活动断层图"})
    cur = [i for i in qa["pages"][0]["issues"] if i["issue"] == "curved_text_left_english"]
    assert cur and cur[0]["count"] == 2


def test_parallel_slanted_labels_are_not_mistaken_for_a_curve(tmp_path, fonts_ready):
    """Several captions at the same angle (a diagram with parallel arrows) are all translated."""
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    for i, t in enumerate(["first stage", "second stage", "third stage"]):
        _slanted(pg, (60 + 110 * i, 200), t, 30)
    d.save(tmp_path / "in" / "par.pdf"); d.close()
    ws, qa, _ = _run(tmp_path, "par.pdf", {"first stage": "第一阶段", "second stage": "第二阶段", "third stage": "第三阶段"})
    assert qa["status"] == "pass", qa["pages"][0]["issues"]
    ang = _line_angles(ws.out_path("par.pdf"))
    assert all(abs(ang[t] - 30) < 1.0 for t in ("第一阶段", "第二阶段", "第三阶段"))


def test_vertical_side_labels_are_still_translated(tmp_path, fonts_ready):
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.insert_text((80, 60), "Yearly totals", fontsize=12, fontname="helv")
    _slanted(pg, (40, 220), "Training loss", 90)
    d.save(tmp_path / "in" / "v.pdf"); d.close()
    ws, qa, _ = _run(tmp_path, "v.pdf", {"Yearly totals": "年度合计", "Training loss": "训练损失"})
    assert abs(_line_angles(ws.out_path("v.pdf"))["训练损失"] - 90) < 1.0 and qa["status"] == "pass"


def test_piece_of_a_curved_label_that_is_exactly_vertical_stays_too(tmp_path, fonts_ready):
    """macOS check C23: "HUNTING CREEK" follows a curve that passes through the vertical. Its
    piece "EE" is a run at 90 degrees; alone it looked like a side label, was translated, and
    the map showed "HUNTING CR" followed by Chinese."""
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.insert_text((40, 40), "Map of active faults", fontsize=12, fontname="helv")
    f = pymupdf.Font("helv"); x, y = 120.0, 80.0
    for piece, ang in (("HUNTIN", -56.0), ("GCR", -72.0), ("EE", -90.0), ("K", -104.0)):
        _slanted(pg, (x, y), piece, ang, size=9)
        adv = f.text_length(piece, fontsize=9) + 1.0
        x += adv * math.cos(math.radians(ang)); y -= adv * math.sin(math.radians(ang))
    _slanted(pg, (330, 250), "Elevation", 90, size=9)          # a real vertical axis label, far away
    d.save(tmp_path / "in" / "creek.pdf"); d.close()
    ws, qa, s = _run(tmp_path, "creek.pdf", {"Map of active faults": "活动断层图", "Elevation": "海拔", "EE": "译译", "K": "译"})
    assert s["sent_chars"] == len("Map of active faults") + len("Elevation")
    cur = [i for i in qa["pages"][0]["issues"] if i["issue"] == "curved_text_left_english"]
    assert cur and cur[0]["count"] == 3, cur                      # "K" alone is a kept single letter anyway
    ang = _line_angles(ws.out_path("creek.pdf"))
    assert "EE" in ang and "译译" not in ang                       # the vertical piece is untouched
    assert abs(ang["海拔"] - 90) < 1.0                              # the axis label is still translated


def test_a_label_is_not_left_half_translated(tmp_path, fonts_ready):
    """Seen on the same map: "HAYWARD" was translated while "FAULT", the next word of the same
    label, was part of a curve and stayed English. A word that continues a kept run at the same
    angle stays as well."""
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.insert_text((40, 40), "Map of active faults", fontsize=12, fontname="helv")
    f = pymupdf.Font("helv")
    def along(x, y, ang, text, gap=0.0):
        _slanted(pg, (x, y), text, ang, size=9)
        adv = f.text_length(text, fontsize=9) + gap
        return x + adv * math.cos(math.radians(ang)), y - adv * math.sin(math.radians(ang))
    x, y = along(80, 90, -55, "HAYWARD", gap=30)            # a wide gap: a symbol sits between the words
    x, y = along(x, y, -55, "FAULT", gap=2)
    x, y = along(x, y, -63, "ZONE", gap=2)                   # the label bends here
    d.save(tmp_path / "in" / "hay.pdf"); d.close()
    ws, qa, s = _run(tmp_path, "hay.pdf", {"Map of active faults": "活动断层图", "HAYWARD": "海沃德", "FAULT": "断层", "ZONE": "带"})
    assert s["sent_chars"] == len("Map of active faults")
    with pymupdf.open(ws.out_path("hay.pdf")) as o:
        text = o[0].get_text()
    assert all(w in text for w in ("HAYWARD", "FAULT", "ZONE")) and "海沃德" not in text


def test_translating_an_upright_label_does_not_erase_a_curved_letter_that_crosses_it(tmp_path, fonts_ready):
    """Seen on the map: the city label "Francisco" was translated and the "r" of the curved
    "San Francisco Bay", which runs across it, disappeared with it."""
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=300)
    pg.insert_text((100, 150), "Oakland", fontsize=11, fontname="helv")
    f = pymupdf.Font("helv"); x, y, ang = 104.0, 128.0, -52.0           # a curve that crosses the label
    for piece in ("Half", "Moon", "Bay"):
        _slanted(pg, (x, y), piece, ang, size=9)
        adv = f.text_length(piece + " ", fontsize=9)
        x += adv * math.cos(math.radians(ang)); y -= adv * math.sin(math.radians(ang)); ang -= 8
    d.save(tmp_path / "in" / "cross.pdf"); d.close()

    def slanted_letters(path):
        out = []
        with pymupdf.open(path) as doc:
            for b in doc[0].get_text("rawdict")["blocks"]:
                for l in b.get("lines", []):
                    if abs(l["dir"][1]) > 0.05:
                        out += [(c["c"], round(c["origin"][0]), round(c["origin"][1])) for sp in l["spans"] for c in sp["chars"] if c["c"].strip()]
        return sorted(out)
    before = slanted_letters(tmp_path / "in" / "cross.pdf")
    with pymupdf.open(tmp_path / "in" / "cross.pdf") as doc:
        label = doc[0].search_for("Oakland")[0]
        crossing = [c for b in doc[0].get_text("rawdict")["blocks"] for l in b.get("lines", []) if abs(l["dir"][1]) > 0.05
                    for sp in l["spans"] for c in sp["chars"] if c["c"].strip() and pymupdf.Rect(c["bbox"]).intersects(label)]
    assert crossing, "fixture: the curved text must cross the upright label"
    ws, qa, _ = _run(tmp_path, "cross.pdf", {"Oakland": "奥克兰"})
    assert slanted_letters(ws.out_path("cross.pdf")) == before
    with pymupdf.open(ws.out_path("cross.pdf")) as o:
        assert "奥克兰" in o[0].get_text() and "Oakland" not in o[0].get_text()
