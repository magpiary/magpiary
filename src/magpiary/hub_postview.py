"""Contextual post tabs in the hub (owner decisions 14 Nov 2026), mixed into Hub.

Three POST routes (all behind `_post`'s same-origin, CSRF and lock checks):
- `/hub/pv/state`    id, tab, key, value  → one tick or servings value for the post; JSON {"ok": true}.
- `/hub/pv/build`    id                   → queue "Build this view" (the worker in views_ai.py does it).
- `/hub/pv/category` id, category         → the owner's category; re-queues the view (Smart) or, in Private, the
                                            free tabs follow at once (views.current builds them on every open).
With a `next` field the reply is a redirect there (plain forms, no JavaScript); without one it is JSON.

Also the parts of the post view the card needs: a category tab's pane (drawn by `hub_views.render_tab` when that
module exists, else the plain list below) and the "Build this view" strip inside the Summary.
"""

import json
import re

from magpiary import categories as cats
from magpiary import modes, ui, views
from magpiary.web import Response, e

KEY = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
MAX_VALUE = 200


def _safe(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


def plain_tab(tab: cats.Tab, body: dict) -> str:
    """The fallback for a category tab: its text and its items as a list, everything escaped (untrusted post/AI text)."""
    rows = []
    group = None
    for it in body.get("items") or []:
        if it.get("group") and it["group"] != group:
            group = it["group"]
            rows.append(f'<li class="pvgroup"><strong>{e(group)}</strong></li>')
        extra = " · ".join(e(it[k]) for k in ("amount", "detail") if it.get(k))
        at = f' <small class="pvat">{e(it["at"])}</small>' if it.get("at") else ""
        value = f'<pre class="pvvalue">{e(it["value"])}</pre>' if it.get("value") else ""
        rows.append(f'<li><span class="pvname">{e(it["name"])}</span>{" · " + extra if extra else ""}{at}{value}</li>')
    text = f'<p class="it-sum sm">{e(body["text"])}</p>' if body.get("text") else ""
    return (text + (f'<ul class="pvlist" data-render="{e(tab.render)}">{"".join(rows)}</ul>' if rows else "")
            or f'<p class="muted">{e(tab.empty_text)}</p>')


class PostViewPages:
    """Needs Hub's store and wake."""

    # ---- routes ----------------------------------------------------------------------------------------------

    def postview_post(self, path: str, form: dict) -> Response | None:
        """Handles /hub/pv/*; None for any other path."""
        if not path.startswith("/hub/pv/"):
            return None
        item = self.store.item_by_id(int(form["id"])) if form.get("id", "").isdigit() else None
        if not item:
            return self._pv_reply(form, False, "unknown post", 404)
        if path == "/hub/pv/state":
            tab, key, value = form.get("tab", ""), form.get("key", ""), form.get("value", "")
            if tab not in cats.TABS or not KEY.fullmatch(key) or len(value) > MAX_VALUE:
                return self._pv_reply(form, False, "bad input", 400)
            self.store.set_view_state(item["canonical_url"], tab, key, value)
            return self._pv_reply(form, True)
        if path == "/hub/pv/build":
            if item.get("status") != "archived" or item.get("shelf") == "trash":
                return self._pv_reply(form, False, "not saved yet", 409)
            if modes.effective(self.store) == "private":  # checked now, not when the job runs (the worker checks again)
                return self._pv_reply(form, False, "private", 409)
            queued = self.store.queue_view(item["id"])
            if queued:
                self.wake()
            return self._pv_reply(form, True, "queued" if queued else "already queued")
        if path == "/hub/pv/category":
            category = form.get("category", "")
            if category not in cats.CATEGORIES:
                return self._pv_reply(form, False, "unknown category", 400)
            self.store.set_category(item["id"], category, "", "owner")
            queued = False
            if (modes.effective(self.store) != "private" and category != "other" and item.get("status") == "archived"
                    and item.get("shelf") != "trash"):
                queued = self.store.queue_view(item["id"])
                if queued:
                    self.wake()
            return self._pv_reply(form, True, "queued" if queued else "")
        return self._pv_reply(form, False, "unknown action", 404)

    def _pv_reply(self, form: dict, ok: bool, detail: str = "", status: int = 200) -> Response:
        if form.get("next"):
            return Response(303, b"", headers={"Location": _safe(form["next"])})
        body = {"ok": ok} | ({"detail": detail} if detail else {})
        return Response(status if not ok else 200, json.dumps(body).encode(), "application/json",
                        headers={"Cache-Control": "no-store"})

    # ---- parts of the post view ---------------------------------------------------------------------------------

    def category_pane(self, tab_id: str, view: dict, state: dict, item: dict) -> str:
        """One category tab's pane. `state` is the post's whole view_state ({tab: {key: value}})."""
        tab, body = cats.TABS[tab_id], (view.get("tabs") or {}).get(tab_id) or {"text": "", "items": []}
        try:
            from magpiary import hub_views
        except ImportError:
            hub_views = None
        if hub_views is not None and hasattr(hub_views, "render_tab"):
            return hub_views.render_tab(tab, body, view, state.get(tab_id, {}), item)
        return plain_tab(tab, body)

    def build_strip(self, item: dict, view: dict) -> str:
        """Inside the Summary: offer to build this post's view (old posts; owner decision 2). Empty when there is
        nothing to build, in Private mode, or before the post is saved."""
        if (not views.needs_build(view) or item.get("status") != "archived" or item.get("shelf") == "trash"
                or modes.effective(self.store) == "private"):
            return ""
        name = cats.name(view.get("category", ""))
        status = item.get("view_status") or ""
        if status in ("queued", "working"):
            return (f'<div class="pvbuild" data-pvbuild="{e(status)}" role="status"><span>Building the '
                    f'{e(name)} tabs for this post…</span></div>')
        failed = '<small class="muted">The last try failed. </small>' if status == "failed" else ""
        return (f'<form class="pvbuild" method="post" action="/hub/pv/build" data-pvbuild="">'
                f'{ui.hidden(self.csrf, id=item["id"], next=f"/item/{item['id']}")}'
                f'<span>This looks like <strong>{e(name)}</strong>. {failed}Build its tabs with your AI (one call).</span>'
                f'<button class="btn sm" type="submit">Build this view</button></form>')
