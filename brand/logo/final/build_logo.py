# /// script
# requires-python = ">=3.12"
# dependencies = ["shapely>=2.0"]
# ///
"""Builds the Magpiary logo files from geometry. Run: uv run build_logo.py

Direction: C3 "The Pair" (two bookmark birds, one behind the other, sparkle eye) plus a
constructed wordmark "Magpiary" whose i-dot is the same sparkle.

The wordmark is written as plain SVG outlines made only of straight lines and true circular
arcs (about 150 anchors in total), so it stays small and clean. The symbol is a short polygon
(shapely is used only to cut the transparent gap between the two birds).
"""
import base64
import math
from pathlib import Path
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

OUT = Path(__file__).parent
# v2 (24 Oct 2026, owner's pick "Pink behind"): the hub's ink and pink. The back bird and the sparkle are pink.
INK, GOLD, CREAM = "#111111", "#FF2E93", "#FBF6EA"
PINK = GOLD

# vertical metrics of the wordmark (y grows downwards)
TOP, XT, BASE, DESC = 22, 60, 160, 220     # cap top, x-height top, baseline, descender bottom


def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pt(x, y):
    return f"{fmt(x)} {fmt(y)}"


# ----------------------------------------------------------------------------- symbol
def arc_pts(cx, cy, r, a0, a1, step=3):
    n = max(2, int(abs(a1 - a0) / step))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def spark_pts(cx, cy, R, inner=0.26):
    pts = []
    for i in range(8):
        a = math.radians(-90 + i * 45)
        rad = R if i % 2 == 0 else R * inner
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


def bird(cx, top, R=38, h=160, beak=32, beak_deg=20):
    """Bookmark bird facing right: semicircle head, 20 degree beak, 45 degree fork."""
    y = top + R
    half = beak * math.tan(math.radians(beak_deg))
    mid = y + 14.5
    pts = arc_pts(cx, y, R, 180, 360)
    pts += [(cx + R, mid - half), (cx + R + beak, mid), (cx + R, mid + half),
            (cx + R, top + h), (cx, top + h - R), (cx - R, top + h)]
    return Polygon(pts)


def symbol(gap=7, off=36, R=38, h=160, eye_R=17, eye_dx=7, eye_dy=-2, beak=32):
    fx, ft = 90, 64
    front = bird(fx, ft, R, h, beak)
    back = bird(fx + off, ft - off, R, h, beak)
    eye = Polygon(spark_pts(fx + eye_dx, ft + R + eye_dy, eye_R))
    seen_back = back.difference(front.buffer(gap, join_style=2, mitre_limit=4))
    return unary_union([front.difference(eye), seen_back]), eye


def fit(geom, size=256, margin=20, extra=()):
    minx, miny, maxx, maxy = geom.bounds
    s = (size - 2 * margin) / max(maxx - minx, maxy - miny)
    dx = size / 2 - s * (minx + maxx) / 2
    dy = size / 2 - s * (miny + maxy) / 2
    f = lambda g: affinity.translate(affinity.scale(g, s, s, origin=(0, 0)), dx, dy)
    return f(geom), [f(g) for g in extra]


def poly_d(geom, tol=0.2):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    out = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.simplify(tol).coords)[:-1]
            out.append("M" + " L".join(pt(x, y) for x, y in c) + "Z")
    return " ".join(out)


def clockwise(points):
    a = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
            for i in range(len(points)))
    return points if a > 0 else points[::-1]


def polygon_d(points):
    pts = clockwise(points)
    return "M" + " L".join(pt(x, y) for x, y in pts) + "Z"


# ----------------------------------------------------------------------------- stroke -> outline
# A chain is a list of segments: ("L", (x0, y0), (x1, y1)) or ("A", cx, cy, r, a0, a1) with angles in degrees.
# Result: one closed outline made only of lines and arcs, drawn clockwise.
def _pos(seg, end):
    if seg[0] == "L":
        return seg[2] if end else seg[1]
    _, cx, cy, r, a0, a1 = seg
    a = math.radians(a1 if end else a0)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def _tan(seg, end):
    if seg[0] == "L":
        dx, dy = seg[2][0] - seg[1][0], seg[2][1] - seg[1][1]
        n = math.hypot(dx, dy)
        return (dx / n, dy / n)
    _, cx, cy, r, a0, a1 = seg
    a = math.radians(a1 if end else a0)
    return (-math.sin(a), math.cos(a)) if a1 > a0 else (math.sin(a), -math.cos(a))


