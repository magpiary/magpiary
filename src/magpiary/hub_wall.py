"""The top bar and the wall (M7a, C1+), mixed into Hub: Everything in time sections (Today, This week, then by
month), Piles, search with the matching line on each tile, Archive and Trash, and adding a post by its link.

Tiles carry what hub.js needs for motion and previews (a stable flip id, a version that changes when the tile
would look different, the video and where its first key moment is, the photos). Long walls come in pages:
`?part=N` returns the next sections alone, which hub.js appends as you scroll."""

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from magpiary import keys as keyring
from magpiary import modes, spotlight, ui
from magpiary import related as rel
from magpiary.activity import STEPS
from magpiary.brain import TYPE_NAMES
from magpiary.query import keep, understand
from magpiary.queuepage import REASONS, when
from magpiary.store import TRASH_DAYS
from magpiary.web import Response, e

SHELF_NAMES = {"inbox": "Library", "archive": "Archive", "trash": "Trash"}
ERRORS = {"unsupported": "That does not look like a link to a post.", "empty": "Paste a link first."}
PAGE = 60  # tiles per part of a long wall
WORKING = {"fetch": "Fetching…", "download": "Downloading…", "transcribe": "Listening…", "frames": "Looking…",
           "summary": "Writing the summary…", "links": "Finding links…", "screen": "Reading text…"}

# a small magpie on its nest, for empty states (drawn with currentColor so it follows the theme)
MAGPIE = ('<svg class="emptyart" viewBox="0 0 120 90" aria-hidden="true"><path d="M14 66q46 14 92 0q-6 22-46 22T14 66z" '
          'fill="currentColor" opacity=".18"/><path d="M22 70q38 9 76 0M30 77q30 6 60 0" stroke="currentColor" opacity=".3" '
          'fill="none" stroke-width="2" stroke-linecap="round"/><ellipse cx="62" cy="50" rx="20" ry="14" fill="currentColor"/>'
          '<path d="M78 46q16-6 26-20q-4 16-18 26z" fill="currentColor"/><circle cx="46" cy="38" r="10" fill="currentColor"/>'
          '<path d="M36 38l-10 3 10 2z" fill="currentColor"/><path d="M52 52q10 6 22 2" stroke="var(--bg)" stroke-width="3" '
          'fill="none" stroke-linecap="round"/><circle cx="44" cy="36" r="2" fill="var(--bg)"/>'
          '<circle cx="88" cy="20" r="3" fill="var(--t-design)"/></svg>')

FEATURE_MIN = 12  # saves before the wall has a Featured area
FEATURE_NEW = {"s": 10, "m": 6, "l": 6}  # newest saves in Featured, by tile size: exactly what fits in two rows. Never hidden
# with CSS: a post Featured leaves out stays in its section below (CSS once hid 7-10 at medium and large, so they were nowhere)
BIG_EVERY = 12  # one big tile (2x2) about every this many posts, in the sections below Featured
BIG_MIN = 12  # a section needs this many posts before it gets one
FEATURE_PAST_DAYS = 7  # how old "from your past" means


def empty_state(title: str, line: str, action: str = "") -> str:
    return (f'<div class="empty"><img class="ebird" src="{ui.art("land-c")}" alt="">{MAGPIE}<b>{e(title)}</b><p>{line}</p>'
            + (f'<div class="row" style="justify-content:center">{action}</div>' if action else "") + "</div>")


