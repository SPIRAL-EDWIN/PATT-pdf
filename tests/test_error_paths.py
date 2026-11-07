"""Shared error paths found on macOS and Windows (candidate 6b969b8, findings W03 / macOS P1).

On both systems `render` aborted the whole batch with `KeyError: 'status'`:
* without Tesseract, the OCR residual check raised OCRUnavailable after the page was already
  recorded without a status; the CLI then indexed p['status'];
* with the output PDF locked (Windows), replace_file raised PermissionError at the same point.
Both are platform-independent. These tests drive the real CLI with synthetic PDFs, offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import pymupdf
import pytest

from patt_pdf.cli import main

SCANS = ("scanned.pdf", "vector_glyphs.pdf", "decor_scan.pdf")


def cli(*a):
    return main([str(x) for x in a])


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def no_tesseract(monkeypatch, tmp_path):
    """Hide every Tesseract location the product knows about (PATH, override, Windows defaults)."""
    import patt_pdf.ocr as O
    monkeypatch.setenv("PATT_PDF_TESSERACT", str(tmp_path / "no-tesseract-here"))
    monkeypatch.setattr(O, "tesseract_cmd", lambda: (_ for _ in ()).throw(
        O.OCRUnavailable("tesseract not found: install it or set PATT_PDF_TESSERACT to the executable")))


@pytest.fixture
def batch(corpus, tmp_path):
    src = tmp_path / "in"; src.mkdir()
    for f in ("toc.pdf", "table.pdf", "damaged.pdf") + SCANS:
        shutil.copy(corpus["src"] / f, src)
    return {"in": src, "st": tmp_path / "st", "tm": corpus["manual_tm"], "tmp": tmp_path}


def _qa(st, f):
    return json.loads((st / "qa" / f"{f}.json").read_text(encoding="utf-8"))


def test_ocr_unavailable_batch_continues_and_is_not_pass(batch, fonts_ready, monkeypatch, tmp_path, capsys):
    """The scenario from both reports: plan WITH OCR available, render on a machine WITHOUT it
    (the plan for scans then contains OCR'd units and the residual check needs Tesseract)."""
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    assert cli("plan", s, "--state", st) in (1, 2)                            # damaged.pdf is an error
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999) in (0, 2)
    no_tesseract(monkeypatch, tmp_path); capsys.readouterr()
    rc = cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm)
    out = capsys.readouterr()
    assert "KeyError" not in out.out + out.err
    assert rc == 1                                                            # damaged.pdf: error
    for f in ("toc.pdf", "table.pdf"):                                        # files after the scans still rendered
        assert _qa(st, f)["status"] == "pass" and (st / "out" / f).exists()
    for f in SCANS:
        q = _qa(st, f)
        assert q["status"] not in ("pass", "error"), (f, q.get("error"))
        assert all("status" in p for p in q["pages"])
        assert any(i["issue"] == "residual_check_skipped" for p in q["pages"] for i in p["issues"])
    rep = tmp_path / "r.md"
    assert cli("report", s, "--state", st, "--out", rep) == 0
    text = rep.read_text(encoding="utf-8")
    assert "not rendered" not in text.split("## ")[0] or "toc.pdf | pass" in text


def test_ocr_unavailable_at_plan_time_is_page_not_processed(batch, fonts_ready, monkeypatch, tmp_path):
    no_tesseract(monkeypatch, tmp_path)
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    cli("plan", s, "--state", st)
    cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999)
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm) == 1
    for f in SCANS:
        q = _qa(st, f)
        assert q["status"] == "fail"
        assert any(i["issue"] == "page_not_processed" for p in q["pages"] for i in p["issues"])
    assert _qa(st, "toc.pdf")["status"] == "pass"


def _locked_replace(monkeypatch):
    """Simulated lock: what os.replace raises on Windows when a viewer holds the file."""
    import patt_pdf.jobs as J
    real = J.os.replace

    def replace(a, b):
        if str(b).endswith("table.pdf") and ".tmp-" in str(a):
            err = PermissionError(13, "The process cannot access the file because it is being used by another process")
            err.winerror = 32
            raise err
        return real(a, b)
    monkeypatch.setattr(J.os, "replace", replace)
    monkeypatch.setattr(J.time, "sleep", lambda s: None)


