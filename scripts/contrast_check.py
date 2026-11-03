"""Check every coloured surface in the hub that carries text against white (WCAG 2.2 contrast).

Reads the colour tokens from hub.css and fails if a pair falls below 4.5:1 (normal text).
Run: uv run python scripts/contrast_check.py
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "src" / "magpiary" / "static" / "hub.css"
WHITE = (1.0, 1.0, 1.0)
FLAP_LIGHT = 0.06  # where a folder flap's text sits it is about this much lighter than the colour (the flap fades 12% to white at its top)


def rgb(hexcode: str) -> tuple[float, float, float]:
    h = hexcode.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(c) -> float:
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tuned(c, sat: float, dark: float):
    """CSS `hsl(from colour h calc(s * sat) calc(l * (1 - dark)))`."""
    import colorsys

    h, l, s = colorsys.rgb_to_hls(*c)
    return colorsys.hls_to_rgb(h, min(1.0, l * (1 - dark)), min(1.0, s * sat))


def over(fg, bg, alpha: float):
    return tuple(f * alpha + b * (1 - alpha) for f, b in zip(fg, bg))


def main() -> int:
    """White text on each category and source colour's -deep shade; on each collection colour (as tuned) the text colour
    that the CSS picks by lightness, including the lighter top of a folder's flap."""
    css = CSS.read_text()
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    tokens = dict(re.findall(r"--((?:t|s|f)-[a-z_]+(?:-deep)?):\s*(#[0-9a-fA-F]{3,6})", root))
    surfaces = {n: h for n, h in tokens.items() if n.endswith("-deep") or n.startswith("f-")}
    worst, failed = 99.0, []
    for name, hexcode in sorted(surfaces.items()):
        bg = rgb(hexcode)
        text = WHITE
        if name.startswith("f-"):
            # collection colours are tuned (saturation, darkness) and always carry white text (owner, 26 Oct)
            bg = tuned(bg, float(re.search(r"--psat:\s*([\d.]+)", root).group(1)), float(re.search(r"--pdark:\s*(-?[\d.]+)", root).group(1)))
        checks = {"text": ratio(text, bg)}
        if name.startswith("f-"):
            checks["flap top"] = ratio(text, over(WHITE, bg, FLAP_LIGHT))
        low = min(checks.values())
        worst = min(worst, low)
        # collection colours carry only bold titles of 18 px or more and short counts, and the owner chose white text on
        # them: they must reach 3:1 (large text); anything under 4.5:1 is listed as "large text only"
        need = 3.0 if name.startswith("f-") else 4.5
        flag = "FAIL" if low < need else ("ok" if low >= 4.5 else "ok (large text)")
        print(f"{name:22} {hexcode}  " + "  ".join(f"{k} {v:5.2f}" for k, v in checks.items()) + f"  {flag}")
        if flag == "FAIL":
            failed.append(name)
    # muted text (--fg-3) on every surface it sits on, in each theme (MAG-01)
    themes = {"light": (r":root, :root\[data-theme=\"light\"\] \{", ), "dark": (r":root\[data-theme=\"dark\"\] \{", )}
    for theme, (opener,) in themes.items():
        block = re.search(opener + r"(.*?)\n\s*--strip", css, re.S).group(1)
        vals = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})", block))
        for bg in ("bg", "card", "chip", "dlg", "dlg-chip"):
            if bg not in vals:
                continue
            r = ratio(rgb(vals["fg-3"]), rgb(vals[bg]))
            worst = min(worst, r)
            flag = "ok" if r >= 4.5 else "FAIL"
            print(f"muted text {theme:5} on {bg:9} {vals['fg-3']} / {vals[bg]}  {r:5.2f}  {flag}")
            if flag == "FAIL":
                failed.append(f"fg-3 on {bg} ({theme})")
        # status colours used as text (--bad-t, --ok-t, --warn-t): light values live in the first :root block
        status = dict(re.findall(r"--(bad-t|ok-t|warn-t):\s*(#[0-9a-fA-F]{3,6})", root if theme == "light" else block))
        for name, value in status.items():
            for bg in ("bg", "chip", "dlg-chip"):
                if bg not in vals:
                    continue
                r = ratio(rgb(value), rgb(vals[bg]))
                worst = min(worst, r)
                flag = "ok" if r >= 4.5 else "FAIL"
                print(f"status text {theme:5} {name:7} {value} on {bg:8} {vals[bg]}  {r:5.2f}  {flag}")
                if flag == "FAIL":
                    failed.append(f"{name} on {bg} ({theme})")
    print(f"\n{len(surfaces)} surfaces with readable text, worst {worst:.2f}:1" + (f", failing: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
