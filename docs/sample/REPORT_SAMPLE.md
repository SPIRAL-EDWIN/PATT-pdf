# PATT-PDF report

Files: 14 · pages: 12 · FAIL: 1 · pass: 6 · needs review: 4 · UNVERIFIED: 1

Statuses: **pass** = no automatic check found a problem; **needs review** = a human must look (e.g. figures read by OCR, explicitly accepted limitations); **UNVERIFIED** = a needed check could not run; **FAIL** = a known problem. Automatic QA does not prove a page is completely or correctly translated — check renders by eye (`patt-pdf compare`).

| File | Status | Pages (pass/review/unverified/fail) | Problems |
|---|---|---|---|
| damaged.pdf | ERROR (StalePlan: error: PDF has no pages (damaged or empty)) | 0/0/0/0 | — |
| decor_scan.pdf | needs review | 0/1/0/0 | p1 review: possible_underline_in_image |
| decorations.pdf | needs review | 1/1/0/0 | p2 review: decoration_not_adjusted, link_area_not_mapped, markup_annotation_on_translated_text |
| encrypted.pdf | ERROR (StalePlan: error: PDF is encrypted (password required)) | 0/0/0/0 | — |
| financial.pdf | pass | 1/0/0/0 | — |
| image_text.pdf | UNVERIFIED | 0/0/1/0 | p1 unverified: image_unverified |
| rotated.pdf | pass | 1/0/0/0 | — |
| scanned.pdf | needs review | 0/1/0/0 | p1 review: ocr_digits_review |
| table.pdf | pass | 1/0/0/0 | — |
| toc.pdf | pass | 1/0/0/0 | — |
| truncated.pdf | ERROR (StalePlan: error: FileDataError: Failed to open file '<input>/truncated.pdf' as type pdf.) | 0/0/0/0 | — |
| two_column_cropbox.pdf | FAIL | 0/0/0/1 | p1 fail: residual_english, untranslated |
| vector_glyphs.pdf | needs review | 0/1/0/0 | p1 review: ocr_digits_review |
| 报告 2026 – résumé.pdf | pass | 1/0/0/0 | — |

## Figures read by OCR (verify against the original)

- scanned.pdf p1: Scanned note: the gate opens 60 minutes before sunrise.
- vector_glyphs.pdf p1: Page 3 of 9

## Images not verified — may contain untranslated text; check visually

- image_text.pdf p1: OCR found no legible text
