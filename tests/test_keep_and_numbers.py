"""Unit tests: keep rules, number/currency/URL checks (pure functions, no PDFs)."""
import pytest

from patt_pdf.keep import is_keep
from patt_pdf.qa import number_check, url_check


@pytest.mark.parametrize("t", ["1", "2", "48,210", "(2,317)", "$", "12.5%", "2024", "AA+", "BBB-", "Baa2",
                               "https://example.com/a?b=1", "?mod=article_inline", "|", "—", "20.12.18",
                               "USD 3.5 bn", "Q3 2025", "第1项"])
def test_keep(t):
    assert is_keep(t), t


@pytest.mark.parametrize("t", ["Contents", "Total spending", "Visitor programmes, net", "Page 7",
                               "Visits grew 12%", "Day 1: Arrival"])
def test_not_keep(t):
    assert not is_keep(t), t


@pytest.mark.parametrize("src,tgt", [
    ("Ticket revenue grew to $2.3 billion in 2024, up 12.5% from 2023.", "2024年门票收入增长至23亿美元，较2023年增长12.5%。"),
    ("Item 1.", "第1项"),                                        # digit right after CJK (ASCII lookbehind)
    ("$150 Million grant", "1.5亿美元补助"),
    ("over $30b (2017)", "超过300亿美元（2017年）"),
    ("$125 to $150 million", "1.25亿至1.5亿美元"),                 # range shares the scale word
    ("USD 2 trillion", "2万亿美元"),
    ("In the mid-1990s", "20世纪90年代中期"),
    ("as of 20.12.2018", "截至2018年12月20日"),
    ("a catch-22 situation", "进退两难的局面"),
    ("3 M USD rate + 60 bps", "3个月期美元利率 + 60个基点"),
])
def test_numbers_ok(src, tgt):
    assert number_check(src, tgt) == []


@pytest.mark.parametrize("src,tgt,needle", [
    ("Loss of (1,234)", "亏损1,234", "sign"),
    ("Up 5%", "增长5", "percent"),
    ("Ticket revenue $2.3 billion", "门票收入2.3亿美元", "missing"),          # wrong magnitude (should be 23亿)
    ("Grants were $51.4 million, $81.3 million and $0", "补助已计入年度预算", "missing"),
    ("Price $10", "价格10", "currency"),
])
def test_numbers_flag_errors(src, tgt, needle):
    issues = number_check(src, tgt)
    assert any(needle in i for i in issues), issues


def test_url_check():
    assert url_check("see https://www.example.com/news/harbour-and-lighthouse", "见 https://www.example.com/news/港口-lighthouse")
    assert not url_check("see https://example.com/x", "见 https://example.com/x")
