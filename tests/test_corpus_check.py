"""tools/corpus_check.py and tools/corpus_fetch.py: the real-PDF corpus is a manifest plus a
local cache (docs/testing/REAL_PDF_CORPUS.md). Offline: a synthetic PDF and a fake opener."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import corpus_check  # noqa: E402
import corpus_fetch  # noqa: E402

sys.path.remove(str(ROOT / "tools"))


def _entry(p: Path, **kw):
    d = p.read_bytes()
    e = {"id": "sample", "file": p.name, "url": "https://example.org/x.pdf", "sha256": hashlib.sha256(d).hexdigest(),
         "bytes": len(d), "title": "Sample", "licence": "CC0-1.0", "licence_evidence_url": "https://example.org/licence",
         "checked_on": "2026-11-13", "checked_by": "test", "category": "born-digital", "pages": "1"}
    e.update(kw); return e


@pytest.fixture
def setup(corpus, tmp_path):
    man = tmp_path / "corpus 语料"; man.mkdir()
    cache = tmp_path / "cache 缓存"; cache.mkdir()
    shutil.copy(corpus["src"] / "table.pdf", cache / "sample.pdf")
    return man, cache


def _write(folder, entries):
    (folder / "MANIFEST.json").write_text(json.dumps({"documents": entries}, ensure_ascii=False), encoding="utf-8")


def test_valid_manifest_with_and_without_cache(setup):
    man, cache = setup
    _write(man, [_entry(cache / "sample.pdf")])
    assert corpus_check.check(man) == []
    assert corpus_check.check(man, cache) == []
    (cache / "sample.pdf").unlink()
    assert corpus_check.check(man, cache) == []                 # a missing cached file is not an error


@pytest.mark.parametrize("change, expect", [
    ({"licence": "free-to-read"}, "not on the allow-list"),
    ({"licence_evidence_url": ""}, "licence_evidence_url"),
    ({"sha256": "0" * 63}, "64 hex digits"),
    ({"url": "http://example.org/x.pdf"}, "https://"),
    ({"file": "../x.pdf"}, "plain .pdf file name"),
    ({"pages": "3-1"}, "pages"),
    ({"bytes": 99 * 1024 * 1024}, "larger than"),
    ({"id": ""}, "'id' missing"),
])
def test_invalid_entries_are_reported(setup, change, expect):
    man, cache = setup
    _write(man, [_entry(cache / "sample.pdf", **change)])
    assert any(expect in p for p in corpus_check.check(man)), corpus_check.check(man)


def test_cached_file_must_match_and_pdfs_do_not_belong_next_to_the_manifest(setup):
    man, cache = setup
    _write(man, [_entry(cache / "sample.pdf", sha256="0" * 64)])
    assert any("cached file SHA-256" in p for p in corpus_check.check(man, cache))
    _write(man, [_entry(cache / "sample.pdf")])
    shutil.copy(cache / "sample.pdf", man / "stray.pdf")
    assert corpus_check.check(man) == ["stray.pdf: PDFs are not stored in the repository (cache only)"]
    assert corpus_check.check(man.parent / "nowhere") == ["MANIFEST.json missing"]


def test_repository_manifest_is_valid_and_holds_no_pdf():
    real = ROOT / "tests" / "corpus"
    assert corpus_check.check(real) == []
    assert not list(real.glob("*.pdf"))
    for e in corpus_fetch.load_manifest():
        assert e["url"].startswith("https://") and e["licence"] in corpus_check.ALLOWED


# ------------------------------------------------------------------ corpus_fetch
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_stores_only_a_file_that_matches_the_manifest(setup, tmp_path):
    man, cache = setup
    data = (cache / "sample.pdf").read_bytes()
    e = _entry(cache / "sample.pdf")
    dest = tmp_path / "dl"
    assert corpus_fetch.fetch(e, dest, opener=lambda rq, timeout=0: _Resp(data)) is None
    assert (dest / "sample.pdf").read_bytes() == data and corpus_fetch.verify(dest / "sample.pdf", e) is None
    assert [p.name for p in dest.iterdir()] == ["sample.pdf"]                # no temporary file left


@pytest.mark.parametrize("payload,expect", [
    (b"%PDF-1.4 a revised form", "the published file changed"),              # other content
    (b"x" * 10 ** 6, "larger than the manifest size"),                       # never stored beyond the listed size
])
def test_changed_upstream_file_is_rejected_and_not_kept(setup, tmp_path, payload, expect):
    man, cache = setup
    e = _entry(cache / "sample.pdf")
    dest = tmp_path / "dl"
    why = corpus_fetch.fetch(e, dest, opener=lambda rq, timeout=0: _Resp(payload))
    assert expect in why and list(dest.iterdir()) == []


def test_network_error_and_non_https_sources(setup, tmp_path):
    man, cache = setup
    e = _entry(cache / "sample.pdf")

    def down(rq, timeout=0):
        raise urllib.error.URLError("no route")
    assert "download failed" in corpus_fetch.fetch(e, tmp_path / "dl", opener=down)
    called = []
    assert "only https" in corpus_fetch.fetch(dict(e, url="http://example.org/x.pdf"), tmp_path / "dl",
                                              opener=lambda *a, **k: called.append(1))
    assert called == [] and list((tmp_path / "dl").iterdir()) == []


def test_check_mode_reports_missing_documents_without_network(tmp_path, monkeypatch, capsys):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    assert corpus_fetch.main(["--check", "--dir", str(tmp_path / "empty")]) == 1
    out = capsys.readouterr().out
    assert out.count("MISSING") == len(corpus_fetch.load_manifest()) and "0 of" in out
    assert corpus_fetch.main(["--only", "no-such-id"]) == 2


def test_cache_folder_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PATT_CORPUS_DIR", str(tmp_path / "c"))
    assert corpus_fetch.cache_dir() == tmp_path / "c"
    monkeypatch.delenv("PATT_CORPUS_DIR"); monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "x"))
    assert corpus_fetch.cache_dir() == tmp_path / "x" / "patt-pdf" / "corpus"
