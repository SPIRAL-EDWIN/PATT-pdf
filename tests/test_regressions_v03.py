"""Regression tests for findings of the third review (see docs/STATUS.md).

* pages with a few outlined glyphs were classified "blank" and passed without checks;
* `translate` returned complete/0 although inputs were unreadable;
* DeepL retries could send more than --max-chars, and --glossary created a remote
  glossary before the budget checks.
Offline: synthetic PDFs, fake HTTP opener, no key, no quota.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import urllib.error

import pymupdf
import pytest

from conftest import needs_ocr
from patt_pdf.cli import main

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent / "fixtures"))
from make_fixtures import _outline  # noqa: E402

FAKE_KEY = "00000000-0000-0000-0000-000000000000:fx"


def cli(*a):
    return main([str(x) for x in a])


# ---------------------------------------------------------------- blank pages
@pytest.fixture
def sparse(tmp_path):
    d = tmp_path / "in"; d.mkdir()
    src = pymupdf.open(); sp = src.new_page(width=595, height=842)
    sp.insert_text((60, 100), "Exit route", fontsize=14, fontname="helv")
    _outline(sp).save(d / "few_outlined.pdf")
    doc = pymupdf.open(); p = doc.new_page()
    p.draw_rect((100, 100, 300, 300), color=(0, 0, 1), width=2); p.draw_line((100, 300), (300, 100))
    doc.save(d / "chart_only.pdf")
    doc = pymupdf.open(); doc.new_page(); doc.save(d / "empty.pdf")
    tm = tmp_path / "tm.json"; tm.write_text(json.dumps({"Exit route": "逃生路线"}, ensure_ascii=False), encoding="utf-8")
    return {"in": d, "st": tmp_path / "st", "tm": tm}


def test_few_outlined_glyphs_are_not_a_silent_pass(sparse, fonts_ready):
    from patt_pdf.classify import classify_page
    with pymupdf.open(sparse["in"] / "few_outlined.pdf") as d:
        assert classify_page(d[0]) == "vector_few"
    s, st, tm = sparse["in"], sparse["st"], sparse["tm"]
    assert cli("plan", s, "--state", st, "--no-ocr") == 0
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99) == 0
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm) == 2
    q = {f: json.loads((st / "qa" / f"{f}.json").read_text(encoding="utf-8")) for f in ("few_outlined.pdf", "chart_only.pdf", "empty.pdf")}
    assert q["few_outlined.pdf"]["status"] == "unverified"
    assert any(i["issue"] == "possible_text_not_checked" for i in q["few_outlined.pdf"]["pages"][0]["issues"])
    assert q["chart_only.pdf"]["status"] == "pass" and q["chart_only.pdf"]["pages"][0]["kind"] == "graphics"
    assert q["empty.pdf"]["status"] == "pass" and q["empty.pdf"]["pages"][0]["kind"] == "blank"


@needs_ocr
def test_few_outlined_glyphs_are_ocrd_when_available(sparse, fonts_ready):
    s, st, tm = sparse["in"], sparse["st"], sparse["tm"]
    assert cli("plan", s, "--state", st, "--files", "few_outlined.pdf") == 0
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99,
               "--files", "few_outlined.pdf") == 0
    cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "few_outlined.pdf")
    with pymupdf.open(st / "out" / "few_outlined.pdf") as o:
        assert "逃生路线" in o[0].get_text()


# ---------------------------------------------------------------- unreadable inputs
def test_unreadable_inputs_change_translate_outcome(corpus, tmp_path, capsys):
    tm = corpus["manual_tm"]
    bad = tmp_path / "bad"; bad.mkdir()
    for f in ("damaged.pdf", "encrypted.pdf"):
        shutil.copy(corpus["src"] / f, bad)
    mix = tmp_path / "mix"; mix.mkdir()
    for f in ("damaged.pdf", "toc.pdf"):
        shutil.copy(corpus["src"] / f, mix)
    cli("plan", bad, "--state", tmp_path / "sb", "--no-ocr")
    assert cli("translate", bad, "--state", tmp_path / "sb", "--backend", "manual", "--manual-tm", tm,
               "--max-chars", 99) == 1                                   # nothing readable: error
    cli("plan", mix, "--state", tmp_path / "sm", "--no-ocr"); capsys.readouterr()
    assert cli("translate", mix, "--state", tmp_path / "sm", "--backend", "manual", "--manual-tm", tm,
               "--max-chars", 999) == 2                                  # readable part done, batch incomplete
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "partial" and "damaged.pdf" in out["stopped"] and "--files" in out["stopped"]
    assert cli("translate", mix, "--state", tmp_path / "sm", "--backend", "manual", "--manual-tm", tm,
               "--max-chars", 999, "--files", "toc.pdf") == 0             # explicit exclusion: complete
    (mix / "damaged.pdf").unlink()                                       # recovery: remove/repair, re-plan
    cli("plan", mix, "--state", tmp_path / "sm", "--no-ocr")
    assert cli("translate", mix, "--state", tmp_path / "sm", "--backend", "manual", "--manual-tm", tm,
               "--max-chars", 999) == 0


# ---------------------------------------------------------------- DeepL retries and glossary
class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _opener(script):
    """Items: dict -> JSON 200, int -> HTTP error, "timeout" -> network timeout."""
    calls = []

    def _open(req, timeout=None):
        calls.append(req.full_url.split(".com", 1)[1])
        item = script.pop(0)
        if item == "timeout":
            raise urllib.error.URLError(TimeoutError("timed out"))
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "x", {}, None)
        return _Resp(json.dumps(item).encode())
    _open.calls = calls
    return _open


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv("DEEPL_AUTH_KEY", FAKE_KEY)


def test_meter_counts_retries_and_refuses_past_budget(key_env, tmp_path):
    from patt_pdf.backends import BudgetExceeded, DeepLBackend, Meter
    op = _opener(["timeout", "timeout", {"translations": [{"text": "你好"}]}])
    be = DeepLBackend(tmp_path / "l.jsonl", qps=1000, opener=op, sleep=lambda s: None)
    be.meter = m = Meter(max_chars=10)                 # "Hello" = 5 chars: room for two attempts only
    with pytest.raises(BudgetExceeded):
        be.translate(["Hello"])
    assert len(op.calls) == 2 and m.sent == 10 and m.unknown == 10 and m.sent <= m.max_chars


def test_rejected_attempts_are_not_possibly_billed(key_env, tmp_path):
    from patt_pdf.backends import DeepLBackend, Meter
    op = _opener([429, {"translations": [{"text": "你好"}]}])
    be = DeepLBackend(tmp_path / "l.jsonl", qps=1000, opener=op, sleep=lambda s: None)
    be.meter = m = Meter(max_chars=100)
    assert be.translate(["Hello"]) == ["你好"]
    assert m.sent == 10 and m.rejected == 5 and m.unknown == 0 and m.retries == 1


def test_job_never_sends_more_than_max_chars(key_env, corpus, tmp_path):
    from patt_pdf.backends import DeepLBackend
    from patt_pdf.jobs import Workspace, estimate, plan_file, translate
    ws = Workspace(corpus["src"], tmp_path / "st"); plan_file(ws, "toc.pdf", ocr=False)
    op = _opener([{"character_count": 0, "character_limit": 1_000_000}] + ["timeout"] * 10)
    be = DeepLBackend(tmp_path / "l.jsonl", qps=1000, opener=op, sleep=lambda s: None)
    need = estimate(ws, ["toc.pdf"], be.namespace)["chars"]
    s = translate(ws, ["toc.pdf"], be, max_chars=need, reserve=0)
    assert s["sent_chars"] == need <= s["max_chars"]            # the retry was refused before sending
    assert s["possibly_billed_chars"] == need and s["outcome"] == "failed"
    assert "budget" in s["stopped"] and op.calls.count("/v2/translate") == 1


def test_glossary_is_not_created_when_the_run_is_refused(key_env, corpus, tmp_path, monkeypatch):
    import patt_pdf.backends as B
    src = tmp_path / "in"; src.mkdir(); shutil.copy(corpus["src"] / "toc.pdf", src)
    g = tmp_path / "g.tsv"; g.write_text("Contents\t目录\n", encoding="utf-8")
    st = tmp_path / "st"
    cli("plan", src, "--state", st, "--no-ocr")
    op = _opener([{"character_count": 0, "character_limit": 1_000_000}])
    monkeypatch.setattr(B.urllib.request, "urlopen", op)
    assert cli("translate", src, "--state", st, "--backend", "deepl", "--yes", "--glossary", g, "--max-chars", 3) == 2
    assert "/v2/glossaries" not in op.calls and op.calls == []          # refused before any request
    # a run that passes the budget creates the glossary once, after the usage check
    op2 = _opener([{"character_count": 0, "character_limit": 1_000_000}, {"glossary_id": "g-1", "entry_count": 1}]
                  + [{"translations": [{"text": "译"}] * 50}] * 5 + [{"character_count": 9, "character_limit": 1_000_000}])
    monkeypatch.setattr(B.urllib.request, "urlopen", op2)
    cli("translate", src, "--state", st, "--backend", "deepl", "--yes", "--glossary", g, "--max-chars", 9999)
    assert op2.calls[:3] == ["/v2/usage", "/v2/glossaries", "/v2/translate"]
    assert op2.calls.count("/v2/glossaries") == 1


# ---------------------------------------------------------------- shareable reports
def test_error_messages_do_not_leak_local_paths(corpus, tmp_path, monkeypatch):
    from patt_pdf.jobs import Workspace, plan_file
    from patt_pdf.report import markdown
    import patt_pdf.jobs as J
    src = tmp_path / "private folder"; src.mkdir(); shutil.copy(corpus["src"] / "toc.pdf", src / "truncated.pdf")
    ws = Workspace(src, tmp_path / "st")

    def failing_open(path, *a, **k):            # MuPDF error texts quote the full path (version-independent)
        raise RuntimeError(f"Failed to open file '{path}' as type pdf.")
    monkeypatch.setattr(J.pymupdf, "open", failing_open)
    st = plan_file(ws, "truncated.pdf", ocr=False)
    monkeypatch.undo()
    assert st["status"] == "error" and str(tmp_path) not in st["error"] and "<input>" in st["error"]
    md = markdown(ws, ["truncated.pdf"])
    assert str(tmp_path) not in md and "private folder" not in md


def test_reconstructed_pdf_is_never_a_clean_pass(corpus, tmp_path, fonts_ready):
    """A truncated file that MuPDF reconstructs (behaviour differs between PyMuPDF versions)."""
    from patt_pdf.jobs import Workspace, plan_file, render_file
    from patt_pdf.backends import ManualBackend
    src = tmp_path / "in"; src.mkdir()
    full = (corpus["src"] / "toc.pdf").read_bytes()
    xref = full.rfind(b"xref")
    (src / "cut.pdf").write_bytes(full[:xref if xref > 0 else len(full) * 3 // 4])     # xref table lost
    ws = Workspace(src, tmp_path / "st")
    st = plan_file(ws, "cut.pdf", ocr=False)
    if st["status"] == "error":
        return                                      # this PyMuPDF refuses the file: also acceptable
    m = ManualBackend(corpus["manual_tm"])
    q = render_file(ws, "cut.pdf", m.namespace, ocr_qa=False)
    with pymupdf.open(src / "cut.pdf") as d:
        repaired = d.is_repaired
    if repaired:
        assert q["status"] not in ("pass", "review")
        assert any(i["issue"] == "source_repaired" for p in q["pages"] for i in p["issues"])
