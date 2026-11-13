"""Checks of install.sh, the one-line installer for macOS and Linux.

Static checks run everywhere; the behavioural checks need bash (skipped on Windows). None of
them touches the network, the user's home folder or system packages: every run uses
--no-system, a temporary HOME/prefix and --no-modify-path (or --uninstall on a folder the script
did not create)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install.sh"
ONE_LINER = "curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(not BASH or sys.platform == "win32", reason="needs bash (macOS/Linux)")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _run(*args, home: Path, env_extra: dict | None = None, stdin=subprocess.DEVNULL):
    env = {k: v for k, v in os.environ.items() if k not in ("XDG_DATA_HOME", "SHELL", "PATT_PDF_LANG", "LC_ALL", "LC_MESSAGES")}
    # official sources by default: the mirror choice probes the mirror, and these tests are offline
    env.update({"HOME": str(home), "PATT_PDF_MIRROR": "official", "LANG": "C.UTF-8", **(env_extra or {})})
    env = {k: v for k, v in env.items() if v is not None}
    r = subprocess.run([BASH, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, stdin=stdin, timeout=600)
    return r.returncode, r.stdout + r.stderr


# ------------------------------------------------------------------ static
def test_script_is_present_and_strict():
    t = _text()
    assert t.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in t
    assert t.rstrip().endswith('main "$@"'), "the script must be wrapped in main() so a truncated download runs nothing"
    assert "\r" not in t, "LF line endings only (the file is run by bash)"
    if sys.platform != "win32":
        assert os.access(SCRIPT, os.X_OK)


def test_readme_one_liner_matches_the_script():
    """The command in both READMEs and in the script's own help text is the same."""
    for name in ("README.md", "README.zh-CN.md"):
        assert ONE_LINER in (ROOT / name).read_text(encoding="utf-8"), name
    assert ONE_LINER in _text()


def test_homebrew_install_is_announced_and_confirmed():
    """Informed consent: on macOS the script may install Homebrew. It must say so in the README
    badge/notes and ask before doing it (only --yes skips the question)."""
    t = _text()
    assert "Homebrew/install/HEAD/install.sh" in t
    i = t.index("Homebrew/install/HEAD/install.sh")
    before = t[:i]
    assert 'confirm "Install Homebrew now?"' in before and "https://brew.sh" in before
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert "img.shields.io/badge/macOS-Homebrew" in readme, f"{name}: Homebrew badge missing"
        assert "Homebrew" in readme


def test_children_never_read_the_piped_script():
    """Under `curl | bash` stdin IS the script: every external command gets </dev/null and
    questions are read from /dev/tty."""
    t = _text()
    assert 'read -r answer <&3' in t and '3<>/dev/tty' in t
    for cmd in ("-m venv", "-m pip install", 'bash "$TMPDL/brew-install.sh"', "curl -fL --retry", '"$uv" pip install',
                'curl -fsS -m 8'):
        line = next(l for l in t.splitlines() if cmd in l and not l.lstrip().startswith(("#", "run ")))
        assert "</dev/null" in line or "</dev/tty" in line, line
    assert "run()" in t and '"$@" </dev/null' in t             # run(): the wrapper for the other commands


def test_uninstall_only_removes_what_the_script_created():
    t = _text()
    body = t[t.index("do_uninstall()"):t.index("# ------------------------------------------------------------------ main")]
    assert '"${PREFIX:?}/venv"' in body and "$MARKER" in body
    assert re.search(r'rm -rf "\$\{PREFIX:\?\}/venv" "\$\{PREFIX:\?\}/\$\{MARKER:\?\}"', body)
    assert 'rm -rf "$PREFIX"' not in body and "rm -rf \"$HOME" not in body
    assert "readlink" in body                             # the link is removed only if it points into PREFIX


def test_bash_3_2_compatible_array_expansion():
    """macOS ships bash 3.2, where "${arr[@]}" of an empty array is an unbound variable under set -u."""
    t = _text()
    assert '${PIP_ARGS[@]+"${PIP_ARGS[@]}"}' in t
    assert '"${PIP_ARGS[@]}" "$SRC"' not in t


