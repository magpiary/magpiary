"""The local web hub: routing, owner actions and the shared page frame.

Page mixins render the library, posts, boards, Ask, Settings and the first-run guide;
hub_media serves archived media and profile photos. The hub checks local access and
the optional lock before dispatching to them.

Content from phones and websites is escaped, pages carry a strict Content-Security-Policy,
and archived media is served only by name from inside the configured library.
"""

import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from magpiary import keys as keyring
from magpiary import login, modes, ui
from magpiary.activity import Activity
from magpiary.brain import Call, http_call
from magpiary.cleaner import UnsupportedLink
from magpiary.hub_ask import AskPages
from magpiary.hub_askset import AskSettings
from magpiary.hub_card import CardPages
from magpiary.hub_nest import NestPages
from magpiary.hub_piles import RelatedPages
from magpiary.hub_boards import BoardPages
from magpiary.hub_checklist import ChecklistPages
from magpiary.hub_activity import ActivityPages
from magpiary.hub_digest import DigestPages
from magpiary.hub_help import HelpPages
from magpiary.hub_lock import LockPages
from magpiary.hub_map import MapPages
from magpiary.hub_media import MediaPages
from magpiary.hub_settings import SettingsPages
from magpiary.hub_wall import WallPages
from magpiary.hub_welcome import WelcomePages
from magpiary.store import Store
from magpiary.web import Response, e, local_only

VIDEO = (".mp4", ".webm", ".mov")
BOARD_WATCH_EVERY = 30  # seconds between board syncs while a board is on screen
AI_REASONS = {"busy": "the AI was too busy or slow; trying again later", "no_key": "no AI key yet", "bad_key": "the key was refused", "rate_limited": "the AI's limit was reached",
              "blocked": "the AI declined this post", "invalid": "the AI's answer was not usable", "unknown": "something went wrong"}
ERRORS = {"unsupported": "That does not look like a link to a post.", "empty": "Paste a link first."}


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


PROFILE = {"instagram": "https://www.instagram.com/{}/", "threads": "https://www.threads.com/@{}",
           "x": "https://x.com/{}", "youtube": "https://www.youtube.com/@{}"}
RICH = re.compile(r"(?P<url>\bhttps?://[^\s<>\"')\]]+)|(?P<at>(?<![\w.@])@[A-Za-z0-9_.]{2,30})|(?P<tag>(?<![\w&#])#\w{2,50})")


def rich_text(text: str, source: str) -> str:
    """Escaped text with clickable links, @mentions (the profile on the same platform) and #hashtags (your library)."""
    out, last = [], 0
    for m in RICH.finditer(text or ""):
        out.append(e(text[last:m.start()]))
        last = m.end()
        token = m.group(0)
        if m.group("url"):
            url = token.rstrip(".,;:!?")
            out.append(f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(url)}</a>{e(token[len(url):])}')
        elif m.group("at") and source in PROFILE:
            handle = token[1:].rstrip(".")
            out.append(f'<a href="{e(PROFILE[source].format(quote(handle)))}" target="_blank" rel="noopener noreferrer">'
                       f'@{e(handle)}</a>{e(token[1 + len(handle):])}')
        elif m.group("tag"):
            out.append(f'<a href="/?{e(urlencode({"q": token[1:]}))}">{e(token)}</a>')
        else:
            out.append(e(token))
    out.append(e((text or "")[last:]))
    return "".join(out)


def details_from_folder(folder: Path) -> dict:
    """What the hub lists for an archived item, from its meta.json."""
    try:
        meta = json.loads((folder / "meta.json").read_text())
    except (OSError, ValueError):
        return {}
    media = meta.get("media") or []
    videos = [m for m in media if m.endswith(VIDEO)]
    kind = "video" if videos else ("photos" if media else "text")
    caption = meta.get("text") or ""
    return {"title": meta.get("title") or "", "author": meta.get("author") or meta.get("author_handle") or "",
            "caption": caption, "thumb": meta.get("thumbnail"), "media_kind": kind,
            "published_at": meta.get("published_at") or ""}