def stroke_d(chain, W, cap):
    h = W / 2
    off = lambda seg, end, side: (lambda p, t: (p[0] + side * h * t[1], p[1] - side * h * t[0]))(_pos(seg, end), _tan(seg, end))
    first, last = chain[0], chain[-1]
    d = "M" + pt(*off(first, 0, 1))
    for seg in chain:                                   # forward along the + side
        x, y = off(seg, 1, 1)
        if seg[0] == "L":
            d += f"L{pt(x, y)}"
        else:
            _, cx, cy, r, a0, a1 = seg
            R = r + h if a1 > a0 else r - h
            d += f"A{fmt(R)} {fmt(R)} 0 {1 if abs(a1 - a0) > 180 else 0} {1 if a1 > a0 else 0} {pt(x, y)}"
    x, y = off(last, 1, -1)                             # end cap
    d += (f"A{fmt(h)} {fmt(h)} 0 0 1 {pt(x, y)}" if cap == "round" else f"L{pt(x, y)}")
    for seg in reversed(chain):                         # back along the - side
        x, y = off(seg, 0, -1)
        if seg[0] == "L":
            d += f"L{pt(x, y)}"
        else:
            _, cx, cy, r, a0, a1 = seg
            R = r - h if a1 > a0 else r + h
            d += f"A{fmt(R)} {fmt(R)} 0 {1 if abs(a1 - a0) > 180 else 0} {0 if a1 > a0 else 1} {pt(x, y)}"
    if cap == "round":                                  # start cap
        x, y = off(first, 0, 1)
        d += f"A{fmt(h)} {fmt(h)} 0 0 1 {pt(x, y)}"
    return d + "Z"


def line(p0, p1):
    return ("L", p0, p1)


def ring_d(cx, cy, R, r):
    return (f"M{pt(cx - R, cy)}A{fmt(R)} {fmt(R)} 0 1 1 {pt(cx + R, cy)}A{fmt(R)} {fmt(R)} 0 1 1 {pt(cx - R, cy)}Z"
            f"M{pt(cx - r, cy)}A{fmt(r)} {fmt(r)} 0 1 0 {pt(cx + r, cy)}A{fmt(r)} {fmt(r)} 0 1 0 {pt(cx - r, cy)}Z")


# ----------------------------------------------------------------------------- letters
# style: W weight, cap "flat"|"round", gaps multiplier, Mw width of the capital M
def vstem(x_centre, y0, y1, S):
    h = S["W"] / 2
    if S["cap"] == "round":
        y0, y1 = y0 + h, y1 - h
    return stroke_d([line((x_centre, y0), (x_centre, y1))], S["W"], S["cap"])


def L_M(x0, S):
    W, h, Mw = S["W"], S["W"] / 2, S["Mw"]
    if S["cap"] == "round":
        c = lambda a, b: stroke_d([line((x0 + a[0], a[1]), (x0 + b[0], b[1]))], W, "round")
        m2 = Mw / 2
        parts = [c((h, TOP + h), (h, BASE - h)), c((Mw - h, TOP + h), (Mw - h, BASE - h)),
                 c((h, TOP + h), (m2, BASE - h)), c((m2, BASE - h), (Mw - h, TOP + h))]
        return " ".join(parts), Mw
    wd = W
    for _ in range(8):                                  # diagonal thickness depends on its own slope
        s = (Mw / 2 - wd / 2) / (BASE - TOP)
        wd = W / math.cos(math.atan(s))
    s = (Mw / 2 - wd / 2) / (BASE - TOP)
    yn = TOP + (Mw / 2 - wd) / s
    y1 = TOP + W / s
    xl = s * (BASE - TOP)
    p = [(0, BASE), (0, TOP), (wd, TOP), (Mw / 2, yn), (Mw - wd, TOP), (Mw, TOP), (Mw, BASE), (Mw - W, BASE),
         (Mw - W, y1), (Mw - xl, BASE), (xl, BASE), (W, y1), (W, BASE)]
    return polygon_d([(x0 + x, y) for x, y in p]), Mw


