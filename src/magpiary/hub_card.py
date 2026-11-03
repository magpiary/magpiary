"""A post (M7a, C1+), mixed into Hub: one near-full-screen card, the video about 40% wide and the information in
tabs (Summary · Links · Related · Details). Opened over the wall by hub.js (`?frag=1` returns the card alone); the
same address opens it as a page of its own. Without JavaScript every tab is shown, one under the other."""

import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from magpiary.hub_map import local_map_html
from magpiary.hub_wall import empty_state
from magpiary import keys as keyring
from magpiary import facets, icons, login, modes, ocr, ui
from magpiary import related as rel
from magpiary.activity import STEPS
from magpiary.brain import type_of
from magpiary.links import host_of as links_host
from magpiary.queuepage import REASONS, when
from magpiary.store import TRASH_DAYS
from magpiary.web import Response, e

VIDEO = (".mp4", ".webm", ".mov")
AI_REASONS = {"busy": "the AI was too busy or slow; trying again later", "no_key": "no AI key yet",
              "bad_key": "the key was refused", "rate_limited": "the AI's limit was reached",
              "blocked": "the AI declined this post", "invalid": "the AI's answer was not usable",
              "unknown": "something went wrong"}
SHORT_CAPTION = 140  # shorter captions are shown large; longer ones fold


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _short(n: int) -> str:
    """1,234 as 1.2K, 3,400,000 as 3.4M."""
    for limit, unit in ((1_000_000, "M"), (1_000, "K")):
        if n >= limit:
            return f"{n / limit:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def shared_record(item: dict) -> dict | None:
    """A friend's post on a board: the summary and tags its card brought stand in for a record until the owner
    asks for a summary of their own."""
    if not item.get("media_only") or item.get("ai_status") != "done":
        return None
    try:
        tags = json.loads(item.get("suggested_tags") or "[]")
    except ValueError:
        tags = []
    return {"title": item.get("ai_title") or ui.caption_title(item), "summary": item.get("summary") or "",
            "type": item.get("ai_type") or "other", "key_points": [], "suggested_tags": tags, "entities": {},
            "engine": {"brain": "Shared with the post on the board"}}


FROM_OK = re.compile(r"/(?:\?[^\s#]{0,300}|pile/\d+|board/[a-z0-9-]{1,80}(?:\?[^\s#]{0,200})?)?")  # where a post was opened from: an address inside the hub
SHOWN_CHIPS = 5     # mentioned names shown before "+N more"
RELATED_SHOWN = 5  # related posts in the tab before "See all"


BAD_TITLE = re.compile(r"one moment|just a moment|loading|loader|access denied|attention required|please wait|enable javascript|\b40[34]\b|"
                       r"are you a robot|captcha", re.I)


def link_title(title: str, host: str) -> str:
    """A link's title, or the website's name when the title is a loading or error page the checker captured by mistake."""
    title = (title or "").strip()
    return host if not title or BAD_TITLE.search(title) or len(title) < 3 else title


def _spoken(text: str) -> bool:
    """False for what a transcriber writes over music: "[Music]", "♪", or only punctuation."""
    words = re.sub(r"\[[^\]]*\]|\([^)]*\)|[^\w]", "", text)
    return bool(words) and words.lower() not in ("music", "applause")


def links_done(item: dict) -> bool:
    """True once the link search has run for this post (so an empty result means 'not found', not 'not looked yet')."""
    return item.get("links_status") is not None


def _svg(paths: str) -> str:
    return f'<svg class="pvi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>'


# our own player controls over the media (play, time, seek, sound, fit, full screen)
PLAYER_BAR = (
    '<div class="pvbar">'
    f'<button type="button" class="pvb" data-pv="play" aria-label="Play">{_svg("<path d=\"M7 5l12 7-12 7z\" fill=\"currentColor\"/>").replace("pvi", "pvi i-play")}'
    f'{_svg("<path d=\"M8 5v14M16 5v14\"/>").replace("pvi", "pvi i-pause")}</button>'
    '<span class="pvtime">0:00</span>'
    '<input type="range" class="pvseek" min="0" max="1000" value="0" aria-label="Seek">'
    f'<button type="button" class="pvb" data-pv="mute" aria-label="Mute">{_svg("<path d=\"M4 9v6h4l5 4V5L8 9z\"/><path d=\"M16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11\"/>").replace("pvi", "pvi i-vol")}'
    f'{_svg("<path d=\"M4 9v6h4l5 4V5L8 9z\"/><path d=\"M17 9l5 6M22 9l-5 6\"/>").replace("pvi", "pvi i-muted")}</button>'
    f'<button type="button" class="pvb" data-pv="fit" aria-pressed="false" aria-label="Show the whole video, uncropped" title="Show the whole video, uncropped">'
    f'{_svg("<rect x=\"6\" y=\"3\" width=\"12\" height=\"18\" rx=\"2\"/><path d=\"M3 8v8M21 8v8\"/>")}</button>'
    f'<button type="button" class="pvb" data-pv="full" aria-label="Full screen" title="Full screen">'
    f'{_svg("<path d=\"M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5\"/>")}</button>'
    '</div>')