def test_locked_output_is_reported_and_batch_continues(batch, fonts_ready, monkeypatch, capsys):
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    cli("plan", s, "--state", st, "--no-ocr", "--files", "t*.pdf")
    cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999, "--files", "t*.pdf")
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "t*.pdf") == 0
    out_pdf = st / "out" / "table.pdf"; before = sha(out_pdf)
    _locked_replace(monkeypatch); capsys.readouterr()
    rc = cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "t*.pdf")
    out = capsys.readouterr().out
    assert rc == 1 and "KeyError" not in out
    assert "in use" in out and "close the output PDF" in out                     # actionable
    assert "PASS       toc.pdf" in out                                           # the other file still rendered
    assert sha(out_pdf) == before                                                # old output intact
    assert not list((st / "out").glob(".tmp-*"))                                 # no temp files left
    q = _qa(st, "table.pdf")
    assert q["error_kind"] == "file_in_use_or_read_only" and str(st) not in q["error"]


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows share-mode lock (CreateFileW without FILE_SHARE_DELETE)")
def test_native_windows_lock(batch, fonts_ready, capsys):
    import ctypes
    from ctypes import wintypes
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    cli("plan", s, "--state", st, "--no-ocr", "--files", "table.pdf")
    cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 9999, "--files", "table.pdf")
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "table.pdf") == 0
    out_pdf = st / "out" / "table.pdf"; before = sha(out_pdf)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(str(out_pdf), 0x80000000, 0x1, None, 3, 0x80, None)   # GENERIC_READ, FILE_SHARE_READ
    assert h != wintypes.HANDLE(-1).value
    try:
        capsys.readouterr()
        rc = cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "table.pdf")
        out = capsys.readouterr().out
    finally:
        k32.CloseHandle(h)
    assert rc == 1 and "in use" in out and "KeyError" not in out
    assert sha(out_pdf) == before and not list((st / "out").glob(".tmp-*"))


def test_any_unexpected_exception_keeps_schema_and_batch(batch, fonts_ready, monkeypatch, capsys):
    """Defensive: an unexpected error inside one file must not abort the batch or break the schema."""
    import patt_pdf.render as R
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    cli("plan", s, "--state", st, "--no-ocr", "--files", "t*.pdf")
    cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999, "--files", "t*.pdf")
    real = R.apply_plan

    def boom(pg, plan):
        if pg.parent.name.endswith("table.pdf"):
            raise ValueError("synthetic failure")
        return real(pg, plan)
    monkeypatch.setattr(R, "apply_plan", boom); capsys.readouterr()
    rc = cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "t*.pdf")
    out = capsys.readouterr().out
    assert rc == 1 and "PASS       toc.pdf" in out and "ValueError: synthetic failure" in out
    q = _qa(st, "table.pdf")
    assert q["status"] == "error" and q["error_kind"] == "internal_error"
    assert all(p.get("status") == "error" for p in q["pages"])


def test_cli_tolerates_qa_without_page_status(monkeypatch, tmp_path, capsys):
    """Unit guard for the exact crash: a QA dict whose pages lack 'status'."""
    import patt_pdf.cli as C
    import patt_pdf.jobs as J
    src = tmp_path / "in"; src.mkdir()
    d = pymupdf.open(); d.new_page(); d.save(src / "a.pdf")
    monkeypatch.setattr(J, "render_file", lambda *a, **k: {"rel": "a.pdf", "status": "error", "error": "X",
                                                           "pages": [{"page": 1, "issues": []}]})
    monkeypatch.setattr(C, "_ns", lambda a: ("manual:x", True))
    rc = C.main(["render", str(src), "--state", str(tmp_path / "st"), "--backend", "pseudo"])
    assert rc == 1 and "ERROR" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "posix", reason="POSIX semantics: an open file can be replaced")
def test_posix_open_reader_does_not_block_replace(batch, fonts_ready):
    """macOS/Linux: a viewer holding the old file does not prevent the atomic replace."""
    s, st, tm = batch["in"], batch["st"], batch["tm"]
    cli("plan", s, "--state", st, "--no-ocr", "--files", "table.pdf")
    cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 9999, "--files", "table.pdf")
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "table.pdf") == 0
    with open(st / "out" / "table.pdf", "rb"):
        assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "table.pdf") == 0
