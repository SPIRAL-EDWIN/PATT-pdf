"""--pages (ranges and single pages), progress output, and page workers.

Synthetic PDFs only; no network.
"""
from __future__ import annotations

import io
import json

import numpy as np
import pymupdf
import pytest

from patt_pdf import pages as P
from patt_pdf.cli import main
from patt_pdf.progress import Progress


def cli(*a):
    return main([str(x) for x in a])


# ------------------------------------------------------------------ parser
@pytest.mark.parametrize("spec,count,want", [
    ("7", 10, [6]),
    ("7-9", 10, [6, 7, 8]),
    ("7,9", 10, [6, 8]),
    ("1-3,7,10-", 12, [0, 1, 2, 6, 9, 10, 11]),
    ("-3", 10, [0, 1, 2]),
    ("8-", 10, [7, 8, 9]),
    ("9,7", 10, [6, 8]),                 # order does not matter
    ("7,7,6-8", 10, [5, 6, 7]),          # duplicates and overlaps merge
    (" 2 , 4 ", 5, [1, 3]),              # spaces around items
    ("1-1", 3, [0]),
    ("1-", 1, [0]),
    ("3", 3, [2]),
])
def test_page_selection_accepts(spec, count, want):
    assert P.resolve(spec, count) == want


@pytest.mark.parametrize("spec,count", [
    ("", 5), ("0", 5), ("9-7", 10), ("11", 10), ("3-11", 10), ("a", 5), ("1,,2", 5), ("1-2-3", 5),
    ("-", 5), ("1.5", 5), ("7 9", 10), ("-0", 5),
])
def test_page_selection_rejects(spec, count):
    with pytest.raises(P.PageSelectionError):
        P.resolve(spec, count)


def test_label_round_trip():
    assert P.label([0, 1, 2, 6, 9, 10]) == "1-3,7,10-11"
    assert P.resolve(P.label([0, 1, 2, 6, 9, 10]), 11) == [0, 1, 2, 6, 9, 10]


# ------------------------------------------------------------------ pipeline with --pages
TEXTS = ["Field notes for the first site.", "Water levels rose after the storm.", "Birds returned to the marsh.",
         "The survey ended in late autumn.", "Results are listed in the appendix."]
TM = {t: z for t, z in zip(TEXTS, ["第一处地点的野外记录。", "暴风雨过后水位上涨。", "鸟类回到了沼泽地。",
                                     "调查在深秋结束。", "结果列在附录中。"])}


@pytest.fixture
def five(tmp_path, fonts_ready):
    src = tmp_path / "in"; src.mkdir()
    d = pymupdf.open()
    for t in TEXTS:
        pg = d.new_page(width=420, height=300)
        pg.insert_text((50, 80), t, fontsize=12, fontname="helv")
    d.save(src / "five.pdf"); d.close()
    tm = tmp_path / "tm.json"; tm.write_text(json.dumps(TM, ensure_ascii=False), encoding="utf-8")
    return {"src": src, "pdf": src / "five.pdf", "state": tmp_path / "state", "tm": tm, "tmp": tmp_path}


def _pix(path, pno):
    with pymupdf.open(path) as d:
        pm = d[pno].get_pixmap(dpi=60, colorspace=pymupdf.csRGB, alpha=False)
        return np.frombuffer(pm.samples, dtype=np.uint8).copy()


