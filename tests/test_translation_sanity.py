"""Unusable translations are prevented, repaired or replaced by the source text; they are
never drawn (sanity.py). Case from a real document: DeepL returned a figure legend with the
name of the target language appended ("…LLaMA 65B简体中文（大陆）").

Offline: synthetic PDF, scripted backends, no network.
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from patt_pdf import sanity
from patt_pdf.backends import Backend, BudgetExceeded
from patt_pdf.jobs import Workspace, plan_file, render_file, translate

LEGEND = "LLaMA 7B LLaMA 13B LLaMA 33B LLaMA 65B"
BAD = LEGEND + "简体中文（大陆）"          # the answer DeepL gave on 2026-11-13


# ------------------------------------------------------------------ 1. prevention
@pytest.mark.parametrize("src", [LEGEND, "13.0B", "65.2B", "3.0e−", "StrategyQA", "GPT-3", "W-9", "iPhone 15",
                                 "COVID-19 IgM/IgG", "a1111111111 a1111111111"])
def test_names_codes_and_figures_are_not_sent(src):
    assert sanity.nothing_to_translate(src)


@pytest.mark.parametrize("src", ["NOTE", "PART 2", "Table 2", "20 MILES", "Part II", "Figure 1", "Training loss",
                                 "LLaMA models", "Meta AI", "NIST CSWP 29", "PLOS ONE", "Abstract", "MA"])
def test_ordinary_words_are_still_sent(src):
    assert not sanity.nothing_to_translate(src)


# ------------------------------------------------------------------ 2. detection and local repair
def test_the_real_case_is_detected_and_repaired_to_the_source():
    assert set(sanity.suspicious(LEGEND, BAD)) == {"language_label_added", "source_plus_extra_text"}
    fixed, how = sanity.repair(LEGEND, BAD)
    assert fixed == LEGEND and how == "label_removed"


@pytest.mark.parametrize("src,tgt", [
    ("Training loss", "训练损失 简体中文"),
    ("Abstract", "摘要（简体）"),
    ("Results", "结果 zh-CN"),
    ("Model output", "模型输出 (Simplified Chinese)"),
])
def test_added_language_labels_are_removed(src, tgt):
    assert sanity.suspicious(src, tgt)
    fixed, how = sanity.repair(src, tgt)
    assert how == "label_removed" and not sanity._LABEL.search(fixed) and fixed


@pytest.mark.parametrize("src,tgt", [
    ("Training loss", "训练损失"),
    ("PLOS ONE", "《PLOS ONE》"),                                   # only punctuation added
    ("Santa", "圣诞老人"),
    ("W-9 (Rev. 3-2024)", "W-9（2024年3月修订版）"),
    ("Quoc V. Le", "Quoc V. Le"),
    ("Simplified Chinese is supported.", "支持简体中文。"),          # the source is about the language
    ("Select your language", "选择您的语言（简体中文）"),
    ("The interface was translated into Chinese (Simplified).", "界面已翻译为简体中文。"),
    ("Part I", "第一部分"),
    ("See Table 2 for details.", "详见表2。"),
])
def test_normal_translations_are_left_alone(src, tgt):
    assert sanity.suspicious(src, tgt) == []
    assert sanity.repair(src, tgt) == (tgt, "ok")


def test_text_that_cannot_be_repaired_locally_is_reported_not_guessed():
    fixed, why = sanity.repair("Model input", "Model input and a long unrelated sentence that was never in the source")
    assert fixed is None and "source_plus_extra_text" in why
    fixed, why = sanity.repair("Bay", "这是一段与原文长度完全不相称的很长很长的译文内容")
    assert fixed is None and "far_longer_than_source" in why


# ------------------------------------------------------------------ pipeline
def _page(tmp_path, lines):
    src = tmp_path / "in"; src.mkdir(exist_ok=True)
    d = pymupdf.open(); pg = d.new_page(width=460, height=320)
    for i, t in enumerate(lines):
        pg.insert_text((50, 70 + 60 * i), t, fontsize=11, fontname="helv")
    d.save(src / "a.pdf"); d.close()
    ws = Workspace(src, tmp_path / "state")
    plan_file(ws, "a.pdf", ocr=False)
    return ws


class Scripted(Backend):
    """Answers from a table; `context_answers` are used for requests that carry a context."""
    name = "scripted"
    supports_context = True

    def __init__(self, answers, context_answers=None):
        self.answers, self.context_answers = answers, context_answers or {}
        self.requests = []                       # (texts, context)

    def translate(self, texts, context=None):
        if self.meter:
            self.meter.before(sum(len(t) for t in texts), 0)
        self.requests.append((list(texts), context))
        table = self.context_answers if context is not None else self.answers
        return [table.get(t, self.answers.get(t)) for t in texts]


def _issues(qa):
    return [i for p in qa["pages"] for i in p["issues"]]


def _page_text(ws):
    with pymupdf.open(ws.out_path("a.pdf")) as o:
        return o[0].get_text()


def test_legend_of_names_is_never_sent_and_stays_on_the_page(tmp_path, fonts_ready):
    ws = _page(tmp_path, [LEGEND, "Training loss over time"])
    be = Scripted({"Training loss over time": "训练损失随时间的变化", LEGEND: BAD})
    s = translate(ws, ["a.pdf"], be, max_chars=999)
    assert s["outcome"] == "complete" and s["sent_chars"] == len("Training loss over time")
    assert all(LEGEND not in texts for texts, _ in be.requests)
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    text = _page_text(ws)
    assert LEGEND in text and "简体中文" not in text and "训练损失" in text
    assert qa["status"] == "pass", _issues(qa)


def test_label_is_removed_when_the_answer_arrives(tmp_path, fonts_ready):
    ws = _page(tmp_path, ["Training loss over time"])
    be = Scripted({"Training loss over time": "训练损失随时间的变化 简体中文（大陆）"})
    s = translate(ws, ["a.pdf"], be, max_chars=999)
    assert s["repairs"][0]["step"] == "label_removed" and len(be.requests) == 1
    assert ws.tm().get("Training loss over time", be.namespace) == ("训练损失随时间的变化", "scripted+repaired")
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    assert "简体中文" not in _page_text(ws) and "训练损失随时间的变化" in _page_text(ws)
    assert qa["status"] == "pass"                                        # repaired: not a failure
    assert [i["issue"] for i in _issues(qa)] == ["translation_repaired"]


def test_unusable_answer_is_retried_once_with_context(tmp_path, fonts_ready):
    src = "Model input"
    junk = "Model input and a long unrelated sentence that was never in the source"
    ws = _page(tmp_path, ["Standard prompting is shown on the left.", src, "The answer is given below."])
    be = Scripted({"Standard prompting is shown on the left.": "左侧为标准提示。", src: junk,
                   "The answer is given below.": "答案见下文。"}, context_answers={src: "模型输入"})
    s = translate(ws, ["a.pdf"], be, max_chars=999)
    with_ctx = [(t, c) for t, c in be.requests if c is not None]
    assert len(with_ctx) == 1 and with_ctx[0][0] == [src]
    assert "Standard prompting" in with_ctx[0][1] and "answer is given" in with_ctx[0][1]   # neighbours as context
    assert s["retried_with_context"] == 1 and s["repairs"][0]["step"] == "retry_with_context"
    total = sum(len(x) for x in ("Standard prompting is shown on the left.", src, "The answer is given below."))
    assert s["sent_chars"] == total + len(src)                          # the retry is counted
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    assert "模型输入" in _page_text(ws) and "unrelated" not in _page_text(ws)
    assert qa["status"] == "pass"


def test_backend_that_always_adds_junk_falls_back_to_the_source(tmp_path, fonts_ready):
    src = "Model input"
    junk = "Model input and a long unrelated sentence that was never in the source"
    ws = _page(tmp_path, [src, "The answer is given below."])
    be = Scripted({src: junk, "The answer is given below.": "答案见下文。"}, context_answers={src: junk})
    s = translate(ws, ["a.pdf"], be, max_chars=999)
    assert s["outcome"] == "complete" and s["remaining_chars"] == 0
    assert len([1 for _, c in be.requests if c is not None]) == 1       # exactly one retry, never a loop
    assert s["repairs"][0]["step"] == "source_kept"
    s2 = translate(ws, ["a.pdf"], be, max_chars=999)                    # decided: not asked again
    assert s2["stopped"] == "nothing to translate" and len(be.requests) == 2
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    text = _page_text(ws)
    assert src in text and "unrelated" not in text and "答案见下文" in text
    assert qa["status"] == "review"                                     # visible, not a failure
    assert "translation_left_source" in [i["issue"] for i in _issues(qa)]


def test_retry_respects_the_character_budget(tmp_path, fonts_ready):
    src = "Model input"
    junk = "Model input and a long unrelated sentence that was never in the source"
    ws = _page(tmp_path, [src])
    be = Scripted({src: junk}, context_answers={src: "模型输入"})
    s = translate(ws, ["a.pdf"], be, max_chars=len(src))                # room for one request only
    assert s["sent_chars"] == len(src) and all(c is None for _, c in be.requests)
    assert ws.tm().get(src, be.namespace) == (sanity.KEEP, "scripted+kept")
    with pytest.raises(BudgetExceeded):
        be.meter = __import__("patt_pdf.backends", fromlist=["Meter"]).Meter(3); be.translate([src])


def test_bad_entry_from_an_older_cache_is_repaired_at_render_without_a_request(tmp_path, fonts_ready):
    ws = _page(tmp_path, ["Training loss over time", "Billion of tokens"])
    be = Scripted({})
    tm = ws.tm()
    tm.put("Training loss over time", "训练损失随时间的变化简体中文（大陆）", be.namespace, "scripted")   # as stored by 0.3.x
    tm.put("Billion of tokens", "数十亿个令牌", be.namespace, "scripted")
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    text = _page_text(ws)
    assert be.requests == [] and "简体中文" not in text and "大陆" not in text
    assert "训练损失随时间的变化" in text and "数十亿个令牌" in text
    rep = [i for i in _issues(qa) if i["issue"] == "translation_repaired"]
    assert len(rep) == 1 and rep[0]["rejected"].endswith("简体中文（大陆）") and qa["status"] == "pass"


def test_old_cached_legend_translation_is_ignored(tmp_path, fonts_ready):
    """The exact entry of the first real run: the legend is no longer looked up at all."""
    ws = _page(tmp_path, [LEGEND])
    be = Scripted({})
    ws.tm().put(LEGEND, BAD, be.namespace, "scripted")
    qa = render_file(ws, "a.pdf", be.namespace, ocr_qa=False)
    assert LEGEND in _page_text(ws) and "简体中文" not in _page_text(ws)
    assert qa["status"] == "pass" and _issues(qa) == []


def test_manual_translations_are_used_as_written(tmp_path, fonts_ready):
    """The user's own wording is not second-guessed, even if it names a language."""
    from patt_pdf.backends import ManualBackend
    ws = _page(tmp_path, ["Language"])
    f = tmp_path / "tm.json"; f.write_text(json.dumps({"Language": "语言：简体中文（大陆）"}, ensure_ascii=False), encoding="utf-8")
    m = ManualBackend(f)
    assert translate(ws, ["a.pdf"], m, max_chars=99)["outcome"] == "complete"
    render_file(ws, "a.pdf", m.namespace, ocr_qa=False)
    assert "简体中文（大陆）" in _page_text(ws)
