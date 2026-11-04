"""The getting-started checklist: a small floating panel for a new library. Four steps that open the real parts of a saved post;
each ticks by itself when it is done. It goes away when finished or dismissed, and Help can bring it back."""
from __future__ import annotations

import json

from magpiary import keys as keyring
from magpiary import modes, ui
from magpiary.web import Response, e

SETTING = "checklist"
STEPS = [("watch", "Watch a moment", "Click a key moment or a line of the transcript."),
         ("link", "Open the main link", "Go to the tool or place the post is about."),
         ("note", "Add a note", "Write why you saved it."),
         ("search", "Search for it", "Type a word you remember from the post.")]


class ChecklistPages:
    def _checklist_state(self) -> dict:
        try:
            s = json.loads(self.store.get_setting(SETTING, "") or "{}")
        except ValueError:
            s = {}
        return {"done": [x for x in s.get("done", []) if x in dict((k, 1) for k, *_ in STEPS)], "off": bool(s.get("off"))}

    def _checklist_save(self, s: dict) -> None:
        self.store.set_setting(SETTING, json.dumps(s))

    def checklist_post(self, form: dict) -> Response:
        s = self._checklist_state()
        action = form.get("action", "")
        if action == "tick" and form.get("step") in dict((k, 1) for k, *_ in STEPS) and form["step"] not in s["done"]:
            s["done"].append(form["step"])
        elif action == "off":
            s["off"] = True
        elif action == "replay":
            s = {"done": [], "off": False}
        self._checklist_save(s)
        if form.get("next"):
            return Response(303, b"", headers={"Location": ui_safe(form["next"])})
        return Response(200, b"ok", "text/plain")

    def checklist_fragment(self) -> Response:
        html_ = self._checklist_inner()
        return Response(200, html_.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

    def _checklist_first(self) -> dict | None:
        rows = self.store.hub_items("inbox", limit=1)
        return rows[0] if rows else None

    def _checklist_inner(self) -> str:
        s = self._checklist_state()
        first = self._checklist_first()
        if s["off"] or not first:
            return ""
        done = s["done"]
        all_done = len(done) == len(STEPS)
        rows = []
        check = '<svg class="gckm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 12.5l4.5 4.5 8.5-9.5" pathLength="1"/></svg>'
        for key, title, hint in STEPS:
            ok = key in done
            text = f'<span class="gst"><b>{e(title)}</b><small>{e(hint)}</small></span>'
            if ok:
                rows.append(f'<li data-gs="{key}" class="done"><div class="gsrow"><span class="gck" aria-hidden="true">{check}</span>{text}</div></li>')
            else:
                rows.append(f'<li data-gs="{key}"><button type="button" class="gsrow" data-gstep="{key}" data-post="{first["id"]}"><span class="gck" aria-hidden="true"></span>'
                            f'{text}<span class="gsarr" aria-hidden="true">{ui.icon("chev")}</span></button></li>')
        key_help = ""
        if not all_done and modes.current(self.store) == "smart" and not first.get("summary") \
                and not any(keyring.PROVIDERS[k.provider]["kind"] == "ai" for k in keyring.load()):
            key_help = ('<p class="gskey">This post has no summary yet. <a href="/welcome/reading">Add a free Gemini key</a> '
                        'and Magpiary writes one.</p>')
        head = ("You're all set" if all_done else "Getting started")
        count = "" if all_done else f'<small>{len(done)} of {len(STEPS)}</small>'
        return (f'<header><b>{head}</b>{count}<button type="button" class="rb" data-gcollapse aria-label="Collapse" title="Collapse">{ui.icon("chevup")}</button>'
                f'<button type="button" class="rb" data-goff aria-label="Dismiss" title="Dismiss">{ui.icon("close")}</button></header>'
                f'<ol>{"".join(rows)}</ol>{key_help}')

    def checklist_panel(self, page: str) -> str:
        if page in ("ask", "welcome") or self.needs_welcome():
            return ""
        inner = self._checklist_inner()
        if not inner:
            return ""
        done = len(self._checklist_state()["done"]) == len(STEPS)
        return f'<aside class="gstart{" fin" if done else ""}" id="gstart" aria-label="Getting started">{inner}</aside>'

    def checklist_replay(self) -> str:
        """A note inside Help's Getting started chapter."""
        return ('<div class="hcall"><p><b>The first-steps checklist</b>Four quick steps that open the real parts of a post. '
                'They tick themselves as you go.</p>'
                + self._form("/hub/checklist", {"action": "replay", "next": "/"}, "Show the checklist again", "btn sm") + "</div>")


def ui_safe(nxt: str) -> str:
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
