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
    user = d.index("C:\\Users\\a\\AppData\\Local\\Microsoft\\Windows\\Fonts")    # Windows rules on any host
    system = d.index("C:\\Windows\\Fonts")
    assert user < system
    import ntpath
    assert len(d) == len({ntpath.normcase(x) for x in d})
    assert not any(x.startswith("/") for x in d)                  # no POSIX folders on Windows


def _posix(paths):
    """Compare simulated macOS/Linux folders by their POSIX form, whatever the host is."""
    return [p.as_posix() for p in paths]


def test_macos_and_linux_orders_user_before_system():
    """Windows CI finding (ca38a93): on a Windows host the simulated macOS list contained
    '\\Users\\a\\Library\\Fonts' (host os.path + Path), so '/Users/a/Library/Fonts' was not found.
    Simulated folders must follow the TARGET OS's path rules on every host."""
    mac = _posix(osenv.font_search_dirs({}, "macos", home="/Users/a"))
    assert mac.index("/Users/a/Library/Fonts") < mac.index("/Library/Fonts")
    lin = _posix(osenv.font_search_dirs({}, "linux", home="/home/a"))
    assert lin.index("/home/a/.local/share/fonts") < lin.index("/usr/share/fonts")
    for d in (mac, lin):
        assert len(d) == len(set(d)) and not any("Windows" in x or "\\" in x for x in d)
        assert all(x.startswith("/") for x in d)


@pytest.mark.parametrize("host", ["posix", "nt"])
def test_simulated_os_paths_do_not_depend_on_the_host(monkeypatch, host):
    """Regression for the Windows CI failure: compute macOS/Linux/Windows lists while the host's
    os.path is posixpath or ntpath (simulated host); the result must be identical."""
    import ntpath
    import posixpath
    # only PATT-PDF's view of the host changes (pytest itself keeps the real os module)
    import types
    fake_os = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    fake_os.path, fake_os.name = (ntpath if host == "nt" else posixpath), host
    monkeypatch.setattr(osenv, "os", fake_os)
    monkeypatch.setattr(osenv, "_host_os", lambda: "windows" if host == "nt" else "linux")
    win_env = {"PATT_PDF_FONT_SOURCE": "D:\\fonts;d:\\FONTS", "LOCALAPPDATA": "C:\\Users\\a\\AppData\\Local",
               "WINDIR": "C:\\Windows"}
    assert [str(p) for p in osenv.font_search_dirs(win_env, "windows", home="C:\\Users\\a")] == [
        "D:\\fonts", "C:\\Users\\a\\AppData\\Local\\Microsoft\\Windows\\Fonts", "C:\\Windows\\Fonts"]
    assert _posix(osenv.font_search_dirs({}, "macos", home="/Users/a"))[:2] == ["/Users/a/Library/Fonts", "/Library/Fonts"]
    assert _posix(osenv.font_search_dirs({"XDG_DATA_HOME": "/x"}, "linux", home="/home/a"))[:2] == ["/x/fonts", "/home/a/.fonts"]


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
    for k in ("pth_strategy", "pth_locale_encoding", "site_frozen", "opencv:"):   # the retest prompts quote these
        assert k in out, k


def test_editable_install_warning_follows_the_pth_strategy():
    """macOS finding: editable install under a non-ASCII folder + ISO8859-1 locale on Python 3.11
    could not be imported. The warning depends on the interpreter's site.py strategy, not on its
    version, and no longer promises that PYTHONUTF8=1 fixes it (it does not on 3.11+)."""
    base = {"locale_encoding": "ISO8859-1", "pth_locale_encoding": "ISO8859-1", "utf8_mode": False, "os": "macos"}
    w = osenv.install_warnings("/Users/a/PATT 验证/src/patt_pdf/osenv.py", dict(base, pth_strategy="locale"))
    assert w and "pip install ." in w[0] and "not a reliable fix" in w[0]
    assert not osenv.install_warnings("/Users/a/PATT 验证/src/x.py", dict(base, pth_strategy="utf8-first"))
    # UTF-8 Mode on 3.11+ does not change the encoding site.py uses: still warn
    assert osenv.install_warnings("/Users/a/PATT 验证/src/x.py", dict(base, pth_strategy="locale", utf8_mode=True))
    assert not osenv.install_warnings("/Users/a/PATT 验证/src/x.py",
                                      dict(base, pth_strategy="locale", pth_locale_encoding="UTF-8"))
    assert not osenv.install_warnings("/Users/a/src/x.py", dict(base, pth_strategy="locale"))
    # Linux legacy locale without UTF-8 Mode: even a UTF-8-first site.py cannot help (real 3.12.16
    # under zh_CN.GBK: ModuleNotFoundError), because the path is re-encoded with the fs encoding
    lin = dict(base, os="linux", pth_strategy="utf8-first", filesystem_encoding="gbk")
    w = osenv.install_warnings("/home/a/PATT 验证/src/x.py", lin)
    assert len(w) == 1 and "file system encoding is gbk" in w[0] and "PYTHONUTF8=1" in w[0]
    assert not osenv.install_warnings("/home/a/PATT 验证/src/x.py", dict(lin, filesystem_encoding="utf-8"))
    assert not osenv.install_warnings("/home/a/src/x.py", lin)
    assert osenv.pth_strategy() in ("utf8-first", "locale", "unknown")
    assert "pth_strategy" in osenv.platform_info()


