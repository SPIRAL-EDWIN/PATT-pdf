# Status of v0.4.2.dev0 (2026-11-13): experimental test candidate (macOS/Linux scope)

**Milestone vs. version:** the product roadmap calls this stage "v0.2: cross-platform verification". The *package* version continues the existing line and is `0.4.2.dev0` (a development pre-release, not a stable release).

**Scope (user decision, 2026-11-08):** the maintainer's work (Claude) covers **macOS and Linux**. **Windows** development and native testing are done by a **Windows collaborator**. Windows support is not dropped: Windows code paths, Windows-specific tests, the Windows retest prompt and the Windows-only CI steps stay in the repository, but the default CI matrix no longer runs Windows jobs. **This version is not verified on Windows in any way.** Known Windows issues for the collaborator are listed in §0-WIN.

**The stage is NOT complete**, and completing it would not mean production readiness.

**Verified for this version (0.4.2.dev0):** on Linux aarch64 (container), CPython 3.10.12, PyMuPDF 1.28.2, with bash 5.1 and a bash 3.2.57 built from source: full suite 480 passed / 3 skipped with the real-document cache and a setuptools wheelhouse present; ShellCheck 0.10.0 clean. **Not run on macOS**: the two earlier candidates were (§0-R2 for `3f65b2a`, §0-R3 for `9cd953e`), this one is the fix for what the second run found. Not run in CI, not run on Python 3.11 or 3.13.
**CI of the previous public commit `c6c9ed5` (run 42487953018):** Linux 4/4 and macOS 3/3 passed; Windows 0/3 (collection error, §0-WIN). That result belongs to `c6c9ed5`, not to this version.

