"""PATT-PDF install preflight: diagnose an environment WITHOUT importing patt_pdf.

Why this exists (macOS retest M3, v0.3.5): after an *editable* install from a non-ASCII folder,
Python 3.11 under a legacy locale (en_US.ISO8859-1, zh_CN.GBK) cannot process the environment's
`.pth` file. Depending on the bytes, the interpreter does not start at all (UnicodeDecodeError in
site.py) or starts without finding `patt_pdf`. `patt-pdf doctor` lives inside the package, so it
cannot run there. This script uses only the standard library and can be started by the broken
interpreter itself with `-S` (skip site.py):

    <venv>/bin/python -S tools/preflight.py              # macOS / Linux
    <venv>\\Scripts\\python.exe -S tools\\preflight.py     # Windows
    python3 -S tools/preflight.py --python <other python>  # check another interpreter

It reports, separately: (1) does the interpreter start in this environment and locale,
(2) can it import patt_pdf, (3) for each `.pth` file with a non-ASCII path: how this
interpreter's site.py decodes it, and the predicted result, (4) recovery steps.
It changes nothing (no installs, no locale or registry changes, no deletions).

Exit codes: 0 no problem found, 1 a problem was found (see "diagnosis"), 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Runs in the TARGET interpreter with -S. Prints one JSON line. Mirrors osenv.pth_strategy():
# the strategy is read from the string constants of the loaded site.addpackage code object
# (site is a frozen module in 3.11+ release builds, so source inspection does not work).
_PROBE = r"""
import io, json, sys
def consts(co, d=0):
    for c in co.co_consts:
        if isinstance(c, str): yield c
        elif hasattr(c, 'co_consts') and d < 4: yield from consts(c, d + 1)
try:
    import site
    k = set(consts(site.addpackage.__code__))
    strategy = 'utf8-first' if 'utf-8-sig' in k else ('locale' if 'locale' in k else 'unknown')
except Exception as e:
    strategy = 'unknown'
try:
    loc = io.TextIOWrapper(io.BytesIO(), encoding='locale').encoding
except Exception:
    import locale; loc = locale.getpreferredencoding(False)
print(json.dumps({'python': sys.version.split()[0], 'executable': sys.executable,
                  'strategy': strategy, 'locale_text_encoding': loc,
                  'fs_encoding': sys.getfilesystemencoding(), 'utf8_mode': sys.flags.utf8_mode,
                  'version_info': list(sys.version_info[:2])}))
