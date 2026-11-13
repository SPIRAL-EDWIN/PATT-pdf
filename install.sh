#!/usr/bin/env bash
# PATT-PDF one-line installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
#
# What it does (every step is printed before it runs):
#   1. installs the system parts PATT-PDF needs: Noto Sans/Serif CJK SC fonts, Tesseract with
#      English data, and a Python >= 3.10 able to create virtual environments
#        macOS  : Homebrew (installed first if missing, after asking you)
#        Linux  : apt-get (Debian/Ubuntu), dnf (Fedora/RHEL), pacman (Arch), zypper (openSUSE),
#                 run through sudo when you are not root
#   2. creates a private virtual environment  ~/.local/share/patt-pdf/venv  (nothing is written
#      into the system Python) and installs the full PATT-PDF package there, including OpenCV
#   3. links the command to  ~/.local/bin/patt-pdf  and tells you if that folder is not on PATH
#   4. runs `patt-pdf fonts` and `patt-pdf doctor` so the result is checked immediately
#
# Options (append after `bash -s --` when piping, e.g. `... | bash -s -- --ref v0.4.0`):
#   --ref REF          git branch, tag or commit to install (default: main)
#   --source DIR       install from a local checkout instead of downloading (for testing / CI)
#   --prefix DIR       installation folder (default: $XDG_DATA_HOME/patt-pdf or ~/.local/share/patt-pdf)
#   --bin-dir DIR      where the `patt-pdf` link goes (default: ~/.local/bin)
#   --python PATH      use this interpreter instead of searching for one
#   --pip-arg=ARG      extra argument for pip (repeatable, never split on spaces), e.g. a wheelhouse
#   --mirror cn        download through mirrors in mainland China (the default; see below)
#   --mirror official  download from the official sources (pypi.org, Homebrew, GitHub)
#   --no-uv            install the Python packages with pip even if `uv` is available
#   --no-system        do not install system packages (fonts, Tesseract, Python); only report them
#   --no-modify-path   never edit shell start-up files
#   --yes, -y          non-interactive: assume "yes" (also for installing Homebrew and editing PATH)
#   --uninstall        remove the virtual environment and the link created by this script
#   --help, -h         this text
#
# Download sources. Most users of an English->Chinese tool are in mainland China, where pypi.org
# and Homebrew's servers are slow. By default the script therefore uses the TUNA mirrors of
# Tsinghua University (pypi.tuna.tsinghua.edu.cn, mirrors.tuna.tsinghua.edu.cn). It says so
# before downloading anything and lets you choose the official sources instead; --mirror (or
# PATT_PDF_MIRROR=cn|official) answers the question in advance. If the mirror cannot be reached,
# the official sources are used. The mirror setting applies to this run only, with one exception
# that is announced: a Homebrew that this script installs through the mirror keeps the mirror
# as its update source.
#
# Windows is not covered by this script; see README.md.
#
# The whole script is wrapped in main() so that bash reads it completely before running anything
# (a half-downloaded script does nothing).

set -euo pipefail

PATT_REPO="${PATT_PDF_REPO:-SPIRAL-EDWIN/PATT-pdf}"
REF="main"
SOURCE=""
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/patt-pdf"
BIN_DIR="$HOME/.local/bin"
PYTHON=""
PIP_ARGS=()
MIRROR="${PATT_PDF_MIRROR:-}"                # cn | official | "" (ask)
PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
TUNA="https://mirrors.tuna.tsinghua.edu.cn"
USE_UV=1
STEPS=5
INSTALL_SYSTEM=1
MODIFY_PATH=1
ASSUME_YES=0
UNINSTALL=0
MARKER=".installed-by-patt-pdf-install-sh"
TMPDL=""
INSTALL_LOCK=""
REPLACE_VENV=0
FINISHED=0                                   # set to 1 only where the script ends on purpose

