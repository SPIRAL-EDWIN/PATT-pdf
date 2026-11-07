"""Text encoding contract: everything PATT-PDF reads or writes as text is UTF-8, independent of
the platform default (cp1252 / cp936 on many Windows systems, a legacy locale on POSIX).

Review finding (Windows acceptance, v0.3.0.dev0 candidate 93ee393): tests/conftest.py read the
UTF-8 truth.json with the platform default encoding, so "¥9,870" became mojibake (or
UnicodeDecodeError) and offline tests failed for reasons unrelated to the code under test.
"""
from __future__ import annotations

import ast
import locale
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "fixtures" / "encoding_probe.py"


# ---------------------------------------------------------------- static contract
def _binary_mode(call):
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for k in call.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            mode = k.value.value
    return isinstance(mode, str) and "b" in mode


def implicit_encoding_calls(root: Path) -> list[str]:
    """Text-mode file I/O without an explicit encoding= in Python sources under `root`."""
    bad = []
    for p in sorted(root.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            kws = {k.arg for k in n.keywords}
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
            where = f"{p.relative_to(ROOT).as_posix()}:{n.lineno}"
            if name in ("read_text", "write_text") and "encoding" not in kws and owner != "tw":   # tw: PyMuPDF TextWriter
                bad.append(f"{where} {name}()")
            elif name == "open" and (isinstance(f, ast.Name) or owner == "io") and "encoding" not in kws \
                    and not _binary_mode(n):
                bad.append(f"{where} open()")
            elif name == "fdopen" and "encoding" not in kws and not _binary_mode(n):
                bad.append(f"{where} fdopen()")
            elif owner == "subprocess" and name in ("run", "check_output", "Popen") and "encoding" not in kws \
                    and any(k.arg in ("text", "universal_newlines") for k in n.keywords):
                bad.append(f"{where} subprocess text mode")
    return bad


def test_text_io_declares_encoding():
    bad = implicit_encoding_calls(ROOT / "src") + implicit_encoding_calls(ROOT / "tests")
    assert not bad, "text I/O without explicit encoding:\n" + "\n".join(bad)


def test_static_check_catches_the_original_defect(tmp_path, monkeypatch):
    """The checker itself must flag the pattern found in review."""
    (tmp_path / "x.py").write_text('import json\njson.loads((d / "truth.json").read_text())\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert implicit_encoding_calls(tmp_path) == ["x.py:2 read_text()"]


# ---------------------------------------------------------------- dynamic: child processes
def _run_probe(extra_env, fonts_dir):
    env = dict(os.environ, PYTHONUTF8="0", PATT_PDF_FONT_DIR=str(fonts_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT / "src")] + [p for p in sys.path if p]))
    env.pop("PYTHONIOENCODING", None)
    env.update(extra_env)
    # -X warn_default_encoding (Python 3.10+): any implicit default-encoding use in PATT-PDF
    # code is reported by the probe with file and line and fails it (exit 2), even where the
    # default happens to be UTF-8. Warnings from the standard library are listed, not failed.
    r = subprocess.run([sys.executable, "-X", "warn_default_encoding", str(PROBE)], capture_output=True,
                       env=env, timeout=300)
    out = (r.stdout + r.stderr).decode("ascii", "backslashreplace")
    return r.returncode, out


def test_pipeline_with_platform_default_encoding(fonts_ready):
    """UTF-8 mode off: on Windows this runs with the real ANSI code page (cp1252, cp936 …)."""
    rc, out = _run_probe({}, fonts_ready)
    assert rc == 0 and "OK" in out, out[-3000:]


