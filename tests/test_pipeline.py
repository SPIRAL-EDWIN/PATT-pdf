"""End-to-end offline pipeline on the synthetic corpus, with pixel/text-level assertions."""
import numpy as np
import pymupdf
import pytest

from conftest import needs_ocr


def _crop(path, rect, dpi=110):
    with pymupdf.open(path) as d:
        pm = d[0].get_pixmap(dpi=dpi, clip=pymupdf.Rect(rect) & d[0].rect)
        return np.frombuffer(pm.samples, np.uint8).reshape(pm.h, pm.w, pm.n).astype(int)


def _out(rendered, name):
    return rendered["ws"].out_path(name)


def test_damaged_files_reported_not_fatal(rendered):
    p = rendered["plans"]
    assert p["damaged.pdf"]["status"] == "error" and "no pages" in p["damaged.pdf"]["error"]
    # a truncated file either fails to open or is reconstructed by MuPDF (version-dependent);
    # it must never be reported as a clean pass
    assert p["truncated.pdf"]["status"] == "error" or rendered["qa"]["truncated.pdf"]["status"] not in ("pass", "review")
    assert rendered["qa"]["damaged.pdf"]["status"] == "error"
    # the rest of the batch still rendered
    assert rendered["qa"]["toc.pdf"]["status"] == "pass"


def test_toc_numbers_untouched(rendered):
    """Section numbers 1,2,3,5 keep exact position and glyphs (the BabelDOC failure case)."""
    src, out = rendered["src"] / "toc.pdf", _out(rendered, "toc.pdf")
    with pymupdf.open(src) as s:
        nums = [w for w in s[0].get_text("words") if w[4] in ("1", "2", "3", "5") and w[3] - w[1] > 15]
    assert len(nums) == 4
    for w in nums:
        assert np.abs(_crop(src, w[:4]) - _crop(out, w[:4])).max() == 0, w[4]
    with pymupdf.open(out) as o:
        txt = o[0].get_text()
    assert "目录" in txt and "入门" in txt and "Contents" not in txt


def test_financial_figures_byte_identical(rendered):
    src, out = rendered["src"] / "financial.pdf", _out(rendered, "financial.pdf")
    with pymupdf.open(src) as s:
        figs = [w for w in s[0].get_text("words") if any(c.isdigit() for c in w[4]) and w[1] < 200]
    assert len(figs) == 9        # 48,210 45,975 31,604 29,388 7,950 (2,317) (1,846) 85,447 73,517
    for w in figs:
        assert np.abs(_crop(src, w[:4]) - _crop(out, w[:4])).max() == 0, w[4]
    with pymupdf.open(out) as o:
        words = [w[4] for w in o[0].get_text("words")]
    for f in ("48,210", "(2,317)", "(1,846)", "85,447", "73,517"):
        assert f in words, f
    qa = rendered["qa"]["financial.pdf"]["pages"][0]
    assert not qa["keep_changed"]
    assert not [i for i in qa["issues"] if i.get("issue") == "number_or_url"]
    assert rendered["qa"]["financial.pdf"]["status"] == "pass"


def test_url_footer_kept(rendered):
    with pymupdf.open(_out(rendered, "financial.pdf")) as o:
        assert "https://example.com/report?id=42" in o[0].get_text()


def test_cropbox_text_lands_on_page(rendered):
    """Offset CropBox: drawn Chinese must be inside the visible page, not off-page."""
    out = _out(rendered, "two_column_cropbox.pdf")
    with pymupdf.open(out) as o:
        pg = o[0]
        cjk = [w for w in pg.get_text("words") if any("一" <= ch <= "鿿" for ch in w[4])]
        assert cjk, "no Chinese drawn"
        for w in cjk:
            assert pymupdf.Rect(w[:4]).intersects(pg.rect)
        assert "doi:10.0000/example.2026.001" in pg.get_text()
        assert not [w for w in pg.get_text("words") if w[4] in ("Migrating", "Light", "pollution")]


def test_rotated_label_translated(rendered):
    with pymupdf.open(_out(rendered, "rotated.pdf")) as o:
        txt = o[0].get_text()
    assert "第1天" in txt and "Day 1" not in txt
    assert "志愿者须知" in txt


def test_translate_budget_refuses(corpus, fonts_ready, tmp_path):
    from patt_pdf.backends import PseudoBackend
    from patt_pdf.jobs import Workspace, plan_file, translate
    ws = Workspace(corpus["src"], tmp_path)
    plan_file(ws, "toc.pdf", ocr=False)
    s = translate(ws, ["toc.pdf"], PseudoBackend(), max_chars=5)
    assert s["stopped"] and "exceeds --max-chars" in s["stopped"] and s["outcome"] == "refused"
    assert s["translated_chars"] == 0 and not (tmp_path / "tm.jsonl").exists()


