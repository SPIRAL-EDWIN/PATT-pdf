"""Test helper (put this folder on PYTHONPATH of a child process).

Makes the locale-encoding query that the encoding probe performs emit an EncodingWarning that is
attributed to the standard library (locale.py), on every Python version:
* Python 3.10 has no locale.getencoding(); the probe calls getpreferredencoding(), patched here;
* Python 3.11+ has getencoding() (which never warns by itself); the probe calls it, patched here.
v0.3.2 patched only getpreferredencoding(), so on 3.11+ nothing warned and the test that expects
the stdlib warning to be *reported* failed on macOS / Python 3.12 (independent review).
Never imported by PATT-PDF itself."""
import locale
import warnings

_MSG = "simulated stdlib EncodingWarning (patt-pdf test helper)"


def _wrap(fn):
    def wrapper(*a, **k):
        warnings.warn_explicit(_MSG, EncodingWarning, locale.__file__, 1)
        return fn(*a, **k)
    return wrapper


locale.getpreferredencoding = _wrap(locale.getpreferredencoding)
if hasattr(locale, "getencoding"):
    locale.getencoding = _wrap(locale.getencoding)
