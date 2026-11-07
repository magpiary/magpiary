"""Settings → Ask Magpiary: the switch that turns Ask on or off everywhere, who answers (Claude Code on your plan, or one of your
AI keys), the model and how hard it thinks, the web, and the token display with an optional spend limit."""

from magpiary import askconfig, ui
from magpiary import keys as keyring
from magpiary.web import e

BACK = "/settings/ai"
KEY_WARN = {"free": "A free key can run out quickly: every question counts against its daily limit.",
            "paid": "Billed per use by the provider; a question costs a little more than a summary."}


class AskSettings:
    """Needs Hub's store, csrf, _switch and _claude_state (SettingsPages)."""

    def ask_status(self) -> tuple[str, bool]:
        """One line for the settings list: how Ask stands right now."""
        if not askconfig.enabled(self.store):
            return "Off · no Ask buttons shown", False
        engine = self.ask_engine()
        if engine is None:
            return "On · nobody can answer yet", True
        return f'On · {engine["short"]}{" · " + engine["model"] if engine["id"] in ("claude", "codex") else ""}', False

    def _askset_form(self, fields: dict, label: str, cls: str = "btn sm") -> str:
        confirm = ' data-confirm="Remove it from Ask Magpiary? It stays installed on this Mac; you can set it up here again."' if "remove" in fields else ""
        return (f'<form method="post" action="/hub/askset"{confirm}>{ui.hidden(self.csrf, next=BACK, **fields)}'
                f'<button type="submit" class="{cls}">{e(label)}</button></form>')

    def _ask_section(self, q: dict, nested: bool = False) -> str:
        from magpiary.hub_settings import _adv, _group, _row

        from magpiary import engines

        on = askconfig.enabled(self.store)
        free = engines.only_free(self.store)
        switch = self._switch("/hub/askset", on, {"on": "0", "next": BACK}, {"on": "1", "next": BACK}, "Ask Magpiary",
                              confirm=("Turn off Ask Magpiary? This closes every open Ask panel, stops any answer being written, and "
                                       "removes every Ask button. Your chats are kept for when you turn it back on.") if on else
                              engines.warning("ask") if free else "",
                              ok="" if on else "I understand, turn it on")
        why = ('<p class="small">Ask needs an AI key, or Claude Code or Codex allowed in AI keys.</p>'
               if not on and not engines.options(self.store) else "")
        out = [_group("", _row("Use Ask Magpiary", "Ask about a post, a pile, a board or your whole library, and the web.", switch,
                               more=why), gid="onoff", cls="feat")]
        if not on:
            return "".join(out)
        extra = self._ask_model() + self._ask_usage()
        out += [self._ask_engines(), self._ask_answers(), extra if nested else _adv(extra, "Model and effort, tokens and a limit")]
        return "".join(out)

    def _engine_switch(self, on: bool, label: str, fields_on: dict, fields_off: dict, confirm: str = "", back: str = BACK) -> str:
        return self._switch("/hub/askset", on, {**fields_off, "next": back}, {**fields_on, "next": back}, label, confirm=confirm)

    def ask_controls(self, scope: str) -> str:
        """The settings that matter while chatting, compact, for the full page's third column: who answers (green when active), the
        model and effort, the web, and the tokens used so far."""
        from magpiary import ask_codex, ask_setup
        from magpiary.hub_ask import ENGINE_LOGO

        back = "/ask?scope=" + scope
        engine = self.ask_engine()
        active = engine["id"] if engine else ""
        rows = []

        def row(logo: str, name: str, on: bool, fields_on: dict, fields_off: dict) -> str:
            return (f'<div class="actl-row"><span class="actl-logo">{logo}</span><span class="actl-name">{e(name)}'
                    + ('<small class="ok">Active</small>' if on else "") + "</span>"
                    + self._engine_switch(on, name, fields_on, fields_off, back=back) + "</div>")
        state = self._claude_state() if ask_setup.installed("claude") else {"installed": False, "signed_in": False}
        from magpiary import engines

        if state["installed"] and state["signed_in"] is not False and not askconfig.removed(self.store, "claude") \
                and engines.is_allowed(self.store, "claude_code"):
            rows.append(row(ENGINE_LOGO["claude"], "Claude Code", active == "claude", {"engine": "claude"}, {"deactivate": "claude"}))
        if ask_codex.available() and not askconfig.removed(self.store, "codex") and engines.is_allowed(self.store, "codex"):
            rows.append(row(ENGINE_LOGO["codex"], "Codex", active == "codex", {"engine": "codex"}, {"deactivate": "codex"}))
        for k in keyring.usable():
            mine = active == "key" and engine["key"] is not None and engine["key"].id == k.id
            rows.append(row(ENGINE_LOGO.get(k.provider, ""), k.name, mine, {"engine": "key", "key": k.id}, {"deactivate": "key"}))
        who = "".join(rows) or '<p class="actl-note">Nobody can answer yet. Set one up in Settings.</p>'
        model = ""
        if engine and engine["id"] in ("claude", "codex"):
            codex = engine["id"] == "codex"
            models = askconfig.CODEX_MODELS if codex else askconfig.CLAUDE_MODELS
            efforts = askconfig.CODEX_EFFORTS if codex else askconfig.EFFORTS
            cur_m = askconfig.codex_model(self.store) if codex else askconfig.claude_model(self.store)
            cur_e = askconfig.codex_effort(self.store) if codex else askconfig.claude_effort(self.store)
            pm, pe = ("cmodel", "ceffort") if codex else ("model", "effort")
            om = "".join(f'<option value="{m}"{" selected" if m == cur_m else ""}>{e(n.split(" (")[0])}</option>' for m, n in models.items())
            oe = "".join(f'<option value="{k}"{" selected" if k == cur_e else ""}>{v}</option>' for k, v in efforts.items())
            model = (f'<form method="post" action="/hub/askset" class="actl-form">{ui.hidden(self.csrf, next=back)}'
                     f'<label>Model<select name="{pm}">{om}</select></label><label>Effort<select name="{pe}">{oe}</select></label>'
                     f'<button type="submit" class="btn sm dark actl-save" hidden>Save</button></form>')
        web = self._switch("/hub/askset", askconfig.web_allowed(self.store), {"web": "0", "next": back}, {"web": "1", "next": back}, "Allow the web")
        starts = askconfig.periods(self.store._now())
        usage = ""
        for period, name in (("day", "Today"), ("week", "This week"), ("month", "This month")):
            used = self.store.ask_usage_since(starts[period])
            total = sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in used)
            qs = sum(int(r["questions"]) for r in used)
            asked = f"{qs} question" + ("" if qs == 1 else "s") if used else ""
            usage += f'<div class="actl-use"><span>{name}</span><b>{askconfig.compact(total) if used else "—"}</b><small>{asked}</small></div>'
        return (f'<div class="actl"><h4>Who answers</h4>{who}{model}<div class="actl-row"><span class="actl-name">Allow web search</span>{web}</div>'
                f'<h4>Tokens used</h4><div class="actl-uses">{usage}</div><a class="actl-all" href="/settings/ai#ask">All Ask settings →</a></div>')

    def _ask_engines(self) -> str:
        from magpiary import ask_codex, ask_setup
        from magpiary.hub_ask import ENGINE_LOGO
        from magpiary.hub_settings import _group, _more, _row

        engine = self.ask_engine()
        active = engine["id"] if engine else ""
        rows = []
        green = '<span class="sstat ok"><i></i>Active</span>'

        def ctl(status: str = "", remove: str = "", switch: str = "") -> str:
            """The same three columns on every row, so the status, Remove and the switch line up like a table."""
            return f'<div class="engctl"><span class="engst">{status}</span><span class="engrm">{remove}</span><span class="engsw">{switch}</span></div>'

        def tool_row(eid: str, title: str, ready_note: str, setup_note: str, ready: bool, confirm: str) -> str:
            job = ask_setup.status(eid)
            logo = ENGINE_LOGO[eid]
            if job["state"] == "working":
                self._claude_cache = None
                return _row(title, setup_note, ctl(f'<span class="sstat"><i></i>{e(job["text"])}</span><span data-askwait hidden></span>'), lead=logo)
            if job["state"] == "error":
                again = self._askset_form({"setup": eid}, "Try again")
                return _row(title, e(job["text"]), ctl(remove=again), lead=logo)
            if not ready:
                return _row(title, setup_note, ctl(switch=self._engine_switch(False, f"Set up {title}", {"setup": eid}, {}, confirm)), lead=logo)
            if not engines.is_allowed(self.store, "claude_code" if eid == "claude" else "codex"):
                return _row(title, "On this Mac, but not allowed. Magpiary never uses it until you allow it in AI keys.",
                            ctl(remove='<a class="btn sm" href="/settings/ai#keys">Allow it</a>'), lead=logo)
            on = active == eid
            controls = ctl(green if on else "", self._askset_form({"remove": eid}, "Remove", "btn sm ghost"),
                           self._engine_switch(on, f"Use {title}", {"engine": eid}, {"deactivate": eid}))
            return _row(title, ready_note, controls, lead=logo)

        from magpiary import engines

        state = self._claude_state() if ask_setup.installed("claude") else {"installed": False, "signed_in": False}
        claude_ready = state["installed"] and state["signed_in"] is not False and not askconfig.removed(self.store, "claude")
        rows.append(tool_row(
            "claude", "Claude Code · your Claude plan",
            "Uses your Claude plan. It can search the web, read pages and look through your saves, and nothing else.",
            "Not set up. Switch it on and Magpiary installs it if needed and opens Claude's sign-in page. Your Mac asks for the usual "
            "permissions there.", claude_ready,
            "Set up Claude Code? If it isn't on this Mac, Magpiary installs it (from claude.ai), then opens Claude's sign-in page in your browser."))
        codex_ready = ask_codex.available() and not askconfig.removed(self.store, "codex")
        rows.append(tool_row(
            "codex", "Codex · your ChatGPT plan",
            "Uses your ChatGPT plan. It can search the web and look through your saves. Heads-up: Codex can't be shut out of this Mac the "
            "way Claude Code can. It runs read-only in an empty folder and is told not to, but it could still read files here (never change them).",
            "Not set up. Switch it on and Magpiary installs it if needed and opens ChatGPT's sign-in page. Your Mac asks for the usual permissions "
            "there. Heads-up: Codex can't be shut out of this Mac the way Claude Code can; it runs read-only.", codex_ready,
            "Set up Codex? If it isn't on this Mac, Magpiary installs it (with npm), then opens ChatGPT's sign-in page in your browser."))
        keys = keyring.usable()
        for k in keys:
            mine = active == "key" and engine["key"] is not None and engine["key"].id == k.id
            controls = ctl(green if mine else "", "", self._engine_switch(mine, f"Use {k.name}", {"engine": "key", "key": k.id}, {"deactivate": "key"}))
            rows.append(_row(f"{k.name}", KEY_WARN.get(k.tier if k.tier in KEY_WARN else "paid", ""), controls,
                             lead=ENGINE_LOGO.get(k.provider, ui.icon("links"))))
        if not keys:
            rows.append(_row("An AI key", "Add a Gemini, OpenRouter, Claude or OpenAI key under AI & login, then pick it here.",
                             '<a class="btn sm" href="/settings/ai#keys">Add a key</a>', lead=ui.icon("links")))
        return _group("Who answers", "".join(rows), gid="engine",
                      desc="One is active at a time (green). Change it any time; each answer says which one wrote it.",
                      more=_more("<p>Claude Code and Codex use the plan you already pay for. An API key is billed by its provider, and a "
                                 "free key has a daily limit. A key searches the web with the provider's own search (about a cent a search on a paid key) and reads the saves that best match your question. <b>Remove</b> takes a tool out of Magpiary only: it stays installed and signed in "
                                 "on this Mac, and you can set it up here again. If the active one runs out, Ask says so; it never spends "
                                 "another key without your tap.</p>"))

    def _ask_answers(self) -> str:
        """What most people change: how much it says, whether it may use the web, and a line on what today cost."""
        from magpiary.hub_settings import _group, _row

        web = self._switch("/hub/askset", askconfig.web_allowed(self.store), {"web": "0", "next": BACK}, {"web": "1", "next": BACK},
                           "Allow the web")
        web_row = _row("Allow web search", "Lets the AI search the web. Off: it answers from what it knows and from your saves. Web "
                       "answers use more tokens, and on a paid key each search is billed by the provider.", web)
        depth_now = askconfig.depth(self.store)
        depth_bar = (f'<form method="post" action="/hub/askset" class="segbar" role="radiogroup">{ui.hidden(self.csrf, next=BACK)}'
                     + "".join(f'<button type="submit" name="depth" value="{k}" role="radio" class="{"on" if k == depth_now else ""}" '
                               f'aria-checked="{str(k == depth_now).lower()}">{v}</button>' for k, v in askconfig.DEPTHS.items()) + "</form>")
        depth_row = _row("Answer depth", "Short: a few lines, fewest tokens. Normal: a proper answer. Deep: thorough research, long answers, "
                         "more searches. Deeper answers use more of your plan.", depth_bar)
        used = self.store.ask_usage_since(askconfig.periods(self.store._now())["day"])
        total = sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in used)
        today = _row("Used today", (f"{askconfig.compact(total)} tokens" if used else "Nothing yet") + '. <a class="link" href="#usage">See more</a>', cls="small")
        return _group("Answers", depth_row + web_row + today, gid="answers")

    def _ask_model(self) -> str:
        from magpiary.hub_settings import _group, _row

        engine = self.ask_engine()
        if engine is not None and engine["id"] == "codex":
            model = askconfig.codex_model(self.store)
            options = "".join(f'<option value="{m}"{" selected" if m == model else ""}>{e(n)}</option>' for m, n in askconfig.CODEX_MODELS.items())
            efforts = "".join(f'<option value="{k}"{" selected" if k == askconfig.codex_effort(self.store) else ""}>{v}</option>'
                              for k, v in askconfig.CODEX_EFFORTS.items())
            form = (f'<form method="post" action="/hub/askset" class="inlineform" data-autosubmit>{ui.hidden(self.csrf, next=BACK)}'
                    f'<label>Model <select name="cmodel">{options}</select></label> '
                    f'<label>Effort <select name="ceffort">{efforts}</select></label></form>')
            return _group("Model and thinking", _row("Model and effort", "Luna at medium effort is the default: quick and light on your "
                                                     "plan. Effort stops at medium here on purpose.", form), gid="model")
        if engine is None or engine["id"] != "claude":
            note = _row("Model", "A key answers with the model set on that key (AI & login → AI keys).",
                        '<a class="btn sm" href="/settings/ai#keys">Open keys</a>')
            return _group("Model and thinking", note, gid="model")
        model = askconfig.claude_model(self.store)
        options = "".join(f'<option value="{m}"{" selected" if m == model else ""}>{e(name)}</option>' for m, name in askconfig.CLAUDE_MODELS.items())
        efforts = "".join(f'<option value="{k}"{" selected" if k == askconfig.claude_effort(self.store) else ""}>{v}</option>'
                          for k, v in askconfig.EFFORTS.items())
        form = (f'<form method="post" action="/hub/askset" class="inlineform" data-autosubmit>{ui.hidden(self.csrf, next=BACK)}'
                f'<label>Model <select name="model">{options}</select></label> '
                f'<label>Effort <select name="effort">{efforts}</select></label></form>')
        rows = (_row("Model and effort", "Haiku 5.5 at medium effort is the default: quick and light on your plan. Higher effort thinks "
                     "longer and uses more tokens.", form))
        return _group("Model and thinking", rows, gid="model")

    def _ask_usage(self) -> str:
        from magpiary.hub_settings import _group, _more, _row

        show = self._switch("/hub/askset", askconfig.show_tokens(self.store), {"tokens": "0", "next": BACK}, {"tokens": "1", "next": BACK},
                            "Show tokens")
        starts = askconfig.periods(self.store._now())
        tiles = []
        for period, name in (("day", "Today"), ("week", "This week"), ("month", "This month")):
            used = self.store.ask_usage_since(starts[period])
            total = sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in used)
            qs = sum(int(r["questions"]) for r in used)
            if not used:
                tiles.append(f'<div class="au"><small>{name}</small><b class="none">Nothing yet</b></div>')
                continue
            who = "".join(f'<li><span>{e(r["engine"].title())}</span>{askconfig.compact(int(r["tokens_in"]) + int(r["tokens_out"]))}</li>' for r in used)
            ins, outs = sum(int(r["tokens_in"]) for r in used), sum(int(r["tokens_out"]) for r in used)
            tiles.append(f'<div class="au"><small>{name}</small><b>{askconfig.compact(total)}<i> tokens</i></b>'
                         f'<p>{qs} question{"" if qs == 1 else "s"} · {askconfig.compact(ins)} in · {askconfig.compact(outs)} out</p>'
                         f'<ul>{who}</ul></div>')
        preset, period, warn = askconfig.limit_preset(self.store), askconfig.limit_period(self.store), askconfig.warn_on(self.store)

        def seg(items: list[tuple[str, str, str, bool]], field: str, label: str, small: bool = False) -> str:
            buttons = "".join(
                f'<form method="post" action="/hub/askset">{ui.hidden(self.csrf, next=BACK, **{field: k})}<button type="submit" '
                f'class="seg-b{" on" if on else ""}" aria-pressed="{str(on).lower()}"><b>{e(name)}</b>' + (f"<small>{e(sub)}</small>" if sub else "") + "</button></form>"
                for k, name, sub, on in items)
            return f'<div class="askseg{" small" if small else ""}" role="group" aria-label="{e(label)}">{buttons}</div>'
        per = seg([(k, name, "", k == period) for k, name in (("day", "Per day"), ("month", "Per month"))], "period", "Count per day or per month", True)
        mult = 30 if period == "month" else 1
        levels = seg([(k, name, "" if not q else f"{q * mult} a {period}", k == preset) for k, (name, q) in askconfig.LIMITS.items()],
                     "limit", "How many questions are plenty")
        toggle = self._switch("/hub/askset", warn, {"warn": "0", "next": BACK}, {"warn": "1", "next": BACK}, "Warn me at the limit")
        limits = (f'<div class="asklim{"" if warn else " off"}"><div class="asklimrow"><span>Count</span>{per}</div>'
                  f'<div class="asklimrow"><span>Limit</span>{levels}</div>'
                  f'<p class="askhow">{e("Warns you at " + askconfig.limit_words(self.store) + "." if warn and askconfig.limit(self.store) else "No warning will show." if not warn else "No limit is set.")}</p></div>')
        rows = (_row("Used so far", f'<div class="askuse">{"".join(tiles)}</div>', cls="askuse-row")
                + _row("Show tokens under each answer", "A small line like “2.1k in · 340 out”.", show)
                + _row("Warn me at a limit", "Tell me before sending once I have used about this much. Nothing is blocked; one tap goes on.", toggle)
                + (_row("How much is plenty", "", limits, cls="askpreset-row rstack") if warn else ""))
        return _group("Tokens", rows, gid="usage",
                      more=_more("<p>Tokens are the pieces of text the AI reads and writes. “In” counts what it read for the first time; "
                                 "text it re-reads from its own memory while working is far cheaper and not counted. On a Claude or "
                                 "ChatGPT plan there is no price per answer, only your plan's allowance, so Magpiary shows tokens. A key's "
                                 "provider bills by tokens, so the same numbers show what a key costs.</p>"))

    def ask_can_answer(self) -> str:
        """"" when Ask has someone to answer it, else why not, in plain words."""
        from magpiary import ask as asking
        from magpiary import modes

        if modes.current(self.store) != "smart":
            return "Ask Magpiary needs an AI, and you are in Private mode. Switch to Smart under AI & login first."
        state = self._claude_state() if asking.claude_available() else {"installed": False, "signed_in": False}
        if state["installed"] and state["signed_in"] is not False:
            return ""
        from magpiary import ask_codex

        if keyring.usable() or ask_codex.available():
            return ""
        return ("Ask Magpiary needs an AI to answer. Sign in to Claude Code or Codex on this Mac, or add an AI key under AI & login, "
                "then turn it on.")

    def askset_post(self, form: dict):
        """Every change on the Ask Magpiary tab. Returns a redirect back to the tab, with a message when something was refused."""
        from magpiary.web import Response
        from urllib.parse import quote

        s = self.store
        if form.get("on") == "1":
            why = self.ask_can_answer()
            if why:
                return Response(303, b"", headers={"Location": f"{BACK}?error={quote(why)}"})
            from magpiary import engines

            engines.set_on(s, "ask", True)
        elif form.get("on") == "0":
            from magpiary import engines

            engines.set_on(s, "ask", False)
            self.ask_stop_all()  # an answer being written stops; open panels close themselves on their next check
        from magpiary import ask_setup

        if form.get("setup") in ask_setup.ENGINES:  # install it if needed and open its sign-in page; it becomes the active one
            askconfig.set_removed(s, form["setup"], False)
            s.set_setting(askconfig.ENGINE, form["setup"])
            self._claude_cache = None
            ask_setup.start(form["setup"])
        for gone in (form.get("deactivate"), form.get("remove")):
            if gone in ("claude", "codex", "key"):
                if gone != "key" and form.get("remove") == gone:
                    askconfig.set_removed(s, gone, True)
                if (self.ask_engine() or {}).get("id") == gone or s.get_setting(askconfig.ENGINE, "") == gone:
                    for other in (x for x in ("claude", "codex", "key") if x != gone):  # the next one that can answer, else nobody
                        s.set_setting(askconfig.ENGINE, other)
                        if self.ask_engine() is not None:
                            break
                    else:
                        s.set_setting(askconfig.ENGINE, "none")
        if form.get("engine") in ("claude", "codex", "key"):
            s.set_setting(askconfig.ENGINE, form["engine"])
            if form["engine"] == "key" and form.get("key"):
                s.set_setting(askconfig.KEY, form["key"][:40])
        if form.get("model") in askconfig.CLAUDE_MODELS:
            s.set_setting(askconfig.CLAUDE_MODEL, form["model"])
        if form.get("cmodel") in askconfig.CODEX_MODELS:
            s.set_setting(askconfig.CODEX_MODEL, form["cmodel"])
        if form.get("ceffort") in askconfig.CODEX_EFFORTS:
            s.set_setting(askconfig.CODEX_EFFORT, form["ceffort"])
        if form.get("effort") in askconfig.EFFORTS:
            s.set_setting(askconfig.CLAUDE_EFFORT, form["effort"])
        if form.get("web") in ("0", "1"):
            s.set_setting(askconfig.WEB, form["web"])
        if form.get("depth") in askconfig.DEPTHS:
            s.set_setting(askconfig.DEPTH, form["depth"])
        if form.get("warn") in ("0", "1"):
            s.set_setting(askconfig.WARN, form["warn"])
        if form.get("tokens") in ("0", "1"):
            s.set_setting(askconfig.SHOW_TOKENS, form["tokens"])
        if form.get("limit") in askconfig.LIMITS:
            s.set_setting(askconfig.LIMIT, form["limit"])
        if form.get("period") in ("day", "month"):
            s.set_setting(askconfig.LIMIT_PERIOD, form["period"])
        back = form.get("next", "")
        return Response(303, b"", headers={"Location": back if back.startswith("/ask?scope=") and "\n" not in back else BACK})
