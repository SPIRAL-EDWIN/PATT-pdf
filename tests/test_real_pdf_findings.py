"""Regressions found on the first real-PDF run with DeepL (2026-11-13, docs/STATUS.md §0-P).

Seven licence-clear documents (arXiv CC BY papers, PLOS ONE, NIST, USGS, IRS) exposed defects
that no synthetic fixture had: a crash on LaTeX named links, letters erased across a page,
sans-serif documents set in a serif face, justified paragraphs cut at every full stop, table
figures sent to the translator, and number checks that failed on correct translations.

The real documents are NOT in the repository. Every case below is rebuilt as a small
synthetic PDF or a plain string, so the tests stay offline.
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from patt_pdf.keep import font_family, is_keep
from patt_pdf.qa import number_check


def _run(tmp_path, pdf_name, tm):
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    src = tmp_path / "src"
    ws = Workspace(src, tmp_path / "state")
    plan_file(ws, pdf_name, ocr=False)
    tmf = tmp_path / "tm.json"
    tmf.write_text(json.dumps(tm, ensure_ascii=False), encoding="utf-8")
    m = ManualBackend(tmf)
    res = translate(ws, [pdf_name], m, max_chars=99999)
    qa = render_file(ws, pdf_name, m.namespace, ocr_qa=False)
    return ws, qa, res


def _plan_units(ws, name):
    from patt_pdf.jobs import load_plan
    return [u for pl in load_plan(ws, name) for u in pl.units]


# ------------------------------------------------------------------ named links (crash)
def test_named_destination_link_survives_render(tmp_path, fonts_ready):
    """hyperref PDFs link citations and footnotes with named destinations. PyMuPDF reports
    them as kind 4 with a 'nameddest' key; rebuilding such a link without that key raised
    KeyError and the whole file ended as ERROR (2 of 7 real documents)."""
    (tmp_path / "src").mkdir()
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 100), "Field notes are summarised below (see Brown, 2020).", fontsize=11, fontname="helv")
    pg.insert_link({"kind": pymupdf.LINK_NAMED, "from": pymupdf.Rect(230, 88, 330, 104), "name": "cite.brown2020"})
    doc.save(tmp_path / "src" / "named.pdf"); doc.close()
    with pymupdf.open(tmp_path / "src" / "named.pdf") as d:
        before = d[0].get_links()
    assert before and before[0]["kind"] == pymupdf.LINK_NAMED
    ws, qa, _ = _run(tmp_path, "named.pdf",
                     {"Field notes are summarised below (see Brown, 2020).": "野外记录摘要如下（见 Brown，2020）。"})
    assert qa["status"] != "error", qa.get("error")
    assert not any(i["issue"] == "link_lost" for p in qa["pages"] for i in p["issues"])
    with pymupdf.open(ws.out_path("named.pdf")) as o:
        after = o[0].get_links()
    assert len(after) == 1 and after[0]["kind"] == pymupdf.LINK_NAMED
    assert (after[0].get("nameddest") or after[0].get("name")) == (before[0].get("nameddest") or before[0].get("name"))


# ------------------------------------------------------------------ letters erased page-wide
def test_single_letter_keep_does_not_erase_that_letter_elsewhere(tmp_path, fonts_ready):
    """A displaced one-letter keep ("A") was searched on the whole page, case-insensitively and
    inside words, and every hit was redacted: a real map lost every 'a' ("P CIFIC OCE N").
    Words that stay in Latin script after translation must keep all their letters."""
    from patt_pdf import render as R
    (tmp_path / "src").mkdir()
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 100), "A", fontsize=12, fontname="helv")
    pg.insert_text((72, 200), "Banana Canal area map", fontsize=12, fontname="helv")
    doc.save(tmp_path / "src" / "letters.pdf"); doc.close()

    with pymupdf.open(tmp_path / "src" / "letters.pdf") as d:
        pg = d[0]
        keep = list(pg.search_for("A", clip=pymupdf.Rect(60, 85, 90, 105))[0]) + ["A"]

        class Plan:  # the keep is reported as moved by pointing its box at an empty place
            pass
        plan = Plan()
        moved_box = pymupdf.Rect(300, 400, 310, 412)
        plan._kp = [("A", moved_box, list(moved_box) + ["A"])]
        plan._keep_spans = {}
        R.restore_keeps(pg, plan)
        text = pg.get_text()
    assert "Banana Canal area map" in text, text
    assert keep


# ------------------------------------------------------------------ font family
@pytest.mark.parametrize("name,flags,want", [
    ("HelveticaNeueLTStd-Roman", 4, "sans"),      # "Roman" weight name + serif flag set by the producer
    ("Univers-Condensed", 4, "sans"),
    ("ArialMT", 4, "sans"),
    ("Calibri", 0, "sans"),
    ("OpenSans", 4, "sans"),
    ("Avenir-Book", 4, "sans"),
    ("Inconsolatazi4-Regular", 4, "sans"),
    ("NimbusRomNo9L-Regu", 4, "serif"),
    ("TimesNewRomanPSMT", 0, "serif"),
    ("MinionPro-Regular", 4, "serif"),
    ("UnknownFace", 4, "serif"),                  # no name hint: the flag decides
    ("UnknownFace", 0, "sans"),
])
def test_font_family_prefers_the_name_over_the_serif_flag(name, flags, want):
    assert font_family(name, flags) == want


# ------------------------------------------------------------------ figures with a unit suffix
@pytest.mark.parametrize("cell", ["13.0B", "32.5B", "1.4T", "4M", "3.0e−4", "1.5e-4", "10×", "≥6.7", "65.2B", "0.95", "25 %"])
def test_figure_cells_are_kept(cell):
    """DeepL rewrote '13.0B' as '130亿' inside a table column; such cells are not sent."""
    assert is_keep(cell)


@pytest.mark.parametrize("text", ["5th", "1st", "22nd", "LLaMA 7B", "Table 2", "3 apples", "Part II"])
def test_words_with_digits_are_still_translated(text):
    assert not is_keep(text)


# ------------------------------------------------------------------ number check
@pytest.mark.parametrize("src,tgt", [
    ("prompting a PaLM 540B with just eight exemplars", "仅向PaLM 540B提供八个示例"),          # \b fails before CJK
    ("New line 3b has been added to this form.", "该表格中新增了第3b行。"),
    ("We use 2, 000 warmup steps.", "我们进行了2,000次预热训练。"),                             # TeX thin space
    ("Peter V. Coyle1,2,3", "彼得·V·科伊尔1,2,3"),                                             # affiliation marks
    ("more than 18.4 million people", "1,840多万人口"),
    ("our 65B-parameter model", "我们的65B参数模型"),
    ("antibody status was used to determine COVID-19 exposure", "抗体状况被用来确定新冠病毒暴露情况"),
])
def test_number_check_accepts_correct_translations(src, tgt):
    assert number_check(src, tgt) == []


@pytest.mark.parametrize("src,tgt", [
    ("PaLM, which has models of 8B, 62B, and 540B parameters", "其模型参数分别为 8 亿、62 亿和 540 亿"),   # real DeepL output
    ("revenue grew 5 billion", "收入增长3亿"),
    ("rose 12,345 units", "增长1.2万个"),
])
def test_number_check_still_catches_wrong_figures(src, tgt):
    assert number_check(src, tgt)


# ------------------------------------------------------------------ justified paragraphs
def _justified_page(path, lines, x=72, width=220, size=10, pitch=12.5, indent_last=False):
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    tw = pymupdf.TextWriter(pg.rect)
    f = pymupdf.Font("helv")
    for i, ln in enumerate(lines):
        x_ = x + (14 if indent_last and i == len(lines) - 1 else 0)
        words = ln.split(" ")
        natural = f.text_length(ln, fontsize=size)
        extra = (width - (x_ - x) - natural) / max(1, len(words) - 1)
        cx = x_
        for w in words:                      # one writer, one block: like a justified column
            tw.append((cx, 100 + i * pitch), w + " ", font=f, fontsize=size)
            cx += f.text_length(w + " ", fontsize=size) + extra
    tw.write_text(pg)
    doc.save(path); doc.close()


FULL = ["Large models trained on many texts can follow",
        "new instructions after only a few examples.",
        "These properties first appeared when models",
        "were scaled to a sufficient size by others."]


def test_full_width_line_ending_with_a_period_does_not_split_the_paragraph(tmp_path):
    from patt_pdf.jobs import Workspace, plan_file
    (tmp_path / "src").mkdir()
    _justified_page(tmp_path / "src" / "just.pdf", FULL)
    ws = Workspace(tmp_path / "src", tmp_path / "state")
    plan_file(ws, "just.pdf", ocr=False)
    units = _plan_units(ws, "just.pdf")
    assert len(units) == 1, [u.src for u in units]
    assert units[0].src.startswith("Large models") and units[0].src.endswith("by others.")


def test_indented_line_after_a_period_still_starts_a_new_paragraph(tmp_path):
    from patt_pdf.jobs import Workspace, plan_file
    (tmp_path / "src").mkdir()
    _justified_page(tmp_path / "src" / "indent.pdf", FULL[:2] + ["The next paragraph is indented and short."],
                    indent_last=True)
    ws = Workspace(tmp_path / "src", tmp_path / "state")
    plan_file(ws, "indent.pdf", ocr=False)
    units = _plan_units(ws, "indent.pdf")
    assert len(units) == 2, [u.src for u in units]


# ------------------------------------------------------------------ drop caps
def test_drop_cap_next_to_translated_lines_is_not_reported_as_changed(tmp_path, fonts_ready):
    """A kept drop cap is as tall as two lines; its box also covers the start of the second
    line. That line is translated, so its ink changes, but the drop cap itself does not."""
    (tmp_path / "src").mkdir()
    doc = pymupdf.open(); pg = doc.new_page(width=420, height=300)
    pg.insert_text((60, 118), "U", fontsize=40, fontname="tibi", color=(0.45, 0.45, 0.45))
    pg.insert_text((92, 96), "sing information from", fontsize=11, fontname="helv")
    pg.insert_text((92, 110), "recent earthquakes and", fontsize=11, fontname="helv")
    pg.insert_text((58, 130), "improved mapping of faults", fontsize=11, fontname="helv")    # its top reaches into the U box
    doc.save(tmp_path / "src" / "cap.pdf"); doc.close()
    with pymupdf.open(tmp_path / "src" / "cap.pdf") as d:
        cap = d[0].search_for("U", clip=pymupdf.Rect(55, 70, 92, 135))[0]
        line3 = d[0].search_for("improved")[0]
        assert line3.y0 < cap.y1 and line3.y1 > cap.y1                    # the boxes overlap, the glyphs do not
    ws, qa, _ = _run(tmp_path, "cap.pdf", {"sing information from recent earthquakes and": "基于近期地震的数据以及",
                                           "sing information from": "基于近期地震的数据", "recent earthquakes and": "以及",
                                           "improved mapping of faults": "对活动断层更精确的测绘"})
    issues = [i["issue"] for p in qa["pages"] for i in p["issues"]]
    assert "keep_changed" not in issues, qa["pages"][0]["issues"]
    with pymupdf.open(ws.out_path("cap.pdf")) as o:
        assert "U" in o[0].get_text() and "测绘" in o[0].get_text()


def test_a_kept_figure_that_really_changes_is_still_reported(tmp_path, fonts_ready):
    from patt_pdf.model import PagePlan, Unit
    from patt_pdf.qa import keep_integrity
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, txt in ((a, "1,250"), (b, "9,863")):
        d = pymupdf.open(); pg = d.new_page(width=300, height=200); pg.insert_text((60, 100), txt, fontsize=14, fontname="helv")
        d.save(path); d.close()
    with pymupdf.open(a) as d:
        box = list(d[0].search_for("1,250")[0])
    unit = Unit(uid="u", page=0, kind="text", src="x", bbox=[200, 20, 280, 40], lines=[[200, 20, 280, 40, 36]], size=10,
                bold=False, family="sans", color=[0, 0, 0], erase=[[200, 20, 280, 40]], tgt="译")
    assert keep_integrity(a, b, 0, PagePlan(0, "text", [unit], [box + ["1,250"]]))
