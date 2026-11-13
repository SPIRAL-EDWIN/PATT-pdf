"""Table rows are cut into cells (tables.py), so a header is not translated as one sentence.

Real case: the header "params dimension n heads n layers learning rate batch size n tokens"
of a three-line table had gaps of 1.3-2.6 × font size between its cells; below the general
tab-stop threshold (1.6 ×) cells were merged and the translation lost its columns.
Synthetic pages only.
"""
from __future__ import annotations

import json

import pymupdf

from patt_pdf.extract_text import plan_text_page
from patt_pdf.tables import line_cuts

HEAD = ["params", "dimension", "n heads", "n layers", "learning rate", "batch size", "n tokens"]
BODY = [["6.7B", "4096", "32", "32", "3.0e-4", "4M", "1.0T"],
        ["13.0B", "5120", "40", "40", "3.0e-4", "4M", "1.0T"],
        ["32.5B", "6656", "52", "60", "1.5e-4", "4M", "1.4T"]]
SIZE = 10


def _booktabs(per_cell_lines: bool, with_rules: bool = False, gap=1.3):
    """Header cells `gap` × font size apart (centred over the body columns)."""
    d = pymupdf.open(); pg = d.new_page(width=595, height=400)
    f = pymupdf.Font("helv")
    x, edges = 70.0, []
    for h in HEAD:
        w = f.text_length(h, fontsize=SIZE); edges.append((x, x + w)); x += w + gap * SIZE
    tw = pymupdf.TextWriter(pg.rect)
    if per_cell_lines:
        for (x0, _), h in zip(edges, HEAD):
            pg.insert_text((x0, 100), h, fontsize=SIZE, fontname="helv")
    else:                                             # one text line, real spaces between the cells
        for (x0, _), h in zip(edges, HEAD):
            tw.append((x0, 100), h + " ", font=f, fontsize=SIZE)
    for r, row in enumerate(BODY):
        for (x0, x1), v in zip(edges, row):
            w = f.text_length(v, fontsize=SIZE)
            if per_cell_lines:
                pg.insert_text(((x0 + x1) / 2 - w / 2, 118 + 14 * r), v, fontsize=SIZE, fontname="helv")
            else:
                tw.append(((x0 + x1) / 2 - w / 2, 118 + 14 * r), v + " ", font=f, fontsize=SIZE)
    tw.write_text(pg)
    pg.draw_line((66, 88), (x, 88)); pg.draw_line((66, 105), (x, 105)); pg.draw_line((66, 160), (x, 160))
    if with_rules:
        for (a, _), (_, b) in zip(edges[1:], edges):
            pg.draw_line(((a + b) / 2, 88), ((a + b) / 2, 160))
    pg.insert_text((70, 190), "Table 2: Model sizes and optimisation settings used in this work.", fontsize=SIZE, fontname="helv")
    return d


def _units(d, pno=0):
    return [u.src for u in plan_text_page(d[pno], pno).units]


def test_header_of_a_table_without_vertical_rules_is_cut_into_cells():
    for per_cell in (False, True):                    # one line for the row, or one line per cell
        us = _units(_booktabs(per_cell))
        for h in HEAD:
            assert h in us, (per_cell, us)
        assert not any("params dimension" in u for u in us)
        assert "Table 2: Model sizes and optimisation settings used in this work." in us   # the caption stays whole


def test_cells_separated_by_vertical_rules_are_cut_even_without_body_rows():
    d = pymupdf.open(); pg = d.new_page(width=595, height=300)
    f = pymupdf.Font("helv"); tw = pymupdf.TextWriter(pg.rect)
    x = 70.0; xs = []
    for h in ["Name of entity", "Business name", "Tax class"]:
        tw.append((x, 100), h + " ", font=f, fontsize=SIZE); xs.append(x)
        x += f.text_length(h, fontsize=SIZE) + 0.9 * SIZE          # tight: a rule sits in each gap
    tw.write_text(pg)
    pg.draw_rect(pymupdf.Rect(64, 86, x, 108))
    for a in xs[1:]:
        pg.draw_line((a - 0.45 * SIZE, 86), (a - 0.45 * SIZE, 108))
    assert sorted(_units(d)) == sorted(["Name of entity", "Business name", "Tax class"])


def test_translated_header_stays_in_its_columns(tmp_path, fonts_ready):
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    (tmp_path / "in").mkdir()
    _booktabs(False).save(tmp_path / "in" / "t.pdf")
    zh = dict(zip(HEAD, ["参数量", "维度", "头数", "层数", "学习率", "批量大小", "令牌数"]))
    zh["Table 2: Model sizes and optimisation settings used in this work."] = "表2：本文使用的模型规模与优化设置。"
    f = tmp_path / "tm.json"; f.write_text(json.dumps(zh, ensure_ascii=False), encoding="utf-8")
    ws = Workspace(tmp_path / "in", tmp_path / "state"); plan_file(ws, "t.pdf", ocr=False)
    m = ManualBackend(f); translate(ws, ["t.pdf"], m, max_chars=9999)
    qa = render_file(ws, "t.pdf", m.namespace, ocr_qa=False)
    assert qa["status"] == "pass", qa["pages"][0]["issues"]
    with pymupdf.open(tmp_path / "in" / "t.pdf") as s, pymupdf.open(ws.out_path("t.pdf")) as o:
        src = {w[4]: w for w in s[0].get_text("words")}
        out = {w[4]: w for w in o[0].get_text("words")}
        # every translated header cell starts where its English cell started
        firsts = dict(zip(["参数量", "维度", "头数", "层数", "学习率", "批量大小", "令牌数"],
                          ["params", "dimension", "n", "n", "learning", "batch", "n"]))
        en_x = sorted(w[0] for w in s[0].get_text("words") if abs(w[3] - src["params"][3]) < 1 and w[4] in set(firsts.values()))
        zh_x = sorted(out[k][0] for k in firsts)
        en_starts = sorted({round(x) for x in en_x})
        assert len(zh_x) == 7 and all(any(abs(x - e) < 1.5 for e in en_starts) for x in zh_x), (zh_x, en_starts)
        for v in ("13.0B", "5120", "3.0e-4", "1.4T"):                 # figures untouched
            assert abs(out[v][0] - src[v][0]) < 0.1


