"""Ask about these saves (M-Ask): a side panel opened from a post, a pile or a board. See ask.py for what the AI reads and may
say. The chat is kept per place it was asked from; a good answer can be saved as a note on the post or the pile."""

import html
import json
import re
from pathlib import Path

import threading
import time
import uuid
from datetime import datetime, timedelta

from magpiary import ask as asking
from magpiary import ask_open, askconfig
from magpiary import keys as keyring
from magpiary import modes, ui
from magpiary.brain import BrainFailed
from magpiary.web import Response

e = html.escape

ENGINE = askconfig.ENGINE  # "claude" (Claude Code on the owner's plan, used for testing) or "key" (the owner's API key)


def _record(item: dict) -> dict:
    folder = Path(item["archive_dir"]) if item.get("archive_dir") else None
    try:
        return json.loads((folder / "record.json").read_text()) if folder else {}
    except (OSError, ValueError):
        return {}


def suggestions(kind: str, items: list[dict], label: str) -> list[str]:
    """Three starting questions that fit what you are looking at (no AI call: made from the post's own details)."""
    if kind == "library":
        return ["What should I try first from my saves?", "Which tools in my saves compare best?", "What is new on a topic I save a lot?"]
    if kind != "post" or not items:
        name = label if len(label) <= 40 else label[:38] + "…"
        return [f"What do the saves in {name} have in common?", "Compare them: which should I try first, and why?",
                "Which of these is most worth my time, and what would I do with it?"]
    record = _record(items[0])
    extras = record.get("extras") or {}
    tool = extras.get("tool_name") or next(iter((record.get("entities") or {}).get("tools") or []), "")
    tools = list(dict.fromkeys(([tool] if tool else []) + [t for t in (record.get("entities") or {}).get("tools") or [] if isinstance(t, str)]))
    kind_ = record.get("type") or ""
    place = extras.get("place_name") or ""
    # The first question is always the "the summary isn't enough" one: go and research this properly (owner, 29 Oct). The other
    # two are what someone landing on the post would want next. No AI call: made from the post's own details.
    if kind_ == "recipe":
        return ["The summary isn't enough: give me the exact ingredients, amounts and steps.", "What can I swap if I am missing something, and what changes?",
                "Find a well-reviewed version of this recipe and tell me how they differ."]
    if kind_ == "place" or place:
        name = place or "this place"
        return [f"Research {name} properly: reviews, prices and the best time to go.", "What is worth ordering or seeing there?",
                "Is it actually good, or just popular online?"]
    if len(tools) > 1:
        names = ", ".join(tools[:3])
        return [f"Research these in more depth: {names}. What is each for, and what does it cost?", f"Compare {names}: which is best for what?",
                "Which should I try first, and what would I do with it?"]
    if tool:
        return [f"Research {tool} more deeply: who makes it, what does it cost, and what do people say?",
                f"Is {tool} any good, and what are the real alternatives?", f"Walk me through getting started with {tool}."]
    return ["The summary isn't enough: research this more deeply and tell me what it leaves out.",
            "Find the original source and check whether the claims hold up.", "What should I do with this? Give me a short plan."]


MIC = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
       'aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/></svg>')
STOP = '<svg class="ico stopic" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/></svg>'
SEND = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>')


