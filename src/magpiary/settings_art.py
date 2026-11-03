"""Small pictures for Settings choices (owner's decision, 24 Oct 2026): Appearance shows what each choice looks like,
and the Smart / Private cards show what leaves the Mac. Plain inline SVG; colours come from the hub's CSS classes
(`pv-*`) so they follow the theme, except the theme pictures, which show their own fixed colours."""

TILES = ("#2f6bff", "#ff2e93", "#00a37a", "#f5a300", "#8a3ffc", "#0091b3")


def _svg(body: str, w: int = 120, h: int = 80) -> str:
    return f'<svg class="pv" viewBox="0 0 {w} {h}" aria-hidden="true">{body}</svg>'


def _grid(x: float, y: float, w: float, cols: int, rows: int, gap: float = 3, rx: float = 2.5) -> str:
    size = (w - gap * (cols - 1)) / cols
    return "".join(f'<rect x="{x + c * (size + gap):.1f}" y="{y + r * (size + gap):.1f}" width="{size:.1f}" '
                   f'height="{size:.1f}" rx="{rx}" fill="{TILES[(r * cols + c) % len(TILES)]}"/>'
                   for r in range(rows) for c in range(cols))


def _page(inner: str, bg: str = "", bar: str = "") -> str:
    fill = f'fill="{bg}"' if bg else 'class="pv-page"'
    line = f'fill="{bar}"' if bar else 'class="pv-line"'
    return (f'<rect x="3" y="3" width="114" height="74" rx="9" {fill}/><rect x="3" y="3" width="114" height="74" rx="9" '
            f'class="pv-edge"/><rect x="11" y="10" width="40" height="5" rx="2.5" {line}/>{inner}')


def theme(kind: str) -> str:
    light = _page(_grid(11, 22, 98, 4, 2, 4), "#ffffff", "#e6e6e6")
    dark = _page(_grid(11, 22, 98, 4, 2, 4), "#141414", "#2c2c2c")
    if kind == "light":
        return _svg(light)
    if kind == "dark":
        return _svg(dark)
    if kind == "indigo":
        return _svg(_page(_grid(11, 22, 98, 4, 2, 4), "#0b0b4e", "#2a2a8c"))
    half = ('<rect x="60" y="3" width="57" height="74" rx="0" fill="#141414"/>'
            '<path d="M108 3a9 9 0 0 1 9 9v56a9 9 0 0 1-9 9h-48V3z" fill="#141414"/>')
    return _svg(light + half + _grid(64, 22, 45, 2, 2, 4) + '<rect x="3" y="3" width="114" height="74" rx="9" class="pv-edge"/>')


def tiles(size: str) -> str:
    cols, rows = {"s": (6, 3), "m": (4, 2), "l": (3, 2)}[size]
    return _svg(_page(_grid(11, 22, 98, cols, rows, 4 if size != "s" else 3)))


def labels(kind: str) -> str:
    """Tiles with a label strip: black (a dark fade over the picture) or in the kind's colour."""
    size, gap, x, y = 22.0, 4.0, 11, 22
    out = ""
    for c in range(4):
        tx = x + c * (size + gap) * 1.0
        col = TILES[c % len(TILES)]
        out += f'<rect x="{tx:.1f}" y="{y}" width="{size:.1f}" height="38" rx="3" fill="#8a8a8a" opacity=".55"/>'
        strip = "#0b0b0b" if kind == "black" else col
        out += (f'<rect x="{tx:.1f}" y="{y + 24}" width="{size:.1f}" height="14" rx="3" fill="{strip}"/>'
                f'<rect x="{tx + 3:.1f}" y="{y + 29}" width="{size - 6:.1f}" height="2.6" rx="1.3" fill="#fff"/>'
                f'<rect x="{tx + 3:.1f}" y="{y + 33.5}" width="{(size - 6) * .6:.1f}" height="2" rx="1" fill="#fff" opacity=".7"/>')
        if kind == "black":
            out += f'<circle cx="{tx + 5:.1f}" cy="{y + 6}" r="1.8" fill="{col}"/>'
    return _svg(_page(out))


def piles(kind: str) -> str:
    if kind == "stack":
        cards = "".join(f'<rect x="{x}" y="22" width="30" height="30" rx="6" fill="{c}" transform="rotate({a} {x + 15} 37)" '
                        f'class="pv-card"/>' for x, a, c in ((36, -14, TILES[2]), (54, 12, TILES[0]), (45, -2, TILES[1])))
        return _svg(_page(cards + '<rect x="40" y="60" width="40" height="5" rx="2.5" class="pv-ink"/>'))
    folder = ('<path d="M36 22h16l4 5h28a4 4 0 0 1 4 4v32a4 4 0 0 1-4 4H36a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z" fill="#b8327a"/>'
              f'<rect x="40" y="24" width="18" height="18" rx="3" fill="{TILES[0]}" transform="rotate(-8 49 33)" class="pv-card"/>'
              f'<rect x="58" y="22" width="18" height="18" rx="3" fill="{TILES[3]}" transform="rotate(7 67 31)" class="pv-card"/>'
              '<path d="M32 44h56v19a4 4 0 0 1-4 4H36a4 4 0 0 1-4-4z" fill="#ff2e93"/>'
              '<rect x="38" y="52" width="26" height="4" rx="2" fill="#fff"/><rect x="38" y="59" width="14" height="3" rx="1.5" fill="#fff" opacity=".7"/>')
    return _svg(_page(folder))


