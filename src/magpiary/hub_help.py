"""The help column (owner's decision, 24 Oct 2026), mixed into Hub. On Settings it is the third column, for the open
section; everywhere else the top bar's "?" opens it as a panel for that page. Top to bottom: live status, guides and FAQs
for the topic, and What's new once after an update. /help has every topic."""

from datetime import date, datetime

from magpiary import help as helptext
from magpiary import keys as keyring
from magpiary import login, ui
from magpiary.web import Response, e

STARTED = datetime.now()  # when this copy of the service started
SEEN = "seen_version"      # the version whose What's new was last seen
HEALTH = "health_last"     # "when|problems|warnings" from the last health check


def topic_for(page: str, section: str = "") -> str:
    if page == "settings":
        return section if section in helptext.TOPICS else "ai"
    return helptext.PAGE_TOPIC.get(page, "start")


def _since(stamp: datetime) -> str:
    mins = int((datetime.now() - stamp).total_seconds() // 60)
    if mins < 60:
        return f"{mins} min" if mins else "just now"
    hours = mins // 60
    return f"{hours} h" if hours < 48 else f"{hours // 24} days"


class HelpPages:
    """Needs Hub's store, csrf, shell, _form, activity and nest_status."""

    def help_column(self, topic: str, panel: bool = False) -> str:
        """The calm column on Settings, or (panel) the sheet from Help at the bottom right: a plain header (owner, 29 Oct)."""
        title = helptext.TOPICS[topic]["title"]
        colour, icon, blurb = helptext.LOOK[topic]
        close = '<button type="button" class="hclose" data-hclose aria-label="Close help">×</button>' if panel else ""
        acts = (f'<div class="hacts"><a class="hbtn" href="/help">All help {ui.icon("ext")}</a>'
                f'<a class="hbtn" href="/doctor">{ui.icon("health")} Run a health check</a></div>')
        head = (f'<header class="hcard"><span class="hic">{ui.icon(icon)}</span><div class="htx"><small>Help</small><b>{e(title)}</b>'
                f'<p>{e(blurb)}</p>{acts}</div>{close}</header>' if panel
                else '<h2 class="hplain">Help</h2>')  # on Settings the page already names the section (owner, 26 Oct)
        foot = ('<nav class="hfoot"><a href="/help">All help →</a><a href="/doctor">Run a health check</a></nav>' if panel
                else '<a class="hall" href="/help">All help →</a>')
        return (f'<div class="hwrap {"hdrop" if panel else "hcol"}" style="--c:{colour}">{head}'
                + self._help_topic(topic, compact=True) + ("" if panel else foot) + self._whats_new()
                + self._help_status(topic) + "</div>")

    # ---- live status ------------------------------------------------------------------------

    def _help_status(self, topic: str) -> str:
        from magpiary import __version__
        from magpiary.update import LATEST_SETTING, newer

        rows = []
        today = date.today().isoformat()
        if topic == "ai":
            items = self.store.items()
            rows.append(("Read today", str(sum((i.get("processed_at") or "").startswith(today) for i in items))))
            for k in keyring.load():
                if keyring.PROVIDERS[k.provider]["kind"] != "ai":
                    continue
                state = ("Refused" if k.refused else "Limit reached" if k.limit_day == today else "Ready")
                rows.append((k.name, state))
        elif topic == "phones":
            phones = [p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]
            last = self.store.last_delivery()
            awake = getattr(getattr(self, "keep_awake", None), "running", False)
            rows += [("Phones paired", str(len(phones))), ("Last delivery", ui.day(last) if last else "None yet"),
                     ("Keep awake", "On" if awake else "Off")]
        elif topic == "links":
            from magpiary.worker import SEARCH_LIMIT, searches_used

            has_search = any(keyring.PROVIDERS[k.provider]["kind"] == "search" for k in keyring.load())
            rows.append(("Web search", f'{searches_used(self.store)} of {self.store.get_setting("search_limit", str(SEARCH_LIMIT))} '
                                       f'this month' if has_search else "Off (no key)"))
            rows.append(("Instagram login", "Connected" if login.connected(self.store) else "Not connected"))
        elif topic in ("storage", "library"):
            counts = self.store.hub_counts()["shelves"]
            rows += [("Library", str(counts.get("inbox", 0))), ("Archive", str(counts.get("archive", 0))),
                     ("Trash", str(counts.get("trash", 0)))]
        mood, line = self.nest_status()
        rows.append(("Activity", line))
        health = self.store.get_setting(HEALTH, "").split("|")
        if len(health) == 3:
            problems, warnings = int(health[1] or 0), int(health[2] or 0)
            rows.append(("Health check", (f"{problems} problem{'s' if problems != 1 else ''}" if problems else
                                          f"{warnings} warning{'s' if warnings != 1 else ''}" if warnings else "All good")
                         + f" · {ui.day(health[0])}"))
        else:
            rows.append(("Health check", "Not run yet"))
        waiting = self.store.get_setting(LATEST_SETTING, "")
        rows.append(("Magpiary", f"{__version__}" + (f" · {waiting} available" if newer(waiting) else " · up to date")))
        rows.append(("Running for", _since(STARTED)))
        return ('<section class="hblock hnow"><h4>Right now</h4><div class="htiles">'
                + "".join(f'<div class="ht" title="{e(a)}: {e(b)}"><small>{e(a)}</small><b>{e(b)}</b></div>' for a, b in rows) + "</div></section>")

    # ---- guides and FAQs --------------------------------------------------------------------

    def _help_topic(self, topic: str, compact: bool = False) -> str:
        t = helptext.TOPICS[topic]
        guides = "".join(
            f'<details class="hguide hitem" style="--g:{helptext.GUIDE_TINTS[n % len(helptext.GUIDE_TINTS)]}"><summary>'
            f'<span class="gic">{ui.icon(helptext.GUIDE_ICONS.get(title, "book"))}</span><span class="gt"><b>{e(title)}</b>'
            f'<span>{e(line)}</span></span><em>{len(steps)} steps</em></summary>'
            f'<ol class="hsteps">{"".join(f"<li><span>{e(s)}</span></li>" for s in steps)}</ol></details>'
            for n, (title, line, steps) in enumerate(t["guides"]))
        faqs = "".join(f'<details class="hfaq hitem"><summary>{e(q)}</summary><p>{e(a)}</p></details>' for q, a in t["faqs"])
        colour, icon, _ = helptext.LOOK[topic]
        head = ("" if compact else f'<h3 id="t-{topic}" style="--c:{colour}"><span class="hic">{ui.icon(icon)}</span>'
                                   f'{e(t["title"])}</h3>')
        return (f'<section class="hblock htopic" data-topic="{topic}">{head}'
                + (f'<h4>Guides</h4><div class="hguides">{guides}</div>' if guides else "")
                + (f'<h4>Questions</h4><div class="hfaqs">{faqs}</div>' if faqs else "") + "</section>")

    # ---- What's new, once after an update -------------------------------------------------------

    def _whats_new(self) -> str:
        from magpiary import __version__
        from magpiary.update import parse

        seen = self.store.get_setting(SEEN, "")
        if not seen:
            self.store.set_setting(SEEN, __version__)  # a first install has nothing "new"
            return ""
        if seen == __version__:
            return ""
        fresh = [(v, lines) for v, lines in helptext.CHANGES if parse(v) > parse(seen)]
        if not fresh:
            return ""
        items = "".join(f'<li><b>{e(v)}</b> {e(line)}</li>' for v, lines in fresh for line in lines)
        return (f'<section class="hblock hnew"><h4>What\'s new</h4><ul>{items}</ul>'
                + self._form("/hub/whatsnew/seen", {"next": "/settings"}, "Got it", "btn sm") + "</section>")

    # ---- the /help page, and the panel's content --------------------------------------------------

    def help_page(self, q: dict) -> Response:
        if q.get("frag") == "1":
            topic = topic_for(q.get("ctx", ""), q.get("section", ""))
            return Response(200, self.help_column(topic, panel=True).encode(),
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        chips = "".join(f'<a class="fchip" href="#t-{k}">{e(t["title"])}</a>' for k, t in helptext.TOPICS.items())
        topics = "".join(self._help_topic(k) for k in helptext.TOPICS)
        body = (f'<div class="helppage"><div class="hero hhero"><div><h1>Help</h1><p>Guides and answers for every part of Magpiary.'
                f'</p></div><a class="hbtn" href="/doctor">{ui.icon("health")} Run a health check</a></div><label class="hsearch">{ui.icon("search")}<input type="search" id="helpq" placeholder="Search the help" '
                f'aria-label="Search the help" autocomplete="off"></label><nav class="hchips">{chips}</nav>'
                f'<p class="hnone" hidden>Nothing matches. Try another word.</p>{self.checklist_replay()}{topics}</div>')
        return self.shell("Help", body, "help")

    def help_post(self, path: str, form: dict) -> bool:
        if path == "/hub/whatsnew/seen":
            from magpiary import __version__

            self.store.set_setting(SEEN, __version__)
            return True
        return False

    def help_shell(self) -> str:
        """The panel the top bar's "?" opens, outside Settings."""
        return ('<aside class="helpsheet" id="helpsheet" role="dialog" aria-modal="false" aria-label="Help" hidden>'
                '<div class="hsin" id="hsin"></div></aside>')

    @staticmethod
    def health_stamp(problems: int, warnings: int) -> str:
        return f"{datetime.now().isoformat(timespec='minutes')}|{problems}|{warnings}"
