"""Progress lines on stderr. stdout keeps its stable, parseable output.

In a terminal one line is rewritten in place; when stderr is redirected (logs, CI, pipes)
one plain line is written per file and no control characters are used.
"""
from __future__ import annotations

import shutil
import sys
import time


class Progress:
    def __init__(self, quiet: bool = False, stream=None):
        self.stream = stream if stream is not None else sys.stderr
        self.quiet = quiet
        try:
            self.tty = bool(self.stream.isatty())
        except (AttributeError, ValueError):
            self.tty = False
        self._open = False          # a rewritable line is on screen
        self._last = 0.0
        self._file = None

    def _write(self, s: str) -> None:
        try:
            self.stream.write(s); self.stream.flush()
        except (OSError, ValueError):
            self.quiet = True       # closed pipe: stop reporting, never fail the job

    def update(self, stage: str, rel: str, done: int | None = None, total: int | None = None, note: str = "") -> None:
        """`stage` e.g. 'plan'; `done`/`total` are pages of the current file."""
        if self.quiet:
            return
        if not self.tty:
            if (stage, rel) != self._file:               # one line per file and stage
                self._file = (stage, rel)
                self._write(f"{stage}: {rel}" + (f" ({total} pages)" if total else "") + "\n")
            return
        now = time.monotonic()
        if done is not None and total and done < total and now - self._last < 0.08:
            return                                        # do not flood the terminal
        self._last = now
        msg = f"{stage}  {rel}"
        if total:
            msg += f"  page {min(done or 0, total)}/{total}"
        if note:
            msg += f"  · {note}"
        width = shutil.get_terminal_size((80, 20)).columns - 1
        if len(msg) > width:
            msg = msg[:max(0, width - 1)] + "…"
        self._write("\r\x1b[2K" + msg)
        self._open = True

    def clear(self) -> None:
        """Remove the rewritable line before normal output is printed."""
        if self._open and not self.quiet:
            self._write("\r\x1b[2K")
        self._open = False


NULL = Progress(quiet=True)
