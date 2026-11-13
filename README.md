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

<sub>Real pages translated with DeepL, unedited. Upper left of each page: the original. Lower right: the PATT-PDF output. PATT's own checks rate the paper and the form `pass` and the map page `fail` (curved map labels are not handled yet). [Sources and licences](#sample-pages).</sub>

## Install

macOS and Linux, one command:

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
```

The script prints each step before it runs, installs into its own folder and finishes with a self-check. On a Mac without Homebrew it asks before installing Homebrew. Details, manual steps and uninstall: [docs/INSTALL.md](docs/INSTALL.md).

## Use

```bash
export DEEPL_AUTH_KEY=...                                  # your own DeepL API key

patt-pdf plan      ./in --state ./work                     # analyse pages (offline)
patt-pdf estimate  ./in --state ./work --backend deepl     # how many characters?
patt-pdf translate ./in --state ./work --backend deepl --max-chars 10000 --yes
patt-pdf render    ./in --state ./work --backend deepl     # translated PDFs + checks
patt-pdf report    ./in --state ./work --out report.md     # what to look at
patt-pdf publish   ./in --state ./work --dest ./translated
```

`./in` holds your PDFs and is never written to. Nothing is sent to DeepL before `translate`, and never more than `--max-chars`.

## What you get

| | |
|---|---|
| **The page stays** | Text is replaced in its own box. Images, charts, table rules and page numbers are not redrawn; links are kept. |
| **Numbers are checked** | Every figure in the source must appear in the translation. On the sample pages this caught DeepL turning `62B` into `62亿`. |
| **A report, not a promise** | Each page is rated `pass`, `review` or `fail` with the reason. Only `pass` files are published by default. |
| **Your budget** | An estimate first, a hard character cap, and a cache so nothing is paid twice. |
| **Offline when needed** | Planning, layout tests and hand-made translations need no network. OCR runs locally and only on pages that need it. |

## How well does it work?

Results on 12 pages from 7 public documents (DeepL, v0.3.9.dev0, Linux), rated by PATT's own checks:

| Document | Pages | Result |
|---|---|---|
| Research paper with figures (arXiv 2201.11903) | 2 | 1 pass · 1 fail (DeepL changed a figure) |
| Two-column paper with a table (arXiv 2302.13971) | 2 | 1 review · 1 fail (figure legend mistranslated, table header merged) |
| Journal article (PLOS ONE) | 2 | 1 review · 1 fail |
| Standard with diagrams (NIST CSWP 29) | 2 | 1 pass · 1 fail (text inside an image stays English) |
| Tax form (IRS W-9) | 1 | 1 pass |
| Fact sheets with maps and photos (USGS) | 3 | 3 fail (curved labels, text inside images) |

A `fail` usually means one item on the page needs a look, not that the page is unusable. A `pass` means the checks found nothing; it does not prove the translation is right. Read the report and compare by eye. Full notes: [docs/STATUS.md](docs/STATUS.md).

**Not there yet:** English → Simplified Chinese only · tables are not rebuilt cell by cell · text inside images stays English · inline italics and link colours are lost · formulas and curved labels can break · no graphical interface · Windows is maintained separately and not verified for this version.

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
