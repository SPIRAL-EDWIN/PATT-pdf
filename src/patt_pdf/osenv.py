"""Operating-system boundary of PATT-PDF.

PATT-PDF has ONE engine (planning, typesetting, QA, budget) for Linux, macOS and Windows.
Everything that legitimately differs between systems is collected here, so that platform
fixes are made once and tested with injected platform values on every OS:

* platform facts (OS, CPU architecture, encodings, long-path support) — `platform_info`;
* where fonts are searched, in a documented order without duplicates — `font_search_dirs`;
* where Tesseract is looked for — `tesseract_candidates` / `find_tesseract`;
* removal of absolute local paths from messages that end up in reports — `redact`;
* Windows path-length limits and the `\\\\?\\` extended-length form — `long_path_problem`,
  `extended_path`.

Atomic replacement and file-lock messages live in `jobs.replace_file`; key-file permissions
in `backends.save_deepl_key` (POSIX mode bits vs. inherited NTFS ACLs).
"""
from __future__ import annotations

import locale
import os
import platform
import re
import shutil
import sys
from pathlib import Path

WINDOWS_MAX_PATH = 260          # classic MAX_PATH incl. terminating NUL


# ---------------------------------------------------------------- platform facts
def _windows_long_paths_enabled() -> bool | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return bool(winreg.QueryValueEx(k, "LongPathsEnabled")[0])
    except OSError:
        return False


