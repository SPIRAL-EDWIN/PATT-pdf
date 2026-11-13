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