"""


def predict(strategy: str, locale_enc: str, line: bytes, fs_enc: str = "utf-8") -> str:
    """found / missing / error / unknown for one UTF-8 `.pth` line (same rule as the test suite)."""
    try:
        if strategy == "utf8-first":
            try:
                text = line.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = line.decode(locale_enc)
        elif strategy == "locale":
            text = line.decode(locale_enc)
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
    return "found" if back == line else "missing"


def venv_site_packages(python: Path, version: tuple[int, int]) -> list[Path]:
    """site-packages of the venv that `python` belongs to, found WITHOUT running site.py
    (with -S, sys.prefix is the base installation, because pyvenv.cfg is handled by site.py)."""
    exe = Path(python)
    for root in (exe.parent.parent, exe.parent):
        if (root / "pyvenv.cfg").is_file():
            if os.name == "nt" or (root / "Lib" / "site-packages").is_dir():
                cands = [root / "Lib" / "site-packages"]
            else:
                cands = [root / "lib" / f"python{version[0]}.{version[1]}" / "site-packages"]
            return [c for c in cands if c.is_dir()]
    return []


def _run(cmd, env=None, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"{type(e).__name__}: {e}"
    dec = lambda b: b.decode("utf-8", "backslashreplace")   # noqa: E731
    return r.returncode, dec(r.stdout), dec(r.stderr)


def _last_line(text: str) -> str:
    lines = [x for x in text.strip().splitlines() if x.strip()]
    return lines[-1].strip()[:240] if lines else ""


def check(python: str, site_dirs: list[str] | None = None) -> dict:
    py = str(python)
    res: dict = {"python": py, "checks": {}, "pth": [], "problems": [], "recovery": []}
    rc, out, err = _run([py, "-S", "-c", _PROBE])
    if rc != 0 or not out.strip():
        res["checks"]["interpreter_runs_with_-S"] = f"FAIL ({_last_line(err) or rc})"
        res["problems"].append("the interpreter does not run even without site.py; this is not a PATT-PDF problem")
        return res
    facts = json.loads(out.strip().splitlines()[-1])
    res["facts"] = facts
    res["checks"]["interpreter_runs_with_-S"] = "OK"
    rc, out, err = _run([py, "-c", "pass"])
    res["checks"]["interpreter_starts_normally"] = "OK" if rc == 0 else f"FAIL (exit {rc}: {_last_line(err)})"
    started = rc == 0
    if started:
        rc, out, err = _run([py, "-c", "import patt_pdf, sys; sys.stdout.write(patt_pdf.__version__)"])
        res["checks"]["import_patt_pdf"] = f"OK ({out.strip()})" if rc == 0 else f"FAIL ({_last_line(err)})"
        imported = rc == 0
    else:
        res["checks"]["import_patt_pdf"] = "NOT RUN (interpreter does not start)"
        imported = False

    dirs = [Path(d) for d in site_dirs] if site_dirs else venv_site_packages(Path(facts["executable"]),
                                                                              tuple(facts["version_info"]))
    res["site_packages"] = [str(d) for d in dirs]
    for d in dirs:
        for pth in sorted(d.glob("*.pth")):
            try:
                data = pth.read_bytes()
            except OSError as e:
                res["pth"].append({"file": pth.name, "error": str(e)}); continue
            for raw in data.splitlines():
                line = raw.strip()
                if not line or line.startswith(b"#") or line.startswith(b"import ") or line.isascii():
                    continue
                res["pth"].append({"file": pth.name, "line_hex": line[:48].hex(),
                                   "predicted": predict(facts["strategy"], facts["locale_text_encoding"],
                                                        line, facts["fs_encoding"])})

    bad = [p for p in res["pth"] if p.get("predicted") in ("error", "missing")]
    editable = any(p["file"].startswith("__editable__") for p in res["pth"])
    if not started:
        res["problems"].append("the interpreter fails while site.py processes this environment"
                               + (" (a .pth file with a non-ASCII path cannot be decoded)" if bad else ""))
    elif not imported:
        res["problems"].append("patt_pdf is not importable in this environment and locale")
    if bad and started and imported:
        res["problems"].append("a .pth line is predicted not to resolve; another package may be affected")
    if res["problems"]:
        res["recovery"] = recovery_steps(facts, editable, bool(bad))
    return res


def recovery_steps(facts: dict, editable: bool, pth_problem: bool) -> list[str]:
    win = os.name == "nt"
    steps = []
    if editable or pth_problem:
        steps.append("Recommended: a REGULAR install into a new virtual environment in a folder whose path is ASCII-only: "
                     + ("py -3.12 -m venv C:\\patt\\venv (or: python -m venv C:\\patt\\venv); "
                        "C:\\patt\\venv\\Scripts\\python.exe -m pip install \"<source folder>[ocr]\""
                        if win else
                        "python3 -m venv ~/patt-venv && ~/patt-venv/bin/python -m pip install \"<source folder>[ocr]\""))
        steps.append("Or, if you need an editable install: put the source in an ASCII-only folder, create a new venv "
                     "and run pip install -e there.")
    if facts.get("strategy") == "locale" and not win:
        steps.append("Or run with a UTF-8 locale for this shell only, e.g. `export LC_ALL=en_US.UTF-8` "
                     "(this changes nothing system-wide). PYTHONUTF8=1 is NOT a fix on Python 3.11+: it does not "
                     "change the encoding this site.py uses for .pth files.")
    if facts.get("strategy") == "utf8-first" and facts.get("fs_encoding", "").lower().replace("-", "") != "utf8":
        steps.append("This interpreter decodes .pth files as UTF-8, but its file system encoding is "
                     f"{facts.get('fs_encoding')} (Linux legacy locale): PYTHONUTF8=1 or a UTF-8 locale fixes this case.")
    steps.append("The broken environment can be left as it is or deleted manually (only its own folder). "
                 "This script never deletes or changes anything.")
    return steps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PATT-PDF install preflight (standard library only; run with python -S)")
    ap.add_argument("--python", default=sys.executable, help="interpreter to check (default: the one running this)")
    ap.add_argument("--site-packages", action="append", help="site-packages folder(s) to inspect (default: the venv's)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args(argv)
    res = check(a.python, a.site_packages)
    if a.json:
        print(json.dumps(res, ensure_ascii=True, indent=1))
    else:
        f = res.get("facts", {})
        print("PATT-PDF preflight (no patt_pdf import; changes nothing)")
        print(f"  python {f.get('python', '?')}  strategy {f.get('strategy', '?')}  locale-text {f.get('locale_text_encoding', '?')}"
              f"  fs {f.get('fs_encoding', '?')}  utf8_mode {f.get('utf8_mode', '?')}")
        for k, v in res["checks"].items():
            print(f"  {k:30s} {v}")
        for p in res["pth"]:
            print(f"  .pth {p['file']}: non-ASCII path, predicted {p.get('predicted', p.get('error'))}")
        if res["problems"]:
            print("diagnosis:")
            for p in res["problems"]:
                print("  - " + p)
            print("recovery:")
            for s in res["recovery"]:
                print("  - " + s)
        else:
            print("diagnosis: no problem found")
    sys.stdout.flush()
    return 1 if res["problems"] else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