# ------------------------------------------------------------------ output helpers
tilde() { local p="$1"; case "$p" in "$HOME"/*|"$HOME") printf '~%s' "${p#"$HOME"}" ;; *) printf '%s' "$p" ;; esac; }
say()  { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '\n!!  %s\n' "$*" >&2; }
die()  { printf '\nerror: %s\n' "$*" >&2; exit 1; }
run()  { note "\$ $*"; "$@" </dev/null; }

# Messages in Chinese when the locale is Chinese (PATT_PDF_LANG overrides), otherwise English.
# In a string that contains non-ASCII text every variable is written ${name}. Bash asks the
# C library which bytes are letters; where bytes above 0x7f count as letters, the first byte
# of "（" is read as part of the name: "$SOURCE（" became the unset variable "SOURCE\xef" and
# ended the install. Seen with bash 3.2 on macOS under LC_ALL=C.UTF-8 (not under LC_ALL=C)
# and reproduced on Linux in a Latin-1 locale with bash 3.2 and 5.1.
# tests/test_install_script.py checks both the rule and a real run in such a locale.
ZH=0
case "${PATT_PDF_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in zh*|ZH*) ZH=1 ;; esac
L() { if [ "$ZH" = 1 ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
step() {                                      # step N "english" "中文"
  if [ "$ZH" = 1 ]; then printf '\n==> 第 %s/%s 步：%s\n' "$1" "$STEPS" "$3"
  else printf '\n==> Step %s/%s: %s\n' "$1" "$STEPS" "$2"; fi
}

usage() {
  cat <<'EOF'
PATT-PDF installer for macOS and Linux

  curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash -s -- [options]

Options:
  --ref REF          git branch, tag or commit to install (default: main)
  --source DIR       install from a local checkout instead of downloading
  --prefix DIR       installation folder (default: ~/.local/share/patt-pdf)
  --bin-dir DIR      where the patt-pdf link goes (default: ~/.local/bin)
  --python PATH      use this interpreter instead of searching for one
  --pip-arg=ARG      extra argument for pip (repeatable)
  --mirror cn        use mirrors in mainland China (default; you are asked first)
  --mirror official  use pypi.org, Homebrew and GitHub directly
  --no-uv            use pip even if uv is available
  --no-system        do not install system packages (fonts, Tesseract, Python)
  --no-modify-path   never edit shell start-up files
  --yes, -y          non-interactive: assume "yes" everywhere
  --uninstall        remove the virtual environment and the link created by this script
  --help, -h         this text
EOF
}

# Questions are read from the terminal, never from stdin (stdin is the script when piped).
confirm() {                                   # confirm "question" -> 0 = yes
  local answer
  if [ "$ASSUME_YES" = 1 ]; then note "$1 [auto-yes]"; return 0; fi
  if ! { printf '%s [y/N] ' "$1" >&3 && read -r answer <&3; } 2>/dev/null 3<>/dev/tty; then
    warn "no terminal to ask: '$1' — re-run with --yes to accept automatically"; return 1
  fi
  case "$answer" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

# ------------------------------------------------------------------ arguments
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --ref)        [ $# -ge 2 ] || die "--ref needs a value"; REF="$2"; shift 2 ;;
      --ref=*)      REF="${1#--ref=}"; shift ;;
      --source)     [ $# -ge 2 ] || die "--source needs a value"; SOURCE="$2"; shift 2 ;;
      --source=*)   SOURCE="${1#--source=}"; shift ;;
      --prefix)     [ $# -ge 2 ] || die "--prefix needs a value"; PREFIX="$2"; shift 2 ;;
      --prefix=*)   PREFIX="${1#--prefix=}"; shift ;;
      --bin-dir)    [ $# -ge 2 ] || die "--bin-dir needs a value"; BIN_DIR="$2"; shift 2 ;;
      --bin-dir=*)  BIN_DIR="${1#--bin-dir=}"; shift ;;
      --python)     [ $# -ge 2 ] || die "--python needs a value"; PYTHON="$2"; shift 2 ;;
      --python=*)   PYTHON="${1#--python=}"; shift ;;
      --pip-arg=*)  PIP_ARGS+=("${1#--pip-arg=}"); shift ;;
      --mirror)     [ $# -ge 2 ] || die "--mirror needs a value (cn or official)"; MIRROR="$2"; shift 2 ;;
      --mirror=*)   MIRROR="${1#--mirror=}"; shift ;;
      --no-uv)      USE_UV=0; shift ;;
      --no-system)  INSTALL_SYSTEM=0; shift ;;
      --no-modify-path) MODIFY_PATH=0; shift ;;
      --yes|-y)     ASSUME_YES=1; shift ;;
      --uninstall)  UNINSTALL=1; shift ;;
      --help|-h)    usage; FINISHED=1; exit 0 ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
  done
  case "$MIRROR" in ""|cn|official) ;; *) die "--mirror must be 'cn' or 'official' (got: $MIRROR)" ;; esac
  case "$PREFIX" in /*) ;; *) die "--prefix must be an absolute path" ;; esac
  case "$BIN_DIR" in /*) ;; *) die "--bin-dir must be an absolute path" ;; esac
  if [ "$PREFIX" = "/" ] || [ "$PREFIX" = "$HOME" ]; then die "refusing to use $PREFIX as the installation folder"; fi
}

# ------------------------------------------------------------------ platform
OS=""; PKG=""; SUDO=""
detect_platform() {
  case "$(uname -s)" in
    Darwin) OS=macos ;;
    Linux)  OS=linux ;;
    *) die "this installer supports macOS and Linux only; for Windows see README.md" ;;
  esac
  if [ "$OS" = linux ]; then
    if   command -v apt-get >/dev/null 2>&1; then PKG=apt
    elif command -v dnf     >/dev/null 2>&1; then PKG=dnf
    elif command -v pacman  >/dev/null 2>&1; then PKG=pacman
    elif command -v zypper  >/dev/null 2>&1; then PKG=zypper
    else PKG=none; fi
    if [ "$(id -u)" = 0 ]; then SUDO=""
    elif command -v sudo >/dev/null 2>&1; then SUDO=sudo
    else SUDO=""; [ "$PKG" = none ] || warn "sudo not found: system packages will be skipped unless you run as root"; PKG=none; fi
  fi
}

# ------------------------------------------------------------------ download source
own_index() {                                   # the caller chose a package index (or none) for pip
  local a
  for a in ${PIP_ARGS[@]+"${PIP_ARGS[@]}"}; do
    case "$a" in --index-url*|-i|-i=*|--no-index|--extra-index-url*) return 0 ;; esac
  done
  return 1
}

choose_mirror() {
  if [ "$INSTALL_SYSTEM" = 0 ] && own_index; then MIRROR=official; return 0; fi   # nothing left to choose
  if [ -z "$MIRROR" ]; then
    say "$(L "Where to download from" "选择下载来源")"
    note "$(L "This installer downloads Python packages (and on macOS Homebrew packages)." \
              "安装过程需要下载 Python 包（macOS 上还有 Homebrew 软件包）。")"
    note "$(L "  1) Mirror in mainland China [default]: Tsinghua University TUNA" \
              "  1) 国内镜像【默认】：清华大学 TUNA 镜像站")"
    note "       $PYPI_MIRROR"
    [ "$OS" = macos ] && note "       $TUNA/homebrew-bottles"
    note "$(L "  2) Official sources [slower from mainland China]: pypi.org, Homebrew, GitHub" \
              "  2) 官方源【在中国大陆较慢】：pypi.org、Homebrew、GitHub")"
    note "$(L "Mirror files are copies kept by the mirror operator, not served by the original publishers." \
              "镜像文件是镜像站保存的副本，不是由原发布方直接提供的。")"
    local answer=""
    if [ "$ASSUME_YES" = 1 ]; then
      MIRROR=cn; note "$(L "[auto] using the mirror; choose with --mirror official" "[自动] 使用镜像；如需官方源请加 --mirror official")"
    elif { printf '%s ' "$(L "Enter = keep the mirror, 2 = official sources:" "回车 = 保持镜像，输入 2 = 改用官方源：")" >&3 \
           && read -r answer <&3; } 2>/dev/null 3<>/dev/tty; then
      case "$answer" in 2|o|O|official|OFFICIAL) MIRROR=official ;; *) MIRROR=cn ;; esac
    else
      MIRROR=cn
      note "$(L "no terminal to ask in: using the mirror (re-run with --mirror official to change)" \
                "没有可提问的终端：使用镜像（如需官方源请加 --mirror official 重新运行）")"
    fi
  fi
  if [ "$MIRROR" = cn ] && command -v curl >/dev/null 2>&1 \
     && ! curl -fsS -m 8 -o /dev/null "$PYPI_MIRROR/pip/" </dev/null 2>/dev/null; then
    warn "$(L "the mirror did not answer within 8 seconds: using the official sources instead" \
              "镜像站 8 秒内没有响应：改用官方源")"
    MIRROR=official
  fi
  if [ "$MIRROR" = cn ]; then
    note "$(L "download source: MIRROR (Tsinghua TUNA)" "下载来源：镜像（清华 TUNA）")"
    # pip and uv read these; an explicit --pip-arg=--index-url still wins
    export PIP_INDEX_URL="$PYPI_MIRROR" UV_DEFAULT_INDEX="$PYPI_MIRROR" UV_INDEX_URL="$PYPI_MIRROR"
  else
    note "$(L "download source: OFFICIAL (pypi.org, Homebrew, GitHub)" "下载来源：官方源（pypi.org、Homebrew、GitHub）")"
  fi
}

# ------------------------------------------------------------------ Homebrew (macOS)
ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then return 0; fi
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then eval "$("$b" shellenv)"; return 0; fi
  done
  say "Homebrew is not installed"
  note "PATT-PDF uses Homebrew on macOS to install the Noto CJK fonts, Tesseract and (if needed) Python."
  note "The official Homebrew installer (https://brew.sh) would be downloaded and run now."
  note "It needs an administrator password and installs the Xcode Command Line Tools if they are missing."
  if ! confirm "Install Homebrew now?"; then
    die "Homebrew is required on macOS. Install it from https://brew.sh (or use --no-system and install fonts, Tesseract and Python >= 3.10 yourself), then re-run this installer."
  fi
  TMPDL="$(mktemp -d)"
  local got=0
  if [ "$MIRROR" = cn ]; then
    # Homebrew itself is cloned from the mirror and keeps it as its update source.
    export HOMEBREW_BREW_GIT_REMOTE="$TUNA/git/homebrew/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="$TUNA/git/homebrew/homebrew-core.git"
    note "$(L "Homebrew will be installed from the mirror and will keep it as its update source." \
              "Homebrew 将从镜像安装，并继续以镜像作为更新来源。")"
    note "$(L "To switch it back later:" "以后如需改回官方源：")  git -C \"\$(brew --repo)\" remote set-url origin https://github.com/Homebrew/brew"
    if xcode-select -p >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
      if run git clone --depth=1 "$TUNA/git/homebrew/install.git" "$TMPDL/brew-install"; then
        cp "$TMPDL/brew-install/install.sh" "$TMPDL/brew-install.sh"; got=1
      fi
    fi
  fi
  if [ "$got" = 0 ]; then
    run curl -fL --progress-bar -o "$TMPDL/brew-install.sh" https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
      || die "could not download the Homebrew installer"
  fi
  if [ "$ASSUME_YES" = 1 ]; then
    env -u INTERACTIVE NONINTERACTIVE=1 /bin/bash "$TMPDL/brew-install.sh" </dev/null || die "Homebrew installation failed"
  else
    env -u NONINTERACTIVE INTERACTIVE=1 /bin/bash "$TMPDL/brew-install.sh" </dev/tty || die "Homebrew installation failed"
  fi
  rm -rf "$TMPDL"
  TMPDL=""
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
  done
  command -v brew >/dev/null 2>&1 || die "Homebrew was installed but 'brew' is not on PATH; open a new terminal and re-run"
}

# ------------------------------------------------------------------ system packages
have_noto_fonts() {                             # both families already installed for this user or system-wide
  local fam d found
  for fam in NotoSansCJK NotoSerifCJK; do
    found=0
    for d in "$HOME/Library/Fonts" /Library/Fonts; do
      if ls "$d"/"$fam"* >/dev/null 2>&1; then found=1; break; fi
    done
    [ "$found" = 1 ] || return 1
  done
  return 0
}

install_system_macos() {
  ensure_homebrew
  step 1 "system components with Homebrew (fonts, Tesseract)" "用 Homebrew 安装系统组件（字体、Tesseract）"
  export HOMEBREW_NO_INSTALL_CLEANUP=1      # brew may still update itself first: current bottles need a current brew
  if [ "$MIRROR" = cn ]; then
    # for these brew calls only; an existing Homebrew is not reconfigured
    export HOMEBREW_API_DOMAIN="$TUNA/homebrew-bottles/api" HOMEBREW_BOTTLE_DOMAIN="$TUNA/homebrew-bottles"
    note "$(L "Homebrew packages come from the mirror for this run:" "本次运行的 Homebrew 软件包来自镜像：") $HOMEBREW_BOTTLE_DOMAIN"
  fi
  # casks: Noto Sans CJK / Noto Serif CJK (SIL OFL 1.1) into ~/Library/Fonts
  if have_noto_fonts; then
    note "$(L "Noto Sans/Serif CJK fonts are already installed: not downloaded again" "Noto Sans/Serif CJK 字体已安装：不重复下载")"
  else
    note "$(L "Noto CJK fonts: about 235 MB. Homebrew downloads them from GitHub (they are not on the mirror), so this is the slow part." \
              "Noto CJK 字体：约 235 MB。Homebrew 从 GitHub 下载（镜像上没有这两个文件），这是最慢的一步。")"
    run brew install --cask font-noto-sans-cjk font-noto-serif-cjk || die "font installation failed"
  fi
  note "$(L "Tesseract (OCR engine with English data) and the libraries it needs" "Tesseract（OCR 引擎，含英文数据）及其依赖库")"
  run brew install tesseract || die "Tesseract installation failed"   # includes English data
  if [ -z "$PYTHON" ] && ! find_python >/dev/null; then
    note "$(L "no Python >= 3.10 found: installing python@3.12 with Homebrew" "没有找到 Python >= 3.10：用 Homebrew 安装 python@3.12")"
    run brew install python@3.12 || die "Python installation failed"
  fi
}

install_system_linux() {
  if [ "$PKG" = none ]; then
    warn "no supported package manager (apt-get, dnf, pacman, zypper) or no sudo: skipping system packages"
    note "install yourself: Noto Sans/Serif CJK SC fonts, tesseract with English data, python3 (>= 3.10) with venv"
    return 0
  fi
  step 1 "system components with $PKG (fonts, Tesseract, Python)${SUDO:+; sudo may ask for your password}" \
         "用 $PKG 安装系统组件（字体、Tesseract、Python）${SUDO:+；sudo 可能会要求输入密码}"
  note "$(L "the package manager prints its own download size and progress" "包管理器会显示自己的下载量和进度")"
  local fail="system package installation failed (see the package manager's messages above)"
  case "$PKG" in
    apt)
      run $SUDO apt-get update || die "$fail"
      run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
          fonts-noto-cjk tesseract-ocr tesseract-ocr-eng python3 python3-venv python3-pip ca-certificates curl \
          || die "$fail" ;;
    dnf)
      run $SUDO dnf install -y google-noto-sans-cjk-fonts google-noto-serif-cjk-fonts \
          tesseract tesseract-langpack-eng python3 python3-pip ca-certificates curl || die "$fail" ;;
    pacman)
      run $SUDO pacman -S --needed --noconfirm noto-fonts-cjk tesseract tesseract-data-eng python python-pip curl \
          || die "$fail" ;;
    zypper)
      run $SUDO zypper --non-interactive install noto-sans-cjk-fonts noto-serif-cjk-fonts \
          tesseract-ocr tesseract-ocr-traineddata-english python3 python3-pip curl || die "$fail" ;;
  esac
}

# ------------------------------------------------------------------ Python
python_ok() {                                   # python_ok PATH -> 0 if >= 3.10 with venv+ensurepip
  [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {                                 # prints the first usable interpreter
  local c prefix v
  local candidates=()
  if [ "$OS" = macos ]; then
    for prefix in /opt/homebrew /usr/local; do
      for v in 3.13 3.12 3.11 3.10; do candidates+=("$prefix/bin/python$v"); done
    done
    for v in 3.13 3.12 3.11 3.10; do candidates+=("/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"); done
  fi
  candidates+=(python3.13 python3.12 python3.11 python3.10 python3)
  for c in "${candidates[@]}"; do
    # /usr/bin/python3 on a Mac without the Command Line Tools is a stub that opens a dialog
    if [ "$OS" = macos ] && [ "$(command -v "$c" 2>/dev/null || true)" = /usr/bin/python3 ] \
       && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if python_ok "$c"; then command -v "$c"; return 0; fi
  done
  return 1
}

# ------------------------------------------------------------------ install
fetch_source() {                                # sets SRC to a directory or an archive path
  TMPDL="$(mktemp -d)"
  if [ -n "$SOURCE" ]; then
    if [ ! -f "$SOURCE/pyproject.toml" ] || [ ! -d "$SOURCE/src/patt_pdf" ]; then die "--source $SOURCE is not a PATT-PDF checkout"; fi
    # Build from a clean copy of the package files only: nothing is written into the checkout and
    # leftover build/ or egg-info state there cannot break the install (see docs/STATUS.md R02).
    SRC="$TMPDL/src"
    mkdir -p "$SRC/src"
    cp "$SOURCE/pyproject.toml" "$SOURCE/README.md" "$SOURCE/LICENSE" "$SRC/"
    cp -R "$SOURCE/src/patt_pdf" "$SRC/src/patt_pdf"
    find "$SRC" \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +
    step 2 "PATT-PDF source: local copy of $SOURCE (no download)" "PATT-PDF 源码：使用本地目录 ${SOURCE}（不下载）"
    return 0
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required to download PATT-PDF"
  SRC="$TMPDL/patt-pdf.tar.gz"
  local url="https://github.com/$PATT_REPO/archive/$REF.tar.gz"
  step 2 "download PATT-PDF ($REF), about 2 MB, from GitHub" "从 GitHub 下载 PATT-PDF（${REF}），约 2 MB"
  note "$url"
  curl -fL --retry 3 --progress-bar -o "$SRC" "$url" </dev/null || die "download failed: $url"
}

python_download_mb() {                          # wheels of PyMuPDF, OpenCV, NumPy, fontTools (PyPI, 2026-11)
  case "$OS/$(uname -m)" in
    macos/arm64)   printf 85 ;;
    macos/x86_64)  printf 75 ;;
    linux/x86_64)  printf 110 ;;
    linux/aarch64|linux/arm64) printf 85 ;;
    *) printf 100 ;;
  esac
}

install_package() {
  local py="$1" venv="$PREFIX/venv" uv="" where
  if [ "$MIRROR" = cn ]; then where="$(L "mirror" "镜像")"; else where="$(L "official source" "官方源")"; fi
  step 3 "Python packages, about $(python_download_mb) MB from the $where (PyMuPDF, OpenCV, NumPy, fontTools)" \
         "Python 包，约 $(python_download_mb) MB，来自${where}（PyMuPDF、OpenCV、NumPy、fontTools）"
  note "$(L "virtual environment:" "虚拟环境：") $(tilde "$venv")"
  note "python: $py ($("$py" -c 'import platform; print(platform.python_version())'))"
  if [ -e "$venv" ] || [ -L "$venv" ]; then
    if [ -L "$venv" ] || [ ! -f "$venv/pyvenv.cfg" ] || [ ! -f "$PREFIX/$MARKER" ]; then
      die "$(tilde "$venv") was not created by this installer; choose another --prefix"
    fi
    note "keeping a backup of the existing environment until installation succeeds"
    mv "$venv" "$INSTALL_LOCK/previous-venv"
  fi
  REPLACE_VENV=1
  "$py" -m venv "$venv" </dev/null || die "could not create the virtual environment (on Debian/Ubuntu: sudo apt install python3-venv)"
  export PIP_DISABLE_PIP_VERSION_CHECK=1
  # uv downloads the packages in parallel. It is used when it is already on this machine and
  # never installed by this script. (One measurement on a fast connection showed no gain
  # over pip: 33 s against 27 s; the gain is expected on slow or lossy connections.)
  # --pip-arg options are pip's, so pip is used when any are given.
  if [ "$USE_UV" = 1 ] && [ "${#PIP_ARGS[@]}" = 0 ] && command -v uv >/dev/null 2>&1; then uv="$(command -v uv)"; fi
  if [ -n "$uv" ]; then
    note "$(L "installer: uv (found on this machine; parallel downloads)" "安装工具：uv（本机已有，并行下载）")"
    if "$uv" pip install --python "$venv/bin/python" "$SRC" </dev/null; then
      [ -x "$venv/bin/patt-pdf" ] || die "installation finished but $(tilde "$venv")/bin/patt-pdf is missing"
      return 0
    fi
    warn "$(L "uv failed; trying again with pip" "uv 安装失败；改用 pip 重试")"
  fi
  note "$(L "installer: pip (progress is shown per package)" "安装工具：pip（逐个包显示进度）")"
  # no --quiet: on a slow connection a silent install looks like a hang
  # ${arr[@]+"${arr[@]}"}: an empty array is an "unbound variable" for bash 3.2 (macOS) under set -u
  "$venv/bin/python" -m pip install ${PIP_ARGS[@]+"${PIP_ARGS[@]}"} "$SRC" </dev/null \
    || die "pip install failed (see pip's messages above)"
  [ -x "$venv/bin/patt-pdf" ] || die "installation finished but $(tilde "$venv")/bin/patt-pdf is missing"
}

check_command_path() {
  local link="$BIN_DIR/patt-pdf"
  if [ -e "$link" ] || [ -L "$link" ]; then
    if [ ! -L "$link" ] || [ "$(readlink "$link")" != "$PREFIX/venv/bin/patt-pdf" ]; then
      die "$(tilde "$link") already exists; choose another --bin-dir"
    fi
  fi
}

link_command() {
  step 4 "link the command to $(tilde "$BIN_DIR")/patt-pdf" "把命令链接到 $(tilde "$BIN_DIR")/patt-pdf"
  mkdir -p "$BIN_DIR"
  check_command_path
  if [ ! -L "$BIN_DIR/patt-pdf" ]; then
    ln -s "$PREFIX/venv/bin/patt-pdf" "$BIN_DIR/patt-pdf"
  fi
  case ":$PATH:" in
    *":$BIN_DIR:"*) ON_PATH=1 ;;
    *) ON_PATH=0 ;;
  esac
}

shell_rc_file() {
  case "$(basename "${SHELL:-}")" in
    zsh)  printf '%s' "${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) if [ "$OS" = macos ]; then printf '%s' "$HOME/.bash_profile"; else printf '%s' "$HOME/.bashrc"; fi ;;
    fish) printf '%s' "$HOME/.config/fish/config.fish" ;;
    *)    printf '%s' "$HOME/.profile" ;;
  esac
}

offer_path() {
  [ "$ON_PATH" = 1 ] && return 0
  local rc line quoted_dir
  rc="$(shell_rc_file)"
  # Quote custom paths before writing them into shell startup files.
  quoted_dir="$(printf '%s' "$BIN_DIR" | sed 's/[\"`$\\]/\\&/g')"
  case "$rc" in
    *config.fish) line="fish_add_path \"$quoted_dir\"" ;;
    *)            line="export PATH=\"$quoted_dir:\$PATH\"" ;;
  esac
  say "$(tilde "$BIN_DIR") is not on your PATH"
  if [ -f "$rc" ] && grep -qF -- "$line" "$rc"; then
    note "$(tilde "$rc") already contains the PATH line; open a new terminal (or run: $line)"
    return 0
  fi
  if [ "$MODIFY_PATH" = 1 ] && confirm "Add it to $(tilde "$rc") now?"; then
    mkdir -p "$(dirname "$rc")"
    { printf '\n# added by the PATT-PDF installer\n%s\n' "$line"; } >> "$rc"
    note "added; open a new terminal (or run: $line)"
  else
    note "add this line to $(tilde "$rc") (or run it in each terminal):"
    note "$line"
  fi
}

check_install() {
  local pp="$PREFIX/venv/bin/patt-pdf" rc=0
  step 5 "prepare fonts and check the installation (patt-pdf fonts, patt-pdf doctor)" \
         "准备字体并检查安装（patt-pdf fonts、patt-pdf doctor）"
  "$pp" fonts </dev/null || rc=$?
  note "patt-pdf doctor:"
  "$pp" doctor </dev/null || rc=$?
  return $rc
}

do_uninstall() {
  say "Uninstalling PATT-PDF from $(tilde "$PREFIX")"
  if [ -f "$PREFIX/$MARKER" ] && [ ! -L "$PREFIX/venv" ] && [ -f "$PREFIX/venv/pyvenv.cfg" ]; then
    if [ -L "$BIN_DIR/patt-pdf" ]; then
      case "$(readlink "$BIN_DIR/patt-pdf")" in
        "$PREFIX/venv/bin/patt-pdf") rm -f "$BIN_DIR/patt-pdf"; note "removed link $(tilde "$BIN_DIR")/patt-pdf" ;;
        *) note "$(tilde "$BIN_DIR")/patt-pdf points elsewhere; left alone" ;;
      esac
    fi
    rm -rf "${PREFIX:?}/venv" "${PREFIX:?}/${MARKER:?}"
    note "removed $(tilde "$PREFIX")/venv"
  elif [ -e "$PREFIX" ]; then
    note "no environment made by this script in $(tilde "$PREFIX"); left alone"
  else
    note "nothing to remove"
  fi
  note "kept: system packages (fonts, Tesseract, Python), the per-user font copies made by"
  note "'patt-pdf fonts', shell start-up lines and your own data."
}

lock_prefix() {
  mkdir "$PREFIX/.install-lock" || die "another install or uninstall is using $(tilde "$PREFIX")"
  INSTALL_LOCK="$PREFIX/.install-lock"
}

# Called by the EXIT trap.
# shellcheck disable=SC2317
cleanup() {
  if [ -n "$INSTALL_LOCK" ]; then
    if [ "$REPLACE_VENV" = 1 ]; then rm -rf "$PREFIX/venv"; fi
    if [ -d "$INSTALL_LOCK/previous-venv" ]; then
      mv "$INSTALL_LOCK/previous-venv" "$PREFIX/venv" || return 1
    fi
    rmdir "$INSTALL_LOCK"
    if [ "$UNINSTALL" = 1 ] && rmdir "$PREFIX" 2>/dev/null; then note "removed $(tilde "$PREFIX")"; fi
  fi
  if [ -n "$TMPDL" ]; then rm -rf "$TMPDL"; fi
}

# Bash 3.2 (macOS) leaves with status 0 when an EXIT trap runs after an "unbound variable"
# error, so an install that stopped half-way looked successful. The trap therefore keeps the
# real status, and an exit that did not come from the end of main() is never 0.
# shellcheck disable=SC2317
on_exit() {
  local rc=$?
  cleanup || true
  if [ "$FINISHED" != 1 ] && [ "$rc" = 0 ]; then
    printf '\nerror: the installer stopped before it finished (see the message above); nothing was installed\n' >&2
    rc=1
  fi
  exit "$rc"
}

# ------------------------------------------------------------------ main
main() {
  trap on_exit EXIT
  parse_args "$@"
  detect_platform
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [ "$UNINSTALL" = 1 ]; then
    if [ -d "$PREFIX" ]; then lock_prefix; fi
    do_uninstall; FINISHED=1; exit 0
  fi
  check_command_path

  say "PATT-PDF installer ($OS${PKG:+/$PKG}) — full install: fonts, Tesseract + English data, OpenCV"
  note "install folder: $(tilde "$PREFIX")   command: $(tilde "$BIN_DIR")/patt-pdf"
  choose_mirror
  if [ "$INSTALL_SYSTEM" = 1 ]; then
    if [ "$OS" = macos ]; then install_system_macos; else install_system_linux; fi
  else
    step 1 "system components: skipped (--no-system)" "系统组件：已跳过（--no-system）"
  fi

  if [ -z "$PYTHON" ]; then
    local hint="install python3 (>= 3.10) and python3-venv with your package manager"
    [ "$OS" = macos ] && hint="run: brew install python@3.12"
    PYTHON="$(find_python)" || die "no Python >= 3.10 with the venv module was found; $hint, then re-run"
  else
    python_ok "$PYTHON" || die "$PYTHON is not a Python >= 3.10 with venv and ensurepip"
  fi

  SRC=""
  fetch_source
  mkdir -p "$PREFIX"
  lock_prefix
  install_package "$PYTHON"
  link_command
  : > "$PREFIX/$MARKER"
  REPLACE_VENV=0
  rm -rf "$INSTALL_LOCK/previous-venv"
  offer_path

  local rc=0
  check_install || rc=$?
  if [ "$rc" = 0 ]; then
    say "Done. PATT-PDF is installed and complete."
  else
    warn "PATT-PDF is installed, but 'patt-pdf doctor' reported problems above (exit $rc)."
    note "Fix what it lists (fonts, Tesseract English data, environment), then run: patt-pdf doctor"
  fi
  [ "$ON_PATH" = 1 ] || note "remember to add $(tilde "$BIN_DIR") to PATH (see above)."
  note "try:        patt-pdf --help"
  note "upgrade:    re-run this installer"
  note "uninstall:  re-run this installer with --uninstall"
  FINISHED=1
  exit "$rc"
}

main "$@"
