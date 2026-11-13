"""Validate the real-PDF corpus manifest against docs/testing/REAL_PDF_CORPUS.md (standard library only).

Usage:  python tools/corpus_check.py tests/corpus [CACHE_DIR]

The repository holds only the manifest; the PDFs live in a local cache filled by
tools/corpus_fetch.py. Checks: MANIFEST.json exists; every entry has the required
provenance and licence fields, an https source, a well-formed SHA-256, a licence on the
allow-list, unique ids and file names, sizes within the limits; no PDF is stored next to the
manifest (the repository must stay free of third-party documents). With CACHE_DIR, files
present there must match SHA-256 and size (missing files are not an error).
Exit 0 = valid, 1 = problems (listed), 2 = usage error.
It does not judge whether a licence statement is true; that is a human review step.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED = ("id", "file", "url", "sha256", "bytes", "title", "licence", "licence_evidence_url", "checked_on",
            "checked_by", "category", "pages")
ALLOWED = {"public-domain", "us-federal-work", "CC0-1.0", "CC-BY-4.0", "explicit-permission"}
MAX_FILE, MAX_TOTAL = 4 * 1024 * 1024, 16 * 1024 * 1024


def check(folder: Path, cache: Path | None = None) -> list[str]:
    problems = []
    man = folder / "MANIFEST.json"
    if not man.is_file():
        return [f"{man.name} missing"]
    try:
        entries = json.loads(man.read_text(encoding="utf-8"))["documents"]
    except (ValueError, KeyError, TypeError) as e:
        return [f"{man.name} unreadable: {e}"]
    for extra in sorted(p.name for p in folder.glob("*.pdf")):
        problems.append(f"{extra}: PDFs are not stored in the repository (cache only)")
    seen_id, seen_file, total = set(), set(), 0
    for e in entries:
        name = e.get("id") or e.get("file", "?")
        for k in REQUIRED:
            if not e.get(k):
                problems.append(f"{name}: field '{k}' missing or empty")
        if e.get("id") in seen_id or e.get("file") in seen_file:
            problems.append(f"{name}: duplicate id or file name")
        seen_id.add(e.get("id")); seen_file.add(e.get("file"))
        if e.get("file") and (Path(e["file"]).name != e["file"] or not e["file"].lower().endswith(".pdf")):
            problems.append(f"{name}: 'file' must be a plain .pdf file name")
        for k in ("url", "licence_evidence_url"):
            if e.get(k) and not str(e[k]).startswith("https://"):
                problems.append(f"{name}: '{k}' must be an https:// address")
        if e.get("sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(e["sha256"])):
            problems.append(f"{name}: sha256 is not 64 hex digits")
        if e.get("licence") and e["licence"] not in ALLOWED:
            problems.append(f"{name}: licence '{e['licence']}' not on the allow-list {sorted(ALLOWED)}")
        if e.get("pages"):
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
                from patt_pdf.pages import PageSelectionError, parse
                try:
                    parse(str(e["pages"]))
                except PageSelectionError as err:
                    problems.append(f"{name}: pages: {err}")
            except ImportError:
                pass
            finally:
                sys.path.pop(0)
        size = e.get("bytes") if isinstance(e.get("bytes"), int) else 0
        total += size
        if size > MAX_FILE:
            problems.append(f"{name}: larger than {MAX_FILE} bytes")
        if cache is not None and e.get("file"):
            p = cache / e["file"]
            if p.is_file():
                data = p.read_bytes()
                if hashlib.sha256(data).hexdigest() != e.get("sha256"):
                    problems.append(f"{name}: cached file SHA-256 does not match the manifest")
                if len(data) != e.get("bytes"):
                    problems.append(f"{name}: cached file size does not match the manifest")
    if total > MAX_TOTAL:
        problems.append(f"corpus is {total} bytes (limit {MAX_TOTAL})")
    return problems


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        print(__doc__); return 2
    problems = check(Path(argv[0]), Path(argv[1]) if len(argv) == 2 else None)
    for p in problems:
        print("problem: " + p)
    print("corpus OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
