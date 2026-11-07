"""Test helper (put this folder on PYTHONPATH of a child process): make
locale.getpreferredencoding() emit an EncodingWarning attributed to the standard library, as
CPython 3.11+ does under `-X warn_default_encoding`. Lets Python 3.10 reproduce review finding
W01 deterministically. Never imported by PATT-PDF itself."""
import locale
import warnings

_orig = locale.getpreferredencoding


def getpreferredencoding(do_setlocale=True):
    warnings.warn_explicit("UTF-8 Mode affects locale.getpreferredencoding(). Consider locale.getencoding() instead.",
                           EncodingWarning, locale.__file__, 1)
    return _orig(do_setlocale)


locale.getpreferredencoding = getpreferredencoding