**Not verified:** this version on macOS (CI or the user's Mac) and on a real Linux machine; Windows (out of scope here); real-world PDFs beyond the twelve pages of §0-P (none in the repository); DeepL beyond those two runs; Preview/Acrobat interaction beyond opening.

## 0-R3. macOS check of 9cd953e: the installer stopped after step 1 and returned 0 (2026-11-13)

**Candidates and names.** The reports call the candidates by round: "v040" = `3f65b2a`, "v041" = `9cd953e`. Both reported package version `0.4.0.dev0`. The package version is now `0.4.2.dev0`, so the next round ("v042") and the version agree; there is no `0.4.1`.

**macOS run of `9cd953e` (Codex, the user's Mac: macOS 27.2.1, Apple M5, system bash 3.2.57, `LC_ALL=C.UTF-8`, CPython 3.12.16).** Report private, not in the repository.

| Check | Result |
|---|---|
| D2 map page | PASS: "HUNTING CREEK", "HAYWARD FAULT", "MAACAMA FAULT" and the curved "San Francisco Bay" are complete in Preview. The C23 fix of §0-R2 is confirmed on macOS |
| Real documents | 16 of 16 passed |
| D1 full suite | **FAIL**: 456 passed, 9 failed, 1 skipped. All nine in `tests/test_install_script.py` |
| D4–D7 installer | **FAIL**: `install.sh: line 372: SOURCE\xef: unbound variable` after step 1, no command created, **exit code 0**. With `LC_ALL=C` for the installer process only, all five runs completed |
| D8 Homebrew parts | not run |

| Defect | Cause | Change | Test |
|---|---|---|---|
| Install stops at "第 2/5 步" | `"… $SOURCE（不下载）"`: where the C library counts bytes above 0x7f as letters, bash reads the first byte of the full-width bracket as part of the variable name; the name is unset and `set -u` ends the script. The Chinese strings are arguments of every step, so English output did not avoid it | every variable next to non-ASCII text is written `${name}` (three places) | a static rule over the whole script; five-step runs under six locale settings × two message languages × every available bash; a run in a Latin-1 locale, which shows the failure on Linux with the old script |
| The stopped install returned 0 | bash 3.2 leaves with status 0 when an EXIT trap runs after an unbound-variable error (bash 5.1 returns 1) | the EXIT trap keeps the status, and an exit that does not come from the end of `main()` is never 0: it prints that the installer stopped and returns 1 | a copy of the script with a deliberate unbound variable must end non-zero under every bash; `--help`, `--uninstall`, argument errors and the doctor's exit code are unchanged |
| The suite did not catch it | the tests ran the script only with the bash on `PATH` under `C.UTF-8` on Linux, where neither defect shows | tests run every available bash (`/bin/bash` on macOS is 3.2; `PATT_TEST_BASH32` elsewhere); CI runs the installer on macOS with `/bin/bash` under `LC_ALL=C.UTF-8` | |

**How far this is reproduced.** A bash 3.2.57 built from the GNU sources on Linux shows both defects in a Latin-1 locale (`SOURCE\xef: unbound variable`, exit 0 with an EXIT trap) and neither after the fix. Under `C.UTF-8` on Linux the old script did not fail, so the exact macOS condition (`LC_ALL=C.UTF-8` with Apple's bash) is **not** reproduced here; the fix does not depend on the locale, but only a macOS run can confirm it.

**Timings measured on the Mac** (pip, `LC_ALL=C`, Python packages only, about 81 MB): mirror 48.9 s and 31.9 s; official sources 66.5 s, 73.9 s and 62.8 s. pip reported 6.7–16 MB/s from the mirror and 1.8–2.6 MB/s from pypi.org. Some runs overlapped, so these are indications from one machine and one hour, not a benchmark. uv was not installed there; the uv path is still verified with a stand-in only, plus one real run on Linux.

## 0-R2. macOS check of 3f65b2a and what changed after it (2026-11-13)

**macOS run (Codex, the user's Mac: macOS 27.2.1, Apple M5 arm64, CPython 3.12.16, PyMuPDF 1.28.2, Tesseract 5.5.4).** 26 checks of `docs/testing/MACOS_V04_CHECK_PROMPT.md` on commit `3f65b2a`: 25 PASS, 1 FAIL. Full suite 434 passed / 18 skipped without the corpus cache; the 16 real-document tests passed after `corpus_fetch.py` (7 of 7 documents verified). `plan` of the 6-page USGS fact sheet: 32.3 s with one worker, 11.6 s with four, same plan. The report is private and not in the repository.

| Finding | Cause | Change | Test |
|---|---|---|---|
| **C23 (FAIL):** on the map page "HUNTING CREEK" showed as "HUNTING CR" plus Chinese | the label follows a curve that passes through the vertical; its piece "EE" is a run at exactly 90°, was treated as a side label and translated | a run that continues a kept curved run is kept too, whatever its angle | synthetic curved label with a vertical piece |
| Found while reproducing: "HAYWARD" translated, "FAULT" of the same label kept | "FAULT" was part of a curve, "HAYWARD" a straight run before it | the next word at the same angle is kept as well | synthetic two-word label |
| Found while reproducing: the "r" of the curved "San Francisco Bay" vanished | the upright city label "Francisco" was translated; MuPDF removes a glyph when the redaction touches its upright bounding box, which is large for a slanted letter | slanted letters that are not being translated are remembered and redrawn at their origin and angle after the removal (`keep_restored`, review) | synthetic crossing; the real-document test checks every slanted letter |

Engine `patt-0.4-e2`. After these fixes, on Linux: 450 passed / 5 skipped with the cache (461 / 5 with the installer tests added below). **The fixes above have not been run on macOS.**

**Installer (`install.sh`), changed after the macOS run; verified on Linux only.**

| Change | State |
|---|---|
| Five numbered steps with what is downloaded and about how much; pip without `--quiet`; `curl --progress-bar` | 22 tests; ShellCheck 0.10.0 clean; `bash -n` |
| Download source: mirror in mainland China (Tsinghua TUNA) by default, announced, with the official sources as the other choice; `--mirror cn\|official`, `PATT_PDF_MIRROR`; fallback to official when the mirror does not answer; nothing written to pip or Homebrew configuration | tests with a fake `curl`/`uv` and a real pseudo-terminal for the question; a real run on Linux reached the mirror and resolved the packages |
| `uv` is used when already installed (never installed by the script); `--no-uv`; pip when `--pip-arg` is given or uv fails | tests with a fake `uv`; one real run with uv 0.13.4 |
| Messages in Chinese when the locale is Chinese | test |
| **Not verified:** any of this on macOS; the Homebrew parts in particular (mirror environment for `brew`, installing Homebrew from the mirror, skipping fonts that are already installed) have never run. The size figures are from PyPI and Homebrew metadata of 2026-11-13, not from a measured install. No timing comparison of mirror vs. official or uv vs. pip was made from mainland China: the sandbox connection is not representative | |

## 0-Q. v0.4.0.dev0: one command, page selection, tables, unusable translations (2026-11-13)

Engine `patt-0.4-e1` (plans are re-made). Everything below was run on Linux aarch64 only.

| Change | What it does | Evidence |
|---|---|---|
| `patt-pdf run` | plan → estimate → confirm → translate → render → copy to `--out`; one line per file on the terminal; every rendered file is delivered whatever its status; no status file | 13 tests; real run on the seven documents (below) |
| `--pages` | `7`, `7-9`, `7,9`, `1-3,7,10-` for plan, estimate, translate, render, compare, run; output keeps all pages; unselected pages are not listed anywhere | 42 tests incl. pixel-identical untouched pages |
| Progress and speed | progress on stderr (`--quiet` to silence); pages that need Tesseract are planned in up to 4 processes; render no longer loops over all vector paths per paragraph and opens each file once per page for the keep check | USGS fact sheet, 6 pages, `plan`: 79 s → 28 s with 4 workers, identical plan. Map page render: about 55 s → 16 s, identical pixels and QA |
| Unusable translations | text made only of names, codes and figures is not sent; answers are checked on arrival and when read from the cache; repair by removing an added language label, else one retry with context, else the source text stays (review) | 47 tests. On the 433 DeepL segments of §0-P: 8 not sent, 1 repaired, 0 others changed. The legend that had "简体中文（大陆）" appended is now shown unchanged |
| Curved text | runs that continue each other at changing angles, or letter-spaced runs, stay as they are and are listed (`curved_text_left_english`, review); straight slanted labels are translated at their angle | 6 tests; USGS map page: 41 of 51 slanted runs left in place, no overlapping labels |
| Table cells | rows are cut at vertical rules, or at the gutters of at least two aligned body rows with three or more cells | 7 tests; the header of the three-line table in arXiv 2302.13971 is seven cells |
| Real-document corpus | manifest with URL, SHA-256, licence; PDFs fetched into a cache, never committed | `tests/test_real_corpus.py`, 16 tests, skipped without the cache |

**DeepL re-run** (free API, 5,885 characters billed in this round: 61 + 2,176 + 3,648; the cap set by the user was 22,071). Fourteen pages, selected with `--pages` from the full documents:

| Document | Pages | Status per page | Cause of the worst status |
|---|---|---|---|
| arXiv 2201.11903v6 | 1, 4 | pass, fail | DeepL wrote "62 亿 / 540 亿" for "62B / 540B" (a real translation error, caught by the number check) |
| arXiv 2302.13971v1 | 1, 3, 8 | review, fail, review | page 3: the source caption says "65 models", DeepL wrote "65B" (it corrected a typo of the source; reported as a difference). Reviews: link areas not matched to the translated words |
| PLOS ONE e0262897 | 1, 2, 4 | fail, review, review | page 1: a footnote asterisk was redrawn in another face (`keep_changed`) |
| NIST CSWP 29 | 9, 11 | review, fail | page 11: text inside a diagram image |
| USGS FS 2016-3020 | 1, 3 | fail, fail | text inside images; curved labels left in English |
| USGS FS 2023-3003 | 1 | fail | text inside images |
| IRS W-9 | 1 | pass | |

Totals: 2 pass, 5 review, 7 fail. The twelve pages of §0-P are among them; compared with §0-P, one page went from pass to review (NIST page 9: a link inside a paragraph that is now kept whole is reported as not matched), and the two pages added in this round are review.

**Seen in this run and not fixed:** link rectangles inside long paragraphs are not matched to the translated words (most `review` pages); the retry with DeepL's `context` parameter is implemented and tested against a scripted backend, but no real answer needed it, so its effect on DeepL is not measured; author names are translated; inline styles are lost; "CSF Profiles" is still mistranslated without a glossary.

## 0-P. First run on real PDFs with DeepL (2026-11-13, v0.3.9.dev0, engine patt-0.3-e4)

**What was run.** Seven public documents were downloaded from their publishers (licence checked on the publisher's page): arXiv 2201.11903 and 2302.13971 (CC BY 4.0), PLOS ONE pone.0262897 (CC BY 4.0), NIST CSWP 29, USGS Fact Sheets 2016-3020 and 2023-3003, IRS Form W-9 (U.S. government works). Twelve pages were selected (page subsets, because there is no `--pages` option yet) and run through `plan → estimate → translate (DeepL free API) → render → report → compare` on Linux aarch64 (container), CPython 3.10.12, PyMuPDF 1.28.2, Tesseract present. 43,898 characters were billed in two runs (36,754 + 7,144 after the paragraph fix); the user set a cap of 50,000. The documents, outputs and the translation memory are local and are **not** in the repository; only two showcase images made from them are (`docs/showcase/`, sources in the README).

**Result after the fixes below** (PATT's own QA): 3 pages `pass`, 2 `review`, 7 `fail`. Before the fixes: 2 of 7 files ended as `ERROR`, 1 page passed.

| Finding on real documents | Cause | Change | Test |
|---|---|---|---|
| 2 of 7 files: `ERROR KeyError: 'nameddest'` | hyperref PDFs use named-destination links; the link rebuild copied a fixed key list without `nameddest` | key added; a link that cannot be re-created is reported as `link_lost` instead of aborting the file | synthetic PDF with a named link |
| A map page lost every letter "a" ("P CIFIC OCE N", "Coll y mi") | `restore_keeps` searched the page for a displaced one-letter keep ("A"); `search_for` ignores case and matches inside words; every hit was redacted | displaced-copy removal only for keeps of 3+ characters and exact matches | `restore_keeps` on a page with "A" and "Banana Canal" |
| Helvetica, Univers and Arial documents were set in a serif (Song) face | the PDF serif flag was set for all these fonts, and "Roman"/"Book" in a sans font name matched the serif hint | `keep.font_family`: sans name hints first, serif hints second, flag last | 12 font names |
| Justified paragraphs were cut at every full stop that ended a line | grouping treated "line ends with a full stop, next starts with a capital" as a paragraph end | a full-width line followed by an un-indented line in the same block continues the paragraph | synthetic justified column; indented new paragraph still splits |
| Table cells such as `13.0B` came back as `130亿` | only cells of at most 4 characters with one letter were kept | figures with a unit suffix of up to two letters are kept (ordinals excluded) | 11 kept cells, 7 translated strings |
| Number check failed on correct translations (`540B` before a Chinese character, `2, 000`, `Coyle1,2,3`, `1,840多万`) | `\b` does not exist between a Latin letter and a CJK character; TeX thin space; reference marks; "多" between figure and scale | ASCII-only lookahead; normalisations | 6 accepted, 3 still rejected |

**Real translation errors the number check caught** (kept as `fail`): DeepL rendered "8B, 62B, and 540B parameters" as "8 亿、62 亿和 540 亿"; a figure legend "LLaMA 65B" came back with "简体中文（大陆）" appended.

**Seen and not fixed** (each is a design decision, listed in `docs/OPTIMIZATION_PLAN_zh-CN.md`): table header cells are merged into one line when the column gaps are narrow; labels drawn along curves (maps) are translated fragment by fragment and overlap; inline styles (link colour, italics, bold run-in headings) are lost; author names are translated; a paragraph that contains an inline link can be split at the link; "CSF Profiles" was translated as a medical term (no glossary or context was given); `plan` took 0.65 s per page (162 pages: 105 s) and `render` about 3 s per page without any progress output.

**Not verified by this run:** macOS; scanned pages and OCR paths on real documents; documents longer than a few pages end to end; other DeepL plans; any language pair other than EN→ZH.

## 0-WIN. Windows: status and handover notes for the Windows collaborator

| Item | State |
|---|---|
| Last Windows CI | `c6c9ed5`, run 42487953018: windows-2025 py3.12 ocr=true, windows-2025 py3.13 ocr=false, windows-11-arm py3.12 ocr=false — all failed in **pytest collection**: `tests/test_process_interrupt.py` used `signal.SIGKILL` in a `parametrize` list; Windows' `signal` has no `SIGKILL`, so the module could not be imported (exit 2). No Windows test ran in that job; this says nothing about the PDF engine on Windows. |
| Fix in v0.3.8 | parametrize by signal **name**, resolve inside the test (the test module is POSIX-only via `pytestmark`). A guard test collects the whole suite with POSIX-only signals removed from `signal` (simulated on Linux) and fails with the old code. Not run on Windows. |
| Earlier Windows results | `07ed2df`: CI 10/10 incl. Windows; user's Windows 11 PC (v0.3.5): R01 (test tool), R02 (install in a deep folder) — see §0-R. `ae9c671`: wrapper self-test failed (fixed in v0.3.7, then passed in `c6c9ed5` CI). |
| Open for the collaborator | full suite on Windows x64/arm64 after the collection fix; native file lock; real cp936/cp1252 systems; editable installs on legacy code pages; Windows ARM64 hardware; `docs/testing/WINDOWS_RETEST_PROMPT.md` (needs the current commit and version before use). |
| To re-enable Windows CI | add the three former matrix entries (listed in the header comment of `.github/workflows/tests.yml`); the Windows-only steps are still in the workflow. |

## 0-C. Public commits after v0.3.7 and their CI

| Commit | Content | CI |
|---|---|---|
| `bea1a3b` | v0.3.7.dev0 candidate (Claude) | not run on its own |
| `3530133` | Codex: preflight redaction also on early return and unreadable `.pth`; `install_check` hides pip arguments and pip output (credentials) and reports the real exit code; logo authorship/licence note (owner-confirmed original, AGPL-3.0-or-later, not affiliated with OpenCode) | run 42487629833 **cancelled** by the next push (concurrency); 3 Windows jobs had failed before cancellation; no conclusion for the rest |
| `c6c9ed5` | README shows the light/dark logo | run 42487953018: Linux 4/4 (244 passed / 4 skipped with OCR; 239 / 9 without), macOS 3/3 (246 / 2 with OCR; 241 / 7 without), Windows 0/3 (collection error) |

The private development tree was at `57f6433` (same tree as `bea1a3b`); both public commits were applied to it unchanged (`git am`), so the development tree now has the identical tree as `c6c9ed5` plus this version's changes.

## 0-L. v0.3.6 (`ae9c671`) CI run 42480633442, review findings, and what v0.3.7 changes

Read from the job logs (signed-in web UI). Test counts are the `Tests` step.

| Job | Python (actual) | Result | Tests step |
|---|---|---|---|
| ubuntu-24.04 py3.12 ocr | 3.12.16 | success | 208 passed, 4 skipped |
| ubuntu-24.04 py3.13 ocr | 3.13.18 | success | 208 passed, 4 skipped |
| ubuntu-24.04-arm py3.12 ocr | 3.12.16 | success | 208 passed, 4 skipped |
| ubuntu-24.04 py3.10 no-OCR | 3.10.22 | success | 204 passed, 8 skipped |
| macos-15 py3.12 ocr | 3.12.10 | success | 210 passed, 2 skipped |
| macos-15 py3.11 no-OCR | 3.11.9 | **failure** | 1 failed, 205 passed, 6 skipped |
| macos-15-intel py3.11 ocr | 3.11.9 | **failure** | 1 failed, 210 passed, 1 skipped |
| windows-2025 py3.12 ocr, windows-2025 py3.13, windows-11-arm py3.12 | 3.12.10 / 3.13.17 | **failure** | wrapper self-test failed (step 16), so `Tests` was skipped; preflight and the R01 step passed |

Skips seen: Windows lock (POSIX jobs), 5 OCR tests (no-OCR jobs), legacy-locale tests (no non-UTF-8 locale on Linux runners), and the real offline-install test (no setuptools in a fresh venv on Linux/macOS 3.12).

| Finding | Root cause (evidence) | v0.3.7 | Status |
|---|---|---|---|
| macOS 3.11 jobs: `test_real_install_into_a_fresh_venv` failed with `error: invalid command 'bdist_wheel'` | python.org CPython 3.11.9 bundles setuptools 65.5.0 (`ensurepip`, checked in the v3.11.9 sources); its venvs have no `wheel` package, and `bdist_wheel` is built into setuptools only from 70.1. With `--no-build-isolation` pip must use that setuptools. Reproduced on Linux: venv + setuptools 65.5.0 (PyPI wheel, SHA-256 checked) → same error. A test-environment problem, not a PATT-PDF or regular-install problem (regular installs use build isolation). | `install_check.py` checks the target's build backend before running pip with `--no-build-isolation` (exit 3 with a clear message; nothing created). The real install test now gets setuptools ≥ 70.1 from a local wheelhouse (`PATT_TEST_WHEELHOUSE`, or the interpreter's ensurepip bundle) and skips only if none exists; CI now downloads `setuptools>=70.1` (binary only) into a wheelhouse, so the test runs on every job. Fake-pip tests cover 65.5 with/without `wheel`, 70.1, 59.6, none. | Fixed (Linux); CI pending |
| Windows jobs: wrapper self-test `several arguments, with spaces and Chinese` failed (`multi 1`) | Not the wrapper: the **child Python** printed `['…', '报告 2026 – résumé.pdf', …]` into a redirected log on a cp1252 runner and raised UnicodeEncodeError (exit 1), so the expected text was missing. Reproduced with PowerShell 7.6.9 on Linux and `PYTHONIOENCODING=cp1252:surrogateescape`. | The test child prints `ascii()` escapes; the check decodes them and also requires exit 0. Passes under default, cp1252 and cp936 output encodings; a mutated wrapper that joins arguments still fails 6 checks. | Fixed (PowerShell on Linux); Windows CI pending |
| P0 (review): `preflight.py` printed `.pth` bytes as hex and absolute interpreter/site-packages paths; the macOS prompt asked for `xxd` output and "copy verbatim" | Hex of a path is the path. | Default output describes `.pth` lines by structure (bytes, UTF-8 validity, CJK chars, spaces, short salted hash) and replaces interpreter/site-packages/error paths; `--private-details` (opt-in, with a warning) shows raw data for local use. Tests check that plain, UTF-8/UTF-16 hex, escapes, URL-quoted and file-URL forms of a secret path and user name do not appear, and that ordinary URLs and error messages survive. `test_osenv` no longer prints the absolute `site.py` path. Prompts no longer ask for hex or raw paths. Redaction is best effort. | Fixed |
| P1 (review): `install_check.py --pip-args` split on whitespace | Paths with spaces became several arguments. | New repeatable `--pip-arg=ARG` (one argv element each, no shell). Old `--pip-args` accepted only for plain flags; refused (exit 2, nothing created) when it contains quotes or path-like values. Fake-pip tests check the exact argv, Chinese/space wheelhouse paths and exit-code passthrough. | Fixed |

## 0-W. Readiness criteria for macOS/Linux (formerly: gate for the Windows stage)

Windows is now handled by the collaborator in parallel (§0-WIN); these criteria describe when the macOS/Linux scope is done.

| Criterion | State (2026-11-08) |
|---|---|
| CI of the candidate green on all Linux/macOS jobs (7), every skip explained | **Not yet**: v0.3.8 has not run in CI (`c6c9ed5`: 7/7 Linux/macOS passed) |
| macOS 3.11 and 3.12 fresh install from the candidate, with and without OCR, Chinese/space paths, preflight, offline workflow, interrupt/resume, Preview replacement | **Not yet** (prompt ready: `docs/testing/MACOS_RETEST_PROMPT.md`) |
| Linux fresh install and offline workflow on a real machine (not only containers/CI) | **Partly**: container + CI only (prompt: `docs/testing/LINUX_RETEST_PROMPT.md`) |
| OCR present/absent and font missing give clear statuses, never a silent `pass` | Covered by tests on Linux/CI; to be confirmed on the Mac |
| Interrupted runs leave consistent state and resume | Real SIGINT/SIGKILL test on Linux (§4); Mac pending |
| Privacy: no local paths in reports, diagnostics or retest feedback | Tests on Linux; best effort |
| At least a few licence-clear real PDFs with reviewed comparisons | **Not yet** (rules and validator only) |
| Known gaps listed: Mac Intel (CI only), Linux x64 (CI only), legacy locales on macOS (user machine only) | Listed here |
| One-line installer (`install.sh`) completes a **full** install (fonts, Tesseract + eng, OpenCV) on macOS and Debian/Ubuntu | **Partly**: see §0-I |

Meeting these criteria does not mean "production ready".

## 0-I. One-line installer (`install.sh`, added 2026-11-09)

**Decision (user, 2026-11-09):** one install, the complete one — no variant without OCR or fonts; macOS and Linux via one terminal command; no Homebrew tap, PyPI, apt or other package repository (nothing extra to maintain, sign or get accepted). The script lives in the repository and is fetched from the public `main` branch:

`curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash`

What it does, in order (each step is printed first): system packages (macOS: Homebrew casks `font-noto-sans-cjk`, `font-noto-serif-cjk`, formula `tesseract`, and `python@3.12` only when no Python ≥ 3.10 is found; Linux: `apt-get`/`dnf`/`pacman`/`zypper` via `sudo`); a private venv in `~/.local/share/patt-pdf/venv` with the full package; a link `~/.local/bin/patt-pdf` and an offer to add that folder to `PATH`; `patt-pdf fonts`; `patt-pdf doctor` (the script's exit code is doctor's: 0 = complete, 2 = installed but incomplete). Options: `--ref`, `--source`, `--prefix`, `--bin-dir`, `--python`, `--pip-arg=`, `--no-system`, `--no-modify-path`, `--yes`, `--uninstall`.

**Informed consent (user requirement):** on a Mac without Homebrew the script explains what Homebrew is for and asks before running the official Homebrew installer; `--yes` is the only way to skip the question. Both READMEs carry a "macOS: Homebrew" badge next to the status badges and describe this in the install section. Questions and the interactive Homebrew installer read from `/dev/tty`. Package commands use separate input so they cannot consume the piped script. Bash reads the entire `main()` definition before starting the install.

**Safety:** `--source` builds from a clean copy of the package files (the checkout is never written to; stale `build/` cannot interfere — cf. R02). The installer refuses to replace a virtual environment or command it does not own, and restores its previous environment if package installation fails. `--uninstall` removes its own environment and matching command link. System packages, per-user font copies and shell start-up lines stay.

| Check | State |
|---|---|
| shellcheck 0.10.0 clean (`-s bash`); `bash -n` | Yes (Linux container) |
| Real run, Linux aarch64 container, CPython 3.11.18 and 3.12.16, offline wheelhouse, `--no-system`: venv, link, fonts 4/4, Tesseract + eng, OpenCV → exit 0; re-run replaces the venv; `--yes` adds the PATH line once (idempotent); `--uninstall` removes venv + link only; foreign prefix left alone; piped through stdin (`cat install.sh \| bash -s --`) | Yes |
| No `sudo`/no package manager → warning, Python part continues, doctor reports Tesseract missing → exit 2 | Yes |
| `tests/test_install_script.py` (static rules, help/argument errors create nothing, uninstall safety, real offline venv install from a staged copy) | Yes, including preservation of an existing command and rollback after a failed upgrade |
| CI step "One-line installer" on every Linux/macOS job: `install.sh --source . --no-system` with the job's Python, expects exit 0 with OCR and 2 without, then `--uninstall` | Added; **not yet run** |
| Apple Silicon Mac, system Bash 3.2 and Python 3.12.16: piped local install with `--no-system`, offline wheels, local Noto fonts and existing Tesseract | Doctor returned 0. The missing-dependencies case returned 2. Failed upgrade restored the previous CLI, and uninstall removed it. |
| Fresh Homebrew setup, macOS Intel | **Not yet** |
| Fedora (`dnf`), Arch (`pacman`), openSUSE (`zypper`) package names | From the distributions' package lists; **not run** |

## 0-R. v0.3.5 (`07ed2df`) on CI and real machines, and what v0.3.6 changes

**CI run 42459411475** (head `07ed2df`, all 10 jobs success; read from the job logs). A green job is not "nothing skipped":

| Job | Main suite | UTF-8-off encoding step |
|---|---|---|
| ubuntu-24.04 py3.12 / py3.13 ocr, ubuntu-24.04-arm py3.12 ocr | 196 passed, 2 skipped (no legacy locale on the runner; Windows lock) | 11 passed, 1 skipped |
| ubuntu-24.04 py3.10 no-OCR | 191 passed, 7 skipped (+5 OCR) | 11 passed, 1 skipped |
| macos-15 py3.12 ocr, macos-15-intel py3.11 ocr | 197 passed, 1 skipped (Windows lock) | 12 passed |
| macos-15 py3.11 no-OCR | 192 passed, 6 skipped | 12 passed |
| windows-2025 py3.12 ocr | 193 passed, 5 skipped (POSIX-only tests) | 11 passed, 1 skipped |
| windows-2025 py3.13 / windows-11-arm py3.12 no-OCR | 188 passed, 10 skipped | 11 passed, 1 skipped |

CI limits: no runner has a non-UTF-8 POSIX locale (the legacy-locale and `.pth` simulations skip on Linux and do not run on Windows); the Windows runners' temp folders are ASCII; the macOS runners are not the user's Mac.

**User's Mac** (macOS 27.2 arm64, Python 3.11.16 and 3.12.16, Tesseract 5.5.4): with OCR 197 passed / 1 skipped each; forced no-OCR 192 passed / 6 skipped each; M4–M7, M7b passed; M8 images checked in an image viewer, Preview step partly SKIP. **User's Windows PC** (Windows 11 x64, Python 3.12.10, ACP 65001, Tesseract 5.5.3): with OCR 192 passed / 1 failed / 5 skipped, without 187 / 1 / 10; E2–E9 passed (E7: a 400-character path fails with a clear LongPathsEnabled message and works as `\\?\` extended path; ordinary long paths are NOT supported). Reports are private and not in the repository.

| Finding | What was established | v0.3.6 | Status |
|---|---|---|---|
| **R01** `test_pipeline_with_windows_like_piped_console` failed on the user's PC | Reproduced on Linux: with a cp1252:surrogateescape pipe, **the fixture generator** (`tests/fixtures/make_fixtures.py`) crashed printing its output folder, which contains Chinese on the user's PC (`…\\PATT 复测 …`); no CLI call was made. The CLI itself passed the same pipes (E1b). CI was green because the runner's temp folder is ASCII. A test-tool defect, not a product defect. | Generator escapes unencodable characters; the probe exits 3 with "fixture generator (before any CLI call)" if the generator fails and prints STAGE lines; the end-to-end test now uses a non-ASCII temp folder and asserts the CLI stage was reached; separate generator test for cp1252/cp936 pipes; a test that a generator failure is reported as such. Before the fix 3 tests fail. CI step runs these in `$RUNNER_TEMP/临时 目录`. | Fixed (Linux simulation); Windows retest pending |
| **M3** Mac, Python 3.11, editable install from a non-ASCII folder, en_US.ISO8859-1 / zh_CN.GBK: not importable / interpreter does not start; `python -m patt_pdf.cli doctor` cannot start there | Expected for CPython 3.11's `site.py` (`.pth` read with the locale encoding; `PYTHONUTF8=1` does not change that), already documented; regular installs work; 3.12.16 works. A diagnosis gap: `doctor` lives in the package it should diagnose. Reproduced with real 3.11.18 on Linux (GBK and CP1252: interpreter fails in `site.py`). | New `tools/preflight.py`: standard library only, started with `python -S`, so it runs where `doctor` cannot. Reports separately: interpreter runs with `-S`, starts normally, imports `patt_pdf`, each non-ASCII `.pth` line with predicted result; then recovery steps (regular install in an ASCII folder; UTF-8 locale for the shell; never "PYTHONUTF8 always fixes it"). Changes nothing. Tests compare its verdict with the interpreter's real behaviour in every available locale × UTF-8 Mode (3.10/3.11/3.12 locally); mutations (version-based strategy, ignoring the fs encoding) fail them. | Mitigated: unsupported combination stays unsupported, now diagnosable; Mac retest pending |
| **R02** Windows regular install from a deep folder failed (pip temp path, then stale `build/`) | Not a source difference (the final install was byte-identical). Long temp/build paths with LongPathsEnabled=0 and leftover build state are the likely factors; a single root cause is not proven. | New `tools/install_check.py`: read-only diagnosis (path lengths, LongPathsEnabled, leftovers), clean copy of only the package files into a NEW short folder, TEMP/TMP for pip only, real pip exit code; refuses existing folders, deletes nothing. Tests: dry run creates nothing, stale `build/`/egg-info/bytecode are never copied, existing folders untouched, real offline install (3.11.18). | Mitigated; Windows retest pending |
| **Retest wrapper**: PowerShell `Run` split a single trailing argument into characters | Confirmed with PowerShell 7.6.9: `$cmd, $rest = $args` makes `$rest` a String when one argument follows. | `tools/run_logged.ps1` (array arguments, `start-failed` for unknown commands, cmdlets, real exit code, log written first); `tools/test_run_logged.ps1` self-test with 11 checks incl. that the old wrapper shows the bug. Passed with PowerShell 7.6.9 on Linux; CI step on Windows runners (not yet run). | Fixed; Windows run pending |

## 0-CI. First GitHub Actions run (v0.3.4, `ca38a93`, run 42396678823, 2026-11-07)

Real hosted runners (not simulations). Linux: 3/3 jobs passed. macOS: 4/4 jobs passed. Windows: **3/3 jobs failed**, each with the same 5 tests; all other tests passed or skipped as designed. Logs were read through the signed-in GitHub web UI; they are not copied into the repository.

| Job | Runner image, Python | Result |
|---|---|---|
| windows-2025 py3.12 ocr=true | Windows Server 2025 x64, CPython 3.12.10, Tesseract (choco) | 180 passed, 5 failed, 5 skipped |
| windows-2025 py3.13 ocr=false | Windows Server 2025 x64, CPython 3.13.17 | 175 passed, 5 failed, 10 skipped |
| windows-11-arm py3.12 ocr=false | Windows 11 ARM64, CPython 3.12.10, no `[ocr]` | 175 passed, 5 failed, 10 skipped |

`doctor` on all three: `locale_encoding cp1252`, `filesystem_encoding utf-8`, `stdout_encoding cp1252`, `utf8_mode False`, `pth_strategy utf8-first` (frozen `site`). The "UTF-8 mode off" step was skipped because the previous step failed.

| Failing tests | Root cause (from the logs, then reproduced) | Fix |
|---|---|---|
| `test_pipeline_with_platform_default_encoding`, `test_stdlib_encoding_warning_does_not_abort_probe`, `test_helper_covers_the_py311_api_even_on_older_python`, `test_real_third_party_encoding_warning_is_listed_not_failed` | **A real product defect in the CLI's console output, not a test artefact.** All four run the same encoding probe; it passed `table.pdf` and `toc.pdf`, then `plan` of `报告 2026 – résumé.pdf` exited 1 with `UnicodeEncodeError: 'charmap' codec can't encode characters in position 33-34`, i.e. while *printing* the result line (`planned … <file name>`); planning itself, file I/O and JSON were fine. Mechanism (CPython `initconfig.c`): on Windows the default stdout/stderr error handler is `surrogateescape`, not `strict`. `cli._safe_console()` only replaced `strict` with `backslashreplace`, so on a piped Windows console in a legacy code page (cp1252 here; cp936 etc. alike) any CJK/en-dash file name aborted the command. The existing regression test used `PYTHONIOENCODING=cp1252`, which means `cp1252:strict`, so it passed on Windows CI and never exercised the real default. The same would affect users who redirect output (`> log.txt`, pipes, schedulers) on a non-UTF-8 Windows system. | `_safe_console()` now also replaces `surrogateescape` (and leaves UTF streams alone). New tests: `test_pipeline_with_windows_like_piped_console` (probe with `cp1252:surrogateescape`), `test_legacy_console_encoding_does_not_abort[cp1252 / cp1252:surrogateescape / cp936:surrogateescape]`, `test_safe_console_replaces_strict_and_surrogateescape_but_not_utf8`. Before the fix: 3 of them fail with the exact CI error; after: pass. |
| `test_macos_and_linux_orders_user_before_system` | **Path rules of the host leaked into a simulated OS.** `font_search_dirs(…, "macos")` joined with the host's `os.path` and wrapped in the host's `Path`: on Windows `'/Users/a\\Library\\Fonts'` → `\\Users\\a\\Library\\Fonts`, so the expected POSIX path was "not in list". Real users are not affected (each OS only computes its own list), but the simulation was wrong. The Windows-order test had the mirror-image problem on POSIX hosts (it compared using the host `Path`). | Simulated lists use the target OS's path module (`ntpath`/`posixpath`) and are returned as pure paths of that OS when it differs from the host; Windows de-duplication is case-insensitive on any host. New test `test_simulated_os_paths_do_not_depend_on_the_host[posix/nt]` computes all lists under both host path modules. Tesseract candidates keep the host `os.path` on purpose (they are checked on this file system). |

The CI workflow now runs the "UTF-8 mode off" step even after a failed suite, and a test asserts that all six OS/CPU targets stay in the matrix. Nothing was removed or made optional.

**Still to confirm on real Windows:** the fixed version (next CI run), a real cp936/cp1252 *interactive* console (`_WindowsConsoleIO` is always UTF-8, so the defect only applies to redirected output), and the user's own Windows machine.

## 0. Findings of the independent macOS check of `1897418` (v0.3.3.dev0), and what v0.3.4 changes

macOS arm64, Python 3.12.14, PyMuPDF 1.28.2, CJK fonts, no Tesseract: **177 passed, 1 failed, 6 skipped**. A second check on Python 3.11.16 failed the same test. The encoding-warning fix and the `/custom/private/report.pdf` redaction passed. (Reviewer logs are private and not part of the repository.)

| Finding | Root cause (verified) | v0.3.4 |
|---|---|---|
| `.pth` test on 3.12.14: `zh_CN.GBK` gave `found`, the test predicted `error` | The test inferred the `.pth` decoding from the version number (3.13+ = UTF-8 first). CPython **backported** UTF-8-first `.pth` reading to **3.12.4** (`Misc/NEWS.d/3.12.4.rst`: "site module now parses .pth file with UTF-8 first"). Checked in the tagged sources: v3.12.0–3.12.3 locale only; v3.12.4/.8/.10/.12/.14 and v3.13.0 UTF-8 first; v3.11.9–3.11.16 and v3.10.12 locale only. | The test asks the running interpreter which strategy its `site.addpackage` uses and predicts from the encodings the child process reports. |
| Same test on 3.11.16: `PYTHONUTF8=1` still gave `UnicodeDecodeError`, the test expected `found` | Old `site.py` uses `TextIOWrapper(..., encoding="locale")`. On 3.11+ the "locale" encoding (`_Py_GetLocaleEncoding`) **ignores UTF-8 Mode**; on 3.10 it returned UTF-8 in UTF-8 Mode. So `PYTHONUTF8=1` changes the file system encoding but not `.pth` decoding on 3.11. | Prediction uses the reported "locale" text encoding, not `utf8_mode`. Warning text no longer recommends `PYTHONUTF8=1` for this case. |
| (found in this round, on real 3.11.18/3.12.16) the strategy could not be detected: `inspect.getsource(site.addpackage)` raises `OSError` | In 3.11+ release builds `site` is a **frozen** module (`co_filename` is `<frozen site>`). The v0.3.3 detection and the first v0.3.4 draft read the source and would have crashed or returned `unknown`. Python.org/Homebrew macOS builds are expected to behave the same (not checked). | Detection reads the string constants of the *loaded* code object (`'utf-8-sig'` → UTF-8 first, `'locale'` → locale). Works frozen or not; cross-checked against the `site.py` file when readable. An `unknown` strategy now fails the test instead of passing silently. |
| (found in this round) Linux legacy locale without UTF-8 Mode: an editable install fails even with 3.12.16 (`ModuleNotFoundError`) | The `.pth` line is decoded correctly as UTF-8, but the folder name is then re-encoded with the **file system encoding** (`gbk`/`cp1252`) and no longer matches the name on disk. Not applicable to macOS/Windows (file system encoding always UTF-8 there). | Prediction includes the file system encoding; `doctor` warns about it (and here `PYTHONUTF8=1` does help). |
| (found in this round) `doctor` did not print `pth_strategy` although README said so | Missing keys in the printed list. | `doctor` prints `pth_strategy`, `pth_locale_encoding`, `site_frozen`; the test checks them. `opencv` is reported via a real import. |
| (found in this round) the legacy-locale tests silently skipped as "no non-UTF-8 locale installed" when run from an editable install in a non-ASCII folder; and failed in a clean room whose venv path is non-ASCII (numpy could not load its own path under CP1252) | The locale probe child ran `site.py`, which aborted on the `.pth`; that was mistaken for a missing locale. The second case is the documented Linux legacy-locale file-name limit. | Locale probing uses `python -S`. The pipeline test excuses only these two documented limits (checked in a child, printed), and fails on anything else. Neither can apply on macOS/Windows (UTF-8 file system encoding). |
| Retest prompts: `${PIPESTATUS[0]}` (bash-only, user shell is zsh); `py -3.12` (no py launcher on the user's Windows) | Prompt errors. | macOS: run in bash, `run` helper writes the log first and records the real exit code, no `tee`/`tail` after a tested command. Windows: detects `py`/`python`/`python3`, stops and asks when no suitable Python exists, `Run` helper. |
| Windows arm64 CI job would install `[ocr]` | opencv-python-headless 5.0.0.93 has **no `win_arm64` wheel** on PyPI (checked 2026-11-07; PyMuPDF, numpy, Pillow, PyYAML do). | `windows-11-arm` job runs without `[ocr]` and verifies OCR is absent. A missing `cv2` is now `page_not_processed` with an install hint, not a planning error. |
| Single-segment root paths such as `/privatefile` | Cannot be told apart from command options, URL paths or fractions in free text. | Redacted when quoted (`'/privatefile'`) or when it looks like a file (`/report.pdf`); unquoted `/privatefile`, `/help`, `1.2/3.4` stay. Redaction is **best-effort**: check reports before sharing. |

**Product support boundary for editable installs from a non-ASCII folder** (regular installs are not affected): works where `site.py` reads `.pth` as UTF-8 first (CPython 3.12.4+, 3.13+) and the file system encoding is UTF-8 (always on macOS/Windows; on Linux only in a UTF-8 locale or UTF-8 Mode). With an older `site.py` it works only when the locale encoding is UTF-8. **Measured on Linux only**; macOS and Windows are predictions from the sources.

## 0a. Findings of the independent macOS check of `30d7366` (v0.3.2.dev0)

macOS arm64, Python 3.12.14, PyMuPDF 1.28.2, CJK fonts present, no Tesseract: **153 passed, 2 failed, 6 skipped**. The 6 skips were 5 OCR tests and the Windows-only lock test. Codex's own review also found a redaction gap.

| Finding | Root cause | Evidence | Status in v0.3.3 | Regression tests |
|---|---|---|---|---|
| `test_stdlib_encoding_warning_does_not_abort_probe` failed: probe printed OK but no `locale.py` | **Test helper defect (certain).** The helper made only `locale.getpreferredencoding()` warn. On Python ≥ 3.11 the probe calls `locale.getencoding()` instead, which never warns, so no stdlib warning appeared and the assertion had nothing to find. Python 3.10 has no `getencoding()`, so the Linux runs passed | Reproduced here by adding the 3.11+ API to Python 3.10: the old helper produced no stdlib warning; the new one produced it and the probe still passed | **Fixed.** The helper now wraps whichever locale query exists. A second test calls `locale.getpreferredencoding()` from third-party code, which on real 3.11+ CPython raises a *real* EncodingWarning; it must be listed, and the probe must still pass. The detection of project-code warnings is unchanged | `test_helper_covers_the_py311_api_even_on_older_python` (fails with the old helper), `test_real_third_party_encoding_warning_is_listed_not_failed`, `test_probe_detects_implicit_encoding_in_project_code` |
| `test_pth_with_non_ascii_path_is_decoded_with_locale_encoding` failed: `LC_ALL=zh_CN.GBK PYTHONUTF8=0` found the package | **The test's assumption was wrong (certain); the macOS mechanism is inferred.** The old test assumed every legacy locale breaks a UTF-8 `.pth`. In CPython 3.10–3.12, `site.addpackage` decodes `.pth` files with the *locale* encoding, and 3.13+ decodes as UTF-8 first (checked in the CPython sources). The outcome depends on the encoding Python actually uses, which a locale name alone does not determine. Likely explanation for macOS (inferred, not measured, because the reviewer's log does not record it): the `zh_CN.GBK` locale did not set a GBK codeset, so locale text stayed UTF-8 | Linux 3.10: real GBK/CP1252 → `UnicodeDecodeError` (no import). A macOS-like emulation (locale text UTF-8, file system encoding legacy) → `missing`. Both match the new rule | **Test corrected.** The child reports its locale and file system encodings, and the expected result is computed from CPython's version-specific rule. `PYTHONUTF8=1` must always find the package. The child's encodings are printed so that a macOS rerun shows the real values. `doctor` now warns only on Python 3.10–3.12 | `test_pth_decoding_matches_cpython_rules`, `test_expected_pth_rule_is_version_aware`, `test_editable_install_warning_…` |
| Same cause as the v0.3.1 macOS editable-import failure? | **Probably the same mechanism, not proven.** The v0.3.1 failure was Python 3.11 + `en_US.ISO8859-1` + an editable `.pth` pointing to a Chinese folder. Under the rule above, an ISO8859-1 decode gives a wrong path (`missing`), which matches the observed `ModuleNotFoundError`. The v0.3.2 test failure was a wrong expectation for a *different* locale on 3.12 | Python 3.11/3.12 and the macOS locale data could not be run here (no network) | **Pending macOS confirmation** (MACOS_RETEST_PROMPT M5) | — |
| Redaction: `open failed: /custom/private/report.pdf` printed as-is | **Implementation gap (certain).** POSIX paths were recognised only under a fixed list of top-level folders | Reproduced through the CLI: plan error JSON, the CLI line and the report all contained the path | **Fixed.** Any absolute POSIX path with at least two segments, `~/…` and `file://` URLs are now redacted. URLs, fractions, `and/or`, dates, DOIs and single-segment `/x` are left alone. Exception texts are also redacted in page-level plan notes, OCR details, translate summaries and logs, publish reasons, and the top-level CLI error handler | 13 new parametrised cases; `test_custom_mount_path_never_reaches_cli_json_or_report` (CLI + every state JSON/JSONL + report, Windows escaped/UNC/extended forms included); `test_redaction_keeps_cli_messages_useful` |
| CI used `macos-13`/`macos-14`, an unverified "no OCR" state, and `\|\| true` | Workflow defect | GitHub runner-images README, checked 2026-11-07: macOS 14 retired 2026-11-02 | **Workflow rewritten (not run):** `macos-15` (arm64), `macos-15-intel`, `ubuntu-24.04`/`-arm`, `windows-2025`, `windows-11-arm`. Actions are pinned to commit SHAs. `tools/ci_check_ocr.py` asserts OCR present+`eng` or absent, using the product's own discovery; no-OCR jobs also set `PATT_PDF_TESSERACT` to a missing file. Shells are explicit (bash default, pwsh only where needed). Windows fonts come from a pinned noto-cjk commit and are checked against git blob SHAs | `tests/test_ci_workflow.py` (labels, pinning, permissions, OCR verification, shell syntax) |

## 0b. Findings of the macOS and Windows runs of `6b969b8` (v0.3.1.dev0)

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

### v0.3.8.dev0, this environment (Linux aarch64 container)

249 tests (2 new: collection guard without POSIX-only signals; Linux/macOS matrix check; plus Codex's 6 redaction/credential tests from `3530133`). pyflakes clean. Run in four chunks per interpreter (sandbox time limit), with `PATT_TEST_WHEELHOUSE` pointing at a local setuptools 79.0.1 wheel so the real offline install test runs:

| Interpreter | Result | Skips |
|---|---|---|
| CPython 3.10.12 (Ubuntu), dev tree | 247 passed, 2 skipped | Windows native lock; real-PDF corpus not present |
| CPython 3.11.18, regular install in a Chinese/space folder | 247 passed, 2 skipped | same |
| CPython 3.12.16, regular install in a Chinese/space folder | 247 passed, 2 skipped | same |

`test_interrupted_render_leaves_consistent_state_and_resumes[SIGINT]` and `[SIGKILL]` both ran and passed on each interpreter (not skipped). The collection guard fails with the old `parametrize([signal.SIGINT, signal.SIGKILL])` and passes with the fix. Not run on Windows (out of scope) or macOS (no Mac here).

### v0.3.7.dev0, this environment (Linux aarch64 container)

242 tests (30 new). pyflakes clean. Run in four chunks per interpreter (sandbox time limit); totals:

| Interpreter | Result | Skips |
|---|---|---|
| CPython 3.10.12 (Ubuntu), dev tree | 240 passed, 2 skipped | Windows native lock; real-PDF corpus not present |
| CPython 3.11.18, regular install in a Chinese/space folder | 240 passed, 2 skipped | same |
| CPython 3.12.16, regular install in a Chinese/space folder | 240 passed, 2 skipped | same |
| PowerShell 7.6.9 (Linux), `tools/test_run_logged.ps1`, output encodings default / cp1252 / cp936 | 11/11 each | – |

The offline install test ran on all three (local setuptools 79.0.1 wheel from the 3.11.18 ensurepip bundle via `PATT_TEST_WHEELHOUSE`). New real-process tests: SIGINT and SIGKILL in the middle of a 5-file render in a Chinese/space path — exit non-zero, sources byte-identical, every visible output/JSON complete, 0 temp leftovers, re-run finishes all 5 (2 done before, 5 after). Long-path workflow (~180-byte paths, Chinese and spaces): plan/budget refusal/translate/cache re-run/render/report/compare/publish twice (no overwrite)/stale plan, sources unchanged, no temp files.

Mutations caught: wrapper joining arguments (6 checks fail); install_check without the build-backend check (1 test), with whitespace splitting (2 tests).

### v0.3.6.dev0, this environment (Linux aarch64 container)

212 tests (15 new). pyflakes clean.

| Run | Result | Skips |
|---|---|---|
| CPython 3.10.12, dev tree | 210 passed, 2 skipped | Windows lock; offline install test (setuptools 59 < 61 in the venv) |
| CPython 3.11.18, regular install, non-ASCII folder | 211 passed, 1 skipped | Windows lock |
| CPython 3.12.16, regular install, non-ASCII folder | 210 passed, 2 skipped | Windows lock; offline install test (fresh venv has no setuptools) |
| `pwsh -File tools/test_run_logged.ps1` (PowerShell 7.6.9, Linux arm64) | 11/11 checks | – |

### v0.3.5.dev0, this environment (Linux aarch64 container)

196 tests (6 new: 5 regression tests for the Windows CI findings + 1 workflow guard; plus 1 workflow test). pyflakes clean.

| Run | Result | Skips |
|---|---|---|
| CPython 3.10.12, dev tree | 195 passed, 1 skipped | Windows native lock |
| CPython 3.11.18, regular install, non-ASCII folder | 195 passed, 1 skipped | same |
| CPython 3.12.16, regular install, non-ASCII folder | 195 passed, 1 skipped | same |

**Windows simulation** (not Windows): Python with a UTF-8 file system encoding, the locale encoding switched to CP1252 after start-up, and `PYTHONIOENCODING=cp1252:surrogateescape` – the same three values `doctor` reported on the CI runners. The encoding probe failed exactly like CI before the fix (`FAIL: plan 报告…`, `UnicodeEncodeError: 'charmap' … position 33-34`) and passes after it (3.12.16). The font-path test was checked with both `ntpath` and `posixpath` as the host path module.

### v0.3.4.dev0, this environment (Linux aarch64 container)

190 tests; pyflakes clean. Interpreters: Ubuntu CPython 3.10.12; python-build-standalone 20261026 CPython 3.11.18 and 3.12.16 (archives checked against the release SHA256SUMS; `site` frozen in both). numpy 2.2.6 and Pillow 12.3.0 wheels for 3.11/3.12 checked against PyPI SHA-256; PyMuPDF 1.28.2 and opencv-python-headless 5.0.0.93 are abi3 builds shared with 3.10; Tesseract 4.1.1 (eng). The source was copied to a folder named `源码 目录` (non-ASCII, space).

| Run | Result | Skips |
|---|---|---|
| 3.10.12, dev tree, C.UTF-8, Tesseract, GBK/CP1252 locales generated | 189 passed, 1 skipped | Windows native lock |
| 3.11.18, regular install (`pip install .`) | 189 passed, 1 skipped | Windows native lock |
| 3.12.16, regular install | 189 passed, 1 skipped | Windows native lock |
| 3.11.18, editable install from the non-ASCII folder | 188 passed, 2 skipped | Windows lock; legacy-locale pipeline test (only documented limits applied, each printed: non-UTF-8 file system encoding with non-ASCII paths, editable install not importable) |
| clean room: bundle → clone into `复测 clean/`, venv there, regular install, 3.12.16 | 189 passed, 1 skipped | Windows lock (the CP1252 probe was excused and printed: venv path not representable in cp1252) |
| 3.12.16, editable install from the non-ASCII folder | 189 passed, 1 skipped | Windows lock (the pipeline test passes: the probe child uses `PYTHONPATH`) |
| 3.12.16, regular, `LC_ALL=zh_CN.GBK PYTHONUTF8=0` | 186 passed, 4 skipped | Windows lock; `.pth` test (parent already legacy); 2 × non-ASCII file names (POSIX legacy fs encoding) |
| 3.11.18, regular, `LC_ALL=en_US.CP1252 PYTHONUTF8=0` | 186 passed, 4 skipped | same |
| 3.11.18, regular, Tesseract hidden | 184 passed, 6 skipped | 5 × OCR, Windows lock |
| 3.10.12, OpenCV hidden and no Tesseract | 179 passed, 6 skipped (earlier in this round) | 5 × OCR, Windows lock |

**`.pth` observations** (`test_pth_decoding_matches_the_interpreters_own_rule`, real interpreters; each row is predicted = observed):

| Python | strategy | locale | UTF-8 Mode | locale text enc. | fs enc. | result |
|---|---|---|---|---|---|---|
| 3.10.12 | locale | GBK / CP1252 | 0 | GBK / CP1252 | gbk / cp1252 | error |
| 3.10.12 | locale | GBK / CP1252 | 1 | UTF-8 | utf-8 | found |
| 3.11.18 | locale (frozen) | GBK / CP1252 | 0 and 1 | GBK / CP1252 | gbk/cp1252, utf-8 | error (UnicodeDecodeError) |
| 3.12.16 | utf8-first (frozen) | GBK / CP1252 | 0 | GBK / CP1252 | gbk / cp1252 | missing |
| 3.12.16 | utf8-first (frozen) | GBK / CP1252 | 1 | GBK / CP1252 | utf-8 | found |
| all | – | C.UTF-8 | 0 and 1 | UTF-8 | utf-8 | found |

**Editable vs regular install, real interpreters** (`import patt_pdf`; regular install always OK):

| Python | C.UTF-8 | CP1252, Mode 0 / 1 | GBK, Mode 0 / 1 |
|---|---|---|---|
| 3.11.18 editable | OK | UnicodeDecodeError / UnicodeDecodeError | UnicodeDecodeError / UnicodeDecodeError |
| 3.12.16 editable | OK | ModuleNotFoundError / OK | ModuleNotFoundError / OK |

**The tests catch the old mistakes** (each mutation run on real 3.11.18 and 3.12.16): the v0.3.3 `.pth` test fails on both (reproduces the macOS failures); source-based strategy detection → fails (frozen `site`); prediction ignoring the fs encoding → fails; `doctor` without the fs-encoding warning → fails.

**Not covered here:** Python 3.11.16 and 3.12.14 exactly (the reviewer's versions; 3.11.18/3.12.16 have the same `site.py` strategy per the tagged sources), Python 3.13, any macOS or Windows interpreter.

### v0.3.3.dev0, this environment (Linux aarch64 container, Python 3.10.12)

184 tests; pyflakes clean. Python 3.11–3.13 could not be installed (no network in this environment).

| Run | Result | Skips |
|---|---|---|
| PyMuPDF 1.28.2, C.UTF-8, Tesseract, PyYAML, GBK/CP1252 locales generated | 183 passed, 1 skipped | Windows native lock |
| Tesseract hidden, no PyYAML | 173 passed, 7 skipped | 5 × OCR, PyYAML, Windows lock |
| `LC_ALL=zh_CN.GBK PYTHONUTF8=0` | 180 passed, 4 skipped | 2 × non-ASCII file names (POSIX legacy fs encoding), `.pth` test (parent already legacy), Windows lock |
| `LC_ALL=en_US.CP1252 PYTHONUTF8=0` | 180 passed, 4 skipped | same |
| PyMuPDF 1.25.2 | 183 passed, 1 skipped | Windows lock |
| no CJK fonts | 114 passed, 70 skipped | font-dependent tests |

### v0.3.2.dev0 independent check on macOS (Codex, before these fixes)

macOS arm64, Python 3.12.14: 153 passed, 2 failed, 6 skipped (fonts, no Tesseract). Without fonts: 92 passed, 1 failed, 68 skipped.

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

`.github/workflows/tests.yml` defines 10 jobs:

| Runner | CPU |
|---|---|
| `ubuntu-24.04` | x64 |
| `ubuntu-24.04-arm` | arm64 |
| `macos-15` | arm64 |
| `macos-15-intel` | x64 |
| `windows-2025` | x64 |
| `windows-11-arm` | arm64 |

The jobs use Python 3.10–3.13, both with Tesseract and with verified absence, plus a `PYTHONUTF8=0` encoding run in every job. It has **never run**; no result can be claimed from it. To run it, push the candidate to GitHub (Actions runs on push to `main`) or start it manually (`workflow_dispatch`), then keep the run URL and the JUnit artifacts. Hosted minutes are free for public repositories on standard runners. `windows-11-arm` runs without `[ocr]` (no opencv `win_arm64` wheel; PyPI checked 2026-11-07); runner labels and action SHAs were checked against the published sources on 2026-11-07, but none of this is verified until a run exists. The YAML is only checked statically (`tests/test_ci_workflow.py`).

## 5. Not verified

* **macOS:** v0.3.1–v0.3.3 checked by reviewers without Tesseract (§0, §0a, §0b); v0.3.4 not run; `.pth` behaviour of python.org/Homebrew builds is a prediction; OCR, Preview locks, cross-volume and signals untested. Prompt: `docs/testing/MACOS_RETEST_PROMPT.md`.
* **Windows:** v0.3.1 was run by a reviewer (§0b); v0.3.2–v0.3.4 not re-run. Still untested: font directories, the `%APPDATA%` key location, the Tesseract default path, file locking, console code pages, the real ANSI code page (cp936/cp1252; only simulated with POSIX locales), editable installs, arm64. Prompt: `docs/testing/WINDOWS_RETEST_PROMPT.md`.
* **Path redaction** is best-effort (pattern based). Unquoted single-segment root paths (`/privatefile`) and paths inside unusual quoting are kept. Check reports before sharing them.
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

* v0.3.8: no engine or CLI behaviour change. Default CI matrix: Linux and macOS only (Windows by the collaborator).
* v0.3.7: no engine or CLI behaviour change. `tools/install_check.py`: `--pip-arg=ARG` (repeatable) replaces whitespace-split `--pip-args` for anything but plain flags; exit 3 when the target cannot build with `--no-build-isolation`. `tools/preflight.py`: no local paths by default (`--private-details` for local use). New `tools/corpus_check.py`.
* v0.3.6: no engine or CLI behaviour change. New tools: `tools/preflight.py`, `tools/install_check.py`, `tools/run_logged.ps1` (+ self-test). The encoding probe exits 3 when the fixture generator fails.
* v0.3.5: no engine change. CLI output on non-UTF-8 consoles now always escapes unencodable characters (previously only for the `strict` handler). `osenv.font_search_dirs(…, os_name=<other OS>)` returns pure paths of that OS.
* v0.3.4: no engine change (`ENGINE_VERSION` stays `patt-0.3-e3`). `platform_info()`/`doctor` gained `pth_strategy`, `pth_locale_encoding`, `site_frozen`. A missing OpenCV during planning is a skipped page note (`page_not_processed`), not a planning error.
* v0.3.3: no engine change (`ENGINE_VERSION` stays `patt-0.3-e3`); existing state directories stay valid. Error texts in state files now redact *all* absolute paths (`<path>/name`). `pyyaml` was added to the `dev` extra (CI-workflow check only).

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
