# Installing PATT-PDF

[README](../README.md) · [简体中文](INSTALL.zh-CN.md)

PATT-PDF has one kind of install: the complete one (Python package, OpenCV, Tesseract with English data, Noto CJK fonts). Python 3.10 or newer is required.

## One-line install (macOS and Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
```

The script prints each step before running it and ends with `patt-pdf doctor`, so you see at once whether the installation is complete. It does, in this order:

1. **System packages** — Noto Sans/Serif CJK SC fonts, Tesseract with English data, and a Python ≥ 3.10 if none is found. On macOS these come from **Homebrew**: if Homebrew is not installed, the script says so and asks for confirmation before running the official Homebrew installer (which needs an administrator password and installs the Xcode Command Line Tools). On Linux it uses `apt-get` (Debian/Ubuntu), `dnf` (Fedora/RHEL), `pacman` (Arch) or `zypper` (openSUSE) through `sudo`; you may be asked for your password.
2. **PATT-PDF itself**, with OpenCV, PyMuPDF, NumPy and fontTools, into a private virtual environment at `~/.local/share/patt-pdf/venv`. Nothing is written into the system Python.
3. **The command** `~/.local/bin/patt-pdf`; if that folder is not on your `PATH`, the script offers to add one line to your shell start-up file (or prints the line for you to add).
4. `patt-pdf fonts` and `patt-pdf doctor`.

### Download source and progress

Before it downloads anything the script says where from and asks:

```text
==> Where to download from
      1) Mirror in mainland China [default]: Tsinghua University TUNA
      2) Official sources [slower from mainland China]: pypi.org, Homebrew, GitHub
    Enter = keep the mirror, 2 = official sources:
```

* **Mirror (default).** Python packages come from `pypi.tuna.tsinghua.edu.cn`, Homebrew packages from `mirrors.tuna.tsinghua.edu.cn/homebrew-bottles`. These are copies kept by the mirror operator, not files served by the original publishers. pip and uv still check each file against the hash in the index they use.
* **Official.** `pypi.org`, Homebrew's own servers and GitHub. Choose this outside mainland China.
* Answer in advance with `--mirror cn` or `--mirror official` (or `PATT_PDF_MIRROR`). Without a terminal (CI, `--yes`) the mirror is used. If the mirror does not answer within 8 seconds the official sources are used.
* The setting applies to this run only; pip and an existing Homebrew are not reconfigured. One exception, announced when it happens: a Homebrew that the script installs through the mirror keeps the mirror as its update source.
* Not on the mirror: PATT-PDF's own source (about 2 MB from GitHub) and, on macOS, the Noto CJK fonts (about 235 MB from GitHub through Homebrew, skipped when the fonts are already installed). With `--mirror cn` these two still come from GitHub.

Each of the five steps prints its number, what it downloads and roughly how much; the download tools show their own progress. The Python packages are about 75–110 MB depending on the platform. If [`uv`](https://docs.astral.sh/uv/) is already on your machine the script uses it (parallel downloads); otherwise it uses pip. It never installs uv. `--no-uv` forces pip.

Prefer to read before running? Download first, then run the same file:

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh -o install.sh
less install.sh
bash install.sh            # options: --help, --ref v0.x.y, --mirror cn|official, --no-uv, --no-system, --yes, --uninstall
```

Re-running the script upgrades the installation; `bash install.sh --uninstall` (or `curl … | bash -s -- --uninstall`) removes the virtual environment and the command link, and leaves system packages, fonts and your data alone. `--no-system` skips step 1 if you prefer to install fonts, Tesseract and Python yourself; `--ref` installs a tag or commit instead of `main`. CI checks the install with system dependencies already set up. Fedora, Arch and openSUSE package installation has yet to be verified (see [platform status](STATUS.md)). The script is not for Windows.

## Manual install

The same result, step by step. All systems use the same Python package; there are no downloadable OS-specific builds. Install Git and Python first. For the Chinese fonts below, install the Noto Sans CJK SC and Noto Serif CJK SC regular and bold faces; install Tesseract with English data as shown.

<details>
<summary><b>macOS</b></summary>

Install the fonts with Homebrew, or obtain the static SC OTF files from [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases). Also install Tesseract for OCR.

```bash
brew install --cask font-noto-sans-cjk font-noto-serif-cjk
# OCR engine and English language data:
brew install tesseract

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

</details>

<details>
<summary><b>Windows</b></summary>

> Windows is developed and tested by a Windows collaborator; this version has **not** been verified on Windows. The steps below are kept for reference.

Install the static SC OTF fonts from [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases) for your user, or keep them in a folder and set `PATT_PDF_FONT_SOURCE`. Install the [Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki) with English data as part of the standard setup. In PowerShell:

```powershell
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

If the Python launcher is unavailable, use `python -m venv .venv`. Use a short path such as `C:\patt` if Windows long paths are disabled; if `pip install` fails with a missing temporary file or "file already exists", `python tools\install_check.py --source . --work C:\pt` retries from a clean copy in a short new folder (it never deletes anything). OpenCV wheels may not be available for every Python/CPU combination, including Windows ARM; in that case the standard `pip install .` can fail before `doctor` is available. See the [platform notes](STATUS.md).

For privacy, `install_check.py` suppresses pip's output and reports its exit code.
This does not control pip's own file logging, configuration, environment, or
process arguments: avoid placing credentials in command arguments, `PIP_LOG`,
`--log`, or shared configuration, and inspect private logs before sharing.

</details>

<details>
<summary><b>Linux (Debian / Ubuntu)</b></summary>

```bash
sudo apt install fonts-noto-cjk python3-venv
# OCR engine and English language data:
sudo apt install tesseract-ocr tesseract-ocr-eng

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

</details>

`patt-pdf fonts` copies locally available fonts into a per-user directory; it does not download them. `doctor` reports detected fonts, Tesseract and environment warnings. If `patt-pdf` cannot even start (for example an editable install from a non-ASCII folder on Python 3.11 with a non-UTF-8 locale), run `python -S tools/preflight.py` with the same Python: it needs only the standard library, prints no local paths by default, and suggests a recovery. See [font and installation details](REFERENCE.md#install) for custom paths and encoding caveats.