class WallPages:
    """Needs Hub's store, activity, csrf, shell, thumb_url, has_summaries and related_library."""

    # ---- the top bar -----------------------------------------------------------------------

    def top_bar(self, q: str = "", shelf: str = "", active: str = "") -> str:
        counts = self.store.hub_counts()["shelves"]
        shelves = "".join(
            f'<a href="{"/" if s == "inbox" else "/?shelf=" + s}" data-shelf="{s}" class="{"on" if s == shelf else ""}'
            f'{"" if s == "inbox" else " ishelf"}"{" aria-current=page" if s == shelf else ""}'
            + ("" if s == "inbox" else f' aria-label="{name}" title="{name}"') + ">"
            + (name if s == "inbox" else ui.icon(s))  # Library is the main place; Archive and Trash are quiet icons (owner, 29 Oct)
            + ("" if s == "inbox" else f'<small data-count="{s}">{counts.get(s) or ""}</small>') + "</a>"
            for s, name in SHELF_NAMES.items())
        snap = self.activity.snapshot()
        busy = " busy" if snap["busy"] else ""
        needs = len(self.store.problems())
        mood, line = self.nest_status(snap)
        return ('<header class="top" id="top"><div class="bar"><a class="logo" href="/" aria-label="Magpiary, your library">' + ui.logo_mark() + 'magpiary</a>'
                f'<div class="sslot"><form class="search" method="get" action="/" role="search" id="searchform" title="Search"><span aria-hidden="true">{ui.icon("search")}</span>'
                f'<input id="q" type="search" name="q" value="{e(q)}" placeholder="Search what was said, shown or written" '
                f'autocomplete="off" aria-label="Search your saves" aria-controls="spanel" aria-expanded="false">'
                f'<button type="button" class="sclear" id="sclear" aria-label="Clear the search"{"" if q else " hidden"}>×</button>'
                f'<kbd>/</kbd><div class="spanel" id="spanel" role="listbox" hidden></div></form></div>'
                f'<a class="btn dark addp" href="/add" id="addbtn" title="Paste a link to any post or page">{ui.icon("plus")} <span class="lbl">Add a post</span></a>'
                f'<nav class="seg shelfsw" id="shelfsw" aria-label="Library, Archive, Trash"><i class="slider" aria-hidden="true"></i>{shelves}</nav>'
                f'<div class="right">' + self.access_button() + self.lock_button() + self.digest_button(active) + self.map_button(active) +
                f'<a class="ubtn nestbtn{busy}{" on" if active == "nest" else ""}" href="/nest" id="t-nest" data-mood="{mood}" '
                f'title="The nest: {e(line)}">{ui.icon("activity", "ico nesti")}<span class="lbl">Nest</span><span class="nline" id="nline">{e(line)}</span>'
                f'<span class="nbadge" id="nbadge" data-badge{"" if needs else " hidden"}>{needs}</span></a>'
                f'<a class="ubtn setbtn{" on" if active == "settings" else ""}" href="/settings" id="t-set" '
                f'aria-label="Settings" title="Settings">'
                f'{ui.icon("gear")}<span class="lbl">Settings</span></a></div></div>'
                + self.strip(snap) + "</header>")

    def strip(self, snap: dict) -> str:
        """The quiet dark strip under the bar: what is being worked on; opens the Nest."""
        lanes, waiting = snap["lanes"], snap["waiting_total"]
        shown = bool(lanes or waiting)
        chips = []
        for l in lanes:
            item = self.store.item_by_id(l["item_id"])
            thumb = self.thumb_url(item) if item else ""
            chips.append(f'<span class="tk"><span class="th"{f" style={chr(34)}background-image:url({e(thumb)}){chr(34)}" if thumb else ""}>'
                         f'</span>{e(l["step_label"])} · {e(l["label"][:60])}'
                         f'<span class="pb"><i style="width:{int(l["percent"] or 0)}%"></i></span></span>')
        head = "Paused" if not lanes and snap["paused_any"] else "Working" if lanes else "Waiting"
        more = f"{waiting} waiting" if waiting else ""
        return (f'<a class="ticker{" paused" if head == "Paused" else ""}{"" if shown else " gone"}" id="ticker" href="/nest" '
                f'aria-label="Open the Nest"><span class="tkin"><b><i></i><span id="tk-h">{head}</span></b>'
                f'<span class="tks" id="tks">{"".join(chips)}</span><span class="more" id="tk-more">{more}</span></span></a>')

    def phone_bar(self, page: str, shelf: str = "", active: str = "") -> str:
        """The bar at the bottom of a phone screen: Library, Search, Add, Nest and More (owner, 6 Nov 2026). CSS shows it
        only on a phone-sized screen; it replaces the floating Ask and Help pills there (Ask is off on the phone for now)."""
        def tab(href: str, icon: str, label: str, on: bool = False, extra: str = "") -> str:
            return (f'<a class="pb{" on" if on else ""}" href="{href}"{" aria-current=page" if on else ""}{extra}>'
                    f'{ui.icon(icon)}<span>{label}</span></a>')
        library = page == "wall" and shelf in ("", "inbox")
        return ('<nav class="pbar" id="pbar" aria-label="Main">'
                + '<i class="pslider" id="pslider" aria-hidden="true"></i>'
                + tab("/", "library", "Library", library, ' data-pb="library"')
                + '<button type="button" class="pb" data-pbar-search data-pb="search" aria-label="Search">' + ui.icon("search") + '<span>Search</span></button>'
                + tab("/add", "plus", "Add", page == "add", ' id="pbar-add" data-pb="add"')
                + tab("/nest", "activity", "Nest", active == "nest", ' data-pb="nest"').replace("</svg>", '</svg><i class="pdot" data-pbar-dot hidden></i>', 1)
                + '<button type="button" class="pb" data-pbar-more data-pb="more" aria-haspopup="true" aria-expanded="false">' + ui.icon("more") + '<span>More</span></button>'
                + '<div class="pmore" id="pmore" role="menu" hidden>'
                + f'<a role="menuitem" href="/?shelf=archive">{ui.icon("archive")}<span>Archive</span></a>'
                + f'<a role="menuitem" href="/?shelf=trash">{ui.icon("trash")}<span>Trash</span></a>'
                + f'<a role="menuitem" href="/digest">{ui.icon("digest")}<span>Digest</span></a>'
                + f'<a role="menuitem" href="/map">{ui.icon("grid3")}<span>Map</span></a>'
                + f'<a role="menuitem" href="/help">{ui.icon("book")}<span>Help</span></a>'
                + (f'<a role="menuitem" href="/phone/app" data-homescreen>{ui.icon("phone")}<span>Add to Home Screen</span></a>'
                   if getattr(self._ctx, "device", None) is not None else "")  # only a paired phone, through the secure door
                + '</div></nav>')

    def search_overlay(self) -> str:
        """The big search used when Appearance → Search is Spotlight (hub.js opens it from the bar's search)."""
        return ('<div class="sover" id="sover" hidden><div class="sbox" role="dialog" aria-modal="true" aria-label="Search">'
                '<form class="sbig" method="get" action="/" role="search"><span class="smag" aria-hidden="true">⌕</span>'
                '<input id="q2" type="search" name="q" placeholder="Search what was said, shown or written" '
                'autocomplete="off" aria-label="Search your saves"><kbd>esc</kbd></form>'
                '<div class="spanel2" id="spanel2" role="listbox"></div></div></div>')

    def add_modal(self) -> str:
        return (f'<div class="modal" id="addm" role="dialog" aria-modal="true" aria-labelledby="addm-h" hidden>'
                f'<h3 id="addm-h">Add a post</h3><p>Paste a link from Instagram, Threads, YouTube, Reddit, X, LinkedIn or '
                f'any other website. Tracking bits are removed before it is saved.</p>'
                f'<form method="post" action="/hub/add">{ui.hidden(self.csrf, next="/")}'
                f'<input type="url" name="url" placeholder="https://" required autocomplete="off" aria-label="Link to the post">'
                f'<div class="row" style="justify-content:flex-end"><button class="btn" type="button" data-close>Cancel</button>'
                f'<button class="btn dark" type="submit">Add</button></div></form></div>')

    def add_page(self, q: dict) -> Response:
        flash = f'<div class="flash err">{e(ERRORS[q["error"]])}</div>' if q.get("error") in ERRORS else ""
        body = (f'<div class="hero"><h1 class="mid">Add a <em>post.</em></h1><p>Paste a link from Instagram, Threads, '
                f'YouTube, Reddit, X, LinkedIn or any other website. Tracking bits are removed before it is saved.</p></div>'
                f'{flash}<form method="post" action="/hub/add" class="orpaste" style="max-width:640px">'
                f'{ui.hidden(self.csrf, next="/add")}<input type="url" name="url" placeholder="https://" required '
                f'aria-label="Link to the post"><button class="btn dark" type="submit">Add</button></form>')
        return self.shell("Add a post", body, "add")

    # ---- tiles -------------------------------------------------------------------------------

    def tile_context(self) -> dict:
        busy = self.activity.busy_urls()
        lanes = {l["item_id"]: l for l in self.activity.snapshot()["lanes"]}
        pile_of = {}
        for p in self.store.piles():
            for u in p["members"]:
                pile_of.setdefault(u, p["id"])
        from magpiary import boards

        boards_of: dict[str, list] = {}  # which shared boards each post is on, for the tag on its tile
        slugs = self.board_slugs() if self.store.boards() else {}
        for b in self.store.boards():
            v = boards.view(self.store, b["id"])
            for c in v["cards"] if v else []:
                boards_of.setdefault(c["url"], []).append((v["sticker"], v["name"], slugs.get(b["id"], b["id"])))
        return {"busy": busy, "lanes": lanes, "private": modes.current(self.store) == "private",
                "summaries": self.has_summaries(), "pile_of": pile_of, "boards_of": boards_of}

    def tile(self, item: dict, ctx: dict, over: str = "", quote: tuple[str, str] | None = None,
             words: list[str] | None = None, extra: str = "") -> str:
        """One square tile. The label takes the post's type colour once summarised; without a summary it takes
        the source's colour (Private, or Smart without a key) or stays grey while it waits its turn."""
        words = words or []
        href = f"/item/{item['id']}"
        thumb = self.thumb_url(item)
        src = ui.source_label(item)
        lane = ctx["lanes"].get(item["id"])
        on = ctx.get("boards_of", {}).get(item["canonical_url"], [])
        version = (f'{item["status"]}.{item.get("ai_status")}.{lane["step"] if lane else ""}.{item.get("shelf")}.'
                   + ",".join(b[2] for b in on))
        base = (f'data-id="{item["id"]}" data-flip-id="t{item["id"]}" data-v="{e(version)}" '
                f'data-url="{e(item["canonical_url"])}" data-shelf="{item.get("shelf", "inbox")}"'
                + (f' data-pile="{ctx["pile_of"][item["canonical_url"]]}"' if item["canonical_url"] in ctx.get("pile_of", {}) else ""))
        if item["status"] == "needs_attention":
            retry = f"Next try {when(item['next_retry_at'])}." if item.get("next_retry_at") else "Retries have run out."
            reason = REASONS.get(item.get("reason") or "unknown", item.get("reason") or "")
            return (f'<div class="tile attn" {base}><a class="cover" href="{href}" aria-label="Open: '
                    f'couldn\'t open this one"></a><div class="sq">{extra}<div><b>Couldn\'t open this one</b>{e(reason)}.<br>'
                    f'{e(retry)}<br><span class="small muted">{e(src)}</span></div></div>{over}</div>')
        archived = item["status"] == "archived"
        done = item.get("ai_status") == "done"
        title = ui.title_of(item)
        media = ui.media_of(item) if archived else {"video": "", "photos": [], "duration": None, "start": 0}
        length = ui.duration(media["duration"]) if media["duration"] else ""
        badge_top = (f'<span class="dur">{length or "▶"}</span>' if media["video"] else
                     f'<span class="dur">{len(media["photos"])} photos</span>' if len(media["photos"]) > 1 else "")
        preview = ""
        if media["video"]:
            preview = f' data-video="{e(self._media_url(item, media["video"]))}" data-start="{media["start"]}"'
        elif len(media["photos"]) > 1:
            preview = f' data-photos="{e(json.dumps([self._media_url(item, p) for p in media["photos"][:8]]))}"'
        art = (f'<img loading="lazy" decoding="async" src="{e(thumb)}" alt="">' if thumb else
               f'<div class="typo" style="background:{ui.gradient(item)}">“{e(title[:90])}”</div>')
        lock = (f'<i class="lockb" title="Instagram shows this post only to logged-in people, so its numbers are not refreshed">{ui.icon("lock")}</i>'
                if item.get("login_only") else "")
        solo = lock.replace('class="lockb"', 'class="lockb solo"')  # always visible; the source chip (with its own lock) shows on hover
        prog, pend, badge = "", False, ""
        if lane:
            pct = lane.get("percent")
            prog = (f'<div class="prog"><i style="width:{int(pct)}%"></i></div>' if pct is not None
                    else '<div class="prog ind"><i></i></div>')
        kind, kind_name, colour = "", "", ""  # the kind once summarised: a dot beside the type name; `colour` fills the label in the Coloured look
        if not archived:
            pend = True
            sub = "Received · " + (WORKING.get(lane["step"], "Fetching…") if lane else "waiting its turn")
            if not prog:
                prog = '<div class="prog ind"><i></i></div>'
        elif lane:
            pend = True
            sub = "Reading it · " + WORKING.get(lane["step"], STEPS.get(lane["step"], "Working…"))
        elif done:
            kind = item.get("ai_type") or "other"
            colour = ui.type_colour(item.get("ai_type"))
            kind_name = ui.type_name(item.get("ai_type"))
            sub = item.get("author") or src
        elif ctx["private"] or not ctx["summaries"]:
            colour = ui.source_colour(item["source"])
            sub = item.get("author") or src
            if not ctx["private"]:
                badge = '<span class="sumb">✦ Summarise</span>'
            if item.get("ai_status") == "needs_attention" and not ctx["private"]:
                badge = '<span class="sumb">Summary problem</span>'
        elif item.get("ai_status") == "needs_attention":
            colour = ui.source_colour(item["source"])
            sub, badge = item.get("author") or src, '<span class="sumb">Summary problem</span>'
        else:
            pend, sub = True, "Received · waiting to be read"
        onb = (f'<a class="onb" href="/board/{on[0][2]}" title="On {e(", ".join(b[1] for b in on))}">'
               f'{ui.sticker(on[0][0])}<span>{e(on[0][1])}</span>{f"<em>+{len(on) - 1}</em>" if len(on) > 1 else ""}</a>'
               if on else "")
        q_html = (f'<div class="quote"><small>{e(quote[0])}</small>{ui.mark(quote[1], words)}</div>' if quote else "")
        summary = (f'<div class="s"><span class="stxt">{e((item.get("summary") or "")[:300])}</span></div>'
                   if done and item.get("summary") else "")
        who = (f'<a class="who" href="/?{urlencode({"author": item["author"]})}" title="All posts by {e(item["author"])}">'
               f'{ui.avatar(item["author"], "rgba(255,255,255,.2)", "", "mini")}<span class="step">{e(sub)}</span></a>'
               if item.get("author") and not pend else f'<span class="step">{e(sub)}</span>')
        label_style = f' style="--lc:{ui.deep(colour)}"' if colour and not pend else ""  # used by the Coloured look only
        return (f'<div class="tile{" pend" if pend else ""}" {base}{preview}>'
                f'<a class="cover" href="{href}" aria-label="{e(title[:120])}"></a>'
                f'<div class="sq">{art}<span class="src"><i class="sd" style="background:{ui.source_colour(item["source"])}"></i>{f'<i class="kd2" style="background:{ui.type_colour(kind)}"></i>' if kind else ""}{e(src)}{lock}</span>{solo}{badge_top}{prog}{q_html}{extra}{onb}</div>'
                f'<div class="label"{label_style}><div class="t">{ui.mark(title, words)}</div>'
                f'<div class="m">{who}{f'<span class="kind"><i class="kd" style="background:{ui.type_colour(kind)}"></i>{e(kind_name)}</span>' if kind else ""}{badge}</div>{summary}</div>{over}</div>')

    def grid(self, items: list[dict], ctx: dict, over=None, words=None, big: set | None = None) -> str:
        """`over(item)` gives what sits on a tile: buttons (top right), or (buttons, a badge inside the picture).
        Items whose id is in `big` become the 2x2 tile."""
        tiles = []
        for i in items:
            extra = over(i) if over else ""
            acts, badge = extra if isinstance(extra, tuple) else (extra, "")
            html = self.tile(i, ctx, acts, words=words, extra=badge)
            tiles.append(html.replace('<div class="tile', '<div class="tile big', 1) if big and i["id"] in big else html)
        return '<div class="grid">' + "".join(tiles) + "</div>"

    def size_control(self) -> str:
        """Tile size, beside Filters and Select: three grid pictures, many small tiles to a few big ones."""
        look = ui.appearance(self.store)
        pics = {"s": "grid4", "m": "grid3", "l": "grid2"}
        now = look["size"] if look["size"] in pics else "m"
        after = {"s": "m", "m": "l", "l": "s"}[now]  # one icon that cycles small → medium → large (owner, 29 Oct)
        shown = "".join(ui.icon(pics[s], f"ico sz-{s}") for s in pics)
        return (f'<form class="sizes" method="post" action="/hub/ui" id="sizes" data-cur="{now}" aria-label="Tile size">'
                f'{ui.hidden(self.csrf, next="/")}<button type="submit" name="size" value="{after}" class="ibtn" '
                f'aria-label="Tile size: {ui.SIZES[now]}" title="{ui.SIZES[now]} (click for {ui.SIZES[after].lower()})">'
                f'{shown}</button></form>')

    def select_button(self) -> str:
        return (f'<button type="button" class="tbtn ibtn selbtn" id="selbtn" aria-pressed="false" aria-label="Select" title="Select">'
                f'{ui.icon("select")}</button>')

    # ---- the wall ---------------------------------------------------------------------------

    def wall_page(self, q: dict) -> Response:
        shelf = q.get("shelf") if q.get("shelf") in ("archive", "trash") else "inbox"
        query = q.get("q", "").strip()
        flash = f'<div class="flash err">{e(ERRORS[q["error"]])}</div>' if q.get("error") in ERRORS else ""
        if query:
            return self.search_page(query, flash, words_only=q.get("words") == "1", no=set(q.get("no", "").split("|")) - {""})
        if shelf != "inbox":
            return self.shelf_page(shelf, flash)
        view = q.get("view") if q.get("view") in ("piles", "boards") else "everything"
        ctx = self.tile_context()
        items = self.store.hub_items("inbox", limit=5000, compact=True)
        if q.get("part", "").isdigit() and view == "everything":
            body, _ = self._everything(q, items, ctx, part=int(q["part"]))
            return Response(200, body.encode(), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        banner = self.offers_banner("/") + self.digest_banner() + self._no_ai_banner() + self._needs_banner()
        head_a, head_b = ui.HEADS[date.today().toordinal() % len(ui.HEADS)]
        today = sum(ui.section_of(i) == "Today" for i in items)
        # the big heading and search with the bird on it (owner, 1 Nov); the search opens the big search box and
        # the page's real one waits in the bar, which takes over once this has scrolled away
        hero = (f'<div class="hero wallhero compact lhero{"" if items else " lhempty"}" id="hero"><h1>{head_a} {head_b}</h1>'
                f'<button type="button" class="lhsearch" id="lhsearch" aria-label="Search your saves"><span aria-hidden="true">⌕</span>'
                f'<span class="lhph">Search what was said, shown or written</span><kbd>/</kbd>'
                f'<img class="lhbird" src="{ui.art("land-c")}" alt=""></button><p class="meta1">'
                + (f"<span><b>{today} new today</b></span>" if today else "")
                + '<span>Sort them into piles, or see everything by when you saved it.</span></p></div>')
        if view == "piles":
            body = self._piles_view(ctx)
            # a phone gets Regroup as an icon beside the tabs (phone.css hides this on the Mac and hides the paragraph + button below on a phone)
            pregroup = ui.button_form(self.csrf, "/hub/piles/regroup", {"next": "/?view=piles"}, ui.icon("refresh"), "ibtn pregroup",
                                      "Group all your saves again? Your renames, moves, removals and deletions stay.", title="Regroup everything")
            tabs = self._views("piles", f'<div class="tools">{self.size_control()}{pregroup}</div>')
        elif view == "boards":
            body, tabs = self.boards_view(q), self._views("boards", f'<div class="tools">{self.size_control()}</div>')
        else:
            body, tabs = self._everything(q, items, ctx)
        if not items and view == "everything" and not any(q.get(k) for k in ("source", "tag", "type", "links", "attention", "author", "deep")):
            body = empty_state("Your library is empty", "Share a post from your iPhone with <b>Share → Magpiary</b>, or "
                               "paste a link.", '<a class="btn dark" href="/add">Add a post</a>'
                               '<a class="btn" href="/welcome">Open the setup guide</a>')
        return self.shell("Library", flash + banner + hero + f'<div id="wallctl">{tabs}</div>'
                          + f'<div id="wallbody" data-view="{view}">{body}</div>',
                          "wall", shelf="inbox")

    def _no_ai_banner(self) -> str:
        if modes.current(self.store) == "private" or keyring.load():
            return ""
        return ('<div class="banner" id="nokey"><div style="flex:1;min-width:240px"><b>✦ Want summaries and key moments too?</b>'
                '<p>Your saves are kept and searchable by caption and by what was said. Add a free AI key (about 2 minutes) '
                'and Magpiary writes a summary for each, or choose Private to keep everything off AI.</p></div>'
                '<a class="btn dark" href="/settings/ai#addkey">Add a free key</a>'
                '<a class="btn" href="/settings/ai#mode">Choose Private</a></div>')

    def _needs_banner(self) -> str:
        problems = self.store.problems()
        if not problems:
            return ""
        n = len(problems)
        return (f'<div class="banner warnb" id="needsb" data-needs="{n}" data-dismiss="needs-{n}-{e(problems[0]["updated_at"] or "")}">'
                f'<div style="flex:1;min-width:240px"><b>{n} save{"" if n == 1 else "s"} need{"s" if n == 1 else ""} you</b>'
                f'<p>Magpiary couldn\'t open or summarise {"it" if n == 1 else "them"} by itself. The Nest shows what happened '
                f'and what to try.</p></div><a class="btn cta alert" href="/nest">Open the Nest</a>'
                f'<button class="btn" type="button" data-dismiss-btn>Not now</button></div>')

    def _views(self, view: str, filters: str) -> str:
        return (f'<div class="ctrl1"><div class="vgrp"><div class="views" role="tablist" id="views"><i class="vline" aria-hidden="true"></i>'
                f'<a role="tab" href="/" data-view="everything" class="{"on" if view == "everything" else ""}" '
                f'aria-selected="{str(view == "everything").lower()}">Everything</a>'
                f'<a role="tab" href="/?view=piles" data-view="piles" class="{"on" if view == "piles" else ""}" '
                f'aria-selected="{str(view == "piles").lower()}">Piles</a>'
                f'<a role="tab" href="/?view=boards" data-view="boards" class="{"on" if view == "boards" else ""}" '
                f'aria-selected="{str(view == "boards").lower()}">Boards</a></div>'
                + self.ask_button("library:auto", cls="btn sm askbtn2 askwall") + f'</div>{filters}</div>')

    def _everything(self, q: dict, items: list[dict], ctx: dict, part: int = 0) -> tuple[str, str]:
        source, tag, kind = q.get("source", ""), q.get("tag", ""), q.get("type", "")
        author = q.get("author", "")
        links, attention = q.get("links") == "1", q.get("attention") == "1"
        deep = q.get("deep") == "suggested"  # long videos that could use a deeper dive (Settings links here)
        trend = q.get("sort") == "trending"
        popular = q.get("sort") == "popular" or trend  # trending is a popularity order too: same layout, different ranking
        state = {"source": source, "tag": tag, "author": author, "type": kind, "links": "1" if links else "", "attention": "1" if attention else "",
                 "deep": "suggested" if deep else "", "sort": "trending" if trend else "popular" if popular else ""}

        def link(**change) -> str:
            params = {k: v for k, v in {**state, **change}.items() if v}
            return "/" + (f"?{urlencode(params)}" if params else "")

        counts = self.store.hub_counts()
        with_links = self.store.urls_with_links()
        n_links = sum(i["canonical_url"] in with_links for i in items)
        types: dict = {}
        for i in items:
            if i.get("ai_status") == "done":
                types[i.get("ai_type") or "other"] = types.get(i.get("ai_type") or "other", 0) + 1

        def chip(href: str, on: bool, label: str, colour: str = "", n=None) -> str:
            return (f'<a class="fchip{" on" if on else ""}" href="{e(href)}">'
                    + (f'<i style="background:{colour}"></i>' if colour else "") + f'{e(label)}'
                    + (f'<span class="n">{n}</span>' if n is not None else "") + "</a>")

        src_chips = "".join(chip(link(source="" if s == source else s), s == source, ui.source_name(s), ui.source_colour(s), n)
                            for s, n in sorted(counts["sources"].items(), key=lambda kv: -kv[1]))
        type_chips = "".join(chip(link(type="" if t == kind else t), t == kind, TYPE_NAMES.get(t, t), ui.type_colour(t), n)
                             for t, n in sorted(types.items(), key=lambda kv: -kv[1]))
        toggles = (chip(link(links="" if links else "1"), links, "Has links", "", n_links)
                   + (chip(link(attention="" if attention else "1"), attention, "Needs you", "var(--bad)", counts["attention"])
                      if counts["attention"] or attention else ""))
        active = sum(bool(x) for x in (source, kind, links, attention, tag, author, deep))
        panel = (f'<div class="pop fpanel" role="dialog" aria-label="Filters"><div class="fgroup"><h5>Sources</h5>'
                 f'<div class="fchips">{src_chips}</div></div>'
                 + (f'<div class="fgroup"><h5>Types</h5><div class="fchips">{type_chips}</div></div>' if type_chips else "")
                 + f'<div class="fgroup"><h5>Show only</h5><div class="fchips">{toggles}</div></div>'
                 + f'<div class="fgroup"><h5>Order</h5><div class="fchips">{chip(link(sort=""), not popular, "Newest first")}'
                   f'{chip(link(sort="popular"), popular and not trend, "Most popular")}{chip(link(sort="trending"), trend, "Trending")}</div></div>'
                 + ('<a class="fclear" href="/">Clear all filters</a>' if active else "") + "</div>")
        filters = (f'<div class="tools"><details class="menu fmenu"><summary class="tbtn ibtn{" on" if active else ""}" aria-label="Filters" title="Filters">'
                   f'{ui.icon("filter")}' + (f'<b class="fcount">{active}</b>' if active else "")
                   + f'</summary>{panel}</details>{self.select_button()}{self.size_control()}</div>')
        actives = []
        if popular:
            actives.append(chip(link(sort=""), True, "Trending" if trend else "Most popular"))
        if source:
            actives.append(chip(link(source=""), True, ui.source_name(source), ui.source_colour(source)))
        if kind:
            actives.append(chip(link(type=""), True, TYPE_NAMES.get(kind, kind), ui.type_colour(kind)))
        if links:
            actives.append(chip(link(links=""), True, "Has links"))
        if attention:
            actives.append(chip(link(attention=""), True, "Needs you", "var(--bad)"))
        if deep:
            actives.append(chip(link(deep=""), True, "Could use a deeper dive"))
        if tag:
            actives.append(chip(link(tag=""), True, f"#{tag}"))
        if author:
            actives.append(chip(link(author=""), True, f"By {author}"))
            n_boards = len(self.boards_with_author(author))
            if n_boards:
                actives.append(f'<a class="fchip" href="/?{urlencode({"view": "boards", "author": author})}">'
                               f'In {n_boards} board{"" if n_boards == 1 else "s"} →</a>')
        chips = (f'<div class="activef" aria-label="Active filters">{"".join(actives)}</div>' if actives else "")
        tag_on = ""
        from magpiary import deepdive

        deep_urls = deepdive.suggested_urls(self.store) if deep else set()
        shown = [i for i in items if (not source or i["source"] == source)
                 and (not kind or (i.get("ai_status") == "done" and (i.get("ai_type") or "other") == kind))
                 and (not links or i["canonical_url"] in with_links)
                 and (not attention or i["status"] == "needs_attention")
                 and (not tag or tag in i["tags"])
                 and (not author or i.get("author") == author)
                 and (not deep or i["canonical_url"] in deep_urls)]
        controls = self._views("everything", filters) + chips + tag_on
        if not shown:
            return (empty_state("Nothing matches these filters", "Try another source or type, or clear them all.",
                                '<a class="btn dark" href="/">Clear filters</a>'), controls)
        today = datetime.now().astimezone().date()
        stats_by = self.store.stats_all() if (popular or not (active or q.get("q"))) else {}
        spot = self._spotlight(items, stats_by) if (popular or not (active or q.get("q"))) else {}
        grew = {}
        if trend:  # biggest recent growth first; posts that did not grow (or have only one refresh) follow in their usual order
            grew = spotlight.trending(shown, stats_by, spot)
            shown = sorted(shown, key=lambda i: -grew.get(i["canonical_url"], {}).get("score", -1))
        elif popular:  # the strongest first; posts with no numbers last, in their usual order
            shown = sorted(shown, key=lambda i: (not spot.get(i["canonical_url"], {}).get("known"), -spot.get(i["canonical_url"], {}).get("score", 0)))
        featured, past = self._featured(shown, today) if not (active or q.get("q") or popular) else ([], None)
        lead = {i["id"] for i in featured} | ({past["id"]} if past else set())
        shown = [i for i in shown if i["id"] not in lead]  # a post is on the page once: hub.js finds tiles by id
        chunk = self.store.items_by_ids([i["id"] for i in shown[part * PAGE:(part + 1) * PAGE]])
        sections: dict[str, list] = {}
        name_of = (lambda i: "Trending" if trend else "Most popular") if popular else (lambda i: ui.section_of(i, today))
        for i in chunk:
            sections.setdefault(name_of(i), []).append(i)
        totals: dict[str, int] = {}
        for i in shown:
            name = name_of(i)
            totals[name] = totals.get(name, 0) + 1
        big = set() if (popular or active or q.get("q")) else self._big_ids(sections, spot, stats_by, today)

        def over(i: dict):
            if trend and i["canonical_url"] in grew:
                return ("", f'<span class="statb up">{ui.icon("trend")}{e(spotlight.gain_text(grew[i["canonical_url"]]["gain"]))}</span>')
            if popular:
                s_ = stats_by.get(i["canonical_url"]) or {}
                bits = [f"{ui.icon('heart')}{spotlight.compact(s_['likes'])}" if s_.get("likes") else "",
                        f"{ui.icon('comment')}{spotlight.compact(s_['comments'])}" if s_.get("comments") else ""]
                return ("", f'<span class="statb">{"".join(b for b in bits if b) or "no numbers yet"}</span>')
            if i["id"] in big:
                info = spot.get(i["canonical_url"], {})
                return ("", f'<span class="reasonb">{e(spotlight.reason(i, info, stats_by.get(i["canonical_url"])))}</span>')
            return ""

        parts = [f'<section class="secblock" data-sec="{e(name)}"><div class="sec"><h2>{e(name)}</h2>'
                 f'<span>{totals[name]} saved</span></div>' + self.grid(xs, ctx, over=over, big=big) + "</section>"
                 for name, xs in sections.items()]
        if featured and not part:
            tiles = [self.tile(i, ctx) for i in self.store.items_by_ids([i["id"] for i in featured])]
            if past:
                tiles.append(self.tile(self.store.item_by_id(past["id"]), ctx, extra='<span class="pastb">From your past</span>'))
            parts.insert(0, '<section class="secblock featblock" data-sec="Featured"><div class="grid featgrid">'
                         + "".join(tiles) + "</div></section>")
        more = ""
        if (part + 1) * PAGE < len(shown):
            nxt = link() + ("&" if "?" in link() else "?") + f"part={part + 1}"
            more = (f'<a class="more-tiles" href="{e(nxt)}" data-more>Show more · {len(shown) - (part + 1) * PAGE} '
                    f'older</a>')
        ids = f'<i id="wallids" data-ids="{",".join(str(i["id"]) for i in shown if i.get("id"))}" hidden></i>'  # for Select all
        if trend and not grew:
            parts.insert(0, '<p class="trendnote">Nothing is trending yet. A post shows up here once two refreshes of its numbers '
                            'are in and it has grown (Select posts, then Refresh stats).</p>')
        return "".join(parts) + more + ids, controls

    def _spotlight(self, items: list[dict], stats_all: dict | None = None) -> dict:
        """Every post's Spotlight score, kept until the numbers or the library change."""
        if stats_all is None:
            stats_all = self.store.stats_all()
        opens = self.store.opens_weighted()
        sig = (len(items), len(stats_all), max((s.get("fetched_at") or "" for s in stats_all.values()), default=""),
               self.store.related_signature(), round(sum(opens.values()), 1))
        cached = getattr(self, "_spot", None)
        if cached and cached[0] == sig:
            return cached[1]
        piles = [{"id": p["id"], "name": p.get("name") or p.get("auto_name") or "this pile", "members": p["members"]}
                 for p in self.store.piles() if len(p["members"]) >= 2]
        result = spotlight.compute(items, stats_all, piles, opens=opens)
        self._spot = (sig, result)
        return result

    def _big_ids(self, sections: dict[str, list], spot: dict, stats_by: dict, today) -> set:
        """The posts that are big today: about one in BIG_EVERY, only in sections with enough posts, picked from the
        top tenth by Spotlight score, the same all day and different tomorrow, never repeated within two weeks."""
        import json

        day = today.toordinal()
        try:
            memory = {int(k): v for k, v in json.loads(self.store.get_setting("big_memory", "{}") or "{}").items()}
        except (ValueError, AttributeError):
            memory = {}
        recent = {u for d, urls in memory.items() if 0 < day - d < spotlight.REPEAT_DAYS for u in urls}
        chosen: list[str] = []
        by_url = {}
        for name, xs in sections.items():
            if len(xs) < BIG_MIN or name == "Today":
                continue
            by_url.update({i["canonical_url"]: i for i in xs})
            cands = [(i["canonical_url"], spot.get(i["canonical_url"], {}).get("score", 0.0), spot.get(i["canonical_url"], {}).get("pile", ""))
                     for i in xs if i["status"] == "archived" and self.thumb_url(i) and spot.get(i["canonical_url"], {}).get("known")]
            want = min(len(xs) // BIG_EVERY, 3)
            place = {i["canonical_url"]: n for n, i in enumerate(xs)}
            kept: list[str] = []
            for url in spotlight.pick_big(cands, day + sum(map(ord, name)), recent, want * 3):  # spread out: no two close together
                if all(abs(place[url] - place[k]) >= BIG_EVERY - 4 for k in kept):
                    kept.append(url)
                if len(kept) == want:
                    break
            chosen += kept
        if chosen and memory.get(day) != chosen:  # remember today's picks so tomorrow's differ
            memory[day] = chosen
            memory = {d: u for d, u in memory.items() if day - d < 30}
            self.store.set_setting("big_memory", json.dumps({str(d): u for d, u in memory.items()}))
        return {by_url[u]["id"] for u in chosen if u in by_url}

    def _featured(self, items: list[dict], today: date) -> tuple[list[dict], dict | None]:
        """The top of the wall: the newest saves with pictures, and one older save that changes each day (owner, 1 Nov).
        A small library has nothing to feature."""
        if len(items) < FEATURE_MIN:
            return [], None
        pics = [i for i in items if i["status"] == "archived" and self.thumb_url(i)]
        count = FEATURE_NEW.get(ui.appearance(self.store)["size"], FEATURE_NEW["m"])
        newest = pics[:count]

        def age(item: dict) -> int:
            when = ui.local(item.get("last_shared_at") or item.get("created_at"))
            return (today - when.date()).days if when else 0

        older = [i for i in pics[count:] if age(i) >= FEATURE_PAST_DAYS]
        return newest, older[today.toordinal() % len(older)] if older else None

    # ---- piles on the wall --------------------------------------------------------------------

    def _piles_view(self, ctx: dict) -> str:
        lib = self.related_library()
        cards = []
        for p in self.store.piles():
            rows = [lib.rows[lib.index[u]] for u in p["members"] if u in lib.index]
            if len(rows) >= 2:  # a pile needs two saves that belong together; a lone save is only on the wall
                cards.append(self.pile_card(p, rows, lib))
        regroup = self._form("/hub/piles/regroup", {"next": "/?view=piles"}, "↻ Regroup everything", "btn sm",
                             confirm="Group all your saves again? Your renames, moves, removals and deletions stay.")
        bar = ('<div class="pilebar"><p><b>Piles are groups Magpiary makes for you</b>, from what your saves have in common. A pile '
               'appears once two saves belong together. Rename, move, merge or split them any time; your changes stay.'
               f'</p>{regroup}</div>')
        if not cards:
            return bar + empty_state("No piles yet", "They appear by themselves once a few saves have been read.")
        return bar + f'<div class="piles">{"".join(cards)}</div>'

    def pile_card(self, pile: dict, rows: list[dict], lib) -> str:
        """One pile, drawn for both looks (stacked photos, a folder); Settings → Appearance sets the page's
        data-piles attribute, which picks the one that shows."""
        items = [i for i in (self.store.item_by_id(r["id"]) for r in rows) if i]
        top = (items[1:2] or items[:1]) + (items[2:3] or items[:1]) + items[:1]

        def pic(i, flip=True):
            thumb = self.thumb_url(i)
            return (f'<div style="background:{ui.gradient(i)}"' + (f' data-flip-id="t{i["id"]}"' if flip else "") + ">"
                    + (f'<img loading="lazy" decoding="async" src="{e(thumb)}" alt="">' if thumb else "") + "</div>")

        stack = "".join(pic(i) for i in top)
        n = len(rows)
        new = self.store.new_in_pile(pile["id"])
        sub = rel.subtitle(lib, pile["members"], pile["name"])
        colour = ui.pile_colour(pile)
        count = f'{n} save{"" if n == 1 else "s"}'
        newb = f'<em class="newb">{new} new</em>' if new else ""
        # stacks show a coloured label under the pictures; folders carry the name and count on their front flap
        return (f'<a class="pile" href="/pile/{pile["id"]}" data-flip-id="p{pile["id"]}" data-pile="{pile["id"]}" '
                f'style="--pc:{colour}"><div class="stack">{stack}</div>'
                f'<div class="folder"><i class="ftab"></i><div class="peek">{"".join(pic(i, False) for i in items[:3])}</div>'
                f'<div class="flap"><b>{e(pile["name"])}</b><span><i class="cn">{count}</i>{newb}</span></div></div>'
                f'<div class="lab"><span class="lt"><b>{e(pile["name"])}</b>{newb}</span><span class="lc"><i class="cn">{count}</i></span></div>'
                f'<p class="sub">{e(sub) if sub else "&nbsp;"}</p></a>')

    # ---- search ------------------------------------------------------------------------------

    def find(self, query: str, no: set, words_only: bool = False):
        """The search itself: what was understood in the query, then the words and meaning left over, then the filters."""
        got = understand(query, self.store.facet_counts(), ui.type_name, ui.source_name, no=no)
        words = re.findall(r"\w+", got.rest, flags=re.UNICODE)[:12]
        items = self.store.hub_items("kept", got.rest if words else "", limit=5000 if got.parts else 300)
        if words and not words_only:
            items = self._with_meaning(got.rest, items)
        wanted = [(p.key, p.value) for p in got.parts if p.kind == "facet"]
        with_facets = self.store.urls_with_facets(wanted) if wanted else None
        return [i for i in items if keep(i, got, with_facets)], got, words

    def search_page(self, query: str, flash: str = "", words_only: bool = False, no: set | None = None) -> Response:
        no = no or set()
        items, got, words = self.find(query, no, words_only)
        ctx = self.tile_context()
        tiles = "".join(self.tile(i, ctx, quote=ui.why(i, words), words=words) for i in items)
        chips = "".join(
            f'<a class="uchip" href="/?q={e(quote(query))}&no={e(quote("|".join(sorted(no | {p.token}))))}" '
            f'title="Read from “{e(p.phrase)}”. Press to search for the words instead">{e(p.label)}<i aria-hidden="true">×</i></a>'
            for p in got.parts)
        save = self._form("/hub/view/save", {"q": query, "no": "|".join(sorted(no)), "next": "/"}, "Save as a view", "pillb") if query else ""
        read = (f'<div class="understood"><small>Read as</small>{chips}</div>' if chips else "")
        head = (f'<div class="sec" style="margin-top:0"><h2>{len(items)} found</h2><span>for “{e(query)}”, across the '
                f'library and the archive, with the matching line on each tile</span>{save}{self.size_control()}{self.select_button()}</div>{read}')
        guess = self.store.did_you_mean(query) if len(items) <= 2 else ""
        mean = (f'<p class="didyou">Did you mean <a class="link" href="/?q={e(quote(guess))}"><b>{e(guess)}</b></a>?</p>'
                if guess and guess.lower() != query.strip().lower() else "")
        body = (mean + (f'<div class="grid">{tiles}</div>' if items else
                empty_state("Nothing matches", f"Nothing you saved mentions “{e(query)}”. Try fewer words, or a name "
                            "from the post.", '<a class="btn" href="/">Clear the search</a>')))
        return self.shell("Search", flash + head + body, "search", q=query)

    def _with_meaning(self, query: str, items: list[dict]) -> list[dict]:
        """M7b: saves close in meaning join the word matches in one list, best first (owner: no mark on them).
        Typing asks for words only first (instant); this runs on the request that follows the pause."""
        from magpiary.related import blend_by_meaning

        vector = self.meaning.query(query) if self.meaning else None
        if not vector:
            return items
        return blend_by_meaning(self.store, vector, items)

    # ---- Archive and Trash ---------------------------------------------------------------------

    def shelf_page(self, shelf: str, flash: str = "") -> Response:
        items = self.store.hub_items(shelf, limit=5000)
        ctx = self.tile_context()
        n = len(items)
        if shelf == "archive":
            note = ('<div class="note1"><span aria-hidden="true">✓</span><span style="flex:1"><b>Done with these.</b> Out of '
                    'the main library, still searchable. Nothing is deleted.</span>' + (self.size_control() + self.select_button() if items else "") + "</div>")
            empty = empty_state("Nothing archived yet", "Use Archive on a post once you're done with it.")

            def over(i):
                return ('<div class="acts show">' + self._form("/hub/shelf", {"id": i["id"], "shelf": "inbox",
                                                                              "next": "/?shelf=archive"}, "Back to library", "pillb")
                        + "</div>")
        else:
            empty_btn = (self._form("/hub/empty-trash", {"next": "/?shelf=trash"}, "Empty trash", "btn sm dark",
                                    confirm="Delete everything in the Trash for good, with its files?") if items else "")
            note = (f'<div class="note1"><span aria-hidden="true">🗑</span><span style="flex:1"><b>Saves here are deleted for good after '
                    f'{TRASH_DAYS} days</b>, files and all. Sharing a post again brings it back.</span>'
                    + (self.size_control() + self.select_button() if items else "") + f'{empty_btn}</div>')
            empty = empty_state("The trash is empty", "Removed posts wait here for 30 days.")

            def over(i):
                left = TRASH_DAYS
                if i.get("trashed_at"):
                    try:
                        gone = datetime.fromisoformat(i["trashed_at"]) + timedelta(days=TRASH_DAYS)
                        left = max(0, (gone.date() - date.today()).days)
                    except ValueError:
                        pass
                return (('<div class="acts show">'
                         + self._form("/hub/shelf", {"id": i["id"], "shelf": "inbox", "next": "/?shelf=trash"}, "Restore", "pillb")
                         + "</div>"), f'<span class="days">{left} day{"" if left == 1 else "s"} left</span>')
        body = (flash + f'<div class="hero"><h1>{SHELF_NAMES[shelf]}</h1><p>{n} save{"" if n == 1 else "s"}</p></div>' + note
                + (self.grid(items, ctx, over) if items else empty))
        return self.shell(SHELF_NAMES[shelf], body, "shelf", shelf=shelf)
