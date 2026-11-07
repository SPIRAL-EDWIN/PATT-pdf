"""Translation backends.

* ``manual``  — fixed translations from a JSON file {source: target}. Offline, deterministic.
* ``pseudo``  — offline placeholder Chinese of realistic length; keeps digits/symbols.
               For layout testing only: output is NOT a translation.
* ``deepl``   — DeepL API (Free or Pro). Sends source text to DeepL; bills characters.

DeepL client migrated from prototype jobs module (TokenBucket, DeepL); changes:
key lookup no longer includes a prototype-relative ``.secrets`` folder, key files
must not be group/world readable, and the key is never placed in exceptions or logs.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import stat
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


class BackendError(RuntimeError): ...
class QuotaExceeded(BackendError): ...
class AuthError(BackendError): ...
class BudgetExceeded(BackendError):
    """Sending another request (a retry included) would exceed --max-chars."""


class Meter:
    """Counts every request attempt a backend sends, retries included.

    ``before`` is called before each HTTP attempt and refuses (BudgetExceeded) if the
    attempt would push the characters sent in this run over ``max_chars``. ``after``
    classifies the attempt: "ok" (answered), "rejected" (the server answered with an error
    that means it did not translate, e.g. 429/456/401/403) or "unknown" (timeout, network
    error, 5xx: the request may have been processed, and billed, without us seeing it)."""

    def __init__(self, max_chars: int):
        self.max_chars = max_chars
        self.sent = self.unknown = self.rejected = self.attempts = self.retries = 0
        self.lock = threading.Lock()

    def before(self, chars: int, attempt: int) -> None:
        with self.lock:
            if self.sent + chars > self.max_chars:
                raise BudgetExceeded(f"attempt {attempt + 1} would send {chars} more characters; "
                                     f"{self.sent} already sent in this run, --max-chars {self.max_chars}")
            self.sent += chars; self.attempts += 1; self.retries += attempt > 0

    def after(self, chars: int, outcome: str) -> None:
        with self.lock:
            if outcome == "unknown":
                self.unknown += chars
            elif outcome == "rejected":
                self.rejected += chars


class Backend:
    """A translation engine plus the configuration that affects its output.

    ``namespace`` identifies results in the translation memory: two runs share cached
    results only if they share it. It must include everything that changes the output
    (engine, language pair, glossary/TM content) and nothing secret (no API keys).
    ``publishable=False`` marks output that must never pass QA (layout test text).
    """
    name = "base"
    billable = False
    publishable = True
    source_lang = "EN"
    target_lang = "ZH-HANS"

    def config(self) -> dict:
        return {}

    @property
    def namespace(self) -> str:
        cfg = json.dumps({"engine": self.name, "src": self.source_lang, "tgt": self.target_lang, **self.config()},
                         sort_keys=True, ensure_ascii=False)
        return f"{self.name}:{hashlib.sha256(cfg.encode()).hexdigest()[:16]}"

    meter: "Meter | None" = None     # set by jobs.translate for backends that send requests

    def prepare(self) -> None:
        """One-time remote setup, called only after all budget checks passed."""

    def translate(self, texts: list[str]) -> list[str | None]:  # None = no translation available
        raise NotImplementedError


def decode_user_text(raw: bytes, what: str) -> str:
    """Files the user writes (manual TM, glossary, key file) must be UTF-8. A UTF-8 byte-order
    mark (Windows Notepad, Excel "CSV UTF-8") is accepted; anything else gets a clear error
    instead of being decoded with the platform's default code page."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise BackendError(f"{what} is not valid UTF-8 (byte {e.start}); save it as UTF-8") from None


class ManualBackend(Backend):
    name = "manual"

    def __init__(self, path: str | os.PathLike):
        raw = Path(path).read_bytes()
        data = json.loads(decode_user_text(raw, f"manual TM {Path(path).name}"))
        self.tm = {k: v for k, v in data.items() if not k.startswith("_")}
        self._digest = hashlib.sha256(raw).hexdigest()[:16]

    def config(self):
        return {"manual_tm_sha256": self._digest}

    def translate(self, texts):
        return [self.tm.get(t) for t in texts]