def bowl(x0, S):
    cx = x0 + 50
    return ring_d(cx, 110, 50, 50 - S["W"]), cx


def L_a(x0, S):
    h = S["W"] / 2
    d, cx = bowl(x0, S)
    return d + " " + vstem(cx + 50 - h, XT, BASE, S), 100


def L_g(x0, S):
    W, h = S["W"], S["W"] / 2
    d, cx = bowl(x0, S)
    sx, rr, yb = cx + 50 - h, 30, DESC - h
    y0 = XT + h if S["cap"] == "round" else XT
    chain = [line((sx, y0), (sx, yb - rr)), ("A", sx - rr, yb - rr, rr, 0, 90), line((sx - rr, yb), (sx - rr - 16, yb))]
    return d + " " + stroke_d(chain, W, S["cap"]), 100


def L_p(x0, S):
    h = S["W"] / 2
    d, cx = bowl(x0, S)
    return d + " " + vstem(x0 + h, XT, DESC, S), 100


def L_i(x0, S):
    return vstem(x0 + S["W"] / 2, XT, BASE, S), S["W"]


def L_r(x0, S):
    W, h = S["W"], S["W"] / 2
    y0 = XT + h if S["cap"] == "round" else XT
    rr = 31
    chain = [("A", x0 + h + rr, XT + h + rr, rr, 180, 270), line((x0 + h + rr, XT + h), (x0 + h + rr + 17, XT + h))]
    return (vstem(x0 + h, XT, BASE, S) + " " + stroke_d(chain, W, S["cap"]),
            h + rr + 17 + (h if S["cap"] == "round" else 0))


def L_y(x0, S):
    W, h = S["W"], S["W"] / 2
    if S["cap"] == "round":
        c0 = x0 + h
        c1 = c0 + 88
        yt, yb = XT + h, DESC - h
        left = stroke_d([line((c0, yt), (c0 + 44, yt + 88))], W, "round")
        right = stroke_d([line((c1, yt), (c1 - 0.5 * (yb - yt), yb))], W, "round")
        return left + " " + right, 88 + W
    wh = h / math.cos(math.atan(0.5))
    c0 = x0 + wh
    c1 = c0 + 88
    left = [(c0 - wh, XT), (c0 + wh, XT), (c0 + 44 + wh, XT + 88), (c0 + 44 - wh, XT + 88)]
    xb = c1 - 0.5 * (DESC - XT)
    right = [(c1 - wh, XT), (c1 + wh, XT), (xb + wh, DESC), (xb - wh, DESC)]
    return polygon_d(left) + " " + polygon_d(right), 88 + 2 * wh


STYLES = {
    "a-rounded": dict(name="A  Rounded", note="Soft round ends, medium weight. Closest to Google Sans.",
                      W=16, cap="round", gaps=1.0, Mw=150),
    "b-crisp": dict(name="B  Crisp", note="Flat ends, clean and confident. Current look + capital M.",
                    W=18, cap="flat", gaps=1.0, Mw=150),
    "c-light": dict(name="C  Light", note="Thin and airy, more elegant and editorial",
                    W=11, cap="flat", gaps=1.18, Mw=146),
    "d-bold": dict(name="D  Bold", note="Heavy and tightly spaced, strong at small sizes",
                   W=26, cap="flat", gaps=0.8, Mw=156),
}
GAPS = [16, 14, 22, 14, 14, 22, 4]        # M-a, a-g, g-p, p-i, i-a, a-r, r-y (outer edge to outer edge)


def wordmark(S):
    seq = [L_M, L_a, L_g, L_p, L_i, L_a, L_r, L_y]
    x, parts, dot = 0, [], None
    for k, fn in enumerate(seq):
        d, w = fn(x, S)
        if fn is L_i:
            dot = spark_pts(x + S["W"] / 2, 24, 28)
        parts.append(d)
        x += w + (GAPS[k] * S["gaps"] if k < len(GAPS) else 0)
    return " ".join(parts), dot, x


