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
assert "calc(85lvh * var(--mar, 100))" in css, "media capped at 85% tall"
assert ".tabs.pvtabs.pmoreR {" in css and "pmoreR" in js, "post tab strip needs an edge fade"
print("phone post view smoke: ok")

# post view round 2: media 90% wide (cap 75%), toolbar back/open/More, swipe + edge arrows, link buttons one line with logos,
# tab strip sideways only, pop-ups not held invisible by the page fade, Back keeps the filter, pull to refresh on a post
assert "calc(85lvh * var(--mar, 100))" in css, "media capped at 85% tall"
assert "html:has(.postpage) #top { display: none !important; }" in css, "no logo bar on a post"
assert "padding: 0 12px !important; gap: 10px; align-items: center; }" in css, "link buttons centred vertically"
assert ".crumbbar .pacts > :is([data-pagenav], .rb.off, .pgpos, [data-addboard], [data-copylink]) { display: none !important; }" in css, "toolbar icons"
assert ".crumbbar::before { display: none !important; }" in css, "no fade behind the toolbar"
assert 'class="mi pmi" data-copylink=' in (src / "hub_card.py").read_text(), "Copy link must be in the More menu"
assert "pedge" in js and 'a[data-pagenav][aria-label="' in js and "touchend" in js.split("Post view: swipe left/right")[-1], "post swipe + edge arrows"
assert ".pvactions { display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr));" in css, "equal-width link buttons"
assert ".pvactions .pvprimary > .fav { flex: none;" in css and ".pvactions .pvprimary.find::before" in css, "logos on link buttons"
assert ".tabs.pvtabs { overflow-x: auto; overflow-y: hidden; overscroll-behavior-x: contain;" in css, "tab strip sideways only"
assert "body > :is(#top, #view) { animation: pfadein" in css, "page fade must not hold body pop-ups at opacity 0 (board chooser)"
assert 'trail = [("Library", frm if frm.startswith("/?") else "/")]' in (src / "hub_card.py").read_text(), "Back must keep the filter"
assert r'/^\/item\/\d+/.test(location.pathname)' in js, "pull to refresh on a post"
print("phone post view round 2 smoke: ok")
assert "mag-backing" not in js, "the old Back note is gone"
print("phone post back smoke: ok")
assert "top: calc(env(safe-area-inset-top, 0px) + 6px) !important; padding-top: 6px;" in css and "box-shadow: 0 0 0 100vmax var(--fade-0, #101015) !important;" in css, "pinned post tabs: higher, own full-bleed background"
print("phone post tabs sticky smoke: ok")
assert ".pscroll > [data-pane] { min-height: calc(100svh - 300px); }" in css and "top: -500px" in css, "short tabs keep room; background reaches over the top"
assert "function pin(wasStuck)" in js, "switching tabs while stuck must keep the bar pinned"
print("phone post tab switch smoke: ok")
assert "calc(85lvh * var(--mar, 100))" in css, "player width: 8px inside the screen, height cap 85% of the large viewport"
assert "padding: 0 !important; width: 44px; justify-content: center;" in css, "back arrow centred"
assert ".cardm.pagemode .stage .pvautozone { position: absolute; z-index: 21;" in css and "insertAdjacentElement" not in js, "autoplay stays in the player, placed beside Back by CSS"
assert 'webkitEnterFullscreen' in js and ".stage.pfs" in css and '.pvb[data-pv="fit"] { display: none; }' in css, "full screen fallback; fit button hidden"
print("phone player round 3 smoke: ok")
assert "location.replace(href)" in js and "history.go(" not in js and "mag-listpos" in js, "Back must go to the list address, not count history entries"
assert "if (vid && vid.paused) { const p = vid.play();" in js, "Full screen must also start the video"
print("phone back/fullscreen round 4 smoke: ok")
assert ".postpage > .crumbbar { position: absolute !important; top: 0;" in css and "html:has(.cardm .stage.pvplaying) .postpage > .crumbbar { opacity: 0; }" in css, "buttons over the media at the top, hidden while playing"
print("phone post overlay round 5 smoke: ok")
assert "margin-top: 0; border-radius: 20px; background: transparent; }" in css and "border-radius: 999px 0 0 999px !important; margin-right: 0;" in css, "rounded media corners; Back+Autoplay one pill"
print("phone post pill round 6 smoke: ok")
assert "drop-shadow(0 1px 3px rgb(0 0 0 / .65))" in css and ".postpage > .crumbbar { background: none !important; padding-bottom: 12px !important; }" in css, "plain white buttons with a soft shadow"
print("phone post plain buttons round 7 smoke: ok")
assert "backdrop-filter: none !important; -webkit-backdrop-filter: none !important;" in css, "Back has no blur background"
print("phone post buttons round 8 smoke: ok")
assert ".cardm.pagemode .stage .pvautozone { left: 84px;" in css and ".postpage > .crumbbar .pgback::after" in css, "Autoplay right of Back; large Back hit area"
print("phone post buttons round 9 smoke: ok")
assert ".cardm.pagemode .stage .pvautozone { left: 62px; }" in css and "padding-left: 8px !important; padding-right: 8px !important;" in css and ".pgback::after { border-radius: 999px; }" in css, "buttons near the edges, round tap shapes"
print("phone post buttons round 10 smoke: ok")
assert ".cardm.pagemode .stage .pvautozone { left: 66px;" in css and "background: rgb(250 250 252 / .74)" not in css and "left: var(--cl, calc(-1 * max(var(--pad, 16px), 24px))) !important;" in css, "equal 12px gaps; right pill stays dark"
print("phone post buttons round 11 smoke: ok")
assert ":root[data-theme] .postpage :is(.pvpile, .pvaddbtn) { display: inline-flex; align-items: center;" in css, "pile pill label centred"
print("phone post audit smoke: ok")
assert ".postpage .frow > small { font-size: 12px; }" in css and "padding-block: 10px; margin-block: -10px;" in css, "post page: bigger hit areas, no text under 12px in labels"
print("phone post hit areas smoke: ok")
assert '"--cw"' in js and "sr.width" in js, "button row aligned to the media's own width"
print("phone post width/row alignment smoke: ok")
assert ".cardm.pagemode .pscroll > [data-pane] { padding-bottom: 170px; }" in css and '.cardm.pagemode .pscroll { padding-bottom: 0 !important; }' in css, "tab bar container reaches the page end"
print("phone post sticky container smoke: ok")
assert 'nav.classList.add("pfix")' in js and ".tabs.pvtabs.pfix { position: fixed !important;" in css, "tab strip is pinned with position fixed (immune to iOS rubber-banding)"
print("phone post pinned tabs smoke: ok")
assert "html::before { content: \"\"; position: fixed; left: 0; right: 0; top: -500px;" in css, "solid cap behind the status bar on every page"
print("phone post status-bar cap smoke: ok")
assert ".label .m .kind, .mx .kind, .bcard .kind { font-size: 12px; }" in css and ".avatar.mini > span { font-size: 10.5px; }" in css, "small text on the home screen"
print("phone home small text smoke: ok")
assert 'body[data-page="help"] em { font-size: 12px; }' in css, "Help small text"
print("phone help small text smoke: ok")
assert ".wrap > .sec > form:not(.sizes) { order: 3;" in css and ".sq .quote small { font-size: 12px; }" in css, "search results header and label"
print("phone search results smoke: ok")
assert '.sover .sbig kbd::after { content: "Close";' in css and '".sover .sbig kbd"' in js, "big search Close button"
print("phone big search close smoke: ok")
assert ".setnav.pmoreR {" not in css, "Settings strip replaced by the two-layer list"
print("phone settings strip smoke: ok")