ENGINE_LOGO = {
    # Claude's spark in its orange; the OpenAI rosette in the text colour. Small marks that say who is answering.
    "claude": '<svg class="enginelogo" viewBox="0 0 24 24" aria-hidden="true"><g stroke="#d97757" stroke-width="2.4" stroke-linecap="round">'
              '<path d="M12 2.5v6M12 15.5v6M2.5 12h6M15.5 12h6M5.3 5.3l4.2 4.2M14.5 14.5l4.2 4.2M18.7 5.3l-4.2 4.2M9.5 14.5l-4.2 4.2"/></g></svg>',
    "codex": '<svg class="enginelogo" viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5">'
             + "".join(f'<ellipse cx="12" cy="6.8" rx="2.9" ry="4.8" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 60)) + "</g></svg>",
}
ENGINE_LOGO["gemini"] = ('<svg class="enginelogo" viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="gmg" x1="0" y1="1" x2="1" y2="0">'
                         '<stop offset="0" stop-color="#4285f4"/><stop offset=".55" stop-color="#9b72cb"/><stop offset="1" stop-color="#d96570"/></linearGradient></defs>'
                         '<path d="M12 1.5c.7 5.8 4.7 9.8 10.5 10.5-5.8.7-9.8 4.7-10.5 10.5C11.3 16.7 7.3 12.7 1.5 12 7.3 11.3 11.3 7.3 12 1.5z" fill="url(#gmg)"/></svg>')
ENGINE_LOGO["openrouter"] = ('<svg class="enginelogo" viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="#6467f2" stroke-width="2" stroke-linecap="round" '
                             'stroke-linejoin="round"><path d="M3 8h15M14 4l4 4-4 4M21 16H6M10 12l-4 4 4 4"/></g></svg>')
ENGINE_LOGO["openai"] = ENGINE_LOGO["codex"]  # a key's provider: OpenAI gets the rosette, Claude's API the spark

NOT_SPEECH = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|[♪♫]+")


def spoken_words(text: str) -> str:
    """What was said, without Whisper's notes about sounds: [BLANK_AUDIO], (silence), *music*, ♪."""
    return re.sub(r"\s+", " ", NOT_SPEECH.sub(" ", text)).strip()


class AskPages:
    # ---- who is asked about what ---------------------------------------------------------------------------

    def ask_stop_all(self) -> None:
        """Ask was switched off: every answer still being written is stopped."""
        for job in self.__dict__.get("_ask_jobs", {}).values():
            job["stop"] = True

    def ask_enabled(self) -> bool:
        """The switch in Settings: when it is off, no Ask button or tab shows anywhere."""
        return askconfig.enabled(self.store)

    def ask_engine(self) -> dict | None:
        """Who answers, as chosen in Settings (Ask Magpiary): Claude Code on the owner's plan, or one of the owner's AI keys.
        None when Ask is off or the chosen one cannot answer."""
        if not self.ask_enabled() or modes.current(self.store) != "smart":
            return None
        from magpiary import ask_codex
        from magpiary import engines

        usable = [k for k in keyring.usable() if not engines.is_free(k) or not engines.strong(self.store)
                  or self.store.get_setting(ENGINE, "") == "key"]
        claude = asking.claude_available() and engines.is_allowed(self.store, "claude_code") and not askconfig.removed(self.store, "claude")
        codex = ask_codex.available() and engines.is_allowed(self.store, "codex") and not askconfig.removed(self.store, "codex")
        first = (engines.choice(self.store, "ask") or {}).get("id", "")
        default = {"claude_code": "claude", "codex": "codex"}.get(first, "key")
        chosen = self.store.get_setting(ENGINE, "") or default
        if chosen == "none":
            return None
        if (chosen == "claude" and not claude) or (chosen == "codex" and not codex):
            chosen = default  # the owner's pick was stopped in AI keys: the next in the shared order answers instead
        if chosen == "key" and not self.store.get_setting(askconfig.KEY, "") and first.startswith("key:"):
            self.store.set_setting(askconfig.KEY, first[4:])
        if chosen == "codex" and codex:
            model = askconfig.codex_model(self.store)
            return {"id": "codex", "name": "Codex (your ChatGPT plan)", "short": "Codex", "key": None, "write": None, "other": "",
                    "model": askconfig.CODEX_NAME.get(model, model), "alias": model}
        if chosen == "claude" and claude:
            model = askconfig.claude_model(self.store)
            return {"id": "claude", "name": "Claude Code (your Claude plan)", "short": "Claude Code", "key": None, "write": asking.write_with_claude,
                    "other": "your API key" if usable else "", "model": askconfig.MODEL_NAME.get(model, model), "alias": model}
        if chosen == "key" and usable:
            wanted = self.store.get_setting(askconfig.KEY, "")
            key = next((k for k in usable if k.id == wanted), None)
            if key is None:
                return None
            name = keyring.PROVIDERS[key.provider]["name"].split(" (")[0]
            return {"id": "key", "name": name, "short": name, "key": key, "write": None, "other": "Claude Code" if claude else "",
                    "model": getattr(key, "model", "") or name, "alias": ""}
        return None

    def ask_scope(self, scope: str):
        """(label, items) for "post:12", "pile:3", "board:<id>"; None when there is no such place."""
        kind, _, ident = scope.partition(":")
        if scope in ("library:all", "library:everything"):
            return "your whole library", []
        if scope == "library:piles":
            return "your piles", []
        if scope == "library:boards":
            return "your boards", []
        if kind == "post" and ident.isdigit():
            item = self.store.item_by_id(int(ident))
            return (ui.title_of(item), [item]) if item else None
        if kind == "pile" and ident.isdigit():
            pile = self.store.pile(int(ident))
            if not pile:
                return None
            items = [i for i in self.store.items_by_urls(pile["members"]) if i and i["shelf"] != "trash"]
            return pile["name"], items
        if kind == "board" and re.fullmatch(r"[0-9a-f]{16}", ident):
            from magpiary import boards

            board = self.store.board(ident)
            if not board:
                return None
            items = []
            for item in self.store.items_by_urls([c["url"] for c in boards.view(self.store, ident)["cards"]]):
                if item["shelf"] != "trash":
                    items.append(item)
            return board["name"], items
        return None

    def ask_place(self, scope: str, label: str, items: list[dict]) -> dict:
        """Where the question is asked from, in words the chat can use: {"line" (under the heading), "context" (a few lines for the
        AI, kept short), "starters" (three questions that fit this place and what is in it)}."""
        n = len(items)
        if scope == "library:piles":
            piles = sorted((p for p in self.store.piles() if p.get("members")), key=lambda p: -len(p["members"]))
            names = [f'{p["name"]} ({len(p["members"])})' for p in piles[:30]]
            top = [p["name"] for p in piles[:2]]
            starters = ([f"What is in {top[0][:30]} and why did I save it?"] if top else []) + [
                "Which of my piles overlap or could be merged?", "Which pile should I go through first?"]
            if len(top) > 1:
                starters.insert(1, f"How do {top[0][:24]} and {top[1][:24]} relate?")
            return {"line": f"Asking about your piles · {len(piles)} pile{'' if len(piles) == 1 else 's'}",
                    "context": "The person is looking at their piles (groups of saves). PILES (saves): " + ", ".join(names) if names else
                    "The person is looking at their piles; there are none yet.", "starters": starters[:3]}
        if scope == "library:boards":
            boards = self.store.boards()
            names = [b["name"] for b in boards[:30]]
            starters = ([f"What is on {names[0][:30]}?"] if names else []) + ["Which board has the most to read?", "What was added to my boards lately?"]
            return {"line": f"Asking about your boards · {len(boards)} board{'' if len(boards) == 1 else 's'}",
                    "context": "The person is looking at their boards (shared collections). BOARDS: " + ", ".join(names) if names else
                    "The person is looking at their boards; there are none yet.", "starters": starters[:3]}
        if scope in ("library:everything", "library:all"):
            recent = self.store.hub_items("inbox", limit=10)
            titles = [f'id {i["id"]}: {ui.title_of(i)[:60]}' for i in recent]
            return {"line": "Asking about everything you saved",
                    "context": "The person is looking at everything they saved, newest first. NEWEST SAVES: " + "; ".join(titles) if titles else "",
                    "starters": ["What have I saved this week?", "Which of my newest saves should I act on first?",
                                 "Which tools in my saves are worth trying?"]}
        kind = scope.partition(":")[0]
        starters = suggestions(kind, items, label)
        if kind == "post":
            ctx = (f'The person has this saved post open: "{label[:120]}" (the posts shown above are this post). Treat it as the subject of the '
                   "conversation: a question that does not name something else is about this post (the tool, place, person or claim in it). "
                   "You may go beyond it, with a web search or their other saves, when the question needs it; say plainly when you do.")
            return {"line": f"This post · {label[:56]}", "context": ctx, "starters": starters}
        return {"line": f"The {kind} “{label[:40]}” · {n} save{'' if n == 1 else 's'}", "context": "", "starters": starters}

    def ask_dock(self, page: str) -> str:
        """The corner at the bottom right: Help on every page but Ask's own, and the Ask bar, which opens Ask about this page
        (on a post: that post's one conversation). Help moved here from the top bar (owner, 29 Oct)."""
        if page == "help":  # the Help page is Help
            return ""
        ask = self.ask_enabled() and page != "ask"  # the full Ask page keeps only Help: Ask is the page
        # Ask off in Smart mode: the button stays and opens Ask's settings, which say why and offer the two ways to turn it on
        off = not ask and page not in ("ask", "settings") and modes.current(self.store) == "smart"
        return ('<div class="askdockwrap' + ("" if ask or off else " helponly") + '"><div class="askdockrow">'
                f'<a class="askhelp" href="/help" id="t-help" title="Help for this page">{ui.icon("book")}<span class="lbl">Help</span></a>'
                + ('<button type="button" class="askdock" data-askdock aria-label="Open Ask Magpiary" title="Ask Magpiary">'
                   '<span class="askmark" aria-hidden="true">✦</span><span class="askdocklab">Ask Magpiary</span><small class="askdockstate" data-askdockstate></small>'
                   f'{ui.icon("chevup")}</button>' if ask else "")
                + ('<a class="askdock askoff" href="/settings/ask#onoff" title="Ask Magpiary is off: see why and turn it on">'
                   '<span class="askmark" aria-hidden="true">✦</span><span class="askdocklab">Ask Magpiary</span>'
                   '<small class="askdockstate">Off</small></a>' if off else "") + '</div></div>')

    def ask_button(self, scope: str, label: str = "Ask Magpiary", cls: str = "btn sm askbtn2") -> str:
        """No button any more: a quiet marker telling the Ask bar which place this page is (a pile, a board, a tab)."""
        if not self.ask_enabled():
            return ""
        return f'<span data-askscope="{e(scope)}" hidden></span>'

    # ---- the panel -------------------------------------------------------------------------------------------

    def ask_body(self, scope: str, label: str, items: list[dict]) -> str:
        """The chat itself: what has been said, starting questions, the box, the first-question notice and the footer. Shared by
        the side panel (piles, boards) and the Ask tab on a post."""
        kind = scope.partition(":")[0]
        engine = self.ask_engine()
        n = len(items)
        thread = self.store.ask_thread(scope)
        if engine is None:
            return ('<div class="asknokey"><b>Ask Magpiary needs an AI.</b><p>Add an AI key in Settings and choose Smart mode, or install Claude Code. '
                    'Private mode never sends anything to an AI, so there is nothing to ask.</p><a class="btn sm" href="/settings/ai">Open AI settings</a></div>')
        opened = engine["id"] == "claude"
        if kind == "library":
            hint = "Ask anything: your saves and the web…"
        elif opened:
            hint = "Ask anything about this post…" if kind == "post" else f"Ask anything about {label}…"
        else:
            hint = "Ask Magpiary about this post…" if kind == "post" else f"Ask Magpiary about the {n} save{'' if n == 1 else 's'} in {label}…"
        place = self.ask_place(scope, label, items)
        starters = "".join(f'<button type="button" class="askstart" data-askq="{e(q)}"><span>{e(q)}</span></button>' for q in place["starters"])
        messages = "".join(self._ask_message(m, items, scope) for m in thread)
        examples = ["Compare two tools I saved", "What did I save about Lisbon?", "Which of my saved tools should I try first?",
                    "How is this different from the alternatives?", "Find me the best article on this"]
        hello = (f'<div class="askhello"><div class="askart" aria-hidden="true">'
                 f'<img class="ask-bird" src="{ui.art("land-c")}" alt=""></div><div class="askorb" aria-hidden="true"><i class="o1"></i><i class="o2"></i>'
                 '<svg class="askstar" viewBox="0 0 24 24"><defs><linearGradient id="askgrad" x1="0" y1="0" x2="1" y2="1">'
                 '<stop offset="0" stop-color="#ff2e93"/><stop offset="1" stop-color="#8a3ffc"/></linearGradient></defs>'
                 '<path d="M12 1.5c.6 5.6 4.9 9.9 10.5 10.5-5.6.6-9.9 4.9-10.5 10.5C11.4 16.9 7.1 12.6 1.5 12 7.1 11.4 11.4 7.1 12 1.5z" fill="url(#askgrad)"/></svg></div>'
                 '<b>What do you want to know?</b>'
                 f'<span class="askctx">{e(place["line"])}</span>'
                 f'<span class="asktype" data-asktype data-examples="{e(json.dumps(examples))}"></span></div>') if not thread else ""
        starters = f'<div class="askstarters" data-asksuggest>{starters}</div>' if not thread else ""
        if kind == "post":  # one conversation per post: it can be cleared, never doubled
            clear = ('<button type="button" class="askclear" data-askclearpost title="Clear this conversation" aria-label="Clear this conversation">'
                     + ui.icon("trash") + "</button>") if thread else ""
        else:
            clear = ('<button type="button" class="askclear" data-askclear title="New chat" aria-label="New chat">' + ui.icon("summary") + "</button>") if thread else ""
        return (f'{clear}<div class="askthread" data-askthread>{hello}{messages}</div>{starters}'
                f'<form class="askform" data-askform>{ui.hidden(self.csrf, scope=scope)}'
                f'<textarea name="q" rows="2" maxlength="2000" placeholder="{e(hint)}" aria-label="Your question" required '
                f'data-gramm="false" data-gramm_editor="false" data-enable-grammarly="false" autocomplete="off"></textarea>'
                f'<div class="askcardbar"><span class="askleft">{self.ask_chip(engine)}<span class="askvoicest" data-askvoicest aria-live="polite"></span></span>'
                f'{self.ask_depth_pick()}'
                f'<span class="askright"><button type="button" class="askmic" data-askmic aria-label="Speak your question" '
                f'title="Speak your question (turned into text on this Mac)">{MIC}</button>'
                f'<button class="asksend" type="submit" aria-label="Send" data-asksend>{SEND}{STOP}</button></span></div></form>'
                f'<div class="askconfirm" data-askconfirm hidden><p>' + (
                    f'This sends your question{f" and the text of {n} post" + ("" if n == 1 else "s") if n else ""} to <b>{e(engine["name"])}</b>, '
                    'which may search the web. Never the video.' if opened else
                    f'This sends the text of about <b>{n}</b> post{"" if n == 1 else "s"} to <b>{e(engine["name"])}</b>. Never the video.')
                + '</p>'
                '<div class="row"><button type="button" class="btn dark sm" data-askgo>Send</button>'
                '<button type="button" class="btn sm quiet" data-askno>Cancel</button></div></div>')

    def ask_panel(self, q: dict) -> Response:
        if not self.ask_enabled():
            return Response(404, b"gone", "text/plain")
        scope = q.get("scope", "")
        found = self.ask_scope(scope)
        if not found:
            return Response(404, b"gone", "text/plain")
        label, items = found
        n = len(items)
        body = self.ask_body(scope, label, items)
        html_ = (f'<aside id="askpanel" class="askp" role="dialog" aria-label="Ask Magpiary" data-scope="{e(scope)}">'
                 f'<div class="askgrip" data-askgrip role="separator" aria-orientation="vertical" aria-label="Drag to resize" tabindex="-1" '
                 f'title="Drag to resize · double-click to reset"><i></i></div>'
                 f'<header class="askhead"><button type="button" class="askhist" data-askhist aria-label="Past chats" title="Past chats">{ui.icon("chats")}</button>'
                 f'<span><b><i class="askmark" aria-hidden="true">✦</i> Ask Magpiary</b><small>{e(label)}{"" if scope.startswith("library") else f" · {n} save" + ("" if n == 1 else "s")}</small></span>'
                 f'<button type="button" class="rb" data-askmin aria-label="Minimise" title="Minimise to a bar">{ui.icon("minimize")}</button>'
                 f'<a class="rb" href="/ask?scope={e(scope)}" data-askexpand aria-label="Open as a full page" title="Open as a full page">{ui.icon("expand")}</a>'
                 f'<button type="button" class="rb" data-askclose aria-label="Close" title="Close (keeps this chat in your list)">{ui.icon("close")}</button></header>{body}</aside>')
        return Response(200, html_.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

    def _ask_message(self, m: dict, items: list[dict], scope: str, readonly: bool = False) -> str:
        if m["role"] == "user":
            return f'<div class="askm me">{e(m["text"])}</div>'
        meta = m["meta"]
        if meta.get("open"):
            return self._open_message(m, scope, readonly)
        by_id = {i["id"]: i for i in items} | {i["id"]: i for i in (self.store.item_by_id(x) for x in meta.get("posts") or []) if i}
        order = meta.get("posts") or [i["id"] for i in items]

        def chip(match: re.Match) -> str:
            n, at = int(match.group(1)), match.group(2) or ""
            if not 1 <= n <= len(order) or order[n - 1] not in by_id:
                return ""
            it = by_id[order[n - 1]]
            name = (it.get("author") or ui.title_of(it))[:22]
            return (f'<a class="askcite" href="/item/{it["id"]}" data-t="{e(at)}" title="{e(ui.title_of(it))}">'
                    f'{e(name)}{" · " + e(at) if at else ""}</a>')

        answer = asking.CITE.sub(chip, e(m["text"]).replace("\n", "<br>"))
        acts = []
        if readonly:
            pass
        elif meta.get("found") is False and not meta.get("widened"):
            acts.append(f'<button type="button" class="askact" data-askwide="{m["id"]}">Search all my saves</button>')
        if not readonly and meta.get("found", True) and scope.partition(":")[0] in ("post", "pile"):
            acts.append(f'<button type="button" class="askact" data-asksave="{m["id"]}">Save as note</button>')
        return (f'<div class="askm ai{" nofind" if meta.get("found") is False else ""}" data-msg="{m["id"]}">{answer}'
                + ('<small class="askwide">Looked across your whole library</small>' if meta.get("widened") else "")
                + (f'<div class="askacts">{"".join(acts)}</div>' if acts else "") + "</div>")

    STEP_LABEL = {"search": "Searching the web", "read": "Reading a page", "saves": "Searching your saves", "save": "Reading a save", "work": "Working"}

    def _think_tree(self, steps: list, live: bool = False) -> str:
        """The thinking steps, one quiet line each: an icon, what it did, and what it searched or read. Steps from before this was
        structured are plain sentences."""
        out = []
        for st in steps:
            st = st if isinstance(st, dict) else {"step": str(st), "kind": "work", "arg": ""}
            kind, arg = st.get("kind", "work"), st.get("arg", "")
            if kind == "read":
                arg = re.sub(r"^https?://(www\.)?", "", arg).split("/")[0]
            icon = ui.icon("search" if kind in ("search", "saves") else "links")
            out.append(f'<li>{icon}<span class="lab">{e(self.STEP_LABEL.get(kind, st.get("step", "Working")))}</span>'
                       + (f'<span class="arg">{e(arg[:80])}</span>' if arg else "") + "</li>")
        return f'<ol class="askthinksteps">{"".join(out)}</ol>'

    def _open_message(self, m: dict, scope: str, readonly: bool = False) -> str:
        """An answer from the open version: what it did to get there (folded), the rendered text, and links it suggests keeping."""
        meta = m["meta"]
        steps = meta.get("steps") or []
        took = int(meta.get("seconds") or 0)
        did = (f'<details class="askthought"><summary>{ui.icon("sparkle")}<span>Thought for {took} s · {len(steps)} step{"" if len(steps) == 1 else "s"}</span></summary>'
               + self._think_tree(steps) + "</details>") if steps else ""
        acts = ""
        if not readonly and scope.partition(":")[0] in ("post", "pile"):
            acts += f'<button type="button" class="askact" data-asksave="{m["id"]}">Save as note</button>'
        tokens = askconfig.usage_line({**meta["usage"], "cost": 0}) if meta.get("usage") and askconfig.show_tokens(self.store) else ""
        cards = "".join(
            f'<a class="askcard" href="{e(c["url"])}" target="_blank" rel="noopener noreferrer">'
            + (f'<span class="askcardimg" style="background-image:url(/ask/card-img/{e(c["img"])})"></span>' if c.get("img") else "")
            + f'<span class="askcardtx"><b>{e(c.get("title") or c["site"])}</b><small>{self._site_icon(c["url"])}{e(c["site"])}</small></span></a>'
            for c in meta.get("cards") or [] if c.get("url"))
        return (f'<div class="askm ai open" data-msg="{m["id"]}">{did}<div class="askbody">{self.render_answer(m["text"])}</div>'
                + (f'<div class="askcards">{cards}</div>' if cards else "")
                + (f'<small class="asktokens" title="Tokens for this answer (Claude plan: no cost per answer)">{e(tokens)}</small>' if tokens else "")
                + (f'<div class="askacts">{acts}</div>' if acts else "") + "</div>")

    def render_answer(self, text: str) -> str:
        """The AI's answer as safe HTML: paragraphs, lists, **bold**, `code`, web links (http and https only) and chips for the
        saves it points at. Everything is escaped first."""
        def inline(line: str) -> str:
            line = e(line)
            line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
            line = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)
            line = re.sub(r"\[([^\]]+)\]\((https?://[^\s)\"']+)\)",
                          lambda mt: f'<a class="asklink" href="{mt.group(2)}" target="_blank" rel="noopener noreferrer">{self._site_icon(html.unescape(mt.group(2)))}{mt.group(1)}</a>', line)

            def chip(mt: re.Match) -> str:
                it = self.store.item_by_id(int(mt.group(1)))
                if not it:
                    return ""
                at = mt.group(2) or ""
                name = (it.get("author") or ui.title_of(it))[:22]
                return (f'<a class="askcite" href="/item/{it["id"]}" data-t="{e(at)}" title="{e(ui.title_of(it))}">'
                        f'{e(name)}{" · " + e(at) if at else ""}</a>')
            return ask_open.SAVE_REF.sub(chip, line)

        out, block = [], []

        def flush() -> None:
            if block:
                out.append(f'<p>{"<br>".join(inline(l) for l in block)}</p>')
                block.clear()
        items: list[str] = []
        ordered = False

        def close_list() -> None:
            nonlocal items
            if items:
                tag = "ol" if ordered else "ul"
                out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
                items = []
        for raw in text.strip().splitlines():
            line = raw.rstrip()
            bullet = re.match(r"^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$", line)
            if bullet:
                flush()
                if items and ordered != bool(bullet.group(1)):
                    close_list()
                ordered = bool(bullet.group(1))
                items.append(bullet.group(2))
            elif not line.strip():
                flush()
                close_list()
            else:
                close_list()
                heading = re.match(r"^#{1,4}\s+(.*)$", line)
                if heading:
                    flush()
                    out.append(f"<h5>{inline(heading.group(1))}</h5>")
                else:
                    block.append(line)
        flush()
        close_list()
        return "".join(out)

    # ---- asking ------------------------------------------------------------------------------------------------

    def ask_post(self, path: str, form: dict) -> Response:
        if not self.ask_enabled():
            return Response(404, b"gone", "text/plain")
        if path == "/hub/ask/engine":
            if form.get("engine") in ("claude", "codex", "key"):
                self.store.set_setting(ENGINE, form["engine"])
            return Response(200, b"ok", "text/plain")
        if path == "/hub/ask/depth":
            if form.get("depth") in askconfig.DEPTHS:
                self.store.set_setting(askconfig.DEPTH, form["depth"])
            return Response(200, b"ok", "text/plain")
        if path == "/hub/ask/voice":
            return self._ask_voice(form)
        if path == "/hub/ask/stop":
            job = self.__dict__.get("_ask_jobs", {}).get(form.get("job", ""))
            if job:
                job["stop"] = True
            return Response(200, b"ok", "text/plain")
        if path == "/hub/ask/session-pin":
            if form.get("id", "").isdigit():
                self.store.ask_session_pin(int(form["id"]), form.get("on") == "1")
            return Response(200, b"ok", "text/plain")
        if path == "/hub/ask/session-resume":
            scope = self.store.ask_session_resume(int(form["id"])) if form.get("id", "").isdigit() else None
            return Response(200, json.dumps({"scope": scope}).encode() if scope else b"{}", "application/json")
        if path == "/hub/ask/live-delete":
            if self.ask_scope(form.get("scope", "")):
                self.store.ask_clear(form["scope"])
            return Response(200, b"ok", "text/plain")
        if path == "/hub/ask/session-delete":
            if form.get("id", "").isdigit():
                self.store.ask_session_delete(int(form["id"]))
            return Response(200, b"ok", "text/plain")
        scope = form.get("scope", "")
        found = self.ask_scope(scope)
        if not found:
            return Response(404, b"gone", "text/plain")
        label, items = found
        if path == "/hub/ask/clear":
            self.store.ask_end(scope, label)
            return Response(303, b"", headers={"Location": "/ask/panel?scope=" + scope})
        if path == "/hub/ask/note":
            message = self.store.ask_message(int(form["message"])) if form.get("message", "").isdigit() else None
            if not message or message["scope"] != scope or message["role"] != "assistant":
                return Response(404, b"gone", "text/plain")
            plain = asking.CITE.sub("", message["text"]).replace("  ", " ").strip()
            kind, _, ident = scope.partition(":")
            saved = "saved"
            if kind == "post":
                item = self.store.item_by_id(int(ident))
                saved = ((item.get("note") or "").rstrip() + "\n\n" if item.get("note") else "") + plain
                self.store.set_note(item["id"], saved)
                saved = self.store.item_by_id(item["id"]).get("note") or saved  # what is kept (a very long note is cut)
            elif kind == "pile":
                self.store.ask_note_add(scope, plain)
            return Response(200, saved.encode(), "text/plain")
        if path != "/hub/ask/send":
            return Response(404, b"gone", "text/plain")
        question = form.get("q", "").strip()[:600]
        engine = self.ask_engine()
        if not question or engine is None:
            return Response(400, b"No question or no AI.", "text/plain")
        over = self.ask_over_limit()
        if over and form.get("over") != "1":  # the soft spend guard: say so, and go on only when asked again
            return Response(200, json.dumps({"warn": over}).encode(), "application/json", headers={"Cache-Control": "no-store"})
        if engine["id"] == "key" and not items:  # a key has no tools of ours: send the saves that best match the question
            items = self._ask_library(question)
        return self._ask_start(scope, label, items, question, form.get("again") == "1", engine)

    # ---- the open version runs as a job: the page asks how far it got every half second ---------------------------

    def ask_usage_state(self) -> dict:
        """Tokens used in the period of the chosen limit, and the limit: {"used", "cap", "period", "fraction"}."""
        period = askconfig.limit_period(self.store)
        used = sum(r["tokens_in"] + r["tokens_out"] for r in self.store.ask_usage_since(askconfig.periods(self.store._now())[period]))
        cap = askconfig.limit(self.store)
        return {"used": used, "cap": cap, "period": period, "fraction": min(used / cap, 1.0) if cap else 0.0}

    def ask_over_limit(self) -> str:
        """A plain sentence when the limit chosen in Settings has been passed; "" otherwise."""
        state = self.ask_usage_state()
        if askconfig.warn_on(self.store) and state["cap"] and state["used"] >= state["cap"]:
            when = "today" if state["period"] == "day" else "this month"
            return (f"You have used about {askconfig.compact(state['used'])} tokens {when} in Ask Magpiary, past your "
                    f"{askconfig.LIMITS[askconfig.limit_preset(self.store)][0]} limit ({askconfig.limit_words(self.store)}).")
        return ""

    def ask_depth_pick(self) -> str:
        """Short / Normal / Deep, beside the send button: how thorough the next answer is (remembered)."""
        now = askconfig.depth(self.store)
        return ('<span class="askdepth" role="radiogroup" aria-label="How thorough the answer is" title="How thorough the answer is">'
                + "".join(f'<button type="button" role="radio" data-askdepth="{k}" class="{"on" if k == now else ""}" '
                          f'aria-checked="{str(k == now).lower()}">{v}</button>' for k, v in askconfig.DEPTHS.items()) + "</span>")

    def ask_chip(self, engine: dict) -> str:
        """Who is answering right now: "Claude Code · Haiku 5.5 · Medium", with a globe when the web is on."""
        bits = [engine.get("short", ""), engine.get("model", "")]
        if engine["id"] == "claude":
            bits.append(askconfig.EFFORTS[askconfig.claude_effort(self.store)])
        elif engine["id"] == "codex":
            bits.append(askconfig.CODEX_EFFORTS[askconfig.codex_effort(self.store)])
        logo = ENGINE_LOGO.get(engine["id"] if engine["id"] != "key" else (engine["key"].provider if engine.get("key") else ""), "")
        return f'<span class="askmodel" title="Who answers (change it in Settings → Ask Magpiary)">{logo}{e(" · ".join(b for b in bits if b))}</span>'

    def _ask_start(self, scope: str, label: str, items: list[dict], question: str, again: bool, engine: dict) -> Response:
        history = [(m["role"], m["text"]) for m in self.store.ask_thread(scope)]
        if not again:
            self.store.ask_add(scope, "user", question)
            self.store.activity_add("ask")
        jobs = self.__dict__.setdefault("_ask_jobs", {})
        for old in [k for k, v in jobs.items() if v["done"] and time.monotonic() - v["at"] > 600]:
            jobs.pop(old, None)
        job_id = uuid.uuid4().hex[:12]
        job = jobs[job_id] = {"events": [], "done": False, "html": "", "at": time.monotonic(), "stop": False}

        web = askconfig.web_allowed(self.store)
        context = self.ask_place(scope, label, items)["context"]
        goals = self.store.get_setting("digest_goals", "")
        who = engine["id"]
        effort = askconfig.codex_effort(self.store) if who == "codex" else askconfig.claude_effort(self.store) if who == "claude" else ""
        model = engine.get("alias") or askconfig.DEFAULT_MODEL
        depth = askconfig.depth(self.store)

        def work() -> None:
            steps: list[dict] = []
            used: dict = {}
            began = time.monotonic()

            def on_event(ev: dict) -> None:
                if "step" in ev:
                    steps.append({k: ev[k] for k in ("step", "kind", "arg") if k in ev})
                if "usage" in ev:
                    used.update(ev["usage"])
                    return  # kept with the answer, not shown as a step
                job["events"].append(ev)

            def answer_it() -> str:
                if who == "codex":
                    from magpiary import ask_codex

                    return ask_codex.run(question, items[:asking.LIBRARY_POSTS], history, label, on_event, cancelled=lambda: job["stop"],
                                         model=model, effort=effort, web=web, context=context, depth=depth, goals=goals)
                if who == "key":
                    from magpiary import ask_keys

                    return ask_keys.run(engine["key"], question, items[:asking.LIBRARY_POSTS], history, label, on_event,
                                        cancelled=lambda: job["stop"], web=web, context=context, depth=depth, goals=goals)
                return ask_open.run(question, items[:asking.LIBRARY_POSTS], history, label, on_event, cancelled=lambda: job["stop"],
                                    model=model, effort=effort, web=web, context=context, depth=depth, goals=goals)
            try:
                text = answer_it()
                answer, saves = ask_open.split_saves(text)
                try:
                    from magpiary import ask_cards

                    # fetched by this Mac, never by the AI: no tokens. Only when the owner let Ask use the web: the addresses
                    # come from an AI answer, and fetching one could carry private text out (review 3, 4 Nov 2026)
                    cards = ask_cards.cards_for(answer) if web else []
                except Exception:
                    cards = []
                usage = {**used, "model": engine.get("model", ""), "effort": effort, "engine": who} if used else {}
                if usage:
                    self.store.ask_usage_add(scope, who, engine.get("model", ""), usage["in"], usage["out"], usage.get("cost", 0.0))
                mid = self.store.ask_add(scope, "assistant", answer or "I have nothing to add.",
                                         {"open": True, "saves": saves, "steps": steps, "usage": usage, "cards": cards,
                                          "seconds": round(time.monotonic() - began)})
                job["html"] = self._ask_message(self.store.ask_message(mid), items, scope)
            except BrainFailed as err:
                if job["stop"]:
                    job["html"] = '<div class="askm ai stopped">Stopped. Nothing was kept from that answer.</div>'
                    job["done"] = True
                    job["at"] = time.monotonic()
                    return
                job["html"] = self._ask_error(self._ask_failure(engine["short"], err))
            except Exception as err:  # the chat must never hang on a surprise
                job["html"] = self._ask_error(f"Something went wrong ({type(err).__name__}). Try again.")
            job["done"] = True
            job["at"] = time.monotonic()
        threading.Thread(target=work, name="ask", daemon=True).start()
        return Response(200, json.dumps({"job": job_id}).encode(), "application/json", headers={"Cache-Control": "no-store"})

    def _ask_voice(self, form: dict) -> Response:
        """A spoken question, turned into text on this Mac with the same Whisper that listens to saved videos. The sound is kept
        only for the moment it takes, in a temporary folder, and never leaves the Mac."""
        import base64
        import subprocess
        import tempfile

        from magpiary import transcribe
        from magpiary.tools import find

        def reply(body: dict) -> Response:
            return Response(200, json.dumps(body).encode(), "application/json", headers={"Cache-Control": "no-store"})
        try:
            data = base64.b64decode(form.get("audio", ""), validate=False)
        except ValueError:
            data = b""
        if not 1000 < len(data) <= 500_000:
            return reply({"error": "That recording was empty or too long. Try again, up to a minute."})
        ffmpeg = find("ffmpeg")
        if not ffmpeg:
            return reply({"error": "Voice needs ffmpeg on this Mac (brew install ffmpeg)."})
        with tempfile.TemporaryDirectory(prefix="magpiary-voice-") as folder:
            src, wav, out = Path(folder, "in"), Path(folder, "a.wav"), Path(folder, "t.json")
            src.write_bytes(data)
            try:
                subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(wav)],
                               capture_output=True, timeout=30, check=True)
                result = transcribe.transcribe(wav, out)
            except (OSError, subprocess.SubprocessError, transcribe.TranscribeFailed):
                return reply({"error": "I couldn't turn that into text. Try again."})
        text = spoken_words(" ".join(s["text"].strip() for s in result.get("segments") or []))
        return reply({"text": text} if text else {"error": "I didn't catch any words. Try again a little closer."})

    def _session_when(self, stamp: str) -> str:
        try:
            at = datetime.fromisoformat(stamp)
            now = self.store._now()
        except ValueError:
            return ""
        days = (now.date() - at.date()).days
        clock = at.strftime("%H:%M")
        return f"Today, {clock}" if days == 0 else f"Yesterday, {clock}" if days == 1 else at.strftime("%b ") + str(at.day)

    def ask_page(self, q: dict) -> Response:
        """Ask on a page of its own: past and live chats on the left, the chat on the right."""
        from magpiary.web import Response as R

        if not self.ask_enabled():
            return R(303, b"", headers={"Location": "/"})
        scope = q.get("scope", "library:all")
        found = self.ask_scope(scope) or self.ask_scope("library:all")
        scope = scope if self.ask_scope(scope) else "library:all"
        label, items = found
        side = self._chat_list(scope)
        picker = self._place_picker(scope)
        body = self.ask_body(scope, label, items)
        main = (f'<div class="askpage"><aside class="askside"><b class="asktitle"><i class="askmark" aria-hidden="true">✦</i> Ask Magpiary</b>'
                f'<hr class="askrule"><a class="askneww" href="/ask?scope=library:all" data-asknewchat>{ui.icon("summary")}<span>New chat</span>{ui.icon("plus")}</a>'
                f'<div class="askslist">{side}</div><a class="askbacklib" href="/" data-askback>← Back</a></aside>'
                f'<section class="askmain"><header class="askfullhead"><div class="askcol">{picker}</div>'
                f'<button type="button" class="rb askctlbtn" data-askctl aria-label="Controls" title="Controls: who answers, model, tokens">{ui.icon("sliders") if "sliders" in ui._ICON_PATHS else ui.icon("gear")}</button></header>'
                f'<div class="askp askfull" data-scope="{e(scope)}">{body}</div></section>'
                f'<aside class="askctlcol" data-askctlcol>{self.ask_controls(scope)}</aside></div>')
        return self.shell("Ask Magpiary", main, "ask")

    def _place_picker(self, scope: str) -> str:
        """"Asking about: [Whole library ▾]": where this chat is asked from."""
        opts = [("library:all", "Whole library"), ("library:everything", "Everything, newest first"), ("library:piles", "Your piles"),
                ("library:boards", "Your boards")]
        piles = [(f'pile:{p["id"]}', p["name"]) for p in self.store.piles() if p.get("members")][:60]
        boards = [(f'board:{b["id"]}', b["name"]) for b in self.store.boards()][:40]
        known = {v for v, _ in opts + piles + boards}
        extra = [(scope, (self.ask_scope(scope) or ("This post", 0))[0][:50])] if scope not in known else []

        def group(name: str, items: list) -> str:
            return f'<optgroup label="{name}">' + "".join(f'<option value="{e(v)}"{" selected" if v == scope else ""}>{e(n[:50])}</option>' for v, n in items) + "</optgroup>" if items else ""
        return ('<label class="askplace">Asking about <select data-askplace aria-label="Where to ask from">' + group("Library", opts)
                + group("This post", extra) + group("Piles", piles) + group("Boards", boards) + "</select></label>")

    def _chat_list(self, scope: str = "") -> str:
        """The chats, for the sheet's list and the full page: Now (still going, one per place), Pinned, Recent (three days), Earlier.
        Every one can be carried on; each has a menu (pin, delete)."""
        dots = f'<button type="button" class="askdots" data-askmenu aria-label="More" title="More">{ui.icon("more")}</button>'

        def place(sc: str, label: str = "") -> str:
            found = None if sc == "library:all" else self.ask_scope(sc)
            return "Whole library" if sc == "library:all" else (found[0] if found else label)

        def live_row(chat: dict) -> str:
            return (f'<div class="askhrow2" data-kind="live" data-scope="{e(chat["scope"])}"><button type="button" class="askhrow{" on" if chat["scope"] == scope else ""}" '
                    f'data-asklive="{e(chat["scope"])}"><b>{e(chat["title"][:90])}</b><small>{e(place(chat["scope"]))}</small></button>{dots}</div>')

        def post_row(chat: dict) -> str:
            name = place(chat["scope"])
            return (f'<div class="askhrow2" data-kind="live" data-scope="{e(chat["scope"])}"><button type="button" class="askhrow{" on" if chat["scope"] == scope else ""}" '
                    f'data-asklive="{e(chat["scope"])}"><b>{e(name[:90])}</b><small>{e(chat["title"][:90])}</small></button>{dots}</div>')

        def past_row(r: dict) -> str:
            return (f'<div class="askhrow2" data-kind="past" data-id="{r["id"]}" data-pinned="{r["pinned"]}"><button type="button" class="askhrow" data-askopen="{r["id"]}">'
                    f'<b>{e(r["title"])}</b><small>{e(place(r["scope"], r["label"]))} · {e(self._session_when(r["ended"]))}</small></button>{dots}</div>')
        rows = self.store.ask_sessions()
        cutoff = (self.store._now() - timedelta(days=3)).isoformat(timespec="seconds")
        chats = [c for c in self.store.ask_live_chats() if self.ask_scope(c["scope"])]
        live = [live_row(c) for c in chats if not c["scope"].startswith("post:")]
        posts = [post_row(c) for c in chats if c["scope"].startswith("post:")]  # one chat per post
        groups = (("Posts", posts), ("Now", live), ("Pinned", [past_row(r) for r in rows if r["pinned"]]),
                  ("Recent", [past_row(r) for r in rows if not r["pinned"] and r["ended"] >= cutoff]),
                  ("Earlier", [past_row(r) for r in rows if not r["pinned"] and r["ended"] < cutoff]))
        return "".join(f'<h3 class="askhgroup">{name}</h3>{"".join(g)}' for name, g in groups if g) or \
            '<p class="askhempty">No chats yet.<br>Ask something and it will be kept here.</p>'

    def ask_sessions_page(self, q: dict) -> Response:
        """Every past chat, in a layer that covers the sheet: Recent (the last three days), then Earlier."""
        if not self.ask_enabled():
            return Response(404, b"gone", "text/plain")
        body = self._chat_list(q.get("scope", ""))
        html_ = (f'<div class="askhistwrap" data-askhistwrap><div class="askhistv" data-askhistv><header class="askhead">'
                 f'<button type="button" class="askhist" data-askhistclose aria-label="Back to the chat" title="Back to the chat">{ui.icon("back")}</button>'
                 f'<span><b>Chats</b><small>Pick one to carry on.</small></span></header>'
                 f'<div class="askhlist">{body}</div></div></div>')
        return Response(200, html_.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

    def ask_session_page(self, q: dict) -> Response:
        """One past chat, to read. No box, no resuming."""
        session = self.store.ask_session(int(q["id"])) if self.ask_enabled() and q.get("id", "").isdigit() else None
        if not session:
            return Response(404, b"gone", "text/plain")
        messages = "".join(self._ask_message({**m, "id": f'{session["id"]}-{i}'}, [], session["scope"], readonly=True)
                           for i, m in enumerate(session["messages"]))
        place = "Whole library" if session["scope"].startswith("library") else session["label"]
        if q.get("plain") == "1":  # on the full page: the chat on its own, no layer
            html_ = (f'<div class="askplain"><header class="askfullhead"><span><b>{e(session["title"][:80])}</b><small>{e(place)} · {e(self._session_when(session["ended"]))}</small></span>'
                     f'<button type="button" class="rb askhdel" data-askhistdel="{session["id"]}" aria-label="Delete this chat" title="Delete this chat">{ui.icon("trash")}</button></header>'
                     f'<div class="askthread askhread">{messages}</div><p class="askhnote">This chat is saved to read. It can&rsquo;t be continued.</p></div>')
            return Response(200, html_.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})
        html_ = (f'<div class="askhistwrap" data-askhistwrap><div class="askhistv" data-askhistv><header class="askhead"><button type="button" class="askhist" data-askhistback aria-label="All past chats" title="All past chats">{ui.icon("back")}</button>'
                 f'<span><b>{e(session["title"][:60])}</b><small>{e(place)} · {e(self._session_when(session["ended"]))}</small></span>'
                 f'<button type="button" class="rb askhdel" data-askhistdel="{session["id"]}" aria-label="Delete this chat" title="Delete this chat">{ui.icon("trash")}</button>'
                 f'</header><div class="askthread askhread">{messages}</div>'
                 f'<p class="askhnote">This chat is saved to read. It can&rsquo;t be continued.</p></div></div>')
        return Response(200, html_.encode(), "text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

    def ask_poll(self, q: dict) -> Response:
        job = self.__dict__.get("_ask_jobs", {}).get(q.get("job", ""))
        if not job:
            return Response(404, b"gone", "text/plain")
        after = int(q["after"]) if q.get("after", "").isdigit() else 0
        events = job["events"][after:]
        body = {"events": events, "n": after + len(events), "done": job["done"], "html": job["html"] if job["done"] else ""}
        if any(ev.get("text") for ev in events) and not job["done"]:
            # the text so far, formatted the way the finished answer will be, so nothing jumps when it is done
            so_far = re.sub(r"\[\[[^\]]*$", "", "".join(ev.get("text", "") for ev in job["events"]))
            body["live"] = self.render_answer(so_far)
        return Response(200, json.dumps(body).encode(), "application/json", headers={"Cache-Control": "no-store"})

    @staticmethod
    def _ask_failure(who: str, err: BrainFailed) -> str:
        """What went wrong in plain words, and what to do about it. Your question is always kept."""
        advice = {"no_key": f"There is no key for {who} yet. Add one in Settings, AI keys.",
                  "bad_key": f"{who} did not accept the key. Check it in Settings, AI keys.",
                  "rate_limited": f"{who} has hit its limit for now. Wait a little, then ask again.",
                  "busy": f"{who} is busy or slow right now. Ask again in a minute.",
                  "blocked": f"{who} would not answer that one. Try putting it another way."}
        tail = advice.get(getattr(err, "reason", ""), f"I couldn't reach {who} just now ({str(err)[:140]}). Try again in a moment.")
        return f"{tail} Your question is kept."

    def _ask_error(self, text: str) -> str:
        return f'<div class="askm ai nofind askerr">{e(text)}</div>'

    def _ask_library(self, question: str) -> list[dict]:
        """A widened question: the saves that best match it, by words and by meaning (about fifteen)."""
        words = re.findall(r"[^\W\d_]{3,}", question.lower())
        keep = [w for w in words if w not in asking.STOP][:8]
        items = self.store.hub_items("kept", " ".join(keep[:3])) if keep else []
        try:
            items = self._with_meaning(question, items)
        except Exception:
            pass
        if not items:
            items = self.store.hub_items("kept", limit=asking.LIBRARY_POSTS)
        return items[:asking.LIBRARY_POSTS]

    def pile_notes_html(self, pile_id: int) -> str:
        notes = self.store.ask_notes(f"pile:{pile_id}")
        if not notes:
            return ""
        rows = "".join(f'<div class="asknote"><p>{e(n["text"])}</p>'
                       + self._form("/hub/pile/note-delete", {"note": n["id"], "pile": pile_id, "next": f"/pile/{pile_id}"}, "Remove", "link")
                       + "</div>" for n in notes)
        return f'<section class="asknotes"><h4>Notes from Ask</h4>{rows}</section>'
