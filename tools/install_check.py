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
Exit codes: pip's exit code; 2 for usage errors (for example the work folder already exists).
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="PATT-PDF source folder (contains pyproject.toml)")
    ap.add_argument("--work", required=True, help="NEW short folder for the clean copy and temp files, e.g. C:\\pt")
    ap.add_argument("--extras", default="ocr", help="extras to install, e.g. ocr,dev ('' for none)")
    ap.add_argument("--python", default=sys.executable, help="interpreter whose environment receives the install")
    ap.add_argument("--pip-args", default="", help="extra pip arguments, e.g. '--no-index --find-links C:\\wh'")
    ap.add_argument("--dry-run", action="store_true", help="only print the diagnosis")
    a = ap.parse_args(argv)
    src = Path(a.source).resolve(); work = Path(a.work)
    if not (src / "pyproject.toml").is_file():
        print(f"error: {src} has no pyproject.toml"); return 2
    for line in diagnose(src, work):
        print("  " + line)
    if a.dry_run:
        return 0
    if work.exists():
        print(f"error: {work} already exists; choose a new folder (this helper never reuses or deletes folders)")
        return 2
    copy, tmp = work / "s", work / "t"
    files = clean_copy(src, copy); tmp.mkdir(parents=True)
    print(f"  clean copy: {files} files in {copy}")
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
    target = str(copy) + (f"[{a.extras}]" if a.extras else "")
    cmd = [a.python, "-m", "pip", "install", target] + a.pip_args.split()
    print("  running: " + " ".join(cmd))
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
