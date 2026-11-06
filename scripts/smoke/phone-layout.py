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

# pull to refresh
js = (src / "static/phone.js").read_text()
assert "__phonePull" in js and "location.reload()" in js, "pull to refresh missing"
assert ".ptr" in css, "pull indicator styles missing"
print("pull to refresh smoke: ok")

# search: the bar's Search opens the big search on any page (the top box is hidden on a phone)
assert "getElementById(\"searchform\")" in js and "form.click()" in js, "bar Search must open the big search"
assert "q.focus()" not in js.split("data-pbar-search")[1].split("data-pbar-more")[0], "bar Search must not focus the hidden box"
print("phone search smoke: ok")

# top bar: no shelf pill, no top search button, buttons pushed right, hub.css row break hidden
for needle in ("#shelfsw { display: none !important; }", ".sslot { display: none !important; }", ".top .bar::after { display: none; }", ".logo { margin-right: auto; }"):
    assert needle in css, "top bar rule missing: " + needle
print("phone top bar smoke: ok")

# Nest switches: one row each on a phone
assert ".nestpage .tgrow { grid-template-columns: minmax(0, 1fr); }" in css, "Nest switches must be one column"
print("phone nest switches smoke: ok")

# search on a phone: no home search box, big search pinned under the top bar, tabs pill waits for the tabs row
assert ".lhsearch { display: none !important; }" in css, "home search box must be hidden on a phone"
assert ".sover { padding-top: 84px;" in css, "big search must sit under the top bar"
ijs = (src / "static/indigo.js").read_text()
assert "box.offsetParent === null && prev" in ijs, "pill must follow the tabs row when the hero search is hidden"
print("phone search position smoke: ok")