def search(kind: str) -> str:
    if kind == "grow":
        return _svg('<rect x="3" y="3" width="114" height="74" rx="9" class="pv-page"/>'
                    '<rect x="3" y="3" width="114" height="74" rx="9" class="pv-edge"/>'
                    '<rect x="11" y="9" width="72" height="11" rx="5.5" class="pv-hi"/>'
                    '<circle cx="18" cy="14.5" r="2.4" class="pv-stroke"/><rect x="24" y="13" width="30" height="3" rx="1.5" class="pv-ink"/>'
                    + _grid(11, 28, 98, 4, 2, 4))
    return _svg('<rect x="3" y="3" width="114" height="74" rx="9" class="pv-page"/>' + _grid(11, 22, 98, 4, 2, 4)
                + '<rect x="3" y="3" width="114" height="74" rx="9" class="pv-dim"/>'
                '<rect x="20" y="24" width="80" height="16" rx="8" class="pv-hi"/>'
                '<circle cx="29" cy="32" r="3" class="pv-stroke"/><rect x="36" y="30.5" width="38" height="3" rx="1.5" class="pv-ink"/>'
                '<rect x="20" y="44" width="80" height="14" rx="5" class="pv-hi" opacity=".75"/>'
                '<rect x="3" y="3" width="114" height="74" rx="9" class="pv-edge"/>')


def width(value: str) -> str:
    share = {"1600": .52, "1920": .64, "2200": .76, "2400": .86, "full": 1.0}[value]
    w = 98 * share
    x = 11 + (98 - w) / 2
    cols = 3 if share < .6 else 4 if share < .8 else 5
    guides = ("" if value == "full" else
              f'<path d="M{x - 3:.1f} 8v66M{x + w + 3:.1f} 8v66" class="pv-guide"/>')
    return _svg('<rect x="3" y="3" width="114" height="74" rx="9" class="pv-page"/>'
                '<rect x="3" y="3" width="114" height="74" rx="9" class="pv-edge"/>' + guides
                + f'<rect x="{x:.1f}" y="10" width="{w * .4:.1f}" height="5" rx="2.5" class="pv-line"/>'
                + _grid(x, 22, w, cols, 2, 3))


def mode(kind: str) -> str:
    """A small Mac. Smart: three things go out to an AI. Private: everything stays inside."""
    mac = ('<rect x="14" y="16" width="62" height="42" rx="5" class="pv-macbody"/>'
           '<rect x="19" y="21" width="52" height="32" rx="2.5" class="pv-page"/>'
           '<path d="M8 62h74l-5 5H13z" class="pv-macbody"/>')
    if kind == "smart":
        film = ('<rect x="24" y="26" width="18" height="22" rx="3" fill="#000" opacity=".85"/>'
                '<path d="M31 33v8l6-4z" fill="#fff"/>'
                '<rect x="46" y="27" width="20" height="3" rx="1.5" class="pv-ink"/>'
                '<rect x="46" y="33" width="16" height="3" rx="1.5" class="pv-ink" opacity=".6"/>'
                '<rect x="46" y="39" width="18" height="3" rx="1.5" class="pv-ink" opacity=".6"/>')
        out = ('<path d="M80 30h26M80 38h26M80 46h26" class="pv-arrow"/>'
               '<path d="M102 26l5 4-5 4M102 34l5 4-5 4M102 42l5 4-5 4" class="pv-arrow"/>'
               '<circle cx="128" cy="38" r="15" fill="#ff2e93"/>'
               '<path d="M128 29.5l2.2 6.3 6.3 2.2-6.3 2.2-2.2 6.3-2.2-6.3-6.3-2.2 6.3-2.2z" fill="#fff"/>')
        return _svg(mac + film + out, 150, 76)
    film = ('<rect x="24" y="26" width="18" height="22" rx="3" fill="#000" opacity=".85"/>'
            '<path d="M31 33v8l6-4z" fill="#fff"/>'
            '<rect x="46" y="27" width="20" height="3" rx="1.5" class="pv-ink"/>'
            '<rect x="46" y="33" width="16" height="3" rx="1.5" class="pv-ink" opacity=".6"/>')
    lock = ('<circle cx="120" cy="38" r="15" class="pv-okbg"/>'
            '<rect x="113" y="37" width="14" height="10" rx="2" fill="#fff"/>'
            '<path d="M116 37v-3a4 4 0 0 1 8 0v3" stroke="#fff" stroke-width="2.2" fill="none"/>'
            '<path d="M80 38h18" class="pv-arrow pv-cut"/><path d="M86 31l8 14M94 31l-8 14" class="pv-x"/>')
    return _svg(mac + film + lock, 150, 76)
