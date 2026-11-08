"""tools/corpus_check.py: rules for adding real, redistributable PDFs (docs/testing/REAL_PDF_CORPUS.md).
Uses a synthetic PDF; no real document is part of the repository yet."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import corpus_check  # noqa: E402

sys.path.remove(str(ROOT / "tools"))


def _entry(p: Path, **kw):
    d = p.read_bytes()
    e = {"file": p.name, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d), "source_url": "https://example.org/x.pdf",
         "licence": "CC0-1.0", "licence_evidence_url": "https://example.org/licence", "checked_on": "2026-11-08",
         "checked_by": "test", "category": "born-digital", "expected": {"1": "review"}}
    e.update(kw); return e


@pytest.fixture
def folder(corpus, tmp_path):
    f = tmp_path / "corpus 语料"; f.mkdir()
    shutil.copy(corpus["src"] / "table.pdf", f / "sample.pdf")
    return f


def _write(folder, entries):
    (folder / "MANIFEST.json").write_text(json.dumps({"documents": entries}, ensure_ascii=False), encoding="utf-8")


def test_valid_manifest(folder):
    _write(folder, [_entry(folder / "sample.pdf")])
    assert corpus_check.check(folder) == []


@pytest.mark.parametrize("change, expect", [
    ({"licence": "free-to-read"}, "not on the allow-list"),
    ({"licence_evidence_url": ""}, "licence_evidence_url"),
    ({"sha256": "0" * 64}, "SHA-256"),
    ({"bytes": 1}, "size"),
])
def test_invalid_entries_are_reported(folder, change, expect):
    _write(folder, [_entry(folder / "sample.pdf", **change)])
    assert any(expect in p for p in corpus_check.check(folder))


def test_unlisted_pdf_and_missing_manifest(folder):
    assert corpus_check.check(folder) == ["MANIFEST.json missing"]
    shutil.copy(folder / "sample.pdf", folder / "other.pdf")
    _write(folder, [_entry(folder / "sample.pdf")])
    assert corpus_check.check(folder) == ["other.pdf: PDF without manifest entry"]


def test_repository_corpus_if_present():
    """Runs on the real corpus once it exists (tests/corpus); until then there is nothing to check."""
    real = ROOT / "tests" / "corpus"
    if not real.exists():
        pytest.skip("no real-PDF corpus in the repository yet (docs/testing/REAL_PDF_CORPUS.md)")
    assert corpus_check.check(real) == []
