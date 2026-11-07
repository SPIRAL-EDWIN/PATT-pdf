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
| `cli.py` | `patt-pdf` command | via backend |

**Resumability and staleness:** page plans are keyed by (file SHA-1, `ENGINE_VERSION`, OCR on/off) and stored per page, so interrupted planning resumes. Pages whose planning raised are not reused, so they are retried. Every consumer (`estimate`, `translate`, `render`, `publish`) calls `plan_state()`. It checks that the source exists, that the plan is complete, the engine version and the OCR setting, and the content (size and mtime first, then SHA-1 on mismatch). A stale plan is refused with a reason, never used.

**Translation identity (v0.2):** each TM record (`{"v":2,"ns","src","tgt","origin","ts"}`) belongs to a namespace `<backend>:<sha256(engine, language pair, backend config)[:16]>`. The backend config is the manual-TM content hash for `manual`, the glossary content hash plus request options for `deepl`, and nothing for `pseudo`. API keys never enter the namespace. Lookups only match the active namespace. v0.1 records live under `legacy:<origin>` and are used only after `patt-pdf tm adopt-legacy`. `pseudo` is not publishable, so its output is always QA `fail`.

**QA statuses:** each issue maps to `pass` < `review` < `unverified` < `fail` < `error` (`jobs.ISSUE_STATUS`); a page takes its worst issue and a file its worst page. Accepted limitations (`state/accept.json`, with a log) lower an accepted issue to `review`; issues in `NEVER_ACCEPTABLE` (number/URL mismatch, changed or lost keeps, untranslated, page errors, non-publishable backend) cannot be accepted. `publish` checks the status and that the source SHA-1 still matches the one QA saw.

**Budget metering:** `jobs.translate` gives the backend a `Meter`. The DeepL client calls `meter.before()` before every HTTP attempt, retries included; it refuses with `BudgetExceeded` if `--max-chars` would be exceeded. `meter.after()` classifies each attempt as answered, rejected (4xx: not processed) or unknown (timeout, network, 5xx: possibly billed). Remote setup (glossary creation) happens in `backend.prepare()`, after all budget checks.

**Underlines and links (`decor.py`):** `apply_plan` snapshots link annotations and finds decorations *before* any redaction. MuPDF redaction deletes overlapping link annotations and does not move vector lines. After drawing the Chinese text, removed decorations are redrawn at the recorded text geometry (`Unit._drawn`) and verified. Links are rebuilt from the snapshot with remapped rectangles. `render_file` then compares link targets on the saved file independently (`link_lost`).

**Concurrency:** translation submits at most `--workers` batches at a time (`wait(FIRST_COMPLETED)`). A shared stop event is set on quota or auth errors (or the time budget), after which no new batch is submitted; requests already in flight cannot be recalled and are counted as *possibly billed* if they fail. A single `DeepLBackend` instance holds a global token bucket (`--qps`) and a semaphore, so all workers share one rate limit. Planning and rendering are sequential per file; the active font set is a `ContextVar`, so a future threaded renderer does not share fonts across files.

**File writes:** JSON state is written UTF-8 via temp file + `os.replace`. Rendered PDFs are saved to a temp file and moved with `replace_file()`, which on `PermissionError` (typical on Windows when a viewer holds the file) keeps the old file, removes the temp file and reports that the file is in use.

**Error boundaries:** every file is processed inside its own try/except. Damaged, encrypted and 0-page files become `status: error` in the plan or QA, and the batch continues. A page that fails to plan becomes `kind: error` and is reported.
