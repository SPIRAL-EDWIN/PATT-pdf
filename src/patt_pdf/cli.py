"""Command line interface: ``patt-pdf <command> ...``.

All commands take ``SRC`` (a PDF file or a folder of PDFs, read-only) and ``--state DIR``
(private working directory: plans, translation memory, ledger, rendered output, QA).

Translation identity: `estimate`, `translate`, `render` and `publish` select cached
translations by backend + configuration (``--backend``, ``--manual-tm``, ``--glossary``).
Use the same options for all of them; translations from another backend are never used.

Exit codes (stable contract for scripts):
  0  complete: every file succeeded (render: every file QA status "pass")
  1  error: bad arguments, unreadable input, missing/stale plan, or an exception
  2  incomplete: partial translation, budget/quota refusal, QA status fail/unverified,
     or files skipped by publish
  3  needs review: rendered, no failures, but at least one file has QA status "review"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__

EXIT_OK, EXIT_ERROR, EXIT_INCOMPLETE, EXIT_REVIEW = 0, 1, 2, 3


def _ws(a):
    from .jobs import Workspace
    return Workspace(a.src, a.state)


def _files(ws, a):
    fs = ws.sources(getattr(a, "files", None))
    if not fs:
        from .osenv import long_path_problem
        hint = long_path_problem(os.path.abspath(a.src))
        raise SystemExit(f"error: no PDF files found in {a.src}" + (f" ({hint})" if hint else ""))
    return fs


def _pages(ws, a, files):
    """0-based page indexes selected by --pages, or None. The selection belongs to one
    document, so it needs exactly one input file."""
    spec = getattr(a, "pages", None)
    if not spec:
        return None
    from .pages import PageSelectionError, parse, resolve
    try:
        parse(spec)
        if len(files) != 1:
            raise PageSelectionError(f"--pages applies to one document, but {len(files)} PDF files are selected; "
                                     "name the file or narrow the folder with --files")
        import pymupdf
        try:
            with pymupdf.open(ws.path(files[0])) as d:
                n = d.page_count
        except Exception:
            return None                    # unreadable input: reported by the command itself
        return resolve(spec, n)
    except PageSelectionError as e:
        raise SystemExit(f"error: {e}") from None


def _progress(a):
    from .progress import Progress
    return Progress(quiet=bool(getattr(a, "quiet", False)))


def _ns(a):
    from .backends import PUBLISHABLE, namespace_for
    return namespace_for(a.backend, manual_tm=getattr(a, "manual_tm", None), glossary=getattr(a, "glossary", None)), \
        PUBLISHABLE[a.backend]


def cmd_plan(a):
    from .jobs import plan_file
    from .jobs import default_workers
    ws = _ws(a); deadline = time.time() + a.time_budget if a.time_budget else None
    worst = EXIT_OK
    files = _files(ws, a); pages = _pages(ws, a, files); prog = _progress(a)
    workers = a.workers if a.workers else default_workers()
    for rel in files:
        st = plan_file(ws, rel, ocr=not a.no_ocr, deadline=deadline, pages=pages, workers=workers, progress=prog)
        prog.clear()
        extra = st.get("error") or (f"page errors: {st['page_errors']} (retried on next run)" if st.get("page_errors") else "")
        if st.get("reused_pages"):
            extra = (extra + " " if extra else "") + f"(reused {st['reused_pages']} pages from an earlier interrupted run)"
        if st["status"] == "partial":
            extra = (extra + " " if extra else "") + f"(stopped by --time-budget after {st['pages']} of {st['total']} pages; run plan again to continue)"
        print(f"{st['status']:20s} {st.get('pages', ''):>4} pages  {rel}  {extra}")
        if st["status"] == "error":
            worst = max(worst, EXIT_ERROR)
        elif st["status"] in ("partial", "planned_with_errors"):
            worst = max(worst, EXIT_INCOMPLETE)
    return worst


def cmd_estimate(a):
    from .jobs import estimate
    ws = _ws(a); ns, _ = _ns(a); files = _files(ws, a)
    e = estimate(ws, files, ns, pages=_pages(ws, a, files))
    for rel, c in e["per_file"].items():
        print(f"{c:>9}  {rel}")
    for rel, why in e["problems"].items():
        print(f"{'?':>9}  {rel}  ({why})")
    print(f"page kinds: {e['page_kinds']}")
    print(f"translation identity: {ns}")
    print(f"TOTAL to translate: {e['chars']} characters in {e['segments']} unique segments "
          f"(already in translation memory for this identity: {e['cache_hits']} segments)")
    return EXIT_ERROR if any(not p.startswith("error:") for p in e["problems"].values()) else EXIT_OK


def cmd_usage(a):
    from .backends import DeepLBackend
    u = DeepLBackend(ledger=Path(a.state) / "ledger.jsonl").usage()
    print(f"DeepL usage: {u['character_count']} / {u['character_limit']} characters "
          f"({u['character_limit'] - u['character_count']} remaining)")
    return EXIT_OK


def cmd_translate(a):
    from .backends import make_backend
    from .jobs import translate
    if a.backend == "deepl" and not a.yes:
        print("error: refusing to call a paid API without --yes (run `estimate` first and set --max-chars)", file=sys.stderr)
        return EXIT_ERROR
    ws = _ws(a)
    be = make_backend(a.backend, ws.state, manual_tm=a.manual_tm, qps=a.qps)
    if a.backend == "deepl" and a.glossary:
        # local only; the glossary is created in the DeepL account after the budget checks
        be.set_glossary(Path(a.glossary), ws.state / "deepl_glossary.json")
    files = _files(ws, a)
    s = translate(ws, files, be, max_chars=a.max_chars, workers=a.workers,
                  time_budget_s=a.time_budget or None, pages=_pages(ws, a, files))
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return {"complete": EXIT_OK, "partial": EXIT_INCOMPLETE, "refused": EXIT_INCOMPLETE}.get(s["outcome"], EXIT_ERROR) \
        if not (s["outcome"] == "refused" and s["stopped"] and s["stopped"].startswith("plans missing")) else EXIT_ERROR


_RENDER_HINTS = {
    "file_in_use_or_read_only": "  -> close the output PDF in your viewer (or check permissions), then run render again;"
                                " the previous output was kept unchanged",
    "ocr_unavailable": "  -> install Tesseract or set PATT_PDF_TESSERACT; `patt-pdf doctor` shows what was found",
    "fonts_missing": "  -> run `patt-pdf fonts`; `patt-pdf doctor` shows the searched folders",
    "stale_plan": "  -> run `patt-pdf plan` again",
    "unreadable_input": "  -> repair, decrypt or remove the file, or leave it out with --files",
}


def cmd_render(a):
    from .jobs import render_file
    ws = _ws(a); ns, publishable = _ns(a)
    statuses = []
    files = _files(ws, a); pages = _pages(ws, a, files); prog = _progress(a)
    for rel in files:
        qa = render_file(ws, rel, ns, publishable=publishable, ocr_qa=not a.no_ocr_qa, pages=pages, progress=prog)
        prog.clear()
        st = qa.get("status", "error")
        flagged = [f"p{p.get('page', '?')}:{p.get('status', 'error')}" for p in qa.get("pages", [])
                   if p.get("status") != "pass"]
        if st == "error":
            detail = qa.get("error", "") + _RENDER_HINTS.get(qa.get("error_kind", ""), "")
        else:
            detail = " ".join(flagged)
        print(f"{st.upper():10s} {rel}  {detail}")
        statuses.append(st)
    if "error" in statuses:
        return EXIT_ERROR
    if any(s in ("fail", "unverified") for s in statuses):
        return EXIT_INCOMPLETE
    return EXIT_REVIEW if "review" in statuses else EXIT_OK


def cmd_report(a):
    from .report import markdown
    ws = _ws(a); md = markdown(ws, _files(ws, a))
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8", errors="backslashreplace"); print(f"wrote {a.out}")
    else:
        print(md)
    return EXIT_OK


def cmd_compare(a):
    from .report import compare
    ws = _ws(a)
    files = _files(ws, a); sel = _pages(ws, a, files)
    pages = [i + 1 for i in sel] if sel is not None else None
    n = 0
    for rel in files:
        for p in compare(ws, rel, pages, a.out, dpi=a.dpi):
            print(p); n += 1
    return EXIT_OK if n else EXIT_INCOMPLETE


def cmd_publish(a):
    from .jobs import publish
    ws = _ws(a)
    res = publish(ws, _files(ws, a), a.dest, min_status=a.min_status, suffix=a.suffix)
    for r in res:
        print(("published  " + r["to"] + f"  [{r['status']}]") if r["published"] else f"skipped    {r['rel']}: {r['why']}")
    return EXIT_OK if all(r["published"] for r in res) else EXIT_INCOMPLETE


def cmd_accept(a):
    ws = _ws(a)
    ws.accept(a.file, a.page, a.issue, a.note)
    print(f"accepted {a.issue} for {a.file} page {a.page} (recorded in {ws.state / 'accept.json'}); re-run render")
    return EXIT_OK


def cmd_tm(a):
    from .tm import TranslationMemory
    tm = TranslationMemory(Path(a.state) / "tm.jsonl")
    if a.action == "info":
        for ns, n in sorted(tm.namespaces().items()):
            print(f"{n:>7}  {ns}")
        return EXIT_OK
    ns, _ = _ns(a)
    n = tm.adopt_legacy(a.origin, ns)
    print(f"adopted {n} legacy '{a.origin}' records into {ns}")
    return EXIT_OK


def cmd_key(a):
    """Read a DeepL key from stdin (never from argv, which is visible in process lists)."""
    from .backends import save_deepl_key
    key = sys.stdin.readline()
    p = save_deepl_key(key, Path(a.path) if a.path else None)
    print(f"key saved to {p} (private file; the key was not printed)")
    return EXIT_OK


def cmd_fonts(a):
    from .fonts import font_dir, install_fonts
    rep = install_fonts()
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"font directory: {font_dir()}")
    return EXIT_ERROR if any(v.startswith(("MISSING", "FAILED")) for v in rep.values()) else EXIT_OK


def cmd_doctor(a):
    """Read-only environment report: platform, encodings, fonts, OCR. Changes nothing."""
    from . import __version__
    from .fonts import FACES, find_system_source, font_dir, search_dirs
    from .osenv import find_tesseract, install_warnings, platform_info, redact
    info = platform_info()
    home = os.path.expanduser("~")

    def show(p):
        return redact(str(p), {"~": home})
    rc = EXIT_OK
    print(f"patt-pdf {__version__}")
    for k in ("os", "machine", "python", "implementation", "locale_encoding", "filesystem_encoding",
              "utf8_mode", "stdout_encoding", "windows_long_paths_enabled",
              "pth_strategy", "pth_locale_encoding", "site_frozen"):
        print(f"  {k:28s} {info.get(k)}")
    fd = font_dir()
    ready = [f for f in FACES.values() if (fd / f).exists()]
    print(f"fonts: {len(ready)}/4 ready in {show(fd)}")
    if len(ready) < 4:
        rc = EXIT_INCOMPLETE
        for key, name in FACES.items():
            if name not in ready:
                src = find_system_source(key)
                print(f"  {name:24s} {'source: ' + show(src) if src else 'no source found'}")
        print("  search order: " + " | ".join(show(d) for d in search_dirs()))
        print("  fix: install Noto Sans/Serif CJK SC (OFL 1.1) or set PATT_PDF_FONT_SOURCE, then `patt-pdf fonts`")
    from .ocr import ocr_dependency_problem, tesseract_language_problem
    exe, how = find_tesseract()
    if exe:
        print(f"tesseract: {show(exe)} (via {how})")
        problem = tesseract_language_problem(exe)
        print(f"tesseract English data: {problem}" if problem else "tesseract English data: available")
        if problem:
            rc = EXIT_INCOMPLETE
    else:
        print(f"tesseract: not available ({how}); scanned and outlined pages will be FAIL/page_not_processed")
        rc = EXIT_INCOMPLETE
    cv = ocr_dependency_problem()                       # a real import: a broken cv2 counts as missing
    print("opencv: available" if cv is None else f"opencv: missing – {cv}")
    if cv:
        rc = EXIT_INCOMPLETE
    for w in install_warnings(info=info):
        print("warning: " + w); rc = max(rc, EXIT_INCOMPLETE)
    return rc


def build_parser():
    ap = argparse.ArgumentParser(prog="patt-pdf", description="Position-aware EN→ZH PDF translation (PATT-PDF, experimental)",
                                 epilog="exit codes: 0 complete, 1 error, 2 incomplete/refused/fail, 3 needs review")
    ap.add_argument("--version", action="version", version=f"patt-pdf {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, files=True):
        p.add_argument("src", help="PDF file or folder of PDFs (read-only)")
        p.add_argument("--state", required=True, help="private working directory")
        if files:
            p.add_argument("--files", help="glob filter on relative paths, e.g. 'reports/2026/*'")
        return p

    def pages(p):
        p.add_argument("--pages", metavar="LIST",
                       help="only these pages of one document: 7   7-9   7,9   1-3,7,10-  (1-based; "
                            "other pages stay as they are)")
        return p

    def quiet(p):
        p.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
        return p

    def identity(p, required=True):
        p.add_argument("--backend", required=required, choices=["deepl", "manual", "pseudo"],
                       help="translation identity: which cached translations to use")
        p.add_argument("--manual-tm", help="JSON {source: translation} for the manual backend")
        p.add_argument("--glossary", help="TSV glossary (DeepL); part of the translation identity")

    p = quiet(pages(common(sub.add_parser("plan", help="analyse pages (no translation, no network)"))))
    p.add_argument("--workers", type=int, default=0,
                   help="processes for pages that need OCR (default: CPU count, at most 4; 1 = no extra processes)")
    p.add_argument("--no-ocr", action="store_true", help="do not OCR vector/scanned pages (they will FAIL QA)")
    p.add_argument("--time-budget", type=float, default=0, help="stop starting new pages after N seconds (resumable)")
    p.set_defaults(fn=cmd_plan)

    p = pages(common(sub.add_parser("estimate", help="characters still needing translation (deduplicated)")))
    identity(p); p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("usage", help="show DeepL account usage (needs key; no translation)")
    p.add_argument("--state", required=True); p.set_defaults(fn=cmd_usage)

    p = pages(common(sub.add_parser("translate", help="fill the translation memory")))
    identity(p)
    p.add_argument("--max-chars", type=int, required=True, help="hard budget for this run (characters submitted)")
    p.add_argument("--yes", action="store_true", help="confirm paid API calls")
    p.add_argument("--qps", type=float, default=1.0); p.add_argument("--workers", type=int, default=2)
    p.add_argument("--time-budget", type=float, default=0)
    p.set_defaults(fn=cmd_translate)

    p = quiet(pages(common(sub.add_parser("render", help="write translated PDFs + QA into the state dir"))))
    identity(p)
    p.add_argument("--no-ocr-qa", action="store_true", help="skip OCR residual check (pages become 'unverified')")
    p.set_defaults(fn=cmd_render)

    p = common(sub.add_parser("report", help="Markdown QA report")); p.add_argument("--out"); p.set_defaults(fn=cmd_report)

    p = pages(common(sub.add_parser("compare", help="original|output PNGs for visual review")))
    p.add_argument("--out", required=True); p.add_argument("--dpi", type=int, default=80)
    p.set_defaults(fn=cmd_compare)

    p = common(sub.add_parser("publish", help="copy rendered PDFs to a destination folder"))
    p.add_argument("--dest", required=True)
    p.add_argument("--min-status", choices=["pass", "review"], default="pass",
                   help="pass (default): only fully passing files; review: also files needing human review")
    p.add_argument("--only-pass", action="store_true", help="deprecated alias of --min-status pass")
    p.add_argument("--suffix", default="", help="e.g. ' zh-Hans'")
    p.set_defaults(fn=cmd_publish)

    p = common(sub.add_parser("accept", help="explicitly accept a known limitation for a page (recorded)"), files=False)
    p.add_argument("--file", required=True); p.add_argument("--page", required=True, help="page number or *")
    p.add_argument("--issue", required=True); p.add_argument("--note", required=True, help="why this is acceptable")
    p.set_defaults(fn=cmd_accept)

    p = sub.add_parser("tm", help="inspect the translation memory / adopt legacy v0.1 records")
    p.add_argument("action", choices=["info", "adopt-legacy"]); p.add_argument("--state", required=True)
    p.add_argument("--origin", default="deepl", help="legacy origin to adopt (adopt-legacy)")
    identity(p, required=False)
    p.set_defaults(fn=cmd_tm)

    p = sub.add_parser("key", help="save a DeepL key read from stdin into a private file")
    p.add_argument("action", choices=["save"]); p.add_argument("--path", help="default: per-user config dir")
    p.set_defaults(fn=cmd_key)

    p = sub.add_parser("fonts", help="install CJK fonts from system Noto CJK (or PATT_PDF_FONT_SOURCE)")
    p.set_defaults(fn=cmd_fonts)

    p = sub.add_parser("doctor", help="read-only report: OS/CPU, encodings, fonts, Tesseract, install hazards")
    p.set_defaults(fn=cmd_doctor)
    return ap


_LOSSLESS = ("utf8", "utf_8", "utf8sig", "utf_8_sig", "utf16", "utf_16", "utf32", "utf_32", "gb18030")


def _safe_console():
    """Windows consoles/pipes often use a legacy code page (cp1252, cp936). Printing a
    file name like '报告 – résumé.pdf' must never abort a batch, so characters the stream
    cannot encode are escaped (backslashreplace) instead of raising UnicodeEncodeError.

    The error handler is replaced whenever it cannot represent arbitrary text: 'strict' (POSIX
    legacy locales) and also 'surrogateescape', which is CPython's DEFAULT for stdout/stderr on
    Windows (and for the C/POSIX locale): surrogateescape only round-trips undecodable bytes and
    raises for real characters such as '报' in cp1252. That was the Windows CI failure of
    ca38a93 (`plan` aborted with UnicodeEncodeError: 'charmap' ...). Streams with a UTF
    encoding are left alone."""
    import codecs
    for s in (sys.stdout, sys.stderr):
        try:
            enc = codecs.lookup(s.encoding or "ascii").name.replace("-", "_")
            if enc.replace("_", "") in {e.replace("_", "") for e in _LOSSLESS}:
                continue
            if (s.errors or "strict") in ("strict", "surrogateescape"):
                s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, LookupError):
            pass


def main(argv=None):
    _safe_console()
    a = build_parser().parse_args(argv)
    if getattr(a, "cmd", None) == "tm" and a.action == "adopt-legacy" and not a.backend:
        print("error: adopt-legacy needs --backend (and the same --glossary/--manual-tm as later runs)", file=sys.stderr)
        return EXIT_ERROR
    try:
        return a.fn(a) or EXIT_OK
    except SystemExit as e:
        print(e, file=sys.stderr); return EXIT_ERROR
    except Exception as e:                      # keep messages short; never print secrets
        from .osenv import redact
        roots = {"<input>": os.path.abspath(a.src) if getattr(a, "src", None) else "",
                 "<state>": os.path.abspath(a.state) if getattr(a, "state", None) else ""}
        print(redact(f"error: {type(e).__name__}: {e}", roots), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
