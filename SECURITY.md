# Security

## Reporting a vulnerability

Please report security problems privately through GitHub: on the repository page choose
**Security → Report a vulnerability**. If that is not available, open an issue that says
only that you have a security report, without details, and wait for a contact.

This is a small project maintained in spare time. There is no guaranteed response time and
no bounty.

## What is in scope

- `install.sh`: it is run with `curl … | bash`, may call `sudo` (Linux) or Homebrew (macOS),
  and downloads packages. Anything that makes it run or install something other than what it
  announces is in scope.
- Handling of the DeepL key: the key is read from the environment or a private file, is never
  printed or logged, and must not appear in reports, caches or diagnostics.
- Leaks of local paths or document content into files meant to be shared (`patt-pdf report`,
  `patt-pdf doctor`, `tools/preflight.py`).
- Crashes or code execution from a crafted PDF **in PATT-PDF's own code**. Problems inside
  PyMuPDF/MuPDF, Tesseract or OpenCV belong to those projects; tell us too if PATT-PDF can
  avoid them.

## What to know as a user

- The working folder (`--state`) stores source text and translations in plain text. Keep it
  private; it is not meant to be shared or committed.
- With the DeepL backend, the text to translate is sent to DeepL. Nothing is sent before you
  confirm (or pass `--yes` with `--max-chars`).
- By default the installer downloads through mirrors operated by Tsinghua University (TUNA).
  Mirror files are copies kept by the mirror operator. Choose `--mirror official` if you
  prefer the original sources. Reading the script before running it is always possible:
  see `docs/INSTALL.md`.
- Only the latest commit on `main` is supported; there are no maintained release branches.
