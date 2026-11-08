"""Install PATT-PDF from a source folder in a way that avoids the known Windows install traps.

Windows retest R02 (v0.3.5): a regular `pip install "<T>\\PATT-pdf[ocr,dev]"` from a deep folder
failed while pip built the wheel (FileNotFoundError in a long temporary path, LongPathsEnabled=0);
the retry with a different TEMP then failed on the `build/` folder left behind by the first
attempt (WinError 183, dist-info exists). A clean copy of the same commit + short TEMP worked.
Which of the two (pip/setuptools temp paths vs. our source tree depth) dominates was not proven;
this helper removes both factors without touching anything outside its own new folders:

* it reports path lengths and LongPathsEnabled (read-only);
* it copies ONLY the files tracked for the package (pyproject, README/LICENSE, src/) into a fresh,
  short folder, so no stale `build/` or `*.egg-info` from an earlier attempt can be reused;
* it points TMP/TEMP/PIP_BUILD_TRACKER for the pip child process only at a short new folder;
* it runs `python -m pip install <copy>[extras]` with the interpreter you give it and reports the
  real exit code. It never deletes the user's folders, edits the registry or changes settings.

Usage (Windows example):
    python tools\\install_check.py --source . --work C:\\pt --extras ocr,dev
    python tools\\install_check.py --source . --work C:\\pt --dry-run      # only diagnose
Extra pip arguments: `--pip-arg=ARG`, once per argument (paths with spaces stay one argument; the
`=` form is required for values that start with "-", e.g. `--pip-arg=--no-index`).
Exit codes: pip's exit code; 2 usage errors (e.g. the work folder already exists); 3 the target
environment cannot build with --no-build-isolation (nothing created).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_FILES = ("pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md")
SKIP_DIRS = {"build", "dist", "__pycache__", ".git", ".venv", ".pytest_cache"}
WINDOWS_MAX_PATH = 260


def long_paths_enabled() -> bool | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return bool(winreg.QueryValueEx(k, "LongPathsEnabled")[0])
    except OSError:
        return False


def longest_relative(src: Path) -> int:
    best = 0
    for root, dirs, files in os.walk(src / "src"):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in files:
            best = max(best, len(os.path.relpath(os.path.join(root, f), src)))
    return best


def diagnose(src: Path, work: Path) -> list[str]:
    notes = []
    lp = long_paths_enabled()
    notes.append(f"LongPathsEnabled: {lp if lp is not None else 'n/a (not Windows)'}")
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    notes.append(f"source folder: {len(str(src))} characters; longest package file inside: {longest_relative(src)}")
    notes.append(f"current TEMP: {len(temp)} characters; work folder: {len(str(work))} characters")
    stale = (["build"] if (src / "build").exists() else []) + [p.name for p in (src / "src").glob("*.egg-info")]
    if stale:
        notes.append("leftovers from an earlier build in the source folder (not reused by this helper): " + ", ".join(stale))
    if sys.platform == "win32" and lp is False and len(temp) > 60:
        notes.append("hint: pip builds in TEMP; with LongPathsEnabled off, a long TEMP path can exceed "
                     f"{WINDOWS_MAX_PATH} characters inside the build. This helper uses a short folder instead.")
    return notes


def clean_copy(src: Path, dest: Path) -> int:
    n = 0
    dest.mkdir(parents=True)
    for name in PACKAGE_FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name); n += 1
    for root, dirs, files in os.walk(src / "src"):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        rel = Path(root).relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(Path(root) / f, dest / rel / f); n += 1
    return n


def pip_arguments(pip_arg: list[str] | None, legacy: str | None) -> list[str]:
    """Extra pip arguments, each passed as ONE argv element (no shell, no word splitting).

    `--pip-arg=X` (repeatable) is the interface: a folder such as `/path/with space` or
    `C:\\wheels 轮子` stays one argument on every OS. The old `--pip-args "a b"` split on
    whitespace (review finding: a wheelhouse path with a space broke); it is still accepted for
    simple flag lists but refused when splitting would be ambiguous (quotes, or an option value
    that looks like a path)."""
    out = list(pip_arg or [])
    if legacy:
        parts = legacy.split()
        if any(c in legacy for c in "\"'") or any(("/" in x or "\\" in x) and not x.startswith("-") for x in parts):
            raise ValueError("--pip-args cannot carry quoted values or paths reliably; use one --pip-arg per "
                             "argument, e.g. --pip-arg=--find-links \"--pip-arg=/path/with space\"")
        out += parts
    return out


def build_backend_problem(python: str, pip_args: list[str]) -> str | None:
    """With --no-build-isolation pip uses the TARGET environment's setuptools to build the wheel.
    PATT-PDF's pyproject needs setuptools >= 64 (PEP 660/621); setuptools < 70.1 also needs the
    `wheel` package for `bdist_wheel`. CI finding (run 42480633442, macOS python.org 3.11.9, whose
    venvs get setuptools 65.5.0 without `wheel`): `error: invalid command 'bdist_wheel'`.
    Returns a clear message instead of letting pip fail deep inside the build."""
    if "--no-build-isolation" not in pip_args:
        return None                     # pip creates an isolated build env with a current setuptools
    probe = ("import importlib.util as u, sys\n"
             "try:\n import setuptools; v = setuptools.__version__\n"
             "except Exception:\n v = ''\n"
             "print(v, int(u.find_spec('wheel') is not None))")
    try:
        r = subprocess.run([python, "-c", probe], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"cannot run {python}: {e}"
    parts = r.stdout.decode("ascii", "replace").split()
    ver, has_wheel = (parts + ["", "0"])[:2] if len(parts) >= 2 else ("", "0")
    if not ver:
        return ("--no-build-isolation: the target environment has no setuptools. Install `setuptools>=70.1` "
                "into it first (or drop --no-build-isolation so pip builds in an isolated environment).")
    try:
        nums = tuple(int(x) for x in ver.split(".")[:2])
    except ValueError:
        return None
    if nums < (64, 0):
        return f"--no-build-isolation: setuptools {ver} is too old (PATT-PDF needs >= 64; 70.1+ recommended)."
    if nums < (70, 1) and has_wheel != "1":
        return (f"--no-build-isolation: setuptools {ver} needs the `wheel` package for `bdist_wheel` "
                "(built in from setuptools 70.1). Install `wheel` or `setuptools>=70.1` into the target "
                "environment first, or drop --no-build-isolation.")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="PATT-PDF source folder (contains pyproject.toml)")
    ap.add_argument("--work", required=True, help="NEW short folder for the clean copy and temp files, e.g. C:\\pt")
    ap.add_argument("--extras", default="ocr", help="extras to install, e.g. ocr,dev ('' for none)")
    ap.add_argument("--python", default=sys.executable, help="interpreter whose environment receives the install")
    ap.add_argument("--pip-arg", action="append", default=[], metavar="ARG",
                    help="one extra pip argument; repeat for more. Use the '=' form for values that start with '-': "
                         "--pip-arg=--find-links \"--pip-arg=C:\\my wheels\"")
    ap.add_argument("--pip-args", default="", help="(old form) whitespace-separated pip flags without paths or quotes")
    ap.add_argument("--dry-run", action="store_true", help="only print the diagnosis")
    a = ap.parse_args(argv)
    try:
        extra = pip_arguments(a.pip_arg, a.pip_args)
    except ValueError as e:
        print(f"error: {e}"); return 2
    src = Path(a.source).resolve(); work = Path(a.work)
    if not (src / "pyproject.toml").is_file():
        print(f"error: {src} has no pyproject.toml"); return 2
    for line in diagnose(src, work):
        print("  " + line)
    problem = build_backend_problem(a.python, extra)
    if problem:
        print("  build backend: " + problem)
    if a.dry_run:
        return 0
    if problem:
        print("error: not starting pip (see 'build backend' above); nothing was created")
        return 3
    if work.exists():
        print(f"error: {work} already exists; choose a new folder (this helper never reuses or deletes folders)")
        return 2
    copy, tmp = work / "s", work / "t"
    files = clean_copy(src, copy); tmp.mkdir(parents=True)
    print(f"  clean copy: {files} files in {copy}")
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
    target = str(copy) + (f"[{a.extras}]" if a.extras else "")
    cmd = [a.python, "-m", "pip", "install", target] + extra
    print("  running: " + " ".join(repr(c) if (" " in c or not c) else c for c in cmd))
    sys.stdout.flush()
    rc = subprocess.run(cmd, env=env).returncode
    print(f"pip exit code: {rc}")
    if rc == 0:
        print(f"done. The folder {work} can be deleted manually after checking (pip does not need it any more).")
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