def platform_info() -> dict:
    getenc = getattr(locale, "getencoding", None)        # 3.11+, does not warn
    return {
        "os": {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux" if sys.platform.startswith("linux") else sys.platform),
        "machine": platform.machine().lower() or "unknown",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "locale_encoding": getenc() if getenc else locale.getpreferredencoding(False),
        "filesystem_encoding": sys.getfilesystemencoding(),
        "utf8_mode": bool(sys.flags.utf8_mode),
        "stdout_encoding": getattr(sys.stdout, "encoding", None),
        "windows_long_paths_enabled": _windows_long_paths_enabled(),
    }


def install_warnings(package_file: str | None = None, info: dict | None = None) -> list[str]:
    """Known installation hazards on this machine (read-only checks)."""
    info = info or platform_info()
    out = []
    pkg = str(package_file or Path(__file__).resolve())
    loc = (info.get("locale_encoding") or "").lower().replace("-", "")
    try:
        pkg.encode("ascii")
        non_ascii = False
    except UnicodeEncodeError:
        non_ascii = True
    if non_ascii and loc not in ("utf8", "cp65001") and not info.get("utf8_mode"):
        out.append("PATT-PDF is installed from a folder with non-ASCII characters while the locale encoding is "
                   f"{info.get('locale_encoding')}. Python reads the .pth file of an *editable* install "
                   "(pip install -e) with the locale encoding, so the import can fail in other processes. "
                   "Use a regular install (pip install .), an ASCII-only source folder, or set PYTHONUTF8=1.")
    if info.get("os") == "windows" and info.get("windows_long_paths_enabled") is False:
        out.append("Windows LongPathsEnabled is off: paths of 260+ characters fail (also pip's build "
                   "folders). Use short folders such as C:\\patt, or \\\\?\\ extended paths.")
    return out


# ---------------------------------------------------------------- fonts
def font_search_dirs(env: dict | None = None, os_name: str | None = None, home: str | None = None) -> list[Path]:
    """Folders searched by `patt-pdf fonts`, most specific first, without duplicates:

    1. $PATT_PDF_FONT_SOURCE (one or more folders, os.pathsep-separated): explicit choice;
    2. the user's own font folders (fonts installed "for me only");
    3. the system font folders.
    Only folders of the running OS are listed. Parameters allow testing other OSes."""
    env = os.environ if env is None else env
    os_name = os_name or {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    home = home or os.path.expanduser("~")
    sep = ";" if os_name == "windows" else ":"
    dirs: list[str] = [x for x in env.get("PATT_PDF_FONT_SOURCE", "").split(sep) if x]
    if os_name == "windows":
        la = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        dirs += [os.path.join(la, "Microsoft", "Windows", "Fonts"),
                 os.path.join(env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows", "Fonts")]
    elif os_name == "macos":
        dirs += [os.path.join(home, "Library", "Fonts"), "/Library/Fonts", "/opt/homebrew/share/fonts",
                 "/usr/local/share/fonts", "/System/Library/Fonts"]
    else:
        xdg = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        dirs += [os.path.join(xdg, "fonts"), os.path.join(home, ".fonts"),
                 "/usr/local/share/fonts", "/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk",
                 "/usr/share/fonts/google-noto-cjk", "/usr/share/fonts/opentype", "/usr/share/fonts"]
    out, seen = [], set()
    for d in dirs:
        key = os.path.normcase(os.path.normpath(d))
        if key not in seen:
            seen.add(key); out.append(Path(d))
    return out


# ---------------------------------------------------------------- Tesseract
def tesseract_candidates(env: dict | None = None, os_name: str | None = None) -> list[tuple[str, str]]:
    """(source, path-or-command) in lookup order: override, PATH, OS default install folders."""
    env = os.environ if env is None else env
    os_name = os_name or {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    c: list[tuple[str, str]] = []
    if env.get("PATT_PDF_TESSERACT"):
        c.append(("PATT_PDF_TESSERACT", env["PATT_PDF_TESSERACT"]))
    c.append(("PATH", "tesseract"))
    if os_name == "windows":
        for var, default in (("ProgramFiles", r"C:\Program Files"), ("LOCALAPPDATA", "")):
            base = env.get(var) or default
            if base:
                c.append((var, os.path.join(base, "Tesseract-OCR", "tesseract.exe")))
    elif os_name == "macos":
        c += [("Homebrew", "/opt/homebrew/bin/tesseract"), ("Homebrew (Intel)", "/usr/local/bin/tesseract")]
    return c


def find_tesseract(env: dict | None = None, os_name: str | None = None) -> tuple[str | None, str]:
    """(executable or None, how it was found / why not). An explicit override that does not
    exist is NOT silently replaced by another installation."""
    env = os.environ if env is None else env
    for source, cand in tesseract_candidates(env, os_name):
        if source == "PATH":
            hit = shutil.which(cand, path=env.get("PATH"))
            if hit:
                return hit, "PATH"
            continue
        if os.path.isfile(cand) or (source == "PATT_PDF_TESSERACT" and shutil.which(cand, path=env.get("PATH"))):
            return (cand if os.path.isfile(cand) else shutil.which(cand, path=env.get("PATH"))), source
        if source == "PATT_PDF_TESSERACT":
            return None, f"PATT_PDF_TESSERACT points to a missing file ({Path(cand).name})"
    return None, "tesseract not found on PATH or in the default install folders"


# ---------------------------------------------------------------- path redaction
# A path inside an exception text ends at a quote, a newline, or end of string; it may contain
# spaces and non-ASCII characters. Windows paths may appear raw (C:\\a), JSON/repr-escaped
# (C:\\\\a), with forward slashes (C:/a), extended (\\?\\C:\\a) or UNC (\\\\host\\share).
_STOP = "'\"\r\n<>|*?"
_WIN_START = re.compile(r"(?:\\\\\\\\\?\\\\(?:UNC\\\\)?|\\\\\?\\(?:UNC\\)?)?(?:[A-Za-z]:[\\/]|\\\\\\\\(?=\w)|\\\\(?=\w)|(?<=UNC\\)(?=\w)|(?<=UNC\\\\)(?=\w))")
_POSIX_START = re.compile(r"(?<![\w.:/])/(?=(?:Users|home|root|private|var|tmp|mnt|media|Volumes|sessions|opt|srv|data)/)")


def _norm(p: str) -> str:
    if p.startswith("\\\\\\\\?\\\\") or (p.count("\\\\") and not p.startswith("\\\\?\\")):
        p = p.replace("\\\\", "\\")              # JSON/repr-escaped: undo the doubling
    if p.startswith("\\\\?\\"):
        p = p[4:]
        if p.upper().startswith("UNC\\"):
            p = "\\\\" + p[4:]
    return p.replace("\\", "/")


def _span_end(s: str, i: int) -> int:
    j = i
    for pre in ("\\\\\\\\?\\\\UNC\\\\", "\\\\\\\\?\\\\", "\\\\?\\UNC\\", "\\\\?\\"):   # extended-length prefixes
        if s.startswith(pre, i):
            j = i + len(pre); break
    while j < len(s):
        if s[j] == "<":                         # an earlier redaction placeholder such as <USER>
            k = s.find(">", j)
            if 0 < k - j <= 12 and re.fullmatch(r"<[A-Za-z_]+>", s[j:k + 1]):
                j = k + 1; continue
        if s[j] in _STOP:
            break
        j += 1
    # an unquoted path ends at the last path-like character before trailing prose
    seg = s[i:j]
    m = re.search(r"\.[A-Za-z0-9]{1,5}(?=$|[\s:;,)\]])", seg)
    if j == len(s) or s[j] in "\r\n":
        if m:
            j = i + m.end()
        else:
            k = re.search(r"[:;,)\]]\s|\s+(?:failed|locked|denied|not|is|as|was|in)\b", seg)
            if k:
                j = i + k.start()
    return j


def redact(msg: str, roots: dict[str, str | os.PathLike] | None = None) -> str:
    """Replace absolute local paths in `msg` (one pass over the text).

    A path below a known root (input / state folder) becomes `<input>/rel/path` — the relative
    part is kept so the message still locates the file. Any other absolute path (home folder,
    temp dir, other drive, UNC share) becomes `<path>/<file name>`. Separators are normalised
    to `/`. Relative names inside the input folder are the user's own file names and are kept
    on purpose (README, privacy)."""
    s = str(msg)
    known = []
    for label, root in (roots or {}).items():
        if root:
            r = _norm(str(root)).rstrip("/")
            known.append((r.casefold() if re.match(r"^[A-Za-z]:/|^//", r) else r, r, label))
    known.sort(key=lambda t: len(t[1]), reverse=True)
    out, i = [], 0
    while i < len(s):
        m = _WIN_START.match(s, i) or _POSIX_START.match(s, i)
        if not m or (i > 0 and (s[i - 1].isalnum() or s[i - 1] in "/\\") and not s[i - 1] in " '\"(="):
            out.append(s[i]); i += 1; continue
        j = _span_end(s, i)
        p = _norm(s[i:j])
        repl = None
        for key, r, label in known:
            cmp = p.casefold() if key != r else p
            if cmp == key or cmp.startswith(key + "/"):
                repl = label + p[len(r):]; break
        if repl is None:
            name = p.rstrip("/").split("/")[-1]
            repl = "<path>/" + name if name else "<path>"
        out.append(repl); i = j
    return "".join(out)


# ---------------------------------------------------------------- Windows long paths
def long_path_problem(path: str | os.PathLike, os_name: str | None = None,
                      long_paths_enabled: bool | None = None) -> str | None:
    """A diagnosis if `path` will likely fail on Windows because of MAX_PATH, else None."""
    os_name = os_name or {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    if os_name != "windows":
        return None
    p = str(path)
    if p.startswith("\\\\?\\"):
        return None
    if long_paths_enabled is None:
        long_paths_enabled = bool(_windows_long_paths_enabled())
    if len(p) >= WINDOWS_MAX_PATH - 12 and not long_paths_enabled:
        return (f"path is {len(p)} characters; Windows limits classic paths to {WINDOWS_MAX_PATH - 1} unless "
                "'LongPathsEnabled' is set (administrator, registry or group policy). Use a shorter folder "
                "(e.g. C:\\patt\\in) or pass the folder as an extended path: \\\\?\\C:\\very\\long\\path")
    return None


def extended_path(path: str | os.PathLike) -> str:
    """Windows extended-length form of an absolute local or UNC path (no-op elsewhere)."""
    p = str(path)
    if not p or p.startswith("\\\\?\\"):
        return p
    p = os.path.abspath(p) if sys.platform == "win32" else p
    if re.match(r"^[A-Za-z]:\\", p):
        return "\\\\?\\" + p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return p
