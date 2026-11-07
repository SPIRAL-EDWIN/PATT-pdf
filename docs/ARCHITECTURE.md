# Architecture

```
            SRC (read-only)                      STATE (private)                       DEST
   ┌──────────────────────────┐   plan    ┌──────────────────────────┐  publish  ┌──────────────┐
   │ *.pdf (folder tree)      │ ────────▶ │ plans/<rel>.json (+parts)│ ────────▶ │ <rel>*.pdf   │
   └──────────────────────────┘           │ tm.jsonl  ◀── translate  │ (never    │ (structure   │
               │                          │ ledger.jsonl / runs.jsonl│ overwrite)│  preserved)  │
               │ render (reads src,       │ out/<rel>     ◀── render │           └──────────────┘
               │ writes only to state)    │ qa/<rel>.json ◀── render │
               └────────────────────────▶ └──────────────────────────┘
```

| Module | Responsibility | Network |
|---|---|---|
| `classify.py` | Page kind: text / vector / raster / vector_few (a few outline glyphs) / graphics / blank | no |
| `extract_text.py` | Text layer → cells (char-level, separator split, superscripts, rotated) | no |
| `ocr.py` | Tesseract CLI (3 passes), missed-word recovery, dash recovery, font-size and bold estimation | no |
| `grouping.py` | Cells → paragraphs (column-aware, table-row and bullet aware) | no |
| `keep.py` | What is never translated (figures, ratings, URLs, symbols) | no |
| `analyze.py` | Per-page planning plus image inventory | no |
| `typeset.py` | Chinese wrapping (line-break rules), fit and shrink, right extension | no |
| `render.py` | Erase (redaction / covered vector paths / patch), draw, restore displaced keeps | no |
| `decor.py` | Underlines, strike-through lines and link areas attached to translated text: detect, move or report; rebuild links deleted by redaction; text-crosses-rule check | no |
| `fonts.py` | Font discovery, per-document subset, CFF→glyf; context-local active font set | no |
| `backends.py` | `manual`, `pseudo`, `deepl` (rate limit, retries, stop on 456/401/403, ledger) | only `deepl` |
| `tm.py` | Append-only JSONL translation memory | no |
| `qa.py` | Number, URL, keep-integrity and residual-English checks | no |
| `jobs.py` | Workspace, resumable planning, estimate, budgeted translate, render, publish | via backend |
| `report.py` | Markdown report and side-by-side PNGs | no |
| `cli.py` | `patt-pdf` command, incl. read-only `doctor` | via backend |
| `osenv.py` | **OS boundary**: platform facts, font folders and their order, Tesseract discovery, path redaction, Windows long-path diagnosis | no |

**Resumability and staleness:** page plans are keyed by (file SHA-1, `ENGINE_VERSION`, OCR on/off) and stored per page, so interrupted planning resumes. Pages whose planning raised are not reused, so they are retried. Every consumer (`estimate`, `translate`, `render`, `publish`) calls `plan_state()`. It checks that the source exists, that the plan is complete, the engine version and the OCR setting, and the content (size and mtime first, then SHA-1 on mismatch). A stale plan is refused with a reason, never used.

**Translation identity (v0.2):** each TM record (`{"v":2,"ns","src","tgt","origin","ts"}`) belongs to a namespace `<backend>:<sha256(engine, language pair, backend config)[:16]>`. The backend config is the manual-TM content hash for `manual`, the glossary content hash plus request options for `deepl`, and nothing for `pseudo`. API keys never enter the namespace. Lookups only match the active namespace. v0.1 records live under `legacy:<origin>` and are used only after `patt-pdf tm adopt-legacy`. `pseudo` is not publishable, so its output is always QA `fail`.

**QA statuses:** each issue maps to `pass` < `review` < `unverified` < `fail` < `error` (`jobs.ISSUE_STATUS`); a page takes its worst issue and a file its worst page. Accepted limitations (`state/accept.json`, with a log) lower an accepted issue to `review`; issues in `NEVER_ACCEPTABLE` (number/URL mismatch, changed or lost keeps, untranslated, page errors, non-publishable backend) cannot be accepted. `publish` checks the status and that the source SHA-1 still matches the one QA saw.

