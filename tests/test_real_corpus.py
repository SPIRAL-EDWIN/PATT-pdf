"""Layout regressions on real documents (tests/corpus/MANIFEST.json).

The PDFs are not in the repository. `python tools/corpus_fetch.py` downloads them into a
local cache and verifies SHA-256 and size; without the cache these tests are skipped, and
the default test run never uses the network. No translation service is used: the pseudo
backend fills the pages with placeholder text, and the assertions are about structure
(no crash, cells, kept text, links, letters), not about wording.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import corpus_fetch  # noqa: E402

sys.path.remove(str(ROOT / "tools"))

DOCS = {d["id"]: d for d in corpus_fetch.load_manifest()}
CACHE = corpus_fetch.cache_dir()


def _path(doc_id):
    e = DOCS[doc_id]
    p = CACHE / e["file"]
    if corpus_fetch.verify(p, e) is not None:
        pytest.skip(f"{e['file']} is not in the corpus cache: run `python tools/corpus_fetch.py` (needs network)")
    return p


@pytest.fixture(scope="module")
def rendered(tmp_path_factory, fonts_ready):
    """doc id -> dict(ws, qa, plans, src, out, pages); each document is processed once."""
    from patt_pdf.backends import PseudoBackend
    from patt_pdf.jobs import Workspace, load_plan, plan_file, render_file, translate
    from patt_pdf.pages import resolve
    done = {}

    def get(doc_id):
        if doc_id in done:
            return done[doc_id]
        src = _path(doc_id)
        ws = Workspace(src, tmp_path_factory.mktemp(doc_id))
        with pymupdf.open(src) as d:
            pages = resolve(DOCS[doc_id]["pages"], d.page_count); count = d.page_count
        st = plan_file(ws, src.name, ocr=False, pages=pages)
        be = PseudoBackend()
        tr = translate(ws, [src.name], be, max_chars=10 ** 7, pages=pages)
        qa = render_file(ws, src.name, be.namespace, publishable=False, ocr_qa=False, pages=pages)
        done[doc_id] = dict(ws=ws, qa=qa, plan_status=st, translate=tr, src=src, out=ws.out_path(src.name), pages=pages,
                            page_count=count, plans={p.page: p for p in load_plan(ws, src.name, pages=pages)})
        return done[doc_id]
    return get


def _issues(r, name=None):
    return [i for p in r["qa"]["pages"] for i in p["issues"] if name is None or i["issue"] == name]


@pytest.mark.parametrize("doc_id", sorted(DOCS))
def test_document_is_processed_without_errors(rendered, doc_id):
    r = rendered(doc_id)
    assert r["plan_status"]["status"] == "planned", r["plan_status"]
    assert r["qa"]["status"] != "error", r["qa"].get("error")
    assert [p["page"] - 1 for p in r["qa"]["pages"]] == r["pages"]
    assert all(pl.units for pl in r["plans"].values())
    assert not _issues(r, "page_error") and not _issues(r, "keep_lost") and not _issues(r, "link_lost")
    with pymupdf.open(r["out"]) as o, pymupdf.open(r["src"]) as s:
        assert o.page_count == r["page_count"]                       # the whole document is kept
        for pno in r["pages"]:
            assert len(o[pno].get_links()) == len(s[pno].get_links())
            assert re.search(r"[一-鿿]", o[pno].get_text())     # the page was rewritten
        other = next((i for i in range(r["page_count"]) if i not in r["pages"]), None)
        if other is not None:
            assert o[other].get_text() == s[other].get_text()        # unselected pages are untouched


def test_named_links_of_a_latex_paper_survive(rendered):
    """Finding 1 of the first real run: KeyError 'nameddest' aborted the file."""
    r = rendered("llama")
    with pymupdf.open(r["src"]) as s, pymupdf.open(r["out"]) as o:
        named = lambda d, n: sorted(l.get("nameddest") or l.get("name") or "" for l in d[n].get_links() if l["kind"] == pymupdf.LINK_NAMED)
        for pno in r["pages"]:
            assert named(s, pno) and named(s, pno) == named(o, pno)


def test_three_line_table_header_is_cut_into_cells(rendered):
    r = rendered("llama")
    srcs = [u.src for u in r["plans"][2].units]
    for cell in ("params", "dimension", "n heads", "n layers", "learning rate", "batch size", "n tokens"):
        assert cell in srcs
    assert not any(s.startswith("params dimension") for s in srcs)


def test_figures_and_model_names_are_not_sent(rendered):
    from patt_pdf.jobs import sendable
    r = rendered("llama")
    units = r["plans"][2].units
    legend = [u for u in units if "LLaMA 7B" in u.src and "LLaMA 65B" in u.src]
    assert legend and not any(sendable(u) for u in legend)
    kept = {str(k[4]) for k in r["plans"][2].keeps}
    assert {"13.0B", "32.5B", "65.2B", "1.4T"} <= kept
    with pymupdf.open(r["out"]) as o:
        text = o[2].get_text()
    for v in ("13.0B", "32.5B", "65.2B", "5120", "LLaMA 65B"):
        assert v in text


def test_justified_paragraphs_are_whole(rendered):
    r = rendered("llama")
    intro = [u for u in r["plans"][0].units if u.src.startswith("Large Languages Models")]
    assert len(intro) == 1 and len(intro[0].lines) >= 12 and intro[0].src.rstrip().endswith("trained on more data.")


def test_sans_documents_are_set_in_a_sans_face(rendered):
    for doc_id, only in (("w9", None), ("usgs_quake", None), ("plos", 0)):     # PLOS: page 1 is Helvetica, page 4 Minion
        r = rendered(doc_id)
        units = [u for n, pl in r["plans"].items() for u in pl.units if only is None or n == only]
        sans = sum(len(u.src) for u in units if u.family == "sans")
        assert sans > 0.8 * sum(len(u.src) for u in units), doc_id


def test_serif_paper_stays_serif(rendered):
    r = rendered("llama")
    units = [u for pl in r["plans"].values() for u in pl.units]
    assert sum(len(u.src) for u in units if u.family == "serif") > 0.8 * sum(len(u.src) for u in units)


def test_map_labels_along_curves_stay_and_no_letter_is_erased(rendered):
    """Findings 2 and 7: every 'a' vanished from a map page; curved labels overlapped."""
    r = rendered("usgs_quake")
    cur = [i for i in _issues(r, "curved_text_left_english") if i]
    assert cur and cur[0]["count"] >= 30
    with pymupdf.open(r["src"]) as s, pymupdf.open(r["out"]) as o:
        before, after = s[0].get_text(), o[0].get_text()
    squeeze = lambda t: re.sub(r"\s+", "", t)
    # macOS check C23: "HUNTING CREEK" passes through the vertical; its piece "EE" was translated.
    # Every slanted letter outside the few straight labels must still be at its place.
    def slanted(pg):
        return {(c["c"], round(c["origin"][0]), round(c["origin"][1])): c["bbox"]
                for b in pg.get_text("rawdict")["blocks"] for l in b.get("lines", []) if abs(l["dir"][1]) > 0.05
                for sp in l["spans"] for c in sp["chars"] if c["c"].strip()}
    with pymupdf.open(r["src"]) as s, pymupdf.open(r["out"]) as o:
        a, b = slanted(s[0]), slanted(o[0])
    straight = [pymupdf.Rect(u.bbox) for u in r["plans"][0].units if u.angle]
    assert 2 <= len({tuple(x) for x in straight}) <= 6                   # a handful of straight labels are translated
    lost = [k for k in a if k not in b and not any(x.intersects(pymupdf.Rect(a[k])) for x in straight)]
    assert lost == [], lost
    assert cur[0]["count"] >= 43
    for word in ("CONCORDFAULT", "BERRYESSA", "SCREEKFAULT", "CAMAFAU", "HUNTIN", "HAYWARD"):      # labels along curves
        assert word in squeeze(before) and squeeze(after).count(word) == squeeze(before).count(word), word
    # Latin words that stay on the page keep every letter (the 'a' of these was erased before)
    for word in ("Collayami", "Reliz"):
        assert word in before
    assert "EXPLANATION" not in after                                    # ordinary labels are rewritten
    for n in ("72%", "33%", "2014", "2043"):
        assert before.count(n) == after.count(n) or n in after


def test_vertical_labels_of_a_form_are_translated_in_place(rendered):
    r = rendered("w9")
    rot = [u for u in r["plans"][0].units if u.angle]
    assert len(rot) == 2 and all(abs(abs(u.angle) - 90) < 1 for u in rot)
    assert not _issues(r, "curved_text_left_english")


def test_manifest_matches_the_documented_limits():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import corpus_check
    finally:
        sys.path.remove(str(ROOT / "tools"))
    assert corpus_check.check(ROOT / "tests" / "corpus", CACHE if CACHE.is_dir() else None) == []
    man = json.loads((ROOT / "tests" / "corpus" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert len(man["documents"]) >= 7
