"""Underlines, strike-through lines and links attached to translated text (decor.py).

Fixture: tests/fixtures/make_fixtures.py::decorations (page 1: cases that are moved,
page 2: cases that are only reported) and ::decor_scan. Assertions are made on the saved
output (drawings, links, words) and on rasterised pixels, not only on QA flags.
"""
from __future__ import annotations

import json
import shutil

import numpy as np
import pymupdf
import pytest

from conftest import needs_ocr


def _segs(page):
    out = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                out.append(dict(x0=min(it[1].x, it[2].x), x1=max(it[1].x, it[2].x), y=(it[1].y + it[2].y) / 2,
                                t=d.get("width"), color=d.get("color"), fill=None, y1=max(it[1].y, it[2].y),
                                y0=min(it[1].y, it[2].y)))
            elif it[0] == "re":
                r = it[1]
                out.append(dict(x0=r.x0, x1=r.x1, y=(r.y0 + r.y1) / 2, t=r.height, color=None, fill=d.get("fill"),
                                y0=r.y0, y1=r.y1))
    return out


def _near(segs, y, tol=1.5, horizontal=True):
    return [s for s in segs if abs(s["y"] - y) < tol and (not horizontal or abs(s["y1"] - s["y0"]) < 2)]


def _word(page, needle):
    ws = [w for w in page.get_text("words") if needle in w[4]]
    assert ws, needle
    return pymupdf.Rect(ws[0][:4])


@pytest.fixture(scope="module")
def deco(corpus, fonts_ready, tmp_path_factory):
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    d = tmp_path_factory.mktemp("deco")
    src = d / "src"; src.mkdir()
    shutil.copy(corpus["src"] / "decorations.pdf", src)
    ws = Workspace(src, d / "state")
    plan_file(ws, "decorations.pdf", ocr=False)
    m = ManualBackend(corpus["manual_tm"])
    assert translate(ws, ["decorations.pdf"], m, max_chars=99999)["outcome"] == "complete"
    qa = render_file(ws, "decorations.pdf", m.namespace, ocr_qa=False)
    return {"ws": ws, "qa": qa, "src": src / "decorations.pdf", "out": ws.out_path("decorations.pdf"),
            "truth": corpus["truth"]["decorations"], "ns": m.namespace, "manual": m}


def test_statuses_page1_pass_page2_review(deco):
    p1, p2 = deco["qa"]["pages"]
    assert p1["status"] == "pass", p1["issues"]
    assert p2["status"] == "review"
    kinds = {i["issue"] for i in p2["issues"]}
    assert {"decoration_not_adjusted", "link_area_not_mapped", "markup_annotation_on_translated_text"} <= kinds
    assert deco["qa"]["status"] == "review"                 # never pass while page 2 needs a look


def test_short_translation_underline_shortened(deco):
    t = deco["truth"]["lines"]["heading"]
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]; segs = _near(_segs(pg), t["y"])
        words = _word(pg, "野外记录摘要")
    assert len(segs) == 1, segs
    s = segs[0]
    assert abs(s["x0"] - words.x0) < 1.0 and abs(s["x1"] - words.x1) < 1.0     # follows the Chinese text
    assert s["x1"] < t["x1"] - 50                                                 # old length is gone
    assert abs(s["t"] - t["t"]) < 0.05 and np.allclose(s["color"], t["color"], atol=0.01)


def test_longer_translation_underline_lengthened(deco):
    t = deco["truth"]["lines"]["map"]
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]; s = _near(_segs(pg), t["y"])
        w = _word(pg, "步道地图")
    assert len(s) == 1 and s[0]["x1"] > t["x1"] + 10 and abs(s[0]["x1"] - w.x1) < 1.0


def test_wrapped_translation_gets_one_underline_per_line(deco):
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]
        blue = [s for s in _segs(pg) if s["color"] and np.allclose(s["color"], (0, 0, 0.7), atol=0.01)]
        lines = sorted({round(w[3]) for w in pg.get_text("words") if 175 < w[3] < 230 and w[1] > 170})
    assert len(lines) >= 3 and len(blue) == len(lines), (lines, blue)    # 2 English lines -> 3 Chinese lines
    for s in blue:
        assert abs(s["t"] - 0.8) < 0.05


def test_filled_rect_underline_keeps_thickness_and_colour(deco):
    t = deco["truth"]["lines"]["fillrect"]
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]
        rs = [s for s in _segs(pg) if s["fill"] is not None and abs(s["y"] - t["y"]) < 1]
        w = _word(pg, "夜空观测清单")
    assert len(rs) == 1
    assert abs(rs[0]["t"] - t["t"]) < 0.05 and np.allclose(rs[0]["fill"], t["color"], atol=0.01)
    assert abs(rs[0]["x1"] - w.x1) < 1.0


def test_strike_through_follows_text(deco):
    t = deco["truth"]["lines"]["strike"]
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]; s = _near(_segs(pg), t["y"]); w = _word(pg, "旧集合点")
    assert len(s) == 1 and abs(s[0]["x1"] - w.x1) < 1.0 and w.y0 < s[0]["y"] < w.y1