def test_full_install_declared():
    """The user decision: one complete install, OpenCV included, Tesseract + English data, fonts."""
    t = _text()
    assert "tesseract-ocr tesseract-ocr-eng" in t          # Debian/Ubuntu
    assert "tesseract tesseract-langpack-eng" in t          # Fedora
    assert "tesseract tesseract-data-eng" in t              # Arch
    assert "font-noto-sans-cjk font-noto-serif-cjk" in t    # Homebrew casks (same as CI)
    assert "fonts-noto-cjk" in t
    assert "[ocr]" not in t and "--no-deps" not in t        # nothing optional, nothing left out


# ------------------------------------------------------------------ behaviour (bash)
@needs_bash
def test_syntax_and_help(tmp_path):
    assert subprocess.run([BASH, "-n", str(SCRIPT)]).returncode == 0
    rc, out = _run("--help", home=tmp_path)
    assert rc == 0 and "--uninstall" in out and ONE_LINER in out
    rc, out = _run("--bogus", home=tmp_path)
    assert rc == 1 and "unknown option" in out
    rc, out = _run("--prefix", "relative/dir", home=tmp_path)
    assert rc == 1 and "absolute" in out
    assert not list(tmp_path.iterdir()), "argument errors must create nothing"


@needs_bash
def test_uninstall_leaves_foreign_folders_alone(tmp_path):
    home = tmp_path / "home"; (home / ".local" / "bin").mkdir(parents=True)
    other = tmp_path / "other"; (other / "venv").mkdir(parents=True)
    (other / "venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    (other / "keep.txt").write_text("mine", encoding="utf-8")
    link = home / ".local" / "bin" / "patt-pdf"; link.symlink_to(tmp_path / "elsewhere" / "patt-pdf")
    rc, out = _run("--uninstall", "--prefix", other, home=home)
    assert rc == 0 and "left alone" in out, out
    assert (other / "venv" / "pyvenv.cfg").exists() and (other / "keep.txt").exists()
    assert link.is_symlink(), "a link that points elsewhere is not ours"


@needs_bash
def test_source_option_rejects_non_checkouts(tmp_path):
    (tmp_path / "home").mkdir()
    rc, out = _run("--source", tmp_path, "--no-system", "--python", sys.executable,
                   "--prefix", tmp_path / "p", "--bin-dir", tmp_path / "b", home=tmp_path / "home")
    assert rc == 1 and "not a PATT-PDF checkout" in out
    assert not (tmp_path / "p").exists()


@needs_bash
def test_install_leaves_existing_command_alone(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    command = bindir / "patt-pdf"
    command.write_text("existing command", encoding="utf-8")
    prefix = tmp_path / "prefix"
    rc, out = _run("--source", ROOT, "--no-system", "--prefix", prefix,
                   "--bin-dir", bindir, home=tmp_path)
    assert rc == 1 and "already exists" in out
    assert not prefix.exists() and command.read_text(encoding="utf-8") == "existing command"


def _local_setuptools_wheel():
    import glob
    cands = []
    for d in filter(None, [os.environ.get("PATT_TEST_WHEELHOUSE"),
                           os.path.join(os.path.dirname(os.__file__), "ensurepip", "_bundled")]):
        cands += glob.glob(os.path.join(d, "setuptools-*-py3-none-any.whl"))

    def ver(p):
        try:
            return tuple(int(x) for x in os.path.basename(p).split("-")[1].split(".")[:2])
        except ValueError:
            return (0, 0)
    good = sorted((p for p in cands if ver(p) >= (70, 1)), key=ver)
    return good[-1] if good else None


@needs_bash
def test_real_offline_install_plumbing(tmp_path):
    """Real bash + real venv + real pip, offline: the script stages a clean copy of the checkout,
    builds PATT-PDF (no dependencies, so the result cannot start; that is reported, not hidden),
    links the command and never writes into the checkout."""
    whl = _local_setuptools_wheel()
    if not whl:
        pytest.skip("no local setuptools>=70.1 wheel (ensurepip bundle or PATT_TEST_WHEELHOUSE); no download")
    home = tmp_path / "home 家"; home.mkdir()
    prefix = tmp_path / "prefix"; bindir = tmp_path / "bin"
    def checkout_state():
        egg = ROOT / "src" / "patt_pdf.egg-info"
        return ((ROOT / "build").exists(), sorted(p.name for p in egg.iterdir()) if egg.exists() else None,
                egg.stat().st_mtime_ns if egg.exists() else None)
    before = checkout_state()
    rc, out = _run("--source", ROOT, "--no-system", "--no-modify-path", "--python", sys.executable,
                   "--prefix", prefix, "--bin-dir", bindir,
                   "--pip-arg=--no-index", f"--pip-arg=--find-links={os.path.dirname(whl)}", "--pip-arg=--no-deps",
                   home=home)
    assert "Linking the command" in out, out[-3000:]
    link = bindir / "patt-pdf"
    assert link.is_symlink() and os.path.realpath(link).startswith(str(prefix.resolve()))
    assert (prefix / ".installed-by-patt-pdf-install-sh").exists()
    py = prefix / "venv" / "bin" / "python"
    r = subprocess.run([str(py), "-c", "import patt_pdf; print(patt_pdf.__version__)"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
    assert rc != 0, "without dependencies `patt-pdf fonts` cannot run: the script must not report success"
    assert "doctor" in out or "fonts" in out
    assert checkout_state() == before, "the installer wrote build state into the checkout"
    # Force pip to fail after the existing environment has been moved aside.
    rc, out = _run("--source", ROOT, "--no-system", "--no-modify-path", "--python", sys.executable,
                   "--prefix", prefix, "--bin-dir", bindir, "--pip-arg=--invalid-option", home=home)
    assert rc == 1 and "pip install failed" in out
    assert link.exists() and not (prefix / ".install-lock").exists()
    assert subprocess.run([str(py), "-c", "import patt_pdf"]).returncode == 0
    # uninstall removes exactly what was created
    rc, out = _run("--uninstall", "--prefix", prefix, "--bin-dir", bindir, home=home)
    assert rc == 0 and not link.exists() and not (prefix / "venv").exists(), out


# ------------------------------------------------------------------ progress, mirrors, uv
def test_slow_steps_are_never_silent():
    """A silent install looks like a hang on a slow connection: pip and curl show progress, and
    every step says which of five it is and how much it downloads."""
    t = _text()
    pip_line = next(l for l in t.splitlines() if "-m pip install" in l and not l.lstrip().startswith("#"))
    assert "--quiet" not in pip_line and " -q " not in pip_line
    assert "--progress-bar" in next(l for l in t.splitlines() if "curl -fL --retry" in l)
    for n in "12345":
        assert f"step {n} " in t, n
    assert "STEPS=5" in t and "about $(python_download_mb) MB" in t and "about 235 MB" in t


def test_mirror_is_the_announced_default_with_a_way_out():
    t = _text()
    body = t[t.index("choose_mirror()"):t.index("# ------------------------------------------------------------------ Homebrew (macOS)")]
    assert "pypi.tuna.tsinghua.edu.cn/simple" in t and "mirrors.tuna.tsinghua.edu.cn" in t
    assert "[default]" in body and "[slower from mainland China]" in body          # the two choices, labelled
    assert "not served by the original publishers" in body                         # says what a mirror is
    assert "3<>/dev/tty" in body                                                   # asked on the terminal
    assert "using the official sources instead" in body                            # unreachable mirror
    # the mirror applies to this run: nothing is written to pip or Homebrew configuration
    for forbidden in ("pip config", "pip.conf", ".zprofile", "brew tap --custom-remote"):
        assert forbidden not in t, forbidden
    assert "will keep it as its update source" in t                                # the one lasting effect is announced


@needs_bash
def test_mirror_option_is_validated(tmp_path):
    rc, out = _run("--mirror", "fastest", home=tmp_path)
    assert rc == 1 and "--mirror must be 'cn' or 'official'" in out
    assert not list(tmp_path.iterdir())
    rc, out = _run("--help", home=tmp_path)
    assert "--mirror cn" in out and "--mirror official" in out and "--no-uv" in out


FAKE_UV = """#!/bin/bash
# records the call and creates a working stand-in for the installed command
{ echo "ARGS $*"; echo "INDEX ${UV_DEFAULT_INDEX:-none}"; echo "PIPINDEX ${PIP_INDEX_URL:-none}"; } >> "$UV_LOG"
py=""; prev=""
for a in "$@"; do [ "$prev" = "--python" ] && py="$a"; prev="$a"; done
[ "${UV_FAIL:-0}" = 1 ] && exit 1
printf '#!/bin/sh\necho "stand-in $*"\n' > "$(dirname "$py")/patt-pdf" && chmod +x "$(dirname "$py")/patt-pdf"
"""
FAKE_CURL = """#!/bin/bash
echo "CURL $*" >> "$UV_LOG"
exit ${CURL_RC:-0}
"""


def _tools(tmp_path, uv=True, curl=True):
    d = tmp_path / "fakebin"; d.mkdir(exist_ok=True)
    for name, text, on in (("uv", FAKE_UV, uv), ("curl", FAKE_CURL, curl)):
        if on:
            (d / name).write_text(text, encoding="utf-8"); (d / name).chmod(0o755)
    path = os.pathsep.join([str(d)] + [p for p in os.environ["PATH"].split(os.pathsep)
                                       if not os.path.exists(os.path.join(p, "uv"))])
    return {"PATH": path, "UV_LOG": str(tmp_path / "uv.log")}


def _install(tmp_path, *extra, env=None, name="p"):
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    return _run("--source", ROOT, "--no-system", "--no-modify-path", "--python", sys.executable,
                "--prefix", tmp_path / name, "--bin-dir", tmp_path / (name + "-bin"), *extra, home=home, env_extra=env)


def _log(tmp_path):
    p = tmp_path / "uv.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


@needs_bash
def test_uv_is_used_when_present_with_the_mirror_and_numbered_steps(tmp_path):
    env = dict(_tools(tmp_path), PATT_PDF_MIRROR=None)                 # no choice given, no terminal: the default
    rc, out = _install(tmp_path, env=env)
    log = _log(tmp_path)
    assert rc == 0, out[-2000:]
    assert "installer: uv" in out and "ARGS pip install --python" in log
    assert "INDEX https://pypi.tuna.tsinghua.edu.cn/simple" in log
    assert "no terminal to ask in: using the mirror" in out and "download source: MIRROR" in out
    assert "CURL -fsS -m 8" in log                                     # the mirror was probed first
    for n in range(1, 6):
        assert f"Step {n}/5:" in out, (n, out[-1500:])
    assert out.index("Step 1/5") < out.index("Step 3/5") < out.index("Step 5/5")
    assert "MB from the mirror" in out and "Where to download from" in out
    assert (tmp_path / "p-bin" / "patt-pdf").is_symlink()


@needs_bash
def test_official_sources_set_no_mirror(tmp_path):
    rc, out = _install(tmp_path, "--mirror", "official", env=_tools(tmp_path))
    log = _log(tmp_path)
    assert rc == 0 and "download source: OFFICIAL" in out and "MB from the official source" in out
    assert "INDEX none" in log and "PIPINDEX none" in log and "CURL" not in log
    assert "Where to download from" not in out                         # decided on the command line: not asked


@needs_bash
def test_unreachable_mirror_falls_back_to_the_official_sources(tmp_path):
    env = dict(_tools(tmp_path), CURL_RC="28")
    rc, out = _install(tmp_path, "--mirror", "cn", env=env)
    assert rc == 0 and "using the official sources instead" in out and "download source: OFFICIAL" in out
    assert "INDEX none" in _log(tmp_path)


@needs_bash
def test_pip_is_used_without_uv_with_no_uv_and_with_pip_args(tmp_path):
    offline = {"PIP_NO_INDEX": "1"}                                    # pip fails at once instead of downloading
    # --no-uv
    rc, out = _install(tmp_path, "--no-uv", env=dict(_tools(tmp_path), **offline))
    assert "installer: pip" in out and "installer: uv" not in out and "ARGS" not in _log(tmp_path)
    assert rc == 1 and "pip install failed" in out
    # pip arguments are pip's: uv is not used
    rc, out = _install(tmp_path, "--pip-arg=--no-index", env=_tools(tmp_path), name="q")
    assert "installer: pip" in out and "ARGS" not in _log(tmp_path)
    # no uv on this machine
    (tmp_path / "fakebin" / "uv").unlink()
    rc, out = _install(tmp_path, env=dict(_tools(tmp_path, uv=False), **offline), name="r")
    assert "installer: pip" in out and "installer: uv" not in out
    for n in "pqr":                                                    # a failed install leaves nothing behind
        assert not (tmp_path / n / "venv").exists() and not (tmp_path / (n + "-bin") / "patt-pdf").exists()


@needs_bash
def test_failing_uv_is_retried_with_pip(tmp_path):
    env = dict(_tools(tmp_path), UV_FAIL="1", PIP_NO_INDEX="1")
    rc, out = _install(tmp_path, env=env)
    assert "uv failed; trying again with pip" in out and "installer: pip" in out
    assert out.index("installer: uv") < out.index("installer: pip")


@needs_bash
def test_messages_are_chinese_in_a_chinese_locale(tmp_path):
    env = dict(_tools(tmp_path), PATT_PDF_MIRROR=None, PATT_PDF_LANG="zh_CN.UTF-8")
    rc, out = _install(tmp_path, env=env)
    assert rc == 0
    for text in ("选择下载来源", "国内镜像【默认】", "官方源【在中国大陆较慢】", "第 1/5 步", "第 3/5 步", "第 5/5 步", "下载来源：镜像"):
        assert text in out, text


def _with_terminal(tmp_path, answer: bytes, env_extra):
    """Run the installer with a real controlling terminal and type `answer` at the prompt."""
    import pty
    import select
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("XDG_DATA_HOME", "SHELL", "PATT_PDF_MIRROR", "LC_ALL", "PATT_PDF_LANG")}
    env.update(HOME=str(home), LANG="C.UTF-8", **env_extra)
    args = [BASH, str(SCRIPT), "--source", str(ROOT), "--no-system", "--no-modify-path", "--python", sys.executable,
            "--prefix", str(tmp_path / "p"), "--bin-dir", str(tmp_path / "p-bin")]
    pid, fd = pty.fork()
    if pid == 0:                                                       # child: the pty is its controlling terminal
        os.execve(BASH, args, env)
    out, sent = b"", False
    while True:
        r, _, _ = select.select([fd], [], [], 120)
        if not r:
            break
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if not sent and b"official sources:" in out:
            os.write(fd, answer); sent = True
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace"), sent


@needs_bash
@pytest.mark.skipif(sys.platform == "win32" or not hasattr(os, "waitstatus_to_exitcode"), reason="needs a POSIX pty")
@pytest.mark.parametrize("answer,mirror", [(b"\n", True), (b"2\n", False)])
def test_question_on_a_terminal_enter_keeps_the_mirror_two_switches(tmp_path, answer, mirror):
    rc, out, asked = _with_terminal(tmp_path, answer, _tools(tmp_path))
    assert asked, out[-1500:]
    assert rc == 0, out[-1500:]
    log = _log(tmp_path)
    if mirror:
        assert "download source: MIRROR" in out and "INDEX https://pypi.tuna.tsinghua.edu.cn/simple" in log
    else:
        assert "download source: OFFICIAL" in out and "INDEX none" in log and "CURL" not in log
