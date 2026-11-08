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
        "pth_strategy": pth_strategy(),
        "pth_locale_encoding": _locale_text_encoding(),
        "site_frozen": site_is_frozen(),
    }


def pth_strategy() -> str:
    """How this interpreter's site.py decodes .pth files: 'utf8-first' (CPython 3.13.0+ and the
    3.12.4+ backport: UTF-8 first, locale encoding only as a fallback), 'locale' (older: locale
    encoding only; on 3.11+ that encoding ignores UTF-8 Mode) or 'unknown'. Determined from the
    running interpreter, not from its version number (distributions may patch site.py).

    Reads the string constants of the *loaded* site.addpackage code object. Source inspection is
    not used: on CPython 3.11+ release builds `site` is a frozen module (co_filename '<frozen site>'),
    so inspect.getsource() fails, and the .py file on disk is not necessarily what runs."""
    import site

    def consts(co, depth=0):
        for c in co.co_consts:
            if isinstance(c, str):
                yield c
            elif hasattr(c, "co_consts") and depth < 4:
                yield from consts(c, depth + 1)
    try:
        found = set(consts(site.addpackage.__code__))
    except AttributeError:
        return "unknown"
    if "utf-8-sig" in found:
        return "utf8-first"
    return "locale" if "locale" in found else "unknown"


def site_is_frozen() -> bool:
    import site
    try:
        return site.addpackage.__code__.co_filename.startswith("<frozen")
    except AttributeError:
        return False


def _locale_text_encoding() -> str:
    """The encoding of io.TextIOWrapper(encoding="locale") – what an old-style site.py uses."""
    import io
    try:
        return io.TextIOWrapper(io.BytesIO(), encoding="locale").encoding
    except LookupError:
        return "unknown"


def install_warnings(package_file: str | None = None, info: dict | None = None) -> list[str]:
    """Known installation hazards on this machine (read-only checks)."""
    info = info or platform_info()
    out = []
    pkg = str(package_file or Path(__file__).resolve())
    try:
        pkg.encode("ascii")
        non_ascii = False
    except UnicodeEncodeError:
        non_ascii = True
    strategy = info.get("pth_strategy") or pth_strategy()
    loc = (info.get("pth_locale_encoding") or info.get("locale_encoding") or "").lower().replace("-", "")
    if non_ascii and strategy != "utf8-first" and loc not in ("utf8", "cp65001"):
        out.append("PATT-PDF is installed from a folder with non-ASCII characters, and this Python's site.py "
                   f"reads .pth files with the locale encoding ({info.get('pth_locale_encoding') or info.get('locale_encoding')}"
                   f"; strategy: {strategy}). An *editable* install (pip install -e) may then not be importable. "
                   "Use a regular install (pip install .) or an ASCII-only source folder. PYTHONUTF8=1 is not a "
                   "reliable fix: on Python 3.11+ it does not change the encoding site.py uses here. Python 3.12.4+ "
                   "and 3.13+ normally read .pth files as UTF-8 first (verify with `patt-pdf doctor`).")
    fs = (info.get("filesystem_encoding") or "utf-8").lower().replace("-", "")
    if non_ascii and fs not in ("utf8", "mbcs"):
        # Seen with real CPython 3.12.16 on Linux under zh_CN.GBK / en_US.CP1252 without UTF-8 Mode:
        # site.py decodes the .pth correctly as UTF-8, but the folder name is then re-encoded with
        # the file system encoding and no longer matches the UTF-8 name on disk. macOS and Windows
        # always use UTF-8 here; this is a Linux legacy-locale case, and PYTHONUTF8=1 does fix it.
        out.append(f"The Python file system encoding is {info.get('filesystem_encoding')} (a legacy locale "
                   "without UTF-8 Mode). Non-ASCII folder names created as UTF-8, including this editable "
                   "install's source folder, may not be found. Use a UTF-8 locale or set PYTHONUTF8=1 "
                   "(which changes the file system encoding), or use an ASCII-only folder.")
    if info.get("os") == "windows" and info.get("windows_long_paths_enabled") is False:
        out.append("Windows LongPathsEnabled is off: paths of 260+ characters fail (also pip's build "
                   "folders). Use short folders such as C:\\patt, or \\\\?\\ extended paths.")
    return out


# ---------------------------------------------------------------- fonts
def _host_os() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _flavour(os_name: str):
    """Path rules of the *target* OS (ntpath or posixpath), independent of the host: building
    macOS paths with the host's os.path on Windows gave '/Users/a\\Library\\Fonts', and
    Path() then turned it into '\\Users\\a\\Library\\Fonts' (Windows CI finding)."""
    import ntpath
    import posixpath
    return ntpath if os_name == "windows" else posixpath


