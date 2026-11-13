#!/usr/bin/env python3
"""Diagonal before/after picture of a translated page (showcase images for the README).

One page is rendered twice at the same size — from the source PDF and from the PATT-PDF
output — and the two renders are joined along a diagonal: the original in the upper-left
part, the translation in the lower-right part. Because both halves come from the same page
geometry, figures, rules and tables run across the seam without a step; that continuity is
the point of the picture.

    python tools/diagonal_compare.py --pair in/a.pdf work/out/a.pdf 1 --out a.jpg
    python tools/diagonal_compare.py --pair A.pdf A_zh.pdf 1 --pair B.pdf B_zh.pdf 2 \
           --out hero.jpg --theme dark --labels "English" "简体中文" --swap 2

`--swap N` shows card N the other way round (translation upper left, original lower right),
for pages whose left side is the more telling part of the translation.

Needs PyMuPDF, Pillow and NumPy (the `dev` extra). Reads the PDFs, writes one image, nothing
else. The picture shows whatever the output contains, including its defects: choose pages
whose QA status you are prepared to state next to the image.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GREEN, CORAL = (51, 199, 155), (240, 112, 95)          # the two logo colours
THEMES = {
    "dark": dict(bg0=(13, 17, 23), bg1=(27, 36, 48), ink=(233, 237, 243), sub=(139, 148, 158)),
    "light": dict(bg0=(246, 248, 250), bg1=(232, 238, 244), ink=(20, 23, 28), sub=(87, 96, 106)),
}


def _render(pdf: Path, page: int, height: int) -> Image.Image:
    with pymupdf.open(pdf) as d:
        if not 1 <= page <= d.page_count:
            raise SystemExit(f"{pdf.name}: page {page} is not in the document (1-{d.page_count})")
        pg = d[page - 1]
        z = height / pg.rect.height
        pm = pg.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes("RGB", (pm.width, pm.height), pm.samples)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    names = (["NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf", "PingFang.ttc", "Hiragino Sans GB.ttc"] if bold else
             ["NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf", "PingFang.ttc", "Hiragino Sans GB.ttc"])
    roots = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".local/share/fonts"),
             "/System/Library/Fonts", "/Library/Fonts", str(Path.home() / "Library/Fonts"), "/opt/homebrew/share/fonts"]
    for root in roots:
        for n in names:
            for p in Path(root).rglob(n) if Path(root).is_dir() else ():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    continue
    return ImageFont.load_default()


def card(src: Path, out: Path, page: int, height: int, top: float, bottom: float, seam: int, swap: bool = False):
    """One page: original above/left of the diagonal, translation below/right of it
    (the other way round with `swap`). Returns the image; the tags are drawn by compose()."""
    a = _render(src, page, height)
    b = _render(out, page, height).resize(a.size, Image.LANCZOS)
    if swap:
        a, b = b, a
    w, h = a.size
    ss = 3                                               # supersampled mask: smooth diagonal
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).polygon([(top * w * ss, 0), (w * ss, 0), (w * ss, h * ss), (bottom * w * ss, h * ss)], fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    img = Image.composite(b, a, mask)
    # seam: a two-colour line; each half has the colour of the side it borders
    left, right = (CORAL, GREEN) if swap else (GREEN, CORAL)
    ov = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    p0, p1 = (top * w * ss, -2 * ss), (bottom * w * ss, h * ss + 2 * ss)
    half = seam * ss / 2
    d.line([(p0[0] - half, p0[1]), (p1[0] - half, p1[1])], fill=left + (255,), width=int(seam * ss))
    d.line([(p0[0] + half, p0[1]), (p1[0] + half, p1[1])], fill=right + (255,), width=int(seam * ss))
    return Image.alpha_composite(img.convert("RGBA"), ov.resize((w, h), Image.LANCZOS))


def _tag(d, xy, text, colour, f, pad, anchor="l"):
    """A pill with white text. `xy` is its top-left corner (anchor "l") or top-right ("r")."""
    tw, th = d.textbbox((0, 0), text, font=f)[2:]
    bw, bh = tw + 4 * pad, th + 2 * pad + pad // 2
    x = xy[0] if anchor == "l" else xy[0] - bw
    d.rounded_rectangle((x, xy[1], x + bw, xy[1] + bh), radius=bh // 2, fill=colour + (255,))
    d.text((x + 2 * pad, xy[1] + pad - pad // 4), text, font=f, fill=(255, 255, 255, 255))
    return bh


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius, fill=255)
    img = img.convert("RGBA"); img.putalpha(m)
    return img


def compose(cards, theme: str, gap: int, margin: int, captions, labels, swaps) -> Image.Image:
    """Cards on a background. The language tags sit outside each card (above its left edge
    and below its right edge), so they never cover the page."""
    t = THEMES[theme]
    h = max(c.size[1] for c in cards)
    f_tag = _font(max(12, h // 58)); pad = max(5, h // 150)
    tag_h = int(h * 0.034) + 2 * pad
    W = sum(c.size[0] for c in cards) + gap * (len(cards) - 1) + 2 * margin
    top = margin // 2 + tag_h + pad * 2
    H = top + h + pad * 2 + tag_h + margin // 2             # captions share the row of the lower tags
    g = np.linspace(0, 1, W)[None, :, None] * 0.6 + np.linspace(0, 1, H)[:, None, None] * 0.4
    bg = (np.array(t["bg0"])[None, None, :] * (1 - g) + np.array(t["bg1"])[None, None, :] * g).astype(np.uint8)
    canvas = Image.fromarray(bg, "RGB").convert("RGBA")
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    x = margin; places = []
    radius = max(8, h // 60)
    for c in cards:
        y = top + (h - c.size[1]) // 2
        ImageDraw.Draw(shadow).rounded_rectangle((x + 4, y + 14, x + c.size[0] + 4, y + c.size[1] + 14), radius=radius,
                                                 fill=(0, 0, 0, 120 if theme == "dark" else 70))
        places.append((x, y)); x += c.size[0] + gap
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(max(6, h // 50))))
    f = _font(max(13, h // 48), bold=False)
    d = ImageDraw.Draw(canvas)
    for c, (x, y), cap, sw in zip(cards, places, captions, swaps):
        canvas.alpha_composite(_rounded(c, radius), (x, y))
        first, second = ((labels[1], CORAL), (labels[0], GREEN)) if sw else ((labels[0], GREEN), (labels[1], CORAL))
        _tag(d, (x, y - tag_h - pad), first[0], first[1], f_tag, pad, "l")                       # upper-left part
        bh = _tag(d, (x + c.size[0], y + c.size[1] + pad * 2), second[0], second[1], f_tag, pad, "r")   # lower-right part
        if cap:
            d.text((x, y + c.size[1] + pad * 2 + (bh - d.textbbox((0, 0), cap, font=f)[3]) // 2 - 1), cap, font=f, fill=t["sub"] + (255,))
    return canvas.convert("RGB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pair", nargs=3, action="append", required=True, metavar=("SOURCE", "OUTPUT", "PAGE"),
                    help="source PDF, translated PDF, 1-based page number (repeat for several cards)")
    ap.add_argument("--out", required=True, help="image to write (.jpg or .png); never overwrites")
    ap.add_argument("--height", type=int, default=1100, help="page height in pixels (default 1100)")
    ap.add_argument("--top", type=float, default=0.66, help="where the diagonal meets the top edge, 0-1 (default 0.66)")
    ap.add_argument("--bottom", type=float, default=0.34, help="where it meets the bottom edge, 0-1 (default 0.34)")
    ap.add_argument("--theme", choices=sorted(THEMES), default="dark")
    ap.add_argument("--labels", nargs=2, default=["English", "简体中文"], metavar=("ORIGINAL", "TRANSLATED"))
    ap.add_argument("--caption", action="append", default=[], help="one caption per card, in order")
    ap.add_argument("--swap", type=int, action="append", default=[], metavar="N",
                    help="show card N (1-based) the other way round: translation upper left, original lower right")
    ap.add_argument("--bare", action="store_true", help="single card only: no background, tags, shadow or caption")
    ap.add_argument("--quality", type=int, default=88, help="JPEG quality (default 88)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        print(f"refusing to overwrite {out.name}", file=sys.stderr); return 2
    seam = max(2, a.height // 260)
    swaps = [i + 1 in a.swap for i in range(len(a.pair))]
    cards = [card(Path(s), Path(o), int(p), a.height, a.top, a.bottom, seam, sw) for (s, o, p), sw in zip(a.pair, swaps)]
    caps = (a.caption + [""] * len(cards))[:len(cards)]
    img = cards[0].convert("RGB") if (a.bare and len(cards) == 1) else compose(
        cards, a.theme, gap=a.height // 18, margin=a.height // 14, captions=caps, labels=a.labels, swaps=swaps)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=a.quality, optimize=True, progressive=True) if out.suffix.lower() in (".jpg", ".jpeg") else img.save(out, optimize=True)
    print(f"wrote {out.name} ({img.size[0]}x{img.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
