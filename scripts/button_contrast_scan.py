"""Every button on every page of a running hub, in every state, light and dark: text against its background (WCAG 2.2).

Fails (exit 1) when a visible, enabled button's text is below 4.5:1 (3:1 for large text and icon-only buttons).
Needs a hub on throwaway data (never the live library) and Playwright with a Chromium:
    uv run --with playwright python scripts/button_contrast_scan.py http://localhost:8791 [--json out.json] [--shots dir]
States checked: rest, hover, active, keyboard focus, and the disabled look (reported, not failed: disabled controls are exempt).
Elements that are in the page but hidden (dialogs, templates) are checked too and reported as "hidden" failures.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
JS = (HERE / "button_contrast_scan.js").read_text()
FIXTURES = (HERE / "button_contrast_fixtures.js").read_text()


def used_classes():
    """Every word that appears in the app's markup and scripts: a CSS rule for a class outside this set styles nothing."""
    import re
    root = HERE.parent
    words = set()
    for path in [*(root / "src" / "magpiary").rglob("*.py"), *(root / "src" / "magpiary" / "static").glob("*.js"), *(root / "packaging" / "app").rglob("*.html"), *(root / "packaging" / "app").rglob("*.js")]:
        words.update(re.findall(r"[A-Za-z_][\w-]*", path.read_text(errors="ignore")))
    return sorted(words)
PAGES = ["/", "/?view=piles", "/?view=boards", "/?shelf=archive", "/?shelf=trash", "/?links=1", "/pile/1", "/item/1", "/item/2", "/item/3",
         "/add", "/ask", "/digest", "/nest", "/help", "/doctor", "/map",
         "/settings", "/settings/profile", "/settings/ai", "/settings/appearance", "/settings/ask", "/settings/phones",
         "/settings/privacy", "/settings/storage", "/settings/agents",
         "/welcome", "/welcome/browser", "/welcome/phone", "/welcome/reading", "/welcome/share"]
# the hub offers two themes (ui.THEMES): dark and indigo; the :root light tokens in hub.css are not reachable
THEMES = ["dark", "indigo"]
STATES = ["rest", "hover", "active", "focus"]


SETTLE_JS = """() => { let t = 0; document.querySelectorAll('button, a.btn, summary, [role=button]').forEach((e) => { for (let x = e; x; x = x.parentElement) t += parseFloat(getComputedStyle(x).opacity); }); return Math.round(t * 1000); }"""


def settle(page, limit=8000):
    """Wait until nothing is fading in: the summed opacity of every button and its ancestors stops changing."""
    waited, last = 0, None
    while waited < limit:
        page.wait_for_timeout(500)
        waited += 500
        now = page.evaluate(SETTLE_JS)
        if now == last and waited >= 1000:
            return
        last = now


def measure(page, cdp, state):
    """Force the state on every marked button at once, then read every computed colour."""
    page.evaluate(JS)  # marks the elements
    if state != "rest":
        doc = cdp.send("DOM.getDocument", {"depth": 0})
        ids = cdp.send("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "[data-ax]"})["nodeIds"]
        forced = {"hover": ["hover"], "active": ["hover", "active"], "focus": ["focus", "focus-visible"]}[state]
        for nid in ids:
            try:
                cdp.send("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": forced})
            except Exception:
                pass
    rows = page.evaluate(JS)
    if state != "rest":
        for nid in ids:
            try:
                cdp.send("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": []})
            except Exception:
                pass
    return rows


def main() -> int:
    args = sys.argv[1:]
    base = args[0]
    out = args[args.index("--json") + 1] if "--json" in args else None
    pages = args[args.index("--pages") + 1].split(",") if "--pages" in args else (["/help"] if "--matrix" in args else PAGES)
    matrix = "--matrix" in args  # also build every button/context combination the CSS styles (see button_contrast_fixtures.js)
    found, total = [], 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in (args[args.index("--themes") + 1].split(",") if "--themes" in args else THEMES):
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
            page = ctx.new_page()
            cdp = ctx.new_cdp_session(page)
            cdp.send("DOM.enable")
            cdp.send("CSS.enable")
            for path in pages:
                resp = page.goto(base + path, wait_until="domcontentloaded")
                if not resp or resp.status >= 400:
                    continue
                page.evaluate(f"document.documentElement.dataset.theme = '{scheme}'")  # the hub sets its own theme; the OS scheme is ignored
                settle(page)  # entrance animations (GSAP) finish
                page.add_style_tag(content="*, *::before, *::after { animation: none !important; transition: none !important; }")
                if matrix:
                    print(f"  {scheme} {path}: {page.evaluate("u => (" + FIXTURES + "\n)(u)", used_classes())} fixtures", flush=True)
                page.evaluate("window.__axn = 0; document.querySelectorAll('[data-ax]').forEach(e => delete e.dataset.ax)")
                seen = {}
                for state in STATES:
                    for row in measure(page, cdp, state):
                        total += 1
                        if row["ratio"] is not None and row["ratio"] < row["need"]:
                            key = (path, row["ax"], state)
                            found.append({**row, "page": path, "scheme": scheme, "state": state})
                # the disabled look: switch every enabled button off, read, switch back
                page.evaluate("document.querySelectorAll('button:not(:disabled)').forEach(b => { b.dataset.wasOn = '1'; b.disabled = true; })")
                for row in measure(page, cdp, "rest"):
                    if row["disabled"] and row["ratio"] is not None and row["ratio"] < 3:
                        found.append({**row, "page": path, "scheme": scheme, "state": "disabled-look", "info": True})
                page.evaluate("document.querySelectorAll('button[data-was-on]').forEach(b => b.disabled = false)")
            ctx.close()
        browser.close()
    real = [f for f in found if not f.get("info") and not f["disabled"]]
    if out:
        Path(out).write_text(json.dumps(found, indent=1))
    groups = {}
    for f in real:
        k = (f["scheme"], f["state"], f.get("fx") or f["cls"] or f["path"].split(" > ")[-1], f["fg"], f["bg"], "visible" if f["rendered"] else "hidden")
        g = groups.setdefault(k, {"ratio": f["ratio"], "need": f["need"], "n": 0, "pages": set(), "ex": f["text"], "path": f["path"]})
        g["n"] += 1
        g["pages"].add(f["page"])
    print(f"checked {total} button states; {len(real)} failing ({len(groups)} distinct)")
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["ratio"]):
        print(f"{g['ratio']}:1 (needs {g['need']}) {k[0]} {k[1]} {k[5]} .{k[2]} {k[3]} on {k[4]}  x{g['n']} “{g['ex']}” pages={sorted(g['pages'])[:4]}")
    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main())
