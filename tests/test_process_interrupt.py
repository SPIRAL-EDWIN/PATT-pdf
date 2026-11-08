"""Real process interruption on POSIX (Linux, macOS): a running `patt-pdf` is stopped with
SIGINT (Ctrl+C) or SIGKILL (power loss / OOM killer) in the middle of a batch, then the same
command is run again. Expected:
* the source PDFs are unchanged (byte-identical);
* no half-written output, plan, QA or TM file is visible: `out/*.pdf` and state JSON files are
  either absent or complete and parseable; no `.tmp-*` leftovers are counted as results;
* the re-run finishes with the normal exit code and only redoes what was missing;
* SIGINT exits non-zero and does not print a misleading success.
Windows has no SIGINT/SIGKILL semantics for child processes in this form; it is not covered here.

The batch is slowed down by a test-only sitecustomize (sleep inside render_file), so the signal
lands mid-batch deterministically. Synthetic fixtures only, offline manual backend.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX signals (Linux/macOS); Windows not covered")

ROOT = Path(__file__).resolve().parents[1]
FILES = ("toc.pdf", "table.pdf", "financial.pdf", "rotated.pdf", "报告 2026 – résumé.pdf")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def batch(corpus, fonts_ready, tmp_path):
    base = tmp_path / "中文 路径 with space"
    src = base / "输入 in"; src.mkdir(parents=True)
    for f in FILES:
        shutil.copy(corpus["src"] / f, src / f)
    slow = tmp_path / "slow"; slow.mkdir()
    (slow / "sitecustomize.py").write_text(
        "import os, time\n"
        "d = float(os.environ.get('PATT_TEST_SLOW_RENDER', '0'))\n"
        "if d:\n"
        "    import patt_pdf.jobs as J\n"
        "    _orig = J.render_file\n"
        "    def render_file(*a, **k):\n"
        "        print('SLOW-RENDER-START', flush=True); time.sleep(d)\n"
        "        return _orig(*a, **k)\n"
        "    J.render_file = render_file\n", encoding="utf-8")
    env = dict(os.environ, PATT_PDF_FONT_DIR=str(fonts_ready), PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([str(slow), str(ROOT / "src")] + [p for p in sys.path if p]))
    st = base / "state 状态"
    for step in (["plan", str(src), "--state", str(st), "--no-ocr"],
                 ["translate", str(src), "--state", str(st), "--backend", "manual", "--manual-tm",
                  str(corpus["manual_tm"]), "--max-chars", "99999"]):
        r = subprocess.run([sys.executable, "-m", "patt_pdf.cli", *step], capture_output=True, env=env, timeout=300)
        assert r.returncode in (0, 2), r.stdout.decode("utf-8", "replace")[-1500:]
    hashes = {f: _sha(src / f) for f in FILES}
    return {"src": src, "state": st, "env": env, "tm": corpus["manual_tm"], "hashes": hashes}


def _render_cmd(b):
    return [sys.executable, "-m", "patt_pdf.cli", "render", str(b["src"]), "--state", str(b["state"]),
            "--backend", "manual", "--manual-tm", str(b["tm"])]


def _interrupt_after(b, sig, n_started):
    """Start render, wait until n_started files have begun, then send `sig`."""
    env = dict(b["env"], PATT_TEST_SLOW_RENDER="0.8")
    p = subprocess.Popen(_render_cmd(b), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    seen, out = 0, []
    t0 = time.time()
    while seen < n_started and time.time() - t0 < 120:
        line = p.stdout.readline().decode("utf-8", "replace")
        if not line:
            break
        out.append(line)
        seen += "SLOW-RENDER-START" in line
    time.sleep(0.3)                                   # inside the sleep of file n_started
    p.send_signal(sig)
    rest, _ = p.communicate(timeout=120)
    return p.returncode, "".join(out) + rest.decode("utf-8", "replace")


def _state_is_consistent(b):
    st, out = b["state"], b["state"] / "out"
    for j in list((st / "qa").glob("*.json")) + list((st / "plans").glob("*.json")):
        json.loads(j.read_text(encoding="utf-8"))   # never a half-written JSON file
    done = sorted(p.name for p in out.glob("*.pdf")) if out.exists() else []
    import pymupdf
    for name in done:
        with pymupdf.open(out / name) as d:          # every visible output opens and has pages
            assert d.page_count >= 1, name
    tm = st / "tm.jsonl"
    if tm.exists():
        for line in tm.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
    return done


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGKILL], ids=["SIGINT", "SIGKILL"])
def test_interrupted_render_leaves_consistent_state_and_resumes(batch, sig):
    rc, out = _interrupt_after(batch, sig, n_started=3)
    assert rc != 0, out[-1500:]                                         # never reported as success
    if sig == signal.SIGINT:
        assert "KeyboardInterrupt" in out or rc == 130 or rc == 1, out[-1500:]
    assert {f: _sha(batch["src"] / f) for f in FILES} == batch["hashes"]   # sources untouched
    done_before = _state_is_consistent(batch)
    assert len(done_before) < len(FILES), done_before                    # really interrupted mid-batch
    r = subprocess.run(_render_cmd(batch), capture_output=True, env=batch["env"], timeout=300)
    text = r.stdout.decode("utf-8", "replace")
    assert r.returncode in (0, 3), text[-1500:]                         # normal outcome after resume
    done_after = _state_is_consistent(batch)
    assert sorted(done_after) == sorted(FILES), (done_after, text[-800:])
    for f in FILES:
        q = json.loads((batch["state"] / "qa" / f"{f}.json").read_text(encoding="utf-8"))
        assert q["status"] in ("pass", "review"), (f, q["status"])
    assert not list((batch["state"] / "out").glob(".tmp-*")) or sig == signal.SIGKILL
    leftovers = list((batch["state"] / "out").glob(".tmp-*"))
    print(f"{sig.name}: before={len(done_before)} after={len(done_after)} tmp-leftovers={len(leftovers)}")
    assert {f: _sha(batch["src"] / f) for f in FILES} == batch["hashes"]