# ----------------------------------------------------------------------------- svg writing
def svg(w, h, title, body, vb=None):
    vb = vb or f"0 0 {w} {h}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{round(w)}" height="{round(h)}" role="img" '
            f'aria-labelledby="t"><title id="t">{title}</title>\n{body}\n</svg>\n')


def spark_d(pts):
    return "M" + " L".join(pt(x, y) for x, y in pts) + "Z"


def symbol_group(sym, eye, ink, gold, back=None):
    """`back` colours the back bird on its own (the piece that does not hold the sparkle)."""
    if back and sym.geom_type != "Polygon":
        front = [g for g in sym.geoms if Polygon(g.exterior).contains(eye.centroid)]
        rest = [g for g in sym.geoms if g not in front]
        g = (f'<path d="{poly_d(unary_union(rest))}" fill="{back}" fill-rule="evenodd"/>'
             f'<path d="{poly_d(unary_union(front))}" fill="{ink}" fill-rule="evenodd"/>')
    else:
        g = f'<path d="{poly_d(sym)}" fill="{ink}" fill-rule="evenodd"/>'
    if gold:
        g += f'<path d="{poly_d(eye, 0.05)}" fill="{gold}"/>'
    return g


def word_group(wd, dot, ink, gold, dx=0):
    t = f' transform="translate({fmt(dx)} 0)"' if dx else ""
    return f'<g{t}><path d="{wd}" fill="{ink}"/><path d="{spark_d(dot)}" fill="{gold or ink}"/></g>'


def lockups(sym, eye, S, ink, gold, bg=None):
    """Return (horizontal svg body+viewBox, stacked svg body+viewBox) for one wordmark style."""
    wd, dot, wmw = wordmark(S)
    asc = dot[0][1] - 0           # top of the sparkle's upper tip
    asc = min(y for _, y in dot)
    minx, miny, maxx, maxy = sym.bounds
    # horizontal: symbol spans sparkle tip to descender
    sh = DESC - asc
    s = sh / (maxy - miny)
    mv = lambda g, s, ox, oy: affinity.translate(affinity.scale(g, s, s, origin=(0, 0)), ox - minx * s, oy - miny * s)
    sw = (maxx - minx) * s
    gx = 56
    hv = (-8, asc - 8, sw + gx + wmw + 16, DESC - asc + 16)
    rect = lambda v: f'<rect x="{fmt(v[0])}" y="{fmt(v[1])}" width="{fmt(v[2])}" height="{fmt(v[3])}" fill="{bg}"/>' if bg else ""
    hbody = rect(hv) + symbol_group(mv(sym, s, 0, asc), mv(eye, s, 0, asc), ink, gold, gold) + word_group(wd, dot, ink, gold, sw + gx)
    # stacked
    top_h = 230
    s2 = top_h / (maxy - miny)
    sw2 = (maxx - minx) * s2
    wy = top_h + 70 - asc
    sv = (-24, -24, wmw + 48, wy + DESC + 48)
    sbody = (rect(sv) + symbol_group(mv(sym, s2, (wmw - sw2) / 2, 0), mv(eye, s2, (wmw - sw2) / 2, 0), ink, gold, gold)
             + f'<g transform="translate(0 {fmt(wy)})">{word_group(wd, dot, ink, gold)}</g>')
    vbs = lambda v: " ".join(fmt(x) for x in v)
    return (hbody, hv, vbs(hv)), (sbody, sv, vbs(sv)), (wd, dot, wmw, asc)


def write(name, text):
    (OUT / name).write_text(text)


