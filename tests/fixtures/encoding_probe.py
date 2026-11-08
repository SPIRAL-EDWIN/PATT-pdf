"""Run the fixture generator and a small CLI pipeline in a child process whose default text
encoding is NOT UTF-8 (see tests/test_encoding.py). Prints only ASCII. Exit codes:
0 ok, 1 assertion failed, 2 an implicit default-encoding use was attributed to project code,
3 the fixture generator itself failed (no CLI call was made; a test-tool problem, see R01).
STAGE lines show how far the probe got; callers assert that the CLI stage was reached.

Detection: the child runs with `-X warn_default_encoding`. Every EncodingWarning is recorded
with the file that triggered it. Warnings raised from PATT-PDF code (src/patt_pdf, the probe and
the fixture generator) fail the probe; warnings from the standard library or third-party
packages are listed but do not fail it. (v0.3.1 turned *all* EncodingWarnings into errors, so
`locale.getpreferredencoding()` inside the probe itself aborted it on Python 3.11+ before the
pipeline ran: review findings W01 / macOS.)"""
from __future__ import annotations

import json
import locale
import sys
import tempfile
import warnings
from pathlib import Path

HERE = Path(__file__).parent
PROJECT = (HERE.parent.parent / "src" / "patt_pdf").resolve()
OWN = [PROJECT, HERE.resolve()]
_seen: list[tuple[str, int, str]] = []
_orig_showwarning = warnings.showwarning


def _record(message, category, filename, lineno, file=None, line=None):
    if issubclass(category, EncodingWarning):
        _seen.append((filename, lineno, str(message)))
    else:
        _orig_showwarning(message, category, filename, lineno, file, line)


warnings.simplefilter("always", EncodingWarning)
warnings.showwarning = _record


def _own(filename: str) -> bool:
    try:
        f = Path(filename).resolve()
    except (OSError, ValueError):
        return False
    return any(f == o or o in f.parents for o in OWN)


def default_encoding() -> str:
    """The locale encoding, without itself triggering EncodingWarning (getencoding: 3.11+)."""
    getenc = getattr(locale, "getencoding", None)
    return getenc() if getenc else locale.getpreferredencoding(False)
sys.path.insert(0, str(HERE))
import make_fixtures  # noqa: E402

from patt_pdf.cli import main as cli  # noqa: E402

UNICODE_NAME = "报告 2026 – résumé.pdf"


def check(cond, msg):
    if not cond:
        print("FAIL:", msg.encode("ascii", "backslashreplace").decode()); sys.exit(1)


def _call_external():
    """PATT_PROBE_CALL=module:function — call code outside the project before the pipeline
    (tests use it to emit a real third-party EncodingWarning on Python 3.11+)."""
    import importlib
    import os
    spec = os.environ.get("PATT_PROBE_CALL")
    if spec:
        mod, _, fn = spec.partition(":")
        getattr(importlib.import_module(mod), fn)()


def run():
    _call_external()
    # MuPDF passes file names to the OS as UTF-8. Windows and macOS file systems are UTF-8 for
    # Python too; only a POSIX system with a legacy-locale file system encoding differs, and
    # there the non-ASCII file name is left out of this probe (documented limitation).
    utf8_fs = sys.getfilesystemencoding().lower().replace("-", "") == "utf8"
    print("default encoding:", default_encoding(), "utf8_mode:", sys.flags.utf8_mode,
          "warn_default_encoding:", getattr(sys.flags, "warn_default_encoding", "n/a"))
    with tempfile.TemporaryDirectory(prefix="patt-enc-") as td:
        td = Path(td); src = td / "in"
        try:
            make_fixtures.main(str(src))
        except Exception as e:              # a test-tool failure must not look like a CLI result
            print("FAIL: fixture generator (before any CLI call):",
                  f"{type(e).__name__}: {e}".encode("ascii", "backslashreplace").decode())
            sys.exit(3)
        print("STAGE: fixtures ready; temp folder is ASCII:", str(td).isascii())
        truth = make_fixtures.load_truth(src / "truth.json")
        tm_path = td / "manual_tm.json"
        (src / "manual_tm.json").replace(tm_path); (src / "truth.json").replace(td / "truth.json")
        check("¥9,870" in truth["table"]["keep"] and "—" in truth["financial"]["keep"], "truth.json decoded wrongly")
        tm = make_fixtures.load_truth(tm_path)
        check(tm["Monthly visits"] == "每月到访", "manual_tm.json decoded wrongly")
        # a manual TM saved by Windows Notepad / Excel with a UTF-8 BOM must work too
        bom = td / "tm_bom.json"; bom.write_bytes(b"\xef\xbb\xbf" + tm_path.read_bytes())
        st = td / "state"
        files = ["table.pdf", "toc.pdf"] + ([UNICODE_NAME] if utf8_fs else [])
        for f in files:
            print("STAGE: CLI plan/translate/render", f.encode("ascii", "backslashreplace").decode())
            check(cli(["plan", str(src), "--state", str(st), "--no-ocr", "--files", f]) == 0, "plan " + f)
            check(cli(["translate", str(src), "--state", str(st), "--backend", "manual", "--manual-tm", str(bom),
                       "--max-chars", "9999", "--files", f]) == 0, "translate " + f)
            check(cli(["render", str(src), "--state", str(st), "--backend", "manual", "--manual-tm", str(bom),
                       "--files", f]) == 0, "render " + f)
        qa = json.loads((st / "qa" / "table.pdf.json").read_text(encoding="utf-8"))
        check(qa["status"] == "pass", "table.pdf status " + qa["status"])
        import pymupdf
        with pymupdf.open(st / "out" / "table.pdf") as o:
            words = o[0].get_text()
        for k in truth["table"]["keep"]:
            check(k in words, "kept figure missing in output: " + k)
        check("每月到访" in words, "translation not drawn")
        check(cli(["report", str(src), "--state", str(st), "--out", str(td / "report.md")]) == 0, "report")
        rep = (td / "report.md").read_text(encoding="utf-8")
        check("table.pdf" in rep, "report missing")
        if utf8_fs:
            check(UNICODE_NAME in rep, "report lost the unicode file name")
        # a manual TM in a legacy code page is rejected with a clear message, not mis-decoded
        legacy = td / "tm_cp1252.json"
        legacy.write_bytes(json.dumps({"Contents": "Caf\u00e9 \u00a5"}, ensure_ascii=False).encode("cp1252"))
        check(cli(["translate", str(src), "--state", str(st), "--backend", "manual", "--manual-tm", str(legacy),
                   "--max-chars", "99", "--files", "toc.pdf"]) == 1, "non-UTF-8 manual TM must be an error")
    own = [w for w in _seen if _own(w[0])]
    other = sorted({(Path(w[0]).name, w[1]) for w in _seen if not _own(w[0])})
    print("EncodingWarnings from other code (not failing):", other or "none")
    if own:
        for f, n, m in own:
            print("FAIL: implicit default encoding in project code:",
                  f"{Path(f).name}:{n}: {m}".encode("ascii", "backslashreplace").decode())
        sys.exit(2)
    print("OK")


if __name__ == "__main__":
    run()
