"""`patt-pdf run`: one command from PDF to translated PDF. Offline (manual/pseudo/fake backends)."""
from __future__ import annotations

import io
import json
import sys

import pymupdf
import pytest

from patt_pdf import runcmd
from patt_pdf.cli import main

FAKE_KEY = "00000000-0000-0000-0000-000000000000:fx"
TM = {"Field notes for the first site.": "第一处地点的野外记录。", "Water levels rose after the storm.": "暴风雨过后水位上涨。",
      "Birds returned to the marsh.": "鸟类回到了沼泽地。"}


def cli(*a):
    return main([str(x) for x in a])


def _pdf(path, texts):
    d = pymupdf.open()
    for t in texts:
        pg = d.new_page(width=420, height=300); pg.insert_text((50, 80), t, fontsize=12, fontname="helv")
    d.save(path); d.close()


@pytest.fixture
def job(tmp_path, fonts_ready, monkeypatch):
    src = tmp_path / "in"; src.mkdir()
    _pdf(src / "good.pdf", list(TM)[:2])
    _pdf(src / "partly.pdf", [list(TM)[2], "This sentence has no translation in the table."])
    (src / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    tm = tmp_path / "tm.json"; tm.write_text(json.dumps(TM, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATT_PDF_LANG", "en")
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    monkeypatch.setenv("DEEPL_KEY_FILE", str(tmp_path / "no-such-key"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return {"src": src, "tm": tm, "tmp": tmp_path, "args": ["--backend", "manual", "--manual-tm", tm, "--no-ocr"]}


def test_one_command_writes_every_rendered_file_and_one_line_per_file(job, capsys):
    rc = cli("run", job["src"], *job["args"])
    cap = capsys.readouterr()
    lines = [l for l in cap.out.splitlines() if l.strip()]
    assert len(lines) == 3                                        # one line per input file, nothing else on stdout
    by = {l.split()[1]: l for l in lines}
    assert by["good.pdf"].startswith("pass") and "translated/good.pdf" in by["good.pdf"].replace("\\", "/")
    assert by["partly.pdf"].startswith("fail") and "text without a translation" in by["partly.pdf"]
    assert "1 pass · 1 fail" in by["partly.pdf"] and "translated/partly.pdf" in by["partly.pdf"].replace("\\", "/")
    assert by["broken.pdf"].startswith("error") and "not written" in by["broken.pdf"]
    out = job["tmp"] / "translated"
    assert sorted(p.name for p in out.iterdir()) == ["good.pdf", "partly.pdf"]      # failed file too; no status file
    with pymupdf.open(out / "good.pdf") as o:
        assert "野外记录" in o[0].get_text() and "水位上涨" in o[1].get_text()
    assert rc == 2
    assert (job["tmp"] / "patt-work" / "qa" / "good.pdf.json").exists()            # default working folder


def test_all_pass_returns_zero_and_summary_is_chinese_in_a_chinese_locale(job, capsys, monkeypatch):
    monkeypatch.setenv("PATT_PDF_LANG", "zh_CN.UTF-8")
    assert cli("run", job["src"] / "good.pdf", *job["args"], "--out", job["tmp"] / "o2") == 0
    out = capsys.readouterr().out
    assert out.startswith("pass") and "2 页" in out


def test_rerun_updates_its_own_output_but_never_a_foreign_file(job, capsys):
    assert cli("run", job["src"] / "good.pdf", *job["args"]) == 0
    target = job["tmp"] / "translated" / "good.pdf"
    capsys.readouterr()
    assert cli("run", job["src"] / "good.pdf", *job["args"]) == 0                  # same command again: fine
    assert "exists" not in capsys.readouterr().out
    target.write_bytes(b"my own notes, not a PATT output")                         # user replaced the file
    assert cli("run", job["src"] / "good.pdf", *job["args"]) == 2
    assert "exists, not written" in capsys.readouterr().out
    assert target.read_bytes() == b"my own notes, not a PATT output"


def test_pages_selects_pages_and_keeps_the_document_whole(job, capsys):
    assert cli("run", job["src"] / "partly.pdf", *job["args"], "--pages", "1") == 0
    line = capsys.readouterr().out
    assert line.startswith("pass") and "1 page" in line
    with pymupdf.open(job["tmp"] / "translated" / "partly.pdf") as o:
        assert o.page_count == 2 and "沼泽地" in o[0].get_text() and "no translation in the table" in o[1].get_text()


def test_output_or_work_folder_inside_the_input_is_refused(job, capsys):
    assert cli("run", job["src"], *job["args"], "--out", job["src"] / "zh") == 1
    assert "--out must not be inside" in capsys.readouterr().err
    assert cli("run", job["src"], *job["args"], "--state", job["src"] / "work") == 1
    assert sorted(p.name for p in job["src"].iterdir()) == ["broken.pdf", "good.pdf", "partly.pdf"]


def test_missing_key_explains_what_to_do(job, capsys):
    assert cli("run", job["src"] / "good.pdf", "--no-ocr") == 1
    err = capsys.readouterr().err
    assert "no DeepL key" in err and "patt-pdf key save" in err
    assert not (job["tmp"] / "translated").exists()


class _Opener:
    """Fake DeepL endpoint that records every request."""
    def __init__(self):
        self.calls = []

    def __call__(self, rq, timeout=0):
        self.calls.append(rq.full_url)
        body = json.loads(rq.data) if rq.data else None
        if rq.full_url.endswith("/v2/usage"):
            data = {"character_count": 1000, "character_limit": 500000}
        else:
            data = {"translations": [{"text": TM.get(t, "译文")} for t in body["text"]]}
        return _Resp(json.dumps(data).encode())


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def deepl(job, monkeypatch):
    import urllib.request
    op = _Opener()
    monkeypatch.setenv("DEEPL_AUTH_KEY", FAKE_KEY)
    monkeypatch.setattr(urllib.request, "urlopen", op)
    return op


def test_paid_service_without_a_terminal_needs_max_chars_and_yes(job, deepl, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))                              # not a terminal
    for extra in ([], ["--yes"], ["--max-chars", 500]):
        assert cli("run", job["src"] / "good.pdf", "--no-ocr", *extra) == 2
        assert "Nothing was sent" in capsys.readouterr().err
    assert deepl.calls == []                                                        # not even a usage request
    assert cli("run", job["src"] / "good.pdf", "--no-ocr", "--max-chars", 500, "--yes") == 0
    assert any(u.endswith("/v2/translate") for u in deepl.calls)
    assert capsys.readouterr().out.startswith("pass")


def test_estimate_above_the_limit_sends_nothing(job, deepl, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli("run", job["src"] / "good.pdf", "--no-ocr", "--max-chars", 10, "--yes") == 2
    assert "more than --max-chars 10" in capsys.readouterr().err
    assert not any(u.endswith("/v2/translate") for u in deepl.calls)


class _TtyIn(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("answer,sent", [("n\n", False), ("\n", False), ("y\n", True)])
def test_terminal_prompt_shows_the_estimate_and_obeys_the_answer(job, deepl, capsys, monkeypatch, answer, sent):
    monkeypatch.setattr(sys, "stdin", _TtyIn(answer))
    rc = cli("run", job["src"] / "good.pdf", "--no-ocr")
    cap = capsys.readouterr()
    n = sum(len(t) for t in list(TM)[:2])
    assert f"to translate: {n} characters" in cap.err and "499,000 of 500,000 characters left" in cap.err
    assert any(u.endswith("/v2/translate") for u in deepl.calls) is sent
    assert rc == (0 if sent else 2)
    assert (job["tmp"] / "translated" / "good.pdf").exists() is sent


def test_interrupt_keeps_progress_and_the_next_run_continues(job, capsys, monkeypatch):
    from patt_pdf import jobs as J
    real = J.render_file
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise KeyboardInterrupt
        return real(*a, **k)
    monkeypatch.setattr(J, "render_file", flaky)
    assert cli("run", job["src"] / "good.pdf", *job["args"]) == 130
    assert "run the same command again" in capsys.readouterr().err
    assert cli("run", job["src"] / "good.pdf", *job["args"]) == 0
    assert capsys.readouterr().out.startswith("pass")


def test_reason_phrases_cover_every_status_issue():
    from patt_pdf.jobs import ISSUE_STATUS
    assert set(ISSUE_STATUS) <= set(runcmd.REASONS)
