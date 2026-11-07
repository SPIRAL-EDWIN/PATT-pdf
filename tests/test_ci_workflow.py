"""Static checks of .github/workflows/tests.yml (the workflow itself has not run yet).

Guards against regressions found in review: retired runner labels (macOS 14 was retired from
GitHub Actions on 2026-11-02), unpinned actions, a "no OCR" job that does not prove OCR is absent,
and shell constructs that differ between bash and PowerShell."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
yaml = pytest.importorskip("yaml", reason="PyYAML not installed (optional, only for this check)")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_no_retired_or_floating_runner_labels(wf):
    oses = {e["os"] for e in wf["jobs"]["test"]["strategy"]["matrix"]["include"]}
    assert not {"macos-13", "macos-14", "macos-latest", "ubuntu-latest", "windows-latest"} & oses
    assert {"linux", "macos", "windows"} <= {o.split("-")[0].replace("ubuntu", "linux") for o in oses}
    assert any("arm" in o or o == "macos-15" for o in oses) and any("intel" in o or o.startswith("windows-2") for o in oses)


def test_actions_are_pinned_to_commits(wf):
    uses = [s["uses"] for s in wf["jobs"]["test"]["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_read_only_token_and_no_secrets(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert "secrets." not in WF.read_text(encoding="utf-8")


def test_both_ocr_states_are_verified(wf):
    inc = wf["jobs"]["test"]["strategy"]["matrix"]["include"]
    assert {True, False} <= {e["ocr"] for e in inc}
    steps = {s.get("name", ""): s for s in wf["jobs"]["test"]["steps"]}
    assert "ci_check_ocr.py" in steps["Verify OCR state"]["run"]
    assert "PATT_PDF_TESSERACT" in steps["Hide any preinstalled Tesseract (ocr=false)"]["run"]


def test_shells_are_explicit(wf):
    job = wf["jobs"]["test"]
    assert job["defaults"]["run"]["shell"] == "bash"
    for s in job["steps"]:
        run = s.get("run", "")
        if s.get("shell") == "pwsh":
            assert "||" not in run and "$GITHUB_ENV" not in run, s["name"]     # bash syntax in PowerShell
        elif run:
            assert "$env:" not in run and "Out-File" not in run, s.get("name")  # PowerShell syntax in bash
    assert "|| true" not in WF.read_text(encoding="utf-8")
