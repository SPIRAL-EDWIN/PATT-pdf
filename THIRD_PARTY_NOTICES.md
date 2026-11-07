# Third-party components and licences

Licences were read from the installed package metadata (`pip show`) on 2026-11-06 and,
for PyMuPDF, also from the official documentation
(https://pymupdf.readthedocs.io/en/latest/about.html, section "License and Copyright").
This is an engineering inventory, **not legal advice**. Items marked *to review* must be
checked before a public release.

## Runtime dependencies (installed by pip; not vendored)

| Component | Version tested | Licence (as declared) | Notes |
|---|---|---|---|
| PyMuPDF (+ bundled MuPDF) | 1.28.2 | **AGPL-3.0** or Artifex commercial licence (dual) | Main reason the project is AGPL-3.0-or-later. If you modify PATT-PDF and let others use it over a network, AGPL section 13 may require offering them the source; the alternative is a commercial MuPDF licence. How this applies to a given deployment is a legal question. |
| numpy | 2.2.6 | BSD-3-Clause | |
| fontTools | 4.65.0 | MIT | |
| opencv-python-headless *(optional, `[ocr]`)* | 5.0.0.93 | Apache-2.0 | Wheels bundle third-party libraries (FFmpeg etc.) under their own licences — *to review* if redistributing binaries. |
| Pillow *(dev; used by `compare`)* | 12.3.0 | MIT-CMU | |
| pytest, pyflakes *(dev only)* | — | MIT | Not needed at runtime. |

## External programs (not installed by pip)

| Program | Version tested | Licence | Use |
|---|---|---|---|
| Tesseract OCR | 4.1.1 | Apache-2.0 | Called as a subprocess (`tesseract` CLI) for vector-glyph and scanned pages. Language data `eng` has its own licence (Apache-2.0, tessdata). |

## Fonts (not included in this repository)

| Font | Licence | Use |
|---|---|---|
| Noto Sans CJK SC, Noto Serif CJK SC (© Adobe; googlefonts/noto-cjk) | SIL Open Font License 1.1 | `patt-pdf fonts` copies the SC members from fonts already on the system (or in `PATT_PDF_FONT_SOURCE`) into a per-user data directory; fonts are never committed or shipped with the package. Subsets are embedded in output PDFs; OFL 1.1 explicitly allows embedding fonts in documents. |

## Services

| Service | Terms | Notes |
|---|---|---|
| DeepL API (Free / Pro) | DeepL terms of service | Optional. Source text is sent to DeepL; usage is billed in characters. Users supply their own key. |

## Code provenance

All code in `src/patt_pdf/` was written for this project (first as a prototype in
2026-11, see `docs/MIGRATION.md`). No source code was copied from BabelDOC,
pdf2zh / pdf2zh-next or other translation projects; BabelDOC 0.5.24 was only *run*
in a separate experiment to compare behaviour.

## To review before public release
- Confirm AGPL-3.0-or-later is acceptable for the maintainer's goals (MIT/Apache would
  require replacing PyMuPDF, e.g. with pikepdf + pdfium, which is a large rewrite).
- OpenCV wheel bundled-library notices, if binaries are ever redistributed.
- No data files are shipped in the package (the earlier example glossary was removed in v0.3).
- `docs/sample/` images are rendered from the synthetic fixtures with Noto CJK SC
  (OFL 1.1 allows embedding the fonts in documents and images).
