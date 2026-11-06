"""Phone layout check: phone.css is served and linked, keeps inputs at 16px and has no sideways-overflow rule missing.
Run: uv run python scripts/smoke/phone-layout.py   (no browser needed; the visual check is done on a phone)."""
import re, sys
from pathlib import Path
css = (Path(__file__).resolve().parents[2] / "src/magpiary/static/phone.css").read_text()
from magpiary import ui
assert "phone.css" in ui.STATIC_FILES, "phone.css not registered"
assert "overflow-x: clip" in css, "sideways scroll guard missing"
assert re.search(r"font-size:\s*16px\s*!important", css), "16px input rule missing"
assert css.count("{") == css.count("}"), "unbalanced braces in phone.css"
print("phone layout smoke: ok")

# bottom bar: markup in the shell, script registered, desktop keeps it hidden
src = Path(__file__).resolve().parents[2] / "src/magpiary"
assert 'class="pbar"' in (src / "hub_wall.py").read_text(), "phone bar markup missing"
assert "phone.js" in ui.STATIC_FILES and (src / "static/phone.js").exists(), "phone.js missing"
assert ".pbar { display: none; }" in css, "bar must be hidden on desktop"
print("phone bar smoke: ok")