def test_partial_underline_moves_with_verbatim_email(deco):
    t = deco["truth"]["lines"]["email"]
    with pymupdf.open(deco["out"]) as o:
        pg = o[0]; s = _near(_segs(pg), t["y"]); e = pg.search_for("info@example.org")[0]
    assert len(s) == 1 and abs(s[0]["x0"] - e.x0) < 1.0 and abs(s[0]["x1"] - e.x1) < 1.0


def test_links_keep_targets_and_cover_the_new_text(deco):
    with pymupdf.open(deco["src"]) as s_, pymupdf.open(deco["out"]) as o_:
        for i in range(2):
            a = sorted(l.get("uri") for l in s_[i].get_links())
            b = sorted(l.get("uri") for l in o_[i].get_links())
            assert a == b and a, (i, a, b)
        links = {l["uri"]: pymupdf.Rect(l["from"]) for l in o_[0].get_links()}
        g = _word(o_[0], "阅读野外指南")
        lr = links["https://example.org/field-guide"]
        assert (lr & g).get_area() > 0.9 * g.get_area() and lr.x1 < g.x1 + 2
        e = o_[0].search_for("info@example.org")[0]
        er = links["mailto:info@example.org"]
        assert (er & e).get_area() > 0.9 * e.get_area() and er.x0 > e.x0 - 2


def test_table_grid_and_separator_untouched(deco):
    with pymupdf.open(deco["out"]) as o:
        segs = _segs(o[0])
    for x0, y0, x1, y1 in deco["truth"]["untouched"]:
        assert any(abs(s["x0"] - min(x0, x1)) < 0.1 and abs(s["x1"] - max(x0, x1)) < 0.1
                   and abs(s["y0"] - min(y0, y1)) < 0.1 and abs(s["y1"] - max(y0, y1)) < 0.1 for s in segs), (x0, y0, x1, y1)


def test_rendered_pixels_have_no_old_underline_tail(deco):
    """Rasterise: below the Chinese heading, nothing dark remains past the end of the text."""
    t = deco["truth"]["lines"]["heading"]
    with pymupdf.open(deco["src"]) as s_, pymupdf.open(deco["out"]) as o_:
        w = _word(o_[0], "野外记录摘要")
        clip = pymupdf.Rect(w.x1 + 3, t["y"] - 1.5, t["x1"], t["y"] + 1.5)
        def dark(p):
            pm = p.get_pixmap(dpi=144, clip=clip, colorspace=pymupdf.csGRAY)
            return (np.frombuffer(pm.samples, np.uint8) < 128).mean()
        assert dark(s_[0]) > 0.2          # the source has the long underline there
        assert dark(o_[0]) == 0.0         # the output does not


def test_unmappable_partial_underline_is_kept_and_reported(deco):
    with pymupdf.open(deco["src"]) as s_, pymupdf.open(deco["out"]) as o_:
        a = [s for s in _segs(s_[1]) if abs(s["y"] - 82.2) < 0.5]
        b = [s for s in _segs(o_[1]) if abs(s["y"] - 82.2) < 0.5]
    assert len(a) == len(b) == 1 and abs(a[0]["x0"] - b[0]["x0"]) < 0.1 and abs(a[0]["x1"] - b[0]["x1"]) < 0.1
    iss = [i for i in deco["qa"]["pages"][1]["issues"] if i["issue"] == "decoration_not_adjusted"]
    assert iss and "verbatim" in iss[0]["why"]


def test_removal_failure_is_review_not_silent_pass(deco, monkeypatch):
    from patt_pdf import decor
    from patt_pdf.jobs import render_file
    monkeypatch.setattr(decor, "remove", lambda pg, decos: [])        # nothing could be removed
    q = render_file(deco["ws"], "decorations.pdf", deco["ns"], ocr_qa=False)
    p1 = q["pages"][0]
    assert p1["status"] == "review"
    assert any(i["issue"] == "decoration_not_adjusted" and "removed" in i["why"] for i in p1["issues"])


def test_lost_links_are_a_fail(deco, monkeypatch):
    """Independent post-save check: if links are not restored, QA must fail."""
    from patt_pdf import decor
    from patt_pdf.jobs import render_file
    monkeypatch.setattr(decor, "restore_links", lambda pg, before, units: ([], 0))
    q = render_file(deco["ws"], "decorations.pdf", deco["ns"], ocr_qa=False)
    assert q["status"] == "fail"
    assert any(i["issue"] == "link_lost" for i in q["pages"][0]["issues"])


def test_without_decor_module_the_v02_defect_reappears(deco, monkeypatch):
    """Mutation check: with decoration handling disabled the heading keeps its English-length line."""
    from patt_pdf import decor
    from patt_pdf.jobs import render_file
    monkeypatch.setattr(decor, "find", lambda pg, units: [])
    render_file(deco["ws"], "decorations.pdf", deco["ns"], ocr_qa=False)
    t = deco["truth"]["lines"]["heading"]
    with pymupdf.open(deco["out"]) as o:
        s = _near(_segs(o[0]), t["y"])
    assert s and abs(s[0]["x1"] - t["x1"]) < 0.5


