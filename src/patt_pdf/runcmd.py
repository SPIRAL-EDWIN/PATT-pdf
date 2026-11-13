"""``patt-pdf run``: plan → estimate → confirm → translate → render → copy, in one command.

Every rendered file is copied to ``--out`` whatever its status, and the terminal shows one
line per file: status, pages, the main reason, the output file. No status file is written;
`patt-pdf report` gives the details. A paid backend is only called after a yes at the
prompt, or with both ``--max-chars`` and ``--yes`` when there is no terminal to ask in.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

EXIT_OK, EXIT_ERROR, EXIT_INCOMPLETE, EXIT_REVIEW = 0, 1, 2, 3

# issue -> (English, Chinese) phrase for the one-line summary
REASONS = {
    "untranslated": ("text without a translation", "有文字未翻译"),
    "number_or_url": ("a number or URL differs from the source", "数字或网址与原文不一致"),
    "keep_changed": ("a kept figure changed", "保留的内容被改动"),
    "keep_lost": ("a kept figure was lost", "保留的内容丢失"),
    "residual_english": ("English left on the page", "页面残留英文"),
    "overflow": ("translation does not fit its box", "译文放不下"),
    "page_error": ("page could not be analysed", "页面分析出错"),
    "page_not_processed": ("page not processed (OCR unavailable)", "页面未处理（OCR 不可用）"),
    "textured_background_left_english": ("text on a textured background not translated", "复杂背景上的文字未翻译"),
    "image_text_left_english": ("text inside images not translated", "图片内文字未翻译"),
    "not_publishable_backend": ("placeholder text (pseudo backend)", "占位文本（pseudo 后端）"),
    "mixed_translation_sources": ("translations from several sources", "译文来源不一"),
    "residual_check_skipped": ("leftover-English check could not run", "残留英文检查未能运行"),
    "image_not_inspected": ("image could not be checked", "图片未能检查"),
    "image_unverified": ("image could not be checked", "图片未能检查"),
    "possible_text_not_checked": ("possible text could not be checked", "疑似文字未能检查"),
    "source_repaired": ("the source PDF was damaged", "源文件有损坏"),
    "ocr_digits_review": ("figures read by OCR", "数字由 OCR 读取"),
    "shrunk": ("text was shrunk to fit", "字号被缩小"),
    "keep_restored": ("a kept figure was redrawn", "保留的内容被重画"),
    "override_used": ("a manual override was used", "使用了人工覆盖译文"),
    "patch_on_textured_background": ("patch on a textured background", "复杂背景上有修补"),
    "decoration_not_adjusted": ("underline not adjusted", "下划线未调整"),
    "link_area_not_mapped": ("link area not matched", "链接区域未对上"),
    "markup_annotation_on_translated_text": ("annotation on translated text", "译文上有批注"),
    "possible_underline_in_image": ("possible underline inside an image", "图片内可能有下划线"),
    "decoration_check_failed": ("underline check failed", "下划线检查失败"),
    "link_lost": ("a link was lost", "链接丢失"),
    "text_crosses_rule": ("text crosses a table rule", "文字越过表格线"),
    "translation_left_source": ("a translation was unusable; source text kept", "译文不可用，保留原文"),
    "curved_text_left_english": ("curved text not translated", "弯曲文字未翻译"),
}
WORDS = {
    "page": ("page", "页"), "pages": ("pages", "页"), "not_written": ("not written", "未输出"),
    "exists": ("exists, not written", "已存在，未写入"), "unreadable": ("cannot be read", "无法读取"),
    "render_error": ("could not be rendered", "渲染失败"),
}


def _zh() -> bool:
    v = os.environ.get("PATT_PDF_LANG") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return v.lower().startswith("zh")


def _w(key: str) -> str:
    return WORDS[key][1 if _zh() else 0]


def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, n: int) -> str:
    return s + " " * max(0, n - _width(s))


def main_reason(qa: dict) -> str:
    """The most frequent issue that causes the file's status, as a short phrase with a count."""
    from .jobs import ISSUE_STATUS
    st = qa.get("status")
    counts: dict[str, int] = {}
    for p in qa.get("pages", []):
        for i in p.get("issues", []):
            if ISSUE_STATUS.get(i.get("issue")) == st or (i.get("accepted") and st == "review"):
                counts[i["issue"]] = counts.get(i["issue"], 0) + 1
    if not counts:
        return ""
    k = max(counts, key=lambda x: counts[x])
    phrase = REASONS.get(k, (k, k))[1 if _zh() else 0]
    return f"{phrase} ×{counts[k]}" if counts[k] > 1 else phrase


