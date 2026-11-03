"""The Nest (M7a, C1+; redesigned 24 Oct), mixed into Hub: everything Magpiary is doing, has done and needs from you.
It drops down from its own button with a short look (`/nest?frag=1`); `/nest?tab=now|needs|stats|phones` is the
full page, and `/queue` (every delivery) is its "From your phones" tab.

Built to hold up with long queues: lists are capped and scroll, titles clamp, and counts stay in view."""

from datetime import date

from magpiary import keys as keyring
from magpiary import modes, ui
from magpiary.activity import label_for
from magpiary.queuepage import REASONS
from magpiary.web import Response, e

AI_REASONS = {"busy": "the AI was busy", "no_key": "no AI key yet", "bad_key": "the key was refused",
              "rate_limited": "the AI's limit was reached", "blocked": "the AI declined this post",
              "invalid": "the AI's answer was not usable", "unknown": "something went wrong"}
FLOW = ("fetch", "download", "transcribe", "frames", "summary")
FLOW_NAMES = {"fetch": "Fetch", "download": "Save", "transcribe": "Listen", "frames": "Look", "summary": "Write"}
FLOW_COLOURS = {"fetch": "var(--t-howto)", "download": "var(--t-explainer)", "transcribe": "var(--t-discussion)",
                "frames": "var(--t-tool)", "summary": "var(--t-design)"}
CONTROLS = (
    (
        "transcribe",
        "Transcribing",
        "On this Mac, free. Whisper listens to each video using the Mac's chip, not the internet.",
    ),
    (
        "summary",
        "Summarising",
        "Sends the caption, transcript and a few frames to your AI key. The video never leaves this Mac.",
    ),
    (
        "links",
        "Finding links",
        "Free directories first (GitHub, App Store, Wikipedia, OpenStreetMap), then Brave Search if you added a key.",
    ),
)

# the magpie, asleep on its nest: shown when everything is quiet
SLEEPY = ('<svg class="nestart" viewBox="0 0 160 110" aria-hidden="true"><path d="M18 78q62 18 124 0q-8 30-62 30T18 78z" '
          'fill="currentColor" opacity=".16"/><path d="M28 84q52 12 104 0M40 93q40 8 80 0" stroke="currentColor" opacity=".28" '
          'fill="none" stroke-width="2.5" stroke-linecap="round"/><ellipse cx="82" cy="62" rx="27" ry="18" fill="currentColor"/>'
          '<path d="M104 58q22-8 36-26q-6 22-24 34z" fill="currentColor"/><circle cx="60" cy="50" r="13" fill="currentColor"/>'
          '<path d="M47 51l-12 4 12 2z" fill="currentColor"/><path d="M54 48q4 3 8 0" stroke="var(--card)" stroke-width="2.4" '
          'fill="none" stroke-linecap="round"/><path d="M68 66q14 8 28 2" stroke="var(--card)" stroke-width="3.5" fill="none" '
          'stroke-linecap="round"/><text x="104" y="28" font-size="14" font-weight="700" fill="var(--t-howto)" '
          'font-family="var(--display)">z</text><text x="116" y="16" font-size="11" font-weight="700" fill="var(--t-howto)" '
          'opacity=".7" font-family="var(--display)">z</text></svg>')


