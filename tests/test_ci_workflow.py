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


def test_all_existing_platform_targets_are_kept(wf):
    """The Windows failures of run 42396678823 must be fixed, not hidden: every OS/CPU target of
    that run stays in the matrix (Windows x64 and arm64 included)."""
    oses = {e["os"] for e in wf["jobs"]["test"]["strategy"]["matrix"]["include"]}
    assert {"ubuntu-24.04", "ubuntu-24.04-arm", "macos-15", "macos-15-intel", "windows-2025", "windows-11-arm"} <= oses
    assert "continue-on-error" not in WF.read_text(encoding="utf-8")


def test_utf8_off_encoding_step_runs_after_a_failed_suite(wf):
    steps = {s.get("name"): s for s in wf["jobs"]["test"]["steps"]}
    assert "cancelled()" in str(steps["Encoding tests with UTF-8 mode off"].get("if", ""))


def test_retest_regressions_are_in_ci(wf):
    """v0.3.5 retest findings (R01, wrapper, M3) are exercised in CI, not only locally."""
    steps = {s.get("name"): s for s in wf["jobs"]["test"]["steps"]}
    pre = next(s for n, s in steps.items() if n and n.startswith("Install preflight"))
    assert "python -S tools/preflight.py" in pre["run"]
    ps = next(s for n, s in steps.items() if n and n.startswith("PowerShell retest wrapper"))
    assert ps["shell"] == "pwsh" and "runner.os == 'Windows'" in ps["if"] and "test_run_logged.ps1" in ps["run"]
    r01 = next(s for n, s in steps.items() if n and "R01" in n)
    assert "临时 目录" in r01["run"] and "TEMP=" in r01["run"] and "windows_like" in r01["run"]


def test_offline_install_test_gets_a_wheelhouse_in_ci(wf):
    """CI run 42480633442: the real offline install test failed on macOS 3.11 (setuptools 65.5,
    no `wheel`) and skipped elsewhere. CI provides setuptools>=70.1 so the test really runs."""
    steps = {s.get("name"): s for s in wf["jobs"]["test"]["steps"]}
    wh = next(s for n, s in steps.items() if n and n.startswith("Build-backend wheelhouse"))
    assert "setuptools>=70.1" in wh["run"] and "PATT_TEST_WHEELHOUSE" in wh["run"] and "--only-binary=:all:" in wh["run"]
    names = [s.get("name") for s in wf["jobs"]["test"]["steps"]]
    assert names.index(wh["name"]) < names.index("Tests")