def pages_text(qa: dict) -> str:
    pages = qa.get("pages", [])
    n = len(pages)
    if _zh():
        head = f"{n} 页"
    else:
        head = f"{n} page" if n == 1 else f"{n} pages"
    sts = [p.get("status", "error") for p in pages]
    if n <= 1 or len(set(sts)) == 1 and sts[0] == "pass":
        return head
    parts = [f"{sts.count(k)} {k}" for k in ("pass", "review", "unverified", "fail", "error") if sts.count(k)]
    return head + ("：" if _zh() else ": ") + " · ".join(parts)


def deliver(ws, src_pdf: Path, target: Path) -> str:
    """Copy a rendered PDF to `target`. Returns "written" or "exists".

    A file that is already there is never overwritten, with one exception: a file this
    working folder wrote itself and that has not been changed since (same SHA-1 as recorded
    in state/delivered.json) is replaced by the new render, so running the same command
    again updates its own output instead of refusing it."""
    import json
    from .jobs import atomic_write_text, replace_file, sha1_file
    rec_path = ws.state / "delivered.json"
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    except ValueError:
        rec = {}
    key = str(target)
    if target.exists() and rec.get(key) != sha1_file(target):
        return "exists"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".pdf"); os.close(fd)
    try:
        shutil.copyfile(src_pdf, tmp); replace_file(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    rec[key] = sha1_file(target)
    atomic_write_text(rec_path, json.dumps(rec, ensure_ascii=False, indent=1))
    return "written"


def _ask(question: str) -> bool:
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run(a) -> int:
    from . import fonts
    from .backends import AuthError, BackendError, PUBLISHABLE, make_backend
    from .jobs import Workspace, default_workers, estimate, plan_file, render_file, translate
    from .osenv import find_tesseract
    from .progress import Progress

    def say(msg):
        print(msg, file=sys.stderr)

    src = Path(a.src)
    if not src.exists():
        say(f"error: {a.src} does not exist"); return EXIT_ERROR
    out = Path(a.out).resolve()
    state = Path(a.state).resolve()
    src_r = src.resolve()
    if src_r.is_dir() and (out == src_r or src_r in out.parents):
        say("error: --out must not be inside the input folder (choose another folder with --out)"); return EXIT_ERROR
    try:
        ws = Workspace(src, state)
    except ValueError:
        say("error: the working folder would be inside the input folder; choose another one with --state")
        return EXIT_ERROR
    files = ws.sources(getattr(a, "files", None))
    if not files:
        say(f"error: no PDF files found in {a.src}"); return EXIT_ERROR

    # ---- before anything else: what is needed and how to get it
    fd = fonts.font_dir()
    if not all((fd / f).exists() for f in fonts.FACES.values()):
        fonts.install_fonts()                                  # copies from system fonts, no download
        if not all((fd / f).exists() for f in fonts.FACES.values()):
            say("error: Chinese fonts are missing. Install Noto Sans/Serif CJK SC, then run:  patt-pdf fonts\n"
                "       (`patt-pdf doctor` shows the folders that were searched)")
            return EXIT_ERROR
    try:
        backend = make_backend(a.backend, ws.state, manual_tm=a.manual_tm)
        if a.backend == "deepl" and a.glossary:
            backend.set_glossary(Path(a.glossary), ws.state / "deepl_glossary.json")
    except AuthError as e:
        say(f"error: {e}\n       set DEEPL_AUTH_KEY, or save the key once with:  pbpaste | patt-pdf key save   (macOS)\n"
            "                                                     xclip -o | patt-pdf key save   (Linux)")
        return EXIT_ERROR
    except BackendError as e:
        say(f"error: {e}"); return EXIT_ERROR
    interactive = sys.stdin is not None and sys.stdin.isatty()
    if backend.billable and not interactive and not (a.yes and a.max_chars is not None):
        say("error: no terminal to ask in. To call a paid service from a script, give both --max-chars N and --yes.\n"
            "       Nothing was sent.")
        return EXIT_INCOMPLETE
    if not a.no_ocr and not find_tesseract()[0]:
        say("warning: Tesseract not found; scanned pages and pages printed as outlines cannot be translated "
            "(`patt-pdf doctor` explains)")

    from .cli import _pages
    pages = _pages(ws, a, files)                               # SystemExit with a message on bad input
    prog = Progress(quiet=a.quiet)
    workers = a.workers or default_workers()

    # ---- plan
    unreadable: dict[str, str] = {}
    for rel in files:
        st = plan_file(ws, rel, ocr=not a.no_ocr, pages=pages, workers=workers, progress=prog)
        if st["status"] == "error":
            unreadable[rel] = st.get("error", "")
    prog.clear()
    good = [r for r in files if r not in unreadable]

    # ---- estimate and confirm
    ns = backend.namespace
    est = estimate(ws, good, ns, pages=pages) if good else {"chars": 0, "segments": 0, "cache_hits": 0}
    max_chars = a.max_chars if a.max_chars is not None else est["chars"]
    if good and est["chars"]:
        say(f"to translate: {est['chars']:,} characters in {est['segments']} segments "
            f"(already translated: {est['cache_hits']} segments)")
        if backend.billable:
            if est["chars"] > max_chars:
                say(f"error: that is more than --max-chars {max_chars:,}. Nothing was sent. "
                    "Raise the limit or select fewer pages with --pages."); return EXIT_INCOMPLETE
            if not a.yes:
                try:
                    u = backend.usage()
                    say(f"{backend.name} account: {u['character_limit'] - u['character_count']:,} of "
                        f"{u['character_limit']:,} characters left")
                except BackendError as e:
                    say(f"error: {e}"); return EXIT_ERROR
                if not _ask(f"Send {est['chars']:,} characters to {backend.name}?"):
                    say("nothing was sent."); return EXIT_INCOMPLETE
        s = translate(ws, good, backend, max_chars=max_chars, pages=pages, log=say)
        if s["outcome"] in ("refused", "failed"):
            say(f"error: translation did not start: {s.get('stopped')}")
            return EXIT_INCOMPLETE
        line = f"translated: {s.get('translated_chars', 0):,} characters"
        if s.get("repairs"):
            line += f"; {len(s['repairs'])} unusable answer(s) repaired or replaced by the source text"
        if s["outcome"] == "partial":
            line += f"; INCOMPLETE ({s.get('stopped') or 'some requests failed'}) - run the same command again to continue"
        say(line)

    # ---- render and copy
    rows = []
    for rel in files:
        target = out / rel
        if a.suffix:
            target = target.with_name(target.stem + a.suffix + target.suffix)
        shown = os.path.relpath(target, Path.cwd()) if _inside(target, Path.cwd()) else str(target)
        if rel in unreadable:
            rows.append(("error", rel, f"{_w('unreadable')} ({unreadable[rel][:60]})", "", _w("not_written"))); continue
        qa = render_file(ws, rel, ns, publishable=PUBLISHABLE[a.backend], ocr_qa=not a.no_ocr, pages=pages, progress=prog)
        prog.clear()
        st = qa.get("status", "error")
        if st == "error" or not ws.out_path(rel).exists():
            rows.append(("error", rel, f"{_w('render_error')} ({qa.get('error', '')[:70]})", "", _w("not_written"))); continue
        how = deliver(ws, ws.out_path(rel), target)
        if how == "exists":
            rows.append((st, rel, pages_text(qa), main_reason(qa), f"{shown}  ({_w('exists')})", True))
        else:
            rows.append((st, rel, pages_text(qa), main_reason(qa), "→ " + shown))
    w1 = max(_width(r[1]) for r in rows); w2 = max(_width(r[2]) for r in rows); w3 = max(_width(r[3]) for r in rows)
    for r in rows:
        print("  ".join([_pad(r[0], 6), _pad(r[1], w1), _pad(r[2], w2), _pad(r[3], w3), r[4]]).rstrip())
    sts = [r[0] for r in rows]
    blocked = any(len(r) > 5 for r in rows)
    if blocked or any(s in ("error", "fail", "unverified") for s in sts):
        return EXIT_INCOMPLETE
    return EXIT_REVIEW if "review" in sts else EXIT_OK


def _inside(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base.resolve()); return True
    except ValueError:
        return False


def cmd_run(a) -> int:
    t0 = time.time()
    try:
        return run(a)
    except KeyboardInterrupt:
        print("\ninterrupted. Finished pages and translations are kept; run the same command again to continue "
              f"({time.time() - t0:.0f} s).", file=sys.stderr)
        return 130

