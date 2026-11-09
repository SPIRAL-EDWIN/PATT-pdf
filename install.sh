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
#   --no-system        do not install system packages (fonts, Tesseract, Python); only report them
#   --no-modify-path   never edit shell start-up files
#   --yes, -y          non-interactive: assume "yes" (also for installing Homebrew and editing PATH)
#   --uninstall        remove the virtual environment and the link created by this script
#   --help, -h         this text
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
INSTALL_SYSTEM=1
MODIFY_PATH=1
ASSUME_YES=0
UNINSTALL=0
MARKER=".installed-by-patt-pdf-install-sh"
TMPDL=""
INSTALL_LOCK=""
REPLACE_VENV=0

# ------------------------------------------------------------------ output helpers
tilde() { local p="$1"; case "$p" in "$HOME"/*|"$HOME") printf '~%s' "${p#"$HOME"}" ;; *) printf '%s' "$p" ;; esac; }
say()  { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '\n!!  %s\n' "$*" >&2; }
die()  { printf '\nerror: %s\n' "$*" >&2; exit 1; }
run()  { note "\$ $*"; "$@" </dev/null; }

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
      --no-system)  INSTALL_SYSTEM=0; shift ;;
      --no-modify-path) MODIFY_PATH=0; shift ;;
      --yes|-y)     ASSUME_YES=1; shift ;;
      --uninstall)  UNINSTALL=1; shift ;;
      --help|-h)    usage; exit 0 ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
  done
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
  run curl -fsSL -o "$TMPDL/brew-install.sh" https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh
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
install_system_macos() {
  ensure_homebrew
  say "Installing fonts and Tesseract with Homebrew"
  export HOMEBREW_NO_INSTALL_CLEANUP=1      # brew may still update itself first: current bottles need a current brew
  # casks: Noto Sans CJK / Noto Serif CJK (SIL OFL 1.1) into ~/Library/Fonts
  run brew install --cask font-noto-sans-cjk font-noto-serif-cjk || die "font installation failed"
  run brew install tesseract || die "Tesseract installation failed"   # includes English data
  if [ -z "$PYTHON" ] && ! find_python >/dev/null; then
    say "No Python >= 3.10 found: installing python@3.12 with Homebrew"
    run brew install python@3.12 || die "Python installation failed"
  fi
}

install_system_linux() {
  if [ "$PKG" = none ]; then
    warn "no supported package manager (apt-get, dnf, pacman, zypper) or no sudo: skipping system packages"
    note "install yourself: Noto Sans/Serif CJK SC fonts, tesseract with English data, python3 (>= 3.10) with venv"
    return 0
  fi
  say "Installing fonts, Tesseract and Python with $PKG${SUDO:+ (via sudo; you may be asked for your password)}"
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
    return 0
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required to download PATT-PDF"
  SRC="$TMPDL/patt-pdf.tar.gz"
  local url="https://github.com/$PATT_REPO/archive/$REF.tar.gz"
  say "Downloading PATT-PDF ($REF)"
  note "$url"
  curl -fsSL --retry 3 -o "$SRC" "$url" </dev/null || die "download failed: $url"
}

install_package() {
  local py="$1" venv="$PREFIX/venv"
  say "Creating the virtual environment in $(tilde "$venv")"
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
  say "Installing PATT-PDF (full package, including OpenCV; PyMuPDF, NumPy and fontTools)"
  export PIP_DISABLE_PIP_VERSION_CHECK=1
  # ${arr[@]+"${arr[@]}"}: an empty array is an "unbound variable" for bash 3.2 (macOS) under set -u
  "$venv/bin/python" -m pip install --quiet ${PIP_ARGS[@]+"${PIP_ARGS[@]}"} "$SRC" </dev/null \
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
  say "Linking the command to $(tilde "$BIN_DIR")/patt-pdf"
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
  say "Preparing fonts (patt-pdf fonts)"
  "$pp" fonts </dev/null || rc=$?
  say "Checking the installation (patt-pdf doctor)"
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

# ------------------------------------------------------------------ main
main() {
  parse_args "$@"
  detect_platform
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [ "$UNINSTALL" = 1 ]; then
    if [ -d "$PREFIX" ]; then lock_prefix; fi
    do_uninstall; exit 0
  fi
  check_command_path

  say "PATT-PDF installer ($OS${PKG:+/$PKG}) — full install: fonts, Tesseract + English data, OpenCV"
  note "install folder: $(tilde "$PREFIX")   command: $(tilde "$BIN_DIR")/patt-pdf"
  if [ "$INSTALL_SYSTEM" = 1 ]; then
    if [ "$OS" = macos ]; then install_system_macos; else install_system_linux; fi
  else
    say "System packages skipped (--no-system)"
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
  exit "$rc"
}

main "$@"