# How a UTF-8 .pth line reaches sys.path (Lib/site.py, addpackage) – established from the CPython
# sources, NOT from the major.minor version alone:
#   * Older site.py: io.TextIOWrapper(..., encoding="locale"). The "locale" encoding is
#     _Py_GetLocaleEncoding(): it ignores UTF-8 Mode on 3.11+ (3.10 returned UTF-8 in UTF-8 Mode),
#     so PYTHONUTF8=1 does NOT help there on 3.11.
#   * Newer site.py: decode("utf-8-sig") first, locale encoding only on UnicodeDecodeError. This
#     arrived in 3.13.0 AND was backported to 3.12.4 (Misc/NEWS: "site module now parses .pth file
#     with UTF-8 first"). Checked: v3.12.0-3.12.3 old, v3.12.4/.8/.10/.12/.14 new, v3.11.9-3.11.16
#     old, v3.10.12 old. Distributions may patch either way.
# So the test asks the running interpreter which strategy its site.addpackage uses (string
# constants of the loaded code object: on 3.11+ release builds `site` is FROZEN, so
# inspect.getsource() fails there; found when running real 3.11.18/3.12.16 builds), and which encodings its "locale" text wrapper and file system really use, then
# predicts found / missing / error from that. Review findings that motivated this: macOS 3.12.14
# found the package under zh_CN.GBK (backport), macOS 3.11.16 failed even with PYTHONUTF8=1.
_PTH_CHILD = (
    "import io, sys, site, importlib.util as u\n"
    "def consts(co, d=0):\n"
    "    for c in co.co_consts:\n"
    "        if isinstance(c, str): yield c\n"
    "        elif hasattr(c, 'co_consts') and d < 4: yield from consts(c, d + 1)\n"
    "k = set(consts(site.addpackage.__code__))\n"
    "strat = 'utf8-first' if 'utf-8-sig' in k else ('locale' if 'locale' in k else 'unknown')\n"
    "frozen = str(site.addpackage.__code__.co_filename.startswith('<frozen'))\n"
    "enc = io.TextIOWrapper(io.BytesIO(), encoding='locale').encoding\n"
    "try:\n"
    "    import locale; genc = locale.getencoding()\n"
    "except AttributeError:\n"
    "    genc = enc\n"
    "try:\n"
    "    site.addsitedir(sys.argv[1]); r = 'found' if u.find_spec('pthprobe_pkg') else 'missing'\n"
    "except Exception as e:\n"
    "    r = 'error:' + type(e).__name__\n"
    "print('|'.join([strat, enc, genc, sys.getfilesystemencoding(), str(sys.flags.utf8_mode),\n"
    "                sys.version.split()[0], frozen, r]))\n")


def _expected_pth_result(strategy: str, locale_enc: str, utf8_path: bytes, fs_enc: str = "utf-8") -> str:
    """found / missing / error / unknown for a .pth line `utf8_path` (UTF-8 bytes).

    strategy: 'utf8-first' (site.py tries utf-8-sig, then the locale encoding) or 'locale'
    (decodes with the locale encoding only), as reported by the interpreter itself."""
    try:
        if strategy == "utf8-first":
            try:
                text = utf8_path.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = utf8_path.decode(locale_enc)
        elif strategy == "locale":
            text = utf8_path.decode(locale_enc)
        else:
            return "unknown"
    except UnicodeDecodeError:
        return "error"
    except LookupError:
        return "unknown"
    try:
        back = text.encode(fs_enc, "surrogateescape")
    except (UnicodeEncodeError, LookupError):
        return "missing"
    return "found" if back == utf8_path else "missing"


def _pth_fixture(tmp_path):
    site_dir = tmp_path / "site"; site_dir.mkdir()
    pkg_root = tmp_path / "源码 目录"; (pkg_root / "pthprobe_pkg").mkdir(parents=True)
    (pkg_root / "pthprobe_pkg" / "__init__.py").write_text("OK = 1\n", encoding="utf-8")
    line = str(pkg_root).encode("utf-8")
    (site_dir / "probe.pth").write_bytes(line + b"\n")          # exactly what setuptools writes: UTF-8
    return site_dir, line


