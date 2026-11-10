"""Shared boards in the hub (M9 task 7), mixed into Hub: the Boards view inside Library (every board as a card, New
board, Join), and a board's page (members, sort, filter, cards with who added them and votes).

Cards are the "Mix" look the owner chose on 25 Oct 2026 from Tiles, Pinboard and Ranked: pinboard cards on the
library's grid, sized by the same tile-size control. /board/mock draws an example board from the owner's own saves
with two made-up friends; nothing in it is written to any board."""

import base64
import hashlib
import io
import json
import random
import re
import time
from datetime import datetime
from urllib.parse import quote, urlencode, urlsplit

import segno

from magpiary import boards, boardsync, identity, stickers, ui
from magpiary.protocol import default_port
from magpiary.web import Response, e

BOARD_PAGE = 24  # cards shown at once on a board; more load as the page is scrolled
SORTS = {"newest": "Newest", "oldest": "Oldest", "votes": "Most votes", "title": "Title A–Z"}
MOCK_FRIENDS = (("f" * 64, "Asha", "#2f6bff"), ("e" * 64, "Ravi", "#00a37a"))
MOCK_PROFILES = {"Asha": {"about": "Industrial designer. Saves chairs, joinery and small shops worth a detour.",
                          "links": {"website": "https://example.com", "instagram": "asha.makes"}, "topics": ["Furniture", "Travel", "Coffee"]},
                 "Ravi": {"about": "Weekend cook and bad photographer.", "links": {"github": "ravi-codes"},
                          "topics": ["Recipes", "Street food", "Cameras"]}}


