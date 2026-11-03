"""Render the extension's toolbar icons from the hub's magpie mark (src/magpiary/static/icon.svg): the mark on a white
rounded square, so it reads on light and dark toolbars. Run: uv run --with playwright python scripts/make_extension_icons.py"""
import re
import glob
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
svg = re.sub(r"<style>.*?</style>", "", (root / "src/magpiary/static/icon.svg").read_text()).replace('class="k"', 'fill="#111"')
out = root / "src" / "magpiary" / "extension" / "icons"
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    # uses Playwright's own browser, or one you name in MAGPIARY_CHROMIUM
    path = os.environ.get("MAGPIARY_CHROMIUM") or next(iter(sorted(glob.glob(
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))), None)
    browser = p.chromium.launch(executable_path=path)
    for size in (16, 32, 48, 128):
        page = browser.new_page(viewport={"width": 300, "height": 300}, device_scale_factor=1)
        pad = round(size * 0.08)
        page.set_content(f'<body style="margin:0;background:transparent"><div style="width:{size}px;height:{size}px;box-sizing:border-box;'
                         f'padding:{pad}px;background:#fff;border-radius:{round(size * 0.22)}px">'
                         f'{svg.replace("<svg ", f"<svg width={chr(34)}{size - 2 * pad}{chr(34)} height={chr(34)}{size - 2 * pad}{chr(34)} ", 1)}</div></body>')
        page.locator("div").first.screenshot(path=str(out / f"{size}.png"), omit_background=True)
    browser.close()
