# PATT-PDF macOS verification checklist (for Codex)

**Superseded:** use `docs/testing/MACOS_RETEST_PROMPT.md` (v0.3.4). This checklist is kept as the v0.3.2 reference; its version and test counts are out of date.
The candidate has only been tested on Linux aarch64 so far.

**Reporting:** mark every item PASS / FAIL / SKIP with evidence. Do not mark anything as passed that you did not run.

**Defaults:**

* No DeepL calls and no translation API of any kind.
* Do not open, copy or upload the user's private documents (course material, translations, earlier prototypes, keys). Do not touch an existing PATT-PDF development checkout or its `.venv`.
* Work only inside the test directory `$T` created below, and delete only `$T` at the end.

## 0. Source to test (record which one you used)

**A. Release bundle (default while nothing is published).** The user gives you three things:

* a file `patt-pdf-<version>-<short-sha>.bundle`;
* its SHA-256;
* the full commit SHA.

```bash
export T="$HOME/patt-macos-test-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T"
shasum -a 256 /path/to/patt-pdf-*.bundle          # must equal the SHA-256 the user gave you
git bundle list-heads /path/to/patt-pdf-*.bundle  # HEAD and refs/heads/main = the commit the user gave you
git clone /path/to/patt-pdf-*.bundle "$T/PATT-pdf"
git -C "$T/PATT-pdf" rev-parse HEAD                # must equal the commit the user gave you
git -C "$T/PATT-pdf" bundle verify /path/to/patt-pdf-*.bundle   # "The bundle records a complete history."
git -C "$T/PATT-pdf" log --oneline | wc -l         # the release snapshot has exactly 1 commit
```

If any of these checks differs, STOP and report it. Do not test anything else instead.

**B. GitHub (only after the user tells you it was pushed and gives the commit):**
```bash
export T="$HOME/patt-macos-test-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T"
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T/PATT-pdf"
git -C "$T/PATT-pdf" checkout <commit-given-by-user> && git -C "$T/PATT-pdf" rev-parse HEAD
```

If the repository is empty or the commit does not exist, STOP and report it. Never substitute another commit.

## 1. Environment facts (record all)

```bash
sw_vers; uname -m; python3 --version; git --version
which tesseract && tesseract --version 2>&1 | head -2 && tesseract --list-langs 2>&1 | head
ls /Library/Fonts ~/Library/Fonts /opt/homebrew/share/fonts 2>/dev/null | grep -i -E "noto.*cjk|notosanssc|notoserifsc"
```

Supported Python is 3.10 or newer. If `python3` is older, install Python 3.12 (`brew install python@3.12`) only if the user agrees; otherwise report SKIP.

## 2. Install into a fresh venv

```bash
cd "$T/PATT-pdf"
python3 -m venv "$T/venv" && source "$T/venv/bin/activate"
python -m pip install --upgrade pip
pip install ".[ocr,dev]" 2>&1 | tail -3          # regular install; an editable install from a non-ASCII folder needs a UTF-8 locale (README)
patt-pdf --version                       # expect: patt-pdf 0.3.2.dev0
python -c "import pymupdf, numpy, fontTools, cv2; print(pymupdf.VersionBind, numpy.__version__, fontTools.version, cv2.__version__)"
```

**Fonts:**
```bash
export PATT_PDF_FONT_DIR="$T/fonts"; patt-pdf fonts; echo "rc=$?"
```
Expected: four lines "extracted from …" and rc 0. If fonts are missing: rc 1, and the message lists the searched folders.

* **Fix (with consent only):** `brew install --cask font-noto-sans-cjk font-noto-serif-cjk`. Without consent, record FAIL with the message.
* **Fonts in another folder:** `export PATT_PDF_FONT_SOURCE=/path/to/folder`.

**OCR (optional):** `brew install tesseract`, with consent only. Without it, the OCR tests are SKIPPED, which is expected. Record results "with OCR" and "without OCR" separately.

## 3. Offline test suite

```bash
cd "$T/PATT-pdf"
python -m pytest -q -p no:cacheprovider -rs 2>&1 | tee "$T/pytest.txt" | tail -5
```

Report the actual numbers. The suite has 161 tests. On macOS, by design:

* `test_native_windows_lock` always skips (Windows only).
* `test_pipeline_in_legacy_posix_locales` and `test_pth_with_non_ascii_path_is_decoded_with_locale_encoding` skip if no non-UTF-8 locale (for example `en_US.ISO8859-1`) is installed.
* Without Tesseract, 5 more tests skip, with Tesseract/OpenCV/OCR as the reason.

Any other skip reason, or any failure, is a finding. Also run the encoding tests with the default encoding forced off UTF-8 and record the first line:
```bash
python -c "import locale,sys; print(getattr(locale,'getencoding',locale.getpreferredencoding)(), sys.flags.utf8_mode, sys.getfilesystemencoding())"
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 python -m pytest -q -p no:cacheprovider -rA tests/test_encoding.py | tail -8
```

**Any failure is a real finding:** keep `$T/pytest.txt`.

## 4. End-to-end CLI checks (synthetic only)

The expected values were predicted from a run of the same commands on Linux with Tesseract. They are not macOS results.

