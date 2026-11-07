"""DeepL client logic with a fake HTTP opener — no network, no key, no quota."""
import io
import json
import os
import urllib.error

import pytest

from patt_pdf.backends import AuthError, DeepLBackend, QuotaExceeded, read_deepl_key

FAKE_KEY = "00000000-0000-0000-0000-000000000000:fx"


class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_from(script):
    """script: list of ints (HTTP error codes) or dicts (JSON bodies), consumed in order."""
    calls = []

    def _open(req, timeout=None):
        calls.append((req.full_url, req.get_header("Authorization")))
        item = script.pop(0)
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "x", {}, None)
        return FakeResp(json.dumps(item).encode())
    _open.calls = calls
    return _open


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv("DEEPL_AUTH_KEY", FAKE_KEY)


def test_retry_then_success(key_env, tmp_path):
    op = opener_from([429, 503, {"translations": [{"text": "你好"}]}])
    be = DeepLBackend(tmp_path / "ledger.jsonl", qps=1000, opener=op, sleep=lambda s: None)
    assert be.translate(["Hello"]) == ["你好"]
    assert len(op.calls) == 3 and op.calls[0][0].startswith("https://api-free.deepl.com")
    led = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in led] == [429, 503, 200]
    assert FAKE_KEY not in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")      # key never logged


def test_quota_stops_everything(key_env, tmp_path):
    be = DeepLBackend(tmp_path / "l.jsonl", qps=1000, opener=opener_from([456]), sleep=lambda s: None)
    with pytest.raises(QuotaExceeded):
        be.translate(["a"])
    with pytest.raises(QuotaExceeded):               # stays stopped, no further request
        be.translate(["b"])


def test_auth_error_message_has_no_key(key_env, tmp_path):
    be = DeepLBackend(tmp_path / "l.jsonl", qps=1000, opener=opener_from([403]), sleep=lambda s: None)
    with pytest.raises(AuthError) as e:
        be.translate(["a"])
    assert FAKE_KEY not in str(e.value)


def test_translate_job_respects_remaining_quota(key_env, corpus, fonts_ready, tmp_path):
    from patt_pdf.jobs import Workspace, plan_file, translate
    ws = Workspace(corpus["src"], tmp_path)
    plan_file(ws, "toc.pdf", ocr=False)
    op = opener_from([{"character_count": 999_990, "character_limit": 1_000_000}])
    be = DeepLBackend(tmp_path / "ledger.jsonl", qps=1000, opener=op, sleep=lambda s: None)
    s = translate(ws, ["toc.pdf"], be, max_chars=10_000, reserve=0)
    assert s["stopped"] and "remaining quota" in s["stopped"]
    assert len(op.calls) == 1                         # only the usage query, no translate call


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits (Windows relies on folder ACLs)")
def test_key_file_permissions(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    kf = tmp_path / "k"; kf.write_text(FAKE_KEY, encoding="utf-8"); kf.chmod(0o644)
    monkeypatch.setenv("DEEPL_KEY_FILE", str(kf))
    with pytest.raises(AuthError, match="chmod 600"):
        read_deepl_key()
    kf.chmod(0o600)
    assert read_deepl_key() == FAKE_KEY


def test_key_file_is_read_as_utf8_with_or_without_bom(monkeypatch, tmp_path):
    """Cross-platform: a key file written by Notepad (UTF-8 BOM) or by `key save` is read."""
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    kf = tmp_path / "k"
    kf.write_bytes(b"\xef\xbb\xbf" + FAKE_KEY.encode("ascii") + b"\r\n")
    if os.name == "posix":
        kf.chmod(0o600)
    monkeypatch.setenv("DEEPL_KEY_FILE", str(kf))
    assert read_deepl_key() == FAKE_KEY
