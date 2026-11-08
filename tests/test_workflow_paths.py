"""End-to-end CLI workflow in a long folder with Chinese characters and spaces (macOS/Linux focus,
runs everywhere): plan -> estimate -> budget refusal -> manual translate -> re-run from cache ->
pseudo -> render -> report -> compare -> publish (twice) -> stale plan. Real subprocesses, real exit
codes, synthetic PDFs, offline backends. Sources must stay byte-identical and no temp file may
remain. Long here means ~180 bytes (inside every OS limit); Windows MAX_PATH is tested elsewhere."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_full_workflow_in_long_cjk_space_path(corpus, fonts_ready, tmp_path):
    base = tmp_path.joinpath("很长的 中文 目录 with spaces", *[f"segment-{i:02d}" for i in range(1, 7)])
    src = base / "输入 资料"; src.mkdir(parents=True)
    for f in ("toc.pdf", "table.pdf", "financial.pdf", "damaged.pdf", "报告 2026 – résumé.pdf"):
        shutil.copy(corpus["src"] / f, src / f)
    st, tm, pub = tmp_path / "状态 state", corpus["manual_tm"], tmp_path / "发布 out"
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()}
    env = dict(os.environ, PATT_PDF_FONT_DIR=str(fonts_ready), PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([str(ROOT / "src")] + [p for p in sys.path if p]))

    def cli(*a):
        r = subprocess.run([sys.executable, "-m", "patt_pdf.cli", *map(str, a)], capture_output=True, env=env, timeout=300)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

    rc, out = cli("plan", src, "--state", st, "--no-ocr"); assert rc == 1, out            # damaged.pdf is an error
    rc, out = cli("translate", src, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 5)
    assert rc == 2 and "exceeds --max-chars 5" in out, out                                   # budget refusal, nothing sent
    rc, out = cli("translate", src, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999)
    assert rc == 2, out                                                                      # done, 1 unreadable input
    s1 = json.loads(out[out.index("{"):out.rindex("}") + 1])
    # 'partial': the fixture TM lacks a few segments on purpose (missing_from_backend > 0)
    assert s1["outcome"] in ("complete", "partial") and s1["skipped_unreadable"] == ["damaged.pdf"], s1
    assert s1["sent_chars"] <= 99999 and s1["possibly_billed_chars"] == 0
    rc, out = cli("translate", src, "--state", st, "--backend", "manual", "--manual-tm", tm, "--max-chars", 99999)
    s2 = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert s2["cache_hits"] >= s1["segments"] - s1["missing_from_backend"], s2               # reused from cache
    assert s2["estimate_chars"] < s1["estimate_chars"] and s2["missing_from_backend"] == s1["missing_from_backend"], s2
    rc, out = cli("render", src, "--state", st, "--backend", "manual", "--manual-tm", tm)
    assert rc == 1 and "PASS       报告 2026 – résumé.pdf" in out, out                      # damaged -> 1
    rc, out = cli("report", src, "--state", st, "--out", tmp_path / "报告 report.md"); assert rc == 0, out
    rep = (tmp_path / "报告 report.md").read_text(encoding="utf-8")
    assert "segment-0" not in rep and str(tmp_path) not in rep                               # no local paths
    rc, out = cli("compare", src, "--state", st, "--out", tmp_path / "对比 cmp", "--files", "t*"); assert rc == 0, out
    assert len(list((tmp_path / "对比 cmp").glob("*.png"))) >= 2
    rc, out = cli("publish", src, "--state", st, "--dest", pub); assert rc in (0, 2), out
    first = sorted(p.name for p in pub.iterdir())
    assert "报告 2026 – résumé.pdf" in first and "damaged.pdf" not in first
    before = {p.name: p.stat().st_mtime_ns for p in pub.iterdir()}
    rc, out = cli("publish", src, "--state", st, "--dest", pub)
    assert "not overwritten" in out and {p.name: p.stat().st_mtime_ns for p in pub.iterdir()} == before
    # change a source after planning: render must refuse it as stale, other files unaffected
    orig = (src / "table.pdf").read_bytes()
    import pymupdf
    d = pymupdf.open(src / "table.pdf"); d[0].insert_text((50, 50), "changed"); d.saveIncr(); d.close()
    rc, out = cli("render", src, "--state", st, "--backend", "manual", "--manual-tm", tm, "--files", "table.pdf")
    assert rc == 1 and "source file content changed" in out, out
    (src / "table.pdf").write_bytes(orig)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()} == sha
    assert not [p for p in tmp_path.rglob(".tmp-*")]