class BoardPages:
    """Needs Hub's store, csrf, shell, _form, thumb_url and the boards module."""

    # ---- the Boards view in Library -------------------------------------------------------------

    def boards_view(self, q: dict | None = None) -> str:
        q = q or {}
        found = self.store.boards()
        author = q.get("author", "")
        if author:
            mine = self.boards_with_author(author)
            found = [b for b in found if b["id"] in mine]
        slugs = self.board_slugs()
        gone = self.store.board(q.get("gone", "")) if q.get("gone") else None
        if gone and gone["archived_at"] and not author:  # just deleted: its folder is still there, to shrink away
            found = sorted([*found, gone], key=lambda b: b["joined_at"], reverse=True)
        cards = "".join(self._board_card(b, slugs, ghost=bool(gone) and b["id"] == gone["id"], back=b["id"] == q.get("back"))
                        for b in found)
        flash = f'<div class="flash err">{e(q["error"][:200])}</div>' if q.get("error") else ""
        if author:
            head = (f'<div class="activef"><a class="fchip on" href="/?view=boards">By {e(author)}</a>'
                    f'<a class="fchip" href="/?{urlencode({"author": author})}">All their posts →</a></div>')
            if not found:
                return flash + head + '<div class="bnone"><b>None of your boards has a post by them</b></div>'
            return flash + head + f'<div class="piles boards">{cards}</div>'
        # the first folder is an empty one: it opens a dialog to make a board or join one (owner, 26 Oct)
        new = (f'<a class="pile bpile bnew" href="/?view=boards&make=new"><div class="folder">'
               f'<svg class="bnewsvg" viewBox="0 0 120 100" aria-hidden="true"><path d="M0 91V7Q0 0 7 0H45.8Q52.8 0 52.8 7V8H111Q120 8 120 17V91Q120 100 111 100H9Q0 100 0 91Z"/></svg>'
               f'<div class="bnewin"><span class="bplus">{ui.icon("plus")}</span><b>New board</b>'
               f'<span>Make one, or join a friend\'s</span></div></div></a>')
        none = ('' if found else '<div class="bnone"><b>No boards yet</b><p>A board is a space of your own to arrange posts. '
                'Share it with friends later. <a class="link" href="/board/mock">See an example board</a></p></div>')
        # coming back: your boards first; making or joining one folds away below them until it is asked for
        panel = lambda h, n=0: f'<div class="skp" style="height:{h}px">' + '<i></i>' * n + '</div>'
        skel = (f'<template id="bskel"><div class="bpage bskel"><div class="bhead"><a class="bback" href="/?view=boards">{ui.icon("chev")}'
                f'<span>Boards</span></a><div class="btitle"><span class="bstkwrap" data-skel-sticker></span><h1 data-skel-name></h1></div></div>'
                '<div class="blay"><div class="bmain"><div class="bsorts"><span class="skb w1"></span><span class="skb w2"></span>'
                '<span class="skb w3"></span></div>'
                '<div class="grid mixes">' + '<article class="mx skel"><div class="sq"></div><div class="mxb"><i></i><i></i></div></article>' * 6
                + '</div></div><aside class="bside"><div class="bsidein">' + panel(74) + panel(74) + panel(112, 2) + panel(214, 4)
                + '</div></aside></div></div></template>')
        note = '<p class="pagenote"><b>Boards are made by you.</b> A place to gather posts for a project, on your own or with friends.</p>'
        return (flash + skel + note + f'<div class="piles boards">{new}{cards}</div>{none}' + self._deleted_boards()
                + (self._make_dialog(q) if q.get("make") else ""))

    def _deleted_boards(self) -> str:
        """Boards their creator deleted: kept hidden for 30 days, and restorable until then."""
        gone = self.store.boards(archived=True)
        if not gone:
            return ""
        rows = ""
        for b in gone:
            v = boards.view(self.store, b["id"])
            left = max(0, 30 - (datetime.fromisoformat(self.store.now()) - datetime.fromisoformat(b["archived_at"])).days)
            rows += (f'<li><span>{ui.sticker(v["sticker"])}<b>{e(v["name"])}</b><small>{len(v["cards"])} cards · '
                     f'deleted for good in {left} day{"" if left == 1 else "s"}</small></span>'
                     + ui.button_form(self.csrf, "/hub/boards/restore", {"board": b["id"], "next": "/?view=boards"},
                                      "Restore", "btn sm") + "</li>")
        return (f'<details class="bmakewrap bdeleted"><summary class="btn sm ghost">{ui.icon("trash")}'
                f'<span>Deleted boards · {len(gone)}</span></summary><ul class="bdellist">{rows}</ul></details>')

    def boards_with_author(self, author: str) -> dict[str, int]:
        """{board id: how many of its cards are by this author}."""
        out = {}
        for b in self.store.boards():
            v = boards.view(self.store, b["id"])
            n = sum(1 for c in (v["cards"] if v else []) if c.get("author") == author)
            if n:
                out[b["id"]] = n
        return out

    def _make_dialog(self, q: dict) -> str:
        """Make a board or join one: one dialog, everything centred. A heading, two compact coloured tabs, then the form
        for the open tab; both forms share one frame (hub.js fades between them)."""
        joining = q.get("make") == "join"
        back = "/?view=boards"
        via = ("your own storage bucket" if new_board_via(self.store) == "bucket" else
               "free public Nostr relays, which only pass on sealed copies that you and your friends can open")
        ideas = "".join(f'<button type="button" class="mkidea" data-idea="{e(t)}">{e(t)}</button>'
                        for t in ("Trip", "Gift ideas", "Recipes", "Reading list", "Flat hunt"))
        new_form = (f'<form method="post" action="/hub/boards/new" class="bmake">{ui.hidden(self.csrf, next=back)}'
                    '<label class="mklab" for="mkname">Name your board</label>'
                    '<input id="mkname" name="name" class="bbig" placeholder="Lisbon trip" aria-label="Board name" '
                    'maxlength="60" required autocomplete="off">'
                    f'<div class="mkideas" aria-label="Ideas">{ideas}</div>'
                    '<button class="btn dark">Make the board</button></form>'
                    f'<p class="bpriv">{ui.icon("lock")}<span>Private: it stays on this Mac until you share it from the '
                    'board\'s page. Sharing syncs through ' + via + ' · <a href="/settings/profile#sync">change</a></span></p>')
        join_form = (f'<form method="post" action="/hub/boards/join" class="bmake">{ui.hidden(self.csrf, next=back)}'
                     '<label class="mklab" for="mkcode">Invite code</label>'
                     '<input id="mkcode" name="code" class="mono bbig bcodein" placeholder="MAG-XXXX-XXXX-XXXX" aria-label="Invite code" '
                     'autocomplete="off" spellcheck="false" required data-code>'
                     f'<button type="button" class="mkpaste" data-paste>{ui.icon("copy")}<span>Paste the code</span></button>'
                     '<button class="btn dark">Join the board</button></form>'
                     f'<p class="bpriv">{ui.icon("people")}<span>The code a friend sent you. If they sent a link, opening it fills the '
                     'code in for you.</span></p>')
        tabs = ('<div class="mktabs" role="tablist">'
                f'<a role="tab" id="mktn" href="{back}&make=new" aria-selected="{str(not joining).lower()}" aria-controls="mkpn" '
                f'class="mktab{"" if joining else " on"}" style="--c:#2f6bff" data-title="New board" data-sub="A space to arrange posts, on your own or with friends."><span class="seticon">{ui.icon("plus")}</span>'
                f'<span>Make a new board</span></a>'
                f'<a role="tab" id="mktj" href="{back}&make=join" aria-selected="{str(joining).lower()}" aria-controls="mkpj" '
                f'class="mktab{" on" if joining else ""}" style="--c:#ff2e93" data-title="Join a board" data-sub="Fill one with a friend who runs Magpiary."><span class="seticon">{ui.icon("people")}</span>'
                f'<span>Join a board</span></a></div>')
        panes = (f'<div class="mkpanes" data-mkpanes><div class="mkpane" id="mkpn" role="tabpanel" aria-labelledby="mktn"{" data-off" if joining else ""}>{new_form}</div>'
                 f'<div class="mkpane" id="mkpj" role="tabpanel" aria-labelledby="mktj"{"" if joining else " data-off"}>{join_form}</div></div>')
        head = ('<header class="mkhead"><span class="mkbadge" aria-hidden="true">'
                f'{ui.icon("folder")}</span><h3 id="mkh">{"Join a board" if joining else "New board"}</h3>'
                f'<p>{"Fill one with a friend who runs Magpiary." if joining else "A space to arrange posts, on your own or with friends."}</p></header>')
        return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg mkdlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="mkh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                f'{head}{tabs}{panes}</div></div>')
    def _stack(self, members: list, board_id: str = "") -> str:
        """The faces on a shared folder: up to four, the creator first and on top, then +N (the same overlap as the board's
        own header)."""
        shown = members[:4]
        out = "".join('<span class="bface"' + (f' data-profile="/board/{board_id}?member={m["key"]}" title="{e(m["name"] or "Someone")}"'
                                                if board_id else "") + f'>{self._face(m)}</span>' for m in shown)
        if len(members) > 4:
            out += f'<span class="bface bmorefaces">+{len(members) - 4}</span>'
        return f'<span class="bfaces fstack">{out}</span>'

    def _board_card(self, board: dict, slugs: dict | None = None, ghost: bool = False, back: bool = False) -> str:
        """A board as a folder in its own colour, its sticker on the tab and its newest cards peeking out. A shared board
        says so above its name, with the faces of the people on it; a solo board says nothing (owner, 26 Oct)."""
        v = boards.view(self.store, board["id"])
        pics = ([self._card_src(c) for c in v["cards"][:3]] + ["", "", ""])[:3]
        ppl = boards.people(v)
        n = len(v["cards"])
        peek = "".join(f'<div>{f"<img src={chr(34)}{e(p)}{chr(34)} alt={chr(34)}{chr(34)}>" if p else ""}</div>' for p in pics if p)
        badge = ""
        if v["ended"]:
            badge = f'{ui.icon("trash")}<span>Deleted by its creator</span>'
        elif v["shared"]:
            badge = (f'{self._stack(sorted(ppl, key=lambda m: not m["creator"]), board["id"])}'
                     f'<span class="btxt">Shared · {len(ppl)}</span>')
        gone_attr = (f' data-gone="{board["id"]}" data-name="{e(v["name"])}"' if ghost else
                     f' data-back="1" data-name="{e(v["name"])}"' if back else "")
        # boards are folders (piles are stacks): the board's colour, its sticker on the tab, a few cards peeking out
        return (f'<a class="pile bpile{" bgone" if ghost else ""}" href="{e(self.board_url(board["id"], slugs))}" '
                f'style="--pc:{ui.folder_colour(v["colour"])}"{gone_attr}>'
                f'<div class="folder"><i class="ftab"></i><div class="peek">{peek}</div>'
                f'<div class="flap"><div class="bshare{"" if badge else " none"}">{badge}</div>'
                f'<b>{ui.sticker(v["sticker"], "flat")}{e(v["name"])}</b><span>{n} card{"" if n == 1 else "s"}</span></div></div></a>')

    def board_slugs(self) -> dict[str, str]:
        """Every board's address by its name ({board id: slug}): lisbon-trip, and lisbon-trip-2 for a second board
        with the same name (the older board keeps the plain one). Remembered, so old addresses forward after a rename."""
        out, used = {}, set()
        for b in sorted(self.store.boards(), key=lambda b: (b["created_at"], b["id"])):
            v = boards.view(self.store, b["id"])
            base = slugify(v["name"] if v else b["name"])
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            out[b["id"]] = slug
        self.store.remember_slugs({slug: board_id for board_id, slug in out.items()})
        return out

    def board_url(self, board_id: str, slugs: dict | None = None) -> str:
        if board_id == "mock":
            return "/board/mock"
        return "/board/" + (slugs or self.board_slugs()).get(board_id, board_id)

    def board_route(self, part: str, q: dict) -> Response:
        """/board/<name>: the board; an old name or the board's id forwards to its address now."""
        if part == "mock":
            return self.board_page("mock", q)
        slugs = self.board_slugs()
        here = {slug: board_id for board_id, slug in slugs.items()}
        if part in here:
            return self.board_page(here[part], q)
        board_id = part if re.fullmatch(r"[0-9a-f]{16}", part) and self.store.board(part) else self.store.board_by_slug(part)
        if board_id in slugs:
            return Response(303, b"", headers={"Location": f"/board/{slugs[board_id]}" + (f"?{urlencode(q)}" if q else "")})
        return self.board_page(part, q)  # not found

    def offers_banner(self, back: str = "/?view=boards") -> str:
        """Invites friends sent straight to this Magpiary: join, or not now."""
        out = ""
        for o in self.store.offers()[:3]:
            who = boards.sender_name(self.store, o["sender"])
            out += (f'<div class="banner offer"><div style="flex:1;min-width:240px"><b>{e(who)} invited you to “{e(o["name"])}”</b>'
                    '<p>A shared board: you each add posts, and see who added what.</p></div>'
                    + self._form("/hub/boards/offer", {"invite": o["invite"], "act": "join", "next": back}, "Join", "btn dark")
                    + self._form("/hub/boards/offer", {"invite": o["invite"], "act": "no", "next": back}, "Not now", "btn")
                    + "</div>")
        return out

    def join_page(self, code: str) -> Response:
        """The page an invite link opens on a friend's Mac: the code filled in, one button."""
        from magpiary.hub_wall import empty_state

        if not boards.normal_code(code):
            return self.shell("Invite", empty_state("That invite link is broken", "Ask for a new one, or type the code "
                              "under Library → Boards."), "board", 404)
        form = (f'<form method="post" action="/hub/boards/join" class="bjoin big">{ui.hidden(self.csrf, next="/?view=boards")}'
                f'<input name="code" value="{e(code)}" aria-label="Invite code" readonly><button class="btn dark">Join the board</button></form>')
        return self.shell("Join a board", f'<div class="joinpage"><p class="eyebrow">A friend invited you</p><h1>Join a shared '
                          f'board</h1><p>Your Magpiary fetches the invite, opens it, and adds the board under Library → Boards. '
                          f'Only what you add to it leaves this Mac.</p>{form}</div>', "board", active="library")

    # ---- a board's page ------------------------------------------------------------------------------

    def board_page(self, board_id: str, q: dict) -> Response:
        v = self._mock_view() if board_id == "mock" else boards.view(self.store, board_id)
        if not v:
            from magpiary.hub_wall import empty_state

            return self.shell("Not found", empty_state("No such board", "It may have been removed, or the address is wrong.",
                                                              '<a class="btn dark" href="/?view=boards">Your boards</a>'), "missing", 404)
        if v.get("archived"):
            return Response(303, b"", headers={"Location": "/?view=boards"})
        sort = q.get("sort") if q.get("sort") in SORTS else "newest"
        only = "shared" if q.get("only") == "shared" else ""
        who = q.get("who", "") if q.get("who", "") in v["members"] else ""
        me = identity.public_key()
        ordered = boards.sort_cards(v["cards"], sort)  # a person opens their row only; the cards stay as they are
        filtering = bool(only)
        shown = [c for c in ordered if c["shared"]] if filtering else ordered
        faded = [c for c in ordered if c not in shown] if filtering else []
        # a long board shows a chunk at a time; the next chunk comes as the page is scrolled (`?part=N` is that chunk alone)
        part = int(q["part"]) if q.get("part", "").isdigit() else 0
        every = [*shown, *faded]
        chunk = every[part * BOARD_PAGE:(part + 1) * BOARD_PAGE]
        if board_id != "mock" and self.store.fetch_for_board(chunk):
            self.wake()  # friends' posts download and are read here (no AI), so they open like library posts
        faded_urls = {c["url"] for c in faded}
        shown_now = [c for c in chunk if c["url"] not in faded_urls]
        faded_now = [c for c in chunk if c["url"] in faded_urls]

        base = self.board_url(board_id)

        def link(**change) -> str:
            params = {"sort": sort, "only": only, "who": who, **change}
            return f"{base}?" + urlencode({k: x for k, x in params.items() if x})

        items = "".join(f'<a class="bopt{" on" if k == sort else ""}" href="{e(link(sort=k))}" role="menuitemradio" '
                        f'aria-checked="{str(k == sort).lower()}">{ui.icon("check")}<span>{e(label)}</span></a>'
                        for k, label in SORTS.items())
        sorts = (f'<details class="menu bsortmenu"><summary class="bchip"><span>Sort: <b>{e(SORTS[sort])}</b></span>'
                 f'{ui.icon("chev")}</summary><div class="pop" role="menu">{items}</div></details>')
        sorts += (f'<a class="bfilter{" on" if only else ""}" href="{e(link(only="" if only else "shared"))}" role="switch" '
                  f'aria-checked="{str(bool(only)).lower()}"><i>{ui.icon("check")}</i><span>Added by more than one</span></a>')
        mine = board_id != "mock" and v["creator"] == me
        head = self._board_head(v, board_id, mine)
        live = board_id == "mock" or not v["ended"]
        add = ("" if board_id == "mock" or not live else
               f'<a class="btn dark sm badd" href="/board/{board_id}?add=1" data-addopen data-opening="Opening…">{ui.icon("plus")}<span>Add posts</span></a>')
        ask = "" if board_id == "mock" else self.ask_button(f"board:{board_id}", cls="btn sm askbtn2")  # next to Add posts
        tools = f'<div class="bsorts">{add}{ask}{sorts}<div class="tools">{self.size_control()}</div></div>'
        from magpiary.hub_wall import empty_state

        dialog = (self._add_dialog(board_id, v, q.get("find", "")) if q.get("add") and board_id != "mock" else
                  self._welcome_dialog(v, board_id, q["welcome"] == "join") if q.get("welcome") and board_id != "mock" else
                  self._share_dialog(v, board_id) if q.get("share") and board_id != "mock" and not v["shared"] else
                  self._delete_dialog(v, board_id) if q.get("delete") and board_id != "mock" and mine else
                  self._invite_dialog(v, board_id, q.get("code") == "1") if "invite" in q and board_id != "mock"
                  else self._member_dialog(v, board_id, q["member"]) if q.get("member") in v["members"]
                  else self._card_dialog(v, board_id, q.get("card", "")))
        waiting = [] if board_id == "mock" or only or part else \
            self._board_waiting(board_id, {c["url"] for c in v["cards"]})
        more = ""
        if (part + 1) * BOARD_PAGE < len(every):
            more = (f'<div class="bskel bmore" data-bmore data-href="{e(link(part=part + 1))}" aria-label="Loading more">'
                    '<div class="grid mixes">' + '<article class="mx skel"><div class="sq"></div><div class="mxb"><i></i><i></i></div></article>' * 4
                    + '</div></div>')
        if part:  # just the next cards, for hub.js to add under the others
            return Response(200, (self._mix(shown_now, v, board_id, None, faded_now, wrap=False) + more).encode(),
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        body = (self._mix(shown_now, v, board_id, waiting, faded_now) + more if shown or waiting or faded else
                empty_state("Nothing here yet", "Add posts from your library, share one from your iPhone, or invite a "
                            "friend to fill it with you.",
                            ("" if board_id == "mock" or not live else f'<a class="btn dark" href="/board/{board_id}?add=1">Add posts</a>'
                             + (self._form("/hub/boards/invite", {"board": board_id, "next": f"/board/{board_id}"}, "Invite", "btn")
                                if v["shared"] else ""))))
        flash = ((f'<div class="flash">{e(q["note"][:200])}</div>' if q.get("note") else "")
                 + ('<div class="flash err bended"><span>This board was deleted by its creator. You can look through your copy, '
                    'but it no longer syncs and can\'t be changed.</span>'
                    + ui.button_form(self.csrf, "/hub/boards/dismiss", {"board": board_id}, "Remove it from this Mac", "btn sm")
                    + "</div>" if board_id != "mock" and v["ended"] else "")
                 + (f'<div class="flash err">{e(q["error"][:200])}</div>' if q.get("error") else ""))
        synced = q.get("note", "").startswith("Synced")
        side = self._board_side(v, board_id, link, who, synced)
        layout = (f'<div class="blay"><div class="bmain">{tools}{body}</div>'
                  f'<aside class="bside" aria-label="About this board"><button type="button" class="bsidebtn" data-sidetoggle '
                  f'aria-expanded="false">{ui.icon("info")}<span>About this board</span>{ui.icon("chev")}</button>'
                  f'<div class="bsidein">{side}</div></aside></div>')
        return self.shell(v["name"], f'<div class="bpage" data-board="{board_id}" style="--bc:{ui.folder_colour(v["colour"])}">{flash + head + layout}</div>'
                          + dialog, "board", active="library")

    def _board_mine(self, board_id: str) -> set:
        """What I put on a board, or am still putting on it (shared from the phone, being read)."""
        me = identity.public_key()
        urls = {c["url"] for c in boards.view(self.store, board_id)["cards"] if me in c["adders"]}
        return urls | {r["canonical_url"] for r in self.store.board_pending() if r["board_id"] == board_id}

    def _board_head(self, v: dict, board_id: str, mine: bool) -> str:
        """The board's sticker and name. For its creator: the sticker opens a small panel (any emoji, from the Mac's
        own emoji window, and the folder colour); the pencil makes the name editable right in the heading."""
        sticker = ui.sticker(v["sticker"], "big")
        people = sorted(v["members"].values(), key=lambda m: not m["creator"])  # the creator first, drawn on top
        names = ", ".join(m["name"] or "Someone" for m in people)
        rest = ", ".join(m["name"] or "Someone" for m in people[4:])
        faces = "" if not v.get("shared", True) else (
            f'<span class="bfaces" role="group" aria-label="People: {e(names)}">'
            + "".join(f'<a class="bface pface" href="/board/{board_id}?member={m["key"]}" '
                      f'data-tip="{e((m["name"] or "Someone") + (" · made it" if m["creator"] else ""))}" '
                      f'aria-label="Open {e(m["name"] or "Someone")}\'s profile">{self._face(m)}</a>' for m in people[:4])
            + (f'<a class="bface bmorefaces" href="#people" data-peoplejump data-tip="{e(rest)}" '
               f'aria-label="See everyone: {e(rest)}">+{len(people) - 4}</a>' if len(people) > 4 else "")
            + "</span>")
        if not mine:
            return (f'<div class="bhead"><a class="bback" href="/?view=boards">{ui.icon("chev")}<span>Boards</span></a>'
                    f'<div class="btitle">{sticker}<h1>{e(v["name"])}</h1>{faces}</div></div>')
        hidden = ui.hidden(self.csrf, board=board_id, next=f"/board/{board_id}")
        colours = "".join(f'<button type="submit" name="colour" value="{c}" class="bcol{" on" if c == v["colour"] else ""}" '
                          f'style="--c:{ui.folder_colour(c)}" aria-label="{e(label)}" title="{e(label)}"></button>'
                          for c, label in identity.COLOURS.items())
        pop = (f'<div class="stkpop" data-stkpop hidden><div class="emp" data-emp>'
               f'<input type="search" class="empsearch" data-empsearch placeholder="Search every emoji" autocomplete="off" '
               f'spellcheck="false" aria-label="Search emoji"><div class="emtabs" data-emtabs role="tablist"></div>'
               f'<div class="emgrid" data-emgrid role="listbox" aria-label="Emoji"></div></div>'
               f'<form method="post" action="/hub/boards/rename" class="stkform" data-stkform>{hidden}'
               f'<input name="name" type="hidden" value="{e(v["name"])}">'
               f'<input name="sticker" type="hidden" data-stkin></form>'
               f'<p class="stklab">Folder colour</p><form method="post" action="/hub/boards/rename" class="bcols">{hidden}'
               f'<input name="name" type="hidden" value="{e(v["name"])}">{colours}</form></div>')
        name = (f'<form method="post" action="/hub/boards/rename" class="bnameform" data-nameform>{hidden}'
                f'<input type="hidden" name="name" value="{e(v["name"])}" maxlength="{boards.NAME_MAX}">'
                f'<h1 data-name>{e(v["name"])}</h1>'
                f'<button type="button" class="bpen" data-renamebtn aria-label="Rename the board" title="Rename">{ui.icon("summary")}</button>'
                f'<span class="bnameacts"><button class="btn sm dark" data-namesave>Save</button>'
                f'<button type="button" class="btn sm quiet" data-namecancel>Cancel</button></span></form>')
        return (f'<div class="bhead"><a class="bback" href="/?view=boards">{ui.icon("chev")}<span>Boards</span></a>'
                f'<div class="btitle"><span class="bstkwrap"><button type="button" class="bstk" data-stickerpick '
                f'aria-label="Change the sticker or colour" title="Change the sticker or colour">{sticker}</button>{pop}</span>'
                f'{name}{faces}</div></div>')

    def _activity(self, board_id: str) -> dict:
        """Per member, from their events: when they joined, their last change (any kind) and their last add or vote."""
        out: dict = {}
        for ev in self.store.board_events(board_id) if board_id != "mock" else []:
            m = out.setdefault(ev["member"], {"joined": ev["at"], "seen": 0, "last": None})
            m["joined"] = min(m["joined"], ev["at"])
            m["seen"] = max(m["seen"], ev["at"])
            if ev["type"] in ("add", "vote", "create", "rename") and (not m["last"] or ev["at"] >= m["last"]["at"]):
                m["last"] = ev
        return out

    def _board_side(self, v: dict, board_id: str, link, who: str = "", synced: bool = False) -> str:
        """The column beside the cards: Sync now and Invite, my library switch, who is on the board (the chosen person
        opened in place, with their numbers and Remove), the board in numbers, and how it syncs."""
        me = identity.public_key()
        act = self._activity(board_id)
        here = {"board": board_id, "next": f"/board/{board_id}"}
        acts = "" if board_id == "mock" or not v["shared"] or v["ended"] else (
            '<div class="bbtns">'
            + ui.button_form(self.csrf, "/hub/boards/sync", here,
                             f'{ui.icon("refresh")}{ui.icon("check", "ico ok")}<span>{"Up to date" if synced else "Sync now"}</span>',
                             "cbtn sync" + (" fresh" if synced else ""), busy="Syncing…")
            + (ui.button_form(self.csrf, "/hub/boards/invite", here, f'{ui.icon("people")}<span>Invite</span>',
                              "cbtn invite", busy="Opening…") if v["via"] == "nostr" or v["creator"] == me else "")
            + "</div>")
        people = ""
        for m in v["members"].values():
            a = act.get(m["key"], {})
            seen, name, opened = a.get("seen"), m["name"] or "Someone", m["key"] == who
            row = (f'<a class="bperson" href="{e(link(who="" if opened else m["key"]))}" aria-expanded="{str(opened).lower()}">'
                   f'{self._face(m)}<span><b>{e(name)}{" (you)" if m["key"] == me else ""}</b>'
                   f'<small>{m["cards"]} card{"" if m["cards"] == 1 else "s"}'
                   f'{" · made it" if m["creator"] else ""}{f" · active {_when(seen)}" if seen else ""}</small></span>'
                   f'{ui.icon("chev")}</a>')
            more = ""
            if opened:
                votes = sum(1 for c in v["cards"] if c["votes"].get(m["key"]))
                last = a.get("last")
                what = ({"add": "Added a card", "vote": "Voted", "create": "Made the board", "rename": "Renamed it"}
                        [last["type"]] + " " + _when(last["at"])) if last else "Nothing yet"
                facts = "".join(f'<div><span>{label}</span><b>{e(val)}</b></div>' for label, val in (
                    ("Cards added", str(m["cards"])), ("Votes given", str(votes)),
                    ("Joined", _day(a["joined"]) if a.get("joined") else "—"), ("Last contribution", what),
                    ("Last change seen", _when(seen) if seen else "—"), ("ID", m["key"][:8])))
                remove = ""
                if v["creator"] == me and m["key"] != me and board_id != "mock":
                    remove = ui.button_form(
                        self.csrf, "/hub/boards/remove-member", {"board": board_id, "who": m["key"], "next": f"/board/{board_id}"},
                        f"Remove {e(name)} from the board…", "btn sm danger bkick",
                        confirm=f"Remove {name} from the board? Their cards and votes leave it, and the board gets a new "
                                "key they don't receive. They keep what's already on their Mac.")
                more = f'<div class="bmore"><div class="bfacts">{facts}</div>{remove}</div>'
            people += f'<div class="bpwrap{" open" if opened else ""}" style="--c:{e(m["colour"])}">{row}{more}</div>'
        cards = v["cards"]
        votes = sum(1 for c in cards for x in c["votes"].values() if x)
        both = sum(1 for c in cards if c["shared"])
        stats = "".join(f'<div><b>{n}</b><span>{label}</span></div>' for n, label in (
            (len(cards), "cards"), (len(v["members"]), "people"), (votes, "votes"), (both, "added by more than one")))
        latest = max((a["last"] for a in act.values() if a.get("last")), key=lambda ev: ev["at"], default=None)
        last = ""
        if latest:
            name = (v["members"].get(latest["member"]) or {}).get("name") or "Someone"
            what = {"add": "added a card", "vote": "voted", "create": "made the board", "rename": "renamed the board"}[latest["type"]]
            last = f'<p class="bline">{ui.icon("clock")}<span>{e(name)} {what} {_when(latest["at"])}</span></p>'
        creator = v["members"].get(v["creator"]) or {}
        made = act.get(v["creator"], {}).get("joined")
        made_line = (f'<p class="bline">{ui.icon("plus")}<span>Made by {e(creator.get("name") or "someone")}'
                     f'{" on " + _day(made) if made else ""}</span></p>')
        entry = boards._keys().get(board_id, {}).get("code") if board_id != "mock" else None
        code = (f'<p class="bline">{ui.icon("people")}<span>Invite code works until {_day(entry["expires"])}</span></p>'
                if entry and entry["expires"] > time.time() else "")
        via = "Nostr relays" if v["via"] == "nostr" else "your bucket" if v["creator"] == me else "the creator's bucket"
        sync = (f'<p class="bline bad">{ui.icon("refresh")}<span title="{e(v["sync_error"])}">{e(sync_words(v["sync_error"]))}</span></p>'
                if v["sync_error"] else
                f'<p class="bline">{ui.icon("refresh")}<span>Synced {e(_ago(v["synced_at"]))} through {via}</span></p>'
                if v["synced_at"] else f'<p class="bline">{ui.icon("refresh")}<span>Not synced yet · through {via}</span></p>')
        on = bool((self.store.board(board_id) or {}).get("to_library"))
        lib = ""
        if board_id != "mock":
            if on:
                n = self.store.from_library(board_id, dry=True)
                ask = ("Turn off “Also add to my library”? Posts you share to this board from your iPhone will stay only "
                       "on the board. " + (f"{n} post{'' if n == 1 else 's'} this switch put in your library will leave it "
                       "(they stay on the board). Posts you also saved yourself stay." if n else "Nothing leaves your library."))
            else:
                n = self.store.to_library(board_id, self._board_mine(board_id), dry=True)
                ask = ("Turn on “Also add to my library”? Posts you share to this board from your iPhone will also go into "
                       "your library. " + (f"{n} post{'' if n == 1 else 's'} you already shared to it will be added to your "
                       "library now." if n else "Nothing already shared needs adding."))
            lib = (f'<section><div class="blib"><span><b>Also add to my library</b><small>Posts you share to this board from '
                   f'your iPhone {"go into your library too" if on else "stay only on the board"}.</small></span>'
                   + self._switch("/hub/boards/to-library", on, {"board": board_id, "next": f"/board/{board_id}"},
                                  {"board": board_id, "value": "1", "next": f"/board/{board_id}"}, "Also add to my library",
                                  confirm=ask)
                   + '</div></section>')
        return (f'{acts}{lib}{self._sharing_block(v, board_id)}<section id="people"><h2>People</h2><div class="bpeople">{people}</div></section>'
                f'<section><h2>This board</h2><div class="bstats">{stats}</div>{last}{made_line}{code}</section>'
                + (f'<section><h2>Sync</h2>{sync}<p class="bnote">Checks for friends\' changes every 30 seconds while '
                   f'this page is open, and every 15 minutes otherwise.</p></section>' if v["shared"] and not v["ended"] else
                   '<section><h2>Sync</h2><p class="bline">' + ui.icon("lock") + '<span>Only on this Mac. Nothing of this board is '
                   'sent anywhere.</span></p></section>' if not v["shared"] else "")
                + self._danger_block(v, board_id))

    def _sharing_block(self, v: dict, board_id: str) -> str:
        """The creator's Share this board switch. Turning it on starts sync and shows Invite; it can only go off while
        nobody else is on the board."""
        if board_id == "mock" or v["creator"] != identity.public_key() or v["ended"]:
            return ""
        alone = len(boards.people(v)) <= 1
        via = "your own storage bucket" if new_board_via(self.store) == "bucket" else "encrypted Nostr relays"
        on = v["shared"]
        fields = {"board": board_id, "next": f"/board/{board_id}"}
        page_link = f"/board/{board_id}"
        ask = "Stop sharing? The board goes back to only this Mac."
        text = ("Only on this Mac. Turn on to invite friends. The posts you add are then sent, encrypted, through " + via + " to the people you invite." if not on else
                "Friends you invite see this board and can add and vote." + ("" if alone else
                " It can go back to solo once you are the only one on it."))
        if not on:
            switch = (f'<a class="sw" role="switch" aria-checked="false" aria-label="Share this board" '
                      f'href="{page_link}?share=1" data-opening><span></span></a>')
        elif alone:
            switch = self._switch("/hub/boards/unshare", on, fields, fields, "Share this board", confirm=ask)
        else:
            switch = ('<button type="button" class="sw on" role="switch" aria-checked="true" disabled '
                      'title="Other people are on this board" aria-label="Share this board"><span></span></button>')
        return (f'<section><div class="blib"><span><b>Share this board</b><small>{e(text)}</small></span>{switch}</div></section>')

    def _danger_block(self, v: dict, board_id: str) -> str:
        """Delete (the creator: archived for 30 days) or Leave (everyone else); nothing here for the example board."""
        if board_id == "mock":
            return ""
        if v["creator"] == identity.public_key():
            return (f'<section class="bdanger"><h2>Delete this board</h2><p class="bnote">Hidden for 30 days, then gone. '
                    f'Your library posts stay.</p><a class="btn sm danger" href="/board/{board_id}?delete=1" data-opening="Opening…"><span>Delete board…</span></a></section>')
        if v["ended"]:
            return ""
        return ('<section class="bdanger"><h2>Leave this board</h2><p class="bnote">The board leaves this Mac and the others '
                'are told. The cards you added stay on it.</p>'
                + ui.button_form(self.csrf, "/hub/boards/leave", {"board": board_id}, "Leave board", "btn sm danger",
                                 confirm="Leave this board? It leaves this Mac, and the cards you added stay on it for the others.")
                + '</section>')

    def add_rows(self, board_id: str, query: str) -> str:
        """The Add posts window's list: the newest saves, or what matches the search (library and archive)."""
        v = boards.view(self.store, board_id)
        on_board = {c["url"] for c in v["cards"] if identity.public_key() in c["adders"]} if v else set()
        items = (self.store.hub_items("kept", query, limit=40) if query.strip()
                 else self.store.hub_items("kept", limit=40))
        rows = ""
        for i in items:
            if i.get("status") != "archived":
                continue
            there = i["canonical_url"] in on_board
            thumb = self.thumb_url(i)
            kind = ("On the board" if there else ui.type_name(i.get("ai_type")) if i.get("ai_status") == "done"
                    else ui.source_label(i)) + (" · Archived" if i.get("shelf") == "archive" and not there else "")
            art = (f'<img src="{e(thumb)}" alt="" loading="lazy">' if thumb else
                   f'<i style="background:{ui.gradient(i)}"></i>')
            rows += (f'<label class="apick{" there" if there else ""}"><input type="checkbox" name="pick" value="{i["id"]}"'
                     f'{" disabled checked" if there else ""}><span class="apic">{art}'
                     f'<em class="atick">{ui.icon("check")}</em></span>'
                     f'<b>{e(ui.title_of(i))}</b><small>{e(kind)}</small></label>')
        return rows or f'<p class="anone">Nothing matches “{e(query)}”.</p>'

    def _add_dialog(self, board_id: str, v: dict, query: str) -> str:
        """Add posts as a window over the board: newest first, a search that narrows with every letter, tick several."""
        back = f"/board/{board_id}"
        return (f'<div class="dlg-wrap qrwrap addwrap" data-close="{back}"><div class="dlg adddlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="addh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                f'<header class="ahead">{ui.sticker(v["sticker"])}<div><h3 id="addh">Add to {e(v["name"])}</h3>'
                f'<p>From your library and archive.</p></div></header>'
                f'<label class="asearch">{ui.icon("search")}<input type="search" value="{e(query)}" placeholder="Search what was '
                f'said, shown or written" aria-label="Search your library" autocomplete="off" data-addsearch="/board/{board_id}/pick" autofocus></label>'
                f'<form method="post" action="/hub/bulk" class="addpicks" data-addpicks>'
                f'{ui.hidden(self.csrf, action="board", board=board_id, ids="", next=back)}'
                f'<div class="alist" data-addlist>{self.add_rows(board_id, query)}</div>'
                + self._share_page_box() +
                f'<div class="afoot"><span data-addcount>Tick the posts to add</span>'
                f'<button class="btn dark" data-addgo disabled>Add to the board</button></div></form></div></div>')

    def _share_page_box(self) -> str:
        """In Add posts: the choice to send the text of saved pages too, only when the library has some. Off unless ticked."""
        newest = [i for i in self.store.hub_items("kept", limit=40) if i.get("status") == "archived"]
        if not any(boards.captured_article(i, self.library) for i in newest):
            return ""
        return ('<label class="small sharepage" style="display:block;margin:8px 4px"><input type="checkbox" name="page" value="1"> '
                'Also share the page text of pages I saved with Save what I see<br><span class="muted">Board members can read '
                'it. Pictures stay on this Mac. Off unless you tick it.</span></label>')

    def _welcome_dialog(self, v: dict, board_id: str, joined: bool) -> str:
        """The first visit to a board (for now after every new or joined board; later only the first): how to fill it,
        then, for a board you made, whether to share it. Two steps in one frame (owner, 27 Oct 2026)."""
        back = f"/board/{board_id}"
        via = "your own storage bucket" if new_board_via(self.store) == "bucket" else "encrypted Nostr relays"
        picker = (f'<div class="wlpick" aria-hidden="true"><div class="wlph">Magpiary Board · pick a board</div>'
                  f'<div class="wlrow dim"><span>🍝</span>Recipes</div>'
                  f'<div class="wlrow on">{ui.sticker(v["sticker"], "flat")}<b>{e(v["name"])}</b>{ui.icon("check")}</div>'
                  f'<div class="wlrow dim"><span>🎁</span>Gift ideas</div></div>')
        library = ('<div class="wlviz wllib" aria-hidden="true"><span class="wladd">' + ui.icon("plus") + '<span>Add posts</span></span>'
                   '<div class="wltiles"><i style="--c:#2f6bff"></i><i style="--c:#ff2e93"></i><i style="--c:#00a37a"></i>'
                   '<i style="--c:#f5a300"></i><i style="--c:#8a3ffc"></i><i style="--c:#0091b3"></i></div></div>')
        fill = ('<div class="wlways">'
                f'<div class="wlway"><span class="seticon" style="--c:#2f6bff">{ui.icon("plus")}</span><b>From your library</b>'
                '<p>Press <b>Add posts</b> on the board, or choose “Add to board…” on any post you have saved.</p>' + library + '</div>'
                f'<div class="wlway"><span class="seticon" style="--c:#ff2e93">{ui.icon("phone")}</span><b>From your iPhone</b>'
                '<p>In the share sheet pick <b>Magpiary Board</b>, then choose this board.</p>' + picker + '</div></div>')
        head1 = ('<header class="mkhead"><span class="mkbadge" aria-hidden="true">' + ui.icon("folder") + '</span>'
                 f'<h3 id="wlh">{"You joined " if joined else ""}{e(v["name"])}</h3>'
                 f'<p>{"Add posts, and see what your friends add." if joined else "Two ways to fill it."}</p></header>')
        step1 = (f'<div class="mkpane wlpane" data-step="1">{head1}{fill}'
                 + (f'<div class="wlgo"><a class="btn dark" href="{back}">Got it</a></div>' if joined else
                    '<div class="wlgo"><button type="button" class="btn dark" data-wl="2">Next</button>'
                    f'<a class="btn quiet" href="{back}">Skip</a></div>')
                 + '</div>')
        if joined:
            return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg mkdlg wldlg" role="dialog" aria-modal="true" '
                    f'aria-labelledby="wlh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>{step1}</div></div>')
        head2 = ('<header class="mkhead"><span class="mkbadge" style="background:linear-gradient(145deg,#8b5cf6,#ff2e93)" aria-hidden="true">'
                 + ui.icon("people") + '</span><h3>Share this board?</h3>'
                 '<p>You can invite friends to add and vote. Only what you add leaves this Mac.</p></header>')
        sub = (f'<p class="bsub">{ui.icon("lock")}<span>Behind the scenes: the board syncs through {via}. Everything is sealed with '
               f'the board\'s key before it leaves, so relays only pass on copies that you and your friends can open.</span></p>')
        step2 = (f'<div class="mkpane wlpane" data-step="2" data-off>{head2}{sub}'
                 f'<form method="post" action="/hub/boards/share" class="bsharego wlgo" data-morph data-busy-label="Sharing…">'
                 f'{ui.hidden(self.csrf, board=board_id, invite="1")}'
                 f'<button class="btn dark" type="submit">{ui.icon("people")}<span>Share and invite</span></button>'
                 f'<a class="btn quiet" href="{back}">Not now</a></form></div>')
        return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg mkdlg wldlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="wlh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                f'<div class="mkpanes" data-wlpanes>{step1}{step2}</div></div></div>')

    def _share_dialog(self, v: dict, board_id: str) -> str:
        """Turning sharing on: what it means first, how it works as a quiet note below, and one button that shares and
        goes straight on to inviting (owner, 26 Oct 2026)."""
        back = f"/board/{board_id}"
        via = ("your own storage bucket" if new_board_via(self.store) == "bucket" else
               "encrypted Nostr relays")
        form = (f'<form method="post" action="/hub/boards/share" class="bsharego" data-morph data-busy-label="Sharing…">{ui.hidden(self.csrf, board=board_id, invite="1")}'
                f'<button class="btn dark" type="submit">{ui.icon("people")}<span>Share and invite</span></button>'
                f'<a class="btn quiet" href="{back}">Not now</a></form>')
        return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="shh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                + f'<header class="ihero"><span class="seticon" style="--c:#8b5cf6">{ui.icon("people")}</span>'
                f'<div><h3 id="shh">Share this board</h3><p>You can invite friends to add and vote. Only what you add leaves this Mac.</p></div></header>'
                f'<p class="bsub">{ui.icon("lock")}<span>Behind the scenes: the board syncs through {via}. Everything is sealed with '
                f'the board\'s key before it leaves, so relays only pass on copies that you and your friends can open.</span></p>'
                f'{form}</div></div>')

    def _delete_dialog(self, v: dict, board_id: str) -> str:
        """Deleting a board: what happens to it and its posts, and the tick that confirms."""
        back = f"/board/{board_id}"
        n = len(boards.people(v)) - 1
        ends = (f'<li>It also ends for the {n} other {"person" if n == 1 else "people"} on it. They keep a read-only copy until '
                f'they remove it.</li>' if n > 0 else "")
        return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="dlh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                f'<header class="ihero"><span class="seticon" style="--c:#e5484d">{ui.icon("trash")}</span>'
                f'<div><h3 id="dlh">Delete “{e(v["name"])}”?</h3><p>You can restore it for 30 days.</p></div></header>'
                f'<ul class="bdlist"><li>Posts in your library stay in your library.</li>'
                f'<li>Posts that are only on this board, not saved in your library, are archived with it.</li>'
                f'<li>The board is hidden. Restore it from “Deleted boards” in the Boards view within 30 days; after that it is deleted for good.</li>{ends}</ul>'
                f'<form method="post" action="/hub/boards/delete" class="bsharego" data-busy-label="Deleting…" data-hold="1600" data-dissolve>{ui.hidden(self.csrf, board=board_id)}'
                f'<label class="back"><input type="checkbox" name="ack" value="1" required> I understand</label>'
                f'<button class="btn danger" type="submit" disabled>{ui.icon("trash")}<span>Delete board</span></button><a class="btn quiet" href="{back}">Cancel</a></form>'
                f'</div></div>')

    def _invite_dialog(self, v: dict, board_id: str, auto: bool = False) -> str:
        """Invite on the board itself: the board's code first (with New code beside it), the QR, then sending it with
        the Mac's Share menu; below, the people already shared with, who get the invite straight in their Magpiary."""
        back = f"/board/{board_id}"
        people = "".join(
            f'<div class="ifr">{self._face(m)}<span><b>{e(m["name"] or "Someone")}</b><small>On a board with you</small></span>'
            + ui.button_form(self.csrf, "/hub/boards/invite-friend", {"board": board_id, "who": m["key"], "next": back + "?invite=1"},
                             f'{ui.icon("send")}<span>Invite</span>', "btn sm") + "</div>"
            for m in boards.friends(self.store, board_id))
        entry = boards._keys().get(board_id, {}).get("code")
        live = entry and entry["expires"] > time.time() and entry["key_tag"] == boardsync.board_tag(boards.board_key(board_id))
        if live:
            code = entry["code"]
            until = datetime.fromtimestamp(entry["expires"]).strftime("%-d %b")
            link = f"http://localhost:{default_port()}/join/{code}"
            message = (f"Join my Magpiary board “{v['name']}”. Code: {code}. On your Mac with Magpiary running, open "
                       f"{link} (works until {until}).")
            qr = segno.make(link, error="m")
            png = io.BytesIO()
            qr.save(png, kind="png", scale=8, border=2)
            renew = ui.button_form(self.csrf, "/hub/boards/new-code", {"board": board_id, "next": back},
                                   f'{ui.icon("refresh")}<span>New code</span>', "ilink",
                               confirm="Make a new code? The current one stops working for anyone who hasn't joined yet.")
            share = (f'<div class="icard"><div class="ihead"><span>Invite code</span>{renew}</div>'
                     f'<button type="button" class="icode" data-copycode="{e(code)}" data-copywhat="Code" title="Copy the code">'
                     f'<b class="mono">{e(code)}</b>{ui.icon("copy")}</button>'
                     f'<p class="imeta">For anyone you send it to · works until {e(until)} · renews by itself</p>'
                     f'<div class="iqr">{qr.svg_inline(scale=5, dark="#111", light="#fff")}</div>'
                     f'<p class="imeta">Or scan it: it opens the join link</p></div>'
                     f'<div class="ishare"><button type="button" class="btn dark" data-share="{e(message)}" '
                     f'data-sharetitle="Join “{e(v["name"])}” on Magpiary" data-sharepng="{base64.b64encode(png.getvalue()).decode()}">'
                     f'{ui.icon("share")}<span>Share…</span></button>'
                     f'<button type="button" class="btn" data-copycode="{e(message)}" data-copywhat="Message">'
                     f'{ui.icon("copy")}<span>Copy message</span></button></div>')
        else:
            share = ('<div class="icard empty"><p>One code for everyone you want on this board.</p>'
                     + (f'<form method="post" action="/hub/boards/invite" data-auto data-busy-label="Making your code…">'
                        f'{ui.hidden(self.csrf, board=board_id, next=back)}<button class="btn dark" type="submit">'
                        f'{ui.icon("refresh")}<span>Show the invite code</span></button></form>' if auto else
                        self._form("/hub/boards/invite", {"board": board_id, "next": back}, "Show the invite code", "btn dark"))
                     + "</div>")
        return (f'<div class="dlg-wrap qrwrap" data-close="{back}"><div class="dlg invdlg" role="dialog" aria-modal="true" '
                f'aria-labelledby="invh"><a class="rb iclose" href="{back}" aria-label="Close">✕</a>'
                + f'<header class="ihero"><span class="seticon" style="--c:#ffc83d">{ui.icon("people")}</span>'
                f'<div><h3 id="invh">Invite to {e(v["name"])}</h3><p>They need Magpiary on their own Mac.</p></div></header>'
                f'{share}'
                + (f'<section class="ifriends"><h4>{ui.icon("people")}People you\'ve shared boards with</h4>'
                   f'<p>They get it straight in their Magpiary, no message needed.</p><div class="ifrs">{people}</div></section>'
                   if people else "")
                + '</div></div>')

    def _tile(self, board_id: str, c: dict, cls: str = "ptile") -> str:
        """A small card: its picture, or (no picture) a colour tile with where it came from and its title."""
        src = self._card_src(c)
        title = e((c.get("title") or c["url"])[:90])
        href = f'/board/{board_id}?card={_cid(c["url"])}'
        if src:
            return f'<a class="{cls}" href="{href}" aria-label="{title}"><img src="{e(src)}" alt="" loading="lazy"><span>{title}</span></a>'
        colour = ui.type_colour(c.get("kind"))
        return (f'<a class="{cls} bare" href="{href}" aria-label="{title}" style="--k:{colour}"><i>'
                f'{e(ui.source_name(c.get("source") or ""))}</i><b>{title}</b></a>')

    def _member_dialog(self, v: dict, board_id: str, key: str) -> str:
        """Someone's profile, opened from a face: who they are, their latest cards on this board (all of them behind
        "See all"), and the boards you share with them."""
        m = v["members"][key]
        me = identity.public_key()
        theirs = sorted((c for c in v["cards"] if key in c["adders"]), key=lambda c: -(c["adders"].get(key) or 0))
        tiles = "".join(self._tile(board_id, c) for c in theirs[:200])
        shared = []
        if board_id != "mock" and key != me:
            for b in self.store.boards():
                if b["archived_at"] or b["ended"] or b["id"] == board_id:
                    continue
                other = boards.view(self.store, b["id"])
                if key in other["members"]:
                    shared.append(f'<a href="/board/{b["id"]}">{e(other["name"])}</a>')
        count = len(theirs)
        who = "You" if key == me else e(m["name"] or "Someone")
        return (f'<div class="dlg-wrap qrwrap bcardwrap" data-close="/board/{board_id}"><div class="dlg bmember" role="dialog" '
                f'aria-modal="true" aria-label="Profile: {e(m["name"] or "Someone")}">'
                + self._person(m)
                + f'<p class="pstat">{who} added <b>{count}</b> card{"" if count == 1 else "s"} to {e(v["name"])}'
                f'{" · made the board" if m.get("creator") else ""}.</p>'
                + (f'<div class="ptiles" data-clamp>{tiles}</div><button type="button" class="btn sm pseeall" data-seeall hidden '
                   f'aria-expanded="false">See all {count}</button>' if tiles else "")
                + (f'<p class="pshared"><small>Boards you share</small>{"".join(shared)}</p>' if shared else "")
                + f'<a class="rb bclose" href="/board/{board_id}" aria-label="Close">✕</a></div></div>')

    def _card_dialog(self, v: dict, board_id: str, cid: str) -> str:
        """A card opened on the board: read-only, with who added it, the votes, and the way to the post."""
        card = next((c for c in v["cards"] if _cid(c["url"]) == cid), None) if cid else None
        if not card:
            return ""
        me = identity.public_key()
        adders = [v["members"][w] for w in card["adders"] if w in v["members"]]
        src = self._card_src(card)
        colour = ui.type_colour(card.get("kind"))
        mine = self.store.item_by_url(card["url"])
        tags = "".join(f"<span>#{e(x)}</span>" for x in (card.get("tags") or []))
        links = "".join(f'<a href="{e(link["url"])}" target="_blank" rel="noopener noreferrer">{e(link["name"] or link["url"])} ↗</a>'
                        for link in card.get("links") or [])
        note = f'<blockquote>{e(card["note"])}</blockquote>' if card.get("note") else ""
        actions = (f'<a class="btn dark" href="{e(card["url"])}" target="_blank" rel="noopener noreferrer">Open the post ↗</a>'
                   + (f'<a class="btn" href="/item/{mine["id"]}">Open in my library</a>' if mine and mine["shelf"] != "board" else "")
                   + (self._form("/hub/shelf", {"id": mine["id"], "shelf": "inbox", "next": f"/board/{board_id}?card={cid}"},
                                 "Add to my library", "btn") if mine and mine["shelf"] == "board" else "")
                   + (self._form("/hub/boards/remove-card", {"board": board_id, "url": card["url"], "next": f"/board/{board_id}"},
                                 "Take it off the board", "btn", confirm="Take your card off the board? Friends who already "
                                 "synced it are asked to hide it.") if me in card["adders"] and board_id != "mock" else ""))
        return (f'<div class="dlg-wrap qrwrap bcardwrap" data-close="/board/{board_id}"><div class="dlg bcard" role="dialog" '
                f'aria-modal="true" aria-label="{e(card.get("title") or "Card")}" style="--c:{colour};--cd:{ui.deep(colour)}">'
                + (f'<img src="{e(src)}" alt="">' if src else "")
                + f'<div class="bcb"><span class="kind">{e(ui.type_name(card.get("kind")))}</span><h3>{e(card.get("title") or card["url"])}</h3>'
                f'<p class="by">{self._faces(adders, board_id)}Added by {e(_by(adders))}{" · ♥ more than one of you" if card["shared"] else ""}</p>'
                f'{note}<p>{e(card.get("summary") or "")}</p><div class="ptags">{tags}</div>'
                + (f'<div class="blinks">{links}</div>' if links else "")
                + f'<div class="bcfoot">{self._votes(card, board_id)}<span class="bsp"></span>{actions}</div></div>'
                f'<a class="rb bclose" href="/board/{board_id}" aria-label="Close">✕</a></div></div>')

    def boards_post(self, path: str, form: dict) -> Response | None:
        """New board and votes. None for a path this does not handle."""
        if path == "/hub/boards/new":
            had_boards = bool(self.store.boards())  # someone who already has boards has seen what a board is
            try:
                board_id = boards.create(self.store, form.get("name", ""), new_board_via(self.store))
            except ValueError as err:
                return Response(303, b"", headers={"Location": "/?view=boards&error=" + quote(str(err))})
            first = not had_boards and not self.store.get_setting("board_welcome_seen")  # the welcome comes with the first board only
            self.store.set_setting("board_welcome_seen", "1")
            return Response(303, b"", headers={"Location": f"/board/{board_id}" + ("?welcome=1" if first else "")})
        if path in ("/hub/boards/invite", "/hub/boards/new-code", "/hub/boards/invite-friend"):
            board_id = form.get("board", "")
            if not self.store.board(board_id):
                return Response(303, b"", headers={"Location": "/?view=boards"})
            try:
                if path.endswith("friend"):
                    boards.invite_friend(self.store, board_id, form.get("who", ""), self.sync_call, self.relay_connect)
                    who = next((m["name"] for m in boards.friends(self.store) if m["key"] == form.get("who")), "them")
                    return Response(303, b"", headers={"Location": f"/board/{board_id}?invite=1&note=" + quote(f"Invite sent to {who}.")})
                boards.board_code(self.store, board_id, self.sync_call, self.relay_connect, renew=path.endswith("new-code"))
            except (PermissionError, ValueError, boards.boardsync.SyncError) as err:
                return Response(303, b"", headers={"Location": f"/board/{board_id}?invite=1&error=" + quote(str(err)[:200])})
            return Response(303, b"", headers={"Location": f"/board/{board_id}?invite=1"})
        if path == "/hub/boards/join":
            try:
                board_id = boards.join(self.store, form.get("code", ""), self.relay_connect)
            except ValueError as err:
                return Response(303, b"", headers={"Location": "/?view=boards&error=" + quote(str(err)[:200])})
            self.sync_boards()
            return Response(303, b"", headers={"Location": f"/board/{board_id}?welcome=join"})
        if path == "/hub/boards/offer":
            invite = form.get("invite", "")
            if form.get("act") == "join":
                try:
                    board_id = boards.accept_offer(self.store, invite, self.relay_connect)
                except ValueError as err:
                    return Response(303, b"", headers={"Location": "/?view=boards&error=" + quote(str(err)[:200])})
                self.sync_boards()
                return Response(303, b"", headers={"Location": f"/board/{board_id}?welcome=join"})
            self.store.set_offer(invite, "dismissed")
            return Response(303, b"", headers={"Location": form.get("next", "/") if form.get("next", "").startswith("/") else "/"})
        if path == "/hub/boards/to-library":
            board_id = form.get("board", "")
            if not self.store.board(board_id):
                return Response(303, b"", headers={"Location": "/?view=boards"})
            on = form.get("value") == "1"
            self.store.update_board(board_id, to_library=int(on))
            if on:
                moved = self.store.to_library(board_id, self._board_mine(board_id))
                note = "Posts you share to this board go into your library too." + (
                    f" {moved} added to your library." if moved else "")
            else:
                moved = self.store.from_library(board_id)
                note = "Posts you share to this board stay only on the board." + (
                    f" {moved} left your library." if moved else "")
            return Response(303, b"", headers={"Location": f"/board/{board_id}?note=" + quote(note)})
        if path == "/hub/boards/rename":
            board_id = form.get("board", "")
            if self.store.board(board_id):
                try:
                    boards.rename(self.store, board_id, form.get("name", ""), form.get("sticker", ""), form.get("colour", ""))
                except PermissionError as err:
                    return Response(303, b"", headers={"Location": f"/board/{board_id}?error=" + quote(str(err))})
                self.sync_boards()
            return Response(303, b"", headers={"Location": f"/board/{board_id}"})
        if path in ("/hub/boards/remove-card", "/hub/boards/remove-member"):
            board_id = form.get("board", "")
            if self.store.board(board_id):
                try:
                    if path.endswith("card"):
                        boards.remove_card(self.store, board_id, form.get("url", ""))
                    else:
                        boards.remove_member(self.store, board_id, form.get("who", ""), self.sync_call)
                except (PermissionError, ValueError) as err:
                    return Response(303, b"", headers={"Location": f"/board/{board_id}?error=" + quote(str(err))})
                self.sync_boards()
            return Response(303, b"", headers={"Location": _back(form, f"/board/{board_id}")})
        if path in ("/hub/boards/share", "/hub/boards/unshare", "/hub/boards/delete", "/hub/boards/restore",
                    "/hub/boards/leave", "/hub/boards/dismiss"):
            return self._board_life(path.rsplit("/", 1)[1], form)
        if path == "/hub/boards/vote":
            board_id = form.get("board", "")
            if self.store.board(board_id) and form.get("value") in ("1", "0", "-1") and form.get("url", "").startswith("http"):
                boards.vote(self.store, board_id, form["url"], int(form["value"]))
                self.sync_boards()
            return Response(303, b"", headers={"Location": _back(form, f"/board/{board_id}") if self.store.board(board_id) else "/?view=boards"})
        return None

    def _board_life(self, act: str, form: dict) -> Response:
        """Share, stop sharing, delete, restore, leave, or dismiss a deleted board (owner, 26 Oct 2026)."""
        board_id = form.get("board", "")
        board = self.store.board(board_id)
        page = f"/board/{board_id}"
        if not board:
            return Response(303, b"", headers={"Location": "/?view=boards"})
        try:
            if act == "share":
                boards.share(self.store, board_id, new_board_via(self.store))
                self.sync_boards()
                if form.get("invite"):
                    # the invite dialog makes the code itself as it opens (the relays can be slow): one flow
                    return Response(303, b"", headers={"Location": page + "?invite=1&code=1"})
                note = "This board is shared now: you can invite people, and it syncs."
            elif act == "unshare":
                boards.unshare(self.store, board_id)
                note = "This board is only on this Mac again."
            elif act == "delete":
                if form.get("ack") != "1":
                    return Response(303, b"", headers={"Location": page + "?error=" + quote("Tick the box to confirm.")})
                boards.end_board(self.store, board_id)
                self.sync_boards()
                return Response(303, b"", headers={"Location": "/?view=boards&gone=" + board_id})
            elif act == "restore":
                boards.restore_board(self.store, board_id)
                self.sync_boards()
                if form.get("next", "").startswith("/?view=boards"):  # from the Deleted boards list: its folder grows back
                    return Response(303, b"", headers={"Location": "/?view=boards&back=" + board_id})
                return Response(303, b"", headers={"Location": self.board_url(board_id)})
            elif act == "leave":
                boards.leave_board(self.store, board_id, self.relay_connect, self.sync_call)
                return Response(303, b"", headers={"Location": "/?view=boards"})
            else:
                boards.dismiss_board(self.store, board_id)
                return Response(303, b"", headers={"Location": "/?view=boards"})
        except (PermissionError, ValueError, boards.boardsync.SyncError) as err:
            return Response(303, b"", headers={"Location": page + "?error=" + quote(str(err)[:200])})
        return Response(303, b"", headers={"Location": page + "?note=" + quote(note)})

    # ---- the cards ----------------------------------------------------------------------------------

    def _board_waiting(self, board_id: str, on_board: set) -> list[dict]:
        """Posts this Mac was asked to put on the board that are still being read, oldest first."""
        out = []
        for row in self.store.board_pending():
            item = self.store.item_by_url(row["canonical_url"]) if row["board_id"] == board_id else None
            if item and item["canonical_url"] not in on_board:
                out.append(item)
        return out

    def _waiting_tile(self, item: dict) -> str:
        """A post on its way to the board: its picture once fetched, and what is still happening. Only on this Mac."""
        src = self.thumb_url(item)
        colour = ui.type_colour(item.get("ai_type"))
        title = item.get("ai_title") or ui.caption_title(item) or item["canonical_url"]
        step = ("Downloading…" if item["status"] != "archived" else
                "Writing the summary…" if item.get("ai_status") not in ("done", "needs_attention") else "Adding…")
        art = (f'<img src="{e(src)}" alt="">' if src else
               f'<div class="typo" style="background:{colour}">{e((item.get("source") or "post").title())}</div>')
        return (f'<article class="mx waiting" style="--c:{colour};--cd:{ui.deep(colour)}">'
                f'<a class="cover" href="/item/{item["id"]}" aria-label="{e(title[:120])}"></a>'
                f'<div class="sq">{art}<span class="bwait"><i></i>{step}</span></div>'
                f'<div class="mxb"><span class="kind">On its way</span><h3>{e(title)}</h3>'
                f'<p>Friends see it once your Mac has read it.</p></div></article>')

    def _mix(self, cards: list, v: dict, board_id: str, waiting: list | None = None, faded: list | None = None,
             wrap: bool = True) -> str:
        """Pinboard cards on the library's grid: a square picture, then what the post is and who added it, the same
        height in a row, sized by the tile-size control. Posts still being read come first; while a filter is on, the
        cards it leaves out follow, faded and greyed, so the whole board stays in view."""
        out = [self._waiting_tile(item) for item in reversed(waiting or [])]
        dim = {c["url"] for c in faded or []}
        newest = max(cards, key=lambda c: c.get("last", 0))["url"] if cards else ""  # the most recent post is the large one
        for c in [*cards, *(faded or [])]:
            src = self._card_src(c)
            colour = ui.type_colour(c.get("kind"))
            adders = [v["members"][w] for w in c["adders"] if w in v["members"]]
            tags = "".join(f"<span>#{e(t)}</span>" for t in (c.get("tags") or [])[:3])
            art = (f'<img loading="lazy" src="{e(src)}" alt="">' if src else
                   f'<div class="typo" style="background:{colour}">“{e(c.get("title", "")[:90])}”</div>')
            both = f'<span class="bboth">♥ {len(adders)} added</span>' if c["shared"] else ""
            local = self.store.item_by_url(clean_url(c["url"])) if v["id"] != "mock" else None
            href = f"/item/{local['id']}" if local else f"/board/{board_id}?card={_cid(c['url'])}"  # opens like a library post
            play = ""
            if local and local["status"] == "archived":
                media = ui.media_of(local)
                if media["video"]:
                    play = f' data-video="{e(self._media_url(local, media["video"]))}" data-start="{media["start"]}"'
                elif len(media["photos"]) > 1:
                    play = f' data-photos="{e(json.dumps([self._media_url(local, p) for p in media["photos"][:8]]))}"'
            attrs = (f' data-url="{e(c["url"])}"' + (f' data-id="{local["id"]}" data-shelf="{local["shelf"]}"' if local else "")
                     + (f' data-mine="1" data-board="{board_id}"' if v["id"] != "mock" and identity.public_key() in c["adders"] else ""))
            out.append(f'<article class="mx{" shared" if c["shared"] else ""}{" dim" if c["url"] in dim else ""}{" big" if c["url"] == newest else ""}" '
                       f'style="--c:{colour};--cd:{ui.deep(colour)}" data-flip-id="c{_cid(c["url"])}"{attrs}{play}{" aria-hidden=" + chr(34) + "true" + chr(34) + " inert" if c["url"] in dim else ""}>'
                       f'<a class="cover" href="{href}" '
                       f'aria-label="{e((c.get("title") or "")[:120])}"></a>'
                       f'<div class="sq">{art}{both}</div>'
                       f'<div class="mxb"><span class="kind">{e(ui.type_name(c.get("kind")))}</span>'
                       f'<h3>{e(c.get("title") or c["url"])}</h3><p>{e((c.get("summary") or "")[:300])}</p>'
                       f'<div class="ptags">{tags}</div></div>'
                       f'<footer>{self._faces(adders, board_id)}<span class="pby">{e(_by(adders))}</span>{self._votes(c, board_id)}</footer>'
                       '</article>')
        return f'<div class="grid mixes">{"".join(out)}</div>' if wrap else "".join(out)

    def board_context(self, item: dict, board_id: str) -> tuple[str, str, str]:
        """For a post opened from a shared board: the row at the top of the post view (the board, who added the post there and
        when, whether it is in my library), the items it adds to the ... menu (Add to my library, Take it off the board) and
        the votes, which sit next to the counts under the title."""
        v = boards.view(self.store, board_id) if self.store.board(board_id) else None
        card = next((c for c in v["cards"] if c["url"] == item["canonical_url"]), None) if v else None
        if not card:
            return "", "", ""
        me = identity.public_key()
        adders = sorted((v["members"][w] for w in card["adders"] if w in v["members"]), key=lambda m: card["adders"][m["key"]])
        here = f"/item/{item['id']}"
        faces = "".join(f'<span class="bface" data-tip="{e(m["name"] or "Someone")}">{self._face(m)}</span>' for m in adders[:4])
        keep = (ui.button_form(self.csrf, "/hub/shelf", {"id": item["id"], "shelf": "inbox", "next": here}, "Add to my library", "mi")
                if item["shelf"] == "board" else "")
        done = f'<span class="pvdone">{ui.icon("check")}In my library</span>' if item["shelf"] != "board" else ""
        left = (f'<a class="pchip" style="--bc:{ui.folder_colour(v["colour"])}" href="{e(self.board_url(board_id))}">'
                f'{ui.sticker(v["sticker"])}<b>{e(v["name"])}</b></a>'
                f'<span class="bfaces sm">{faces}</span><span class="pvby">Added by {e(_by(adders))} · {_when(card["first"])}</span>'
                f'{done}')
        off = (ui.button_form(self.csrf, "/hub/boards/remove-card", {"board": board_id, "url": card["url"], "next": here},
                              "Take it off the board", "mi bad", confirm="Take this post off the board? Your vote goes too; "
                              "it stays wherever else it is.") if me in card["adders"] else "")
        return f'<div class="pctx board">{left}</div>', keep + off, self._votes(card, board_id, next_=here)

    def _votes(self, card: dict, board_id: str, big: bool = False, next_: str = "") -> str:
        me = identity.public_key()
        mine = card["votes"].get(me, 0)
        up = sum(1 for x in card["votes"].values() if x > 0)
        down = sum(1 for x in card["votes"].values() if x < 0)

        def button(value: int, glyph: str, count: int, label: str) -> str:
            on = mine == value
            fields = {"board": board_id, "url": card["url"], "value": str(0 if on else value), "next": next_ or f"/board/{board_id}"}
            return (f'<form method="post" action="/hub/boards/vote">{ui.hidden(self.csrf, **fields)}'
                    f'<button class="vb{" on" if on else ""}" aria-pressed="{str(on).lower()}" aria-label="{label}"'
                    f'{" disabled" if board_id == "mock" else ""}>{glyph}<b>{count}</b></button></form>')
        return (f'<div class="votes{" big" if big else ""}">{button(1, "👍", up, "Vote for it")}'
                f'{button(-1, "👎", down, "Vote against it")}</div>')

    def _card_src(self, card: dict) -> str:
        if card.get("thumb_url"):
            return card["thumb_url"]
        return f'data:image/jpeg;base64,{card["thumb"]}' if card.get("thumb") else ""

    LINK_LABELS = {"website": "Website", "instagram": "Instagram", "x": "X", "github": "GitHub"}
    @staticmethod
    def _bars(key: str) -> str:
        """A barcode that is theirs alone: one bar per hex digit of their key (width and gap from its value)."""
        x, out = 4, []
        for ch in key[:40]:
            n = int(ch, 16)
            w = 1.2 + n % 4 * 1.1
            out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="40"/>')
            x += w + 1.1 + (n // 4) % 3 * 1.2
        return f'<svg class="pbars" viewBox="0 0 {x + 4:.0f} 40" preserveAspectRatio="none" fill="currentColor" aria-hidden="true">{"".join(out)}</svg>'

    def _person(self, m: dict, *, size: str = "xl", edit: dict | None = None) -> str:
        """A person as friends see them, as an admission ticket: their face, name and short ID, an about line, links and
        topics on the ticket, and a barcode of their key on the stub. Everything came from a friend's message, so it is
        shown as plain text. `edit` swaps the face, name and about line for editors (the owner's own page)."""
        edit = edit or {}
        key = m["key"]
        links = "".join(
            f'<a href="{e(identity.link_url(slot, value))}" target="_blank" rel="noopener noreferrer" '
            f'aria-label="{self.LINK_LABELS[slot]}: {e(value)} (opens in a new tab)">{ui.social_icon(slot)}'
            f'<span>{e(urlsplit(value).netloc.removeprefix("www.") if slot == "website" else "@" + value if slot != "github" else value)}'
            f'</span></a>' for slot in identity.LINK_SLOTS if (value := (m.get("links") or {}).get(slot)))
        topics = "".join(f"<span>{e(t)}</span>" for t in m.get("topics") or [])
        name = e(m.get("name") or "Someone")
        colour = m.get("colour", "#ff2e93")
        return (f'<div class="person" style="--c:{e(colour)}">'
                f'<div class="pbody"><div class="pkicker" aria-hidden="true"><span>Admit one</span><span>Magpiary hoard</span></div>'
                f'<div class="pav">{edit.get("avatar") or ui.avatar(m.get("name") or "?", colour, self._photo(m), size)}</div>'
                f'<div class="pname">{edit.get("name") or f"<b>{name}</b>"}<small class="mono">ID {e(identity.short_id(key))}</small></div>'
                + (edit.get("about") or (f'<p class="pabout">{e(m["about"])}</p>' if m.get("about") else ""))
                + (f'<div class="plinks">{links}</div>' if links else "")
                + (f'<div class="ptopics"><small>Into</small><div class="chips">{topics}</div></div>' if topics else "")
                + f'</div><div class="pstub" aria-hidden="true">{self._bars(key)}<span class="pno">No. {e(identity.short_id(key))}</span></div>'
                f'<i class="pshine" aria-hidden="true"></i></div>')

    def _photo(self, m: dict) -> str:
        return f'data:image/jpeg;base64,{m["photo"]}' if m.get("photo") else m.get("photo_url", "")

    def _face(self, m: dict) -> str:
        return ui.avatar(m.get("name") or "?", m.get("colour", "#ff2e93"), self._photo(m))

    def _faces(self, members: list, board_id: str = "") -> str:
        """Overlapping faces. With a board, each one opens that person's profile."""
        def one(m: dict) -> str:
            if not board_id:
                return self._face(m)
            return (f'<a class="pface" href="/board/{board_id}?member={m["key"]}" '
                    f'aria-label="Open {e(m.get("name") or "Someone")}\'s profile">{self._face(m)}</a>')
        return f'<span class="faces">{"".join(one(m) for m in members[:4])}</span>' if members else ""

    def _mock_view(self) -> dict:
        """A board drawn from this library's own saves, with two made-up friends: an example while no board exists."""
        from magpiary.hub_settings import photo_url

        me = identity.profile(self.store)
        mine = identity.public_key()
        members = {mine: {"key": mine, "name": me["name"] or "You", "colour": me["colour"], "photo": "",
                          "photo_url": photo_url() if me["photo"] else "", "creator": True, "cards": 0}}
        members[mine].update(about=me["about"], links=me["links"], topics=me["topics"])
        for key, name, colour in MOCK_FRIENDS:
            members[key] = {"key": key, "name": name, "colour": colour, "photo": "", "creator": False, "cards": 0,
                            **MOCK_PROFILES.get(name, {})}
        items = [i for i in self.store.hub_items("inbox", limit=60) if i.get("ai_status") == "done" and i.get("thumb")][:14]
        rng = random.Random(7)
        keys = list(members)
        cards = []
        for n, item in enumerate(items):
            adders = {keys[n % 3]: 1000 - n} | ({keys[(n + 1) % 3]: 1000 - n} if n % 4 == 0 else {})
            votes = {k: rng.choice((1, 1, 1, -1, 0)) for k in keys if rng.random() < .6}
            votes = {k: x for k, x in votes.items() if x}
            for k in adders:
                members[k]["cards"] += 1
            cards.append({"url": item["canonical_url"], "title": ui.title_of(item), "summary": item.get("summary") or "",
                          "kind": item.get("ai_type"), "tags": item.get("tags", []), "thumb_url": self.thumb_url(item),
                          "adders": adders, "votes": votes, "score": sum(votes.values()), "shared": len(adders) > 1,
                          "first": 1000 - n, "last": 1000 - n})
        return {"id": "mock", "name": "Example: Weekend ideas", "creator": mine, "via": "nostr", "members": members,
                "sticker": stickers.pick("Weekend ideas"), "colour": "#00a37a",
                "cards": cards, "synced_at": "", "sync_error": "", "shared": True, "ended": False, "archived": False}


def _by(adders: list) -> str:
    names = [a.get("name") or "Someone" for a in adders]
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _back(form: dict, board_page: str) -> str:
    """Back to the post when a vote or Take it off came from the post opened over the board, else to the board."""
    nxt = form.get("next", "")
    return nxt if re.fullmatch(r"/item/\d+", nxt) else board_page


def clean_url(url: str) -> str:
    """A card's address as this library keys it (the same cleaning as a phone share)."""
    from magpiary.cleaner import UnsupportedLink, clean

    try:
        return clean(url).url
    except UnsupportedLink:
        return url


def slugify(name: str) -> str:
    """A board name as an address: "Lisbon trip!" → lisbon-trip (plain letters and digits; "board" when none)."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60].strip("-") or "board"


def _when(at: int) -> str:
    """An event's moment (seconds) in plain words: "5 min ago"."""
    return _ago(datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds"))


def _day(at: float) -> str:
    return datetime.fromtimestamp(at).strftime("%-d %b")


def _ago(stamp: str) -> str:
    from magpiary.hub_settings import ago

    return ago(stamp)


def _cid(url: str) -> str:
    """A short, stable id for a card in a page address (the post's address, hashed)."""
    return hashlib.sha1(url.encode()).hexdigest()[:10]


def new_board_via(store) -> str:
    """Where new boards sync, chosen once in Settings: "bucket" only while a bucket is connected."""
    return "bucket" if store.get_setting("board_via") == "bucket" and boardsync.load_bucket() else "nostr"


def sync_words(error: str) -> str:
    """A sync problem in plain words (the details stay in the log and on hover)."""
    if error.startswith(("No relay took it", "No relay could be reached")):
        return "Couldn't reach the Nostr relays. Trying again in 15 minutes."
    if error.startswith("Could not reach the storage service"):
        return "Couldn't reach the bucket. Trying again in 15 minutes."
    return error
