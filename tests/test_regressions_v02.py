"""Regression tests for defects reproduced in v0.1 (see docs/STATUS.md).

They drive the real CLI (`patt_pdf.cli.main`) where possible and assert externally
observable results: exit codes, published files, rendered text, QA status. Offline only.
"""
from __future__ import annotations

import json
import os
import shutil

import pymupdf
import pytest

from fakes import FakeMT
from patt_pdf.cli import main


def cli(*args):
    return main([str(a) for a in args])


def text_of(path):
    with pymupdf.open(path) as d:
        return "".join(p.get_text() for p in d)


# ---------------------------------------------------------------- P0-1 cache isolation
def test_pseudo_output_is_never_reused_or_published(mini, fonts_ready):
    s, st, tm = mini["src"], mini["state"], mini["manual_tm"]
    assert cli("plan", s, "--state", st, "--no-ocr") == 0
    assert cli("translate", s, "--state", st, "--backend", "pseudo", "--max-chars", 99999) == 0
    # the pseudo translations must not count as done for the manual identity
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999) in (0, 2)
    # rendering with the pseudo identity: FAIL (not publishable), exit 2
    assert cli("render", s, "--state", st, "--backend", "pseudo", "--files", "toc.pdf") == 2
    q = json.loads((st / "qa" / "toc.pdf.json").read_text(encoding="utf-8"))
    assert q["status"] == "fail" and any(i["issue"] == "not_publishable_backend" for i in q["pages"][0]["issues"])
    assert cli("publish", s, "--state", st, "--dest", mini["tmp"] / "pub", "--files", "toc.pdf") == 2
    assert not (mini["tmp"] / "pub" / "toc.pdf").exists()
    # rendering with the manual identity uses manual text, not pseudo text
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "toc.pdf") in (0, 3)
    t = text_of(st / "out" / "toc.pdf")
    assert "目录" in t and "占位中文" not in t


def test_switching_identity_requires_new_translation(mini, fonts_ready):
    """A cache for deepl+glossary A must not satisfy deepl+glossary B (here: FakeMT config)."""
    from patt_pdf.jobs import Workspace, estimate, plan_file, translate
    ws = Workspace(mini["src"], mini["state"])
    files = ws.sources()
    for r in files:
        plan_file(ws, r, ocr=False)
    a, b = FakeMT(name="deepl", glossary="A"), FakeMT(name="deepl", glossary="B")
    assert a.namespace != b.namespace
    s1 = translate(ws, files, a, max_chars=99999)
    assert s1["outcome"] == "complete"
    assert estimate(ws, files, a.namespace)["chars"] == 0          # legitimate reuse
    assert estimate(ws, files, b.namespace)["chars"] == s1["translated_chars"]   # B starts from zero


