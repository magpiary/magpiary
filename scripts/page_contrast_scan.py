"""Scan every main page of a running hub for text below WCAG contrast (4.5:1, or 3:1 for large text), light and dark.

Needs a hub to look at (use a scratch copy, never the live library) and Playwright with a Chromium:
    uv run --with playwright python scripts/page_contrast_scan.py http://localhost:8791 [path-to-chromium]
Known false positives to ignore: hidden tooltips (.ttip, 1:1), the idle status strip ("Waiting"), the hover-only
"Remove from pile" button and the 0:00 time stamps in the video scrubber.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["/", "/?view=piles", "/?view=boards", "/board/coffee", "/pile/3", "/nest", "/settings", "/help", "/digest",
         "/item/52", "/add"]
script = (Path(__file__).parent / "page_contrast_scan.js").read_text()
base = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=sys.argv[2]) if len(sys.argv) > 2 else p.chromium.launch()
    for scheme in ("light", "dark"):
        page = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme=scheme).new_page()
        for path in PAGES:
            page.goto(base + path, wait_until="networkidle")
            page.wait_for_timeout(1500)
            result = page.evaluate(script)
            print(f"{scheme:5} {path:16} checked {result['checked']:4}  failing {len(result['failing'])}")
            for key, v in result["failing"]:
                print(f"       {v['ratio']}:1 x{v['n']} {key} “{v['ex']}”")
    browser.close()