def backfill_details(store: Store) -> int:
    """Items archived before the hub existed get their listing details once."""
    done = 0
    for item in store.items():
        if item["status"] == "archived" and item.get("caption") is None and item.get("archive_dir"):
            store.set_details(item["canonical_url"], details_from_folder(Path(item["archive_dir"])))
            done += 1
    return done


class Hub(
    WallPages,
    AskPages,
    AskSettings,
    CardPages,
    NestPages,
    SettingsPages,
    HelpPages,
    DigestPages,
    WelcomePages,
    RelatedPages,
    MapPages,
    BoardPages,
    LockPages,
    ChecklistPages,
    ActivityPages,
    MediaPages,
):
    def __init__(
        self,
        store: Store,
        library: Path | None = None,
        wake: Callable[[], None] = lambda: None,
        call: Call = http_call,
        activity: Activity | None = None,
    ) -> None:
        self.store, self.library, self.wake, self.call = store, library, wake, call
        self.activity = activity or Activity(store)
        from magpiary.lock import Lock

        self.lock = Lock(store)  # the service starts its watcher (lock.watch()); without one it still checks on each request
        self._csrf = secrets.token_urlsafe(24)
        self.setup = None  # the pairing side (setup.Setup), when the service runs one
        from magpiary import boards, boardsync

        boards.sort_sharing(store)  # once: boards with only their maker on them become solo (sync off)
        self.sync_call, self.relay_connect = boardsync.http_call, None  # tests swap these (None: the real relays)
        self.sync_boards = self._sync_here  # Sync now; the service hands it to its board lane instead
        self._boards_watched = 0.0
        self.meaning = None  # the warm meaning model (embed.Warm) for search by meaning, when the service runs one
        # after an update the service exits and launchd starts the new copy (KeepAlive)
        self.restart = lambda: threading.Timer(2.0, os._exit, (0,)).start()

    # ---- routing ------------------------------------------------------------------------

    def get(self, path: str, query: dict, client_ip: str, host: str, range_header: str = "") -> Response:
        refused = local_only(client_ip, host)
        if refused:
            return refused
        if path.startswith("/static/"):
            return ui.static(path)
        if held := self.locked_get(path, query):
            return held
        q = {k: v[0] for k, v in query.items()}
        if path in ("/lock", "/lock.json"):
            return self.lock_get(path, q)
        if path == "/panel.json":
            return self.panel_json()
        if path == "/":
            if self.needs_welcome():
                return Response(303, b"", headers={"Location": "/welcome"})
            return self.wall_page(q)
        if path == "/add":
            return self.add_page(q)
        if path == "/welcome" or path.startswith("/welcome/"):
            return self.welcome_page(path.removeprefix("/welcome").strip("/"), q)
        if path == "/welcome.json":
            return self.welcome_json()
        if path == "/pair.json":  # the QR window's ticks and countdown
            status = self.setup.status(q.get("qr", "")) if self.setup else None
            return Response(200 if status else 404, json.dumps(status or {}).encode(), "application/json")
        if path == "/settings" or path.startswith("/settings/"):
            return self.settings_page(path.removeprefix("/settings").strip("/"), q)
        if path == "/digest" or path.startswith("/digest/"):
            return self.digest_page(path.removeprefix("/digest").strip("/"), q)
        if path == "/help":
            return self.help_page(q)
        if m := re.fullmatch(r"/join/([A-Za-z0-9-]{12,24})", path):
            return self.join_page(m.group(1))
        if m := re.fullmatch(r"/board/([0-9a-f]{16})/pick", path):
            if not self.store.board(m.group(1)):
                return Response(404, b"not found", "text/plain")
            return Response(200, self.add_rows(m.group(1), q.get("q", "")[:200]).encode(), "text/html; charset=utf-8")
        if m := re.fullmatch(r"/board/([a-z0-9-]{1,80})", path):
            return self.board_route(m.group(1), q)
        if path == "/profile/photo.jpg":
            return self._profile_photo()
        if m := re.fullmatch(r"/icon/([a-z0-9.-]{1,253})", path):
            from magpiary import icons

            found = icons.cached(m.group(1))
            if not found:
                return Response(404, b"none", "text/plain")
            return Response(200, found.read_bytes(), icons.content_type(found),
                            headers={"Cache-Control": "max-age=86400", "X-Content-Type-Options": "nosniff"})
        if m := re.fullmatch(r"/ask/card-img/([0-9a-f]{16})", path):
            from magpiary import ask_cards

            found = ask_cards.image_path(m.group(1))
            if not found:
                return Response(404, b"none", "text/plain")
            return Response(200, found.read_bytes(), ask_cards.content_type(found),
                            headers={"Cache-Control": "max-age=604800", "X-Content-Type-Options": "nosniff"})
        if path == "/ask":
            return self.ask_page(q)
        if path == "/ask/poll":
            return self.ask_poll(q)
        if path == "/ask/panel":
            return self.ask_panel(q)
        if path == "/ask/sessions":
            return self.ask_sessions_page(q)
        if path == "/ask/session":
            return self.ask_session_page(q)
        if path == "/nest":
            return self.nest_page(fragment=q.get("frag") == "1", tab=q.get("tab", "now"))
        if path == "/queue":
            return self.deliveries_page()
        if path == "/stats/estimate.json":
            return self._stats_estimate(q)
        if path == "/stats/status.json":
            return self._stats_status()
        if path == "/activity.json":
            return self._activity_json(q)
        if path == "/boards.json":
            from magpiary import boards

            data = [{"id": b["id"], "name": b["name"], "n": len(boards.view(self.store, b["id"])["cards"])}
                    for b in self.store.boards()]
            return Response(200, json.dumps(data).encode(), "application/json", headers={"Cache-Control": "no-store"})
        if path == "/checklist/panel":
            return self.checklist_fragment()
        if path == "/map":
            return self.map_page(q)
        if path == "/graph.json":
            return self.graph_json(q)
        if path == "/search.json":
            return self._search_json(q.get("q", ""), q.get("piles") == "1")
        if m := re.fullmatch(r"/item/(\d+)", path):
            return self.card_page(int(m.group(1)), fragment=q.get("frag") == "1", tab=q.get("tab", ""),
                                  board=q.get("board", "") if re.fullmatch(r"[0-9a-f]{16}", q.get("board", "")) else "",
                                  pile=q.get("pile", "") if q.get("pile", "").isdigit() else "", frm=q.get("from", ""))
        if m := re.fullmatch(r"/item/(\d+)/related", path):
            return self.related_page(int(m.group(1)))
        if path == "/doctor":
            return self.doctor_page(False)  # live checks require an explicit action on the page
        if path == "/doctor.json":
            return self.doctor_json(q)
        if m := re.fullmatch(r"/pile/(\d+)", path):
            return self.pile_page(int(m.group(1)))
        if m := re.fullmatch(r"/media/(\d+)/([^/]+)", path):
            return self._media(int(m.group(1)), m.group(2), range_header, q.get("w", ""))
        return self.shell("Not found", '<p class="empty">Nothing here. <a class="link" href="/">Back to the library</a></p>',
                          "missing", 404)

    def post(self, path: str, form: dict, client_ip: str, host: str, origin: str | None) -> Response:
        refused = local_only(client_ip, host)
        if refused:
            return refused
        if origin and urlsplit(origin).hostname not in ("localhost", "127.0.0.1", "::1"):
            return self.shell("Refused", "<p>This request came from another website.</p>", "missing", 403)
        if not hmac.compare_digest(form.get("csrf", "").encode(), self._csrf.encode()):
            return self.shell("Refused", '<p>This page has expired. <a class="link" href="/">Reload the library</a>.</p>',
                              "missing", 403)
        if held := self.locked_post(path):
            return held
        if path.startswith("/hub/lock/") and (done := self.lock_post(path, form, host)) is not None:
            return done
        back = _safe_next(form.get("next", "/"))
        item_id = int(form["id"]) if form.get("id", "").isdigit() else 0
        if path == "/hub/doctor":
            return self.doctor_json({"start": "1", "live": form.get("live", "0")}, authorized_start=True)
        if path == "/hub/checklist":
            return self.checklist_post(form)
        if path == "/hub/activity":
            return self.activity_post(form)
        if path.startswith("/hub/ask/"):
            return self.ask_post(path, form)
        if path == "/hub/pile/note-delete":
            if form.get("note", "").isdigit():
                self.store.ask_note_delete(int(form["note"]))
            return Response(303, b"", headers={"Location": back})
        if path == "/hub/panel/save":
            return self.panel_save(form.get("url", ""))
        if path == "/hub/add":
            return self._add(form.get("url", ""), form.get("next", ""))
        if self.pile_post(path, form) or self.welcome_post(path, form) or self.settings_post(path, form) or self.help_post(path, form):
            return Response(303, b"", headers={"Location": back})
        if (handled := self.phones_post(path, form)) is not None or (handled := self.settings_redirects(path, form)) is not None \
                or (handled := self.digest_post(path, form)) is not None or (handled := self.boards_post(path, form)) is not None:
            return handled
        if path == "/hub/bulk":
            self._bulk(form)
        elif path == "/hub/tags":
            self.store.set_tags(item_id, form.get("tags", ""))
        elif path == "/hub/screen-again":
            item = self.store.item_by_id(item_id)
            if item:
                self.store.reset_screen(item["canonical_url"])
                self.wake()
        elif path == "/hub/tag/add":
            item = self.store.item_by_id(item_id)
            if item:
                self.store.set_tags(item_id, ", ".join(item["tags"] + [form.get("tag", "").replace(",", " ")]))
        elif path == "/hub/tag/remove":
            item = self.store.item_by_id(item_id)
            if item:
                self.store.set_tags(item_id, ", ".join(t for t in item["tags"] if t != form.get("tag", "")))
        elif path in ("/hub/facet/add", "/hub/facet/remove"):
            item = self.store.item_by_id(item_id)
            if item and path.endswith("add"):
                self.store.add_facet(item["canonical_url"], form.get("facet", ""), form.get("value", ""))
            elif item:
                self.store.remove_facet(item["canonical_url"], form.get("facet", ""), form.get("value", ""))
            self.store.set_setting("piles_dirty", "1")
        elif path == "/hub/view/save":
            self.store.save_view(form.get("q", ""), {"q": form.get("q", ""), "no": [x for x in form.get("no", "").split("|") if x]})
        elif path == "/hub/view/delete":
            self.store.delete_view(int(form["view"])) if form.get("view", "").isdigit() else None
        elif path == "/hub/note":
            self.store.set_note(item_id, form.get("note", ""))
        elif path == "/hub/agentnote/remove":
            self.store.set_agent_note(item_id, "clear")  # the old version stays in the history, so an agent can still undo it
        elif path == "/hub/shelf":
            self.store.set_shelf(item_id, form.get("shelf", ""))
            self.store.set_setting("piles_dirty", "1")
        elif path == "/hub/retry":
            item = self.store.item_by_id(item_id)
            url = item["canonical_url"] if item else form.get("url", "")
            if url and self.store.retry(url):
                self.wake()
        elif path == "/hub/deep":
            if self.store.queue_deep(item_id):
                self.wake()
        elif path == "/hub/again":
            if self.store.summarise_again(item_id):
                self.store.allow_one_more_summary()
            self.wake()
        elif path == "/hub/update":
            return self._update()
        elif path in ("/hub/keep-link", "/hub/archive-link"):
            self.store.keep_as_link(item_id, archive=path == "/hub/archive-link")
        elif path == "/hub/try-login":
            if self.store.try_with_login(item_id):
                self.wake()
        elif path == "/hub/login/disconnect":
            login.disconnect(self.store)
        elif path == "/hub/accept-tags":
            self.store.accept_tags(item_id)
        elif path == "/hub/links/remove":
            if form.get("link_id", "").isdigit():
                self.store.remove_link(int(form["link_id"]))
        elif path == "/hub/links/add":
            self.store.add_link_by_owner(item_id, form.get("name", ""), form.get("url", ""), form.get("kind", "links"))
        elif path == "/hub/links/again":
            self.store.find_links_again(item_id)
            self.wake()
        elif path == "/hub/refresh-stats":
            self._refresh_stats(item_id)
        elif path == "/hub/control":
            part, action = form.get("part", ""), form.get("action", "")
            if part == "statsproxy":
                from magpiary import proxy
                if action == "test":
                    ok, words = proxy.test(proxy.get()) if proxy.get() else (False, "Save a proxy address first.")
                    return Response(303, b"", headers={"Location": "/settings/storage?" + urlencode({"error" if not ok else "note": words})})
                wrong = proxy.save("" if action == "remove" else form.get("address", ""))
                if wrong:
                    return Response(303, b"", headers={"Location": "/settings/storage?" + urlencode({"error": wrong})})
                return Response(303, b"", headers={"Location": "/settings/storage?" + urlencode({"note": "Proxy removed." if action == "remove" else "Proxy saved."})})
            if part == "statsauto" and action in ("pause", "resume"):
                self.store.set_setting("stats_auto", "1" if action == "resume" else "0")
            elif part in ("transcribe", "summary", "links", "stats") and action in ("pause", "resume"):
                self.store.set_paused(part, action == "pause")
                if part == "summary" and action == "resume" and self.store.summary_budget() not in ("all",) \
                        and not self.store.summary_budget().strip("0"):
                    self.store.set_setting("ai_budget", "all")  # "the next N" were used up: resume means all
                self.wake()
            return Response(303, b"", headers={"Location": back if back != "/" else "/nest"})
        elif path == "/hub/empty-trash":
            self._delete_folders(self.store.purge_trash(everything=True))
        else:
            return self.shell("Not found", "<p>Nothing here.</p>", "missing", 404)
        return Response(303, b"", headers={"Location": back})

    # ---- the menu-bar panel ---------------------------------------------------------------

    def panel_json(self) -> Response:
        """What the Mac app's panel shows. A background poll, so it never counts as someone using the hub; while locked it says only that."""
        self.lock.tick()
        headers = {"Cache-Control": "no-store"}
        if self.lock.is_locked():
            return Response(200, b'{"locked": true}', "application/json", headers=headers)
        saves, waiting, need = self.store.panel_counts()
        latest = [{"id": i["id"], "title": ui.title_of(i), "thumb": self.thumb_url(i)} for i in self.store.hub_items(limit=3)]
        return Response(200, json.dumps({"saves": saves, "waiting": waiting, "need": need, "latest": latest, "csrf": self._csrf}).encode(),
                        "application/json", headers=headers)

    def panel_save(self, url: str) -> Response:
        try:
            status = "again" if self.store.add_link(url).status == "again" else "saved"
        except UnsupportedLink:
            status = "bad"
        self.wake()
        return Response(200, json.dumps({"status": status}).encode(), "application/json", headers={"Cache-Control": "no-store"})

    # ---- actions ------------------------------------------------------------------------

    def _add(self, url: str, back: str = "") -> Response:
        fail = "/add?error=" if back.startswith("/add") else "/?error="
        if not url.strip():
            return Response(303, b"", headers={"Location": fail + "empty"})
        try:
            result = self.store.add_link(url)
        except UnsupportedLink:
            return Response(303, b"", headers={"Location": fail + "unsupported"})
        self.wake()
        item_id = self.store.id_for(result.id)
        if back.startswith("/welcome"):
            return Response(303, b"", headers={"Location": "/welcome/share"})
        return Response(303, b"", headers={"Location": f"/item/{item_id}" if item_id else "/"})

    def _bulk(self, form: dict) -> None:
        """One action on several saves (the selection bar and the right-click menu)."""
        from magpiary import related as rel

        ids = [int(x) for x in form.get("ids", "").split(",") if x.strip().isdigit()][:5000]
        items = [i for i in self.store.items_by_ids(ids) if i]
        action = form.get("action", "")
        if action in ("archive", "trash", "inbox"):
            for i in items:
                self.store.set_shelf(i["id"], action)
            self.store.set_setting("piles_dirty", "1")
        elif action == "again":
            for i in items:
                self.store.summarise_again(i["id"])
            if items:
                self.store.allow_one_more_summary()
            self.wake()
        elif action == "stats":  # refresh likes, comments and views: queued, then done slowly in the background
            self.store.stats_enqueue([i["canonical_url"] for i in items if i["status"] == "archived"])
            self.stats_wake()
        elif action == "board":
            from magpiary import boards, identity

            board_id = form.get("board", "")
            if self.store.board(board_id):
                mine = identity.public_key()
                already = {c["url"] for c in boards.view(self.store, board_id)["cards"] if mine in c["adders"]}
                for i in items:
                    if i["status"] == "archived" and i["canonical_url"] not in already:
                        boards.add_card(self.store, board_id, i, self.library)
                        self.store.activity_add("board")
                self.sync_boards()
        elif action in ("tag", "untag"):
            tag = " ".join(form.get("tag", "").lower().lstrip("#").split())[:40]
            for i in items:
                tags = [t for t in i["tags"] if t != tag] + ([tag] if action == "tag" and tag else [])
                self.store.set_tags(i["id"], ", ".join(tags))
        elif action == "pile":
            target = form.get("pile", "")
            pile_id = self.store.new_pile(form.get("name", "")) if target == "new" else int(target) if target.isdigit() else 0
            for i in items:
                self.store.move_to_pile(i["canonical_url"], pile_id)
            if items:
                rel.rebuild_piles(self.store)

    def _search_json(self, query: str, all_piles: bool = False) -> Response:
        """What the search panel suggests: piles, tags and named things matching what was typed, plus the
        sources and types to filter by."""
        words = query.lower().strip().lstrip("#")
        counts = self.store.hub_counts()
        piles = [{"id": p["id"], "name": p["name"], "n": len(p["members"])} for p in self.store.piles() if p["members"]
                 and words and words in p["name"].lower()][:4]
        tags = [{"tag": t, "n": n} for t, n in sorted(counts["tags"].items(), key=lambda kv: -kv[1])
                if words and t.startswith(words)][:6]
        names, seen = [], set()
        if len(words) >= 2:
            for i in self.store.hub_items("kept", query, limit=40):
                for values in ui.media_of(i)["entities"].values():
                    for name in values:
                        if words in name.lower() and name.lower() not in seen and not name.startswith("http"):
                            seen.add(name.lower())
                            names.append(name)
        names = names[:6]
        types: dict = {}
        for i in self.store.hub_items("inbox"):
            if i.get("ai_status") == "done":
                types[i.get("ai_type") or "other"] = types.get(i.get("ai_type") or "other", 0) + 1
        views = [{"id": v["id"], "name": v["name"], "q": v["rule"].get("q", ""), "no": "|".join(v["rule"].get("no", [])),
                  "n": len(self.find(v["rule"].get("q", ""), set(v["rule"].get("no", [])), True)[0])} for v in self.store.views()] \
            if not words else []
        data = {"piles": piles, "tags": tags, "names": names, "views": views,
                "sources": [{"source": k, "name": ui.source_name(k), "n": n} for k, n in
                            sorted(counts["sources"].items(), key=lambda kv: -kv[1])],
                "types": [{"type": k, "name": ui.type_name(k), "n": n} for k, n in sorted(types.items(), key=lambda kv: -kv[1])]}
        if all_piles:
            data["all_piles"] = [{"id": p["id"], "name": p["name"], "n": len(p["members"]), "colour": ui.pile_colour(p)}
                                 for p in self.store.piles() if p["members"]]
        return Response(200, json.dumps(data).encode(), "application/json", headers={"Cache-Control": "no-store"})

    def purge_old_trash(self) -> int:
        folders = self.store.purge_trash()
        self._delete_folders(folders)
        from magpiary import boards

        for board_id in self.store.purge_archived_boards():
            boards.forget_key(board_id)
        return len(folders)

    def _delete_folders(self, folders: list[str]) -> None:
        for folder in folders:
            path = Path(folder)
            if self.library and path.resolve().is_relative_to(self.library.resolve()) and path.resolve() != self.library.resolve():
                shutil.rmtree(path, ignore_errors=True)
                (self.library.parent / "notes" / f"{path.name}.md").unlink(missing_ok=True)

    def stats_wake(self) -> None:
        """Nudge the slow refresh lane (it also checks by itself every half minute)."""
        event = getattr(self, "stats_wanted", None)
        if event is not None:
            event.set()

    def _stats_estimate(self, q: dict) -> Response:
        """What a bulk job would take and cost, for the confirmation box. `job` is refresh (stats) or again (summaries)."""
        import json as _json

        from magpiary import keys as keyring, modes, stats

        ids = [int(x) for x in q.get("ids", "").split(",") if x.strip().isdigit()][:5000]
        items = [i for i in self.store.items_by_ids(ids) if i and i["status"] == "archived"]
        job, n = q.get("job", "refresh"), len(items)
        body: dict = {"posts": n, "confirm": n > 5, "job": job}
        if job == "again":
            seconds = int(n * self.store.avg_step_seconds("summary", 40))
            private = modes.current(self.store) == "private"
            if private:
                writer = "Private mode is on, so nothing is written."
            else:  # summaries are always written by the AI keys, in their order
                usable = keyring.usable()
                writer = (f"Your AI key {usable[0].name} writes them, and each one uses a request from its daily limit." if usable
                          else "No AI key is ready, so they would wait.")
            body.update(time=stats.human(seconds), cost=writer,
                        note=f"{n} summaries, one at a time, about {round(seconds / max(n, 1))} seconds each.")
        else:
            per = {}
            for i in items:
                per[i["source"]] = per.get(i["source"], 0) + 1
            est = stats.estimate(per)
            body.update(time=stats.human(est["seconds"]), per_source=per,
                        cost="No AI is used and nothing is downloaded: one small request per post, to the site it came from.",
                        note="They are spread out on purpose (a pause of about a minute or two between posts, a daily limit per site) so the sites "
                             "do not mistake this Mac for a robot. It keeps running in the background; watch it in the Nest.")
        return Response(200, _json.dumps(body).encode(), "application/json", headers={"Cache-Control": "no-store"})

    def _stats_status(self) -> Response:
        import json as _json

        queued = self.store.stats_queue_counts()
        body = {"queued": sum(queued.values()), "per_source": queued, "paused": self.store.paused("stats"),
                "next_in": None}
        return Response(200, _json.dumps(body).encode(), "application/json", headers={"Cache-Control": "no-store"})

    def _refresh_stats(self, item_id: int) -> None:
        """Read likes, comments and views again (counts only) and save them with today's date."""
        from magpiary.sources import FetchFailed, describe

        item = self.store.item_by_id(item_id)
        if not item or not item.get("archive_dir") or item.get("login_only"):
            return
        meta_path = Path(item["archive_dir"]) / "meta.json"
        try:
            meta = json.loads(meta_path.read_text())
            fresh = describe(item["source"], item["canonical_url"]).meta
        except (OSError, ValueError, FetchFailed):
            return
        for key in ("like_count", "comment_count", "view_count", "repost_count", "share_count"):
            if fresh.get(key) is not None:
                meta[key] = fresh[key]
        meta["stats_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    def _update(self) -> Response:
        from magpiary import update

        version = self.store.get_setting(update.LATEST_SETTING, "")
        problem = update.install(version) if update.newer(version) else "There is no newer version."
        if problem:
            return self.shell("Update", f'<div class="hero"><h1 class="mid">Update</h1></div>'
                              f'<div class="flash err">{e(problem)}</div><a class="link" href="/">Back to the library</a>',
                              "missing", 500)
        self.restart()
        page = self.shell("Updated", f'<div class="hero"><h1 class="mid">Updated to Magpiary {e(version)}</h1>'
                          '<p>Magpiary is restarting. This page reloads in about 20 seconds.</p></div>', "missing")
        page.body = page.body.replace(b"</head>", b'<meta http-equiv="refresh" content="20;url=/"></head>', 1)
        return page

    # ---- board sync ---------------------------------------------------------------------

    def _sync_here(self) -> None:
        from magpiary import boards

        boards.sync_all(self.store, self.relay_connect, self.sync_call)

    # ---- the frame every page shares -----------------------------------------------------

    @property
    def csrf(self) -> str:
        return self._csrf

    def _form(self, action: str, fields: dict, button: str, cls: str = "btn sm", confirm: str = "") -> str:
        return ui.button_form(self._csrf, action, fields, e(button), cls, confirm)

    def has_summaries(self) -> bool:
        """Whether a summary can be written right now (Smart with a usable key)."""
        return bool(modes.summarisers(self.store, keyring))

    def not_found_page(self) -> Response:
        """What a browser sees for an address the hub does not have (programs asking for the API still get JSON)."""
        from magpiary.hub_wall import empty_state

        return self.shell("Not found", empty_state("Nothing here", "That address is not a page in Magpiary.",
                                                   '<a class="btn dark" href="/">Back to the library</a>'), "missing", 404)

    def shell(self, title: str, main: str, page: str, status: int = 200, data: dict | None = None,
              q: str = "", shelf: str = "", active: str = "", bare: bool = False) -> Response:
        """A full page: update banner, top bar with the strip, the page itself, and the overlays hub.js uses."""
        look = ui.appearance(self.store)
        if bare:
            body = main
        else:
            body = (self._update_banner() + self.top_bar(q, shelf, active)
                    + f'<main class="wrap" id="view">{main}</main>'
                    '<div class="scrim" id="scrim" hidden></div>'
                    '<section class="cardm it" id="cardm" role="dialog" aria-modal="true" aria-label="Post" hidden></section>'
                    + self.add_modal() + self.search_overlay() + self.nest_shell() + self.help_shell() + self.checklist_panel(page) + self.ask_dock(page))
        script = json.dumps(data or {}).replace("</", "<\\/")
        return ui.document(title, body, look, self._csrf, page, status, script=script)

    def _update_banner(self) -> str:
        from magpiary import __version__
        from magpiary.tools import in_mac_app
        from magpiary.update import LATEST_SETTING, RELEASES_PAGE, from_homebrew, newer

        waiting = self.store.get_setting(LATEST_SETTING, "")
        if not newer(waiting):
            return ""
        action = (f'<span>Quit Magpiary, then drag the new version to Applications.</span><a class="btn sm" href="{RELEASES_PAGE}" '
                  'target="_blank" rel="noopener noreferrer">Download</a>' if in_mac_app()
                  else "<span>Run <b>brew upgrade magpiary</b> in Terminal.</span>" if from_homebrew()
                  else self._form("/hub/update", {"next": "/"}, "Update now", "btn sm"))
        return (f'<div class="update" role="status"><span>Magpiary {e(waiting)} is available '
                f'(you have {e(__version__)}).</span>{action}</div>')

    def _activity_json(self, q: dict | None = None) -> Response:
        if (q or {}).get("boards") and time.monotonic() - self._boards_watched >= BOARD_WATCH_EVERY:
            self._boards_watched = time.monotonic()
            self.sync_boards()  # a board is on screen: look for friends' changes often, not every 15 minutes
        snap = self.activity.snapshot()
        snap["signature"] = self.store.progress_signature()
        if (q or {}).get("item", "").isdigit():
            snap["item_signature"] = self.store.item_signature(int((q or {})["item"]))
            snap["item_looking"] = bool((self.store.item_by_id(int((q or {})["item"])) or {}).get("links_force"))
        snap["needs"] = len(self.store.problems())
        snap["ask"] = self.ask_enabled()  # a page that sees this change closes its Ask panel and reloads
        snap["mood"], snap["line"] = self.nest_status(snap)
        first = next(iter(modes.summarisers(self.store, keyring)), None)
        snap["key_name"] = first.name if first is not None and hasattr(first, "name") else ""
        for lane in snap["lanes"]:
            item = self.store.item_by_id(lane["item_id"])
            lane["thumb"] = self.thumb_url(item) if item else ""
        return Response(200, json.dumps(snap).encode(), "application/json", headers={"Cache-Control": "no-store"})