class CardPages:
    """Needs Hub's store, csrf, shell, _form, _media_url, thumb_url, related_library and activity."""

    def card_page(self, item_id: int, fragment: bool = False, tab: str = "", board: str = "", pile: str = "", frm: str = "") -> Response:
        item = self.store.item_by_id(item_id)
        if item and not frm.startswith("preview"):
            self.store.open_record(item["canonical_url"])  # which posts get opened: a quiet signal of interest
        if not item:
            if fragment:
                return Response(404, b"gone", "text/plain")
            return self.shell("Not found", empty_state("This post is gone", "It may have been deleted, or the link is old.",
                                                              '<a class="btn dark" href="/">Back to the library</a>'), "missing", 404)
        if fragment:
            card = self.card(item, tab, board, pile)
            return Response(200, card.encode(), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        frm = frm if FROM_OK.fullmatch(frm or "") else ""
        page: dict = {"from": frm}
        path = frm.partition("?")[0]
        if not pile and (m := re.fullmatch(r"/pile/(\d+)", path)):
            pile = m.group(1)  # opened from a pile: its name and place in the bar
        if not board and (m := re.fullmatch(r"/board/([a-z0-9-]{1,80})", path)):
            slugs = self.board_slugs()
            board = next((b["id"] for b in self.store.boards() if slugs.get(b["id"]) == m.group(1) or b["id"] == m.group(1)), "")
        card = self.card(item, tab, board, pile, page=page)
        prev_id, next_id, at, total = self._neighbours(item, frm)
        icons = page["icons"].replace("{{NAV}}", self._page_nav(item, frm, prev_id, next_id, at, total))
        crumbs, back_label, back_href = self._crumbs(item, frm)
        body = (f'<div class="postpage" data-from="{e(frm)}">{self.ask_button(f"post:{item_id}")}<div class="crumbbar">'
                f'<a class="pgback" href="{e(back_href)}" data-pgback>{ui.icon("back")}<span>Back to {e(back_label)}</span></a>{crumbs}'
                f'<div class="pacts">{icons}</div></div>'
                f'<section class="cardm it pagemode" role="region" aria-label="Post" data-standalone data-from="{e(frm)}" '
                f'data-prev="{prev_id or ""}" data-next="{next_id or ""}">{card}</section></div>')
        return self.shell(ui.title_of(item)[:60] or "Post", body, "card")

    # ---- the post as a page: breadcrumb, and the posts before and after it ---------------------------------------------

    def _crumbs(self, item: dict, frm: str) -> tuple[str, str, str]:
        """Library › Example pile › Post title: where you came from, each part a link, ending at this post."""
        trail: list[tuple[str, str]] = []
        path, _, query = (frm or "/").partition("?")
        q = parse_qs(query)
        if m := re.fullmatch(r"/pile/(\d+)", path):
            pile = self.store.pile(int(m.group(1)))
            trail = [("Library", "/"), ("Piles", "/?view=piles")] + ([(pile["name"], path)] if pile else [])
        elif m := re.fullmatch(r"/board/([a-z0-9-]{1,80})", path):
            board = self.store.board(m.group(1)) or next((b for b in self.store.boards() if self.board_slugs().get(b["id"]) == m.group(1)), None)
            trail = [("Library", "/"), ("Boards", "/?view=boards")] + ([(board["name"], path)] if board else [])
        elif q.get("q"):
            trail = [("Search", "/"), (f"“{q['q'][0][:40]}”", frm)]
        elif q.get("shelf", [""])[0] in ("archive", "trash"):
            trail = [("Library", "/"), (q["shelf"][0].capitalize(), frm)]
        elif q.get("view", [""])[0] == "piles":
            trail = [("Library", "/"), ("Piles", frm)]
        else:
            trail = [("Library", "/")]
        parts = "".join(f'<a href="{e(href)}" data-crumb>{e(label)}</a><i aria-hidden="true">›</i>' for label, href in trail)
        label, href = trail[-1]
        label = label.strip("“”") if label.startswith("“") is False else "search results"
        return (f'<nav class="crumbs" aria-label="Breadcrumb">{parts}<span aria-current="page">{e((ui.title_of(item) or "Post")[:70])}</span></nav>',
                label, href)

    def _neighbours(self, item: dict, frm: str) -> tuple[int | None, int | None, int, int]:
        """(previous id, next id, position, total) in the list the post was opened from; None when it is not in it."""
        path, _, query = (frm or "/").partition("?")
        q = parse_qs(query)
        ids: list[int] = []
        if m := re.fullmatch(r"/pile/(\d+)", path):
            pile = self.store.pile(int(m.group(1)))
            ids = [i for i in (self.store.id_for(u) for u in (pile["members"] if pile else [])) if i]
        elif q.get("q"):
            ids = [i["id"] for i in self.store.hub_items("kept", q["q"][0][:200])]
        elif q.get("shelf", [""])[0] in ("archive", "trash"):
            ids = [i["id"] for i in self.store.hub_items(q["shelf"][0], limit=5000)]
        elif path == "/" and not q.get("view", [""])[0] == "boards":
            ids = [i["id"] for i in self.store.hub_items("inbox", limit=5000)]
        if item["id"] not in ids:
            return None, None, 0, 0
        at = ids.index(item["id"])
        return (ids[at - 1] if at else None), (ids[at + 1] if at + 1 < len(ids) else None), at + 1, len(ids)

    def _page_nav(self, item: dict, frm: str, prev_id, next_id, at: int, total: int) -> str:
        def link(target, icon, label, attr):
            href = f"/item/{target}" + (f"?from={quote(frm, safe='')}" if frm else "")
            return (f'<a class="rb" href="{href}" {attr} aria-label="{label}" title="{label}">{ui.icon(icon)}</a>' if target
                    else f'<span class="rb off" aria-hidden="true">{ui.icon(icon)}</span>')
        if not at:
            return ""
        return (link(prev_id, "back", "Previous post", "data-pagenav") + f'<span class="pgpos">{at} of {total}</span>'
                + link(next_id, "chev", "Next post", "data-pagenav"))

    def card(self, item: dict, tab: str = "", board: str = "", pile: str = "", page: dict | None = None) -> str:
        """A post, opened. One design for the library, the archive, the Trash, a pile and a shared board: the top bar's
        left side (the CONTEXT slot) and the extra ... menu items are the only parts that differ, and `post_context`
        fills them. New things (notes, a board's discussion, asking the post, a module's own block) have a place already:
        `_extra_tabs` for tabs and `_summary_blocks` for blocks inside the Summary."""
        folder = Path(item["archive_dir"]) if item.get("archive_dir") else None
        meta = (_read_json(folder / "meta.json") if folder else None) or {}
        record = (_read_json(folder / "record.json") if folder else None) or shared_record(item)
        here = f"/item/{item['id']}"
        caption = meta.get("text") or item.get("caption") or ""
        stage, under = self._stage(item, meta, caption)
        context, extra_menu, votes = self.post_context(item, board, pile)
        kind = type_of(record) if record else ""
        tint = ui.deep(ui.type_colour(kind)) if record else ui.deep(ui.source_colour(item["source"]))
        if page is not None:
            page["ckind"] = context[0]
        bar = self._card_bar(item, record, here, context[1], extra_menu, page=page)
        # on a page, where the post sits on a board (who added it, votes, Add to my library) or in the Trash (Restore) is the first
        # thing in the reading column, not a second row at the top
        # (on a board the type and date line joins that row, and the votes sit by the counts)
        ctx_strip, line = "", None
        if page is not None and context[0] == "board":
            ctx_strip = f'<div class="pvctx">{context[1][:-len("</div>")]}{self._type_line(item, record)}</div></div>'
            line = ""
        elif page is not None and context[0] == "trash":
            ctx_strip = f'<div class="pvctx">{context[1]}</div>'
        return (f'<div class="vid" style="--tc:{tint}">{stage}{under}<div class="capslot">{self._caption_block(item, meta, caption)}</div></div>'
                f'<div class="main" data-item="{item["id"]}" data-context="{e(context[0])}" style="--tc:{tint}">'
                f'{bar}'
                f'<div class="pscroll">{ctx_strip}{self._card_head(item, meta, record, here, caption, votes, line)}'
                f'{self._card_tabs(item, record, folder, caption, meta, here, tab, context[0])}</div></div>')

    # ---- the context: where this post was opened from ------------------------------------------------

    def post_context(self, item: dict, board: str = "", pile: str = "") -> tuple[tuple[str, str], str, str]:
        """((kind, html for the top bar's left side), extra ... menu items, votes for the counts row (a board's only)).
        The kinds: board, pile, trash, archive, library."""
        if board:
            left, menu, votes = self.board_context(item, board)
            if left:
                return ("board", left), menu, votes
        if pile.isdigit() and (p := self.store.pile(int(pile))):
            return ("pile", f'<div class="pctx"><span class="pwhere">{ui.icon("folder")}<b>{e(p["name"])}</b></span>'
                            f'<span class="ppos" data-pos></span></div>'), "", ""
        if item["shelf"] == "trash":
            when_gone = ""
            if item.get("trashed_at"):
                gone = datetime.fromisoformat(item["trashed_at"]) + timedelta(days=TRASH_DAYS)
                days = max((gone - datetime.now(gone.tzinfo)).days, 0)
                when_gone = f" · deleted for good in {days} day{'' if days == 1 else 's'}"
            restore = self._form("/hub/shelf", {"id": item["id"], "shelf": "inbox", "next": f"/item/{item['id']}"},
                                 "Restore to library", "btn sm dark")
            return ("trash", f'<div class="pctx"><span class="pwhere">{ui.icon("trash")}<b>In the Trash</b>{e(when_gone)}</span>'
                             f'{restore}</div>'), "", ""
        word = "Archive" if item["shelf"] == "archive" else "Library"
        piles = self.store.piles_for(item["canonical_url"]) if item["status"] == "archived" else []
        chips = "".join(f'<a class="pvpile" href="/pile/{p["id"]}" title="Open the pile {e(p["name"])}">{ui.icon("folder")}{e(p["name"])}</a>'
                        for p in piles)
        return ("archive" if item["shelf"] == "archive" else "library",
                f'<div class="pctx"><span class="pwhere">{e(word)}</span>{chips}</div>'), "", ""

    # ---- left: the media ------------------------------------------------------------------

    def _stage(self, item: dict, meta: dict, caption: str) -> tuple[str, str]:
        from magpiary.hub import rich_text

        media = meta.get("media") or []
        videos = [m for m in media if m.endswith(VIDEO)]
        images = [m for m in media if not m.endswith(VIDEO)]
        poster = f' poster="{e(self._media_url(item, meta["thumbnail"]))}"' if meta.get("thumbnail") == "thumbnail.jpg" else ""
        slides = len(media) if videos and len(media) > 1 else 0  # a carousel: every slide is playable, not just the first video
        if videos:
            inner = (f'<video playsinline preload="metadata"{poster} src="{e(self._media_url(item, videos[0]))}">'
                     f'</video><img class="pvslide" alt="" hidden><button type="button" class="pvbig" data-bigplay aria-label="Play"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.2 5.4v13.2a1 1 0 001.5.85l10.3-6.6a1 1 0 000-1.7L9.7 4.55a1 1 0 00-1.5.85z" fill="currentColor"/></svg></button><div class="pvautozone"><button type="button" class="pvauto" role="switch" aria-checked="false" data-autoplay '
                     'title="Play each post as soon as it opens">Autoplay<i></i></button></div>' + PLAYER_BAR)
            if slides:
                inner += ('<button type="button" class="gnav gprev" aria-label="Previous slide" disabled>‹</button>'
                          '<button type="button" class="gnav gnext" aria-label="Next slide">›</button>'
                          f'<span class="gcount" aria-live="polite">1 / {slides}</span>')
        elif images:
            inner = '<div class="gal" tabindex="0" aria-label="Photos, use the arrow keys or the buttons">' + "".join(
                f'<img loading="lazy" src="{e(self._media_url(item, i))}" alt="Photo {n} of {len(images)}">'
                for n, i in enumerate(images, 1)) + "</div>"
            if len(images) > 1:  # a visible way along: buttons and "1 / 7"; swipe and scroll still work
                inner = (f'<div class="galw" data-gallery>{inner}<button type="button" class="gnav gprev" aria-label="Previous photo" '
                         f'disabled>‹</button><button type="button" class="gnav gnext" aria-label="Next photo">›</button>'
                         f'<span class="gcount" aria-live="polite">1 / {len(images)}</span></div>')
        else:
            text = caption or ("Still being fetched…" if item["status"] in ("queued", "expanding") else
                               "Nothing was saved for this post.")
            title = meta.get("title") if item["source"] in ("reddit", "youtube") and meta.get("title") else ""
            inner = ('<div class="txtpost">' + (f"<b>{e(title)}</b>\n" if title else "")
                     + f'{rich_text(text, item["source"])}</div>')
        bits = [ui.source_name(item["source"])]
        if slides:
            bits.append(f"{slides} slides")
        else:
            if meta.get("duration"):
                bits.append(ui.duration(meta["duration"]))
            if len(images) > 1:
                bits.append(f"{len(images)} photos")
        under = (f'<div class="cap"><span>{e(" · ".join(bits))}</span><a href="{e(item["canonical_url"])}" target="_blank" '
                 f'rel="noopener noreferrer">Open original ↗</a></div>')
        strip = self._slide_strip(item, media) if slides else ""
        return f'<div class="stage">{inner}</div>{strip}', under

    def _slide_strip(self, item: dict, media: list[str]) -> str:
        """A carousel's slides as a row of small pictures under the player: click one to play or show it. Each video carries
        where it starts on the one timeline the summary and the key moments use (slides.json, made when it was read)."""
        folder = ui.folder_of(item)
        times = {s["file"]: s for s in (ui.read_json(folder / "slides.json") if folder else None) or []}
        out = []
        for n, m in enumerate(media):
            src = e(self._media_url(item, m))
            video = m.endswith(VIDEO)
            thumb = f'<img loading="lazy" decoding="async" alt="" src="{src}?w=160">'  # a small copy (a video's first moment)
            start = f' data-start="{times[m]["start"]}" data-dur="{times[m]["duration"]}"' if m in times else ""
            out.append(f'<button type="button" class="pvsl{" on" if n == 0 else ""}" data-k="{"v" if video else "i"}" data-src="{src}"'
                       f'{start} aria-label="Slide {n + 1}{" (video)" if video else ""}">{thumb}'
                       f'{"<i></i>" if video else ""}</button>')
        return f'<div class="pvstrip" role="group" aria-label="Slides">{"".join(out)}</div>'

    # ---- right: title, counts, actions ------------------------------------------------------

    def _card_bar(self, item: dict, record: dict | None, here: str, context_html: str, extra_menu: str, page: dict | None = None) -> str:
        """The top bar: the context on the left; on the right, the icons (previous, next, open the original, copy the link,
        the ... menu, close)."""
        done = bool(record)
        acts = []
        if item["status"] == "needs_attention":
            acts.append(self._form("/hub/retry", {"id": item["id"], "next": here}, "Retry now", "mi"))
        if item["status"] == "archived" and modes.current(self.store) != "private" and item["shelf"] != "trash":
            acts.append(self._form("/hub/again", {"id": item["id"], "next": here},
                                   "Summarise again" if done else "✦ Summarise", "mi"))
        if item["shelf"] == "inbox":
            acts.append(self._form("/hub/shelf", {"id": item["id"], "shelf": "archive", "next": here}, "Archive", "mi"))
        elif item["shelf"] != "board":
            acts.append(self._form("/hub/shelf", {"id": item["id"], "shelf": "inbox", "next": here},
                                   "Restore to library" if item["shelf"] == "trash" else "Back to library", "mi"))
        if item["status"] == "archived":
            acts.append(f'<button type="button" class="mi" data-addboard="{item["id"]}">Add to board…</button>')
        acts.append(extra_menu)
        if item["shelf"] != "trash":
            acts.append(self._form("/hub/shelf", {"id": item["id"], "shelf": "trash", "next": "/"}, "Remove…", "mi bad",
                                   confirm="Move this post to the Trash? It is deleted for good after 30 days."))
        url = e(item["canonical_url"])
        steps = ("{{NAV}}" if page is not None else
                 f'<a class="rb" href="#" data-prev aria-label="Previous post" title="Previous post" hidden>{ui.icon("back")}</a>'
                 f'<a class="rb" href="#" data-next aria-label="Next post" title="Next post" hidden>{ui.icon("chev")}</a>')
        close = ("" if page is not None else f'<a class="rb" href="/" data-close aria-label="Close" title="Close">{ui.icon("close")}</a>')
        icons = (steps + f'<a class="rb" href="{url}" target="_blank" rel="noopener noreferrer" aria-label="Open the original" '
                 f'title="Open the original">{ui.icon("ext")}</a>'
                 + (f'<button type="button" class="rb" data-addboard="{item["id"]}" aria-label="Add to a board" title="Add to a board">'
                    f'{ui.icon("folder")}</button>' if item["status"] == "archived" and item["shelf"] != "trash" else "")
                 + f'<button type="button" class="rb" data-copylink="{url}" aria-label="Copy the link" title="Copy the link">'
                 f'{ui.icon("links")}</button>'
                 f'<details class="menu cardmenu"><summary class="rb" aria-label="More actions" title="More actions">'
                 f'{ui.icon("more")}</summary><div class="pop" role="menu">{"".join(acts)}</div></details>' + close)
        if page is not None:  # on a page the breadcrumb says where you are; card_page puts the icons beside it
            page["icons"], page["context"] = icons, context_html
            return ""
        return f'<div class="pbar">{context_html}<span class="pgrow"></span><div class="pacts">{icons}</div></div>'

    def _type_line(self, item: dict, record: dict | None) -> str:
        """The type tag and when it was saved: "How-to  Saved yesterday 22:24"."""
        done = bool(record)
        kind = type_of(record) if record else ""
        colour = ui.deep(ui.type_colour(kind)) if done else ui.deep(ui.source_colour(item["source"]))
        badge = (f'<b style="background:{colour}">{e(ui.type_name(kind) if done else ui.source_name(item["source"]))}</b>')
        where = ui.source_badge(item["source"]) if done else ""
        from magpiary.brain import FORMAT_NAMES
        shape = " · ".join(x for x in (FORMAT_NAMES.get((record or {}).get("format") or "", ""), (record or {}).get("topic") or "") if x)
        badge += f'<em class="itfmt">{e(shape)}</em>' if shape else ""
        return (f'<div class="it-type">{where}{badge}<span>{"From a friend’s board" if item.get("media_only") else "Saved"} '
                f'{e(ui.day(item.get("first_shared_at") or item.get("created_at")))}'
                + (f' · {item["saved_count"]}×' if item["saved_count"] > 1 else "") + "</span></div>")

    def _card_head(self, item: dict, meta: dict, record: dict | None, here: str, caption: str = "", votes: str = "",
                   line: str | None = None) -> str:
        """Type and date, the title, the summary (or why there is none), the caption, then who, where and how popular.
        `line` replaces the type and date line ("" when it sits elsewhere); `votes` join the counts."""
        done = bool(record)
        kind = type_of(record) if record else ""
        colour = ui.deep(ui.type_colour(kind)) if done else ui.deep(ui.source_colour(item["source"]))
        if line is None:
            line = self._type_line(item, record)
        title = (record or {}).get("title") if done else ui.caption_title(item)
        counts = ""
        if meta:
            as_of = ui.day(meta.get("stats_at") or meta.get("fetched_at"))
            stats = [f'<span class="cn cn-{icon}" title="{meta[key]:,} {label}, as of {e(as_of)}">{ui.icon(icon)}<b>{_short(meta[key])}</b></span>'
                     for key, icon, label in (("like_count", "heart", "likes"), ("comment_count", "comment", "comments"),
                                              ("view_count", "eye", "views")) if isinstance(meta.get(key), int)]
            if stats:
                refresh = ("" if item.get("login_only") else
                           ui.button_form(self.csrf, "/hub/refresh-stats", {"id": item["id"], "next": here}, ui.icon("refresh"),
                                          "rf", title=f"Refresh counts (these are as of {as_of})"))  # login-only posts are never refreshed
                counts = f'<div class="counts pvcounts">{"".join(stats)}{refresh}{votes}</div>'
                votes = ""
        if votes:
            counts = f'<div class="counts pvcounts">{votes}</div>'
        return (f'<header class="pvhead" style="--tc:{colour}">{line}<h2 class="it-h">{e(title or "Untitled")}</h2>{counts}</header>'
                + self._lead(item, record) + self._actions(item, record, here) + self._mentioned(item, record or {})
                + self._state(item, record, here))

    def _lead(self, item: dict, record: dict | None) -> str:
        """The summary right under the title, flat and in line with it: the main point comes before the caption.
        A small label says it was written by an AI, and which one."""
        if not record or not record.get("summary"):
            return ""
        engine = record.get("engine") or {}
        label = f'<small class="pvlabel">AI summary{" · " + e(engine["brain"]) if engine.get("brain") else ""}</small>'
        return (f'<div class="it-lead pvlead">{label}<p class="it-sum">{e(record["summary"])}</p><div class="psf">'
                f'<button type="button" class="link copyb" data-copy="{e(self._copy_with_source(item, record))}" '
                f'data-copyname="Summary with source">{ui.icon("copy")}Copy with source</button></div></div>')

    def _copy_with_source(self, item: dict, record: dict) -> str:
        """Title, summary, key moments with their times, then the original link: plain text, ready to paste."""
        return "\n".join([record.get("title", ""), "", record.get("summary", ""), ""]
                         + [f'{p.get("at") + " " if p.get("at") else ""}{p["text"]}' for p in record.get("key_points") or []]
                         + ["", item["canonical_url"]])

    def _actions(self, item: dict, record: dict | None, here: str) -> str:
        """What to do with this post, right under the summary: up to two actions. Usually the main resources it names
        (more than two go behind "+N more in Links"); a place gets Maps; with no link yet, find one or add one."""
        if item["status"] != "archived" or item["shelf"] == "trash" or not record:
            return ""
        extras = record.get("extras") or {}
        links = self.store.links_for(item["canonical_url"])
        tool = extras.get("tool_name") or next(iter((record.get("entities") or {}).get("tools") or []), "")
        named = [l for l in links if (l.get("section") or "named") == "named" and l.get("role", "main") == "main" and l.get("central", 1)]
        named.sort(key=lambda l: 0 if tool and l["name"].lower() == tool.lower() else 1)  # the post's own tool first; the rest keep their order

        def row(href: str, title: str, small: str, kind_: str = "link") -> str:
            return (f'<a class="pvprimary" href="{e(href)}" target="_blank" rel="noopener noreferrer" title="{title}">{self._site_icon(href) if kind_ == "link" else ui.icon("ext")}'
                    f'<span><b>{title}</b><small>{e(small)}</small></span><i aria-hidden="true">↗</i></a>')

        out: list[str] = ([f'<button type="button" class="pvask" data-askpost="{item["id"]}"><span class="askmark" aria-hidden="true">✦</span> Ask Magpiary</button>']
                          if self.ask_enabled() else [])
        base = len(out)  # the Ask button, when it is on, comes first; the rest depends on what else is there
        for l in named[:2]:
            out.append(row(l["url"], "Open " + e(l["name"]), (urlsplit(l["url"]).hostname or "").removeprefix("www.")))
        if len(out) == base and extras.get("place_name"):
            query = " ".join(x for x in (extras["place_name"], extras.get("city", "")) if x)
            out.append(row("https://maps.apple.com/?q=" + quote(query), f'Open {e(extras["place_name"])} in Maps', extras.get("city", "") or "Apple Maps", "maps"))
        if len(out) == base and (tool or type_of(record) == "tool"):
            if item.get("links_force"):
                out.append('<span class="pvprimary wait"><span><b>Looking for the link…</b><small>This can take a minute</small></span></span>')
            else:
                out.append(self._form("/hub/links/again", {"id": item["id"], "next": here + "?tab=links"},
                                      f'Find the link{" for " + e(tool) if tool else ""}', "pvprimary find"))
            out.append('<a class="pvprimary find" href="#links" data-tabto="links"><span><b>Add a link yourself</b></span></a>')
        return f'<div class="pvactions">{"".join(out)}</div>' if out else ""

    @staticmethod
    def _duration(item: dict) -> float | None:
        meta = _read_json(Path(item["archive_dir"]) / "meta.json") if item.get("archive_dir") else None
        return (meta or {}).get("duration")

    def _state(self, item: dict, record: dict | None, here: str) -> str:
        """Why this post is not finished yet, in plain words, with what to do about it."""
        if item["status"] == "needs_attention" and item.get("login_only") != 2:
            retry = f" Next try {e(when(item['next_retry_at']))}." if item.get("next_retry_at") else " Retries have run out."
            return (f'<div class="pstate bad"><b>Couldn\'t open this post</b><p>'
                    f'{e(REASONS.get(item.get("reason") or "unknown", item.get("reason") or ""))}. Magpiary fetches logged out, '
                    f'slowly, so it waits and tries again by itself.{retry}</p>'
                    + (f'<p class="small muted">{e(item["reason_detail"])}</p>' if item.get("reason_detail") else "")
                    + (f'<p class="small muted">{ui.icon("lock")} {e(self._wall_words(item))}</p>' if item.get("reason") == "login_wall" else "")
                    + f'<div class="row">{self._form("/hub/retry", {"id": item["id"], "next": here}, "Retry now", "btn sm dark")}'
                    + self._login_button(item)
                    + (self._form("/hub/keep-link", {"id": item["id"], "next": here}, "Keep it as a link", "btn sm")
                       + self._form("/hub/archive-link", {"id": item["id"], "next": here}, "Archive it", "btn sm")
                       if item.get("reason") == "login_wall" else "") + "</div></div>")
        if item["status"] == "needs_attention" and item.get("login_only") == 2:
            return (f'<div class="pstate"><b>Kept as a link</b><p>{ui.icon("lock")} {e(self._wall_words(item).split(". ")[0])}. '
                    'It stays in your library as a link and is not tried again.</p><div class="row">'
                    + self._login_button(item) + "</div></div>")
        if item["status"] != "archived":
            return ('<div class="pstate"><b>Being fetched</b><p>Magpiary is downloading this post. This card fills in '
                    'by itself.</p></div>')
        lane = next((l for l in self.activity.snapshot()["lanes"] if l["item_id"] == item["id"]), None)
        if lane:
            pct = f' {int(lane["percent"])}%' if lane.get("percent") is not None else ""
            return (f'<div class="pstate"><b>{e(STEPS.get(lane["step"], "Working"))}{pct}</b><p>Being read on this Mac '
                    'now. This card fills in by itself.</p></div>')
        if item.get("ai_status") == "needs_attention":
            why = AI_REASONS.get(item.get("ai_reason") or "", "something went wrong")
            return (f'<div class="pstate bad"><b>No summary yet</b><p>Not made: {e(why)}.</p>'
                    + (f'<p class="small muted">{e(item.get("ai_detail") or "")}</p>' if item.get("ai_detail") else "")
                    + self._form("/hub/again", {"id": item["id"], "next": here}, "Try again", "btn sm dark") + "</div>")
        if not record and item["shelf"] != "trash":
            why = modes.waiting_reason(self.store, keyring)
            if modes.current(self.store) == "private":
                return ('<div class="pstate"><b>Private mode</b><p>No AI summary: the caption and the transcript are kept '
                        'and searchable. Switch to Smart in <a class="link" href="/settings/ai">Settings</a> for summaries.</p></div>')
            if why:
                return (f'<div class="pstate"><b>No summary yet</b><p>{e(why)} <a class="link" href="/settings/ai">Settings</a>'
                        '</p></div>')
            return '<div class="pstate"><b>Waiting for its turn</b><p>The summary shows up here when it is ready.</p></div>'
        return ""

    @staticmethod
    def _wall_words(item: dict) -> str:
        site = login.site_of(item["canonical_url"])
        if site == login.DEFAULT:
            return ("Instagram shows this post only to logged-in people (often an age limit or a private account). "
                    "Trying again logged out will not change that.")
        return (f"{site or 'This site'} refused a visit without a login. It may need you to be logged in, or it may block automated "
                "visits. Retrying logged out will not change that; retrying with your own login might.")

    def _login_button(self, item: dict) -> str:
        """Retry with the owner's own login: for any site that refuses a logged-out visit, not only Instagram."""
        site = login.site_of(item["canonical_url"])
        if not site:
            return ""
        if login.connected(self.store, site):
            return self._form("/hub/try-login", {"id": item["id"], "next": f"/item/{item['id']}"}, "Retry with my login",
                              "btn sm")
        if site == login.DEFAULT:
            return '<a class="btn sm" href="/settings/phones#instagram">Connect Instagram to try with your login</a>'
        from magpiary.tools import in_mac_app

        program = "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary" if in_mac_app() else "magpiary"
        return ('<details class="fold loginhow"><summary class="btn sm">Retry with my login</summary><div class="small">'
                f'<p>First log in to <b>{e(site)}</b> in Chrome. Then open the <b>Terminal</b> app and run:</p>'
                f'<pre class="cmd">{e(program)} login connect {e(site)}</pre>'
                '<p>macOS asks twice: to let Terminal use data from other apps, and to use “Chrome Safe Storage”. Choose Allow both '
                'times. Then reload this page and press <b>Retry with my login</b>. Your login stays on this Mac and is used only for '
                'this site, only when you press that button.</p></div></details>')

    # ---- the tabs ---------------------------------------------------------------------------

    def _extra_tabs(self, item: dict, record: dict | None, context: str) -> list[tuple[str, str, str, str]]:
        """Tabs that only some posts or contexts have, as (key, label, count text, pane html). Today: Deeper dive, when it
        is turned on in Settings and the post has been read. (Ask is not a tab: its side sheet opens from the bar.)"""
        from magpiary import deepdive

        if not record or item.get("status") != "archived" or item.get("shelf") == "trash" or not deepdive.enabled(self.store):
            return []
        meta = (_read_json(Path(item["archive_dir"]) / "meta.json") if item.get("archive_dir") else None) or {}
        hint = "Suggested" if item.get("deep_status") is None and deepdive.suggested(self.store, meta) else ""
        return [("deep", "Deeper dive", hint, self._deep_pane(item, meta))]

    def _deep_pane(self, item: dict, meta: dict) -> str:
        """Before: what it will read and a button (over the call limit, it asks first). While it runs: where it is. After:
        the overview, sections (click to jump), takeaways, quotes and the things named in each section."""
        from magpiary import deepdive

        here = f"/item/{item['id']}?tab=deep"
        status = item.get("deep_status")
        folder = Path(item["archive_dir"]) if item.get("archive_dir") else None
        if status == "done":
            result = (_read_json(folder / "deep.json") if folder else None) or {}
            if result.get("overview"):
                return self._deep_result(result)
        if status in ("queued", "running"):
            return ('<div class="pstate"><b>Deeper dive under way</b><p>It reads every part, then writes the whole. This tab '
                    'fills in by itself; you can leave the page.</p></div>')
        chosen = deepdive.engine(self.store)
        if not chosen["kind"]:
            return ('<div class="pstate"><b>No engine for a deeper dive</b><p>Add an AI key, or choose Claude Code or Codex, in '
                    '<a class="link" href="/settings/ai#deepdive">Settings</a>.</p></div>')
        guess = deepdive.estimate(meta)
        long = deepdive.suggested(self.store, meta)
        why = (f"This video runs {round((meta.get('duration') or 0) / 60)} minutes: the short summary covers only part of it. "
               if long else "")
        what = ("It reads every part of the video in sections, with many more frames, the creator's subtitles when there are "
                "some, the comments and the pages it links to, and writes sections, takeaways and quotes."
                if guess["calls"] > 1 else
                "It reads every slide, many more frames, the full text, the comments, the pages it links to and the "
                "creator's bio links, and writes sections, takeaways and quotes.")
        cost = f'About {guess["calls"]} AI call{"s" if guess["calls"] != 1 else ""} · {guess["minutes"]} min · {chosen["label"]}'
        confirm = (f"This deeper dive needs about {guess['calls']} AI calls on {chosen['label']} and takes about "
                   f"{guess['minutes']} minutes. Start it?") if deepdive.needs_confirm(meta) else ""
        failed = (f'<p class="small muted">Last try did not finish: {e(item.get("deep_detail") or "unknown reason")}.</p>'
                  if status == "failed" else "")
        button = (f'<form method="post" action="/hub/deep"{f" data-confirm={chr(34)}{e(confirm)}{chr(34)}" if confirm else ""}>'
                  f'{ui.hidden(self.csrf, id=item["id"], next=here)}<button class="btn dark" type="submit">'
                  f'{ui.icon("sparkle")}{"Try the deeper dive again" if status == "failed" else "Start the deeper dive"}</button></form>')
        return (f'<div class="deepintro">{"<span class=" + chr(34) + "bd p" + chr(34) + ">Suggested</span>" if long else ""}'
                f'<p class="it-sum">{e(why)}{e(what)}</p><p class="small muted">{e(cost)}. Once per post.</p>{failed}{button}</div>')

    def _deep_result(self, result: dict) -> str:
        from magpiary.deepdive import NAMED_KINDS  # noqa: F401  (kinds shown as written)

        def secs(at: str) -> float:
            try:
                return sum(int(p) * 60 ** i for i, p in enumerate(reversed((at or "").split(":"))))
            except ValueError:
                return -1
        out = [f'<p class="small muted">Made {e(ui.day((result.get("made_at") or "")[:10]))} from '
               f'{e(result.get("text_from") or "the post")}'
               + (f', in {result["parts"]} parts' if (result.get("parts") or 1) > 1 else "") + ".</p>",
               "<h4>Overview</h4>" + "".join(f'<p class="it-sum">{e(p)}</p>' for p in (result.get("overview") or "").split("\n") if p.strip())]
        sections = result.get("sections") or []
        named = result.get("named") or []
        if sections:
            starts = [secs(s.get("at") or "") for s in sections]
            groups: dict[int, list[dict]] = {}
            for n in named:
                t = secs(n.get("at") or "")
                index = max((i for i, st in enumerate(starts) if 0 <= st <= t), default=0) if t >= 0 else 0
                groups.setdefault(index, []).append(n)
            rows = []
            for i, s in enumerate(sections):
                at = s.get("at") or ""
                chips = "".join(f'<span class="chip sm">{e(n["name"])}</span>' for n in groups.get(i, []))
                head = (f'<button type="button" class="kp" data-t="{e(at)}">' if at else '<div class="kp">')
                rows.append(head + f'<b>{i + 1}</b><span><strong>{e(s.get("title") or "")}</strong> {e(s.get("summary") or "")}'
                            + (f'<span class="deepnamed">{chips}</span>' if chips else "") + f'</span><small>{e(at)}</small>'
                            + ("</button>" if at else "</div>"))
            out.append("<h4>Sections <span>· click to jump</span></h4>" + "".join(rows))
        elif named:
            out.append("<h4>Named</h4><div class=\"chips\">" + "".join(f'<span class="chip sm">{e(n["name"])}</span>' for n in named) + "</div>")
        if result.get("takeaways"):
            out.append("<h4>Takeaways</h4><ul class=\"it-sum sm\">" + "".join(f"<li>{e(t)}</li>" for t in result["takeaways"]) + "</ul>")
        if result.get("quotes"):
            out.append("<h4>Quotes</h4>" + "".join(
                f'<blockquote class="deepq"><p>{e(q["text"])}</p>' + (f'<button type="button" class="link" data-t="{e(q["at"])}">{e(q["at"])}</button>' if q.get("at") else "")
                + "</blockquote>" for q in result["quotes"]))
        return f'<div class="deep">{"".join(out)}</div>'


    def _summary_blocks(self, item: dict, record: dict | None) -> str:
        """Blocks a post type adds to the top of the Summary tab (a map for a place, a price list for a product…)."""
        return ""

    def _facets_block(self, item: dict, record: dict | None, here: str) -> str:
        """What the post looks like: the one-line look, then facet groups (Format, Setting, Mood...) as chips that
        open a search for that value. The owner can remove a value or add one; removed values stay removed."""
        have = self.store.facets_for(item["canonical_url"])
        look = (item.get("look") or (record or {}).get("look") or "").strip()
        if not have and not look:
            return ""
        rows = []
        for key, label, values in facets.labelled(have):
            chips = "".join(
                f'<span class="fchip"><a href="/?q={e(quote(v))}" title="Search the library for “{e(v)}”">{e(v)}</a>'
                + ui.button_form(self.csrf, "/hub/facet/remove", {"id": item["id"], "facet": key, "value": v, "next": here}, "×", "link",
                                 title=f"Remove {v}").replace("<form", '<form style="display:inline"') + "</span>" for v in values)
            rows.append(f'<div class="frow"><small>{e(label)}</small><div class="chips">{chips}</div></div>')
        options = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in facets.FACETS.items() if k != "length")
        add = (f'<form method="post" action="/hub/facet/add" class="pvtagadd fadd" hidden>{ui.hidden(self.csrf, id=item["id"], next=here)}'
               f'<select name="facet" aria-label="Kind">{options}</select>'
               f'<input type="text" name="value" maxlength="40" placeholder="e.g. kitchen" aria-label="Value">'
               f'<button class="btn sm" type="submit">Save</button><button class="link" type="button" data-pvhide>Cancel</button></form>'
               f'<button type="button" class="pvaddbtn" data-pvshow>{ui.icon("plus")}Add detail</button>')
        return (f'<h4>Look <span>· what it is like, not what it says</span></h4>'
                + (f'<p class="it-sum sm looksent">{e(look)}</p>' if look else "")
                + f'<div class="facets">{"".join(rows)}</div><div class="pvadd">{add}</div>')

    def _card_tabs(self, item, record, folder, caption, meta, here, tab, context: str = "library") -> str:
        links = self.store.links_for(item["canonical_url"])
        related = []
        lazy_related = tab != "rel" and item.get("status") == "archived" and item.get("shelf") != "trash"
        if not lazy_related and item.get("status") == "archived" and item.get("shelf") != "trash":
            related = rel.related(self.related_library(), item["canonical_url"])
        related_html = (f'<a class="link" href="{here}?tab=rel">Show related saves</a>' if lazy_related
                        else self._related_pane(item, related, here))
        tabs = [("sum", "Summary", "", self._summary_pane(item, record, caption, here)),
                ("links", "Links", str(len(links)) if links else "", self._links_pane(item, links, here, record)),
                ("rel", "Related", str(len(related)) if related else "", related_html),
                ("tr", "Transcript", "", self._transcript_pane(folder)),
                ("det", "Details", "", self._details_pane(item, record, folder, meta))]
        tabs = tabs[:1] + self._extra_tabs(item, record, context) + tabs[1:]  # Ask Magpiary is the second tab, after Summary
        off = self._transcript_off(folder)  # no speech or no transcript: the tab stays, greyed, with the reason on hover
        tab = tab if tab in {t[0] for t in tabs} and tab != off[0] else "sum"
        kind = type_of(record) if record else ""
        tint = ui.deep(ui.type_colour(kind)) if record else ui.deep(ui.source_colour(item["source"]))
        nav = (f'<nav class="tabs pvtabs" role="tablist" style="--tc:{tint}">' + "".join(
            (f'<a role="tab" data-tab="{k}" class="off" aria-disabled="true" tabindex="-1" title="{e(off[1])}" aria-label="{name}: {e(off[1])}">{name}</a>'
             if k == off[0] else
             f'<a href="#{k}" role="tab" data-tab="{k}" class="{"on" if k == tab else ""}" '
             f'aria-selected="{str(k == tab).lower()}">{name}' + (f"<small>{n}</small>" if n else "") + "</a>")
            for k, name, n, _ in tabs) + "</nav>")
        return nav + "".join(f'<section class="pane" id="{k}" role="tabpanel" data-pane="{k}"'
                             + (f' data-related-src="{here}?frag=1&amp;tab=rel&amp;from=preview"' if k == "rel" and lazy_related else "")
                             + f'>{v}</section>'
                             for k, _, _, v in tabs)

    def _list_block(self, item: dict, record: dict | None) -> str:
        """A list post's items (a round-up, "10 tools"): each with who made it, the poster's note and its link once found."""
        items = (record or {}).get("list_items") or []
        if not items:
            return ""
        found = {}
        for link in self.store.links_for(item["canonical_url"]):
            if link.get("role", "main") == "main":
                found.setdefault(link["name"].lower(), link)
        kinds = {"video": "Video", "article": "Article", "book": "Book", "show": "Show", "film": "Film", "podcast": "Podcast",
                 "music": "Music", "course": "Course", "tool": "Tool", "product": "Product", "place": "Place"}
        rows = []
        for n, it in enumerate(items, 1):
            link = found.get(it["name"].lower())
            name = (f'<a href="{e(link["url"])}" target="_blank" rel="noopener noreferrer">{e(it["name"])} ↗</a>'
                    if link else f'<b>{e(it["name"])}</b>')
            meta = " · ".join(x for x in (kinds.get(it.get("kind"), ""), it.get("by") or "",
                                          f'slide {it["slide"]}' if it.get("slide") else "") if x)
            flag = ('<span class="bd p">possible match</span>' if link and link.get("rank") == "possible"
                    else "" if link or not links_done(item) else '<span class="bd">No link found</span>')
            rows.append(f'<li class="pvli"><div>{name}{flag}</div><small>{e(meta)}</small>'
                        + (f'<p>{e(it["note"])}</p>' if it.get("note") else "") + "</li>")
        return f'<h4>The list <span>· {len(items)} things</span></h4><ol class="pvlist">{"".join(rows)}</ol>'

    def _note_block(self, item: dict, here: str) -> str:
        """Your note, right under the summary: a button until you write one, then plain text with an Edit button."""
        out: list[str] = []
        note = item.get("note") or ""
        out.append('<h4>Your note</h4><div class="pvadd pvnoteblock">'
                   + (f'<p class="pvnote">{e(note)}</p>' if note else "")
                   + f'<button type="button" class="pvaddbtn" data-pvshow>{ui.icon("plus")}{"Edit note" if note else "Add note"}</button>'
                   + f'<form method="post" action="/hub/note" class="pvnoteform" hidden>{ui.hidden(self.csrf, id=item["id"], next=here)}'
                   f'<textarea class="note" name="note" placeholder="Why did you save this?" aria-label="Your note">{e(note)}</textarea>'
                   f'<div class="row" style="margin-top:8px"><button class="btn sm" type="submit">Save note</button>'
                   f'<button class="link" type="button" data-pvhide>Cancel</button></div></form></div>')
        return "".join(out)

    def _agent_note_block(self, item: dict, here: str) -> str:
        """What an AI agent wrote on this save (through `magpiary note`): labelled, read-only, and the owner can remove it."""
        note = item.get("agent_note") or ""
        if not note:
            return ""
        who = item.get("agent_note_by") or "an AI agent"
        when = (item.get("agent_note_at") or "")[:10]
        return (f'<h4>Note from {e(who)}</h4><div class="pvadd pvnoteblock pvagentnote">'
                f'<p class="pvnote">{e(note)}</p><small class="pvmuted">Written by an AI agent{(" on " + e(when)) if when else ""}. '
                f'It is not your note, and it never changes it.</small>'
                + self._form("/hub/agentnote/remove", {"id": item["id"], "next": here}, "Remove this note", "link")
                + "</div>")

    def _caption_block(self, item: dict, meta: dict, caption: str) -> str:
        """The post as its maker wrote it: who (avatar, name, @handle) on top, the caption, then where and when it was posted."""
        from magpiary.hub import rich_text

        name = item.get("author") or meta.get("author") or ""
        handle = meta.get("author_handle") or ""
        handle = "" if handle.isdigit() else handle  # older archives stored Instagram's numeric id
        who = ""
        if name or handle:
            who = (f'<div class="pvwho">{ui.avatar(name or handle, "rgba(255,255,255,.2)", "", "pvav")}'
                   f'<span><b>{e(name or "@" + handle)}</b>'
                   + (f'<small>@{e(handle)}</small>' if handle and name and handle != name else "") + "</span></div>")
        posted = ui.day(meta.get("published_at") or item.get("published_at"))
        foot = (f'<div class="pvwhere">{e(ui.source_name(item["source"]))}'
                + (f" · posted {e(posted)}" if posted else "") + "</div>")
        if not caption:
            return f'<div class="capb pvcapb">{who}{foot}</div>'
        text = f'<p class="cap2">{rich_text(caption, item["source"])}</p>'
        if len(caption) <= SHORT_CAPTION:
            return f'<div class="capb pvcapb short">{who}{text}{foot}</div>'
        return (f'<div class="capb pvcapb long" data-fold>{who}{text}{foot}'
                f'<button type="button" class="capt" hidden>Show the whole caption</button></div>')

    def _summary_pane(self, item: dict, record: dict | None, caption: str, here: str) -> str:
        out = [self._summary_blocks(item, record)]  # the summary itself sits under the title (_lead), the caption after it
        out.append(self._list_block(item, record))
        if record:
            extras = record.get("extras") or {}
            for label, key in (("Ingredients", "ingredients"), ("Steps", "steps"), ("Takeaways", "takeaways")):
                if extras.get(key):
                    out.append(f"<h4>{label}</h4><ol class=\"it-sum sm\">" + "".join(f"<li>{e(x)}</li>" for x in extras[key]) + "</ol>")
            facts = [(label, extras.get(key)) for label, key in (
                ("Tool", "tool_name"), ("Link", "tool_url"), ("Price", "pricing"), ("Place", "place_name"), ("City", "city"),
                ("Why", "why"), ("Title", "media_title"), ("Kind", "media_kind"), ("Claim", "claim"), ("Source", "claim_source"))
                if extras.get(key)]
            if facts:
                out.append("<h4>Details</h4>" + "".join(
                    f'<p class="it-sum sm"><b>{e(k)}:</b> {self._outlink(v) or e(v)}</p>' if k == "Link" else
                    f'<p class="it-sum sm"><b>{e(k)}:</b> {e(v)}</p>' for k, v in facts))
            if record.get("discussion_summary"):
                out.append(f'<h4>The discussion</h4><p class="it-sum sm">{e(record["discussion_summary"])}</p>')
        tags = "".join(
            f'<span>#{e(t)} '
            + ui.button_form(self.csrf, "/hub/tag/remove", {"id": item["id"], "tag": t, "next": here}, "×", "link",
                             title=f"Remove the tag {t}").replace("<form", '<form style="display:inline"')
            + "</span>" for t in item["tags"])
        suggested = [t for t in (record or {}).get("suggested_tags", []) if t not in item["tags"]]
        add = (f'<form method="post" action="/hub/tag/add" class="pvtagadd" hidden>{ui.hidden(self.csrf, id=item["id"], next=here)}'
               f'<input type="text" name="tag" maxlength="40" placeholder="New tag" aria-label="New tag">'
               f'<button class="btn sm" type="submit">Save</button>'
               f'<button class="link" type="button" data-pvhide>Cancel</button></form>'
               f'<button type="button" class="pvaddbtn" data-pvshow>{ui.icon("plus")}Add tag</button>')
        piles = self.store.piles_for(item["canonical_url"]) if item["status"] == "archived" else []
        in_piles = ('<h4>Pile</h4><div class="chips">' + "".join(
            f'<a class="pvpile" href="/pile/{p["id"]}" title="Open the pile {e(p["name"])}">{ui.icon("folder")}{e(p["name"])}</a>' for p in piles)
            + "</div>") if piles else ""
        out.append(self._note_block(item, here))
        out.append(self._agent_note_block(item, here))
        out.append(f'<h4>Tags <span>· {"added by the AI, " if record else ""}yours to change</span></h4>'
                   f'<div class="chips">{tags}</div><div class="pvadd">{add}</div>' + in_piles)
        out.append(self._facets_block(item, record, here))
        if suggested:
            out.append(f'<p class="small muted" style="margin:8px 0 0">Suggested tags: {" ".join("#" + e(t) for t in suggested)} '
                       + self._form("/hub/accept-tags", {"id": item["id"], "next": here}, "Add them", "link")
                       .replace("<form", '<form style="display:inline"') + "</p>")
        moments = (record or {}).get("key_points") or []
        if moments:
            timed = any(m.get("at") for m in moments)
            out.append(f'<h4>Key moments{" <span>· click to jump</span>" if timed else ""}</h4>' + "".join(
                (f'<button type="button" class="kp" data-t="{e(m["at"])}">' if m.get("at") else '<div class="kp">')
                + f'<b>{n}</b><span>{e(m["text"])}</span><small>{e(m.get("at") or "")}</small>'
                + ("</button>" if m.get("at") else "</div>") for n, m in enumerate(moments, 1)))
        return "".join(out)

    def _site_icon(self, url: str) -> str:
        """The little icon of the site a link goes to: a built-in mark, the icon this Mac fetched once, or a globe."""
        host = icons.host_of(url if "://" in url else "https://" + url)
        mark = icons.builtin(host)
        if mark in ui.SOCIAL_ICONS:
            inner = ui.social_icon(mark)
        elif mark in icons.EXTRA_MARKS:
            inner = f'<svg class="soc" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{icons.EXTRA_MARKS[mark]}</svg>'
        elif icons.cached(host):
            inner = f'<img src="/icon/{e(host)}" alt="" width="18" height="18" loading="lazy">'
            return f'<span class="fav pic" aria-hidden="true">{inner}</span>'
        else:
            inner = ui.social_icon("website")
        return f'<span class="fav" aria-hidden="true">{inner}</span>'

    def _outlink(self, text: str, label: str = "", cls: str = "xl") -> str:
        """A web address the post names, as a link that opens the website (never the post's own address)."""
        raw = (text or "").strip()
        url = raw if "://" in raw else "https://" + raw
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname or " " in raw:
            return ""
        return (f'<a class="{cls}" href="{e(url)}" target="_blank" rel="noopener noreferrer" '
                f'aria-label="Open {e(label or raw)} (opens the website)">{self._site_icon(url)}{e(label or raw)} <span aria-hidden="true">↗</span></a>')

    def _mentioned(self, item: dict, record: dict) -> str:
        """Names the post mentions. Web addresses open the website (↗); every other name searches this library
        (magnifier), so the two no longer look alike. The post's own address is left out."""
        def key(u: str) -> str:
            u = u if "://" in u else "https://" + u
            return links_host(u) + urlsplit(u).path.rstrip("/")

        own = key(item["canonical_url"])
        chips, seen = [], set()
        for kind, values in (record.get("entities") or {}).items():
            for v in values:
                if v in seen:
                    continue
                seen.add(v)
                if kind == "links":
                    if key(v) == own:
                        continue
                    chip = self._outlink(v)
                    if chip:
                        chips.append(chip.replace(" href=", ' data-kind="links" href=', 1))
                        continue
                chips.append(f'<a class="qs" href="/?q={e(v)}" aria-label="Search your library for {e(v)}" title="Search your library" data-kind="{e(kind)}">'
                             f'{e(v)}</a>')
        if not chips:
            return ""
        shown, more = chips[:SHOWN_CHIPS], chips[SHOWN_CHIPS:]
        extra = "".join(c.replace('<a class="', '<a hidden class="pvx ', 1) for c in more)
        button = (f'<button type="button" class="pvmorebtn" data-pvmore data-more="+{len(more)} more">+{len(more)} more</button>' if more else "")
        return '<div class="chips pvment" aria-label="Mentioned in this post"><small class="pvmentl">Mentioned</small>' + "".join(shown) + extra + button + "</div>"

    def _links_pane(self, item: dict, links: list[dict], here: str, record: dict | None = None) -> str:
        from magpiary.links import KINDS

        rows: dict[tuple, list[dict]] = {}  # one row per name: its main link, then its badges
        for link in links:
            rows.setdefault((link.get("section") or "named", link["name"]), []).append(link)
        back = here + "?tab=links"

        def row(group: list[dict]) -> str:
            main = next((l for l in group if l.get("role", "main") == "main"), group[0])
            host = (urlsplit(main["url"]).hostname or "").removeprefix("www.")
            flags = ""
            if main["rank"] == "possible":
                flags += '<span class="bd p">possible match</span>'
            if main["checked"] != "yes":
                flags += '<span class="bd" title="The site blocks checks">not checked</span>'
            chips = "".join(
                f'<span class="lkb"><a href="{e(b["url"])}" target="_blank" rel="noopener noreferrer">{e(b["source"])} ↗</a>'
                + self._form("/hub/links/remove", {"id": item["id"], "link_id": b["id"], "next": back}, "×", "link")
                + "</span>" for b in group if b is not main)
            return (f'<div class="lk"><div>{self._site_icon(main["url"])}<b>{e(main["name"])}</b><span class="bd">{e(KINDS.get(main["kind"], ""))}</span>'
                    f'{flags}<br><a href="{e(main["url"])}" target="_blank" rel="noopener noreferrer">'
                    f'{e(link_title(main["title"], host))} ↗</a><small>{e(host)} · {e(main["source"])}</small>'
                    + (f'<div class="lkbs">{chips}</div>' if chips else "") + '</div>'
                    + self._form("/hub/links/remove", {"id": item["id"], "link_id": main["id"], "next": back},
                                 "Remove", "link") + "</div>")

        named = [g for (section, _), g in rows.items() if section == "named"]
        central = [g for g in named if any(l.get("central", 1) for l in g)]
        passing = [g for g in named if g not in central]
        alternatives = [g for (section, _), g in rows.items() if section != "named"]
        out = [row(g) for g in central]
        if passing:
            out.append(f'<details class="lkmore"{" open" if not central else ""}><summary>'
                       f'{"Also mentioned" if not central else f"Show {len(passing)} more"}</summary>'
                       + "".join(row(g) for g in passing) + "</details>")
        known = {n.lower() for (_, n) in rows}
        missing = [n for n in ((record or {}).get("entities") or {}).get("tools", []) if n.lower() not in known]
        if missing and links_done(item):
            out.append("".join(
                f'<div class="lk pvnolink"><div><b>{e(n)}</b><span class="bd">No link found yet</span></div>'
                + ('<span class="bd">Looking…</span>' if item.get("links_force") else self._form("/hub/links/again", {"id": item["id"], "next": back}, "Find it", "btn sm")) + "</div>"
                for n in missing[:6]))
        if alternatives:
            out.append('<div class="lkh">Also worth a look</div>' + "".join(row(g) for g in alternatives))
        if not links:
            if item.get("ai_status") != "done" and modes.current(self.store) != "private":
                out.append('<p class="muted">Links are found once the post has been read.</p>')
            elif item.get("links_status") is None:
                out.append('<p class="muted">Looking for links…</p>')
            else:
                out.append('<p class="muted">No links found for this post.</p>')
        kinds = "".join(f'<option value="{k}"{" selected" if k == "links" else ""}>{e(v)}</option>' for k, v in KINDS.items())
        out.append(f'<h4>Add a link</h4><form method="post" action="/hub/links/add" class="linkadd">'
                   f'{ui.hidden(self.csrf, id=item["id"], next=here + "?tab=links")}'
                   f'<input type="text" name="name" required maxlength="80" placeholder="Name, e.g. frontend-design" aria-label="Name">'
                   f'<input type="url" name="url" required placeholder="https://" aria-label="Link">'
                   f'<select name="kind" aria-label="Kind">{kinds}</select><button class="btn sm" type="submit">Add</button></form>'
                   f'<div class="row" style="margin-top:14px">'
                   + ('<span class="bd looking">Looking…</span>' if item.get("links_force")
                      else self._form("/hub/links/again", {"id": item["id"], "next": here + "?tab=links"}, "Find more links", "btn sm"))
                   + '<span class="small muted">The post\'s own links first, then free directories (Wikidata, GitHub, '
                   'App Store, Wikipedia, OpenStreetMap, Crossref), then a web search if you added a key. Never your AI '
                   'quota.</span></div>')
        return "".join(out)

    def _related_pane(self, item: dict, related: list[dict], here: str) -> str:
        if item.get("status") != "archived" or item.get("shelf") == "trash":
            return '<p class="muted">Related saves show up once this post is saved.</p>'
        if not related:
            waiting = item["canonical_url"] not in self.store.vectors(rel.MODEL)
            return (f'<p class="muted">{"Finding related saves…" if waiting else "Nothing related yet. Related saves show up here as your library grows."}</p>')
        rows = []
        for r in related[:RELATED_SHOWN]:
            other = r["row"]
            thumb = self.thumb_url(other)
            who = other.get("author") or ui.source_name(other["source"])
            rows.append(f'<div class="rel"><a class="th" href="/item/{other["id"]}" style="background:{ui.gradient(other)}">'
                        + (f'<img loading="lazy" src="{e(thumb)}" alt="">' if thumb else "") + "</a>"
                        f'<a href="/item/{other["id"]}"><b>{e(rel.title_of(other)[:120])}</b><small>{e(who)} · '
                        f'{e(ui.source_name(other["source"]))}</small><em>{e(r["reason"])}</em></a>'
                        + self._form("/hub/not-related", {"id": item["id"], "other": other["id"], "next": here + "?tab=rel"},
                                     "Not related", "link") + "</div>")
        more = (f'<p style="margin:12px 8px 0"><a class="btn sm" href="{here}/related">See all {len(related)} related →</a></p>'
                if len(related) > RELATED_SHOWN else
                f'<p style="margin:12px 8px 0"><a class="link" href="{here}/related">More like this →</a></p>')
        library = self.related_library()
        return ((local_map_html(self.store, item["id"], library) if library is not None else "") +
                '<p class="small muted" style="margin:10px 8px">Best match first: the same named things, the same tags and '
                'the same topic all count. “Not related” takes one out for good.</p>' + "".join(rows) + more)

    def _screen_cloud(self, item: dict, folder: Path | None, here: str) -> str:
        """Words read off the screen as a small cloud, last on the Details tab. Hover shows when a word was on screen."""
        lines = (_read_json(folder / "ocr.json") if folder else None) or []
        if not lines:
            if item.get("screen_text") is None:
                return '<h4>On screen</h4><p class="muted">Not read yet. It is read quietly on this Mac after the post is summarised.</p>'
            return '<h4>On screen</h4><p class="muted">No text found on screen.</p>'
        words = ocr.cloud(lines)
        if not words:
            return ""
        top = max(w["count"] for w in words)

        def when(secs: list) -> str:
            return " · ".join(f"{int(t) // 60}:{int(t) % 60:02d}" for t in secs[:6]) if secs else "in a photo"

        cloud = "".join(
            f'<span class="pvw" style="--s:{12.5 + 6.5 * (w["count"] - 1) / max(top - 1, 1):.1f}px" title="{e(when(w["at"]))}">{e(w["word"])}</span>'
            for w in words)
        return (f'<h4>On screen <span>· read from the video on this Mac</span></h4><div class="pvcloud">{cloud}</div>'
                + self._form("/hub/screen-again", {"id": item["id"], "next": here + "?tab=det"}, "Read again", "link"))

    def _details_pane(self, item: dict, record: dict | None, folder: Path | None, meta: dict) -> str:
        from magpiary.hub import rich_text

        out = []
        discussion = _read_json(folder / "discussion.json") if folder else None
        if discussion:
            out.append(f'<details class="fold" style="margin-top:22px"><summary>{len(discussion)} comments saved</summary>'
                       + "".join(f'<div class="cmt"><b>{e(c.get("author", ""))}</b>{rich_text(c.get("text", ""), "")}</div>'
                                 for c in discussion[:200]) + "</details>")
        out.append(self._timing(item))
        engine = (record or {}).get("engine") or {}
        details = [("Source", ui.source_name(item["source"])), ("Link", item["canonical_url"]),
                   ("First saved", when(item.get("first_shared_at"))), ("Times shared", str(item["saved_count"]))]
        if meta.get("published_at"):
            details.append(("Posted", ui.day(meta["published_at"])))
        if engine:
            details.append(("Summary by", engine.get("brain", "?") + (f' using {engine["key"]}' if engine.get("key") else "")))
            if record.get("frames"):
                details.append(("Frames read", str(len(record["frames"]))))
            if engine.get("problem"):
                details.append(("Note", engine["problem"]))
        details.append(("Folder", "library/" + (Path(item["archive_dir"]).name if item.get("archive_dir") else "(not yet)")))
        if item["shelf"] == "trash" and item.get("trashed_at"):
            gone = datetime.fromisoformat(item["trashed_at"]) + timedelta(days=TRASH_DAYS)
            details.append(("Deleted for good", ui.day(gone.isoformat())))
        out.append('<h4>Details</h4><div class="dgrid">' + "".join(f"<span>{e(k)}</span><span>{e(v)}</span>" for k, v in details)
                   + "</div>")
        out.append(self._screen_cloud(item, folder, f"/item/{item['id']}"))
        return "".join(out)

    def _transcript_off(self, folder: Path | None) -> tuple[str, str]:
        """("tr", why) when the Transcript tab has nothing to show, else ("", "")."""
        segs = ((_read_json(folder / "transcript.json") or {}).get("segments") if folder else None)
        if segs and any(_spoken(s.get("text", "")) for s in segs):
            return "", ""
        return "tr", "No transcript detected"

    def _transcript_pane(self, folder: Path | None) -> str:
        """What was said, a line at a time: click a line to jump there; the line being spoken lights up as the video plays."""
        out: list[str] = []
        segs = ((_read_json(folder / "transcript.json") or {}).get("segments") if folder else None)
        if segs is not None:
            if segs:
                out.append('<small class="pvlabel">Spoken · written down on this Mac</small>' + "".join(
                    f'<button type="button" class="tline" data-t="{int(x["start"]) // 60}:{int(x["start"]) % 60:02d}">'
                    f'<small>{int(x["start"]) // 60}:{int(x["start"]) % 60:02d}</small><span>{e(x["text"])}</span></button>'
                    for x in segs))
            else:
                out.append('<p class="muted">No speech in this post (music only?).</p>')
        return "".join(out)

    def _timing(self, item: dict) -> str:
        t = self.store.timings_for(item["canonical_url"])
        if not t:
            return ""
        rows = []
        try:
            if item.get("first_shared_at") and item.get("created_at"):
                wait = (datetime.fromisoformat(item["created_at"]) - datetime.fromisoformat(item["first_shared_at"])).total_seconds()
                if wait >= 1:
                    rows.append(("Waiting on the phone", wait))
        except (ValueError, TypeError):
            pass
        for step in ("fetch", "download", "transcribe", "frames", "summary"):
            if step in t:
                rows.append((STEPS[step], t[step]))
        return ('<h4>How long it took</h4><table class="timet">' + "".join(
            f"<tr><td>{e(k)}</td><td>{ui.secs(v)}</td></tr>" for k, v in rows)
            + f'<tr class="tot"><td>Magpiary total</td><td>{ui.secs(sum(t.values()))}</td></tr></table>')