_PSEUDO_POOL = "这是用于版面测试的占位中文文本仅用来检查字体换行与位置并不代表任何真实译文请勿发布或引用"


class PseudoBackend(Backend):
    """Deterministic placeholder: ~0.36 CJK chars per Latin letter, digits/symbols kept.
    NOT a translation — output is never publishable and always fails QA."""
    name = "pseudo"
    publishable = False

    def translate(self, texts):
        out = []
        for s in texts:
            figs = re.findall(r"[$€£¥]?\d[\d,.]*%?", s)
            n = max(2, round(len(re.sub(r"[^A-Za-z]", "", s)) * 0.36))
            o = (_PSEUDO_POOL * (n // len(_PSEUDO_POOL) + 1))[:n]
            out.append(o[: n // 2] + "".join(f + " " for f in figs) + o[n // 2:])
        return out


# ---------------------------------------------------------------- DeepL
KEY_RE = re.compile(r"[0-9a-fA-F-]{30,}(:fx)?")


def read_deepl_key() -> str:
    """Key from env DEEPL_AUTH_KEY, else from the file named by DEEPL_KEY_FILE,
    else ~/.config/patt-pdf/deepl.key. Files must be private (chmod 600)."""
    k = os.environ.get("DEEPL_AUTH_KEY", "").strip()
    if k:
        if not KEY_RE.fullmatch(k):
            raise AuthError("DEEPL_AUTH_KEY has an unexpected format")
        return k
    candidates = [os.environ.get("DEEPL_KEY_FILE", ""), str(default_key_path())]
    for p in filter(None, candidates):
        path = Path(p)
        if not path.is_file():
            continue
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise AuthError(f"key file {path} is readable by others; run: chmod 600 '{path}'")
        k = decode_user_text(path.read_bytes(), f"key file {path}").strip()
        if not KEY_RE.fullmatch(k):
            raise AuthError(f"key file {path} has an unexpected format")
        return k
    raise AuthError("no DeepL key: set DEEPL_AUTH_KEY or DEEPL_KEY_FILE (see README)")


def default_key_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "patt-pdf" / "deepl.key"
    return Path(os.path.expanduser("~/.config/patt-pdf/deepl.key"))


def save_deepl_key(key: str, path: Path | None = None) -> Path:
    """Write the key to a private file without a window where it is readable by others:
    the directory is created 0700 and the file is opened with O_CREAT|O_EXCL at 0600
    (on Windows the file is created in the user's profile; NTFS ACLs of %APPDATA% apply).
    Refuses to overwrite an existing file. The key itself is never printed."""
    key = key.lstrip("\ufeff").strip()          # PowerShell pipes may prepend a BOM
    if not KEY_RE.fullmatch(key):
        raise AuthError("input does not look like a DeepL key (nothing written)")
    path = Path(path or default_key_path())
    old_umask = os.umask(0o077) if os.name == "posix" else None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise AuthError(f"{path} already exists; delete it first if you want to replace the key") from None
    finally:
        if old_umask is not None:
            os.umask(old_umask)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    return path


class TokenBucket:
    def __init__(self, rate: float, burst: int = 2):
        self.rate, self.cap, self.tokens, self.t = rate, burst, float(burst), time.monotonic()
        self.lock = threading.Lock()

    def take(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.cap, self.tokens + (now - self.t) * self.rate); self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1; return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class DeepLBackend(Backend):
    """Thread-safe DeepL client with a global rate limit, bounded concurrency, retries
    and a hard stop on quota/auth errors. Every request is appended to ``ledger``."""
    name = "deepl"
    billable = True
    RETRY = (429, 500, 502, 503, 504, 529)

    def __init__(self, ledger: Path, qps: float = 1.0, inflight: int = 2, glossary_id: str | None = None,
                 target_lang: str = "ZH-HANS", opener=None, max_attempts: int = 7, sleep=time.sleep):
        self._key = read_deepl_key()
        self.base = "https://api-free.deepl.com" if self._key.endswith(":fx") else "https://api.deepl.com"
        self.bucket = TokenBucket(qps, 2); self.sem = threading.Semaphore(inflight)
        self.ledger = Path(ledger); self.llock = threading.Lock(); self.stop = threading.Event()
        self.glossary_id = glossary_id; self.target_lang = target_lang
        self.glossary_digest: str | None = None
        self._open = opener or urllib.request.urlopen
        self.max_attempts = max_attempts; self._sleep = sleep
        self._glossary_file: Path | None = None; self._glossary_cache: Path | None = None

    def config(self):
        # glossary content changes results; the glossary *id* is account-specific, so the
        # content digest is used. The API key is deliberately not part of the identity.
        return {"glossary_sha256": self.glossary_digest, "split_sentences": "nonewlines",
                "preserve_formatting": True}

    # -- low level
    def _req(self, path, payload=None, method="POST"):
        data = json.dumps(payload).encode() if payload is not None else None
        rq = urllib.request.Request(self.base + path, data=data, method=method,
                                    headers={"Authorization": "DeepL-Auth-Key " + self._key,
                                             "Content-Type": "application/json", "User-Agent": "patt-pdf/0.1"})
        with self._open(rq, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    def _log(self, **kw):
        kw["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.llock, open(self.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")

    # -- API
    def usage(self) -> dict:
        try:
            u = self._req("/v2/usage", method="GET")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"DeepL rejected the key (HTTP {e.code})") from None
            raise BackendError(f"DeepL usage failed (HTTP {e.code})") from None
        self._log(op="usage", character_count=u.get("character_count"), character_limit=u.get("character_limit"))
        return u

    def set_glossary(self, tsv: Path, cache: Path) -> None:
        """Select a glossary file. Local only: computes the digest that is part of the
        translation identity and reuses a cached glossary id. Creating the glossary in the
        DeepL account (a remote write) is deferred to prepare()."""
        tsv = Path(tsv)
        self.glossary_digest = hashlib.sha256(tsv.read_bytes()).hexdigest()[:16]
        self._glossary_file, self._glossary_cache = tsv, Path(cache)
        digest = hashlib.sha1(tsv.read_bytes()).hexdigest()
        if self._glossary_cache.exists():
            c = json.loads(self._glossary_cache.read_text(encoding="utf-8"))
            if c.get("digest") == digest:
                self.glossary_id = c["id"]

    def prepare(self) -> None:
        if self._glossary_file is not None and not self.glossary_id:
            try:
                self._create_glossary(self._glossary_file, self._glossary_cache)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise AuthError(f"DeepL rejected the key (HTTP {e.code})") from None
                raise BackendError(f"DeepL glossary creation failed (HTTP {e.code})") from None

    def ensure_glossary(self, tsv: Path, cache: Path) -> str:
        """set_glossary + create it now if needed (kept for scripts using v0.1 API)."""
        self.set_glossary(tsv, cache); self.prepare()
        return self.glossary_id

    def _create_glossary(self, tsv: Path, cache: Path) -> str:
        digest = hashlib.sha1(tsv.read_bytes()).hexdigest()
        entries = "\n".join(l for l in decode_user_text(tsv.read_bytes(), f"glossary {tsv.name}").splitlines()
                             if "\t" in l)
        g = self._req("/v2/glossaries", {"name": "patt-" + digest[:8], "source_lang": "en", "target_lang": "zh",
                                         "entries": entries, "entries_format": "tsv"})
        cache.write_text(json.dumps({"id": g["glossary_id"], "digest": digest}), encoding="utf-8")
        self._log(op="glossary_create", entries=g.get("entry_count"))
        self.glossary_id = g["glossary_id"]
        return self.glossary_id

    def translate(self, texts):
        if self.stop.is_set():
            raise QuotaExceeded("stopped after an earlier quota/auth error")
        payload = {"text": texts, "source_lang": "EN", "target_lang": self.target_lang,
                   "split_sentences": "nonewlines", "preserve_formatting": True}
        if self.glossary_id:
            payload["glossary_id"] = self.glossary_id
        chars = sum(len(t) for t in texts)
        m = self.meter
        for attempt in range(self.max_attempts):
            if self.stop.is_set():
                raise QuotaExceeded("stopped after an earlier quota/auth error")
            if m:
                m.before(chars, attempt)              # BudgetExceeded: never send past --max-chars
            self.bucket.take()
            with self.sem:
                try:
                    r = self._req("/v2/translate", payload)
                    self._log(op="translate", n=len(texts), chars=chars, status=200, attempt=attempt)
                    if m: m.after(chars, "ok")
                    return [x["text"] for x in r["translations"]]
                except urllib.error.HTTPError as e:
                    self._log(op="translate", n=len(texts), chars=chars, status=e.code, attempt=attempt)
                    if m: m.after(chars, "unknown" if e.code >= 500 else "rejected")
                    if e.code == 456:
                        self.stop.set(); raise QuotaExceeded("DeepL quota exhausted (HTTP 456)") from None
                    if e.code in (401, 403):
                        self.stop.set(); raise AuthError(f"DeepL rejected the key (HTTP {e.code})") from None
                    if e.code not in self.RETRY:
                        raise BackendError(f"DeepL HTTP {e.code}") from None
                except (urllib.error.URLError, TimeoutError, OSError):
                    self._log(op="translate", n=len(texts), chars=chars, status="network", attempt=attempt)
                    if m: m.after(chars, "unknown")
            self._sleep(min(60, 2 ** attempt + random.random()))
        raise BackendError("DeepL: retries exhausted")


def namespace_for(name: str, manual_tm: str | None = None, glossary: str | None = None,
                  target_lang: str = "ZH-HANS") -> str:
    """TM namespace of a backend configuration, computed WITHOUT creating a client
    (no key needed). `render` uses this to select which translations to draw; it must
    match what `translate` wrote for the same options."""
    cfg: dict = {}
    if name == "manual":
        if not manual_tm:
            raise BackendError("--manual-tm FILE is required for the manual backend")
        cfg = {"manual_tm_sha256": hashlib.sha256(Path(manual_tm).read_bytes()).hexdigest()[:16]}
    elif name == "deepl":
        cfg = {"glossary_sha256": hashlib.sha256(Path(glossary).read_bytes()).hexdigest()[:16] if glossary else None,
               "split_sentences": "nonewlines", "preserve_formatting": True}
    elif name != "pseudo":
        raise BackendError(f"unknown backend {name!r} (choose: manual, pseudo, deepl)")
    blob = json.dumps({"engine": name, "src": "EN", "tgt": target_lang, **cfg}, sort_keys=True, ensure_ascii=False)
    return f"{name}:{hashlib.sha256(blob.encode()).hexdigest()[:16]}"


PUBLISHABLE = {"manual": True, "deepl": True, "pseudo": False}


def make_backend(name: str, state_dir: Path, manual_tm: str | None = None, qps: float = 1.0) -> Backend:
    if name == "manual":
        if not manual_tm:
            raise BackendError("--manual-tm FILE is required for the manual backend")
        return ManualBackend(manual_tm)
    if name == "pseudo":
        return PseudoBackend()
    if name == "deepl":
        return DeepLBackend(ledger=Path(state_dir) / "ledger.jsonl", qps=qps)
    raise BackendError(f"unknown backend {name!r} (choose: manual, pseudo, deepl)")