def _as_path(p: str, os_name: str):
    """A concrete Path for the running OS; a pure path of the target OS when simulating another."""
    from pathlib import PurePosixPath, PureWindowsPath
    if (os_name == "windows") == (_host_os() == "windows"):     # same path family as the host
        return Path(p)
    return PureWindowsPath(p) if os_name == "windows" else PurePosixPath(p)


def font_search_dirs(env: dict | None = None, os_name: str | None = None, home: str | None = None) -> list[Path]:
    """Folders searched by `patt-pdf fonts`, most specific first, without duplicates:

    1. $PATT_PDF_FONT_SOURCE (one or more folders, separated by ';' on Windows, ':' elsewhere);
    2. the user's own font folders (fonts installed "for me only");
    3. the system font folders.
    Only folders of the running OS are listed. Parameters allow computing the list for another
    OS; paths then follow THAT OS's rules (separators, case-insensitive de-duplication on
    Windows) and are returned as pure paths, whatever the host is."""
    env = os.environ if env is None else env
    os_name = os_name or _host_os()
    fp = _flavour(os_name)
    home = home or os.path.expanduser("~")
    sep = ";" if os_name == "windows" else ":"
    dirs: list[str] = [x for x in env.get("PATT_PDF_FONT_SOURCE", "").split(sep) if x]
    if os_name == "windows":
        la = env.get("LOCALAPPDATA") or fp.join(home, "AppData", "Local")
        dirs += [fp.join(la, "Microsoft", "Windows", "Fonts"),
                 fp.join(env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows", "Fonts")]
    elif os_name == "macos":
        dirs += [fp.join(home, "Library", "Fonts"), "/Library/Fonts", "/opt/homebrew/share/fonts",
                 "/usr/local/share/fonts", "/System/Library/Fonts"]
    else:
        xdg = env.get("XDG_DATA_HOME") or fp.join(home, ".local", "share")
        dirs += [fp.join(xdg, "fonts"), fp.join(home, ".fonts"),
                 "/usr/local/share/fonts", "/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk",
                 "/usr/share/fonts/google-noto-cjk", "/usr/share/fonts/opentype", "/usr/share/fonts"]
    out, seen = [], set()
    for d in dirs:
        key = fp.normcase(fp.normpath(d))
        if key not in seen:
            seen.add(key); out.append(_as_path(fp.normpath(d), os_name))
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
    if os_name == "windows":        # host os.path on purpose: candidates are checked on this file system
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
# Any absolute POSIX path with at least two segments ("/a/b"), not only well-known top-level
# folders (custom mounts such as /custom/private/x.pdf were missed before). Not matched: URLs
# ("https://h/a" – the "/" is preceded by ":" or "/"), fractions and "and/or" (no leading "/"
# at a word boundary), a single segment such as "/x", and DOIs ("doi:10.1/x").
_POSIX_START = re.compile(r"(?<![\w.:/\-~])(?:~(?=/))?/(?=[^/\s'\"<>|]+/[^\s'\"<>|])")
# Single-segment root paths ("/privatefile.pdf") are ambiguous: "/help", "/etc", "1/2" are more often
# prose or commands. They are redacted only when they look like a file, i.e. quoted as a whole
# ('/name' or "/name"), or carrying a file extension (/name.ext) at a word boundary.
_POSIX_ROOT_QUOTED = re.compile(r"(?<=['\"])/[^/\s'\"<>|]+(?=['\"])")
_POSIX_ROOT_EXT = re.compile(r"(?<![\w.:/\-~>])/[^/\s'\"<>|]+\.[A-Za-z0-9]{1,5}(?=$|[\s'\",;:)\]])")


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
    # file:// URLs carry local paths: reduce them to the plain path first ("file:///C:/a" too)
    s = re.sub(r"file:///(?=[A-Za-z]:/)", "", s)          # file:///C:/a  -> C:/a
    s = re.sub(r"file://(?=/)", "", s)                     # file:///etc/a -> /etc/a
    s = re.sub(r"file://(?=[^/\s])", r"\\\\", s)          # file://host/a -> \\host/a (UNC)
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
    s = "".join(out)

    def _root(m):
        return "<path>/" + m.group(0)[1:]
    s = _POSIX_ROOT_QUOTED.sub(_root, s)
    s = _POSIX_ROOT_EXT.sub(_root, s)
    return s


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
