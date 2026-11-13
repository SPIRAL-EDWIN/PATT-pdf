# Contributing to PATT-PDF

Thank you for looking. PATT-PDF is a small, experimental project; reports from real documents
are the most useful contribution right now.

## Reporting a problem

Open an issue and include:

- what you ran (the full command) and the output of `patt-pdf --version` and `patt-pdf doctor`
  (the doctor report contains no local paths);
- what you expected and what happened; for layout problems, a screenshot of the page next to
  the original, or the image from `patt-pdf compare`;
- the document, **only if you may share it publicly**. Otherwise describe the page (two
  columns, a table without rules, a map…) or reproduce the problem with a small PDF of your own.

Please do not attach private documents, API keys, or the working folder (`--state`): it
holds source text and translations in plain text.

## Setting up

```bash
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git && cd PATT-pdf
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'
patt-pdf fonts && patt-pdf doctor
python -m pytest -q
```

The test suite is offline: synthetic PDFs, fixed or placeholder translations, no translation
service. Two optional parts:

- **Real documents.** `python tools/corpus_fetch.py` downloads seven public documents (about
  10 MB) into a local cache; `tests/test_real_corpus.py` then runs instead of being skipped.
  The PDFs are never added to the repository; see `docs/testing/REAL_PDF_CORPUS.md`.
- **OCR.** Tests that need Tesseract are skipped when it is missing.

## Making a change

- Reproduce first. A fix comes with a test that fails without it; for layout work, build the
  case as a small synthetic page (see `tests/test_real_pdf_findings.py` for examples).
- Keep `python -m pyflakes src tests tools` and, for `install.sh`, `shellcheck -s bash install.sh`
  clean. `install.sh` must run with bash 3.2 (the system bash on macOS): write `${name}` when
  non-ASCII text follows a variable, and expand arrays as `${arr[@]+"${arr[@]}"}`.
- When rendering or planning changes, raise `ENGINE_VERSION` in `src/patt_pdf/__init__.py` so
  that stored plans are re-made.
- Say what you ran and on which system. `docs/STATUS.md` records what is verified and what is
  not; statements there need evidence, and "not verified" is an acceptable entry.
- Platform scope: macOS and Linux are maintained in this repository. Windows-specific changes
  are welcome, but they are reviewed and tested by a separate collaborator.

## Licence of contributions

PATT-PDF is licensed under AGPL-3.0-or-later (it builds on PyMuPDF, which is AGPL or
commercial). By contributing you agree that your contribution is distributed under the same
licence. Do not copy code from projects with incompatible licences, and do not add documents,
fonts or translations whose licence does not allow redistribution.
