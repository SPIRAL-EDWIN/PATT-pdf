# Status of v0.3.2.dev0 (2026-11-07): experimental, cross-platform test candidate

**Milestone vs. version:** the product roadmap calls this stage "v0.2: cross-platform verification". The *package* version continues from 0.3.1 and is `0.3.2.dev0` (a development pre-release, not a stable release).

**Verified for this version:** only on Linux aarch64 (container), with synthetic PDFs and offline backends.
**Real-system evidence:** the macOS and Windows reports below were produced on **v0.3.1.dev0** (`6b969b8`). v0.3.2 has **not** been re-run on macOS or Windows.
**Not verified:** real-world PDFs, real DeepL calls, cp936/cp1252 Windows systems, Preview/Acrobat interaction, CI (written, not run).

## 0. Findings of the macOS and Windows runs of `6b969b8` (v0.3.1.dev0)

Sources: reviewer reports for macOS 27.2 arm64 (Python 3.11.16, no Tesseract) and Windows 11 x64 (Python 3.12.10, Tesseract 5.5.3, ACP 65001). Each item was re-checked against the logs and reproduced here where the environment allowed.

| ID | Report | Root cause (evidence) | Status in v0.3.2 | Tests |
|---|---|---|---|---|
| W03 / macOS P1 | `render` stops the batch with `KeyError: 'status'` without Tesseract, and when the output PDF is locked | **Same root cause on both systems, platform-independent.** After a page was appended to the QA without `status`, the post-render OCR residual check raised `OCRUnavailable` (no Tesseract) or `replace_file` raised `PermissionError` (lock). The file's except block set only the file status; `cli.cmd_render` then indexed `p['status']`. Reproduced on Linux by hiding Tesseract | **Fixed.** OCR missing for the residual check → `residual_check_skipped` (`unverified`) on that page; pages that could not be OCR'd at plan time stay `fail` (`page_not_processed`). Never `pass`. Every page always has a status. File errors get an `error_kind`, and the CLI prints an actionable hint. `replace_file` retries briefly, and its message names only the file. The batch continues | `tests/test_error_paths.py` (OCR missing at plan or render time, simulated lock, unexpected exception, schema guard; native Windows lock test runs only on Windows) |
| W01 / macOS | Encoding probe fails before the pipeline: `EncodingWarning` from `locale.getpreferredencoding()` | **Test design.** The probe turned *all* EncodingWarnings into errors and itself called `locale.getpreferredencoding()`, which warns on Python ≥ 3.11 (`-X warn_default_encoding`). Python 3.10 does not warn, so the Linux runs passed. Not a data-decoding defect | **Fixed in the test, detection kept.** The probe records each EncodingWarning with its source file and fails only on warnings from PATT-PDF code (exit 2), listing stdlib/third-party ones. It uses `locale.getencoding()` where available | `test_stdlib_encoding_warning_does_not_abort_probe` (simulates 3.11 on any version), `test_probe_detects_implicit_encoding_in_project_code` (the original defect still fails the probe) |
| macOS editable import | `ModuleNotFoundError: patt_pdf` with `LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0`, source in a Chinese-named folder, editable install | **CPython behaviour, not PATT-PDF code.** `site.addpackage` reads `.pth` files with `encoding="locale"`. setuptools writes the editable `.pth` (containing the non-ASCII source path) as UTF-8, so under ISO8859-1 the path is mis-decoded and not found. Reproduced with a UTF-8 `.pth` under CP1252 (wrong path) and GBK (`UnicodeDecodeError`); `PYTHONUTF8=1` fixes both. **Not the same root cause as W01** | **Documented and diagnosed, not "fixed".** `patt-pdf doctor` warns. README recommends a regular install, an ASCII-only folder or `PYTHONUTF8=1`. CI installs non-editable. The macOS setuptools version was not recorded; confirmation on macOS is pending | `test_pth_with_non_ascii_path_is_decoded_with_locale_encoding`, `test_editable_install_warning_for_non_ascii_source_and_legacy_locale` |
| W02 | Escaped Windows absolute path in `truncated.pdf.error.json` and the report | The old redaction replaced the literal root string only. PyMuPDF quotes the path with backslashes, which JSON then doubles | **Fixed.** `osenv.redact` normalises raw, escaped, `/`, `\\?\` and UNC Windows paths and POSIX home paths. Paths under the input or state folder keep their relative part (`<input>/sub/a.pdf`); others become `<path>/name` | `tests/test_osenv.py` (12 message shapes, injected Windows message end-to-end; on Windows itself still to be re-run) |
| W04 | `C:\Windows\Fonts` searched before the user font folder, and listed twice; POSIX folders listed on Windows | The README promised env → user → system, but the code listed a fixed cross-OS list containing `C:/Windows/Fonts`, then appended the Windows folders | **Fixed.** `osenv.font_search_dirs` gives, per OS, env → user → system, de-duplicated, with no other OS's folders. Verified by the actual file hit with the same file name in both folders | `test_windows_font_order_…`, `test_same_font_in_user_and_system_folder_user_wins`, `test_env_source_beats_user_and_system` |
| W05 | 307-character path: `no PDF files found` with `LongPathsEnabled=0`; pip's temp path too long | Windows MAX_PATH; not engine logic. Extended paths worked in the reviewer's run | **Diagnosed, not bypassed.** `osenv.long_path_problem` explains the cause in the "no PDF files found" error and in `doctor`. The docs advise short folders; the registry is not changed. Extended paths are mentioned as "worked in one test", not as supported. Long paths during pip installs remain an environment limit | `test_long_path_diagnosis_only_when_it_applies`, `test_no_pdfs_found_explains_long_path` |
| OCR detection in tests | `conftest.py` looked only at `PATH`, while the product also uses `PATT_PDF_TESSERACT` and the Windows default folders | — | **Fixed.** conftest uses `osenv.find_tesseract`, the same function as the product. An override that points to a missing file is reported, never silently replaced | `test_conftest_uses_product_detection`, `test_tesseract_order_and_explicit_override_is_not_replaced` |
| Not reproduced as defects | macOS without fonts: 64 passed, 60 skipped (expected: font-dependent tests skip); budget, isolation, stale plan, damaged files, cross-drive state, resume, links, ACL: **passed** on the reviewers' systems | — | unchanged | — |

**Mutations this round:** each fix was reverted on purpose, and the targeted tests failed every time:

- M19: OCR error not caught.
- M20: no page status, together with the old CLI line.
- M21: no lock hint.
- M22: old literal path redaction.
- M23: Windows system fonts before user fonts.
- M24: no long-path hint.
- M25: missing override silently replaced.
- The probe set back to "error on every EncodingWarning".

## 1. Findings of the Windows-acceptance review (on candidate `93ee393`), reproduced and fixed

| ID | Behaviour on `93ee393` (reproduced here) | Fix | Regression tests |
|---|---|---|---|
| Encoding (must fix) | `tests/conftest.py` read the UTF-8 `truth.json` with the platform default encoding. Reproduced on Linux with `LC_ALL=zh_CN.GBK PYTHONUTF8=0`: `UnicodeDecodeError` before any test ran. With a cp1252 default, `¥9,870` became mojibake | All text I/O in `src/` and `tests/` declares `encoding="utf-8"`. User-supplied files (manual TM, glossary, key file) accept a UTF-8 BOM (Notepad, Excel) and give a clear "not valid UTF-8" error otherwise, instead of guessing a code page. State and run logs no longer crash on undecodable POSIX file names | `tests/test_encoding.py`: an AST check that every text-mode `open`/`read_text`/`write_text`/`fdopen`/`subprocess(text=True)` names an encoding; a child-process pipeline run with `PYTHONUTF8=0` and `-X warn_default_encoding` (EncodingWarning = error), on Windows under the real ANSI code page; the same under GBK and Western POSIX locales where installed; plus BOM tests |
| Underline sample with PyMuPDF 1.25.2 | Codex's own sample stayed long but was marked `review` ("could not be removed safely"). Codex's file was not available here. A line drawn as a closed path (`m l h`, e.g. PyMuPDF `Shape` defaults) with round caps gave **the same message on 1.25.2 and 1.28.2** | A line drawn there and back is treated as one line; the redaction box is padded by half the line width plus 0.4 pt at the ends too, because MuPDF only removes line art whose *stroked* box (caps included) is covered | `test_closed_path_underline_is_one_line`, `test_dashed_segments_with_gaps_are_not_merged` |
| Damaged files (found while testing on 1.25.2) | With PyMuPDF 1.25.2 the truncated fixture is *reconstructed* by MuPDF into a page without content → classified blank → **pass** | Documents MuPDF had to reconstruct (`is_repaired`) get `source_repaired` (`unverified`) on every page | `test_reconstructed_pdf_is_never_a_clean_pass` |
| Windows-only test failure (found by review of the tests) | `test_key_file_permissions` expected a POSIX permission error on Windows, where the check deliberately does not apply | Marked POSIX-only; new cross-platform test reads a key file with BOM and CRLF | `test_key_file_is_read_as_utf8_with_or_without_bom` |

**Mutation check (this round):** each fix was reverted on purpose; the targeted tests failed every time. M12 repaired flag ignored · M13 closed-path merge removed · M14 end padding removed · M15 BOM not accepted · M16/M17 state writes without error handler · M18 key-file BOM. The encoding defect itself (`load_truth` without `encoding=`) makes 3 of the 6 encoding tests fail.

**Scope of the underline result:** the redraw is verified on the synthetic `decorations.pdf` and the closed-path sample with PyMuPDF 1.28.2 and 1.25.2 on Linux. Codex's 1.25.2 sample is not part of the suite; its cause is assumed, not confirmed. Where removal is not possible the page stays `review` — a conservative fallback, not a visual fix.

## 2. Findings of the third review (on `26ad5c3`), reproduced and fixed

Each finding was first reproduced through the CLI with offline backends.

| ID | Behaviour on `26ad5c3` (reproduced) | Fix | Regression tests |
|---|---|---|---|
| P0 underline | `SUMMARY OF REASONS` → `理由摘要`: the vector underline kept its English length (60→229 pt, text 60→116 pt); QA **pass** | New `decor.py`. Thin horizontal lines near a translated baseline are detected. They must not run more than max(3 pt, 0.8 × size) past the text and must not be joined to a vertical line. Full-line decorations are removed and redrawn under each line of the translation, keeping colour, thickness, dash pattern and baseline offset. Partial decorations move only if the underlined words appear verbatim in the translation. The result is checked on the page. Unmovable cases → `review` | `tests/test_decorations.py` (17 tests: shorter, longer, wrapped, filled-rect, strike-through, e-mail, pixel check, borders untouched, …) |
| P0 links (found while reproducing) | MuPDF redaction **deleted every link annotation** overlapping erased text (incl. `mailto:` links on kept addresses); QA **pass** | Links are snapshotted before editing and rebuilt afterwards. Targets never change, and rectangles over translated text are remapped. An independent check on the saved file compares link targets per page; a lost target is `fail` and cannot be accepted | `test_links_keep_targets_and_cover_the_new_text`, `test_lost_links_are_a_fail` |
| P0 QA gap (found while reproducing) | Translated table cells drawn **across a vertical table border**; QA **pass** | `text_crosses_rule` (`fail`): text that crosses a vertical rule (≥ 1.1 × font size tall) that the source line did not cross | `test_text_crossing_a_table_border_fails` |
| P1 blank pages | Page with a short outlined label ("Exit route", 9 glyph paths) → `blank` → **pass without checks** | New page kinds `vector_few` (3–19 glyph-like paths, no text layer) and `graphics` (drawings or small images, no text). `vector_few` is OCR'd when OCR is available, otherwise `unverified`. Only truly empty pages are `blank` | `test_few_outlined_glyphs_are_not_a_silent_pass`, `test_few_outlined_glyphs_are_ocrd_when_available` |
| P1 unreadable inputs | `translate` on a folder of damaged/encrypted PDFs, or a mix with nothing left to translate → `complete`, **exit 0** | All unreadable (or no input) → `failed`, exit 1. Some unreadable → `partial`, exit 2, with the files named and the recovery steps (repair/decrypt/remove + `plan`, or `--files`) | `test_unreadable_inputs_change_translate_outcome` |
| P1 retries | `--max-chars` limited first submissions only; up to 7 retries per batch could resend the same text, unaccounted | `Meter`: every HTTP attempt (retries included) is counted in `sent_chars` and refused *before sending* if it would exceed `--max-chars`. Each attempt is classified: answered; rejected (4xx such as 429/456: not processed); or unknown (timeout, network error, 5xx), counted as `possibly_billed_chars` | `test_meter_counts_retries_and_refuses_past_budget`, `test_rejected_attempts_are_not_possibly_billed`, `test_job_never_sends_more_than_max_chars` |
| P1 glossary | `--glossary` created the glossary in the DeepL account **before** the budget checks, even for runs that were then refused | `set_glossary()` is local only (digest for the translation identity). The remote glossary is created in `prepare()`, after all budget checks and only if there is something to translate | `test_glossary_is_not_created_when_the_run_is_refused` |
| Reports | Error messages contained absolute local paths | Input/state roots replaced by `<input>`/`<state>` | `test_error_messages_do_not_leak_local_paths` |

**Mutation check:** each fix was reverted on purpose and the targeted tests re-run. Every reversion was caught:

| Mutation | Result |
|---|---|
| M6: `vector_few` → `blank` | caught |
| M7: unreadable files ignored for the outcome | caught |
| M8: meter never refuses | caught |
| M9: glossary created before budget checks | caught |
| M10: links not restored | caught |
| M11: crossing check removed | caught |

The v0.2 mutations M1–M5 (identity, staleness, unverified-as-pass, submission bound, exit codes) remain covered by `tests/test_regressions_v02.py`.

**Public-material clean-up:** the synthetic fixtures were rewritten with invented themes (a birding society, a community observatory, a coastal trail) and invented figures. The pseudo backend's placeholder text was replaced. The v0.1 domain glossary data file was removed, and the docs no longer name private folders or files.

**Fixes from v0.2 that remain in force** (tests in `tests/test_regressions_v02.py`, `tests/test_reliability.py`):

* translation memory keyed by translation identity, so `pseudo` text is never reused or published;
* stale plans (content, page count, engine, OCR setting) refused by every command;
* statuses pass/review/unverified/fail/error, with `publish` requiring `pass`;
* exit codes 0/1/2/3;
* a bounded in-flight window with a global stop on quota or auth errors;
* an OCR timeout, safe key files, configurable fonts, clear errors for locked outputs, and no crash on legacy console code pages.

## 3. What the underline/link handling covers, and what it does not

| Situation | Handling | QA |
|---|---|---|
| Single stroked line (also drawn as a closed there-and-back path) or thin filled rectangle under or through a whole translated line (underline, strike-through) | Removed and redrawn under each new line; colour, thickness, dash pattern and baseline offset kept; offset scaled if the text shrank | `pass` if the redrawn line is verified on the page; `decoration_check_failed` → `fail` otherwise |
| Part of a line underlined, words found verbatim in the translation (URLs, e-mail addresses, numbers) | Moved under those words | `pass` |
| Part of a line underlined, words not found verbatim | Left exactly where it was | `review` (`decoration_not_adjusted`) |
| Decoration drawn as part of a larger path, under rotated text or under outlined (vector) text | Not changed | `review` (`decoration_not_adjusted`) |
| Line detected but MuPDF does not remove it (e.g. unusual path construction, other PyMuPDF versions) | Left at its original length; nothing redrawn | `review` (`decoration_not_adjusted: could not be removed safely`) — the page is **not** visually fixed |
| Underline in a scanned image | Detected (long dark row under an OCR line), not changed | `review` (`possible_underline_in_image`) |
| Markup annotations (Underline, StrikeOut, Squiggly, Highlight) over translated text | Not changed | `review` |
| Link over a whole translated paragraph, or over words found verbatim | Rectangle remapped to the new text; target unchanged | `pass` |
| Link over part of a translated sentence | Original rectangle and target kept | `review` (`link_area_not_mapped`) |
| Link target missing after rendering (any cause) | — | `fail` (`link_lost`) |
| Table borders, separators, long rules | Ignored by the detector: they run past the text or touch a vertical line | Translated text crossing a vertical border → `fail` |

**Not detected:** other visual relations to moved text, such as boxes, arrows, callouts or highlights drawn as filled shapes behind words. Double underlines whose two lines are more than 0.45 × font size below the baseline are also missed. And a bottom border that hugs the text without touching any vertical line could be mistaken for an underline and shortened (shown in `compare` output). Rendering checks cannot prove that a page *looks* right; use `patt-pdf compare`.

## 4. Test results

### v0.3.2.dev0, this environment (Linux aarch64 container, Python 3.10.12)

Dependencies: numpy 2.2.6, fontTools 4.65.0, opencv-python-headless 5.0.0.93, Pillow 12.3.0, pytest 9.2.0, pyflakes 4.0.3, Tesseract 4.1.1 (eng). The suite has 161 tests. `pyflakes src tests`: clean.

| Run | Result | Skips (reason) |
|---|---|---|
| PyMuPDF 1.28.2, C.UTF-8, Tesseract, GBK/CP1252 locales generated | 160 passed, 1 skipped | native Windows lock |
| same, Tesseract hidden | 155 passed, 6 skipped | 5 × OCR, 1 × Windows lock |
| `LC_ALL=zh_CN.GBK PYTHONUTF8=0` | 157 passed, 4 skipped | 2 × non-ASCII file names need a UTF-8 file system encoding on POSIX; 1 × `.pth` simulation needs a UTF-8 parent; 1 × Windows lock |
| `LC_ALL=en_US.CP1252 PYTHONUTF8=0` | 157 passed, 4 skipped | same |
| no legacy locales installed | 158 passed, 3 skipped | locale simulations, Windows lock |
| PyMuPDF 1.25.2 | 160 passed, 1 skipped | Windows lock |
| no CJK fonts | 93 passed, 68 skipped | font-dependent tests |

Python 3.11–3.13 could **not** be installed here (no network in this environment). The W01 fix is tested by simulating the 3.11 warning; it has not run on a real 3.11/3.12.

### v0.3.1.dev0 on real systems (reviewers, before these fixes)

| System | Result |
|---|---|
| macOS 27.2 arm64, Python 3.11.16, fonts, no Tesseract | 117 passed, 2 failed (W01), 5 skipped |
| Windows 11 x64, Python 3.12.10, Tesseract 5.5.3 | 120 passed, 1 failed (W01), 3 skipped |
| Windows, no Tesseract | 115 passed, 1 failed (W01), 8 skipped |

### CI

`.github/workflows/tests.yml` defines Linux x64/arm64, macOS arm64/x64 and Windows x64 jobs (Python 3.10–3.13, with and without Tesseract, plus a `PYTHONUTF8=0` encoding run on Windows). It has **never run**; no result can be claimed from it.

## 5. Not verified

* **macOS:** v0.3.1 was run by a reviewer without Tesseract (see §0); v0.3.2 not re-run; OCR, Preview locks, cross-volume and signals untested. Checklist: `docs/testing/MACOS_CHECKLIST.md`.
* **Windows:** v0.3.1 was run by a reviewer (see §0); v0.3.2 not re-run. Still untested: font directories, the `%APPDATA%` key location, the Tesseract default path, file locking, console code pages and the real ANSI code page (cp936/cp1252; only simulated with POSIX locales). Prompt: `docs/testing/WINDOWS_CODEX_PROMPT.md`.
* **Real DeepL calls through v0.2/v0.3:** none made. The ledger, the meter and the billed-delta reporting have not been checked against the live API.
* **Real-world PDFs:** the corpus contains only synthetic fixtures (14 files, 12 readable pages), and underline detection has only been tested on synthetic pages.
* **General OCR accuracy:** two synthetic scans and one outlined page.
* **Throughput** on large batches.

## 6. Known limits

* **Kept-text drift:** redaction can shift kept text that uses the `'`/`T*` operators. It is detected and restored (`keep_restored` → `review`), but no fixture covers that path yet.
* **No table structure:** cells on one row or in one column may be grouped into one unit. Text that does not fit shrinks (`review`), overflows (`fail`) or crosses a border (`fail`).
* **Images:** text inside images is never translated.
* **Billing:**
  * `sent_chars` counts every request PATT-PDF sent, retries included, and never exceeds `--max-chars`.
  * `possibly_billed_chars` covers requests whose outcome is unknown (timeout, network error, 5xx).
  * DeepL decides what it bills. PATT-PDF cannot guarantee the billed amount; keep the quota reserve.