def test_resume_uses_cache(corpus, fonts_ready, tmp_path):
    from patt_pdf.backends import PseudoBackend
    from patt_pdf.jobs import Workspace, plan_file, translate
    ws = Workspace(corpus["src"], tmp_path)
    assert plan_file(ws, "toc.pdf", ocr=False)["status"] == "planned"
    assert plan_file(ws, "toc.pdf", ocr=False)["status"] == "cached"
    s1 = translate(ws, ["toc.pdf"], PseudoBackend(), max_chars=10_000)
    s2 = translate(ws, ["toc.pdf"], PseudoBackend(), max_chars=10_000)
    assert s1["translated_chars"] > 0 and s2["stopped"] == "nothing to translate" and s2["outcome"] == "complete"


def test_source_never_written(corpus, rendered):
    for p in corpus["src"].glob("*.pdf"):
        assert rendered["ws"].state not in p.parents
    # state inside source is refused
    from patt_pdf.jobs import Workspace
    with pytest.raises(ValueError):
        Workspace(corpus["src"], corpus["src"] / "state")


def test_publish_refuses_overwrite_and_source(rendered, tmp_path):
    from patt_pdf.jobs import publish
    ws = rendered["ws"]
    assert rendered["qa"]["toc.pdf"]["status"] == "pass"
    r1 = publish(ws, ["toc.pdf"], tmp_path / "pub", suffix=" zh-Hans")
    assert r1[0]["published"] and (tmp_path / "pub" / "toc zh-Hans.pdf").exists()
    r2 = publish(ws, ["toc.pdf"], tmp_path / "pub", suffix=" zh-Hans")
    assert not r2[0]["published"] and "not overwritten" in r2[0]["why"]
    with pytest.raises(ValueError):
        publish(ws, ["toc.pdf"], rendered["src"] / "x")


def test_image_text_is_reported(rendered):
    q = rendered["qa"]["image_text.pdf"]
    issues = [i["issue"] for i in q["pages"][0]["issues"]]
    assert {"image_text_left_english", "image_unverified", "image_not_inspected"} & set(issues)
    assert q["status"] in ("unverified", "fail") and q["pass"] is False


@needs_ocr
def test_vector_glyphs_replaced(rendered):
    qa = rendered["qa"]["vector_glyphs.pdf"]["pages"][0]
    assert qa["kind"] == "vector"
    with pymupdf.open(_out(rendered, "vector_glyphs.pdf")) as o:
        assert "光污染" in o[0].get_text()
    assert not qa["residual_en"], qa["residual_en"]
    assert any(i["issue"] == "ocr_digits_review" for i in qa["issues"])   # "Page 3 of 9" flagged


@needs_ocr
def test_scanned_page(rendered):
    qa = rendered["qa"]["scanned.pdf"]["pages"][0]
    assert qa["kind"] == "raster"
    assert not qa["keep_changed"], qa["keep_changed"]          # date 2026-11-06 untouched
    with pymupdf.open(_out(rendered, "scanned.pdf")) as o:
        assert "扫描便条" in o[0].get_text()
    assert not qa["residual_en"], qa["residual_en"]


def test_ocr_disabled_page_is_not_a_silent_pass(corpus, fonts_ready, tmp_path):
    """With --no-ocr a scanned page cannot be translated: it must FAIL with a reason, never pass."""
    from fakes import FakeMT
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    ws = Workspace(corpus["src"], tmp_path)
    plan_file(ws, "scanned.pdf", ocr=False)
    fake = FakeMT()
    translate(ws, ["scanned.pdf"], fake, max_chars=10_000)
    qa = render_file(ws, "scanned.pdf", fake.namespace, ocr_qa=False)
    p = qa["pages"][0]
    assert p["pass"] is False and p["status"] == "fail"
    assert any(i["issue"] == "page_not_processed" for i in p["issues"])


def test_pseudo_backend_output_is_flagged_by_number_check(rendered):
    """Sanity check of the QA itself: pseudo text drops scale words, so the number check must
    catch the financial sentence. (Manual TM covers it in the shared run, so test directly.)"""
    from patt_pdf.backends import PseudoBackend
    from patt_pdf.qa import number_check
    src = "Ticket revenue grew to $2.3 million in 2024, up 12.5% from 2023."
    assert number_check(src, PseudoBackend().translate([src])[0])
