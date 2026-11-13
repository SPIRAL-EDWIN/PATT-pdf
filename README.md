<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/logo-horizontal-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="brand/logo-horizontal-light.svg">
  <img alt="PATT-PDF logo" src="brand/logo-horizontal-light.svg" width="300">
</picture>

### Translate a PDF. Keep the page.

PATT-PDF puts the Chinese translation where the English text was,<br>
and leaves figures, tables, rules and numbers in place.

[![Status: experimental](https://img.shields.io/badge/status-experimental-orange)](docs/STATUS.md)
[![Python: ≥3.10](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](pyproject.toml)
[![macOS: Homebrew](https://img.shields.io/badge/macOS-Homebrew-orange?logo=homebrew&logoColor=white)](docs/INSTALL.md)
[![Linux](https://img.shields.io/badge/Linux-Debian%20%C2%B7%20Ubuntu-blue?logo=linux&logoColor=white)](docs/INSTALL.md)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-lightgrey)](LICENSE)

**English** · [简体中文](README.zh-CN.md)

<img src="docs/showcase/hero.jpg" alt="Three real pages, each split diagonally: the English original on the upper left, the PATT-PDF output in Simplified Chinese on the lower right" width="100%">

</div>

<sub>Real pages translated with DeepL, unedited. Upper left of each page: the original. Lower right: the PATT-PDF output. PATT's own checks rate the paper and the form `pass` and the map page `fail`: text inside its images is not translated, and labels that follow curves are left in English. [Sources and licences](#sample-pages).</sub>

## Install

macOS and Linux, one command:

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
```

The script shows five numbered steps with download sizes and progress, installs into its own folder and finishes with a self-check. It downloads through mirrors in mainland China (Tsinghua TUNA) unless you choose the official sources when it asks, or add `--mirror official`. On a Mac without Homebrew it asks before installing Homebrew. Details, manual steps and uninstall: [docs/INSTALL.md](docs/INSTALL.md).

## Use

```bash
export DEEPL_AUTH_KEY=...            # your own DeepL API key

patt-pdf run paper.pdf               # shows the character count and asks before sending
patt-pdf run paper.pdf --pages 1-3   # try a few pages first: 7   7-9   7,9   1-3,7,10-
patt-pdf run ./papers --out ./zh --max-chars 20000 --yes      # for scripts
```

Translated PDFs go to `./translated`, and the terminal shows one line per file:

```text
pass    form.pdf    1 page                                                             → translated/form.pdf
fail    paper.pdf   2 pages: 1 pass · 1 fail  a number or URL differs from the source  → translated/paper.pdf
```

Your PDFs are never written to. Nothing is sent before you confirm, and never more than `--max-chars`. With `--pages` the output keeps every page and only the selected ones are translated. Each step also exists as its own command (`plan`, `estimate`, `translate`, `render`, `report`, `compare`, `publish`): see the [reference](docs/REFERENCE.md).

## What you get

| | |
|---|---|
| **The page stays** | Text is replaced in its own box. Images, charts, table rules and page numbers are not redrawn; links are kept. |
| **Numbers are checked** | Every figure in the source must appear in the translation. On the sample pages this caught DeepL turning `62B` into `62亿`. |
| **A report, not a promise** | Each page is rated `pass`, `review` or `fail` with the reason. Only `pass` files are published by default. |
| **Your budget** | An estimate first, a hard character cap, and a cache so nothing is paid twice. |
| **Offline when needed** | Planning, layout tests and hand-made translations need no network. OCR runs locally and only on pages that need it. |

## How well does it work?

Results on 14 pages from 7 public documents (DeepL, v0.4.0.dev0, Linux), rated by PATT's own checks:

| Document | Pages | Result | Why not all pass |
|---|---|---|---|
| Research paper with figures (arXiv 2201.11903) | 2 | 1 pass · 1 fail | DeepL changed a figure (`62B` → `62亿`) |
| Two-column paper with tables and charts (arXiv 2302.13971) | 3 | 2 review · 1 fail | link areas to check; one figure differs from the source |
| Journal article (PLOS ONE) | 3 | 2 review · 1 fail | link areas to check; a footnote mark was redrawn |
| Standard with diagrams (NIST CSWP 29) | 2 | 1 review · 1 fail | text inside an image stays English |
| Tax form (IRS W-9) | 1 | 1 pass | |
| Fact sheets with maps and photos (USGS) | 3 | 3 fail | text inside images stays English |

A `fail` usually means one item on the page needs a look, not that the page is unusable. A `pass` means the checks found nothing; it does not prove the translation is right. Compare with the original before you rely on a page. Full notes: [docs/STATUS.md](docs/STATUS.md).

**Not there yet:** English → Simplified Chinese only · text inside images stays English · text that follows a curve (map labels) stays English · inline italics and link colours are lost · formulas can break · tables are cut into cells but not re-flowed · no graphical interface · verified on Linux only so far; macOS checks are pending, and Windows is maintained separately.

## Privacy and cost

The work folder stores source text and translations in plain text. DeepL receives the text you translate and decides the bill. Read [DeepL, privacy and cost](docs/REFERENCE.md#deepl-key-cost-and-privacy) first.

## Documentation

[Install](docs/INSTALL.md) · [Reference](docs/REFERENCE.md) · [Status and verification](docs/STATUS.md) · [Architecture](docs/ARCHITECTURE.md)

```bash
python -m pip install -e '.[dev]' && python -m pytest -q      # development
```

## Sample pages

<img src="docs/showcase/more.jpg" alt="Three more real pages split diagonally between original and translation" width="100%">

The pictures are made with `tools/diagonal_compare.py` from these documents; the documents themselves are not in the repository.

- Wei et al., *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models*, [arXiv:2201.11903](https://arxiv.org/abs/2201.11903), CC BY 4.0.
- Touvron et al., *LLaMA: Open and Efficient Foundation Language Models*, [arXiv:2302.13971](https://arxiv.org/abs/2302.13971), CC BY 4.0.
- Coyle et al., [PLOS ONE 17(1): e0262897](https://doi.org/10.1371/journal.pone.0262897), CC BY 4.0.
- U.S. Geological Survey Fact Sheet 2016–3020; NIST CSWP 29; IRS Form W-9: works of the U.S. government.

The Chinese text in the pictures is machine translation produced by this tool. It is a modified version of the originals and is not endorsed by their authors.

## License

[AGPL-3.0-or-later](LICENSE). PATT-PDF builds on PyMuPDF/MuPDF (AGPL or commercial). Dependencies and fonts: [third-party notices](THIRD_PARTY_NOTICES.md).