def _legacy_locales():
    if os.name != "posix":
        return []
    found = []
    for groups in (("zh_CN.GBK", "zh_CN.gbk", "zh_CN.GB18030", "zh_CN.gb18030"),
                   ("en_US.CP1252", "en_US.ISO8859-1", "en_US.ISO-8859-1", "en_US.iso88591")):
        for name in groups:
            try:
                r = subprocess.run([sys.executable, "-c", "import locale; locale.setlocale(locale.LC_ALL, '');"
                                    "print(locale.getpreferredencoding(False))"],
                                   env=dict(os.environ, LC_ALL=name, PYTHONUTF8="0"), capture_output=True,
                                   timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                continue
            enc = r.stdout.decode("ascii", "replace").strip().lower().replace("-", "")
            if r.returncode == 0 and enc and enc not in ("utf8", "ascii", "ansi_x3.41968"):
                found.append(name); break
    return found


@pytest.mark.skipif(os.name != "posix", reason="POSIX locale simulation; Windows uses its real code page above")
def test_pipeline_in_legacy_posix_locales(fonts_ready):
    """Simulate a non-UTF-8 default (GBK and/or a Western code page) where such locales exist."""
    names = _legacy_locales()
    if not names:
        pytest.skip("no non-UTF-8 locale installed (e.g. zh_CN.GBK, en_US.ISO8859-1)")
    for name in names:
        rc, out = _run_probe({"LC_ALL": name}, fonts_ready)
        assert rc == 0 and "OK" in out, f"[{name}] " + out[-3000:]


def test_probe_detects_implicit_encoding_in_project_code(fonts_ready, monkeypatch, tmp_path):
    """The probe must still catch the review's original defect (no more 'green by deletion')."""
    import shutil as _sh
    root = tmp_path / "proj"
    _sh.copytree(ROOT / "src", root / "src"); _sh.copytree(ROOT / "tests" / "fixtures", root / "tests" / "fixtures")
    mf = root / "tests" / "fixtures" / "make_fixtures.py"
    t = mf.read_text(encoding="utf-8")
    bad = t.replace('json.loads(Path(path).read_text(encoding="utf-8"))', 'json.loads(Path(path).read_text())')
    assert bad != t
    mf.write_text(bad, encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="0", PATT_PDF_FONT_DIR=str(fonts_ready),
               PYTHONPATH=os.pathsep.join([str(root / "src")] + [p for p in sys.path
                                                                if p and Path(p).resolve() != (ROOT / "src").resolve()]))
    r = subprocess.run([sys.executable, "-X", "warn_default_encoding", str(root / "tests" / "fixtures" / "encoding_probe.py")],
                       capture_output=True, env=env, timeout=300)
    out = (r.stdout + r.stderr).decode("ascii", "backslashreplace")
    # detected either by the warning report (names the file) or, where the default encoding cannot
    # decode the data, by the content check that runs first; both mean the defect is caught
    assert r.returncode != 0 and ("make_fixtures.py" in out or "decoded wrongly" in out), out[-2000:]


def test_stdlib_encoding_warning_does_not_abort_probe(fonts_ready):
    """W01 / macOS: on Python 3.11+ locale.getpreferredencoding() itself warns. Simulated here on
    every Python version with a sitecustomize helper; the probe must still run the pipeline."""
    helper = ROOT / "tests" / "fixtures" / "py311_locale_warning"
    rc, out = _run_probe({"PYTHONPATH": os.pathsep.join([str(helper), str(ROOT / "src")] + [p for p in sys.path if p])},
                         fonts_ready)
    assert rc == 0 and "OK" in out, out[-3000:]
    assert "locale.py" in out                                   # the stdlib warning is reported, not hidden


def test_probe_does_not_fail_on_stdlib_warnings(monkeypatch):
    """A warning raised inside the standard library (e.g. locale) is listed, not failed."""
    sys.path.insert(0, str(PROBE.parent))
    try:
        import importlib
        probe = importlib.import_module("encoding_probe")
        assert probe._own(str(ROOT / "src" / "patt_pdf" / "jobs.py"))
        assert probe._own(str(PROBE))
        assert not probe._own(locale.__file__)
    finally:
        sys.path.remove(str(PROBE.parent))


def test_current_default_encoding_is_reported():
    """Not an assertion about correctness: records what the platform default is in -rA output."""
    getenc = getattr(locale, "getencoding", None)      # 3.11+: does not emit EncodingWarning
    print("default text encoding:", getenc() if getenc else locale.getpreferredencoding(False),
          "utf8_mode:", sys.flags.utf8_mode)


def test_undecodable_file_names_do_not_crash_state_writes(tmp_path):
    """POSIX with a legacy locale lists some names with surrogate escapes; state and run logs
    must still be written (as JSON escapes that read back to the same string)."""
    import json
    from patt_pdf.jobs import Workspace, _log_run, atomic_write_text
    name = "r\udce9sum\udce9.pdf"
    atomic_write_text(tmp_path / "x.json", json.dumps({"rel": name}, ensure_ascii=False))
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))["rel"] == name
    (tmp_path / "in").mkdir()
    ws = Workspace(tmp_path / "in", tmp_path / "st"); ws.state.mkdir(parents=True, exist_ok=True)
    _log_run(ws, {"skipped_unreadable": [name]})
    assert json.loads((ws.state / "runs.jsonl").read_text(encoding="utf-8"))["skipped_unreadable"] == [name]