def test_legacy_tm_records_are_not_used_until_adopted(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, estimate, plan_file
    ws = Workspace(mini["src"], mini["state"])
    plan_file(ws, "toc.pdf", ocr=False)
    (ws.state / "tm.jsonl").write_text(json.dumps({"src": "Contents", "tgt": "伪目录", "origin": "pseudo"},
                                                  ensure_ascii=False) + "\n", encoding="utf-8")
    fake = FakeMT()
    before = estimate(ws, ["toc.pdf"], fake.namespace)
    assert "Contents" in before["texts"]                            # v0.1 record ignored
    assert cli("tm", "info", "--state", ws.state) == 0


def test_override_file_wins_but_is_reported(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, translate
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "toc.pdf", ocr=False)
    fake = FakeMT(); translate(ws, ["toc.pdf"], fake, max_chars=9999)
    tm = ws.tm(overrides={"Contents": "目录（人工）"})
    assert tm.get("Contents", fake.namespace) == ("目录（人工）", "override")


# ---------------------------------------------------------------- P0-2 stale plans
def _replace_with_other_pdf(path, text="Completely different page"):
    d = pymupdf.open(); p = d.new_page(width=842, height=595); p.insert_text((300, 400), text, fontsize=20)
    tmp = str(path) + ".new"; d.save(tmp); os.replace(tmp, path)


def test_changed_source_is_detected_everywhere(mini, fonts_ready):
    s, st = mini["src"], mini["state"]
    assert cli("plan", s, "--state", st, "--no-ocr") == 0
    assert cli("translate", s, "--state", st, "--backend", "pseudo", "--max-chars", 99999) == 0
    _replace_with_other_pdf(s / "toc.pdf")
    assert cli("estimate", s, "--state", st, "--backend", "pseudo") == 1
    assert cli("translate", s, "--state", st, "--backend", "pseudo", "--max-chars", 99999) == 1
    assert cli("render", s, "--state", st, "--backend", "pseudo", "--files", "toc.pdf") == 1
    q = json.loads((st / "qa" / "toc.pdf.json").read_text(encoding="utf-8"))
    assert q["status"] == "error" and "changed" in q["error"]
    # re-planning fixes it, and the new content is what gets planned
    assert cli("plan", s, "--state", st, "--no-ocr", "--files", "toc.pdf") == 0
    plan = json.loads((st / "plans" / "toc.pdf.json").read_text(encoding="utf-8"))
    assert "Completely different page" in json.dumps(plan)


def test_page_count_change_and_missing_source(mini, fonts_ready):
    from patt_pdf.jobs import StalePlan, Workspace, load_plan, plan_file, plan_state
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "toc.pdf", ocr=False)
    d = pymupdf.open(mini["src"] / "toc.pdf"); d.new_page(); tmp = str(mini["src"] / "toc.pdf") + ".x"
    d.save(tmp); d.close(); os.replace(tmp, mini["src"] / "toc.pdf")
    assert plan_state(ws, "toc.pdf")[0] == "stale"
    with pytest.raises(StalePlan):
        load_plan(ws, "toc.pdf")
    (mini["src"] / "toc.pdf").unlink()
    assert plan_state(ws, "toc.pdf")[0] == "source_missing"