def test_text_crossing_a_table_border_fails(tmp_path, fonts_ready):
    """No table model: a translation that runs across a vertical border must not pass."""
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    src = tmp_path / "src"; src.mkdir()
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pg.insert_text((64, 100), "Heron count", fontsize=9)
    pg.insert_text((150, 100), "14", fontsize=9)
    for x in (60, 120, 200):
        pg.draw_line((x, 88), (x, 106), color=(0, 0, 0), width=0.5)
    for y in (88, 106):
        pg.draw_line((60, y), (200, y), color=(0, 0, 0), width=0.5)
    doc.save(src / "cell.pdf")
    tm = tmp_path / "tm.json"
    tm.write_text(json.dumps({"Heron count": "本季在北堤观察到的苍鹭总数"}, ensure_ascii=False), encoding="utf-8")
    ws = Workspace(src, tmp_path / "st"); plan_file(ws, "cell.pdf", ocr=False)
    m = ManualBackend(tm); translate(ws, ["cell.pdf"], m, max_chars=999)
    q = render_file(ws, "cell.pdf", m.namespace, ocr_qa=False)
    assert q["status"] == "fail"
    assert any(i["issue"] == "text_crosses_rule" for i in q["pages"][0]["issues"])


def test_find_ignores_borders_and_separators(corpus):
    """Unit check of the detector on the source page (before any editing)."""
    from patt_pdf import decor
    from patt_pdf.analyze import plan_page
    with pymupdf.open(corpus["src"] / "decorations.pdf") as d:
        plan = plan_page(d[0], 0, False)
        for u in plan.units:
            u.tgt = "x"
        found = decor.find(d[0], plan.units)
    ys = sorted(round(f["y"], 1) for f in found)
    assert 495.0 not in ys and 499.0 not in ys and 560.0 not in ys and 481.0 not in ys
    assert len(found) == 8                     # heading, map, 2 wrap lines, fill rect, guide, email, strike


@needs_ocr
def test_underline_in_scanned_image_is_reported(corpus, fonts_ready, tmp_path):
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    src = tmp_path / "src"; src.mkdir(); shutil.copy(corpus["src"] / "decor_scan.pdf", src)
    ws = Workspace(src, tmp_path / "st"); plan_file(ws, "decor_scan.pdf", ocr=True)
    m = ManualBackend(corpus["manual_tm"]); translate(ws, ["decor_scan.pdf"], m, max_chars=999)
    q = render_file(ws, "decor_scan.pdf", m.namespace)
    assert q["status"] != "pass"
    assert any(i["issue"] == "possible_underline_in_image" for i in q["pages"][0]["issues"])


def test_closed_path_underline_is_one_line(tmp_path, fonts_ready):
    """`m l h` (line drawn there and back) is treated as one line, not 'part of a larger drawing'."""
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    src = tmp_path / "src"; src.mkdir()
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pg.insert_text((60, 80), "SUMMARY OF REASONS", fontsize=14, fontname="hebo")
    w = pymupdf.get_text_length("SUMMARY OF REASONS", "hebo", 14)
    sh = pg.new_shape(); sh.draw_line((60, 84), (60 + w, 84)); sh.finish(color=(0, 0, 0), width=1.5, lineCap=1)
    sh.commit(); doc.save(src / "closed.pdf")
    tm = tmp_path / "tm.json"; tm.write_text(json.dumps({"SUMMARY OF REASONS": "理由摘要"}, ensure_ascii=False),
                                             encoding="utf-8")
    ws = Workspace(src, tmp_path / "st"); plan_file(ws, "closed.pdf", ocr=False)
    m = ManualBackend(tm); translate(ws, ["closed.pdf"], m, max_chars=99)
    q = render_file(ws, "closed.pdf", m.namespace, ocr_qa=False)
    assert q["status"] == "pass", q["pages"][0]["issues"]
    with pymupdf.open(ws.out_path("closed.pdf")) as o:
        segs = _near(_segs(o[0]), 84)
        word = _word(o[0], "理由摘要")
    assert segs and max(s["x1"] for s in segs) < word.x1 + 1.0 and all(abs(s["t"] - 1.5) < 0.05 for s in segs)


def test_dashed_segments_with_gaps_are_not_merged():
    from patt_pdf.decor import _one_horizontal_line
    P = pymupdf.Point
    assert _one_horizontal_line([("l", P(0, 5), P(10, 5)), ("l", P(10, 5), P(0, 5))])
    assert not _one_horizontal_line([("l", P(0, 5), P(4, 5)), ("l", P(6, 5), P(10, 5))])
    assert not _one_horizontal_line([("l", P(0, 5), P(10, 5)), ("l", P(10, 5), P(10, 9))])
