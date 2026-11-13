#!/usr/bin/env python3
"""Download the real-PDF regression corpus into a local cache (standard library only).

    python tools/corpus_fetch.py            # fetch what is missing, verify everything
    python tools/corpus_fetch.py --check    # verify the cache only, no network
    python tools/corpus_fetch.py --dir PATH # another cache folder (or set PATT_CORPUS_DIR)

The documents are listed in tests/corpus/MANIFEST.json with source URL, SHA-256, size and
licence. They are never added to the repository. A download whose SHA-256 or size differs
from the manifest is rejected and not kept: the publisher changed the file (forms are
revised), and the manifest needs a human update. Exit: 0 all present and verified, 1 at
least one document missing or rejected, 2 usage or manifest error.

Cache folder: $PATT_CORPUS_DIR, else $XDG_CACHE_HOME/patt-pdf/corpus, else
~/.cache/patt-pdf/corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "corpus" / "MANIFEST.json"
UA = "patt-pdf-corpus-fetch/1 (+https://github.com/SPIRAL-EDWIN/PATT-pdf)"


def cache_dir() -> Path:
    if os.environ.get("PATT_CORPUS_DIR"):
        return Path(os.environ["PATT_CORPUS_DIR"]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "patt-pdf" / "corpus"


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


def verify(path: Path, entry: dict) -> str | None:
    """None if `path` is the document of `entry`, else the reason."""
    if not path.is_file():
        return "missing"
    data = path.read_bytes()
    if len(data) != entry["bytes"]:
        return f"size {len(data)} differs from the manifest ({entry['bytes']})"
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return "SHA-256 differs from the manifest"
    return None


def fetch(entry: dict, folder: Path, opener=urllib.request.urlopen, timeout: int = 90) -> str | None:
    """Download one document. None on success, else the reason; nothing is kept on failure."""
    url = entry["url"]
    if not url.startswith("https://"):
        return "refused: only https:// sources are fetched"
    folder.mkdir(parents=True, exist_ok=True)
    limit = max(entry["bytes"], 1) + 1
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".part-")
    try:
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": UA})
            with opener(rq, timeout=timeout) as r, os.fdopen(fd, "wb") as f:
                fd = None
                got = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > limit:                     # never store more than the manifest allows
                        return f"larger than the manifest size ({entry['bytes']} bytes): the published file changed"
                    f.write(chunk)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return f"download failed ({type(e).__name__})"
        why = verify(Path(tmp), entry)
        if why:
            return f"{why}: the published file changed, the manifest needs an update"
        os.replace(tmp, folder / entry["file"]); tmp = None
        return None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="verify the cache, do not download")
    ap.add_argument("--dir", help="cache folder (default: see --help text above)")
    ap.add_argument("--only", action="append", default=[], metavar="ID", help="document id (repeatable)")
    a = ap.parse_args(argv)
    try:
        docs = load_manifest()
    except (OSError, ValueError, KeyError) as e:
        print(f"manifest unreadable: {type(e).__name__}", file=sys.stderr); return 2
    if a.only:
        unknown = set(a.only) - {d["id"] for d in docs}
        if unknown:
            print(f"unknown id(s): {', '.join(sorted(unknown))}", file=sys.stderr); return 2
        docs = [d for d in docs if d["id"] in a.only]
    folder = Path(a.dir).expanduser() if a.dir else cache_dir()
    bad = 0
    for e in docs:
        p = folder / e["file"]
        why = verify(p, e)
        if why is None:
            print(f"ok        {e['id']:12s} {e['file']}"); continue
        if why != "missing":                               # a wrong file is never used or kept
            p.unlink()
        if a.check:
            print(f"MISSING   {e['id']:12s} {e['file']}  ({why})"); bad += 1; continue
        err = fetch(e, folder)
        if err:
            print(f"REJECTED  {e['id']:12s} {e['file']}  ({err})"); bad += 1
        else:
            print(f"fetched   {e['id']:12s} {e['file']}  ({e['bytes']} bytes, {e['licence']})")
    print(f"{len(docs) - bad} of {len(docs)} documents verified in {folder.name}/")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
