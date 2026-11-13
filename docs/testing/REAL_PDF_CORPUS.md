# Real-PDF regression corpus

**Status (2026-11-13):** seven public documents are listed in
`tests/corpus/MANIFEST.json`. The PDFs themselves are **not** in the repository. They are
downloaded into a local cache by `tools/corpus_fetch.py`, which checks SHA-256 and size
against the manifest. Without the cache the real-document tests are skipped; the default
test run never uses the network.

```bash
python tools/corpus_fetch.py          # download what is missing (about 10 MB), verify all
python -m pytest -q tests/test_real_corpus.py -rs
python tools/corpus_fetch.py --check  # verify the cache only, no network
```

Cache folder: `$PATT_CORPUS_DIR`, else `$XDG_CACHE_HOME/patt-pdf/corpus`, else
`~/.cache/patt-pdf/corpus`.

## What the tests check, and what they do not

`tests/test_real_corpus.py` plans and renders the selected pages with the **pseudo** backend
(placeholder text, no translation service) and checks structure: no error, every link still
present, table header cut into cells, figures and model names not sent, justified paragraphs
whole, sans documents set in a sans face, curved map labels left in place, unselected pages
untouched. They say nothing about translation quality. Results with a real translation
service are recorded by hand in `docs/STATUS.md`; translations and translation memories are
never added to the repository.

## Admission rules (all required)

1. **Licence permits redistribution and adaptation**, verified on the publisher's own page at
   the time of adding (not a mirror), and recorded as `licence_evidence_url`. Accepted: public
   domain, works of the U.S. government (17 U.S.C. §105), CC0, CC BY 4.0, or an explicit
   written permission that is itself publishable. Not accepted: "free to read", unclear terms,
   course material, anything from a user's own documents.
2. **No personal data** beyond what the publisher made public.
3. **Stable source.** Prefer a versioned address (arXiv `…v6`, a DOI, a numbered report). Where
   the publisher replaces the file in place (tax forms), the entry carries `"stable_url": false`:
   when the file changes, `corpus_fetch.py` rejects it and the tests of that document are
   skipped until a person updates the manifest.
4. **Size:** each file ≤ 4 MB, all files ≤ 16 MB (download time in CI).
5. **Manifest entry** with: `id`, `file`, `url` (https), `sha256`, `bytes`, `title`, `licence`,
   `licence_evidence_url`, `checked_on`, `checked_by`, `category`, `pages` (the pages the tests
   use, in `--pages` syntax). `python tools/corpus_check.py tests/corpus [CACHE]` validates the
   manifest and, with a cache folder, the files in it. A PDF stored next to the manifest is an
   error.

## Documents (2026-11-13)

| id | Document | Licence | Pages | Exercises |
|---|---|---|---|---|
| `cot` | arXiv 2201.11903v6 | CC BY 4.0 | 1, 4 | single column, figure with text boxes, table |
| `llama` | arXiv 2302.13971v1 | CC BY 4.0 | 1, 3 | two columns, three-line table, chart legend, named links |
| `plos` | PLOS ONE e0262897 | CC BY 4.0 | 1, 4 | side column, many links, table |
| `nist` | NIST CSWP 29 | U.S. government work | 9, 11 | lists, underlined links, diagram as image |
| `usgs_quake` | USGS Fact Sheet 2016-3020 | U.S. government work | 1, 3 | map with curved labels, coloured background |
| `usgs_bay` | USGS Fact Sheet 2023-3003 | U.S. government work | 1 | photos with text, columns |
| `w9` | IRS Form W-9 (Rev. March 2024) | U.S. government work | 1 | ruled form, fine print, vertical labels |

Trademarks and logos inside these documents (journal marks, agency seals) are not covered by
the licences above; the documents are only processed locally and are not redistributed by
this project.

## Not covered yet

Scanned pages and the OCR path on real documents, slides, textbooks, formula-heavy pages,
whole long documents, documents in languages other than English.
