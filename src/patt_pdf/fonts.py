"""CJK font discovery, per-document subsetting and CFF→TrueType conversion.

Migrated from prototype layout module (use_subset_fonts, _cff_to_ttf, font).
Changes: font files are located at runtime (env var / user dir / system paths)
instead of a hard-coded prototype folder; temp files go to a private temp dir.

Why the CFF→glyf conversion: MuPDF mis-maps glyphs of CID-keyed CFF *subsets*
(rendering e.g. "%" and ")" instead of hanzi), and ``Document.subset_fonts()`` fails
on these OTFs, embedding ~20 MB per face. Subsetting with fontTools and converting
outlines to quadratic glyf avoids both.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pymupdf

FACES = {
    ("sans", False): "NotoCJKsc-SansR.otf", ("sans", True): "NotoCJKsc-SansB.otf",
    ("serif", False): "NotoCJKsc-SerifR.otf", ("serif", True): "NotoCJKsc-SerifB.otf",
}
# Accepted source files per face, in order of preference. Collections (.ttc/.otc) are
# searched for the Simplified-Chinese member of the right weight. Variable fonts are NOT
# accepted (subsetting would freeze the default weight). All are SIL OFL 1.1 (Noto CJK).
SYSTEM_TTC = {
    ("sans", False): ["NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf", "NotoSansSC-Regular.otf",
                      "NotoSansSC-Regular.ttf", "NotoSansCJK.ttc"],
    ("sans", True): ["NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf", "NotoSansSC-Bold.otf",
                     "NotoSansSC-Bold.ttf", "NotoSansCJK.ttc"],
    ("serif", False): ["NotoSerifCJK-Regular.ttc", "NotoSerifCJKsc-Regular.otf", "NotoSerifSC-Regular.otf",
                       "NotoSerifSC-Regular.ttf", "NotoSerifCJK.ttc"],
    ("serif", True): ["NotoSerifCJK-Bold.ttc", "NotoSerifCJKsc-Bold.otf", "NotoSerifSC-Bold.otf",
                      "NotoSerifSC-Bold.ttf", "NotoSerifCJK.ttc"],
}
SYSTEM_DIRS: list[str] | None = None     # None: per-OS defaults from osenv.font_search_dirs (tests may override)


class FontsMissing(RuntimeError):
    pass


def font_dir() -> Path:
    """Directory holding the four extracted faces (created by `patt-pdf fonts`).
    $PATT_PDF_FONT_DIR, else %LOCALAPPDATA%\\patt-pdf\\fonts (Windows),
    else $XDG_DATA_HOME or ~/.local/share /patt-pdf/fonts."""
    env = os.environ.get("PATT_PDF_FONT_DIR")
    if env:
        return Path(env)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "patt-pdf" / "fonts"
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "patt-pdf" / "fonts"


def _member_matches(name4: str, family: str, bold: bool) -> bool:
    n = (name4 or "").lower()
    if " sc" not in n or f"noto {family}" not in n:
        return False
    weights = ("thin", "light", "demilight", "medium", "semibold", "black", "extralight", "extrabold")
    if any(w in n for w in weights):
        return False
    return ("bold" in n) == bool(bold)


def search_dirs() -> list[Path]:
    """Where `patt-pdf fonts` looks for Noto CJK, in this order and without duplicates:
    $PATT_PDF_FONT_SOURCE, then the user's own font folders, then the system font folders of
    the running OS (osenv.font_search_dirs). SYSTEM_DIRS, if set (tests), replaces the
    OS defaults."""
    from .osenv import font_search_dirs
    if SYSTEM_DIRS is not None:
        dirs = [Path(x) for x in os.environ.get("PATT_PDF_FONT_SOURCE", "").split(os.pathsep) if x]
        return dirs + [Path(d) for d in SYSTEM_DIRS]
    return font_search_dirs()


def find_system_source(key) -> Path | None:
    for d in search_dirs():
        for name in SYSTEM_TTC[key]:
            p = Path(d) / name
            if p.exists():
                return p
    return None


def install_fonts(target: Path | None = None) -> dict:
    """Extract the Simplified-Chinese members from system Noto CJK collections."""
    from fontTools.ttLib import TTCollection, TTFont
    target = Path(target or font_dir()); target.mkdir(parents=True, exist_ok=True)
    report = {}
    for key, out_name in FACES.items():
        out = target / out_name
        if out.exists():
            report[out_name] = "present"; continue
        src = find_system_source(key)
        if src is None:
            report[out_name] = ("MISSING: none of " + ", ".join(SYSTEM_TTC[key]) + " found in "
                                + "; ".join(str(d) for d in search_dirs()) + " — install Noto Sans/Serif CJK "
                                "or set PATT_PDF_FONT_SOURCE"); continue
        if src.suffix.lower() in (".ttc", ".otc"):
            for ft in TTCollection(str(src)).fonts:
                if _member_matches(ft["name"].getDebugName(4), key[0], key[1]):
                    ft.save(str(out)); break
        else:
            ft = TTFont(str(src))
            if "fvar" in ft:
                report[out_name] = f"FAILED: {src} is a variable font; use the static Regular/Bold files"; continue
            ft.save(str(out))
        report[out_name] = f"extracted from {src}" if out.exists() else f"FAILED: no matching SC member in {src}"
    return report


def face_path(family: str, bold: bool) -> Path:
    p = font_dir() / FACES[(family, bool(bold))]
    if not p.exists():
        raise FontsMissing(f"CJK font {p.name} not found in {font_dir()}; run `patt-pdf fonts` "
                           "(or set PATT_PDF_FONT_DIR to a folder containing the four NotoCJKsc-*.otf files)")
    return p


class FontSet:
    """Per-document subset fonts. Create one per output document."""

    BASE_CHARS = set("0123456789.,;:%()-–—/$ ") | set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def __init__(self, texts, workdir: str | None = None):
        self.workdir = workdir or tempfile.mkdtemp(prefix="pattpdf-fonts-")
        self._fonts: dict = {}
        self.chars = set("".join(t for t in texts if t)) | self.BASE_CHARS

    def get(self, family: str, bold: bool) -> pymupdf.Font:
        key = (family, bool(bold))
        if key not in self._fonts:
            self._fonts[key] = pymupdf.Font(fontfile=self._subset(key))
        return self._fonts[key]

    def _subset(self, key) -> str:
        from fontTools import subset
        opts = subset.Options(); opts.name_IDs = ["*"]; opts.notdef_outline = True; opts.layout_features = ["*"]
        f = subset.load_font(str(face_path(*key)), opts)
        sub = subset.Subsetter(opts); sub.populate(text="".join(sorted(self.chars))); sub.subset(f)
        if "CFF " in f:
            cff_to_ttf(f)
        out = os.path.join(self.workdir, f"{key[0]}{'B' if key[1] else 'R'}.ttf")
        f.save(out)
        return out


def cff_to_ttf(font) -> None:
    """Convert CFF outlines of a fontTools TTFont to quadratic glyf, in place."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import newTable
    gs = font.getGlyphSet(); order = font.getGlyphOrder(); glyf = {}
    for name in order:
        pen = TTGlyphPen(gs)
        gs[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf[name] = pen.glyph()
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    t = newTable("glyf"); t.glyphOrder = order; t.glyphs = glyf; font["glyf"] = t
    for g in glyf.values():
        g.recalcBounds(t)
    font["loca"] = newTable("loca")
    mp = font["maxp"]; mp.tableVersion = 0x00010000
    for a in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
              "maxStackElements", "maxSizeOfInstructions", "maxComponentElements", "maxPoints", "maxContours",
              "maxCompositePoints", "maxCompositeContours", "maxComponentDepth"):
        setattr(mp, a, 0)
    mp.maxZones = 1
    font["head"].indexToLocFormat = 0; font["head"].glyphDataFormat = 0
    font["post"].formatType = 3.0
    font.sfntVersion = "\x00\x01\x00\x00"


# ---------------------------------------------------------------------------
# Active font set for the document being rendered. A ContextVar (not a module
# global as in the prototype) so concurrent renders in threads cannot mix fonts.
import contextvars as _cv

_ACTIVE: _cv.ContextVar = _cv.ContextVar("patt_pdf_fontset")


def activate(fs: FontSet):
    return _ACTIVE.set(fs)


def font(family: str, bold: bool) -> pymupdf.Font:
    try:
        fs = _ACTIVE.get()
    except LookupError:
        raise RuntimeError("no active FontSet; call fonts.activate(FontSet(...)) before rendering") from None
    return fs.get(family, bold)
