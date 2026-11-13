# PATT-PDF logo

## Authorship and license

The project owner confirms that the distributed PATT-PDF logo SVGs and
`logo-preview.png` are original work created for this project. These assets
are distributed under the project's AGPL-3.0-or-later license; see
[LICENSE](../LICENSE). The wordmark's visual style was inspired by OpenCode;
PATT-PDF is not affiliated with or endorsed by the OpenCode project.

See **`logo-preview.png`** for an overview on light and dark backgrounds. A 1280 × 640
social-preview image for the repository settings is in `docs/showcase/social-preview.jpg`.

The mark has two parts: an **icon** (a PDF page split by a black diagonal, with a red
source line on the upper-left and its green translated line on the lower-right of the
**same row** — the alignment is the point: translated in place) and a chunky,
**opencode-inspired blocky wordmark** where **PA is green and TT is red**.

Everything is hand-built vector SVG: no fonts, external resources, raster images, or
JavaScript. Backgrounds are transparent and each file has a `viewBox`.

## Palette (muted "sci", high-contrast but not pure red/green)

| role | light bg | dark bg |
|------|----------|---------|
| green (PA / translated) | `#18A079` | `#33C79B` |
| red (TT / source) | `#DB5B4C` | `#F0705F` |
| ink (page + diagonal) | `#14171C` | `#E9EDF3` |

Use `*-light.svg` on light backgrounds and `*-dark.svg` on dark. Note: the diagonal is
black on light backgrounds; on dark backgrounds it flips to near-white so it stays
visible (a black line would disappear on a dark page).

## Files

```
logo-horizontal-{light,dark}.svg   icon + PATT wordmark (README / header)
logo-wordmark-{light,dark}.svg     PATT wordmark only
logo-icon-{light,dark}.svg         page icon only (avatar / favicon)
logo-preview.png                   overview image
_archive_concepts/                 earlier three-concept exploration (kept for reference)
```

Still a draft — the exact green/red, the notch detail, letter spacing, and the icon's
diagonal/row layout can all be tuned. PNG/ICO favicons can be exported once settled.
