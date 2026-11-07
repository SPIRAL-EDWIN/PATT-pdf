"""The OS boundary (src/patt_pdf/osenv.py), tested with injected platform values on every OS.

Findings from the Windows run of 6b969b8: W02 (escaped absolute paths in error JSON and
report), W04 (system font folder searched before the user font folder, listed twice),
W05 (classic MAX_PATH). Injected values are synthetic; only a run on Windows itself is
evidence for Windows.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from patt_pdf import osenv


# ---------------------------------------------------------------- W02 redaction
WIN_IN = "C:\\Users\\alice\\Documents\\PATT 测试 20261107\\输入 目录"


@pytest.mark.parametrize("msg,roots,want", [
    # as PyMuPDF reports it on Windows, then JSON-escaped (the exact W02 shape)
    ("FileDataError: Failed to open file 'C:\\\\Users\\\\alice\\\\Documents\\\\PATT 测试 20261107\\\\输入 目录\\\\truncated.pdf' as type pdf.",
     {"<input>": WIN_IN}, "FileDataError: Failed to open file '<input>/truncated.pdf' as type pdf."),
    # raw backslashes, subfolder kept
    ("cannot open " + WIN_IN + "\\sub\\a.pdf", {"<input>": WIN_IN}, "cannot open <input>/sub/a.pdf"),
    # different case of the drive/user part (Windows paths are case-insensitive)
    ("No such file: 'c:\\\\users\\\\ALICE\\\\in\\\\a.pdf'", {"<input>": "C:\\Users\\alice\\in"}, "No such file: '<input>/a.pdf'"),
    # unknown roots: only the file name survives
    ("open C:\\Users\\alice\\AppData\\Local\\Temp\\x.pdf: denied", {}, "open <path>/x.pdf: denied"),
    ("open C:/Users/alice/AppData/x.pdf", {}, "open <path>/x.pdf"),
    ("open D:\\PATT 测试\\state\\out\\t.pdf locked", {"<state>": "D:\\PATT 测试\\state"}, "open <state>/out/t.pdf locked"),
    ("open \\\\?\\C:\\very\\long\\folder\\f.pdf failed", {}, "open <path>/f.pdf failed"),
    ("open \\\\?\\UNC\\server\\share\\f.pdf failed", {}, "open <path>/f.pdf failed"),
    ("open \\\\server\\share\\dir\\f.pdf failed", {}, "open <path>/f.pdf failed"),
    # POSIX
    ("Failed to open file '/Users/alice/PATT 验证/in/t.pdf' as type pdf.", {}, "Failed to open file '<path>/t.pdf' as type pdf."),
    ("Failed to open file '/home/alice/in/sub/t.pdf'", {"<input>": "/home/alice/in"}, "Failed to open file '<input>/sub/t.pdf'"),
    # not paths: must be left alone
    ("ratio 3/4, https://example.com/a/b, doi:10.1/x, a/b/c, 2025-03-31", {}, "ratio 3/4, https://example.com/a/b, doi:10.1/x, a/b/c, 2025-03-31"),
])
def test_redact(msg, roots, want):
    assert osenv.redact(msg, roots) == want


def test_redact_leaves_no_drive_or_home(tmp_path):
    msgs = ["x 'C:\\\\Users\\\\bob\\\\a b\\\\c.pdf' y", "x /Users/bob/a/c.pdf y", "x /home/bob/c.pdf", "E:\\data\\c.pdf"]
    for m in msgs:
        r = osenv.redact(m)
        assert "bob" not in r and "C:" not in r and "E:" not in r and r.count("<path>/c.pdf") == 1, r


def test_w02_end_to_end_with_injected_windows_path(corpus, tmp_path, monkeypatch):
    """Inject the exact Windows message into planning; error JSON and report must be clean."""
    import shutil
    import patt_pdf.jobs as J
    from patt_pdf.report import markdown
    src = tmp_path / "in"; src.mkdir(); shutil.copy(corpus["src"] / "toc.pdf", src / "truncated.pdf")
    ws = J.Workspace(src, tmp_path / "st")
    win_abs = "C:\\\\Users\\\\<USER>\\\\Documents\\\\work\\\\PATT 测试 20261107\\\\输入 目录\\\\truncated.pdf"

    def failing_open(path, *a, **k):
        raise RuntimeError(f"FileDataError: Failed to open file '{win_abs}' as type pdf.")
    monkeypatch.setattr(J.pymupdf, "open", failing_open)
    st = J.plan_file(ws, "truncated.pdf", ocr=False)
    monkeypatch.undo()
    err = json.loads(ws.error_path("truncated.pdf").read_text(encoding="utf-8"))["error"]
    md = markdown(ws, ["truncated.pdf"])
    for text in (st["error"], err, md):
        assert "Users" not in text and "Documents" not in text and "C:" not in text, text
        assert "truncated.pdf" in text


# ---------------------------------------------------------------- W04 fonts
def test_windows_font_order_env_user_system_without_duplicates():
    env = {"PATT_PDF_FONT_SOURCE": "D:\\fonts;E:\\more", "LOCALAPPDATA": "C:\\Users\\a\\AppData\\Local",
           "WINDIR": "C:\\Windows"}
    d = [str(p) for p in osenv.font_search_dirs(env, "windows", home="C:\\Users\\a")]
    assert d[:2] == ["D:\\fonts", "E:\\more"]
    user = d.index(str(Path("C:\\Users\\a\\AppData\\Local") / "Microsoft" / "Windows" / "Fonts"))
    system = d.index(str(Path("C:\\Windows") / "Fonts"))
    assert user < system
    assert len(d) == len({os.path.normcase(x) for x in d})
    assert not any(x.startswith("/") for x in d)                  # no POSIX folders on Windows


def test_macos_and_linux_orders_user_before_system():
    mac = [str(p) for p in osenv.font_search_dirs({}, "macos", home="/Users/a")]
    assert mac.index("/Users/a/Library/Fonts") < mac.index("/Library/Fonts")
    lin = [str(p) for p in osenv.font_search_dirs({}, "linux", home="/home/a")]
    assert lin.index("/home/a/.local/share/fonts") < lin.index("/usr/share/fonts")
    for d in (mac, lin):
        assert len(d) == len(set(d)) and not any("Windows" in x for x in d)


def test_same_font_in_user_and_system_folder_user_wins(tmp_path, monkeypatch):
    """Actual hit, not just list order (W04): identical file name in both folders."""
    from patt_pdf import fonts
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir(); system.mkdir()
    (user / "NotoSansCJKsc-Regular.otf").write_bytes(b"user")
    (system / "NotoSansCJKsc-Regular.otf").write_bytes(b"system")
    (system / "NotoSansCJK-Regular.ttc").write_bytes(b"system-ttc")      # earlier in the preference list
    monkeypatch.setattr(fonts, "SYSTEM_DIRS", None)
    monkeypatch.setattr(osenv, "font_search_dirs", lambda *a, **k: [user, system])
    assert fonts.find_system_source(("sans", False)) == user / "NotoSansCJKsc-Regular.otf"


def test_env_source_beats_user_and_system(tmp_path, monkeypatch):
    from patt_pdf import fonts
    env_dir, user = tmp_path / "env", tmp_path / "user"
    env_dir.mkdir(); user.mkdir()
    (env_dir / "NotoSansSC-Regular.otf").write_bytes(b"env")
    (user / "NotoSansCJK-Regular.ttc").write_bytes(b"user")
    monkeypatch.setattr(fonts, "SYSTEM_DIRS", None)
    real = osenv.font_search_dirs
    monkeypatch.setattr(osenv, "font_search_dirs",
                        lambda *a, **k: [p for p in real({"PATT_PDF_FONT_SOURCE": str(env_dir)})][:1] + [user])
    assert fonts.find_system_source(("sans", False)) == env_dir / "NotoSansSC-Regular.otf"


# ---------------------------------------------------------------- Tesseract discovery
def test_tesseract_order_and_explicit_override_is_not_replaced(tmp_path):
    exe = tmp_path / "tess.exe"; exe.write_bytes(b"")
    env = {"PATT_PDF_TESSERACT": str(exe), "PATH": "", "ProgramFiles": str(tmp_path / "pf")}
    assert osenv.find_tesseract(env, "windows") == (str(exe), "PATT_PDF_TESSERACT")
    env["PATT_PDF_TESSERACT"] = str(tmp_path / "missing.exe")
    (tmp_path / "pf" / "Tesseract-OCR").mkdir(parents=True); (tmp_path / "pf" / "Tesseract-OCR" / "tesseract.exe").write_bytes(b"")
    found, why = osenv.find_tesseract(env, "windows")
    assert found is None and "PATT_PDF_TESSERACT" in why           # never silently uses another one
    env.pop("PATT_PDF_TESSERACT")
    assert osenv.find_tesseract(env, "windows")[1] == "ProgramFiles"


def test_conftest_uses_product_detection():
    """The test suite decides 'OCR available' exactly as the product does (review item)."""
    import conftest
    from patt_pdf.osenv import find_tesseract
    assert conftest.HAS_TESSERACT == (find_tesseract()[0] is not None)


# ---------------------------------------------------------------- W05 long paths
def test_long_path_diagnosis_only_when_it_applies():
    long = "C:\\" + "\\".join(["d" * 40] * 7) + "\\f.pdf"
    assert len(long) > 260
    msg = osenv.long_path_problem(long, "windows", long_paths_enabled=False)
    assert msg and "LongPathsEnabled" in msg and "\\\\?\\" in msg
    assert osenv.long_path_problem(long, "windows", long_paths_enabled=True) is None
    assert osenv.long_path_problem("\\\\?\\" + long, "windows", long_paths_enabled=False) is None
    assert osenv.long_path_problem("/" + "a" * 400, "linux") is None
    assert osenv.long_path_problem("C:\\short\\f.pdf", "windows", long_paths_enabled=False) is None


def test_extended_path_forms():
    if sys.platform == "win32":
        assert osenv.extended_path("C:\\a\\b").startswith("\\\\?\\C:\\")
    assert osenv.extended_path("\\\\?\\C:\\a") == "\\\\?\\C:\\a"
    assert osenv.extended_path("\\\\srv\\share\\a") == "\\\\?\\UNC\\srv\\share\\a"


def test_no_pdfs_found_explains_long_path(tmp_path, monkeypatch, capsys):
    """W05 symptom was 'no PDF files found': the CLI now names the path-length cause."""
    from patt_pdf import cli
    monkeypatch.setattr(osenv, "long_path_problem", lambda p, *a, **k: "path is 307 characters; LongPathsEnabled")
    (tmp_path / "in").mkdir()
    rc = cli.main(["plan", str(tmp_path / "in"), "--state", str(tmp_path / "st")])
    err = capsys.readouterr().err
    assert rc == 1 and "LongPathsEnabled" in err


def test_platform_info_is_complete():
    info = osenv.platform_info()
    assert {"os", "machine", "python", "locale_encoding", "filesystem_encoding", "utf8_mode"} <= set(info)
    assert info["os"] in ("linux", "macos", "windows") or info["os"]


# ---------------------------------------------------------------- doctor
def test_doctor_reports_without_changing_anything(tmp_path, monkeypatch, capsys):
    from patt_pdf import cli
    monkeypatch.setenv("PATT_PDF_FONT_DIR", str(tmp_path / "nofonts"))
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 2 and "fonts: 0/4" in out and "search order" in out
    assert not (tmp_path / "nofonts").exists()                     # read-only
    assert "locale_encoding" in out and "tesseract" in out


def test_editable_install_warning_for_non_ascii_source_and_legacy_locale():
    """macOS finding: editable install under a non-ASCII folder + ISO8859-1 locale cannot be
    imported (CPython's site.py reads .pth files with the locale encoding)."""
    w = osenv.install_warnings("/Users/a/PATT 验证/src/patt_pdf/osenv.py",
                               {"locale_encoding": "ISO8859-1", "utf8_mode": False, "os": "macos"})
    assert w and "pip install ." in w[0] and "PYTHONUTF8=1" in w[0]
    assert not osenv.install_warnings("/Users/a/PATT 验证/src/x.py", {"locale_encoding": "UTF-8", "os": "macos"})
    assert not osenv.install_warnings("/Users/a/src/x.py", {"locale_encoding": "ISO8859-1", "os": "macos"})


@pytest.mark.skipif(os.name != "posix", reason="needs a POSIX legacy locale to simulate")
def test_pth_with_non_ascii_path_is_decoded_with_locale_encoding(tmp_path):
    """Root-cause check for the macOS editable-install finding, independent of PATT-PDF:
    CPython's site.addpackage decodes .pth files with the locale encoding. A UTF-8 .pth that
    points to a non-ASCII folder is mis-decoded (wrong sys.path entry, or UnicodeDecodeError)
    under a legacy locale; PYTHONUTF8=1 fixes it. Skips if no legacy locale is installed."""
    import subprocess
    from test_encoding import _legacy_locales
    if sys.getfilesystemencoding().lower().replace("-", "") != "utf8":
        pytest.skip("parent process already runs in a legacy locale; the test sets the locale per child")
    names = _legacy_locales()
    if not names:
        pytest.skip("no non-UTF-8 locale installed")
    site_dir = tmp_path / "site"; site_dir.mkdir()
    pkg_root = tmp_path / "源码 目录"; (pkg_root / "pthprobe_pkg").mkdir(parents=True)
    (pkg_root / "pthprobe_pkg" / "__init__.py").write_text("OK = 1\n", encoding="utf-8")
    (site_dir / "probe.pth").write_bytes((str(pkg_root) + "\n").encode("utf-8"))
    code = ("import site, sys; site.addsitedir(sys.argv[1]); "
            "import importlib.util as u; print('found' if u.find_spec('pthprobe_pkg') else 'missing')")
    for name in names:
        base = dict(os.environ, LC_ALL=name)
        legacy = subprocess.run([sys.executable, "-c", code, str(site_dir)], capture_output=True,
                                env=dict(base, PYTHONUTF8="0"), timeout=60)
        utf8 = subprocess.run([sys.executable, "-c", code, str(site_dir)], capture_output=True,
                              env=dict(base, PYTHONUTF8="1"), timeout=60)
        assert b"found" not in legacy.stdout, (name, legacy.stdout, legacy.stderr[-300:])
        assert b"found" in utf8.stdout, (name, utf8.stdout, utf8.stderr[-300:])
