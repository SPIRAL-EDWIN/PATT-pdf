"""tools/install_check.py (Windows retest R02): clean, short-path regular install helper.

What is tested where:
* argument passing, folder safety and the build-backend check: here, offline, with a FAKE pip
  (no network, no real install) - runs on every OS;
* a real offline install with `--no-build-isolation`: only if the test can provide a suitable
  setuptools from a local, already present wheel (see _local_setuptools_wheel); otherwise the
  test reports exactly why it cannot run. The normal user path (pip WITH build isolation, which
  downloads a current setuptools) is not exercised offline; the retest prompts cover it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "install_check.py"


def _run(*args, timeout=600, env=None):
    r = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, timeout=timeout, env=env)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def _module():
    sys.path.insert(0, str(TOOL.parent))
    try:
        import install_check
        return install_check
    finally:
        sys.path.remove(str(TOOL.parent))


@pytest.fixture
def fake_python(tmp_path):
    """A stand-in for the target interpreter: `-c <probe>` answers like an environment with
    setuptools <FAKE_SETUPTOOLS> (and wheel if FAKE_WHEEL=1); `-m pip install …` records its
    argv as JSON and exits with FAKE_PIP_RC. No real pip runs."""
    rec = tmp_path / "argv.json"
    script = tmp_path / "fakepy.py"
    script.write_text(
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        "if a[:1] == ['-c']:\n"
        "    print(os.environ.get('FAKE_SETUPTOOLS', '80.0.0'), os.environ.get('FAKE_WHEEL', '0')); sys.exit(0)\n"
        "print(os.environ.get('FAKE_PIP_OUTPUT', ''))\n"
        "print(os.environ.get('FAKE_PIP_OUTPUT', ''), file=sys.stderr)\n"
        f"open({str(rec)!r}, 'w', encoding='utf-8').write(json.dumps(a, ensure_ascii=False))\n"
        "sys.exit(int(os.environ.get('FAKE_PIP_RC', '0')))\n", encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / "fakepy.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "fakepy"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return {"python": launcher, "argv": rec}


def test_dry_run_only_diagnoses(tmp_path):
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--dry-run")
    assert rc == 0 and "LongPathsEnabled" in out and "source folder:" in out, out
    assert not (tmp_path / "w").exists()                      # nothing created


def test_refuses_existing_work_folder(tmp_path, fake_python):
    (tmp_path / "w").mkdir(); (tmp_path / "w" / "keep.txt").write_text("user file", encoding="utf-8")
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--python", fake_python["python"])
    assert rc == 2 and "already exists" in out
    assert (tmp_path / "w" / "keep.txt").read_text(encoding="utf-8") == "user file"   # untouched


def test_clean_copy_ignores_stale_build_state(tmp_path):
    """The R02 retry failed on a build/ folder left by the first attempt. The copy must contain
    the package sources only, never build/, *.egg-info or bytecode."""
    install_check = _module()
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


# ------------------------------------------------------------------ pip arguments (review P1)
@pytest.mark.parametrize("extra, want", [
    ([], []),
    (["--pip-arg=--no-index"], ["--no-index"]),
    (["--pip-arg=--find-links", "--pip-arg", "WHEELS"], ["--find-links", "WHEELS"]),   # value without '-': plain form ok
    (["--pip-arg=--find-links=WHEELS"], ["--find-links=WHEELS"]),
    (["--pip-args", "--no-deps --no-index"], ["--no-deps", "--no-index"]),                 # old form, flags only
])
def test_pip_arguments_are_passed_one_by_one(tmp_path, fake_python, extra, want):
    wh = tmp_path / "wheel house 轮子"                         # space + Chinese stays ONE argument
    extra = [str(wh) if x == "WHEELS" else x.replace("WHEELS", str(wh)) for x in extra]
    want = [str(wh) if x == "WHEELS" else x.replace("WHEELS", str(wh)) for x in want]
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--extras", "", "--python", fake_python["python"], *extra)
    assert rc == 0, out
    argv = json.loads(fake_python["argv"].read_text(encoding="utf-8"))
    assert argv[:3] == ["-m", "pip", "install"] and argv[4:] == want, argv
    assert Path(argv[3]).parent == tmp_path / "w"              # installs the clean copy in the NEW folder


def test_pip_exit_code_is_returned(tmp_path, fake_python):
    env = dict(os.environ, FAKE_PIP_RC="7")
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--python", fake_python["python"], env=env)
    assert rc == 7 and "pip exit code: 7" in out


@pytest.mark.parametrize("exit_code", ["0", "7"])
def test_sensitive_pip_arguments_and_child_output_are_never_printed(tmp_path, fake_python, exit_code):
    secret = "FAKE_SECRET_NOT_REAL_4829"
    url = f"https://fakeuser:{secret}@example.invalid/simple"
    env = dict(os.environ, FAKE_PIP_RC=exit_code, FAKE_PIP_OUTPUT=url)
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--python", fake_python["python"],
                   "--pip-arg=--index-url", f"--pip-arg={url}", env=env)
    assert rc == int(exit_code)
    assert secret not in out and "fakeuser" not in out and url not in out
    # Suppression only affects diagnostics, not arguments delivered to pip.
    argv = json.loads(fake_python["argv"].read_text(encoding="utf-8"))
    assert argv[-2:] == ["--index-url", url]


@pytest.mark.parametrize("legacy", ['--find-links "/a b"', "--find-links /tmp/wheel house", "--find-links C:\\wh"])
def test_old_pip_args_with_paths_or_quotes_is_refused(tmp_path, fake_python, legacy):
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--python", fake_python["python"], "--pip-args", legacy)
    assert rc == 2 and "--pip-arg" in out and not (tmp_path / "w").exists(), out
    assert not fake_python["argv"].exists()                    # pip never started


# ------------------------------------------------------------------ build backend (CI run 42480633442)
@pytest.mark.parametrize("setuptools, wheel, ok", [
    ("65.5.0", "0", False),        # python.org 3.11.9 venv: the macOS CI failure ('invalid command bdist_wheel')
    ("65.5.0", "1", True),         # older setuptools + wheel package: works
    ("70.1.0", "0", True),         # bdist_wheel built in
    ("59.6.0", "1", False),        # too old for PEP 621/660
    ("", "0", False),              # no setuptools at all
])
def test_no_build_isolation_checks_the_target_build_backend(tmp_path, fake_python, setuptools, wheel, ok):
    env = dict(os.environ, FAKE_SETUPTOOLS=setuptools, FAKE_WHEEL=wheel)
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--extras", "", "--python", fake_python["python"],
                   "--pip-arg=--no-build-isolation", env=env)
    if ok:
        assert rc == 0 and "build backend:" not in out, out
    else:
        assert rc == 3 and "build backend:" in out and not (tmp_path / "w").exists(), out
        assert not fake_python["argv"].exists()


def test_with_build_isolation_the_target_setuptools_does_not_matter(tmp_path, fake_python):
    env = dict(os.environ, FAKE_SETUPTOOLS="", FAKE_WHEEL="0")
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--python", fake_python["python"], env=env)
    assert rc == 0 and "build backend:" not in out, out


# ------------------------------------------------------------------ real offline install
def _local_setuptools_wheel():
    """A setuptools >= 70.1 wheel that is already on this machine (the interpreter's own
    ensurepip bundle, or $PATT_TEST_WHEELHOUSE). No download."""
    import glob
    cands = []
    for d in filter(None, [os.environ.get("PATT_TEST_WHEELHOUSE"),
                           os.path.join(os.path.dirname(os.__file__), "ensurepip", "_bundled")]):
        cands += glob.glob(os.path.join(d, "setuptools-*-py3-none-any.whl"))
    def ver(p):
        try:
            return tuple(int(x) for x in os.path.basename(p).split("-")[1].split(".")[:2])
        except ValueError:
            return (0, 0)
    good = sorted((p for p in cands if ver(p) >= (70, 1)), key=ver)
    return good[-1] if good else None


def test_real_install_into_a_fresh_venv(tmp_path):
    """Offline, real pip: new venv + setuptools >= 70.1 from a local wheel, then install PATT-PDF
    (no deps) with --no-build-isolation through the helper and import it."""
    import venv
    whl = _local_setuptools_wheel()
    if not whl:
        pytest.skip("no local setuptools>=70.1 wheel (ensurepip bundle or PATT_TEST_WHEELHOUSE); "
                    "this test does not download. The fake-pip tests above cover the helper itself")
    vdir = tmp_path / "v 环境"; venv.EnvBuilder(with_pip=True, symlinks=(sys.platform != "win32")).create(vdir)
    py = vdir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    r = subprocess.run([str(py), "-m", "pip", "install", "--no-index", "--upgrade", whl], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-1500:]
    rc, out = _run("--source", ROOT, "--work", tmp_path / "w", "--extras", "", "--python", py,
                   "--pip-arg=--no-deps", "--pip-arg=--no-build-isolation", "--pip-arg=--no-index")
    assert rc == 0, out[-2000:]
    r = subprocess.run([str(py), "-c", "import patt_pdf; print(patt_pdf.__version__)"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
