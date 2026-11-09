"""Standard OCR installation and page routing."""
import subprocess
from types import SimpleNamespace

import pymupdf

from patt_pdf import analyze, ocr


def test_text_page_is_extracted_without_ocr(monkeypatch):
    def unexpected_ocr(*args, **kwargs):
        raise AssertionError("ordinary text extraction must not invoke OCR")

    monkeypatch.setattr(ocr, "_tesseract_multi", unexpected_ocr)
    monkeypatch.setattr(ocr, "plan_ocr_page", unexpected_ocr)
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Hello world")
        plan = analyze.plan_page(page, 0)
    assert plan.kind == "text"
    assert plan.units


def test_raster_page_uses_ocr(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(analyze, "classify_page", lambda page: "raster")
    monkeypatch.setattr(ocr, "ocr_dependency_problem", lambda: None)
    monkeypatch.setattr(ocr, "plan_ocr_page", lambda page, pno, kind: sentinel)
    assert analyze.plan_page(object(), 0) is sentinel


def test_tesseract_language_check(monkeypatch):
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="List of available languages (1):\neng\n"))
    assert ocr.tesseract_language_problem("tesseract") is None
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="List of available languages (1):\nchi_sim\n"))
    assert "eng" in ocr.tesseract_language_problem("tesseract")
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 15)
    monkeypatch.setattr(ocr.subprocess, "run", timed_out)
    assert "cannot check" in ocr.tesseract_language_problem("tesseract")
