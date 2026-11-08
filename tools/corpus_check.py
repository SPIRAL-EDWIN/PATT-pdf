"""Validate a real-PDF corpus folder against docs/testing/REAL_PDF_CORPUS.md (standard library only).

Usage:  python tools/corpus_check.py tests/corpus
Checks: MANIFEST.json exists and lists exactly the PDFs in the folder; every entry has the
required provenance/licence fields; SHA-256 and size match; licence is on the allow-list or
marked as an explicit permission. Exit 0 = valid, 1 = problems (listed), 2 = usage error.
It does not judge whether a licence statement is true; that is a human review step.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REQUIRED = ("file", "sha256", "bytes", "source_url", "licence", "licence_evidence_url", "checked_on",
            "checked_by", "category", "expected")
ALLOWED = {"public-domain", "us-federal-work", "CC0-1.0", "CC-BY-4.0", "explicit-permission"}
MAX_FILE, MAX_TOTAL = 2 * 1024 * 1024, 20 * 1024 * 1024


def check(folder: Path) -> list[str]:
    problems = []
    man = folder / "MANIFEST.json"
    if not man.is_file():
        return [f"{man.name} missing"]
    try:
        entries = json.loads(man.read_text(encoding="utf-8"))["documents"]
    except (ValueError, KeyError, TypeError) as e:
        return [f"{man.name} unreadable: {e}"]
    pdfs = {p.name for p in folder.glob("*.pdf")}
    listed = {e.get("file") for e in entries if isinstance(e, dict)}
    for extra in sorted(pdfs - listed):
        problems.append(f"{extra}: PDF without manifest entry")
    total = 0
    for e in entries:
        name = e.get("file", "?")
        for k in REQUIRED:
            if not e.get(k):
                problems.append(f"{name}: field '{k}' missing or empty")
        if e.get("licence") and e["licence"] not in ALLOWED:
            problems.append(f"{name}: licence '{e['licence']}' not on the allow-list {sorted(ALLOWED)}")
        p = folder / name
        if not p.is_file():
            problems.append(f"{name}: listed but file missing"); continue
        data = p.read_bytes(); total += len(data)
        if hashlib.sha256(data).hexdigest() != e.get("sha256"):
            problems.append(f"{name}: SHA-256 does not match the manifest")
        if len(data) != e.get("bytes"):
            problems.append(f"{name}: size does not match the manifest")
        if len(data) > MAX_FILE:
            problems.append(f"{name}: larger than {MAX_FILE} bytes")
    if total > MAX_TOTAL:
        problems.append(f"corpus is {total} bytes (limit {MAX_TOTAL})")
    return problems


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__); return 2
    problems = check(Path(argv[0]))
    for p in problems:
        print("problem: " + p)
    print("corpus OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