def test_discrete_pages_translate_only_those_pages(five, capsys):
    ident = ["--backend", "manual", "--manual-tm", five["tm"]]
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", "2,4", "--no-ocr") == 0
    capsys.readouterr()
    assert cli("estimate", five["pdf"], "--state", five["state"], "--pages", "2,4", *ident) == 0
    out = capsys.readouterr().out
    assert f"TOTAL to translate: {len(TEXTS[1]) + len(TEXTS[3])} characters in 2 unique segments" in out
    assert cli("translate", five["pdf"], "--state", five["state"], "--pages", "2,4", *ident, "--max-chars", 999) == 0
    assert cli("render", five["pdf"], "--state", five["state"], "--pages", "2,4", *ident) == 0
    out_pdf = five["state"] / "out" / "five.pdf"
    with pymupdf.open(out_pdf) as o:
        assert o.page_count == 5                                  # the whole document is kept
        text = [o[i].get_text() for i in range(5)]
    assert "暴风雨" in text[1] and "深秋" in text[3]
    for i in (0, 2, 4):                                           # untouched pages: same text, same pixels
        assert TEXTS[i] in text[i]
        assert np.array_equal(_pix(five["pdf"], i), _pix(out_pdf, i))
    qa = json.loads((five["state"] / "qa" / "five.pdf.json").read_text(encoding="utf-8"))
    assert [p["page"] for p in qa["pages"]] == [2, 4] and qa["status"] == "pass"
    capsys.readouterr()
    assert cli("report", five["pdf"], "--state", five["state"]) == 0
    rep = capsys.readouterr().out
    assert "pages: 2" in rep
    for word in ("not selected", "unselected", "skipped", "未选"):   # no marker for the other pages
        assert word not in rep


def test_range_reuses_pages_planned_before(five, capsys):
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", "2", "--no-ocr") == 0
    capsys.readouterr()
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", "2-3", "--no-ocr") == 0
    assert "reused 1 pages" in capsys.readouterr().out
    j = json.loads((five["state"] / "plans" / "five.pdf.json").read_text(encoding="utf-8"))
    assert [p["page"] for p in j["pages"]] == [1, 2] and j["doc_pages"] == 5
    # the same selection again is served from the cache
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", "3,2", "--no-ocr") == 0
    assert capsys.readouterr().out.startswith("cached")


def test_translation_cache_is_shared_between_selections(five):
    """The page selection is not part of the translation identity: nothing is paid twice."""
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, translate
    ws = Workspace(five["pdf"], five["state"])
    plan_file(ws, "five.pdf", ocr=False, pages=[1])
    m = ManualBackend(five["tm"])
    assert translate(ws, ["five.pdf"], m, max_chars=999, pages=[1])["sent_chars"] == len(TEXTS[1])
    plan_file(ws, "five.pdf", ocr=False, pages=[1, 2])
    s = translate(ws, ["five.pdf"], ManualBackend(five["tm"]), max_chars=999, pages=[1, 2])
    assert s["sent_chars"] == len(TEXTS[2]) and s["cache_hits"] == 1


def test_selection_that_was_not_planned_is_refused(five, capsys):
    ident = ["--backend", "manual", "--manual-tm", five["tm"]]
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", "2", "--no-ocr") == 0
    capsys.readouterr()
    assert cli("estimate", five["pdf"], "--state", five["state"], "--pages", "2-3", *ident) == 1
    assert "not planned" in capsys.readouterr().out
    # no --pages after a partial plan: say so instead of silently treating two pages as the document
    assert cli("estimate", five["pdf"], "--state", five["state"], *ident) == 1
    assert "only page(s) 2 of 5 are planned" in capsys.readouterr().out
    assert cli("render", five["pdf"], "--state", five["state"], *ident) == 1


@pytest.mark.parametrize("spec", ["9", "0", "3-2", "x", "2,,3"])
def test_bad_selection_is_an_error_and_creates_no_plan(five, capsys, spec):
    assert cli("plan", five["pdf"], "--state", five["state"], "--pages", spec, "--no-ocr") == 1
    assert "--pages" in capsys.readouterr().err
    assert not (five["state"] / "plans").exists()


def test_pages_needs_exactly_one_document(five, capsys):
    import shutil
    shutil.copy(five["pdf"], five["src"] / "second.pdf")
    assert cli("plan", five["src"], "--state", five["state"], "--pages", "1", "--no-ocr") == 1
    assert "one document" in capsys.readouterr().err
    assert cli("plan", five["src"], "--state", five["state"], "--files", "five.pdf", "--pages", "1", "--no-ocr") == 0


def test_compare_accepts_the_same_syntax(five, capsys):
    ident = ["--backend", "manual", "--manual-tm", five["tm"]]
    for cmd, extra in (("plan", ["--no-ocr"]), ("translate", [*ident, "--max-chars", 999]), ("render", ident)):
        assert cli(cmd, five["pdf"], "--state", five["state"], *extra) == 0
    capsys.readouterr()
    assert cli("compare", five["pdf"], "--state", five["state"], "--out", five["tmp"] / "cmp", "--pages", "1,3-4") == 0
    names = sorted(p.name for p in (five["tmp"] / "cmp").iterdir())
    assert names == ["five_p1.png", "five_p3.png", "five_p4.png"]