class NestPages:
    """Needs Hub's store, activity, csrf, shell, _form and thumb_url; `keep_awake` when the service has one."""

    def _thumb_box(self, item: dict | None, cls: str = "th") -> str:
        if not item:
            return f'<span class="{cls}"></span>'
        thumb = self.thumb_url(item)
        if not thumb:  # nothing to show yet: the platform's own mark, flat, instead of a coloured square
            return f'<span class="{cls} logo" style="background:{ui.gradient(item)}">{ui.source_logo(item["source"])}</span>'
        return (f'<span class="{cls}" style="background:{ui.gradient(item)}">'
                f'<img loading="lazy" decoding="async" src="{e(thumb)}" alt=""></span>')

    def nest_shell(self) -> str:
        """The drop-down the Nest opens in from its button."""
        return ('<aside class="nestsheet" id="nestsheet" role="dialog" aria-modal="false" aria-label="The nest" hidden>'
                '<div class="nsin" id="nsin"></div></aside>')

    def nest_status(self, snap: dict | None = None) -> tuple[str, str]:
        """(mood, one line): working, waiting, paused, needs or quiet."""
        snap = snap or self.activity.snapshot()
        needs = len(self.store.problems())
        lanes, waiting = snap["lanes"], snap["waiting_total"]
        if lanes:
            line = f"Reading {len(lanes)}" + (f" · {waiting} waiting" if waiting else "")
            return "working", line
        if needs:
            return "needs", f"{needs} need{'s' if needs == 1 else ''} you"
        if waiting and snap["paused_any"]:
            return "paused", f"Paused · {waiting} waiting"
        if waiting:
            return "waiting", f"{waiting} waiting"
        return "quiet", "All quiet"

    def lanes_html(self, lanes: list[dict]) -> str:
        """One card per lane: picture, title, the five steps in colour, and how far along it is."""
        cards = []
        for l in lanes:
            item = self.store.item_by_id(l["item_id"])
            at = FLOW.index(l["step"]) if l["step"] in FLOW else -1
            steps = "".join(
                f'<span class="fs {"d" if n < at else "r" if n == at else ""}" style="--c:{FLOW_COLOURS[s]}">'
                f'{ui.icon(s)}<em>{FLOW_NAMES[s]}</em></span>' for n, s in enumerate(FLOW))
            pct = l.get("percent")
            bar = (f'<div class="lbar"><i style="width:{int(pct)}%"></i></div>' if pct is not None
                   else '<div class="lbar ind"><i></i></div>')
            cards.append(f'<a class="lane" href="/item/{l["item_id"]}">{self._thumb_box(item, "lth")}<span class="lbody">'
                         f'<small>{e(l["lane_label"])} lane · {e(l["step_label"])}{f" · {int(pct)}%" if pct is not None else ""}'
                         f' · {ui.secs(l["seconds"])}</small><b>{e(l["label"][:140])}</b><span class="flow">{steps}</span>'
                         f'{bar}</span></a>')
        return "".join(cards)

    NEST_TABS = {"now": "Now", "needs": "Needs you", "stats": "Stats", "phones": "From your phones"}

    def _nest_head(self, mood: str, line: str) -> str:
        moods = {"working": ("Busy as a magpie", "Your Mac is reading what you shared."),
                 "needs": ("A few need you", "Magpiary couldn't finish these by itself."),
                 "paused": ("Paused", "Nothing is being read until you resume."),
                 "waiting": ("Starting soon", "Shares are lined up and will be read in turn."),
                 "quiet": ("All quiet", "Everything you shared has been read. Share something from your phone.")}
        title, sub = moods[mood]
        return (f'<div class="nhead {mood}"><div class="nh-txt"><span class="nh-k">The nest</span><h2>{e(title)}</h2>'
                f'<p>{e(sub)}</p><span class="nh-line" data-nline>{e(line)}</span></div>'
                + (SLEEPY if mood == "quiet" else f'<div class="nh-ico">{ui.icon("activity", "ico nesti")}</div>') + "</div>")

    def _nest_row(self, i: dict, note: str, cls: str = "") -> str:
        return (f'<a class="nrow {cls}" href="/item/{i["id"]}">{self._thumb_box(i)}<span class="nr-t"><b>'
                f'{e(label_for(i)[:120])}</b><small>{e(note)}</small></span>{ui.icon("chev", "ico chev")}</a>')

    def _nest_needs(self, problems: list[dict], shown: int, more_href: str) -> str:
        if not problems:
            return ""
        rows = "".join(self._nest_row(p, REASONS.get(p["reason"] or "", "Couldn't open it") if p["status"] == "needs_attention"
                                      else "Summary: " + AI_REASONS.get(p.get("ai_reason") or "", "a problem"), "bad")
                       for p in problems[:shown])
        more = (f'<a class="nmore" href="{more_href}">and {len(problems) - shown} more →</a>' if len(problems) > shown else "")
        return (f'<section class="nsec need"><h3>{ui.icon("alert")} Needs you <span class="cnt">{len(problems)}</span></h3>'
                f'<div class="nlist">{rows}</div>{more}</section>')

    def _nest_waiting(self, snap: dict, shown: int, more_href: str) -> str:
        n_fetch, n_read = snap["waiting"]["fetch"], snap["waiting"]["process"]
        if not (n_fetch or n_read):
            return ""
        waiting = self.store.waiting_items(limit=shown)
        items = waiting["fetch"] + waiting["process"]
        rows = "".join(self._nest_row(i, "to be read" if i["status"] == "archived" else "to be fetched") for i in items[:shown])
        more_n = n_fetch + n_read - min(len(items), shown)
        why = modes.waiting_reason(self.store, keyring)
        return (f'<section class="nsec"><h3>{ui.icon("clock")} Waiting <span class="cnt">{n_fetch + n_read}</span></h3>'
                f'<div class="wchips"><span style="--c:var(--t-howto)">{ui.icon("fetch")} {n_fetch} to fetch</span>'
                f'<span style="--c:var(--t-design)">{ui.icon("summary")} {n_read} to read</span></div>'
                f'<div class="nlist">{rows}</div>'
                + (f'<a class="nmore" href="{more_href}">and {more_n} more →</a>' if more_n > 0 else "")
                + (f'<p class="nwhy">{e(why)} <a class="link" href="/settings/ai">Settings</a></p>' if why else "")
                + "</section>")

    def _nest_refresh(self, back: str) -> str:
        """The slow stats refresh, only when something is waiting or it is paused: how many, and a Pause / Resume."""
        queued = self.store.stats_queue_counts()
        total, paused = sum(queued.values()), self.store.paused("stats")
        if not total and not paused:
            return ""
        names = ", ".join(f"{n} {ui.source_name(src)}" for src, n in sorted(queued.items(), key=lambda kv: -kv[1]))
        line = (f"{total} post{'' if total == 1 else 's'} waiting ({e(names)}). Spread out on purpose, a limited number a day per site, "
                "so the sites do not mistake this Mac for a robot." if total else "Nothing is waiting.")
        flip = "resume" if paused else "pause"
        return (f'<div class="nstats"><span class="nsi">{ui.icon("refresh")}</span><div><b>Refreshing stats{" · paused" if paused else ""}</b>'
                f'<small>{line}</small></div><form method="post" action="/hub/control">{ui.hidden(self.csrf, part="stats", action=flip, next=back)}'
                f'<button class="btn sm" type="submit">{"Resume" if paused else "Pause"}</button></form></div>')

    def _nest_switches(self, back: str) -> str:
        budget = self.store.summary_budget()
        toggles = []
        for part, name, what in CONTROLS:
            paused = self.store.paused(part)
            limit = part == "summary" and not paused and budget != "all" and not budget.strip("0")
            off = paused or limit
            state = "Paused" if paused else "Limit reached" if limit else "Running"
            if part == "summary" and modes.current(self.store) == "private":
                state, what = "Private mode", "Switch to Smart in Settings to have your AI key write summaries."
            toggles.append(
                f'<form method="post" action="/hub/control">{ui.hidden(self.csrf, part=part, action="resume" if off else "pause", next=back)}'
                f'<button class="tgl" type="submit" aria-pressed="{str(not off).lower()}" title="{e(what)}">'
                f'<span class="tgt"><b>{name}</b><small>{e(state)}</small></span><span class="tg{" off" if off else ""}"></span></button></form>')
        awake = getattr(getattr(self, "keep_awake", None), "running", False)
        toggles.append(
            f'<form method="post" action="/hub/awake">{ui.hidden(self.csrf, enabled="0" if awake else "1", next=back)}'
            f'<button class="tgl" type="submit" aria-pressed="{str(awake).lower()}" title="Only while plugged in, so shares '
            f'arrive and are read overnight. A closed lid still sleeps."><span class="tgt"><b>Keep awake</b><small>{"On" if awake else "Off"}</small></span>'
            f'<span class="tg{"" if awake else " off"}"></span></button></form>')
        limited = budget != "all"
        count = budget if limited and budget.strip("0") else "2"
        limit = ""
        if back.startswith("/nest?") and modes.current(self.store) != "private":
            # how many summaries to write before pausing (moved here from Settings, owner's decision 24 Oct 2026)
            limit = (f'<form method="post" action="/hub/settings/budget" class="nlimit">{ui.hidden(self.csrf, next=back)}'
                     f'<span class="nlab">Summarise</span><span class="seg">'
                     f'<button type="submit" name="mode" value="all" class="{"" if limited else "on"}" aria-pressed="{str(not limited).lower()}">All posts</button>'
                     f'<button type="submit" name="mode" value="next" class="{"on" if limited else ""}" aria-pressed="{str(limited).lower()}">Only the next</button>'
                     f'</span><input type="number" name="count" min="1" max="1000" value="{e(count)}" aria-label="How many">'
                     f'<span class="nlab">then pause</span></form>')
        return (f'<section class="nsec"><h3>{ui.icon("moon")} Switches</h3><div class="tgrow">{"".join(toggles)}</div>{limit}'
                + (f'<p class="nwhy">Summaries stop after {e(budget)} more.</p>'
                   if budget not in ("all",) and budget.strip("0") else "") + "</section>")

    def _nest_today(self, snap: dict) -> str:
        today = date.today().isoformat()
        items = self.store.items()
        saved = sum((i.get("created_at") or "").startswith(today) for i in items)
        read = sum((i.get("processed_at") or "").startswith(today) for i in items)
        tiles = [("saved today", saved, "var(--t-howto)", "phone"), ("read today", read, "var(--t-design)", "summary"),
                 ("in your library", len(items), "var(--t-explainer)", "library"),
                 ("to fetch", snap["waiting"]["fetch"], "var(--t-discussion)", "fetch")]
        return (f'<section class="nsec"><h3>{ui.icon("sparkle")} Today</h3><div class="ntiles">'
                + "".join(f'<div class="ntile" style="--c:{c}">{ui.icon(ic)}<b>{n}</b><span>{label}</span></div>'
                          for label, n, c, ic in tiles) + "</div></section>")

    def _nest_stats(self) -> str:
        recent = self.store.recent_finished(50)
        if not recent:
            return '<p class="nwhy">Nothing has been read yet, so there is nothing to time.</p>'
        sums: dict = {}
        for r in recent:
            bucket = sums.setdefault(ui.source_name(r["source"]), {s: [] for s in [*FLOW, "total"]})
            for s in FLOW:
                if s in r["timings"]:
                    bucket[s].append(r["timings"][s])
            bucket["total"].append(sum(r["timings"].values()))
        head_row = "".join(f"<th>{e(FLOW_NAMES[s])}</th>" for s in FLOW)
        avg = "".join(f"<tr><td>{e(src)} <span class='muted'>({len(v['total'])})</span></td>"
                      + "".join(f"<td>{ui.secs(sum(v[s]) / len(v[s])) if v[s] else '–'}</td>" for s in [*FLOW, "total"]) + "</tr>"
                      for src, v in sorted(sums.items()))
        last = "".join(f'<tr><td><a href="/item/{r["id"]}">{e(label_for(r)[:48])}</a></td>'
                       + "".join(f"<td>{ui.secs(r['timings'].get(s))}</td>" for s in FLOW)
                       + f"<td>{ui.secs(sum(r['timings'].values()))}</td></tr>" for r in recent[:15])
        return (f'<section class="nsec"><h3>{ui.icon("clock")} Average per step <span class="cnt">last {len(recent)}</span></h3>'
                f'<div class="panel tscroll"><table class="avg"><tr><th>Source</th>{head_row}<th>Total</th></tr>{avg}</table></div></section>'
                f'<section class="nsec"><h3>{ui.icon("check")} Recently finished</h3><div class="panel tscroll"><table class="avg">'
                f'<tr><th>Post</th>{head_row}<th>Total</th></tr>{last}</table></div>'
                f'<p class="nwhy">Total is the time Magpiary spent on a post; waiting in line is not counted.</p></section>')

    def nest_body(self) -> str:
        """The drop-down: a short look at what is happening; everything longer is a link to the Nest page."""
        snap = self.activity.snapshot()
        mood, line = self.nest_status(snap)
        now = (f'<section class="nsec"><h3>{ui.icon("sparkle")} Working on now</h3>'
               f'<div class="lanes" id="lanes">{self.lanes_html(snap["lanes"])}</div></section>' if snap["lanes"] else "")
        foot = (f'<nav class="nfoot"><a class="nopen" href="/nest">Open the Nest {ui.icon("ext")}</a>'
                f'<a href="/nest?tab=stats">{ui.icon("stats")} Stats</a>'
                '<a class="nflat" href="/nest?tab=phones">From your phones</a></nav>')
        return (f'<div class="nest2 {mood}" data-mood="{mood}">{self._nest_head(mood, line)}{now}'
                f'{self._nest_needs(self.store.problems(), 3, "/nest?tab=needs")}'
                f'{self._nest_waiting(snap, 3, "/nest")}{self._nest_switches("/")}{self._nest_refresh("/")}{self._nest_today(snap)}{foot}</div>')

    def nest_page(self, fragment: bool = False, tab: str = "now") -> Response:
        if fragment:
            return Response(200, self.nest_body().encode(), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        tab = tab if tab in self.NEST_TABS else "now"
        snap = self.activity.snapshot()
        mood, line = self.nest_status(snap)
        problems = self.store.problems()
        back = f"/nest?tab={tab}"
        if tab == "needs":
            failed = sum(1 for i in self.store.items() if i.get("ai_status") == "needs_attention")
            again = (f'<div class="nagain"><p><b>{failed} summar{"y" if failed == 1 else "ies"} had a problem.</b> Busy or '
                     f'refused answers are retried by themselves; these are what was left.</p>'
                     + self._form("/hub/settings/again-all", {"next": "/nest?tab=needs"}, "Try them all again", "btn sm dark")
                     + "</div>") if failed else ""
            body = again + (self._nest_needs(problems, 200, "/?attention=1") or
                    '<div class="empty"><b>Nothing needs you</b><p>Every share was opened and read.</p></div>')
        elif tab == "stats":
            body = self._nest_today(snap) + self._nest_stats()
        elif tab == "phones":
            from magpiary.queuepage import table
            summary, rows = table(self.store, self.csrf)
            body = f'<p class="nwhy">{e(summary)}</p><div class="panel tscroll">{rows}</div>'
        else:
            now = (f'<section class="nsec"><h3>{ui.icon("sparkle")} Working on now</h3>'
                   f'<div class="lanes" id="lanes">{self.lanes_html(snap["lanes"])}</div></section>' if snap["lanes"] else "")
            body = now + self._nest_waiting(snap, 60, "/nest?tab=phones") + self._nest_switches(back) + self._nest_refresh(back) + self._nest_today(snap)
        tabs = "".join(f'<a href="/nest?tab={k}" class="{"on" if k == tab else ""}"'
                       f'{" aria-current=page" if k == tab else ""}>{v}'
                       + (f' <b class="cnt">{len(problems)}</b>' if k == "needs" and problems else "") + "</a>"
                       for k, v in self.NEST_TABS.items())
        page = (f'<div class="nestpage"><div class="nest2 {mood}" data-mood="{mood}">{self._nest_head(mood, line)}'
                f'<nav class="ntabs" aria-label="The nest">{tabs}</nav><div id="ntbody">{body}</div></div></div>')
        return self.shell("Nest", page, "nest", active="nest")

    def deliveries_page(self) -> Response:
        """Every share as it arrived: the Nest page's "From your phones" tab."""
        return self.nest_page(tab="phones")