* **Glossaries:** `--glossary` creates a glossary resource in your DeepL account (a remote write) the first time a run passes the budget checks. It is reused while the TSV content is unchanged and is not deleted by PATT-PDF.
* **Encodings:** files you supply (manual TM, glossary, key file) must be UTF-8 (a BOM is fine). On Linux/BSD with a non-UTF-8 locale, non-ASCII *file names* are not supported, because MuPDF passes file names to the OS as UTF-8; use a UTF-8 locale. Windows and macOS are not affected by this.
* **Reconstructed PDFs:** files MuPDF had to repair are `unverified` even if they look complete; accept them with `patt-pdf accept … --issue source_repaired` after checking.
* **AGPL:** PyMuPDF is AGPL-3.0 or commercial. Obligations depend on how PATT-PDF is distributed or deployed; this is not legal advice.

## 7. Compatibility notes

* `ENGINE_VERSION` is now `patt-0.3-e3` (v0.3.2), so existing state directories must be re-planned.
* QA files of failed renders gain `error_kind`; error messages use `<input>/…`, `<state>/…`, `<path>/name`.
* New command `patt-pdf doctor` (read-only).
* `fonts.SYSTEM_DIRS` is `None` by default (per-OS folders come from `osenv`).
* New QA issue `source_repaired` (`unverified`).
* `translate` exits 2 (not 0) when some inputs are unreadable, and 1 when none are readable.
* Run summaries gained `sent_chars`, `retry_attempts` and `rejected_chars`. `possibly_billed_chars` now comes from the per-attempt meter for DeepL.
* New QA issues:
  * `decoration_not_adjusted`, `link_area_not_mapped`, `markup_annotation_on_translated_text`, `possible_underline_in_image` (`review`);
  * `possible_text_not_checked` (`unverified`);
  * `decoration_check_failed`, `link_lost`, `text_crosses_rule` (`fail`).
* `DeepLBackend.ensure_glossary()` still works (it creates immediately); the CLI uses `set_glossary()` + `prepare()`.
* The packaged example glossary (`src/patt_pdf/data/*.tsv`) was removed; pass your own TSV with `--glossary`.
* v0.2 notes still apply: `estimate`/`render` need `--backend`, statuses replace `pass`, and v0.1 TM lines need `tm adopt-legacy`.

## 8. Next priorities

1. macOS and Windows verification (Codex), from the published candidate or a verified archive.
2. An openly licensed real-PDF regression corpus, including underlined headings and links.
3. Content-stream editing instead of redaction (removes the link-deletion and kept-text-drift workarounds).
4. Table detection.
5. Number locking before MT (DeepL XML tag handling).
6. CI on Linux, macOS and Windows.
