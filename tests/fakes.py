"""Controllable fake translation backends for offline tests (no network, no quota)."""
from __future__ import annotations

import threading
import time

from patt_pdf.backends import AuthError, Backend, BackendError, QuotaExceeded


def _fake_zh(t: str) -> str:
    """Chinese-like stand-in: every Latin word becomes one CJK char (compact, like real
    Chinese), digits/symbols/URLs are kept so number and URL checks pass."""
    import re
    url = re.compile(r"(?:https?://|doi:|www\.)\S+")
    out, i = [], 0
    for m in url.finditer(t):
        out.append(re.sub(r"[A-Za-z][A-Za-z'’-]*", "译", t[i:m.start()])); out.append(m.group(0)); i = m.end()
    out.append(re.sub(r"[A-Za-z][A-Za-z'’-]*", "译", t[i:]))
    return "".join(out)


class FakeMT(Backend):
    """Translates every English word to "译" (keeps digits/URLs, so number checks pass).

    script: dict batch_index -> "quota" | "auth" | "error" | float(seconds to block).
    Records concurrency so tests can assert the in-flight bound."""
    billable = False

    def __init__(self, name="fakemt", script=None, usage=None, glossary="g1"):
        self.name = name; self.script = dict(script or {}); self._usage = usage
        self.glossary = glossary
        self.calls = 0; self.inflight = 0; self.max_inflight = 0; self.lock = threading.Lock()
        self.received_chars = 0
        if usage is not None:
            self.billable = True

    def config(self):
        return {"glossary": self.glossary}

    def usage(self):
        return dict(self._usage)

    def translate(self, texts):
        with self.lock:
            idx = self.calls; self.calls += 1; self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            self.received_chars += sum(len(t) for t in texts)
        try:
            act = self.script.get(idx)
            if isinstance(act, (int, float)) and not isinstance(act, bool):
                time.sleep(act)
            elif act == "quota":
                raise QuotaExceeded("fake quota (456)")
            elif act == "auth":
                raise AuthError("fake auth (403)")
            elif act == "error":
                raise BackendError("fake 500 after retries")
            return [_fake_zh(t) for t in texts]
        finally:
            with self.lock:
                self.inflight -= 1
