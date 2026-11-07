"""Run the fixture generator and a small CLI pipeline in a child process whose default text
encoding is NOT UTF-8 (see tests/test_encoding.py). Prints only ASCII. Exit codes:
0 ok, 1 assertion failed."""
from __future__ import annotations

import json
import locale
import sys
import tempfile
import warnings
from pathlib import Path

warnings.simplefilter("error", EncodingWarning)        # any implicit default-encoding I/O fails

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import make_fixtures  # noqa: E402

from patt_pdf.cli import main as cli  # noqa: E402

UNICODE_NAME = "报告 2026 – résumé.pdf"


def check(cond, msg):
    if not cond:
        print("FAIL:", msg.encode("ascii", "backslashreplace").decode()); sys.exit(1)


def run():
    # MuPDF passes file names to the OS as UTF-8. Windows and macOS file systems are UTF-8 for
    # Python too; only a POSIX system with a legacy-locale file system encoding differs, and
    # there the non-ASCII file name is left out of this probe (documented limitation).
    utf8_fs = sys.getfilesystemencoding().lower().replace("-", "") == "utf8"
    print("default encoding:", locale.getpreferredencoding(False), "utf8_mode:", sys.flags.utf8_mode)
    with tempfile.TemporaryDirectory(prefix="patt-enc-") as td:
        td = Path(td); src = td / "in"
        make_fixtures.main(str(src))
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
    print("OK")


if __name__ == "__main__":
    run()
