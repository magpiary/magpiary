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
assert "safe-area-inset-top, 0px) + 10px); padding-bottom: 8px" in css, "big search must sit over the top bar"
ijs = (src / "static/indigo.js").read_text()
assert "box.offsetParent === null && wc" in ijs and "natural < 10" in ijs, "pill must follow the tabs row when the hero search is hidden"
print("phone search position smoke: ok")

# home top: no heading block, tabs pulled up, logo shows its name
assert ".lhero:not(.lhempty) { display: none !important; }" in css, "heading block must be hidden on a phone"
assert ".top .bar > .logo { font-size: 22px;" in css, "logo name must show on a phone"
print("phone home top smoke: ok")

# tabs and pill: nothing sticky until the pill shows; then the pill alone sticks, in one row; no gap under the top bar
assert "html:not(.lhslim):has(#wallctl) .top { position: static !important;" in css, "top bar must not be sticky on the library"
assert "html:has(.lhero) #wallctl { position: relative !important; top: auto !important; }" in css, "tabs must not be sticky before they become the pill"
assert "html.lhslim:has(.lhero) #wallctl { position: sticky !important;" in css and "html.lhslim.navhid:has(.lhero) #wallctl { top:" in css, "the pill must stick, under the top bar when it returns"
assert 'gone && !was && box.offsetParent === null) root.classList.add("navhid")' in ijs, "top bar must start hidden when the pill appears"
assert "html.lhslim #wallctl .ctrl1 { flex-wrap: nowrap !important;" in css, "the pill must be one row"
assert ".wrap:has(> #wallctl):has(> .lhero:not(.lhempty)) { padding-top: 0; }" in css, "gap under the top bar must go"
print("phone tabs and pill smoke: ok")

# filter/select flat at the top, no tile-size button, Medium always, pill labels 12px, pile names get a whole line
assert "html:not(.lhslim) #wallctl .ctrl1 :is(.ibtn, .tbtn, summary, .tools button) { background: none !important;" in css, "flat icons"
assert "#wallctl .sizes { display: none !important; }" in css, "tile size button must be hidden"
assert "html.lhslim #wallctl .views a { font-size: 12px; }" in css, "pill labels 12px"
assert 'root.dataset.size = "m"' in js, "phone must keep Medium tiles"
assert ".pile .lt { display: contents; }" in css and ".piles { grid-template-columns: repeat(2, minmax(0, 1fr));" in css, "piles: name line then labels"
print("phone filter/size/pill/piles smoke: ok")

# filter panel stays on screen, Digest+Settings are one dark pill, pages cross-fade, swipe between the three views, no explanations
assert "details.fmenu > .pop.fpanel {" in css and "position: absolute; left: 0; right: 0; width: auto;" in css, "filter panel must fit the screen"
assert ".ubtn.dgbtn { border-radius: 999px 0 0 999px;" in css and ".ubtn.setbtn { border-radius: 0 999px 999px 0; }" in css, "top icons must be one pill"
assert "pfade-out" in js and "@keyframes pfadein" in css, "cross-fade between pages missing"
assert "__phoneSwipe" in js and "touchmove" in js.split("__phoneSwipe")[-1], "swipe between views missing"
assert "translateX" not in js.split("Swipe left/right")[1].split("Changing the view")[0], "swipe must only fade, not slide"
assert ".pilebar, .pagenote { display: none !important; }" in css, "Piles/Boards explanations must go"
assert 'class="psr"' not in (src / "hub_wall.py").read_text() and 'ibtn pregroup' in (src / "hub_wall.py").read_text(), "Regroup icon button missing"
assert "html.lhslim #wallctl .views a { padding: 0 12px; }" in css, "pill tab padding"
print("phone filter/swipe/fade/top-icons smoke: ok")

# swipe is a plain cross-fade; changing view does not bring the top bar back; the tab line is re-measured; board names show
assert "html.pswipe #view > :not(#wallctl):not(.lhero) { opacity: 0 !important;" in css, "swipe fade rule missing"
assert "window.__phoneHold = performance.now()" in js and "window.__phoneHold > performance.now()" in ijs, "view change must not bring the top bar back"
assert "__phoneLine" in js, "tab underline must be re-measured"
assert ".bpile .folder .flap { height: auto !important;" in css, "board name must show"
print("phone swipe fade / nav hold / board names smoke: ok")

# post view: one-row toolbar, Ask hidden, video capped, tab strip fades at the edge with more tabs
assert ".crumbbar { flex-wrap: nowrap !important;" in css, "post toolbar must be one row"
assert ".pvask, .pvactions:has(> .pvask:only-child) { display: none !important; }" in css, "Ask chip must be hidden on the phone"
assert ".cardm.pagemode .stage { max-height: min(62svh, 520px) !important;" in css, "post video must be capped"
assert ".tabs.pvtabs.pmoreR {" in css and "pmoreR" in js, "post tab strip needs an edge fade"
print("phone post view smoke: ok")
