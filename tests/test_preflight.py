"""tools/preflight.py: diagnosing an environment in which patt_pdf (and `patt-pdf doctor`) cannot run.

macOS retest M3 (v0.3.5): editable install from a non-ASCII folder, Python 3.11, legacy locale
(en_US.ISO8859-1 / zh_CN.GBK) -> `import patt_pdf` fails or the interpreter does not start, so
`python -m patt_pdf.cli doctor` cannot print its warning. These tests build a small venv whose
`.pth` points to a non-ASCII folder (exactly what an editable install writes) and check, for every
locale available on this machine, that the preflight's verdict equals what the interpreter really
does. Nothing is predicted per Python version.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "tools" / "preflight.py"


@pytest.fixture(scope="module")
def fake_editable_env(tmp_path_factory):
    """A venv without pip plus a `.pth` line pointing to `<tmp>/源码 目录` which contains a stub
    `patt_pdf` package: the same files an editable install from a non-ASCII folder produces."""
    base = tmp_path_factory.mktemp("pf")
    src = base / "源码 目录"; (src / "patt_pdf").mkdir(parents=True)
    (src / "patt_pdf" / "__init__.py").write_text("__version__ = 'stub-editable'\n", encoding="utf-8")
    vdir = base / "venv"
    venv.EnvBuilder(with_pip=False, symlinks=(os.name != "nt")).create(vdir)
    py = vdir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    sp = subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.strip()
    (Path(sp) / "__editable__.patt_pdf_stub-0.pth").write_bytes(str(src).encode("utf-8") + b"\n")
    return {"python": py, "site": Path(sp), "src": src}


def _preflight(py, env):
    r = subprocess.run([sys.executable, "-S", str(PREFLIGHT), "--python", str(py), "--json"],
                       capture_output=True, env=env, timeout=120)
    assert r.stdout, r.stderr.decode("utf-8", "backslashreplace")[-800:]
    return r.returncode, json.loads(r.stdout.decode("ascii"))


def _actual(py, env):
    started = subprocess.run([str(py), "-c", "pass"], capture_output=True, env=env, timeout=60).returncode == 0
    imp = subprocess.run([str(py), "-c", "import patt_pdf"], capture_output=True, env=env, timeout=60)
    return started, imp.returncode == 0


def _consistent(py, env, label):
    rc, res = _preflight(py, env)
    started, imported = _actual(py, env)
    c = res["checks"]
    assert c["interpreter_runs_with_-S"] == "OK", (label, res)
    assert c["interpreter_starts_normally"].startswith("OK") == started, (label, res)
    assert c["import_patt_pdf"].startswith("OK") == imported, (label, res)
    assert (rc == 0) == imported, (label, rc, res)                      # exit 1 exactly when broken
    pth = [p for p in res["pth"] if p["file"].startswith("__editable__.patt_pdf_stub")]
    assert len(pth) == 1, (label, res)
    assert (pth[0]["predicted"] == "found") == imported, (label, res)   # prediction == reality
    if not imported:
        assert res["recovery"] and "REGULAR install" in res["recovery"][0], res
        if res["facts"]["strategy"] == "locale":
            assert any("PYTHONUTF8=1 is NOT a fix" in s for s in res["recovery"]), res
    return {"label": label, "python": res["facts"]["python"], "strategy": res["facts"]["strategy"],
            "locale_enc": res["facts"]["locale_text_encoding"], "fs": res["facts"]["fs_encoding"],
            "started": started, "imported": imported, "predicted": pth[0]["predicted"], "exit": rc}


def test_preflight_runs_without_patt_pdf_and_matches_reality_in_the_default_locale(fake_editable_env):
    """Runs on every OS (also Windows CI): the verdict must equal what the interpreter does."""
    env = dict(os.environ); env.pop("PYTHONPATH", None)
    print(_consistent(fake_editable_env["python"], env, "default"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX locale simulation; Windows uses its real code page")
def test_preflight_matches_reality_in_legacy_locales(fake_editable_env):
    """For every legacy locale installed here and UTF-8 Mode off/on: preflight == reality. On a
    Python 3.11 (locale strategy) this includes the M3 case where the interpreter does not start."""
    from test_encoding import _legacy_locales
    names = _legacy_locales()
    if not names:
        pytest.skip("no non-UTF-8 locale installed here (CI coverage boundary: see docs/STATUS.md)")
    seen = []
    for name in names:
        for mode in ("0", "1"):
            env = dict(os.environ, LC_ALL=name, PYTHONUTF8=mode); env.pop("PYTHONPATH", None)
            seen.append(_consistent(fake_editable_env["python"], env, f"{name} UTF8={mode}"))
    print("preflight vs reality:")
    for s in seen:
        print("   ", s)


def test_preflight_reports_a_healthy_regular_environment(tmp_path):
    """No .pth problem and patt_pdf importable -> exit 0, no recovery advice."""
    vdir = tmp_path / "venv"; venv.EnvBuilder(with_pip=False, symlinks=(os.name != "nt")).create(vdir)
    py = vdir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    sp = Path(subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.strip())
    (sp / "patt_pdf").mkdir(); (sp / "patt_pdf" / "__init__.py").write_text("__version__ = 'stub'\n", encoding="utf-8")
    env = dict(os.environ); env.pop("PYTHONPATH", None)
    rc, res = _preflight(py, env)
    assert rc == 0 and res["checks"]["import_patt_pdf"] == "OK (stub)" and not res["recovery"], res


def test_prediction_rule_is_shared_with_the_test_suite():
    """preflight.predict and the suite's _expected_pth_result must agree (one rule, two copies:
    the preflight cannot import anything from the package or the tests)."""
    sys.path.insert(0, str(PREFLIGHT.parent))
    try:
        import preflight
    finally:
        sys.path.remove(str(PREFLIGHT.parent))
    from test_osenv import _expected_pth_result
    line = "/x/源码 目录/a".encode("utf-8")
    for strat in ("utf8-first", "locale", "unknown"):
        for enc in ("UTF-8", "ISO8859-1", "CP1252", "GBK", "cp65001"):
            for fs in ("utf-8", "gbk", "cp1252"):
                assert preflight.predict(strat, enc, line, fs) == _expected_pth_result(strat, enc, line, fs), (strat, enc, fs)


def test_preflight_uses_only_the_standard_library():
    """It must start in a broken environment: no third-party or patt_pdf imports."""
    import ast
    tree = ast.parse(PREFLIGHT.read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    stdlib = getattr(sys, "stdlib_module_names", None) or {"argparse", "json", "os", "subprocess", "sys", "pathlib", "__future__"}
    assert mods <= set(stdlib) | {"__future__"}, mods
    assert "patt_pdf" not in mods


# ------------------------------------------------------------------ minimal disclosure (review P0)
def _leak_forms(secret: str) -> dict[str, str]:
    """Ways a path can leak in a report: plain, UTF-8/UTF-16 hex, escapes, file URL, quoted."""
    import urllib.parse
    b = secret.encode("utf-8")
    return {
        "plain": secret,
        "utf8-hex": b.hex(),
        "utf8-hex-upper": b.hex().upper(),
        "utf16le-hex": secret.encode("utf-16-le").hex(),
        "utf16be-hex": secret.encode("utf-16-be").hex(),
        "backslash-escape": secret.encode("unicode_escape").decode("ascii"),
        "ascii-repr": ascii(secret)[1:-1],
        "url-quoted": urllib.parse.quote(secret),
        "file-url": "file://" + urllib.parse.quote(secret),
        "hex-of-cjk-part": "我的私人 资料".encode("utf-8").hex(),
    }


@pytest.fixture(scope="module")
def private_env(tmp_path_factory):
    """A venv + editable-style .pth whose folder names contain a 'secret' user name and CJK."""
    base = tmp_path_factory.mktemp("pfp")
    src = base / "secretuser_zq7" / "我的私人 资料"; (src / "patt_pdf").mkdir(parents=True)
    (src / "patt_pdf" / "__init__.py").write_text("__version__ = 'stub'\n", encoding="utf-8")
    vdir = base / "secretuser_zq7" / "venv 环境"
    venv.EnvBuilder(with_pip=False, symlinks=(os.name != "nt")).create(vdir)
    py = vdir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    sp = subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.strip()
    (Path(sp) / "__editable__.patt_pdf_stub-0.pth").write_bytes(str(src).encode("utf-8") + b"\n")
    return {"python": py, "src": src}


@pytest.mark.parametrize("fmt", ["text", "json"])
def test_default_output_contains_no_local_path_in_any_encoding(private_env, fmt):
    env = dict(os.environ); env.pop("PYTHONPATH", None)
    args = [sys.executable, "-S", str(PREFLIGHT), "--python", str(private_env["python"])] + (["--json"] if fmt == "json" else [])
    r = subprocess.run(args, capture_output=True, env=env, timeout=120)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    assert "interpreter_runs_with_-S" in out, out
    for secret in (str(private_env["src"]), "secretuser_zq7", "我的私人 资料", str(private_env["python"])):
        for kind, form in _leak_forms(secret).items():
            assert form.lower() not in out.lower(), (kind, secret)
    assert "secretuser" not in out.lower()
    if fmt == "json":
        res = json.loads(r.stdout.decode("ascii"))
        assert res["redacted"] is True and res["python"] == "<python>"
        line = res["pth"][0]["line"]
        assert line["cjk_chars"] == 6 and line["spaces"] >= 1 and line["utf8"] is True and len(line["sha256_12"]) == 12


def test_private_details_are_opt_in_and_marked(private_env):
    env = dict(os.environ); env.pop("PYTHONPATH", None)
    r = subprocess.run([sys.executable, "-S", str(PREFLIGHT), "--python", str(private_env["python"]), "--private-details"],
                       capture_output=True, env=env, timeout=120)
    out = r.stdout.decode("utf-8", "replace"); err = r.stderr.decode("utf-8", "replace")
    assert "PRIVATE raw bytes (hex)" in out and str(private_env["src"]).encode("utf-8").hex() in out
    assert "Keep it private" in err


def test_redaction_keeps_safe_text():
    sys.path.insert(0, str(PREFLIGHT.parent))
    try:
        import preflight
    finally:
        sys.path.remove(str(PREFLIGHT.parent))
    for safe in ("UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 17",
                 "ModuleNotFoundError: No module named 'patt_pdf'", "https://example.org/field-guide", "exit 1"):
        assert preflight._redact(safe) == safe, safe
    for leaky in ('File "/home/secretuser_zq7/x 目录/site.py", line 3',
                  "C:\\Users\\secretuser_zq7\\私人 目录\\x.pth",
                  "\\\\fileserver\\secretuser_zq7\\a\\b",
                  "see file:///Users/secretuser_zq7/a%20b/x and file://host/secretuser_zq7/x",
                  "cannot open /Users/secretuser_zq7/my docs/report.pdf now",
                  "~/secretuser_zq7/notes/a.txt"):
        red = preflight._redact(leaky)
        assert "secretuser_zq7" not in red and "目录" not in red, (leaky, red)
