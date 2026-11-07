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
        raise SystemExit(f"error: no PDF files found in {a.src}")
    return fs


def _ns(a):
    from .backends import PUBLISHABLE, namespace_for
    return namespace_for(a.backend, manual_tm=getattr(a, "manual_tm", None), glossary=getattr(a, "glossary", None)), \
        PUBLISHABLE[a.backend]


def cmd_plan(a):
    from .jobs import plan_file
    ws = _ws(a); deadline = time.time() + a.time_budget if a.time_budget else None
    worst = EXIT_OK
    for rel in _files(ws, a):
        st = plan_file(ws, rel, ocr=not a.no_ocr, deadline=deadline)
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
    ws = _ws(a); ns, _ = _ns(a); e = estimate(ws, _files(ws, a), ns)
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
    s = translate(ws, _files(ws, a), be, max_chars=a.max_chars, workers=a.workers,
                  time_budget_s=a.time_budget or None)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return {"complete": EXIT_OK, "partial": EXIT_INCOMPLETE, "refused": EXIT_INCOMPLETE}.get(s["outcome"], EXIT_ERROR) \
        if not (s["outcome"] == "refused" and s["stopped"] and s["stopped"].startswith("plans missing")) else EXIT_ERROR


def cmd_render(a):
    from .jobs import render_file
    ws = _ws(a); ns, publishable = _ns(a)
    statuses = []
    for rel in _files(ws, a):
        qa = render_file(ws, rel, ns, publishable=publishable, ocr_qa=not a.no_ocr_qa)
        flagged = [f"p{p['page']}:{p['status']}" for p in qa.get("pages", []) if p.get("status") != "pass"]
        detail = qa.get("error", "") if qa["status"] == "error" else " ".join(flagged)
        print(f"{qa['status'].upper():10s} {rel}  {detail}")
        statuses.append(qa["status"])
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
    pages = [int(x) for x in a.pages.split(",")] if a.pages else None
    n = 0
    for rel in _files(ws, a):
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

    def identity(p, required=True):
        p.add_argument("--backend", required=required, choices=["deepl", "manual", "pseudo"],
                       help="translation identity: which cached translations to use")
        p.add_argument("--manual-tm", help="JSON {source: translation} for the manual backend")
        p.add_argument("--glossary", help="TSV glossary (DeepL); part of the translation identity")

    p = common(sub.add_parser("plan", help="analyse pages (no translation, no network)"))
    p.add_argument("--no-ocr", action="store_true", help="do not OCR vector/scanned pages (they will FAIL QA)")
    p.add_argument("--time-budget", type=float, default=0, help="stop starting new pages after N seconds (resumable)")
    p.set_defaults(fn=cmd_plan)

    p = common(sub.add_parser("estimate", help="characters still needing translation (deduplicated)"))
    identity(p); p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("usage", help="show DeepL account usage (needs key; no translation)")
    p.add_argument("--state", required=True); p.set_defaults(fn=cmd_usage)

    p = common(sub.add_parser("translate", help="fill the translation memory"))
    identity(p)
    p.add_argument("--max-chars", type=int, required=True, help="hard budget for this run (characters submitted)")
    p.add_argument("--yes", action="store_true", help="confirm paid API calls")
    p.add_argument("--qps", type=float, default=1.0); p.add_argument("--workers", type=int, default=2)
    p.add_argument("--time-budget", type=float, default=0)
    p.set_defaults(fn=cmd_translate)

    p = common(sub.add_parser("render", help="write translated PDFs + QA into the state dir"))
    identity(p)
    p.add_argument("--no-ocr-qa", action="store_true", help="skip OCR residual check (pages become 'unverified')")
    p.set_defaults(fn=cmd_render)

    p = common(sub.add_parser("report", help="Markdown QA report")); p.add_argument("--out"); p.set_defaults(fn=cmd_report)

    p = common(sub.add_parser("compare", help="original|output PNGs for visual review"))
    p.add_argument("--out", required=True); p.add_argument("--pages"); p.add_argument("--dpi", type=int, default=80)
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
    return ap


def _safe_console():
    """Windows consoles/pipes often use a legacy code page (cp1252, cp936). Printing a
    file name like '报告 – résumé.pdf' must never abort a batch, so unencodable characters
    are escaped instead of raising UnicodeEncodeError."""
    for s in (sys.stdout, sys.stderr):
        try:
            if (s.errors or "strict") == "strict":
                s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
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
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
