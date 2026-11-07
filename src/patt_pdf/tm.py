"""Translation memory: append-only JSONL, keyed by (translation identity, source text).

Why identities ("namespaces"): v0.1 keyed entries by source text only, so placeholder
text from the `pseudo` backend was later treated as a real translation by `estimate`,
`translate` and `render` (reproduced, see docs/STATUS.md). Every entry now carries the
namespace of the engine/configuration that produced it, and lookups only match the
namespace that is in use. The namespace is a hash of backend name, language pair and
result-relevant configuration (e.g. glossary content, manual TM file content); API keys
are never part of it.

Record format (v2):  {"v": 2, "ns": "...", "src": "...", "tgt": "...", "origin": "deepl", "ts": ...}
Legacy v0.1 records (no "ns") are loaded into the namespace "legacy:<origin>" and are
NEVER matched automatically; `patt-pdf tm adopt-legacy` re-tags them explicitly.

Human overrides (a JSON {source: translation} file passed with --overrides) take
precedence over any namespace and are counted separately in QA.

Privacy: the TM stores source sentences and translations in plain text. It lives in the
private state directory chosen by the user and must not be published.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

LEGACY_PREFIX = "legacy:"


class TranslationMemory:
    def __init__(self, path: str | os.PathLike, overrides: dict[str, str] | None = None):
        self.path = Path(path); self.lock = threading.Lock()
        self.entries: dict[tuple[str, str], tuple[str, str]] = {}      # (ns, src) -> (tgt, origin)
        self.overrides = dict(overrides or {})
        self.legacy_count: dict[str, int] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        r = json.loads(ln)
                        src, tgt, origin = r["src"], r["tgt"], r.get("origin", "unknown")
                    except (ValueError, KeyError, TypeError):
                        continue                    # torn last line after a crash
                    ns = r.get("ns") or (LEGACY_PREFIX + origin)
                    if ns.startswith(LEGACY_PREFIX) and (ns, src) not in self.entries:
                        self.legacy_count[ns] = self.legacy_count.get(ns, 0) + 1
                    self.entries[(ns, src)] = (tgt, origin)

    def get(self, src: str, ns: str) -> tuple[str | None, str | None]:
        """Translation for `src` in namespace `ns` (overrides first). Returns (tgt, origin)."""
        if src in self.overrides:
            return self.overrides[src], "override"
        if ns.startswith(LEGACY_PREFIX):
            raise ValueError("legacy namespaces cannot be used for lookups; adopt them first")
        return self.entries.get((ns, src), (None, None))

    def put(self, src: str, tgt: str, ns: str, origin: str) -> None:
        if ns.startswith(LEGACY_PREFIX):
            raise ValueError("cannot write into a legacy namespace")
        with self.lock:
            self.entries[(ns, src)] = (tgt, origin)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"v": 2, "ns": ns, "src": src, "tgt": tgt, "origin": origin, "ts": time.time()},
                                   ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())

    def namespaces(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ns, _ in self.entries:
            out[ns] = out.get(ns, 0) + 1
        return out

    def adopt_legacy(self, origin: str, target_ns: str) -> int:
        """Explicitly re-tag legacy records of `origin` into `target_ns`. Returns the count."""
        src_ns = LEGACY_PREFIX + origin
        items = [(s, v) for (ns, s), v in self.entries.items() if ns == src_ns]
        for s, (tgt, org) in items:
            self.put(s, tgt, target_ns, org)
        return len(items)

    def __len__(self):
        return len(self.entries)