def _run_pth_child(site_dir, env):
    import subprocess
    # -S: the child must not process this environment's own .pth files at start-up (an editable
    # install from a non-ASCII folder would abort it); it imports site and runs addsitedir itself
    r = subprocess.run([sys.executable, "-S", "-c", _PTH_CHILD, str(site_dir)], capture_output=True, env=env, timeout=60)
    parts = r.stdout.decode("ascii", "replace").strip().split("|")
    if len(parts) != 8:
        pytest.fail(f"child crashed: {r.stderr.decode('ascii', 'replace')[-300:]}")
    return dict(zip(("strategy", "enc", "getencoding", "fs", "utf8_mode", "python", "frozen", "result"), parts))


@pytest.mark.skipif(os.name != "posix", reason="POSIX locale simulation (Windows: see the Windows retest prompt)")
def test_pth_decoding_matches_the_interpreters_own_rule(tmp_path):
    """For every available locale and UTF-8 Mode off/on, the real outcome of site.addsitedir on a
    UTF-8 .pth pointing to a non-ASCII folder must equal the prediction from the interpreter's own
    strategy and encodings. Nothing is assumed per Python version; every observation is printed."""
    from test_encoding import _legacy_locales
    if sys.getfilesystemencoding().lower().replace("-", "") != "utf8":
        pytest.skip("parent process already runs in a legacy locale; the test sets the locale per child")
    site_dir, line = _pth_fixture(tmp_path)
    observed = []
    for name in ["C.UTF-8"] + _legacy_locales():
        for utf8 in ("0", "1"):
            c = _run_pth_child(site_dir, dict(os.environ, LC_ALL=name, PYTHONUTF8=utf8))
            want = _expected_pth_result(c["strategy"], c["enc"], line, c["fs"])
            observed.append((name, f"UTF8={utf8}", c["python"], c["strategy"], f"frozen={c['frozen']}", c["enc"],
                             c["getencoding"], c["fs"], c["result"], want))
            # an unrecognised site.py is a finding to report, not something to pass silently
            assert want != "unknown", ("cannot classify this interpreter's site.addpackage", observed)
            assert c["result"].split(":")[0] == want, observed
    assert observed[0][8] == "found", observed                      # C.UTF-8 must always work
    print("pth decoding (locale, mode, python, strategy, site, locale-enc, getencoding, fs-enc, result, expected):")
    for o in observed:
        print("   ", o)


def test_expected_pth_rule_follows_the_strategy_not_the_version():
    p = "/x/源码/a".encode("utf-8")
    assert _expected_pth_result("locale", "UTF-8", p) == "found"
    assert _expected_pth_result("locale", "ISO8859-1", p) == "missing"      # decodes to the wrong path
    assert _expected_pth_result("locale", "CP1252", p) == "error"           # 0x90/0x81 undefined
    assert _expected_pth_result("locale", "GBK", p) == "missing"            # decodes to the wrong path
    for enc in ("ISO8859-1", "GBK", "CP1252"):                              # 3.12.4+ / 3.13+: UTF-8 first
        assert _expected_pth_result("utf8-first", enc, p) == "found"
    assert _expected_pth_result("utf8-first", "UTF-8", p, "gbk") == "missing"   # Linux legacy fs encoding
    assert _expected_pth_result("unknown", "GBK", p) == "unknown"


def test_pth_strategy_detection_on_this_interpreter():
    """The detection must classify this interpreter from the code that actually runs, also when
    `site` is frozen (3.11+ release builds, where inspect.getsource() raises OSError). If the
    site.py file is readable, its addpackage source must agree. Prints a line for retest reports."""
    import ast
    import site
    strat = osenv.pth_strategy()
    frozen = osenv.site_is_frozen()
    tail = "/".join(Path(site.__file__).parts[-2:])           # e.g. python3.12/site.py: no local path in reports
    print("site.addpackage strategy:", strat, "python", sys.version.split()[0], "frozen", frozen, "site", tail)
    assert strat in ("utf8-first", "locale"), strat
    try:
        text = open(site.__file__, encoding="utf-8").read()
    except (OSError, TypeError, UnicodeDecodeError):
        text = None
    if text:
        fn = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "addpackage")
        src = ast.get_source_segment(text, fn)
        assert ("utf-8-sig" in src) == (strat == "utf8-first"), (strat, site.__file__)
    if sys.version_info >= (3, 13):
        assert strat == "utf8-first"           # documented in the 3.13 site docs ("Changed in version 3.13")
    if sys.version_info[:2] <= (3, 11):
        assert strat == "locale" or "utf-8-sig" in src   # upstream 3.10/3.11 never had it; a patched build may


