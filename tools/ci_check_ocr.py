"""CI/retest helper: assert that OCR is (or is not) usable *as PATT-PDF sees it*.

    python tools/ci_check_ocr.py expect-present   # Tesseract found AND the 'eng' model is listed
    python tools/ci_check_ocr.py expect-absent    # Tesseract not found by PATT-PDF's own discovery

Uses the product's discovery (patt_pdf.osenv.find_tesseract), so a Tesseract preinstalled on a
runner image cannot silently turn a "no OCR" job into an OCR job. Exit 0 if the expectation holds,
1 otherwise. Prints only the source (PATH / env / default folder) and language list, no paths."""
from __future__ import annotations

import subprocess
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("expect-present", "expect-absent"):
        print(__doc__); return 2
    from patt_pdf.osenv import find_tesseract
    exe, how = find_tesseract()
    if argv[0] == "expect-absent":
        if exe:
            print(f"FAIL: Tesseract is available via {how}; this job must run without OCR")
            return 1
        print(f"OK: no Tesseract ({how})")
        return 0
    if not exe:
        print(f"FAIL: Tesseract not found ({how})")
        return 1
    r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    langs = [l.strip() for l in (r.stdout + r.stderr).splitlines()[1:] if l.strip()]
    if "eng" not in langs:
        print(f"FAIL: Tesseract via {how} has no 'eng' model (languages: {langs[:10]})")
        return 1
    v = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    print(f"OK: Tesseract via {how}: {(v.stdout or v.stderr).splitlines()[0]}; languages include eng")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
