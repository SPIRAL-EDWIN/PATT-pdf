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

By default the output contains NO local paths: the interpreter, site-packages and .pth lines are
described by structure (length, UTF-8 validity, CJK/space counts, a short hash), so it can be
pasted into a report. `--private-details` adds the raw paths and bytes for your own use only.

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


def describe_line(line: bytes) -> dict:
    """What is needed to diagnose a .pth line WITHOUT the path itself (review finding: the hex
    of the line is the user's folder path, fully reversible). Length, which byte classes occur,
    whether it is valid UTF-8, and a short salted hash that lets the user compare two of their
    own reports without revealing the path (the salt is fixed, so it is not a secret: do not
    treat the hash as anonymisation of guessable paths)."""
    import hashlib
    info = {"bytes": len(line), "ascii": line.isascii()}
    try:
        text = line.decode("utf-8")
        info["utf8"] = True
        info["non_ascii_chars"] = sum(1 for c in text if ord(c) > 127)
        info["cjk_chars"] = sum(1 for c in text if "\u3000" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff")
        info["spaces"] = text.count(" ")
    except UnicodeDecodeError as e:
        info["utf8"] = False
        info["first_bad_byte_at"] = e.start
    info["sha256_12"] = hashlib.sha256(b"patt-preflight:" + line).hexdigest()[:12]
    return info


def check(python: str, site_dirs: list[str] | None = None, private: bool = False) -> dict:
    py = str(python)
    res: dict = {"python": py, "checks": {}, "pth": [], "problems": [], "recovery": []}
    rc, out, err = _run([py, "-S", "-c", _PROBE])
    if rc != 0 or not out.strip():
        res["checks"]["interpreter_runs_with_-S"] = f"FAIL ({_last_line(err) or rc})"
        res["problems"].append("the interpreter does not run even without site.py; this is not a PATT-PDF problem")
        if not private:
            _redact_result(res)
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
                entry = {"file": pth.name, "line": describe_line(line),
                         "predicted": predict(facts["strategy"], facts["locale_text_encoding"],
                                              line, facts["fs_encoding"])}
                if private:
                    entry["line_hex_PRIVATE"] = line.hex()
                res["pth"].append(entry)

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
    if not private:
        _redact_result(res)
    return res


def _redact(text: str) -> str:
    """Remove absolute paths, file URLs, the home folder and the user name from free text.
    Best effort (see README): unusual quoting or paths split across lines can survive.
    URLs other than file:// are kept."""
    import re
    home = os.path.expanduser("~")
    for h in sorted({home, home.replace("\\", "/")}, key=len, reverse=True):
        if len(h) > 3:
            text = text.replace(h, "~")
    text = re.sub(r"file:/{2,3}[^\s'\"<>]+", "<file-url>", text, flags=re.IGNORECASE)
    # quoted absolute paths: the whole quoted string (keeps spaces inside the quotes together)
    text = re.sub(r"(['\"])(?:[A-Za-z]:[\\/]|[\\/]{1,2}|~[\\/])[^'\"]*\1", lambda m: m.group(1) + "<path>" + m.group(1), text)
    # unquoted absolute paths (POSIX, C:\\…, \\\\server\\…), not URLs (scheme://host/…); a path may
    # contain single spaces between non-space parts
    seg = r"[^\\/\s'\"<>:|]+(?: [^\\/\s'\"<>:|-][^\\/\s'\"<>:|]*)*"
    text = re.sub(r"(?<![\w:/\\])(?:[A-Za-z]:|[\\/]{2}[^\\/\s]+)?(?:[\\/]" + seg + r"){2,}[\\/]?", "<path>", text)
    text = re.sub(r"~[\\/]" + seg + r"(?:[\\/]" + seg + r")*", "<path>", text)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if len(user) > 2:
        text = re.sub(re.escape(user), "<user>", text, flags=re.IGNORECASE)
    return text


def _redact_result(res: dict) -> None:
    res["python"] = "<python>"
    f = res.get("facts", {})
    if "executable" in f:
        f["executable"] = "<python>"
    res["site_packages"] = [f"<site-packages #{i + 1}>" for i, _ in enumerate(res.get("site_packages", []))]
    res["checks"] = {k: _redact(v) for k, v in res["checks"].items()}
    res["problems"] = [_redact(x) for x in res["problems"]]
    # An OS exception can contain paths in encoded or unusual forms. Preserve the fact
    # that a .pth could not be inspected, not the untrusted exception text itself.
    for entry in res.get("pth", []):
        if "error" in entry:
            entry["error"] = "Unable to read .pth file; check locally with --private-details"
    res["redacted"] = True


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
    ap.add_argument("--private-details", action="store_true",
                    help="also print local paths and the raw .pth bytes (hex). For your own machine only: "
                         "the hex IS your folder path. Never paste this output into a public report")
    a = ap.parse_args(argv)
    res = check(a.python, a.site_packages, private=a.private_details)
    if a.private_details:
        print("WARNING: --private-details output contains your local paths (also as hex). Keep it private.",
              file=sys.stderr)
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
            ln = p.get("line", {})
            print(f"  .pth {p['file']}: non-ASCII path ({ln.get('bytes', '?')} bytes, utf8={ln.get('utf8', '?')}, "
                  f"cjk={ln.get('cjk_chars', '?')}, spaces={ln.get('spaces', '?')}, id={ln.get('sha256_12', '?')}), "
                  f"predicted {p.get('predicted', p.get('error'))}")
            if "line_hex_PRIVATE" in p:
                print(f"    PRIVATE raw bytes (hex): {p['line_hex_PRIVATE']}")
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