# ---------------------------------------------------------------- redaction: arbitrary paths, end-to-end
@pytest.mark.parametrize("msg,want", [
    ("open failed: /custom/private/report.pdf", "open failed: <path>/report.pdf"),        # independent review
    ("cache /opt2/cache/u/x.bin", "cache <path>/x.bin"),
    ("[Errno 13] Permission denied: '/data/projects/客户 A/q3 report.pdf'", "[Errno 13] Permission denied: '<path>/q3 report.pdf'"),
    ("error in /home/bob/My Files/a b.pdf: denied", "error in <path>/a b.pdf: denied"),
    ("see ~/Library/Fonts/a.otf now", "see <path>/a.otf now"),
    ("file:///etc/private/b.pdf x", "<path>/b.pdf x"),
    ("file:///C:/Users/bob/a.pdf", "<path>/a.pdf"),
    ("file://server/share/a.pdf", "<path>/a.pdf"),
    ("Failed /a/b/c.pdf, then /d/e/f.pdf.", "Failed <path>/c.pdf, then <path>/f.pdf."),
    # must stay unchanged
    ("https://example.com/a/b and ftp://h/a/b", "https://example.com/a/b and ftp://h/a/b"),
    ("ratio 3/4, and/or, a/b/c, 2025/03/31, km/h, N/A, I/O, 1/2/3", "ratio 3/4, and/or, a/b/c, 2025/03/31, km/h, N/A, I/O, 1/2/3"),
    ("doi:10.0000/example.2026.001", "doi:10.0000/example.2026.001"),
    ("single /x and /etc", "single /x and /etc"),
    # single-segment root paths: only when quoted as a whole or with a file extension
    ("[Errno 2] No such file or directory: '/privatefile'", "[Errno 2] No such file or directory: '<path>/privatefile'"),
    ("error at /report.pdf: denied", "error at <path>/report.pdf: denied"),
    ("open failed: /privatefile", "open failed: /privatefile"),          # documented gap: ambiguous with prose
    ("Use /help for help; version 1.2/3.4; size 3/4.5", "Use /help for help; version 1.2/3.4; size 3/4.5"),
])
def test_redact_arbitrary_absolute_paths(msg, want):
    assert osenv.redact(msg) == want
    assert osenv.redact(want) == want                                   # idempotent on redacted text


def _plan_with_failing_open(src, st, message, monkeypatch):
    import patt_pdf.jobs as J
    from patt_pdf.cli import main
    monkeypatch.setattr(J.pymupdf, "open", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(message)))
    rc = main(["plan", str(src), "--state", str(st), "--no-ocr"])
    monkeypatch.undo()
    return rc


def test_custom_mount_path_never_reaches_cli_json_or_report(tmp_path, capsys, monkeypatch):
    """Exception text -> CLI output, state JSON (errors and plans), report: all redacted."""
    from patt_pdf.cli import main
    src = tmp_path / "in"; src.mkdir(); (src / "a.pdf").write_bytes(b"%PDF-1.4 broken")
    st = tmp_path / "st"
    msg = ("open failed: /custom/private/report.pdf; also C:\\\\Users\\\\bob\\\\x.pdf, \\\\\\\\nas\\\\share\\\\y.pdf, "
           f"\\\\\\\\?\\\\D:\\\\deep\\\\z.pdf and {tmp_path}/in/a.pdf")
    assert _plan_with_failing_open(src, st, msg, monkeypatch) == 1
    assert main(["report", str(src), "--state", str(st), "--out", str(tmp_path / "r.md")]) == 0
    texts = {"cli": capsys.readouterr(), "report": (tmp_path / "r.md").read_text(encoding="utf-8")}
    # "wrote <--out>" echoes the path the user typed on their own terminal; it is not in shared files
    texts["cli"] = "\n".join(l for l in (texts["cli"].out + texts["cli"].err).splitlines() if not l.startswith("wrote "))
    for p in st.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".jsonl"):
            texts[p.name] = p.read_text(encoding="utf-8")
    for name, t in texts.items():
        for leak in ("/custom/", "private", "Users", "bob", "nas", "deep", str(tmp_path)):
            assert leak not in t, (name, leak, t[:400])
    assert "<input>/a.pdf" in texts["a.pdf.error.json"]


def test_redaction_keeps_cli_messages_useful(tmp_path, capsys, monkeypatch):
    src = tmp_path / "in"; src.mkdir(); (src / "a.pdf").write_bytes(b"x")
    _plan_with_failing_open(src, tmp_path / "st", "cannot open /mnt/x/y/a.pdf: Permission denied", monkeypatch)
    out = capsys.readouterr().out
    assert "a.pdf" in out and "Permission denied" in out and "<path>/a.pdf" in out and "/mnt/x" not in out