def test_ocr_setting_change_forces_replan(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file
    ws = Workspace(mini["src"], mini["state"])
    assert plan_file(ws, "toc.pdf", ocr=False)["status"] == "planned"
    assert plan_file(ws, "toc.pdf", ocr=False)["status"] == "cached"
    assert plan_file(ws, "toc.pdf", ocr=True)["status"] == "planned"       # setting changed → re-plan


def test_touch_without_content_change_keeps_plan(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, plan_state
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "toc.pdf", ocr=False)
    os.utime(mini["src"] / "toc.pdf", None)                                  # mtime changes, bytes don't
    assert plan_state(ws, "toc.pdf")[0] == "ok"


# ---------------------------------------------------------------- P0-3 status semantics
def test_image_unverified_is_not_pass_and_not_published(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate, publish
    ws = Workspace(mini["src"], mini["state"])
    plan_file(ws, "image_text.pdf", ocr=False)                 # OCR off → image cannot be inspected
    fake = FakeMT(); translate(ws, ["image_text.pdf"], fake, max_chars=9999)
    q = render_file(ws, "image_text.pdf", fake.namespace)
    assert q["status"] == "unverified" and q["pass"] is False
    r = publish(ws, ["image_text.pdf"], mini["tmp"] / "pub")
    assert not r[0]["published"] and "unverified" in r[0]["why"]
    r = publish(ws, ["image_text.pdf"], mini["tmp"] / "pub", min_status="review")
    assert not r[0]["published"]                                 # unverified is worse than review


def test_residual_check_skipped_is_unverified(mini, fonts_ready, corpus):
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    from conftest import HAS_OCR
    if not HAS_OCR:
        pytest.skip("needs OCR to plan a vector page")
    shutil.copy(corpus["src"] / "vector_glyphs.pdf", mini["src"] / "vector_glyphs.pdf")
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "vector_glyphs.pdf", ocr=True)
    fake = FakeMT(); translate(ws, ["vector_glyphs.pdf"], fake, max_chars=9999)
    q = render_file(ws, "vector_glyphs.pdf", fake.namespace, ocr_qa=False)
    assert q["status"] == "unverified"


def test_accepting_a_limitation_is_recorded_and_stays_review(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, publish, render_file, translate
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "image_text.pdf", ocr=False)
    fake = FakeMT(); translate(ws, ["image_text.pdf"], fake, max_chars=9999)
    assert cli("accept", mini["src"], "--state", ws.state, "--file", "image_text.pdf", "--page", "1",
               "--issue", "image_not_inspected", "--note", "decorative photo, no text") == 0
    q = render_file(ws, "image_text.pdf", fake.namespace)
    assert q["status"] == "review"
    assert publish(ws, ["image_text.pdf"], mini["tmp"] / "p1")[0]["published"] is False          # default: pass only
    assert publish(ws, ["image_text.pdf"], mini["tmp"] / "p2", min_status="review")[0]["published"] is True
    from patt_pdf.report import markdown
    assert "decorative photo, no text" in markdown(ws, ["image_text.pdf"])
    with pytest.raises(ValueError):
        ws.accept("image_text.pdf", "1", "number_or_url", "never allowed")


def test_publish_refuses_output_of_older_source(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, publish, render_file, translate
    ws = Workspace(mini["src"], mini["state"]); plan_file(ws, "rotated.pdf", ocr=False)
    fake = FakeMT(); translate(ws, ["rotated.pdf"], fake, max_chars=9999)
    assert render_file(ws, "rotated.pdf", fake.namespace)["status"] == "pass"
    _replace_with_other_pdf(mini["src"] / "rotated.pdf")
    r = publish(ws, ["rotated.pdf"], mini["tmp"] / "pub")
    assert not r[0]["published"] and "source changed" in r[0]["why"]


# ---------------------------------------------------------------- P1-1 exit codes, retry
def test_exit_codes(mini, fonts_ready):
    s, st, tm = mini["src"], mini["state"], mini["manual_tm"]
    assert cli("plan", s, "--state", st, "--no-ocr") == 0
    # budget refusal → 2
    assert cli("translate", s, "--state", st, "--backend", "pseudo", "--max-chars", 3) == 2
    # deepl without --yes → 1, no key needed
    assert cli("translate", s, "--state", st, "--backend", "deepl", "--max-chars", 10) == 1
    # a manual TM that lacks a segment → partial translation → 2, and rendering that file → fail → 2
    import json as _j
    partial_tm = mini["tmp"] / "partial_tm.json"
    full = _j.loads(tm.read_text(encoding="utf-8")); full.pop("Total spending")
    partial_tm.write_text(_j.dumps(full, ensure_ascii=False), encoding="utf-8")
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", partial_tm, "--max-chars", 99999) == 2
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", partial_tm, "--files", "financial.pdf") == 2
    # complete manual TM → 0
    assert cli("translate", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999) == 0
    # fully passing file → 0
    assert cli("render", s, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "rotated.pdf") == 0
    # damaged input → plan exits 1, others still planned
    (s / "broken.pdf").write_bytes(b"%PDF-1.7\nnot really")
    assert cli("plan", s, "--state", st, "--no-ocr") == 1
    assert (st / "plans" / "toc.pdf.json").exists()


def test_failed_page_is_retried_and_good_pages_reused(mini, fonts_ready, monkeypatch):
    import patt_pdf.analyze as A
    from patt_pdf.jobs import Workspace, plan_file
    d = pymupdf.open(mini["src"] / "toc.pdf"); d.insert_pdf(pymupdf.open(mini["src"] / "rotated.pdf"))
    d.save(mini["src"] / "two.pdf"); d.close()
    ws = Workspace(mini["src"], mini["state"])
    real = A.plan_page
    calls = []
    failures_left = {1: 1}                          # page index 1 fails exactly once

    def flaky(pg, pno, ocr=True):
        calls.append(pno)
        if failures_left.get(pno, 0) > 0:
            failures_left[pno] -= 1
            raise RuntimeError("transient failure")
        return real(pg, pno, ocr)
    monkeypatch.setattr(A, "plan_page", flaky)
    st1 = plan_file(ws, "two.pdf", ocr=False)
    assert st1["status"] == "planned_with_errors" and st1["page_errors"] == [2]
    calls.clear()
    st2 = plan_file(ws, "two.pdf", ocr=False)
    assert st2["status"] == "planned" and st2["reused_pages"] == 1 and calls == [1]   # only the failed page re-run
    assert plan_file(ws, "two.pdf", ocr=False)["status"] == "cached"


def test_interrupted_planning_resumes(mini, fonts_ready):
    from patt_pdf.jobs import Workspace, plan_file, plan_state
    d = pymupdf.open(mini["src"] / "toc.pdf")
    for _ in range(3):
        d.insert_pdf(pymupdf.open(mini["src"] / "rotated.pdf"))
    d.save(mini["src"] / "four.pdf"); d.close()
    ws = Workspace(mini["src"], mini["state"])
    st = plan_file(ws, "four.pdf", ocr=False, deadline=0.0001)       # deadline already passed: nothing planned
    assert st["status"] == "partial" and plan_state(ws, "four.pdf")[0] in ("missing", "partial")
    st = plan_file(ws, "four.pdf", ocr=False)
    assert st["status"] == "planned" and st["pages"] == 4


# ---------------------------------------------------------------- P1-2 bounded submission, stop, accounting
def _planned_ws(mini, n_files=1):
    from patt_pdf.jobs import Workspace, plan_file
    ws = Workspace(mini["src"], mini["state"])
    for r in ws.sources():
        plan_file(ws, r, ocr=False)
    return ws


def test_quota_error_stops_submission(mini, fonts_ready):
    from patt_pdf.jobs import translate
    ws = _planned_ws(mini)
    fake = FakeMT(script={0: "quota"})
    s = translate(ws, ws.sources(), fake, max_chars=99999, batch_items=1, workers=1)
    assert s["stopped"].startswith("fake quota") and s["outcome"] in ("failed", "partial")
    assert fake.calls == 1                         # nothing submitted after the quota error
    assert s["batches_submitted"] == 1 and s["batches_total"] > 1


def test_inflight_bound_and_accounting(mini, fonts_ready):
    from patt_pdf.jobs import translate
    ws = _planned_ws(mini)
    fake = FakeMT(script={i: 0.05 for i in range(40)})
    s = translate(ws, ws.sources(), fake, max_chars=99999, batch_items=1, workers=3)
    assert fake.max_inflight <= 3
    assert s["outcome"] == "complete" and s["submitted_chars"] == fake.received_chars == s["translated_chars"]
    assert s["submitted_chars"] <= s["max_chars"]


def test_auth_error_with_requests_in_flight(mini, fonts_ready):
    """Batches already running when a stop happens are awaited and accounted, not 'cancelled'."""
    from patt_pdf.jobs import translate
    ws = _planned_ws(mini)
    fake = FakeMT(script={0: "auth", 1: 0.2, 2: 0.2})
    s = translate(ws, ws.sources(), fake, max_chars=99999, batch_items=1, workers=3)
    assert "auth" in s["stopped"]
    assert fake.calls == 3                         # 3 were in flight; none submitted afterwards
    assert s["batches_completed"] == 2 and s["batches_failed"] == 1
    assert s["submitted_chars"] == fake.received_chars


def test_transient_failure_counts_as_possibly_billed_and_resumes(mini, fonts_ready):
    from patt_pdf.jobs import translate
    ws = _planned_ws(mini)
    fake = FakeMT(script={1: "error"})
    s = translate(ws, ws.sources(), fake, max_chars=99999, batch_items=1, workers=1)
    assert s["outcome"] == "partial" and s["batches_failed"] == 1 and s["possibly_billed_chars"] > 0
    fake2 = FakeMT()
    s2 = translate(ws, ws.sources(), fake2, max_chars=99999, batch_items=1, workers=1)
    assert s2["outcome"] == "complete" and fake2.calls == 1           # only the failed batch is resent


def test_budget_uses_quota_reserve(mini, fonts_ready):
    from patt_pdf.jobs import translate
    ws = _planned_ws(mini)
    fake = FakeMT(usage={"character_count": 990_000, "character_limit": 1_000_000})
    s = translate(ws, ws.sources(), fake, max_chars=99999, reserve=9_900)
    assert s["outcome"] == "refused" and fake.calls == 0