# Settings in two layers on the phone: the list of sections, each section on its own with a Back link; Privacy is a normal row
hs = (ROOT / "src/magpiary/hub_settings.py").read_text() if "ROOT" in globals() else open("src/magpiary/hub_settings.py").read()
assert 'setlayout{" setroot" if root else ""}' in hs and 'class="setback" href="/settings"' in hs and 'setsech">Security' in hs, "settings two layers markup"
assert ".setlayout.setroot .setpane, .setlayout:not(.setroot) .setside" in css, "settings list/section switch"
assert ".setcard::after, .setpriv::after" in css and ".setpane .info .ttip { position: fixed;" in css, "settings rows chevron + tip card"
assert ".setback, .setsupport { display: none; }" in css.split("@media")[0], "phone-only settings bits hidden on the Mac"
print("phone settings two-layer smoke: ok")
assert '".setpane .info.open"' in js and ".setpane .info.open .ttip { opacity: 1; }" in css, "settings tip opens on tap"
assert ".setpane form.picks { grid-template-columns: repeat(auto-fit, minmax(104px, 1fr))" in css and ".setpane .srow > .src:has(> form > .sw:only-of-type)" in css, "settings pickers fill the width, lone switch at the row's right"
print("phone settings sections smoke: ok")
hubjs = open("src/magpiary/static/hub.js").read()
assert '$(".setlayout", view).className = $(".setlayout", fresh).className' in hubjs, "Settings swap keeps list/section class in step (rows open)"
assert "html:has(.setlayout) #top { display: none !important; }" in css and "border-radius: 0 !important; border: 0 !important; border-bottom" in css, "Settings: no top bar, flat rows"
print("phone settings open/flat smoke: ok")
assert ".setpriv > span:not(.seticon) > :is(b, small) { grid-column: auto !important;" in css and ".setnav > .setcard:has(+ .setnavh)" in css, "Privacy row left-aligned like the rest; last row of a group has no line"
print("phone settings last-row/privacy smoke: ok")
assert ".setpane .srow:not(.addrow, .pfull, .rstack) { display: flex !important;" in css and ".setpane .engctl { display: flex !important;" in css, "settings sections: flat flex rows, controls under the text"
assert ".setpane .segbar { display: flex !important; flex-wrap: nowrap !important;" in css and ".setpane .deepengine { display: grid !important;" in css, "settings segmented controls and engine pickers fit the screen"
print("phone settings flat-rows smoke: ok")
assert ".setpane .srow .sw { position: absolute !important; right: 0; top: 14px;" in css and "details.menu > .pop { position: fixed !important; left: 16px !important;" in css, "settings: switch always top right, menus on screen"
assert "line-clamp: 2" in css and "Settings: explanations are clamped" in js, "settings: explanations clamped to two lines, tap opens"
print("phone settings column/menu/clamp smoke: ok")
