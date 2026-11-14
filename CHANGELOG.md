# Changes

All versions so far are development pre-releases. What was run, on which machines, and what
is still unverified is recorded per version in [docs/STATUS.md](docs/STATUS.md).

## 0.4.4.dev0 — 2026-11-14

First version published after `0.3.8.dev0`; it contains everything listed below.

- **Labels next to curved text.** An upright label crossed by text that follows a curve
  no longer damages it: the curved letter is not removed and redrawn any more, and the
  translation is not printed over it. A label with no room beside the curve keeps its
  source text and is listed (`label_left_source`).
- **Place names in two lines** ("San" over "Francisco") are one text, translated as a
  whole and set on one centred line when it fits.
- **Numbered legends:** a bare number next to a line starts a list item.
- Showcase images re-made. Engine `patt-0.4-e3`: plans are re-made.

## 0.4.3.dev0 — 2026-11-13 (not published)

- **Checked on macOS as well.** Three rounds on an Apple Silicon Mac, including one complete
  install through Homebrew. The READMEs and `docs/STATUS.md` say what was run where.
- **Front page.** Showcase images for light and dark themes; the language tags no longer
  cover the pages. Results and limits are separate sections.
- **Installer.** Says that Homebrew may update itself before installing; no longer claims
  that uv is much faster than pip. Its Homebrew branch is exercised by tests with a
  stand-in `brew`.
- **Project files.** `CONTRIBUTING.md`, `SECURITY.md`, an issue form and this change log.
- `tools/diagonal_compare.py`: `--swap N` shows a card with the translation on the left.

## 0.4.2.dev0 — 2026-11-13

- **Installer, macOS:** with the system bash 3.2 the installer stopped after step 1
  (`SOURCE…: unbound variable`) and still returned 0. Variables next to non-ASCII text are
  delimited, and an install that stops early never returns 0.
- Installer tests run with every available bash and under several locales.

## 0.4.1 (no package version of its own) — 2026-11-13

- **Curved labels:** a piece of a curved label that is exactly vertical was translated
  ("HUNTING CREEK" became "HUNTING CR" plus Chinese); a label could be left half translated;
  a slanted letter crossed by a translated upright label disappeared. Engine `patt-0.4-e2`.
- **Installer:** five numbered steps with download sizes and progress; mirrors in mainland
  China (Tsinghua TUNA) by default with the official sources as the other choice
  (`--mirror cn|official`); uv is used when it is already installed (`--no-uv`); messages in
  Chinese in a Chinese locale.

## 0.4.0.dev0 — 2026-11-13

- **`patt-pdf run`:** analyse, estimate, confirm, translate, render and copy in one command.
  Every rendered file is delivered; the terminal shows one line per file.
- **`--pages`:** `7`, `7-9`, `7,9`, `1-3,7,10-`. The output keeps every page; only the
  selected pages are translated and reported.
- **Progress and speed:** progress lines on stderr (`--quiet`); pages that need OCR are
  analysed in parallel (`--workers`); faster rendering of pages with many vector paths.
- **Unusable translations are never drawn:** text made only of names, codes and figures is
  not sent; an answer with an added language label is repaired, retried once with context,
  or replaced by the source text.
- **Curved text** (map labels) stays in place and is listed; straight slanted labels are
  translated at their angle.
- **Tables:** rows are cut into cells, so each cell is translated in its own column.
- **Real-document tests:** seven public documents listed with checksums and licences,
  fetched into a local cache at test time; the PDFs are not in the repository.
- Engine `patt-0.4-e1`: plans made by earlier versions are re-made.

## 0.3.9.dev0 — 2026-11-13

First run on real documents with DeepL. Fixed: a crash on links with named destinations
(LaTeX papers); a kept one-letter item erasing that letter across the page; sans-serif
documents set in a serif face; justified paragraphs split at every full stop; table figures
such as `13.0B` rewritten by the translator; number checks failing on correct translations.
READMEs rewritten; diagonal showcase images added.

## 0.3.8.dev0 and earlier

Cross-platform reliability work (encodings, paths, interrupts, privacy of diagnostics), the
one-line installer, and the original engine. See [docs/STATUS.md](docs/STATUS.md).