# ------------------------------------------------------------------ progress
class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_progress_redirected_has_one_plain_line_per_file():
    buf = io.StringIO(); p = Progress(stream=buf)
    for i in range(1, 6):
        p.update("plan", "a.pdf", i, 5)
    p.update("plan", "b.pdf", 1, 2); p.clear()
    assert buf.getvalue() == "plan: a.pdf (5 pages)\nplan: b.pdf (2 pages)\n"
    assert "\r" not in buf.getvalue() and "\x1b" not in buf.getvalue()


def test_progress_terminal_rewrites_one_line_and_clears_it():
    buf = _Tty(); p = Progress(stream=buf)
    p.update("plan", "a.pdf", 5, 5); p.clear()
    v = buf.getvalue()
    assert "page 5/5" in v and v.endswith("\r\x1b[2K") and "\n" not in v


def test_quiet_and_broken_streams_never_fail():
    buf = io.StringIO(); Progress(quiet=True, stream=buf).update("plan", "a.pdf", 1, 2)
    assert buf.getvalue() == ""

    class Closed(io.StringIO):
        def write(self, s):
            raise OSError("closed pipe")
    p = Progress(stream=Closed()); p.update("plan", "a.pdf", 1, 2); p.update("plan", "b.pdf", 1, 2)


def test_cli_progress_goes_to_stderr_only(five, capsys):
    assert cli("plan", five["pdf"], "--state", five["state"], "--no-ocr") == 0
    cap = capsys.readouterr()
    assert cap.out.startswith("planned") and "plan: five.pdf" in cap.err and "\r" not in cap.err
    assert cli("plan", five["pdf"], "--state", five["tmp"] / "s2", "--no-ocr", "--quiet") == 0
    assert capsys.readouterr().err == ""


# ------------------------------------------------------------------ page workers
def _image_pages(path, n=4):
    from PIL import Image, ImageDraw
    d = pymupdf.open()
    for i in range(n):
        pg = d.new_page(width=420, height=300)
        pg.insert_text((40, 40), f"Station report number {i + 1} for the river.", fontsize=11, fontname="helv")
        im = Image.new("RGB", (600, 260), (235, 240, 245)); ImageDraw.Draw(im).rectangle((20, 20, 580, 240), outline=(40, 60, 90), width=4)
        b = io.BytesIO(); im.save(b, "PNG")
        pg.insert_image(pymupdf.Rect(40, 80, 380, 230), stream=b.getvalue())
    d.save(path); d.close()


def test_workers_give_the_same_plan_as_one_process(tmp_path, monkeypatch):
    """Pages that need OCR are planned in separate processes. The result must not depend on it."""
    from patt_pdf import analyze
    from patt_pdf.jobs import Workspace, plan_file
    src = tmp_path / "in"; src.mkdir(); _image_pages(src / "img.pdf")
    with pymupdf.open(src / "img.pdf") as d:
        assert all(analyze.page_needs_ocr(d[i]) for i in range(4))
    plans = {}
    for w in (1, 3):
        ws = Workspace(src, tmp_path / f"state{w}")
        st = plan_file(ws, "img.pdf", ocr=True, workers=w)
        assert st["status"] == "planned" and st["pages"] == 4
        j = json.loads(ws.plan_path("img.pdf").read_text(encoding="utf-8"))
        plans[w] = [json.dumps(p, sort_keys=True, ensure_ascii=False) for p in j["pages"]]
    assert plans[1] == plans[3]


def test_text_only_pages_start_no_worker_processes(five, monkeypatch):
    import concurrent.futures as cf
    from patt_pdf.jobs import Workspace, plan_file

    def boom(*a, **k):
        raise AssertionError("no process pool is needed for pages without images")
    monkeypatch.setattr(cf, "ProcessPoolExecutor", boom)
    ws = Workspace(five["pdf"], five["state"])
    assert plan_file(ws, "five.pdf", ocr=True, workers=4)["status"] == "planned"