**Budget metering:** `jobs.translate` gives the backend a `Meter`. The DeepL client calls `meter.before()` before every HTTP attempt, retries included; it refuses with `BudgetExceeded` if `--max-chars` would be exceeded. `meter.after()` classifies each attempt as answered, rejected (4xx: not processed) or unknown (timeout, network, 5xx: possibly billed). Remote setup (glossary creation) happens in `backend.prepare()`, after all budget checks.

**Underlines and links (`decor.py`):** `apply_plan` snapshots link annotations and finds decorations *before* any redaction. MuPDF redaction deletes overlapping link annotations and does not move vector lines. After drawing the Chinese text, removed decorations are redrawn at the recorded text geometry (`Unit._drawn`) and verified. Links are rebuilt from the snapshot with remapped rectangles. `render_file` then compares link targets on the saved file independently (`link_lost`).

**Concurrency:** translation submits at most `--workers` batches at a time (`wait(FIRST_COMPLETED)`). A shared stop event is set on quota or auth errors (or the time budget), after which no new batch is submitted; requests already in flight cannot be recalled and are counted as *possibly billed* if they fail. A single `DeepLBackend` instance holds a global token bucket (`--qps`) and a semaphore, so all workers share one rate limit. Planning and rendering are sequential per file; the active font set is a `ContextVar`, so a future threaded renderer does not share fonts across files.

**File writes:** JSON state is written UTF-8 via temp file + `os.replace`. Rendered PDFs are saved to a temp file and moved with `replace_file()`, which on `PermissionError` (typical on Windows when a viewer holds the file) keeps the old file, removes the temp file and reports that the file is in use.

**Error boundaries:** every file is processed inside its own try/except. Damaged, encrypted and 0-page files become `status: error` in the plan or QA, and the batch continues. A page that fails to plan becomes `kind: error` and is reported. QA schema invariant: every page entry has a `status`, also when the file fails after some pages were recorded; file errors carry an `error_kind` (`file_in_use_or_read_only`, `ocr_unavailable`, `fonts_missing`, `stale_plan`, `unreadable_input`, `os_error`, `internal_error`) that the CLI turns into an actionable hint. OCR that is missing only for the post-render residual check becomes `residual_check_skipped` on that page, not a file error.

## One engine, one OS boundary

Planning, typesetting, QA and budgeting are the same code on every system. A platform fix is made once and tested everywhere, with injected platform values (`osenv.font_search_dirs(env, os_name)`, `find_tesseract(env, os_name)`, `long_path_problem(path, os_name, enabled)`). OS-specific behaviour lives only at these boundaries:

| Concern | Where | Linux | macOS | Windows |
|---|---|---|---|---|
| Text encoding | all I/O names `encoding="utf-8"`; `tests/test_encoding.py` | same | same | same; console code page handled in `cli._safe_console` |
| Paths in messages | `osenv.redact` | POSIX | POSIX | raw, escaped, `/`, `\\?\`, UNC |
| Atomic replace / locks | `jobs.replace_file` | open files replaceable | open files replaceable | sharing violations → retry, then clear error, old file kept |
| Fonts | `osenv.font_search_dirs` | XDG, `~/.fonts`, `/usr/share/fonts` | `~/Library/Fonts`, `/Library/Fonts`, Homebrew | `%LOCALAPPDATA%\Microsoft\Windows\Fonts`, `%WINDIR%\Fonts` |
| Tesseract | `osenv.find_tesseract` | `PATH` | `PATH`, Homebrew | `PATH`, `%ProgramFiles%`, `%LOCALAPPDATA%` |
| Key file privacy | `backends.save_deepl_key` | 0600 / 0700 | 0600 / 0700 | inherited NTFS ACL of `%APPDATA%\patt-pdf` |
| Long paths | `osenv.long_path_problem` | — | — | diagnosis when `LongPathsEnabled` is off |

**Packaging path (not implemented):** today PATT-PDF is a Python package; `pip` chooses compatible wheels for the OS and CPU. Possible later steps, in order: published wheels/sdist on PyPI; a `pipx`/`uv tool` install recipe; optional helper that *suggests* (never silently downloads) fonts and Tesseract with source, licence and checksum; per-platform bundles or a GUI. An install script that detects OS and CPU (as some CLI tools do) is only a candidate; nothing of this is claimed until built and verified on real systems.
