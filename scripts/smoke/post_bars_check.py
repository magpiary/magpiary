"""The post view's two sticky bars never let the page show through, and match the page behind them.
Usage: post_bars_check.py BASE_URL THEME [--shots DIR] [--label NAME]   (hub from post_bars_hub.py; Playwright with Chromium)
Checks, for the long and the short post, on every tab, at the top, mid-scroll and the bottom, at wide and narrow desktop widths:
  1. the post's top bar: with the post's content hidden the bar's pixels equal the same pixels with the content showing (nothing passes through),
     and equal the bare page behind it (no darker band);
  2. the tab row: the same test over its box with the pane text hidden; its fill (class "stuck") is on only while the row is stuck under the bar,
     it is the post surface colour (--bg) then, and it has no fill in its place in the flow."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

base, theme = sys.argv[1].rstrip("/"), sys.argv[2]
shots = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None
label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "shot"
if shots:
    shots.mkdir(parents=True, exist_ok=True)
fails, checked = [], 0
HIDE = "<style id=hide>.cardm.pagemode, .postpage > :not(.crumbbar) { visibility: hidden !important; }</style>"
HIDE_PANES = "<style id=hidep>.cardm.pagemode .pscroll > :not(.tabs), .cardm.pagemode .vid { visibility: hidden !important; }</style>"
NOFILL = "<style id=nofill>.crumbbar::before { display: none !important; }</style>"


def differ(a, b, tol=0):
    """Pixels that differ between two same-size PNGs (bytes), by more than tol on any channel."""
    from PIL import Image, ImageChops
    import io
    ia, ib = Image.open(io.BytesIO(a)).convert("RGB"), Image.open(io.BytesIO(b)).convert("RGB")
    box = ImageChops.difference(ia, ib).point(lambda v: 255 if v > tol else 0).getbbox()
    return box


def mask_controls(pg, sel):
    """Boxes (page px) of the bar's buttons and text, which are in both pictures but anti-alias the same: not masked; returns nothing."""
    return None


with sync_playwright() as p:
    br = p.chromium.launch()
    for width in (1400, 900):
        pg = br.new_page(viewport={"width": width, "height": 800}, reduced_motion="reduce")
        for item in (1, 2):
            pg.goto(f"{base}/item/{item}")
            pg.wait_for_selector(".crumbbar")
            pg.wait_for_timeout(1200)
            tabs = pg.eval_on_selector_all("[data-tab]:not(.off)", "els => els.map(e => e.dataset.tab)")
            for tab in tabs:
                pg.evaluate(f"document.querySelector('[data-tab=\"{tab}\"]').click()")
                pg.wait_for_timeout(150)
                height = pg.evaluate("document.documentElement.scrollHeight")
                for y in (0, 300, 900, 1600, height):
                    pg.evaluate(f"window.scrollTo(0, {y})")
                    pg.wait_for_timeout(450)
                    tag = f"{theme}-w{width}-i{item}-{tab}-y{y if y != height else 'end'}"
                    st = pg.evaluate("""() => { const t = document.querySelector('.tabs.pvtabs'), c = document.querySelector('.crumbbar');
                        const tr = t.getBoundingClientRect(), cr = c.getBoundingClientRect(), z = getComputedStyle(t);
                        return {stuck: t.classList.contains('stuck'), bg: z.backgroundColor, bgvar: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),
                                body: (() => { const m = document.createElement('i'); m.style.color = getComputedStyle(document.documentElement).getPropertyValue('--bg'); document.body.append(m); const v = getComputedStyle(m).color; m.remove(); return v; })(),
                                tTop: tr.top, tBot: tr.bottom, tLeft: tr.left, tW: tr.width, cBot: cr.bottom, cTop: cr.top, vh: innerHeight, pos: z.position} }""")
                    checked += 1
                    # the tab row is stuck exactly when it has reached the line under the bar
                    reached = st["tTop"] <= st["cBot"] + 1.5 and st["tBot"] > 0
                    if st["pos"] == "sticky" and reached != st["stuck"] and abs(st["tTop"] - st["cBot"]) > 3:
                        fails.append(f"{tag}: stuck={st['stuck']} but tab top {st['tTop']:.1f} vs bar bottom {st['cBot']:.1f}")
                    if st["stuck"] and st["bg"] != st["body"]:
                        fails.append(f"{tag}: stuck fill {st['bg']} is not the post surface {st['body']}")
                    if not st["stuck"] and st["bg"] != "rgba(0, 0, 0, 0)":
                        fails.append(f"{tag}: row not stuck but has a fill {st['bg']}")
                    if st["stuck"] and abs(st["tTop"] - st["cBot"]) > 1.5:
                        fails.append(f"{tag}: stuck row at {st['tTop']:.1f}, bar ends at {st['cBot']:.1f}: a gap or an overlap")
                    # 1: the bar
                    clip = {"x": 0, "y": 0, "width": width, "height": max(1, st["cBot"])}
                    # leave out the nav strip when it is shown above: it has its own fill and is not under test
                    full = pg.screenshot(clip=clip)
                    pg.add_style_tag(content=HIDE[len("<style id=hide>"):-len("</style>")])
                    bare = pg.screenshot(clip=clip)
                    pg.add_style_tag(content=NOFILL[len("<style id=nofill>"):-len("</style>")])
                    page = pg.screenshot(clip=clip)
                    if shots and (tag.endswith("-sum-y900") or tag.endswith("-tr-yend")):
                        pg.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('visibility: hidden !important') || s.textContent.includes('.crumbbar::before { display: none')) s.remove(); })")
                        pg.screenshot(path=str(shots / f"{label}-{tag}.png"), clip={"x": 0, "y": 0, "width": width, "height": 320})
                    pg.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('visibility: hidden !important') || s.textContent.includes('.crumbbar::before { display: none')) s.remove(); })")
                    if differ(full, bare):
                        fails.append(f"{tag}: the post's content shows through the top bar")
                    if differ(bare, page, tol=0):
                        fails.append(f"{tag}: the top bar's fill is not the page behind it")
                    # 2: the tab row (only when on screen)
                    if st["tBot"] > 0 and st["tTop"] < st["vh"]:
                        c2 = {"x": st["tLeft"], "y": max(0, st["tTop"]), "width": st["tW"], "height": max(1, min(st["tBot"], st["vh"]) - max(0, st["tTop"]))}
                        if st["stuck"]:
                            f2 = pg.screenshot(clip=c2)
                            pg.add_style_tag(content=HIDE_PANES[len("<style id=hidep>"):-len("</style>")])
                            b2 = pg.screenshot(clip=c2)
                            pg.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('visibility: hidden !important')) s.remove(); })")
                            if differ(f2, b2):
                                fails.append(f"{tag}: text shows through the stuck tab row")
        pg.close()
    br.close()
print(f"checked {checked} scroll positions ({theme})")
for f in fails:
    print("FAIL", f)
sys.exit(1 if fails else 0)