def build(default="d-bold"):
    sym, eye = symbol()
    sym_f, (eye_f,) = fit(sym, extra=(eye,))
    write("symbol.svg", svg(256, 256, "Magpiary symbol", symbol_group(sym_f, eye_f, INK, GOLD, PINK)))
    write("symbol-black.svg", svg(256, 256, "Magpiary symbol, black", symbol_group(sym_f, eye_f, "#000000", None)))
    write("symbol-reversed.svg", svg(256, 256, "Magpiary symbol, reversed",
          f'<rect width="256" height="256" fill="{INK}"/>' + symbol_group(sym_f, eye_f, CREAM, GOLD, PINK)))
    ss, se = symbol(gap=12, off=34, eye_R=22, eye_dx=8, eye_dy=0, beak=36)
    ss_f, (se_f,) = fit(ss, margin=12, extra=(se,))
    write("symbol-small.svg", svg(256, 256, "Magpiary symbol, small-size cut", symbol_group(ss_f, se_f, "#000000", None)))

    opts = OUT / "wordmark-options"
    opts.mkdir(exist_ok=True)
    rows = []
    for key, S in STYLES.items():
        (hb, hv, hvb), (sb, sv, svb), (wd, dot, wmw, asc) = lockups(sym, eye, S, INK, GOLD)
        write_to = lambda n, t: (opts / n).write_text(t)
        write_to(f"{key}-horizontal.svg", svg(hv[2], hv[3], f"Magpiary horizontal, {S['name']}", hb, hvb))
        rows.append((S, svg(hv[2], hv[3], S["name"], hb, hvb), hv))
        if key == default:
            wvb = (-8, asc - 8, wmw + 16, DESC - asc + 16)
            wvs = " ".join(fmt(v) for v in wvb)
            write("wordmark.svg", svg(wvb[2], wvb[3], "Magpiary wordmark", word_group(wd, dot, INK, GOLD), wvs))
            write("wordmark-black.svg", svg(wvb[2], wvb[3], "Magpiary wordmark, black", word_group(wd, dot, "#000000", None), wvs))
            write("lockup-horizontal.svg", svg(hv[2], hv[3], "Magpiary logo, horizontal", hb, hvb))
            write("lockup-stacked.svg", svg(sv[2], sv[3], "Magpiary logo, stacked", sb, svb))
            (hbk, hvk, hvkb), (sbk, svk, svkb), _ = lockups(sym, eye, S, "#000000", None)
            write("lockup-horizontal-black.svg", svg(hvk[2], hvk[3], "Magpiary logo, horizontal, black", hbk, hvkb))
            (hbr, hvr, hvrb), (sbr, svr, svrb), _ = lockups(sym, eye, S, CREAM, GOLD, bg=INK)
            write("lockup-horizontal-reversed.svg", svg(hvr[2], hvr[3], "Magpiary logo, horizontal, reversed", hbr, hvrb))
            write("lockup-stacked-reversed.svg", svg(svr[2], svr[3], "Magpiary logo, stacked, reversed", sbr, svrb))

    # options sheet: one row per style
    uri = lambda s: "data:image/svg+xml;base64," + base64.b64encode(s.encode()).decode()
    rh, W_ = 190, 1200
    body = ""
    for i, (S, doc, hv) in enumerate(rows):
        y = 100 + i * (rh + 22)
        scale = 640 / hv[2]
        body += (f'<rect x="40" y="{y}" width="{W_ - 80}" height="{rh}" rx="18" fill="#fff" stroke="#e6dfd0"/>'
                 f'<image href="{uri(doc)}" x="70" y="{y + (rh - hv[3] * scale) / 2:.1f}" width="640" height="{hv[3] * scale:.1f}"/>'
                 f'<text x="760" y="{y + 70}" font-size="26" font-weight="700" fill="{INK}">{S["name"]}</text>'
                 f'<text x="760" y="{y + 102}" font-size="15" fill="#5a5547">{S["note"]}</text>')
    H_ = 100 + len(rows) * (rh + 22) + 10
    sheet = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_}" height="{H_}" viewBox="0 0 {W_} {H_}" '
             f'font-family="-apple-system,Helvetica,Arial,sans-serif"><rect width="{W_}" height="{H_}" fill="#FBF6EA"/>'
             f'<text x="40" y="52" font-size="30" font-weight="700" fill="{INK}">Magpiary wordmark options</text>'
             f'<text x="40" y="80" font-size="15" fill="#5a5547">Same symbol, same sparkle. Only the letter style changes.</text>{body}</svg>')
    (OUT.parent / "wordmark-options-v1.svg").write_text(sheet)
    print("ok")


if __name__ == "__main__":
    build()
