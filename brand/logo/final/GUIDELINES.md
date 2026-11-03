# Magpiary logo: one-page guide (v2, wordmark style D)

Status: first kit, built to be refined by hand in Figma or Illustrator. Not trademark-cleared.

## The logo
- **Symbol:** "The Pair", two bookmark birds, one behind the other. The back bird is pink, the front bird ink, and the front bird's eye is a pink sparkle (v2, 24 Oct 2026: matches the hub).
- **Wordmark:** "Magpiary" in a bold geometric sans, drawn as outlines (no font is installed or licensed). The dot of the i is the same sparkle.
- **Idea:** a magpie keeps shiny things; this is where you keep what you find.

## Files (`brand/logo/final/`)
| Need | File |
|---|---|
| Main logo, light backgrounds | `lockup-horizontal.svg`, `lockup-stacked.svg` |
| Dark backgrounds | `lockup-horizontal-reversed.svg`, `lockup-stacked-reversed.svg` |
| One colour (print, stamps, docs) | `lockup-horizontal-black.svg`, `icons/magpiary-horizontal-white.svg` |
| Symbol alone | `symbol.svg`, `symbol-black.svg`, `symbol-reversed.svg` |
| **Under 24 px / macOS menu bar / template image** | `symbol-small.svg` (single colour, wider gap, bigger sparkle) |
| App icon, avatar | `icons/magpiary-symbol-app-icon.svg` (+ PNGs), `icons/magpiary-symbol-square.svg`. The Mac app and disk image use `icons/magpiary-app-icon-1024.png` (flat birds on a dark tile with soft glow, made with Codex, 1 Nov 2026) |
| Website | `web/` (favicon.ico, favicon.svg, apple-touch-icon, 192/512, maskable, manifest, head snippet) |
| Regenerate or tweak | `build_logo.py` (`uv run build_logo.py`) |

## Colour
| Name | Hex | RGB | Use |
|---|---|---|---|
| Ink | `#111111` | 17 17 17 | Front bird, letters, dark backgrounds (the hub's text colour) |
| Pink | `#FF2E93` | 255 46 147 | Back bird and sparkles (the hub's accent) |
| Cream | `#FBF6EA` | 251 246 234 | Front bird and letters on Ink |

Contrast: Ink on white 18.9:1, Cream on Ink 17.4:1, Pink on Ink 5.4:1. **Pink on white is 3.4:1**, fine for the bird and
sparkles (large shapes) but never for small text. The app icon is an Ink tile with a Cream front bird and a Pink back
bird. CMYK and Pantone values are not set yet.

## Clear space and minimum size
- **Clear space:** keep at least the width of the front bird's head (about one fifth of the symbol's width) free on every side.
- **Minimum sizes:** full symbol 24 px (or 8 mm). Below that, use `symbol-small.svg`; below 16 px use nothing smaller than that. Horizontal logo 120 px wide (30 mm). Stacked logo 80 px wide.
- **Menu bar:** `symbol-small.svg`, black on transparent, marked as a template image so macOS tints it.

## Backgrounds
Ink or Cream backgrounds, or a photo with a calm area. On busy images put the logo on a solid Ink or Cream tile. On any coloured background that isn't Ink, use the one-colour black or white version.

## Don't
- Don't recolour the birds, or make the sparkle any colour except Pink (or the logo's single colour).
- Don't stretch, rotate, add shadows, outlines or gradients.
- Don't redraw the wordmark in a font; use the outlines.
- Don't put the gold sparkle on white at small sizes where it disappears; use a one-colour version.
- Don't separate the two birds or fill the gap between them.
- Don't imitate or combine with the marks of Instagram, Threads, YouTube, X or Reddit.

## Open items
- Refine the letterforms by hand (the current wordmark is a first construction).
- Trademark, reverse-image and domain checks (not done; cannot be guaranteed from here).
- Choose CMYK/Pantone; confirm accessibility of the gold sparkle against your final backgrounds.
