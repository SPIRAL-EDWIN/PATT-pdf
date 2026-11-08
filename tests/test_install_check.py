"""tools/install_check.py (Windows retest R02): clean, short-path regular install helper."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "install_check.py"


def _run(*args, timeout=600):
    r = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def test_dry_run_only_diagnoses(tmp_path):
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--dry-run")
    assert rc == 0 and "LongPathsEnabled" in out and "source folder:" in out, out
    assert not (tmp_path / "w").exists()                      # nothing created


def test_refuses_existing_work_folder(tmp_path):
    (tmp_path / "w").mkdir(); (tmp_path / "w" / "keep.txt").write_text("user file", encoding="utf-8")
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w")
    assert rc == 2 and "already exists" in out
    assert (tmp_path / "w" / "keep.txt").read_text(encoding="utf-8") == "user file"   # untouched


def test_clean_copy_ignores_stale_build_state(tmp_path):
    """The R02 retry failed on a build/ folder left by the first attempt. The copy must contain
    the package sources only, never build/, *.egg-info or bytecode."""
    sys.path.insert(0, str(TOOL.parent))
    try:
        import install_check
    finally:
        sys.path.remove(str(TOOL.parent))
    src = tmp_path / "src 源"; (src / "src" / "pkg").mkdir(parents=True)
    (src / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (src / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (src / "src" / "pkg" / "m.cpython-312.pyc").write_bytes(b"x")
    (src / "src" / "x.egg-info").mkdir(); (src / "src" / "x.egg-info" / "PKG-INFO").write_text("", encoding="utf-8")
    (src / "build" / "lib").mkdir(parents=True); (src / "build" / "lib" / "stale.py").write_text("", encoding="utf-8")
    assert any("leftovers" in n for n in install_check.diagnose(src, tmp_path / "w"))
    n = install_check.clean_copy(src, tmp_path / "copy")
    got = sorted(str(p.relative_to(tmp_path / "copy")).replace("\\", "/") for p in (tmp_path / "copy").rglob("*") if p.is_file())
    assert got == ["pyproject.toml", "src/pkg/__init__.py"] and n == 2, got


def test_real_install_into_a_fresh_venv(tmp_path):
    """End to end, offline: install PATT-PDF (no extras, no deps) into a new venv via the helper."""
    import venv
    vdir = tmp_path / "v"; venv.EnvBuilder(with_pip=True, symlinks=(sys.platform != "win32")).create(vdir)
    py = vdir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    import pytest
    st = subprocess.run([str(py), "-c", "import setuptools; print(setuptools.__version__)"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if st.returncode != 0:
        pytest.skip("fresh venv has no setuptools and this test is offline (--no-build-isolation --no-index)")
    if int(st.stdout.strip().split(".")[0]) < 61:
        pytest.skip(f"setuptools {st.stdout.strip()} in the venv predates PEP 621 support (61); offline, "
                    "pip cannot fetch a newer one. Normal installs use build isolation and are not affected")
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--extras", "", "--python", py,
                   "--pip-args", "--no-deps --no-build-isolation --no-index")
    assert rc == 0, out[-2000:]
    r = subprocess.run([str(py), "-c", "import patt_pdf; print(patt_pdf.__version__)"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