def test_body_text_and_two_columns_are_not_cut():
    d = pymupdf.open(); pg = d.new_page(width=595, height=500)
    left = ["Large models trained on many texts can follow", "new instructions after only a few examples and",
            "these properties appeared when models grew."]
    right = ["The focus of this work is to train a series of", "language models that achieve the best possible",
             "performance at various inference budgets."]
    for col, x in ((left, 60), (right, 315)):         # column by column, as typesetters store it
        tw = pymupdf.TextWriter(pg.rect)
        for i, t in enumerate(col):
            tw.append((x, 100 + 13 * i), t, font=pymupdf.Font("helv"), fontsize=10)
        tw.write_text(pg)
    info = line_cuts(pg, pg.get_text("rawdict"))
    assert not any(v["cuts"] or v["L"] or v["R"] for v in info.values()), info
    us = _units(d)
    assert len(us) == 2 and us[0].startswith("Large models") and us[1].startswith("The focus"), us


def test_list_of_short_lines_is_not_a_table():
    d = pymupdf.open(); pg = d.new_page(width=595, height=400)
    for i, t in enumerate(["Check the appropriate box", "Enter your name here", "Sign and date the form", "Keep a copy"]):
        pg.insert_text((70, 100 + 14 * i), t, fontsize=10, fontname="helv")
    info = line_cuts(pg, pg.get_text("rawdict"))
    assert not any(v["cuts"] or v["L"] or v["R"] for v in info.values())


def test_a_wide_translation_stops_short_of_the_next_cell(fonts_ready):
    """Real case: "批处理大小" grew to the right until it touched "n 个令牌" and read as one word."""
    from patt_pdf import fonts as F
    from patt_pdf.model import Unit
    from patt_pdf.typeset import fit_unit
    u = Unit(uid="u", page=0, kind="text", src="batch size", bbox=[100, 90, 144, 102], lines=[[100, 90, 144, 102, 100]],
             size=10, bold=False, family="sans", color=[0, 0, 0], tgt="批处理大小")
    nxt = [152, 90, 190, 102]
    fs = F.FontSet([u.tgt]); token = F.activate(fs)
    try:
        size, lines, _, box, ok = fit_unit(u, pymupdf.Rect(0, 0, 595, 842), [u.bbox, nxt])
        width = F.font("sans", False).text_length(lines[0], fontsize=size)
    finally:
        F._ACTIVE.reset(token)
    assert ok and len(lines) == 1
    assert 100 + width <= nxt[0] - 0.3 * u.size, (width, size)        # a visible gap stays


def test_a_shrunk_single_line_keeps_the_baseline_of_its_row(tmp_path, fonts_ready):
    """Real case: the one header cell that had to shrink sat lower than the other cells."""
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    (tmp_path / "in").mkdir()
    d = pymupdf.open(); pg = d.new_page(width=420, height=200)
    for x, t in ((60, "rate"), (130, "size"), (200, "count")):       # far apart: three separate cells
        pg.insert_text((x, 100), t, fontsize=11, fontname="helv")
    d.save(tmp_path / "in" / "row.pdf"); d.close()
    f = tmp_path / "tm.json"
    f.write_text(json.dumps({"rate": "率", "size": "每批处理样本数量", "count": "数"}, ensure_ascii=False), encoding="utf-8")
    ws = Workspace(tmp_path / "in", tmp_path / "state"); plan_file(ws, "row.pdf", ocr=False)
    m = ManualBackend(f); translate(ws, ["row.pdf"], m, max_chars=999)
    qa = render_file(ws, "row.pdf", m.namespace, ocr_qa=False)
    assert any(i["issue"] in ("shrunk", "overflow") for i in qa["pages"][0]["issues"]), qa["pages"][0]["issues"]
    with pymupdf.open(ws.out_path("row.pdf")) as o:
        lines = [(sp["bbox"][0], sp["origin"][1], sp["size"])            # one span per cell
                 for b in o[0].get_text("dict")["blocks"] for l in b.get("lines", []) for sp in l["spans"] if sp["text"].strip()]
    lines.sort()
    assert len(lines) == 3
    assert lines[1][2] < 0.8 * lines[0][2]                               # the middle cell was shrunk
    assert all(abs(y - lines[0][1]) < 0.2 for _, y, _ in lines), lines    # and still sits on the row's baseline
