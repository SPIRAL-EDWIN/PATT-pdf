"""P1-3: OCR robustness, encrypted/unicode inputs, tables, key handling, font discovery."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

import numpy as np
import pymupdf
import pytest

from fakes import FakeMT
from patt_pdf.cli import main


def cli(*a):
    return main([str(x) for x in a])


def test_encrypted_pdf_is_reported(corpus, tmp_path):
    from patt_pdf.jobs import Workspace, plan_file
    ws = Workspace(corpus["src"], tmp_path)
    st = plan_file(ws, "encrypted.pdf")
    assert st["status"] == "error" and "encrypted" in st["error"]


NON_UTF8_FS = pytest.mark.skipif(
    sys.getfilesystemencoding().lower().replace("-", "") != "utf8",
    reason="POSIX file system encoding is not UTF-8 (legacy locale): MuPDF uses UTF-8 file names, so "
           "non-ASCII file names are unsupported there (Windows and macOS are always UTF-8)")


@NON_UTF8_FS
def test_unicode_filename_roundtrip(corpus, fonts_ready, tmp_path):
    from patt_pdf.jobs import Workspace, plan_file, publish, render_file, translate
    name = "报告 2026 – résumé.pdf"
    ws = Workspace(corpus["src"], tmp_path / "state")
    assert plan_file(ws, name, ocr=False)["status"] == "planned"
    fake = FakeMT(); translate(ws, [name], fake, max_chars=999)
    assert render_file(ws, name, fake.namespace)["status"] == "pass"
    r = publish(ws, [name], tmp_path / "out dir 输出", suffix=" zh-Hans")
    assert r[0]["published"] and os.path.exists(r[0]["to"])


def test_table_figures_kept(corpus, fonts_ready, tmp_path):
    """Currency, percentages in parentheses, negative %, dates in a ruled table stay identical."""
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    ws = Workspace(corpus["src"], tmp_path)
    plan_file(ws, "table.pdf", ocr=False)
    fake = FakeMT(); translate(ws, ["table.pdf"], fake, max_chars=9999)
    q = render_file(ws, "table.pdf", fake.namespace)
    assert q["status"] == "pass", q["pages"][0]["issues"]
    src, out = corpus["src"] / "table.pdf", ws.out_path("table.pdf")
    with pymupdf.open(src) as s, pymupdf.open(out) as o:
        for t in corpus["truth"]["table"]["keep"]:
            rs = s[0].search_for(t)
            assert rs, t
            a = s[0].get_pixmap(dpi=110, clip=rs[0]); b = o[0].get_pixmap(dpi=110, clip=rs[0])
            assert np.abs(np.frombuffer(a.samples, np.uint8).astype(int)
                          - np.frombuffer(b.samples, np.uint8).astype(int)).max() == 0, t
        assert "Monthly visits" not in o[0].get_text() and "每月" not in s[0].get_text()


def test_ocr_missing_executable_is_reported_not_crash(corpus, tmp_path, monkeypatch):
    from patt_pdf.jobs import Workspace, plan_file
    monkeypatch.setenv("PATT_PDF_TESSERACT", str(tmp_path / "no-such-tesseract"))
    monkeypatch.setenv("PATH", "")
    ws = Workspace(corpus["src"], tmp_path / "s")
    st = plan_file(ws, "scanned.pdf", ocr=True)
    assert st["status"] == "planned"
    plan = json.loads(ws.plan_path("scanned.pdf").read_text(encoding="utf-8"))
    note = plan["pages"][0]["notes"][0]["skipped"]
    assert "OCR" in note


def test_ocr_timeout_is_enforced(monkeypatch):
    import patt_pdf.ocr as O
    monkeypatch.setattr(O, "OCR_TIMEOUT_S", 0.01)
    monkeypatch.setattr(O, "tesseract_cmd", lambda: "x")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=0.01)
    monkeypatch.setattr(O.subprocess, "run", slow)
    with pytest.raises(O.OCRUnavailable, match="timed out"):
        O._tesseract(b"png")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_key_save_is_private_and_never_printed(tmp_path, capsys, monkeypatch):
    import io
    key = "11111111-2222-3333-4444-555555555555:fx"
    monkeypatch.setattr("sys.stdin", io.StringIO(key + "\n"))
    p = tmp_path / "cfg" / "deepl.key"
    assert cli("key", "save", "--path", p) == 0
    out = capsys.readouterr()
    assert key not in out.out + out.err
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    monkeypatch.setattr("sys.stdin", io.StringIO(key + "\n"))
    assert cli("key", "save", "--path", p) == 1                        # never overwrites
    monkeypatch.setattr("sys.stdin", io.StringIO("not-a-key\n"))
    assert cli("key", "save", "--path", tmp_path / "k2") == 1
    assert not (tmp_path / "k2").exists()


def test_font_search_is_configurable_and_errors_clearly(tmp_path, monkeypatch):
    from patt_pdf import fonts
    monkeypatch.setenv("PATT_PDF_FONT_SOURCE", str(tmp_path / "none"))
    monkeypatch.setattr(fonts, "SYSTEM_DIRS", [])
    rep = fonts.install_fonts(tmp_path / "f")
    assert all(v.startswith("MISSING") and "PATT_PDF_FONT_SOURCE" in v for v in rep.values())
    monkeypatch.setenv("PATT_PDF_FONT_DIR", str(tmp_path / "empty"))
    with pytest.raises(fonts.FontsMissing, match="PATT_PDF_FONT_DIR"):
        fonts.face_path("sans", False)


# PYTHONIOENCODING values: ":surrogateescape" is what CPython uses BY DEFAULT for stdout/stderr on
# Windows (Python/initconfig.c, config_get_stdio_errors), so "cp1252:surrogateescape" reproduces a
# piped Windows console exactly. v0.3.4 (ca38a93) tested only "cp1252" (= strict on POSIX) and
# failed on all three Windows CI jobs with UnicodeEncodeError: 'charmap'.
@NON_UTF8_FS
@pytest.mark.parametrize("ioenc", ["cp1252", "cp1252:surrogateescape", "cp936:surrogateescape"])
def test_legacy_console_encoding_does_not_abort(corpus, tmp_path, ioenc):
    """A legacy code page console (common on Windows when output is piped) must not crash on CJK names."""
    env = dict(os.environ, PYTHONIOENCODING=ioenc,
               PYTHONPATH=os.pathsep.join([str(p) for p in sys.path if p]))
    env.pop("PYTHONUTF8", None)
    r = subprocess.run([sys.executable, "-X", "utf8=0", "-m", "patt_pdf.cli", "plan", str(corpus["src"]),
                        "--state", str(tmp_path / "s"), "--no-ocr", "--files", "报*"],
                       capture_output=True, env=env, timeout=120)
    enc = ioenc.split(":")[0]
    out = r.stdout.decode(enc, "replace") + r.stderr.decode(enc, "replace")
    assert r.returncode == 0, out
    assert "planned" in out and "UnicodeEncodeError" not in out
    assert "sum" in out                                   # the file-name line itself was printed


def test_safe_console_replaces_strict_and_surrogateescape_but_not_utf8():
    import io
    from patt_pdf import cli

    def stream(enc, err):
        return io.TextIOWrapper(io.BytesIO(), encoding=enc, errors=err)
    cases = {("cp1252", "strict"): "backslashreplace", ("cp1252", "surrogateescape"): "backslashreplace",
             ("cp936", "surrogateescape"): "backslashreplace", ("cp1252", "replace"): "replace",
             ("utf-8", "surrogateescape"): "surrogateescape", ("utf-8", "strict"): "strict"}
    old = sys.stdout, sys.stderr
    try:
        for (enc, err), want in cases.items():
            sys.stdout, sys.stderr = stream(enc, err), stream(enc, err)
            cli._safe_console()
            got = (sys.stdout.errors, sys.stderr.errors)
            if enc != "utf-8":
                print("\u62a5\u544a 2026 \u2013 r\xe9sum\xe9.pdf", file=sys.stdout)   # must not raise
            sys.stdout, sys.stderr = old
            assert got == (want, want), (enc, err, got)
    finally:
        sys.stdout, sys.stderr = old


def test_locked_target_gives_clear_error_and_no_temp_left(tmp_path, monkeypatch):
    """Simulates Windows' PermissionError on os.replace when the output PDF is open."""
    import patt_pdf.jobs as J
    target = tmp_path / "out.pdf"; target.write_bytes(b"old")
    tmp = tmp_path / ".tmp-x.pdf"; tmp.write_bytes(b"new")

    def locked(a, b):
        raise PermissionError(13, "The process cannot access the file")
    monkeypatch.setattr(J.os, "replace", locked)
    with pytest.raises(PermissionError, match="in use"):
        J.replace_file(tmp, target)
    assert target.read_bytes() == b"old" and not tmp.exists()