```bash
python tests/fixtures/make_fixtures.py "$T/in 输入" && mv "$T/in 输入/truth.json" "$T/in 输入/manual_tm.json" "$T/"
IN="$T/in 输入"; S="$T/state"; TM="$T/manual_tm.json"
patt-pdf plan "$IN" --state "$S"; echo "plan rc=$?"                                    # 1: damaged/encrypted are errors (truncated: see table)
patt-pdf translate "$IN" --state "$S" --backend pseudo --max-chars 99999; echo "A1 rc=$?"     # 2: done, but 3 unreadable files skipped
patt-pdf estimate "$IN" --state "$S" --backend manual --manual-tm "$TM" | tail -1             # 1136 chars / 44 segments (981 / 40 without OCR): pseudo NOT reused
patt-pdf render "$IN" --state "$S" --backend pseudo --files toc.pdf; echo "A2 rc=$?"        # 2, FAIL
patt-pdf publish "$IN" --state "$S" --dest "$T/pub" --files toc.pdf; echo "A3 rc=$?"       # 2, skipped; $T/pub has no toc.pdf
patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 99999; echo "B1 rc=$?"  # 2: 3 segments missing from the TM
patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 5; echo "B2 rc=$?"      # 2: "estimate 290 chars exceeds --max-chars 5"
patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM"; echo "C1 rc=$?"     # 1 (error files present)
patt-pdf report "$IN" --state "$S" --out "$T/report.md"
patt-pdf compare "$IN" --state "$S" --out "$T/cmp" --files "t*"
patt-pdf compare "$IN" --state "$S" --out "$T/cmp" --files "decorations.pdf"
```

Expected statuses in `$T/report.md`:

| File | Expected status |
|---|---|
| `toc.pdf`, `financial.pdf`, `table.pdf`, `rotated.pdf`, `报告 2026 – résumé.pdf` | `pass` |
| `decorations.pdf` | `needs review`: page 1 pass, page 2 review (`decoration_not_adjusted`, `link_area_not_mapped`, `markup_annotation_on_translated_text`) |
| `image_text.pdf` | `UNVERIFIED` |
| `scanned.pdf`, `vector_glyphs.pdf`, `decor_scan.pdf` | `needs review` with Tesseract; `FAIL` (`page_not_processed`) without it |
| `two_column_cropbox.pdf` | `FAIL` (TM gap, on purpose) |
| `damaged.pdf`, `encrypted.pdf` | `ERROR`; the message shows `<input>/…`, never your home folder |
| `truncated.pdf` | Depends on the PyMuPDF version: `ERROR` if it cannot be opened, `UNVERIFIED` (`source_repaired`) if MuPDF reconstructs it. **Never** `pass` |

**Underlines and links:**

* Open `$T/cmp/decorations_p1.png`. On the right side, every underline and the strike-through line should end where the Chinese text ends. The e-mail underline should sit under `info@example.org`. The small table and the long grey separator should be unchanged.
* Then check the link targets:
```bash
python -c "import pymupdf,sys; o=pymupdf.open(sys.argv[1]); print([sorted(l['uri'] for l in p.get_links()) for p in o])" "$S/out/decorations.pdf"
```
Expected: `[['https://example.org/field-guide', 'mailto:info@example.org'], ['https://example.org/map']]`.
* Clicking the links in Preview should hit the Chinese text.

**Stale plan:**
```bash
python - "$T" "$IN" <<'EOF'
import pymupdf, os, sys
t, src = sys.argv[1], sys.argv[2]
d = pymupdf.open(); d.new_page().insert_text((72, 72), "Other content"); d.save(t + "/x.pdf")
os.replace(t + "/x.pdf", src + "/toc.pdf")
EOF
patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM" --files toc.pdf; echo "rc=$?"   # 1, "source file content changed"
```

**Visual check:** open `$T/cmp/toc_p1.png` and `$T/cmp/table_p1.png`. The numbers 1, 2, 3, 5, the table figures and the dates must look identical on both sides, and the English labels must be Chinese on the right. Take screenshots into `$T/screens/`.

**Key handling (fake key only):**
```bash
echo "11111111-2222-3333-4444-555555555555:fx" | patt-pdf key save --path "$T/k/deepl.key"; ls -l "$T/k" "$T" | grep -E "deepl.key| k$"
```
Expected: `-rw-------` on the file and `drwx------` on `k`, and the fake key must not appear in the output. Running the same command again → rc 1 (never overwrites).

## 5. If something fails, collect (redacted)

* The command, its exit code, and the last 40 lines of output.
* `$T/pytest.txt`.
* `$T/state/qa/<file>.json` for the file concerned. These are synthetic fixtures only, so they are safe to share.
* Version facts from step 1.

Replace your user name with `<USER>` in any path. Never include `DEEPL_AUTH_KEY`, real key files or any of the user's documents.

## 6. Cleanup (test directory only)

```bash
deactivate 2>/dev/null; echo "about to delete: $T"; ls "$T"
rm -rf "$T"        # only this test directory; do NOT remove Homebrew packages or fonts
```

## 7. Report template

```
macOS <version> (<arch>), Python <x>, Git <x>, Tesseract <x or none>
PyMuPDF <x> numpy <x> fontTools <x> opencv <x>
Source: A bundle (SHA-256 <…>) | B GitHub; commit <full sha>
1 env ............ PASS/FAIL
2 install ........ PASS/FAIL  (fonts: PASS/FAIL, OCR: available/missing)
3 pytest ......... <n passed, n failed, n skipped>
4 e2e statuses ... PASS/FAIL (list deviations)
4 underlines/links PASS/FAIL (screenshot path)
4 stale plan ..... PASS/FAIL
4 visual ......... PASS/FAIL (screenshot paths)
4 key file perms . PASS/FAIL
Findings: <command, expected, actual, log path>
Residual risks: <...>
```
