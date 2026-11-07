"""Settings (M7a, C1+, redesigned 24 Oct and 1 Nov 2026), mixed into Hub. The sections are listed on the left under small
headings; the open one is on the right as groups of rows: Your profile (with private goals), Phone (sending and opening the library), AI & login (Smart or Private, keys in order, the digest, finding links,
the opt-in Instagram login), Ask Magpiary, AI agents, Shared
boards, Appearance, Library & this Mac (folders, backup, Trash, keep awake, the health check), and Privacy (what leaves the Mac,
where data lives, deleting it)."""

import html
import json
import re
import sqlite3
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from magpiary import boardsync, identity
from magpiary import keys as keyring
from magpiary import claude_code, login, modes, settings_art, ui
from magpiary.protocol import DEFAULT_PORT, DEFAULT_RETRY_WAIT
from magpiary.providers import SUGGESTED_MODELS
from magpiary.hub_help import HEALTH, topic_for
from magpiary.store import TRASH_DAYS
from magpiary.tools import in_mac_app
from magpiary.web import Response, e

# The addresses "phones" and "storage" stay as they were, so old links keep working; only the names changed (1 Nov 2026).
BACKUP_SETTING = "last_backup_at"
SECTIONS = {"profile": "Profile & boards", "phones": "Phone", "ai": "AI & login", "ask": "Ask Magpiary", "agents": "AI agents",
            "appearance": "Appearance", "storage": "Library & this Mac"}
NAV_GROUPS = (("You", ("profile",)), ("Using Magpiary", ("phones", "ai", "ask", "agents")), ("This hub", ("appearance", "storage")))
# Shared boards sits on Profile & boards since 8 Nov 2026 (owner); Ask Magpiary and AI agents stay pages of their own.
# The old boards address redirects, keeping the query and the #anchor, so every old link and form return still lands.
MOVED = {"boards": "profile"}
PAGES = {**SECTIONS, "privacy": "Privacy"}  # Privacy sits apart, under the list
SECTION_ICONS = {"profile": ("people", "var(--t-place)"), "ai": ("sparkle", "var(--t-design)"), "ask": ("comment", "var(--t-design)"), "agents": ("terminal", "var(--t-tool)"), "phones": ("phone", "var(--t-place)"),
                 "storage": ("library", "var(--t-discussion)"), "appearance": ("palette", "var(--t-tool)"), "privacy": ("lock", "#3d3d3d")}
SUPPORT_URL = "https://www.buymeacoffee.com/magpiary"  # opens in the browser on click; nothing is sent from the app

SAVED = {"key": "Key checked and saved.", "login": "Instagram connected.", "model": "Model changed.",
         "mode": "Saved. New summaries follow this mode.", "budget": "Saved.", "look": "Saved.", "phone": "Phone removed.",
         "awake": "Saved.", "limit": "Search limit saved.", "longvideo": "Saved.", "allowed": "Allowed. The Digest, Ask and Deeper dive now use it.", "stopped": "Stopped. Magpiary no longer uses it.", "deep": "Deeper dive engine saved.", "keys": "Keys removed.", "profile": "Profile saved.",
         "photo": "Photo saved.", "nophoto": "Photo removed.", "bucket": "Bucket connected and checked.",
         "nobucket": "Bucket removed from this Mac.", "claude": "Claude Code settings saved.",
         "claudetest": "Test finished.", "claudeoff": "Claude Code disconnected. Your AI key writes the digest now.", "via": "New boards will sync there.", "joined": "You joined the board. It fills in as it syncs."}
MODE_PICS = {"smart": ("Your AI keys write a summary, key points, tags and links for each save.",
                       "the caption, the transcript and a few frames"),
             "private": ("No AI at all. Saves are still downloaded, transcribed, grouped and searchable.", "nothing")}
# The privacy note under each of these settings.
LOCKS = {
    "ai": "Only the caption, the transcript and a few frames go to the AI service of the key in use; the video "
          "never leaves this Mac. With a free Gemini key, Google may use what is sent to improve its products; with "
          "billing on, it says it does not. On OpenRouter, each model's provider has its own policy.",
    "search": "The free directories and sites get only the names a post mentions, never the post, its video or its words. "
              "A web search service gets the same names.",
    "instagram": "Your login is copied into a private file on this Mac (owner-only access) and used "
                 "only when you press “Try with my Instagram login” on a blocked post.",
    "profile": "Your name, photo and colour are shared only with the members of boards you join, next to the "
               "cards you add. Your key stays on this Mac.",
    "goals": "Your goals go to the AI that writes your digest and answers Ask, and to AI agents you allow to read your saves. "
             "They are never on your card and never go to a board.",
    "sync": "Board posts are sealed on this Mac with the board's key before they leave it: relays and "
            "storage services see only sealed data, never what's in it. Relays can see that your key posts to a board.",
    "phones": "Phones send links straight to this Mac over Wi-Fi, each with its own pairing key. Nothing goes through a server.",
}

# What the settings search can find: (title, other words people type, page, anchor). Advanced blocks open themselves on arrival.
SEARCH_INDEX = [
    ("Your public face", "profile name photo about colour avatar", "profile", "profile"),
    ("My goals", "goals working toward digest ask ai private", "profile", "goals"),
    ("Profile links", "website instagram x github", "profile", "links"),
    ("Profile topics", "interests", "profile", "topics"),
    ("Your identity key", "nostr signing", "profile", "identity"),
    ("Your phones", "pair add phone iphone qr install code", "phones", "phones"),
    ("Home Wi-Fi and any Wi-Fi", "wifi network where it sends wait failed try", "phones", "phones"),
    ("Open the library on a phone", "phone access pair iphone https certificate revoke", "phones", "phoneaccess"),
    ("Chrome extension", "browser pair extension code", "storage", "chrome"),
    ("Instagram login", "chrome blocked private", "ai", "instagram"),
    ("Smart summaries", "smart private mode ai summaries", "ai", "mode"),
    ("AI keys", "gemini openrouter claude openai api key model", "ai", "keys"),
    ("Digest", "weekly monthly off wrapped summary schedule", "ai", "digest"),
    ("Claude Code and Codex on this Mac", "claude code codex allow local plan permission test order drag", "ai", "keys"),
    ("Web search key", "tavily brave search links finding directories wikidata limit", "ai", "search"),
    ("Pause summaries", "pause stop limit transcribing nest budget", "ai", "pause"),
    ("Remove all keys", "delete keys", "ai", "advanced"),
    ("Turn Ask Magpiary on or off", "ask chat question assistant switch hide", "ask", "onoff"),
    ("Who answers Ask", "claude code codex chatgpt gemini key engine", "ask", "engine"),
    ("Answer depth and web search", "short deep web", "ask", "answers"),
    ("Ask model and effort", "haiku sonnet opus effort", "ask", "model"),
    ("Ask tokens and limit", "token usage spend limit warning", "ask", "usage"),
    ("Let AI agents use Magpiary", "cli terminal command line claude code codex agent mcp switch on off enable disable", "agents", "switch"),
    ("What AI agents may do", "agent permission read save links notes", "agents", "switch"),
    ("Connect an AI agent", "copy command claude code codex mcp", "agents", "connect"),
    ("What AI agents did", "agent activity log recent clear", "agents", "activity"),
    ("Hide saves from AI agents", "agent private hide tag", "agents", "hide"),
    ("Daily limits for AI agents", "agent limit links notes per day", "agents", "limit-add"),
    ("Your boards", "shared boards invite friends", "profile", "boards"),
    ("Where boards sync", "relays nostr bucket b2 backblaze r2 s3", "profile", "sync"),
    ("Theme", "light dark colour mode", "appearance", "theme"),
    ("Tile size", "grid small large wall", "appearance", "tiles"),
    ("Tile labels", "overlay coloured text", "appearance", "labels"),
    ("Glass", "glass blur dark surfaces depth", "appearance", "glass"),
    ("Glass strength", "glass blur glow edge slider percent", "appearance", "glassstrength"),
    ("Page width", "wide full boxed", "appearance", "width"),
    ("Digest on or off", "digest on off switch written by who writes claude codex key", "ai", "digest-on"),
    ("Deeper dive", "deeper dive deep long video podcast minutes suggest sections chapters takeaways quotes engine model claude code codex", "ai", "deepdive"),
    ("Connections map (beta)", "beta map graph connections try early", "appearance", "betamap"),
    ("Interface size", "scale zoom smaller bigger laptop 14 inch size text", "appearance", "scale"),
    ("Your library folders", "storage media notes models size finder", "storage", "library"),
    ("Back up now", "backup copy export database", "storage", "backup"),
    ("Restore from a backup", "restore recover undo database earlier copy", "storage", "restore"),
    ("Trash", "deleted empty", "storage", "trash"),
    ("Keep this Mac awake", "sleep overnight plugged in", "storage", "awake"),
    ("Health check", "doctor test problems", "storage", "health"),
    ("Popularity numbers", "likes views comments refresh stats weekly", "storage", "popularity"),
    ("Check for new versions", "update version github", "storage", "versioncheck"),
    ("About this Mac", "version port firewall receiver", "storage", "mac"),
    ("What Magpiary downloads", "models tools ffmpeg deno whisper size install first run", "storage", "downloads"),
    ("Uninstall Magpiary", "remove delete program", "storage", "remove"),
    ("Hub lock", "pin touch id passcode idle password", "privacy", "lock"),
    ("What leaves this Mac", "privacy journey data sent", "privacy", "leaves"),
    ("Your activity", "counts usage links opened questions asked", "privacy", "activity"),
    ("Where your data lives", "files paths location", "privacy", "lives"),
    ("Delete my data", "remove keys erase", "privacy", "delete"),
]


def _folder_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def _mb(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


# ---- the parts every section is built from ------------------------------------------------------------

def _info(text: str) -> str:
    """A short extra, shown on hover or focus."""
    return (f'<span class="info" tabindex="0" role="note" aria-label="{e(text)}">{ui.icon("info")}'
            f'<span class="ttip">{e(text)}</span></span>')


def _tip(desc: str, info: str = "") -> str:
    """A dropped explaining line, as plain text for the (i) hover, joined to the row's own tip."""
    text = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
    return (text + (" " + info if info else ""))[:600]


def _more(body: str, label: str = "More about this") -> str:
    """A longer extra, folded until asked for. The plain "More about this" explanations are gone (8 Nov 2026, one line per row):
    only an extra with its own label, which carries steps or a command, is kept."""
    if label == "More about this":
        return ""
    return f'<details class="xmore"><summary>{ui.icon("info")}<span>{e(label)}</span></summary><div class="xmorebody">{body}</div></details>'


def _lock(key: str) -> str:
    """The per-group privacy note is gone (8 Nov 2026): the Privacy page says what leaves this Mac, once."""
    return ""
    return f'<div class="plock"><p>{e(LOCKS[key])}</p></div>'


def _handle(name: str, on: bool = True) -> str:
    """The grip on a row of the AI list: drag it, or focus it and use the arrow keys. Greyed and still for one not in use."""
    if not on:
        return (f'<button type="button" class="draghandle" data-keyhandle disabled aria-label="{e(name)} is not in use, so it '
                f'stays below the others" title="Not in use: it stays below">{ui.icon("grip")}</button>')
    return (f'<button type="button" class="draghandle" data-keyhandle aria-label="Reorder {e(name)}: drag, or use the arrow keys" '
            f'title="Drag to change the order">{ui.icon("grip")}</button>')


# A row's explaining line is dropped (8 Nov 2026, owner: too much text; he asks when he wants more). It stays only where it
# states something live (a phone's date, a key's state, folder sizes) or is the row's content: classes below, or the Privacy page.
KEEP_DESC = {"small", "phone2", "emptyrow", "askuse-row", "keyrow", "offrow", "keep"}
_page = threading.local()


def _row(label: str, desc: str = "", control: str = "", *, info: str = "", more: str = "", lead: str = "",
         cls: str = "", sid: str = "") -> str:
    """One setting: what it is on the left (title, one muted line when it has live state), its control on the right. The longer
    extras fold on a line of their own below, so the control never moves when they open."""
    if desc and not getattr(_page, "keep_all", False) and not KEEP_DESC & set(cls.split()):
        info, desc = _tip(desc, info), ""  # the line moves behind the (i) hover instead of being shown
    return (f'<div class="srow{" " + cls if cls else ""}"' + (f' id="{sid}"' if sid else "") + ">"
            + (f'<span class="slead">{lead}</span>' if lead else "")
            + f'<div class="srl"><b>{label}{_info(info) if info else ""}</b>' + (f"<p>{desc}</p>" if desc else "") + "</div>"
            + (f'<div class="src">{control}</div>' if control else "") + (f'<div class="srmore">{more}</div>' if more else "") + "</div>")


def _group(title: str, rows: str, *, gid: str = "", desc: str = "", info: str = "", more: str = "", lock: str = "",
           tag: str = "", cls: str = "", status: str = "", action: str = "") -> str:
    if desc and title and not getattr(_page, "keep_all", False):
        info, desc = _tip(desc, info), ""  # a group's line is a hover too (8 Nov 2026)
    return (f'<section class="sgroup{" " + cls if cls else ""}"' + (f' id="{gid}"' if gid else "") + '><header class="sgh">'
            + (f'<h3>{e(title)}' + (f"<small>{e(tag)}</small>" if tag else "") + (_info(info) if info else "") + "</h3>" if title else "")
            + (f"<p>{desc}</p>" if desc else "") + status + more + (f'<div class="sgact">{action}</div>' if action else "") + f'</header><div class="srows">{rows}'
            + (_lock(lock) if lock else "") + "</div></section>")


def _status(text: str, tone: str = "ok") -> str:
    """One line saying how a hidden (Advanced) setting stands, shown above the fold."""
    return f'<p class="sstat {tone}"><i></i>{text}</p>'


def _adv(body: str, hint: str = "", *, attention: bool = False, gid: str = "advanced", label: str = "Advanced settings", pill: str = "Advanced") -> str:
    """The folded block that ends a page. It remembers if it was opened and opens itself when a link points inside
    it (lock.js-style script lives in settings.js: data-adv)."""
    return (f'<details class="adv" id="{gid}" data-adv><summary><span class="advic">{ui.icon("sliders")}</span>'
            f'<span class="advtx"><span class="advt">{e(label)}</span>' + (f'<span class="advh">{e(hint)}</span>' if hint else "") + "</span>"
            + ('<span class="advdot" title="Something here needs a look"></span>' if attention else "")
            + (f'<span class="advpill">{e(pill)}</span>' if pill else "") + f'<span class="advc">{ui.icon("chev")}</span></summary><div class="advbody">{body}</div></details>')


def _paste(target: str) -> str:
    """A button inside a key field that pastes what is on the clipboard."""
    return (f'<button type="button" class="pastebtn" data-paste="{target}" aria-label="Paste from the clipboard" '
            f'title="Paste">{ui.icon("paste")}</button>')


def _fold(title: str, hint: str, body: str, *, cls: str = "advmini", gid: str = "") -> str:
    """A small flat fold inside a card: a hairline, the title with what is inside it, and a chevron."""
    return (f'<details class="{cls}"' + (f' id="{gid}"' if gid else "") + f'><summary><span class="amt"><b>{e(title)}</b>'
            f'<small>{e(hint)}</small></span><span class="advc">{ui.icon("chev")}</span></summary>{body}</details>')


def _stat(word: str, tone: str) -> str:
    return f'<span class="kstat {tone}"><i></i>{e(word)}</span>'


def _menu(label: str, items: str) -> str:
    return (f'<details class="menu kmenu"><summary class="dots" aria-label="{e(label)}" title="{e(label)}">{ui.icon("more")}'
            f'</summary><div class="pop right">{items}</div></details>')


class SettingsPages:
    """Needs Hub's store, csrf, shell, _form, library and setup (the pairing side, when the service runs one)."""

    def settings_page(self, section: str, q: dict) -> Response:
        if section == "links":  # that page's settings moved: the search key and the Instagram login to AI & login
            return Response(303, b"", headers={"Location": "/settings/ai#search"})
        if section in MOVED:
            where = "/settings/" + MOVED[section] + ("?" + urlencode({k: v for k, v in q.items() if isinstance(v, str)}) if q else "")
            return Response(303, b"", headers={"Location": where})
        if section and section not in PAGES:
            return self.shell("Not found", '<p class="empty">No such settings page. <a class="link" href="/settings">'
                              'Settings</a></p>', "missing", 404)
        _page.keep_all = section == "privacy"  # the Privacy page is the information page: its lines stay
        root = not section  # /settings itself: on a phone this is the list of sections, not one of them
        section = section or next((k for k, (_, bad) in self._nav_status().items() if bad), "ai")
        saved = SAVED.get(q.get("saved", ""), "") or q.get("note", "")[:200]
        error = q.get("error", "")[:200]
        flash = ((f'<div class="flash">{e(saved)}</div>' if saved else "")
                 + (f'<div class="flash err">{e(error)}</div>' if error else ""))
        body = {"profile": self._profile_section, "ai": self._ai_section, "ask": self._ask_section, "agents": self._agents_section, "phones": self._phones_section,
                "storage": self._storage_section, "appearance": self._look_section,
                "privacy": self._privacy_section}[section](q)
        icon, colour = SECTION_ICONS[section]
        page = (f'<div class="setlayout{" setroot" if root else ""}"><aside class="setside"><h1>Settings</h1>{self._search_box()}{self._nav(section)}'
                f'<a class="setsupport" href="{SUPPORT_URL}" target="_blank" rel="noopener">Support Magpiary ↗</a></aside>'
                f'<section class="setpane" id="setpane"><a class="setback" href="/settings">Settings</a><div class="sethead" style="--c:{colour}"><span class="seticon">'
                f'{ui.icon(icon)}</span><div><h2>{PAGES[section]}</h2></div>'
                f'<button type="button" class="btn sm sethelpbtn" id="sethelpbtn" aria-controls="sethelp">?<span>Help</span></button></div>'
                f'{flash}<div class="setboxes">{body}</div></section>'
                f'<aside class="sethelp" id="sethelp" aria-label="Help">'
                f'<button type="button" class="hclose hside" data-hclose aria-label="Close help">×</button>'
                f'{self.help_column(topic_for("settings", section))}</aside></div>')
        return self.shell(f"Settings · {PAGES[section]}", page, "settings", active="settings")

    def _agent_state(self) -> tuple[str, str]:
        """(a few words for the nav, tone)."""
        from magpiary import agent_policy

        if not agent_policy.enabled(self.store):
            return "Off", "ok"
        return "On", "ok"

    def _agents_section(self, q: dict, nested: bool = False) -> str:
        from magpiary import agent_log, agent_policy as ap

        store, back = self.store, "/settings/ai"
        on = ap.enabled(store)

        def switch(action: str, is_on: bool, fields: dict, label: str, confirm: str = "") -> str:
            return self._switch(action, is_on, {**fields, "enabled": "0", "next": back}, {**fields, "enabled": "1", "next": back},
                                label, confirm)

        sub = "".join(
            _row(title, text, switch("/hub/agents/perm", ap.permitted(store, key), {"which": key}, title), lead=ui.icon(icon),
                 cls="small sub", sid=f"perm-{key}")
            for key, title, text, icon in (
                ("read", "Read my saves", "Search, list and read saves, and see the counts.", "search"),
                ("add", "Save links for me", "Add a link the way your phone does.", "plus"),
                ("note", "Write notes on my saves", "Their own labelled note, kept apart from yours.", "summary"))) if on else ""
        master = _group(
            "", _row(
                "Let AI agents use Magpiary",
                "Off until you turn it on. While it is off, every Magpiary command and tool an AI uses says so and does nothing."
                + ("" if on else " Turn it on to choose what they may do.") + ' <a class="link" href="/help#help-agents">How it works</a>',
                switch("/hub/agents/on", on, {}, "Let AI agents use Magpiary"), lead=ui.icon("terminal"), sid="switch")
            + sub
            + "".join(_row(f"Connect {name}", f"Paste this into Terminal once: <code>{e(command)}</code>",
                           f'<button type="button" class="btn sm" data-copycode="{e(command)}" data-copywhat="Command">{ui.icon("copy")}Copy</button>',
                           lead=ui.icon("terminal"), sid=sid)
                      for name, command, sid in (("Claude Code", "claude mcp add magpiary -- magpiary mcp", "connect"),
                                                 ("Codex", "codex mcp add magpiary -- magpiary mcp", "connect-codex"))),
            gid="agents-on")
        shown = {"search": "Searched", "show": "Read a save", "list": "Listed saves", "status": "Checked the counts",
                 "add": "Saved a link", "note": "Wrote a note"}

        def entries(rows: list) -> str:
            return "".join(_row(shown.get(r["tool"], e(r["tool"])),
                                (e(r["detail"]) + " · " if r["detail"] else "") + e(ui.day(r["at"])),
                                f'<span class="sstat {"ok" if r["ok"] else "warn"}"><i></i>{"Done" if r["ok"] else "Refused"}</span>',
                                info=r["why"] if not r["ok"] else "", cls="small") for r in rows)

        log = agent_log.recent(200)
        earlier = (_fold("Show earlier activity", f"{len(log) - 10} more", entries(log[10:])) if len(log) > 10 else "")
        activity = _group(
            "Recent activity", (entries(log[:10]) or _row("Nothing yet", "When an AI uses Magpiary, it shows here.", cls="small")) + earlier,
            gid="activity", desc="What AI agents did, newest first. The log is a private file on this Mac.",
            action=self._form("/hub/agents/clearlog", {"next": back}, "Clear", "btn sm ghost", "Clear the activity log?") if log else "")

        tags = ", ".join(ap.hidden_tags(store))
        hide = _group("Hide from agents", _row(
            "Saves with these tags", "To an AI they do not exist: they are left out of search, lists, counts and notes. Separate tags "
            "with commas. To hide a whole group, give its saves a tag such as private.",
            f'<form method="post" action="/hub/agents/hide" class="inlineform">{ui.hidden(self.csrf, next=back)}'
            f'<input type="text" name="tags" value="{e(tags)}" placeholder="private, journal" maxlength="300" aria-label="Tags to hide" '
            f'autocomplete="off" spellcheck="false"><button class="btn sm dark" type="submit">Save</button></form>',
            lead=ui.icon("lock"), sid="hide"), gid="hide-group")

        def limit_row(kind: str, title: str, text: str) -> str:
            pills = "".join(f'<label class="pillc"><input type="radio" name="{kind}" value="{c}"{" checked" if c == ap.limit(store, kind) else ""}>'
                            f'<span>{"No limit" if c == 0 else c}</span></label>' for c in ap.LIMIT_CHOICES)
            return _row(title, f"{text} Today: {store.agent_used(kind)}.",
                        f'<form method="post" action="/hub/agents/limits" class="inlineform" data-autosubmit>{ui.hidden(self.csrf, next=back)}'
                        f'<div class="pillbar" role="radiogroup" aria-label="{e(title)}">{pills}</div></form>', lead=ui.icon("clock"), sid=f"limit-{kind}")
        limits = _group("Daily limits", limit_row("add", "Links a day", "The most links an AI can save in a day.")
                        + limit_row("note", "Notes a day", "The most notes an AI can write in a day."), gid="limits",
                        desc="So a runaway agent cannot flood your library.")
        return master + activity + (hide + limits if nested else _adv(hide + limits, "Hide saves, daily limits"))

    def _search_box(self) -> str:
        data = e(json.dumps([[t, k, p, a] for t, k, p, a in SEARCH_INDEX]))
        return (f'<div class="setsearch" data-setsearch data-index="{data}">{ui.icon("search")}<input type="search" '
                f'placeholder="Search settings" aria-label="Search settings" autocomplete="off" spellcheck="false">'
                f'<div class="setresults" role="listbox" hidden></div></div>')

    def _nav_status(self) -> dict:
        """One short fact per section, in list order, and whether it needs a look."""
        mode = modes.current(self.store)
        working = next((k for k in modes.summarisers(self.store, keyring)), None)
        ai = ("Private · no AI" if mode == "private" else f"Smart · {working.name}" if working else "Smart · no key yet")
        phones = [p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]
        counts = self.store.hub_counts()["shelves"]
        status = {"profile": (identity.profile(self.store)["name"] or "No name yet", False),
                  "phones": (f'{len(phones)} phone{"" if len(phones) == 1 else "s"} paired' if phones else "No phone yet", not phones),
                  "ai": (ai, mode == "smart" and not working), "ask": self.ask_status(), "agents": (self._agent_state()[0], False),
                  "appearance": (ui.THEMES[ui.appearance(self.store)["theme"]], False),
                  "storage": (f'{sum(counts.values())} saves', False)}
        return {k: status[k] for k in SECTIONS}

    def _nav(self, current: str) -> str:
        """The sections as a list under small headings, each with how it stands right now; Privacy apart, under it."""
        status = self._nav_status()
        me = identity.profile(self.store)

        def card(k: str) -> str:
            face = (ui.avatar(me["name"] or "You", me["colour"], photo_url() if me["photo"] else "") if k == "profile"
                    else ui.icon(SECTION_ICONS[k][0]))
            return (f'<a class="setcard{" warn" if status[k][1] else ""}{" on" if k == current else ""}{" me" if k == "profile" else ""}" href="/settings/{k}" '
                    f'style="--c:{SECTION_ICONS[k][1]}"{" aria-current=page" if k == current else ""}>'
                    f'<span class="seticon">{face}</span><b>{SECTIONS[k]}</b>'
                    f'<span class="setstat">{"● " if status[k][1] else ""}{e(status[k][0])}</span></a>')

        return ('<nav class="setnav" aria-label="Settings sections">' + "".join(
            f'<p class="setnavh">{e(head)}</p>' + "".join(card(k) for k in keys) for head, keys in NAV_GROUPS) + "</nav>"
            f'<p class="setnavh setsech">Security</p><a class="setpriv{" on" if current == "privacy" else ""}" href="/settings/privacy"'
            f'{" aria-current=page" if current == "privacy" else ""}><span class="seticon" style="--c:#5b5b66">{ui.icon("lock")}</span><span><b>Privacy</b>'
            f'<small>{e(self.lock_nav_status() or "Hub lock off")}</small></span></a>')

    # ---- AI & login ------------------------------------------------------------------

    def _ai_section(self, q: dict) -> str:
        """AI keys first, then Summaries: the Smart or Private switch, and the Digest, Ask and Deeper dive that need Smart."""
        return "".join([self._keys_group(q), self._summaries_group(), self._digest_group(q), self._deep_group(),
                        self._finding_group(), self._instagram_group(),
                        _adv(_group("Pause summaries", _row("Pause or limit them", "The switches for summaries and transcribing are in the Nest, where you can see the work.",
                                                            '<a class="btn sm" href="/nest">Open the Nest</a>', lead=ui.icon("clock")), gid="pause")
                             + self._keys_danger(), "Pausing summaries, removing keys")])

    def _summaries_group(self) -> str:
        """One switch: Smart (on) or Private (off). With nothing that can write a summary it reads Private and the switch
        explains that a key is needed first (owner, 4 Nov 2026)."""
        from magpiary import askconfig
        from magpiary import engines as eng

        smart = modes.effective(self.store) == "smart"
        has_engine = bool(eng.options(self.store))
        back = "/settings/ai#mode"
        if smart:
            confirm, ok = ("Switch to Private? Posts already read stay as they are; new ones get no summary. "
                           "Nothing will be sent to any AI. Your keys stay saved."), "Switch to Private"
        elif not has_engine:
            confirm, ok = "Smart summaries need an AI key, or Claude Code or Codex allowed. Add one in AI keys.", "Add a key"
        else:
            confirm, ok = "", ""
        status = (f'<span class="modestat smart">Smart</span>' if smart else
                  f'<span class="modestat private">{ui.icon("lock")}Private</span>')
        switch = self._switch("/hub/settings/mode", smart, {"mode": "private", "next": back}, {"mode": "smart", "next": back},
                              "Smart summaries", confirm=confirm, ok=ok)
        why = modes.waiting_reason(self.store, keyring) if smart else ""
        desc = (MODE_PICS["smart"][0] + " Only the caption, the transcript and a few frames are sent." if smart else
                "No AI at all. Saves are still downloaded, transcribed on this Mac, grouped into piles and searchable, "
                "without summaries." + (" Your keys stay saved, unused." if has_engine else ""))
        rows = _row("Enable Smart Summaries", desc, f'<span class="modectl">{status}{switch}</span>', lead=ui.icon("sparkle"),
                    sid="smart", more=f'<p class="small bad">{e(why)}</p>' if why else "")
        ask_on = askconfig.enabled(self.store)
        rows += _row("Ask Magpiary", "Ask questions about your saves and get answers with the posts they came from.",
                     f'<span class="modectl">{_stat("On" if ask_on else "Off", "ok" if ask_on else "")}'
                     f'<a class="btn sm" href="/settings/ask">Open</a></span>', lead=ui.icon("book"), sid="summaries-ask")
        return _group("Summaries", rows, gid="mode",
                      more=_more("<p>In both modes the transcript and the frames are made on this Mac, and the video itself "
                                 "is never sent anywhere. You can switch any time; posts already read stay as they are.</p>"
                                 "<p>Summaries are written in English, whatever language a post is in. Names and quotes stay "
                                 "as said. Tags from the AI are added to each post; change them on the post.</p>"))

    # ---- Claude Code ---------------------------------------------------------------------

    def _claude_state(self) -> dict:
        """The free checks (they start Claude Code twice, about half a second), kept for five minutes."""
        import time

        cached = getattr(self, "_claude_cache", None)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        state = claude_code.check()
        self._claude_cache = (time.monotonic(), state)
        return state

    def _keys_danger(self) -> str:
        if not keyring.load():
            return ""
        return _group("Remove keys", _row("Remove all keys", "Every AI and web search key is deleted from this Mac.",
                                          self._form("/hub/keys/remove-all", {"next": "/settings/ai"}, "Remove all", "btn sm danger",
                                                     confirm="Remove every AI and web search key from this Mac? Summaries wait until you add one."),
                                          lead=ui.icon("trash")), gid="keysdanger", cls="careful")

    def _key_state(self, k, all_keys: list, today: str) -> tuple[str, str]:
        if k.refused:
            return "Refused: replace it", "bad"
        if k.limit_day == today:
            return "Limit reached · back tomorrow", "warn"
        if keyring.PROVIDERS[k.provider]["kind"] == "search":
            return "In use", "ok"
        first = next((x for x in all_keys if x.usable(today) and keyring.PROVIDERS[x.provider]["kind"] == "ai"), None)
        return ("Working", "ok") if k is first else ("Standby", "idle")

    def _key_rows(self, kind: str) -> str:
        today = date.today().isoformat()
        all_keys = keyring.load()
        mine = [k for k in all_keys if keyring.PROVIDERS[k.provider]["kind"] == kind]
        back = "/settings/agents"
        rows = []
        for n, k in enumerate(mine):
            state, tone = self._key_state(k, all_keys, today)
            provider = keyring.PROVIDERS[k.provider]["name"].split(" (")[0]
            items = ""
            if k.provider in SUGGESTED_MODELS:
                items += (f'<div class="mi chmodel"><b>Change model</b><form method="post" action="/hub/keys/model">'
                          f'{ui.hidden(self.csrf, key_id=k.id)}<input type="text" name="model" value="{e(k.model)}" '
                          f'list="models-{e(k.provider)}" maxlength="100" aria-label="Model for this key">'
                          f'<button class="btn sm dark" type="submit">Save</button></form></div>')
            items += ("<hr>" if items else "") + ui.button_form(
                self.csrf, "/hub/keys/remove", {"key_id": k.id, "next": back}, "Remove this key", "bad",
                confirm=f"Remove {k.name}? It is deleted from this Mac.")
            desc = (f'{e(provider)} · {e(keyring.TIERS[k.tier])}' + (f' · <span class="mono">{e(k.model)}</span>' if k.model else "")
                    + f' · added {e(k.added)}')
            if kind == "ai":
                from magpiary.hub_ask import ENGINE_LOGO

                logo = ENGINE_LOGO.get(k.provider, ui.icon("links"))
                working = not k.refused and keyring.PROVIDERS.get(k.provider, {}).get("ready", False)
                rows.append((f"key:{k.id}", _row(e(k.name), desc, _stat(state, tone) + _menu(f"More for {k.name}", items),
                                                 lead=_handle(k.name, working) + logo, sid=f"key-{k.id}",
                                                 cls="keyrow" + ("" if working else " offrow"))))
            else:
                rows.append(("", _row(e(k.name), desc, _stat(state, tone) + _menu(f"More for {k.name}", items), lead=ui.icon("search"), cls="keep")))
        if kind == "ai":
            return dict(rows)  # type: ignore[return-value]  (the AI keys are placed in the owner's one order by _keys_group)
        return "".join(r for _, r in rows)

    def _local_rows(self) -> dict:
        """Claude Code and Codex on this Mac, as rows of the one AI list: off until allowed here, the only place they are allowed
        or stopped. Allowing asks first (a dialog), then a tiny test run; only a passing test allows it."""
        from magpiary import engines as eng
        from magpiary.hub_ask import ENGINE_LOGO

        rows = {}
        for kind in eng.LOCAL:
            on = eng.is_allowed(self.store, kind)
            here = eng.installed(kind)
            logo = ENGINE_LOGO.get("claude" if kind == "claude_code" else "codex", "")
            confirm = (f"Allow {eng.SHORT[kind]} on this Mac? Magpiary will use {eng.PLAN[kind]} for the Digest, Ask Magpiary and "
                       f"Deeper dive, and for summaries too if you drag it above your keys. It sends the text and frames of the posts "
                       f"involved; your keys and other files stay on this Mac. A tiny test runs first (a few tokens).")
            if on:
                desc = f"Allowed · {eng.PLAN[kind]}. Writes summaries when it is the first in this list that can."
            elif here:
                desc = f"On this Mac, not allowed. Magpiary never uses {eng.PLAN[kind]} until you switch it on."
            else:
                desc = "Not on this Mac. Set it up from Ask Magpiary's settings, then switch it on here."
            control = (self._switch("/hub/engine/allow", on, {"kind": kind, "enabled": "0", "next": "/settings/ai#keys"},
                                    {"kind": kind, "enabled": "1", "next": "/settings/ai#keys"}, f"Allow {eng.SHORT[kind]}",
                                    confirm="" if on else confirm)
                       if on or here else '<a class="btn sm" href="/settings/ask#engine">Set it up</a>')
            rows[kind] = _row(eng.LOCAL[kind], desc, control, lead=_handle(eng.SHORT[kind], on and here) + logo, sid=f"local-{kind}",
                              cls="keyrow" + ("" if on and here else " offrow"))
        return rows

    def _keys_group(self, q: dict) -> str:
        from magpiary import engines as eng

        keyed = {**self._key_rows("ai"), **self._local_rows()}
        ordered = [i for i in eng.order(self.store) if i in keyed]
        rows = "".join(sorted((keyed[i] for i in ordered), key=lambda r: " offrow" in r.split(">", 1)[0]))  # in use first, in order
        have_keys = any(i.startswith("key:") for i in keyed)
        lists = "".join(f'<datalist id="models-{prov}">' + "".join(f'<option value="{e(m)}">' for m in models)
                        + "</datalist>" for prov, models in SUGGESTED_MODELS.items())
        empty = _row("No key yet", "Summaries are waiting. A free Gemini or OpenRouter key takes about two minutes.",
                     cls="emptyrow") if not have_keys else ""
        add = (f'<details class="addk"{"" if have_keys else " open"}><summary class="btn sm">{ui.icon("plus")}Add a key</summary>'
               f'{self._add_key_form("ai")}</details>')
        return _group("AI keys", f'<div class="keylist" data-keylist>{rows}</div>' + empty + f'<div class="srow addrow">{add}</div>' + lists, gid="keys", cls="feat hero pink",
                      desc="Used in this order: the first one that works writes each summary. Drag by the handle to change it. "
                           "The Digest, Ask and Deeper dive use the first Claude Code, Codex or paid key in this order.", lock="ai",
                      more=_more("<p>When a key reaches its daily limit or is refused, Magpiary moves to the next, and goes "
                                 "back to the first the next day. Each post records which key wrote it. Free keys are paced "
                                 "to stay within their limits.</p>"))

    GUIDE_CHIP = {"gemini": "Free", "openrouter": "Free models", "claude": "Paid · needs credits",
                  "openai": "Paid · needs a card", "tavily": "Free · no card", "brave": "Needs a card · $5 free each month"}
    GUIDE_NOTES = ("Free or paid", "Recommended", "Magpiary ", "Brave reportedly")   # advice after the numbered steps

    @staticmethod
    def _key_guides(providers: dict) -> str:
        """How to get a key, one block per provider; the page script shows only the block of the chosen provider.
        The link comes first as a big button, the steps are numbered, and the advice after them is set apart."""
        first = next(iter(providers))
        out = []
        for p, v in providers.items():
            name = e(v["name"].split(" (")[0])
            steps = [x for x in v["steps"] if not x.startswith(SettingsPages.GUIDE_NOTES)]
            notes = [x for x in v["steps"] if x.startswith(SettingsPages.GUIDE_NOTES)]
            chip = SettingsPages.GUIDE_CHIP.get(p, "")
            out.append(
                f'<div class="guide2" data-provider="{p}"{"" if p == first else " hidden"}>'
                f'<div class="g2head"><b>Get your {name} key</b>' + (f'<span class="g2chip">{e(chip)}</span>' if chip else "") + '</div>'
                f'<a class="btn dark g2open" href="{e(v["url"])}" target="_blank" rel="noopener noreferrer">Open the {name} page ↗</a>'
                '<ol class="g2steps">' + "".join(f"<li>{e(step)}</li>" for step in steps) + "</ol>"
                + ("".join(f'<p class="g2note">{e(n)}</p>' for n in notes)) + "</div>")
        return "".join(out)

    def _add_key_form(self, kind: str) -> str:
        providers = {p: v for p, v in keyring.PROVIDERS.items() if v["kind"] == kind}
        options = "".join(f'<option value="{p}">{e(v["name"])}</option>' for p, v in providers.items())
        guides = self._key_guides(providers)
        back = "/settings/agents"
        if kind == "search":
            fields = (f'<input type="hidden" name="tier" value="free"><div class="form"><label for="search-provider">Service'
                      f'</label><select name="provider" id="search-provider">{options}</select><label for="search-key">Key</label>'
                      '<span class="pastewrap"><input id="search-key" type="password" name="key" placeholder="tvly-… or BSA…" required '
                      f'autocomplete="off">{_paste("#search-key")}</span></div>')
        else:
            tiers = "".join(f'<option value="{t}">{e(label)}</option>' for t, label in keyring.TIERS.items())
            more = _fold("More options", "free or paid, model, name",
                         f'<div class="form"><label for="tier">Free or paid</label><select name="tier" id="tier">{tiers}</select>'
                         f'<label for="model" id="model-label" hidden>Model</label><input type="text" name="model" id="model" '
                         f'maxlength="100" placeholder="recommended (leave empty)" hidden>'
                         f'<label for="label">Name</label><input type="text" name="label" id="label" maxlength="40" '
                         f'placeholder="Optional, like “Personal Gemini”"></div>', gid="addkey-adv")
            fields = (f'<div class="form"><label for="provider">Provider</label><select name="provider" id="provider">{options}</select></div>'
                      f'{guides}<div class="form"><label for="key">Key</label>'
                      f'<span class="pastewrap"><input type="password" name="key" id="key" placeholder="Paste the key" required>{_paste("#key")}</span></div>{more}')
            guides = ""
        return (f'<form method="post" action="/hub/keys/add" autocomplete="off" class="addform">{ui.hidden(self.csrf, next=back)}'
                f'{fields}{guides}<div class="row"><button class="btn dark" type="submit">Check and save</button><button class="btn" type="button" data-closedetails>Cancel</button>'
                f'<span class="small muted">Checked with the provider, then stored only on this Mac and never shown again.'
                f'</span></div></form>')

    # ---- Finding links, the Instagram login -----------------------------------------------------

    def _deep_group(self) -> str:
        """Deeper dive: on by itself once Claude Code or Codex is allowed or a paid key is saved; never on a free-tier key."""
        from magpiary import deepdive
        from magpiary import engines as eng

        on = deepdive.enabled(self.store)
        back = "/settings/ai#deepdive"
        usable = deepdive.engines(self.store)
        what = ("An extra, deeper reading of a post when you ask for it: every part of a long video, more frames, comments and "
                "linked pages, with sections, takeaways and quotes. The normal summary stays as it is.")
        if not usable:
            rows = _row("Deeper dive", what + " It needs Claude Code or Codex allowed in AI keys, or a paid key: a free key "
                        "would run out.", '<a class="btn sm" href="/settings/ai#keys">Allow Claude Code or Codex</a>',
                        lead=ui.icon("sparkle"), sid="deepdive")
            return _group("Deeper dive", rows, gid="deep", desc="Off: no engine that can carry it.")
        rows = _row("Deeper dive", what,
                    self._switch("/hub/deep/on", on, {"enabled": "0", "next": back}, {"enabled": "1", "next": back}, "Deeper dive"),
                    lead=ui.icon("sparkle"), sid="deepdive",
                    info="It runs only when you press Deeper dive on a post, once per post. "
                         f"Up to {deepdive.CONFIRM_ABOVE} AI calls it starts at once; more, and it asks first.")
        if on:
            chosen = deepdive.engine(self.store)
            picked = eng.choice(self.store, "deep")
            pick = lambda name, label, items, now: (  # noqa: E731
                f'<label class="deeppick"><span>{label}</span><select name="{name}" aria-label="{label}">'
                + "".join(f'<option value="{e(v)}"{" selected" if v == now else ""}>{e(t)}</option>' for v, t in items) + "</select></label>")
            efforts = deepdive.efforts_for(chosen["kind"], chosen["key"])
            control = (f'<form method="post" action="/hub/deep/engine" class="deepengine" data-autosubmit>{ui.hidden(self.csrf)}'
                       + (pick("engine", "Engine", usable, picked["id"]) if len(usable) > 1 else
                          f'<span class="deeppick"><span>Engine</span><em>{e(picked["label"])}</em></span>')
                       + pick("model", "Model", deepdive.models_for(chosen["kind"], chosen["key"]).items(), chosen["model"])
                       + (pick("effort", "Effort", efforts.items(), chosen["effort"]) if efforts else
                          '<span class="deeppick"><span>Effort</span><em>Set by the model</em></span>')
                       + "</form>")
            rows += _row("Engine", "Which AI reads it. Frames and text go to that AI; the video never leaves this Mac. "
                         "A stronger model and higher effort read more closely and use more of your plan or quota.",
                         control, lead=ui.icon("sliders"), sid="deepengine", cls="rstack")
            minutes = self.store.get_setting(deepdive.LONG, str(deepdive.LONG_DEFAULT)) or str(deepdive.LONG_DEFAULT)
            waiting = len(deepdive.suggested_urls(self.store))
            rows += _row("Suggest it for videos longer than",
                         "Minutes. Those posts show Deeper dive as suggested. 0 never suggests it.",
                         f'<form method="post" action="/hub/settings/long-video" class="iform">{ui.hidden(self.csrf)}'
                         f'<input type="number" min="0" max="600" name="minutes" value="{e(minutes)}" aria-label="Minutes">'
                         f'<button class="btn sm" type="submit">Save</button></form>', lead=ui.icon("clock"), sid="longvideo",
                         more=(f'<a class="link" href="/?deep=suggested">{waiting} long video{"s" if waiting != 1 else ""} '
                               f'could use one now →</a>') if waiting else "")
        return _group("Deeper dive", rows, gid="deep", desc=f'Uses {e(eng.choice(self.store, "deep")["label"])}.' if on else "Off.")

    def _finding_group(self) -> str:
        """Links work with no setup; a web search key only finds what the free directories miss."""
        from magpiary.worker import SEARCH_LIMIT, searches_used

        rows = self._key_rows("search")
        if rows:
            limit = self.store.get_setting("search_limit", str(SEARCH_LIMIT))
            used = searches_used(self.store)
            rows += _row("Monthly limit", f"{used} of {e(limit)} searches used this month.",
                         f'<form method="post" action="/hub/settings/search-limit" class="iform">{ui.hidden(self.csrf)}'
                         f'<input type="number" min="0" max="10000" name="limit" value="{e(limit)}" aria-label="Searches a month">'
                         f'<button class="btn sm" type="submit">Save</button></form>',
                         info="Searches stop for the month at this number, so a paid plan never runs over.", cls="keep")
            on = True
        else:
            rows = (f'<div class="srow addrow"><details class="addk"><summary class="btn sm">{ui.icon("plus")}Add a search key'
                    f'</summary>{self._add_key_form("search")}</details></div>')
            on = False
        return _group("Finding links", rows, gid="search", lock="search",
                      desc="Links work with no setup and never use your AI quota. A web search key finds the sites the free directories miss.",
                      status=_status("Web search is on." if on else "Free directories only.", "ok" if on else "idle"),
                      more=_more("<p>Tavily is free with no card (1,000 searches a month). Brave asks for a card and "
                                 "gives $5 of credit a month.</p>", "Which service?"))

    def _instagram_group(self) -> str:
        day = login.connected(self.store)
        command = ('<p>Open the <b>Terminal</b> app and run:</p><pre class="cmd">magpiary login connect</pre>'
                   '<p>macOS asks twice: to let Terminal use data from other apps, and to use “Chrome Safe Storage”. Choose '
                   'Allow both times. (macOS does not let a background service read Chrome, so this one step happens in '
                   'Terminal.) Then reload this page.</p>')
        if day:
            row = _row("Connected from Chrome", f"Since {e(ui.day(day).removesuffix(' 00:00'))}. Used only when you ask, on a blocked post.",
                       self._form("/hub/login/disconnect", {"next": "/settings/ai#instagram"}, "Disconnect", "btn sm danger",
                                  confirm="Delete Magpiary's copy of your Instagram login?"),
                       lead=ui.icon("check"), more=_more(command, "Copy it again"))
        else:
            row = _row("Not connected", "Only needed for posts that are age-limited or for followers only. Your login stays on this Mac.",
                       lead=ui.icon("phone"), more=_more(command, "How to connect"))
        return _group("Instagram login", row, gid="instagram", lock="instagram",
                      more=_more("<p>Some posts only show to logged-in people. If you connect, Magpiary copies just your "
                                 "Instagram login from Chrome and uses it only when you press “Try with my Instagram "
                                 "login” on a blocked post. Fetching while logged in carries a small risk to your account, "
                                 "so it stays a per-post choice.</p>"))

    # ---- Saving posts -------------------------------------------------------------------

    def phone_advanced(self) -> str:
        """The "Advanced settings" a phone is paired with (Settings and the setup guide). The wait after a failed try is set
        afterwards, on the phone's own row."""
        return (f'<details class="homewifi"><summary><span class="advic">{ui.icon("sliders")}</span><span class="advt">Advanced settings</span>'
                f'<span class="advpill">Advanced</span><span class="advc">{ui.icon("chev")}</span></summary><div class="homewifibody">'
                f'<label><span>Set up a home Wi-Fi <small>(optional)</small></span><input type="text" name="home_wifi" maxlength="64" '
                f'placeholder="Exactly as in Settings → Wi-Fi on the iPhone"></label>'
                f'<p class="hint">Type it exactly as it appears in Settings → Wi-Fi. The phone then sends only on that Wi-Fi, and keeps '
                f'everything else until it is back.</p></div></details>')

    def _home_group(self) -> str:
        """"Send when I get home": a closed fold under the phones (an optional step done once in the Shortcuts app)."""
        steps = ("<ol class=\"small\"><li>In Shortcuts open <b>Automation</b>, then <b>+</b>, then <b>Wi-Fi</b>.</li>"
                 "<li>Choose your home network and tick <b>Is Joined</b> only.</li><li>Pick <b>Run Immediately</b>.</li>"
                 "<li>Add the action <b>Run Shortcut</b>, then <b>Magpiary</b>.</li><li>Switch <b>Notify When Run</b> off.</li></ol>"
                 "<p class=\"hint\">iPhones don't let a program create this part, so it's done by hand once.</p>")
        return _fold("Send when I get home", "optional: shares made away from home arrive by themselves", steps, gid="home")

    def _chrome_group(self, q: dict) -> str:
        """The Chrome extension, apart from the phones: one browser only. Unpaired: a Pair button. Paired: one row, a green
        Paired pill on the right, and a menu with a new code and Remove."""
        if not self.setup:
            return ""
        browser = next((p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") == "browser"), None)
        code = q.get("chromecode", "")
        code = code if len(code) == 14 and all(ch.isalnum() or ch == "-" for ch in code) else ""
        back = {"next": "/settings/storage"}
        rows = ""
        if code:
            rows += _row("Paste this code into the extension", "It works once, for 15 minutes. Open the Magpiary extension in Chrome "
                         "and paste it where it asks.",
                         f'<code class="ccode">{e(code)}</code><button type="button" class="btn sm" data-copycode="{e(code)}" '
                         f'data-copywhat="Code">{ui.icon("copy")}Copy</button>', lead=ui.icon("ext"), cls="phone2")
        if browser:
            items = (self._form("/hub/browsers/add", back, "New code", "", confirm="A new code lets you pair the extension again. The "
                                "current pairing keeps working until the new code is used.")
                     + "<hr>" + self._form("/hub/phones/remove", {"name": browser["name"], **back}, "Remove Chrome", "bad",
                                           confirm="Remove Chrome? The extension can no longer save links until you pair it again."))
            rows += _row("Chrome", "", _stat("Paired", "ok") + _menu("More for Chrome", items), lead=ui.icon("ext"), cls="phone2")
        elif not code:
            steps = ("<ol class=\"small\"><li>Press <b>Show the folder</b>: Chrome's extensions page opens too. Turn on <b>Developer mode</b> at the top right.</li>"
                     "<li>Press <b>Load unpacked</b> and choose the folder that opens: <code>Magpiary › chrome-extension</code>.</li>"
                     "<li>Pin Magpiary from the puzzle-piece menu.</li><li>Then press <b>Pair Chrome</b> here and paste the code into the extension.</li></ol>")
            from magpiary.hub_welcome import CHROME_STORE
            from magpiary.logos import LOGOS

            rows += _row("Get the extension", "Free from the Chrome Web Store.",
                         f'<a class="btn sm" href="{CHROME_STORE}" target="_blank" rel="noopener">{LOGOS["chromewebstore"]}Chrome Web Store</a>',
                         lead=ui.icon("ext"), cls="phone2",
                         more=_more(steps + self._form("/hub/extension/get", back, "Show the folder", "btn sm"), "Or add it by hand"))
            rows += _row("Chrome", "Save the page you're on, or one post from a feed, straight to this Mac.",
                         self._form("/hub/browsers/add", back, "Pair Chrome", "btn sm dark"), lead=ui.icon("ext"), cls="phone2")
        else:
            rows += _row("Chrome", "", _stat("Waiting for the extension", "warn"), lead=ui.icon("ext"), cls="phone2")
        return _group("Chrome", rows, gid="chrome",
                      desc="Saves go to this Mac only. Pair one browser; its shortcuts are shown in the extension.")

    def _phones_section(self, q: dict) -> str:
        phones = [p for p in self.store.list_phones() if not p["revoked_at"] and p.get("kind") not in ("browser", "agent")]
        last = self.store.last_delivery()
        rows = []
        for p in phones:
            paired = ui.day(p.get("created_at"))
            items = (self._form("/hub/phones/new-code", {"name": p["name"]}, "New install code", "",
                                confirm="A new code replaces this phone's key: its Shortcut stops working until you install the new one.")
                     + "<hr>" + self._form("/hub/phones/remove", {"name": p["name"]}, "Remove this phone", "bad",
                                           confirm=f"Remove {p['name']}? It can no longer send links."))
            mode = p.get("wifi_mode") if p.get("wifi_mode") in ("home", "any") else "home"
            wait = p.get("retry_wait") or DEFAULT_RETRY_WAIT
            wait_label = {5: "5 minutes", 15: "15 minutes", 30: "30 minutes", 60: "1 hour"}
            if p.get("home_wifi"):
                picks = "".join(f'<label class="lkseg"><input type="radio" name="mode" value="{k}"{" checked" if mode == k else ""}>'
                                f"<span>{label}</span></label>" for k, label in (("home", "Home only"), ("any", "Any Wi-Fi")))
                wifi = (f'<form class="padvrow" method="post" action="/hub/phones/wifi" data-autosubmit>'
                        f'{ui.hidden(self.csrf, name=p["name"], next="/settings/phones")}<span><b>Where it sends</b>'
                        f'<small>{"Only on its home Wi-Fi. Anything saved elsewhere waits on the phone." if mode == "home" else "On any Wi-Fi it joins, if this Mac is on it too."} '
                        f'Takes effect the next time the phone reaches this Mac.</small></span>'
                        f'<div class="lkseggroup" role="radiogroup" aria-label="Where {e(p["name"])} sends">{picks}</div></form>')
                where = _stat("Home only" if mode == "home" else "Any Wi-Fi", "ok")
                line = f'<span class="pnet">{ui.icon("wifi")}{e(p["home_wifi"])}</span>'
            else:  # paired without a home Wi-Fi: it sends on any Wi-Fi, nothing to switch
                wifi = ('<div class="padvrow"><span><b>Where it sends</b><small>On any Wi-Fi it joins, if this Mac is on it too. '
                        'To limit it to one Wi-Fi, add the phone again with a home Wi-Fi name.</small></span></div>')
                where = _stat("Any Wi-Fi", "ok")
                line = ""
            waits = "".join(f'<option value="{m}"{" selected" if m == wait else ""}>{label}</option>' for m, label in wait_label.items())
            waitf = (f'<form class="padvrow" method="post" action="/hub/phones/wait" data-autosubmit>{ui.hidden(self.csrf, name=p["name"], next="/settings/phones")}'
                     f'<span><b>After a failed try, wait</b><small>The phone stops trying a Wi-Fi your Mac never answered on for this long. '
                     f'It is built into the phone\'s Shortcut: make a new install code after changing it.</small></span>'
                     f'<span class="padvctl"><select name="retry_wait" aria-label="Wait after a failed try">{waits}</select></span></form>')
            adv = _fold("More options", "where it sends, the wait after a failed try",
                        f'<div class="padvbody">{wifi}{waitf}'
                        f'<p class="hint">Running Magpiary by hand from the Shortcuts app, with nothing shared, always tries to send now.</p></div>',
                        cls="padv")
            sub = (f'<span class="pmuted">Paired {e(paired)}</span>' if paired else "")
            if p.get("last_seen_at") and not p.get("signed_at"):  # it has sent, the old way: its key crosses the Wi-Fi as it is
                sub += ('<span class="pold">Older Shortcut: it sends its key as it is over Wi-Fi. Choose New install code in '
                        'its ⋯ menu and install the new Shortcut, which signs each send instead.</span>')
            rows.append(_row(e(p["name"]) + line, sub, where + _menu(f"More for {p['name']}", items), lead=ui.icon("phone"), cls="phone2", more=adv))
        if not rows:
            rows.append(_row("No phone yet", "Add one to share posts straight to this Mac.", cls="emptyrow"))
        add = (f'<div class="srow addrow"><details class="addk"{" open" if not phones else ""}><summary class="btn sm">'
               f'{ui.icon("plus")}Add a phone</summary><form method="post" action="/hub/phones/add" class="addform">'
               f'{ui.hidden(self.csrf, next="/settings/phones")}<div class="form">'
               f'<label for="pname">Name for this phone</label><input id="pname" type="text" name="name" required maxlength="60" '
               f'placeholder="Like “Work iPhone”"><span class="hint">The phone sends on any Wi-Fi your Mac is on.</span></div>'
               f'{self.phone_advanced()}'
               f'<div class="row"><button class="btn dark" type="submit">'
               f'Show the QR code</button><button class="btn" type="button" data-closedetails>Cancel</button></div></form></details></div>') if self.setup else (
               '<p class="gnote">Pairing runs with the background service.</p>')
        qr = self._qr_block(q.get("qr", ""), q.get("phone", "")) if q.get("qr") and self.setup else ""
        out = [_group("Send posts from your iPhone", "".join(rows) + add + (self._home_group() if phones else ""), gid="phones", lock="phones", cls="hero lilac",
                      desc=(f"Share a post to Magpiary on your iPhone and it arrives here. Last delivery {e(ui.day(last))}." if last
                            else "Share a post to Magpiary on your iPhone and it arrives here."),
                      more=""),
               self.access_group(q),
               qr]
        return "".join(out)

    def _switch(self, action: str, on: bool, fields_off: dict, fields_on: dict, label: str, confirm: str = "", ok: str = "") -> str:
        """An on/off switch that posts. `confirm` asks first in a dialog; `ok` is that dialog's button ("I understand, turn it on")."""
        fields = fields_off if on else fields_on
        ask = (f' data-confirm="{e(confirm)}"' + (f' data-confirm-ok="{e(ok)}"' if ok else "")) if confirm else ""
        return (f'<form method="post" action="{e(action)}"{ask}>{ui.hidden(self.csrf, **fields)}<button type="submit" '
                f'class="sw{" on" if on else ""}" role="switch" aria-checked="{str(on).lower()}" aria-label="{e(label)}">'
                f'<span></span></button></form>')

    def _proxy_row(self) -> str:
        """Advanced: send the popularity refresh through a proxy or VPN address the owner supplies."""
        from magpiary import proxy
        now = proxy.get()
        field = (f'<form method="post" action="/hub/control" class="proxyf">{ui.hidden(self.csrf, part="statsproxy", action="save", next="/settings/storage")}'
                 f'<input type="text" name="address" autocomplete="off" spellcheck="false" aria-label="Proxy address" '
                 f'placeholder="{e(proxy.mask(now)) if now else "socks5://host:port"}" value="">'
                 f'<button type="submit" class="btn sm dark">Save</button></form>')
        extra = ((self._form("/hub/control", {"part": "statsproxy", "action": "test", "next": "/settings/storage"}, "Test", "btn sm")
                  + self._form("/hub/control", {"part": "statsproxy", "action": "remove", "next": "/settings/storage"}, "Remove", "btn sm")) if now else "")
        return _row("Proxy for popularity refreshes", "Optional. Instagram and YouTube refreshes go out through an address you paste from your own VPN or proxy service." + (" One is saved." if now else ""),
                    lead=ui.icon("refresh"),
                    more=f'<div class="proxyline">{field}{extra}</div>' + _more("<p>Use <code>http://</code>, <code>https://</code> or <code>socks5://</code>, then <code>user:password@host:port</code> if it needs a login. "
                               "It is kept in your config folder with the keys, never shown back and never logged. Only these refreshes use it: not your downloads, "
                               "your Instagram login, the phone link or the AI. The proxy's owner can see which post addresses are asked for. "
                               "It cannot get past a login wall; it only helps when a site is limiting this Mac. A VPN app that covers the whole Mac works too, with no setting.</p>"))

    def _qr_block(self, token_url: str, name: str, back: str = "/settings/phones") -> str:
        """The QR code for a new phone, as a dialog over the page: a ring that empties over the code's 15 minutes, and
        three steps that tick themselves off as the phone opens the page, gets the Shortcut and sends its first share."""
        if not token_url.startswith(f"http://{self.setup.host_name}:"):
            return ""
        st = self.setup.status(token_url) or {"left": 0, "opened": False, "downloaded": False, "shared": False}
        reached = 3 if st["shared"] else 2 if st["downloaded"] else 1 if st["opened"] else 0
        steps = (("Open the install page", "Tap the banner the iPhone Camera shows.", "Waiting for the phone…",
                  f"Opened on {name}"),
                 ("Get the Shortcut", "Tap <b>Get the Shortcut</b>, then <b>Download</b>.", "Waiting for the download…",
                  "Shortcut downloaded"),
                 ("Add it and share one post", "Add Shortcut, then share any reel to Magpiary.", "Waiting for a share…",
                  "First share arrived"))
        ticks = "".join(
            f'<li class="{"pd" if i < reached else "pn" if i == reached else ""}" data-wait="{e(wait)}" data-done="{e(done)}">'
            f'<span class="pdot"><i>{i + 1}</i>{ui.icon("check")}</span><div><b>{head}</b><span>{text}</span>'
            f'<em>{e(done if i < reached else wait if i == reached else "")}</em></div></li>'
            for i, (head, text, wait, done) in enumerate(steps))
        renew = ui.button_form(self.csrf, "/hub/phones/new-code", {"name": name, "next": back}, "Make a new code", "btn")
        state = "paired" if st["shared"] else "sent" if st["downloaded"] else "dead" if not st["left"] else ""
        return (f'<div class="dlg-wrap qrwrap" data-close="{e(back)}"><div class="dlg pairdlg {state}" role="dialog" '
                f'aria-modal="true" aria-label="Pair {e(name)}" data-pair="{e(token_url)}" data-left="{st["left"]}">'
                f'<div class="pcol"><div class="pring"><svg viewBox="0 0 300 300" aria-hidden="true"><defs><linearGradient '
                f'id="pgrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2f6bff"/><stop offset="1" '
                f'stop-color="#8a3ffc"/></linearGradient></defs><rect class="ptrack" x="3" y="3" width="294" height="294" '
                f'rx="30" pathLength="100"/><rect class="pprog" x="3" y="3" width="294" height="294" rx="30" '
                f'pathLength="100"/></svg><div class="pcode">{self.setup.qr_svg(token_url)}</div><div class="pover">'
                f'<b>This code ran out</b>{renew}</div></div><div class="pleft"><b></b><small></small></div></div>'
                f'<div class="pinfo"><div class="pkick">Pair a phone</div><h3>Scan with <em>{e(name)}</em></h3>'
                f'<p>Point the iPhone Camera at the code. The steps tick themselves off as they happen.</p>'
                f'<ol class="pticks">{ticks}</ol><div class="pdone">{ui.icon("check")}{e(name)} is paired. Its shares '
                f'arrive here.</div><div class="pfoot"><div class="plink"><span class="small muted">Can\'t scan? Send this link to '
                f'the iPhone (AirDrop or Messages) and open it there.</span><div class="purl"><span class="mono">'
                f'{e(token_url)}</span><button type="button" class="btn sm" data-copycode="{e(token_url)}" '
                f'data-copywhat="Install link">{ui.icon("copy")}Copy</button></div></div><a class="btn dark" '
                f'href="{e(back)}" data-qrdone>Done</a></div></div></div></div>')

    def phones_post(self, path: str, form: dict) -> Response | None:
        """Pairing from Settings or the first-run guide. None for a path this does not handle."""
        if path not in ("/hub/phones/add", "/hub/phones/new-code", "/hub/phones/remove", "/hub/browsers/add"):
            return None
        back = form.get("next", "/settings/phones")
        back = back if back in ("/settings/phones", "/settings/storage", "/welcome/phone") else "/settings/phones"
        if not self.setup:
            return Response(303, b"", headers={"Location": back + "?error=" + quote("Pairing runs with the background service.")})
        name = form.get("name", "").strip()
        if path == "/hub/phones/remove":
            self.store.revoke_phone(name)
            return Response(303, b"", headers={"Location": back + "?saved=phone"})
        if path == "/hub/browsers/add":  # the Chrome extension: a one-time code to paste into it (15 minutes)
            name, code = self.setup.pair_browser("Chrome")
            return Response(303, b"", headers={"Location": f"{back}?chromecode={quote(code)}"})
        try:
            if path == "/hub/phones/add":
                name, url = self.setup.pair(name, form.get("home_wifi", ""),
                                            int(form["retry_wait"]) if form.get("retry_wait", "").isdigit() else DEFAULT_RETRY_WAIT)
            else:
                url = self.setup.renew(name)
                if url is None:
                    raise ValueError("That phone is not paired.")
        except ValueError as err:
            return Response(303, b"", headers={"Location": back + "?error=" + quote(str(err))})
        return Response(303, b"", headers={"Location": f"{back}?qr={quote(url, safe='')}&phone={quote(name)}"})

    # ---- Library & this Mac, Appearance, Privacy ------------------------------------------------

    def _folders(self) -> dict:
        from magpiary import config

        lib = Path(self.library or config.data_dir() / "library")
        return {"library": lib, "notes": lib.parent / "notes", "models": lib.parent / "models", "identity": identity._key_path().parent,
                "backups": lib.parent / "backups"}

    def _finder(self, which: str, back: str) -> str:
        return self._form("/hub/reveal", {"which": which, "next": back}, "Show in Finder", "btn sm")

    def _downloads_group(self) -> str:
        from magpiary import downloads

        entries = downloads.catalog()
        rows = "".join(_row(e(d.name), f'{e(d.why)} From {e(d.source)} · <b class="size">{e(downloads.human_size(d.bytes))}</b>',
                            _stat("On this Mac", "ok") if d.installed else _stat("Not here yet", "idle"), info=d.url, cls="keep")
                       for d in entries)
        in_app = in_mac_app()
        if in_app:
            rows += _fold("Already inside the app", "Not downloaded", "".join(_row(e(name), e(why), cls="small") for name, why in downloads.INCLUDED))
        return _group("What Magpiary downloads", rows, gid="downloads",
                      desc=f"Fetched once during setup, {e(downloads.human_size(downloads.total_bytes(entries)))} in all. Nothing about you or your saves is sent."
                           + (" The app checks each file against its published checksum before using it." if in_app else ""))

    def _backup_files(self, folder: Path) -> list[Path]:
        """Backups in the Backups folder, newest first: database copies only (a half-made .part is never one)."""
        try:
            return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix == ".db"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return []

    def _restore_row(self, folder: Path) -> str:
        files = self._backup_files(folder)
        if not files:
            return _row("Restore from a backup", "No backups yet. Press Back up now to make one. A backup made earlier, or on another Mac, "
                        "can be put into the Backups folder and will show up here.", lead=ui.icon("refresh"), sid="restore")
        options = "".join(f'<option value="{e(p.name)}">{e(datetime.fromtimestamp(p.stat().st_mtime).strftime("%-d %b %Y, %H:%M"))} '
                          f'· {e("under 1 MB" if p.stat().st_size < 1_000_000 else _mb(p.stat().st_size))} · {e(p.name)}</option>' for p in files[:30])
        form = (f'<form method="post" action="/hub/restore" class="restoreform" data-busy-label="Restoring…" '
                f'data-confirm="Replace your library with this backup? Everything saved after it was made (posts, notes, boards, '
                f'paired phones) is replaced. Magpiary first copies what you have now into the Backups folder, so you can undo this.">'
                f'{ui.hidden(self.csrf)}<select name="file" aria-label="Backup to restore">{options}</select>'
                f'<button class="btn sm danger" type="submit">Restore…</button></form>')
        return _row("Restore from a backup", "Puts your saves, notes and boards back as they were when the backup was made. "
                    "Your current library is kept as a safety copy first.", form, lead=ui.icon("refresh"), sid="restore")

    def _storage_section(self, q: dict) -> str:
        folders = self._folders()
        trash = self.store.hub_counts()["shelves"].get("trash", 0)
        what = {"library": ("Library", "Videos, photos, captions, transcripts and frames"),
                "notes": ("Notes", "One Markdown note per post; works with Obsidian"),
                "models": ("Models", "The speech model, and the small model that finds related posts and piles")}
        rows = "".join(_row(name, f'{e(text)} · <b class="size">{_mb(_folder_size(folders[k]))}</b>',
                            self._finder(k, "/settings/storage"), lead=ui.icon("folder"),
                            info=f"Folder: {folders[k]}", cls="keep")
                       for k, (name, text) in what.items())
        trash_controls = ('<a class="btn sm" href="/?shelf=trash">Open the Trash</a>'
                          + (self._form("/hub/empty-trash", {"next": "/settings/storage"}, "Empty", "btn sm danger",
                                        confirm="Delete everything in the Trash for good, with its files?") if trash else ""))
        trash_group = _group("Trash", _row(f'{trash} post{"" if trash == 1 else "s"} in the Trash',
                                       f"Removed posts wait {TRASH_DAYS} days, then they and their files are deleted for good.",
                                       trash_controls, lead=ui.icon("trash"),
                                       info="Sharing a post again brings it back from the Trash."), gid="trash")
        uninstall = _group("Removing Magpiary",
                           _row("Uninstall", "Removes the app, its service and its downloads. It asks first whether to keep your library.",
                                '<a class="btn sm" href="magpiary://uninstall">Uninstall…</a>', lead=ui.icon("alert"))
                           if in_mac_app() else
                           _row("Uninstall", 'In Terminal, run <code>magpiary uninstall</code>.',
                                info="It stops the service and removes the program. Your library folder stays unless you add "
                                     "--delete-library.", lead=ui.icon("alert")), gid="remove")
        auto = self.store.get_setting("stats_auto", "1") == "1"
        pop = _group("Popularity numbers",
                     _row("Refresh them each week", "Likes, comments and views of your newest posts are read again, slowly.",
                          self._switch("/hub/control", auto, {"part": "statsauto", "action": "pause", "next": "/settings/storage"},
                                       {"part": "statsauto", "action": "resume", "next": "/settings/storage"}, "Refresh popularity numbers weekly"),
                          lead=ui.icon("refresh"),
                          more=_more("<p>They decide which posts get the big tiles and the Most popular order. Only the post's details are "
                                     "read (no download, no AI): a post every few minutes, a few a day per site, never in a burst, so a site does not "
                                     "mistake this Mac for a robot. You can also refresh chosen posts: Select, then Refresh stats. Progress shows in the Nest.</p>")),
                     gid="popularity")
        awake = getattr(getattr(self, "keep_awake", None), "running", False)
        from magpiary import __version__
        from magpiary import update

        port = self.setup.port if self.setup else DEFAULT_PORT
        last_backup = self.store.get_setting(BACKUP_SETTING, "")
        backup = _row("Back up now", f"Last one: {e(ui.day(last_backup))}." if last_backup else "",
                      ui.button_form(self.csrf, "/hub/backup", {}, "Back up now", "btn sm dark", busy="Backing up…")
                      + (self._finder("backups", "/settings/storage") if folders["backups"].exists() else ""),
                      lead=ui.icon("copy"), sid="backup")
        restore = self._restore_row(folders["backups"])
        checking = self.store.get_setting(update.CHECK_SETTING, "1") != "0"
        about = (_row("Magpiary", f"Version {e(__version__)}", lead=ui.icon("info"), cls="keep")
                 + _row("Support Magpiary", "Free, with no ads. If it helps you, a coffee covers the costs of keeping it going. Opens in your browser.",
                        f'<a class="btn sm" href="{SUPPORT_URL}" target="_blank" rel="noopener">Buy me a coffee ↗</a>',
                        lead=ui.icon("heart"), sid="support")
                 + _row("Check for new versions", "The switch asks GitHub for the latest version number once a day. Nothing about you is sent.",
                        ui.button_form(self.csrf, "/hub/versioncheck/now", {}, "Check now", "btn sm", busy="Checking…")
                        + self._switch("/hub/versioncheck", checking, {"enabled": "0", "next": "/settings/storage"},
                                       {"enabled": "1", "next": "/settings/storage"}, "Check for new versions every day"), lead=ui.icon("refresh"), sid="versioncheck"))
        receiver = _group("How this Mac listens",
                          _row("Receiver", f"Port {port} · starts at login, restarts if it stops", cls="small",
                               info="Where your phones send to. These pages only open on this Mac.")
                          + _row("Firewall", "If it's on, macOS may ask to allow incoming connections the first time a phone "
                                             "connects. Choose Allow.", cls="small"), gid="receiver")
        return (_group("Your library", rows + backup + restore, gid="library",
                       desc="Everything is in folders you own: a database, the archived media and a note per post.")
                + trash_group
                + self._chrome_group(q)
                + _group("Keep this Mac awake",
                         _row("Keep awake while plugged in", "So shares arrive and are read overnight.",
                              self._switch("/hub/awake", awake, {"enabled": "0", "next": "/settings/storage"},
                                           {"enabled": "1", "next": "/settings/storage"}, "Keep this Mac awake"),
                              more=_more("<p>A sleeping Mac can't receive links: the phone's share waits about a minute and "
                                         "fails (nothing is lost). While this is on, the Mac doesn't sleep by itself when plugged "
                                         "in. On battery it changes nothing, and closing a laptop's lid still puts it to sleep.</p>")),
                         gid="awake")
                + _group("Health check",
                         '<div class="hrun"><span class="hico">' + ui.icon("health") + '</span><div class="hrt"><b>Check everything'
                         + _info("Nothing runs until you press it. The site test makes one request per site, using your newest save from it. "
                                 "Keys are checked without using any quota.") + '</b><p>The tools, models, service, keys and each site.</p></div>'
                         '<a class="btn dark" href="/doctor" data-health>Run the checks</a></div>'
                         '<label class="hopt"><input type="checkbox" id="health-live"><span class="hsw"></span>'
                         '<span><b>Also test each site and key</b><small>One request each. Takes up to a minute.</small></span></label>',
                         gid="health", cls="feat health hero mint")
                + pop
                + _group("About this Mac", about, gid="mac")
                + self._downloads_group()
                + _adv(_group("Popularity refresh", self._proxy_row(), gid="popproxy") + receiver + uninstall,
                       "Refresh proxy, receiver, firewall, uninstall"))

    def _digest_group(self, q: dict) -> str:
        from magpiary import digest as dg

        back = "/settings/ai#digest"
        day, hour = dg.schedule(self.store)
        every = self.store.get_setting(dg.EVERY, "monthly")
        def pills(name: str, choices: list, current) -> str:
            return "".join(f'<label class="pillc"><input type="radio" name="{name}" value="{k}"{" checked" if str(k) == str(current) else ""}>'
                           f"<span>{e(label)}</span></label>" for k, label in choices)

        hours = "".join(f'<option value="{h}"{" selected" if h == hour else ""}>{h:02d}:00</option>' for h in range(24))
        when = (f'<form method="post" action="/hub/digest/when" class="dgform" data-autosubmit>{ui.hidden(self.csrf, next=back)}'
                f'<div class="dghead"><span class="slead">{ui.icon("digest")}</span><div class="srl"><b>How often{_info("A monthly digest comes on the 1st; the day applies to the weekly one.")}</b>'
                f"<p>What your saves were about and what's worth acting on.</p></div></div>"
                f'<div class="dgpick"><div class="pillbar" role="radiogroup" aria-label="How often">{pills("every", list(dg.EVERY_CHOICES.items()), every)}</div>'
                f'<div class="pillbar dgday" role="radiogroup" aria-label="Day for the weekly one">{pills("day", [(n, d[:3]) for n, d in enumerate(dg.DAYS)], day)}</div>'
                f'<label class="selbox dgtime"><span>at</span><select name="hour" aria-label="Time">{hours}</select></label></div></form>')
        goals = self.store.get_setting(dg.GOALS, "")
        goals_row = _row("Your goals", (f"Its “Worth doing” picks lean toward: {e(goals[:90])}{'…' if len(goals) > 90 else ''}" if goals
                                        else "None yet, so its “Worth doing” picks are guessed from your saves."),
                         '<a class="btn sm" href="/settings/profile#goals">Edit</a>', lead=ui.icon("sparkle"), sid="digest-goals", cls="keep")
        from magpiary import engines

        private = modes.current(self.store) == "private"
        if private:
            intro = '<p class="sinfo">Private mode: digests show the words, numbers and piles, with no written summary.</p>'
            return _group("Digest", f'<div class="dgset">{when}</div>' + goals_row, gid="digest", cls="feat dgfeat hero gold", status=intro)
        on = engines.is_on(self.store, "digest")
        free = engines.only_free(self.store)
        switch = self._switch("/hub/digest/on", on, {"enabled": "0", "next": back}, {"enabled": "1", "next": back}, "Digest",
                              confirm=engines.warning("digest") if (free and not on) else "", ok="I understand, turn it on")
        more = '<p class="small">It needs an AI key, or Claude Code or Codex allowed in AI keys.</p>' if not on and not engines.options(self.store) else ""
        rows = _row("Digest", "What your saves were about and what's worth acting on, written for you each week or month.", switch,
                    lead=ui.icon("digest"), sid="digest-on", more=more)
        if on:
            usable = engines.options(self.store)
            chosen = engines.choice(self.store, "digest")
            writer = (f'<form method="post" action="/hub/digest/engine" class="deepengine" data-autosubmit>{ui.hidden(self.csrf)}'
                      f'<label class="deeppick"><span>Written by</span><select name="engine" aria-label="Written by">'
                      + "".join(f'<option value="{e(o["id"])}"{" selected" if chosen and o["id"] == chosen["id"] else ""}>'
                                f'{e(o["label"])}{" (free)" if o["free"] else ""}</option>' for o in usable)
                      + "</select></label></form>") if len(usable) > 1 else ""
            rows += (f'<div class="dgset">{when}</div>' + goals_row
                     + _row("Written by", (f"{e(chosen['label'])}." if chosen and len(usable) == 1 else
                                           "Pick who writes it. It never moves to another one without you."), writer,
                            lead=ui.icon("sparkle"), sid="digest-writer"))
        return _group("Digest", rows, gid="digest", cls="feat dgfeat hero gold",
                      info="Each save's summary, the first 300 words of what was said and your goals are sent to write it. Videos never leave this Mac.")

    # ---- Shared boards -------------------------------------------------------------------

    def _send_profile(self) -> None:
        """Friends get a change to your profile at the next sync."""
        from magpiary import boards

        boards.republish_profile(self.store)
        self.sync_boards()

    def _profile_section(self, q: dict) -> str:
        """Your face, links, goals and topics, then your boards; one Advanced block holds the identity key and board sync."""
        main, identity_group = self._profile_part(q)
        boards, sync, broken = self._boards_part(q)
        return main + boards + _adv(identity_group + sync, "Your key, relays and your own storage bucket", attention=broken)

    def _profile_part(self, q: dict) -> tuple[str, str]:
        """The owner's own profile, as friends see it, edited right in it: click the face for photo and colour, click the
        name or the about line to change them (each with its own Save). Links and topics are below."""
        me = identity.profile(self.store)
        back = "/settings/profile"
        photo = photo_url() if me["photo"] else ""
        shown_name = me["name"] or "Your name"
        hidden = ui.hidden(self.csrf, next=back)
        pencil = ui.icon("summary")
        photo_ctl = (f'<form method="post" action="/hub/profile/photo" class="pavrow" id="photoform">'
                     f'{ui.hidden(self.csrf, next=back, photo="")}<label class="btn sm filebtn">{"Change photo" if me["photo"] else "Choose a photo"}'
                     f'<input type="file" accept="image/jpeg,image/png,image/webp,image/heic" id="photopick"></label></form>'
                     + (self._form("/hub/profile/photo/remove", {"next": back}, "Remove", "btn sm") if me["photo"] else ""))
        colours = (f'<form method="post" action="/hub/profile" class="swatches">{hidden}' + "".join(
            f'<button type="submit" name="colour" value="{k}" class="swatch{" on" if k == me["colour"] else ""}" '
            f'style="--c:{k}" title="{v}" aria-label="{v}" aria-pressed="{str(k == me["colour"]).lower()}"></button>'
            for k, v in identity.COLOURS.items()) + "</form>")
        avatar = (f'<div class="pavedit"><button type="button" class="pavbtn" data-pavpop aria-expanded="false" '
                  f'aria-label="Change your photo or colour">{ui.avatar(shown_name, me["colour"], photo, "xl")}'
                  f'<span class="pcam">{ui.icon("plus")}</span></button><div class="pavpop" data-pavbox hidden>'
                  f'<p>Photo is shrunk to {identity.PHOTO_SIZE} px on this Mac, without where or when it was taken.</p>'
                  f'<div class="pavacts">{photo_ctl}</div><p>Colour</p>{colours}</div></div>')
        name = (f'<form method="post" action="/hub/profile" class="ped" data-ed>{hidden}<div class="pedview">'
                f'<b>{e(shown_name)}</b><button type="button" class="pedbtn" data-edopen aria-label="Edit your name">{pencil}</button></div>'
                f'<div class="pedform" hidden><input type="text" name="name" value="{e(me["name"])}" maxlength="{identity.NAME_MAX}" '
                f'placeholder="Your name" aria-label="Your name" required><button class="btn sm dark">Save</button>'
                f'<button type="button" class="btn sm" data-edcancel>Cancel</button></div></form>')
        about = (f'<form method="post" action="/hub/profile/about" class="ped pedabout" data-ed>{hidden}<div class="pedview">'
                 + (f'<p class="pabout">{e(me["about"])}</p><button type="button" class="pedbtn" data-edopen aria-label="Edit your about line">{pencil}</button>'
                    if me["about"] else f'<button type="button" class="pedadd" data-edopen>{pencil}<span>Add a line about you</span></button>')
                 + f'</div><div class="pedform" hidden><textarea name="about" rows="3" maxlength="{identity.ABOUT_MAX}" '
                 f'placeholder="What you collect, what you\'re into" aria-label="About you">{e(me["about"])}</textarea>'
                 f'<span class="pedacts"><button class="btn sm dark">Save</button><button type="button" class="btn sm" data-edcancel>Cancel</button>'
                 f'<small>Up to {identity.ABOUT_MAX} characters</small></span></div></form>')
        card = self._person(
            {
                "key": identity.public_key(),
                "name": shown_name,
                "colour": me["colour"],
                "photo_url": photo,
                "about": "",
                "links": me["links"],
                "topics": me["topics"],
            },
            edit={"avatar": avatar, "name": name, "about": about},
        )
        hints = {"website": "Website address, like yourname.com", "instagram": "Instagram handle, like example.maker",
                 "x": "X handle", "github": "GitHub username"}
        links = (f'<form method="post" action="/hub/profile/links" class="plinkform" data-dirty>{hidden}<div class="lchips">' + "".join(
            f'<label class="lchip{" filled" if me["links"].get(slot) else ""}" title="{e(hints[slot])}">{ui.social_icon(slot)}'
            f'<input type="text" name="{slot}" value="{e(me["links"].get(slot, ""))}" placeholder="{self.LINK_LABELS[slot]}" '
            f'aria-label="{e(hints[slot])}" maxlength="200" autocomplete="off" spellcheck="false"></label>' for slot in identity.LINK_SLOTS)
            + '</div><div class="pform-acts" hidden><button class="btn sm dark">Save changes</button>'
            '<button type="button" class="btn sm" data-dirtycancel>Cancel</button></div></form>')
        rows = identity.topic_rows(self.store)
        topic_chips = "".join(
            f'<form method="post" action="/hub/profile/topic" class="tchip{" auto" if auto else ""}">'
            f'{ui.hidden(self.csrf, next=back, topic=t, act="remove")}<span>{e(t)}</span>'
            f'<button aria-label="Take {e(t)} off your profile" title="Take it off">×</button></form>' for t, auto in rows)
        topics = (f'<div class="tchips">{topic_chips or "<em>No topics yet</em>"}</div>'
                  f'<div class="topicbar"><form method="post" action="/hub/profile/topic" class="topicadd" data-addtopic>{ui.hidden(self.csrf, next=back, act="add")}'
                  f'<div class="pfield-wrap"><input class="pfield" type="text" name="topic" maxlength="{identity.TOPIC_LEN}" placeholder="Add a topic of your own" '
                  f'aria-label="Add a topic" autocomplete="off"><button class="btn sm dark" disabled>Add</button></div></form>'
                  + "</div>")
        from magpiary import digest as dg

        goals = _group("Just for your AI, never shared with friends", (
            f'<div class="dgset"><form method="post" action="/hub/digest/goals" class="goalform">{ui.hidden(self.csrf, next=back + "#goals")}'
            f"<div class=\"srl\"><b>My goals</b><p>What you're working toward, in a line or two. Your digest, Ask and AI agents can use it.</p></div>"
            f'<textarea name="goals" rows="3" maxlength="{dg.GOALS_MAX}" placeholder="Launch my business; brew better coffee" '
            f'aria-label="My goals">{e(self.store.get_setting(dg.GOALS, ""))}</textarea><div class="cacts"><button class="btn sm dark" type="submit">Save</button></div></form></div>'),
            gid="goals", lock="goals")
        return (_group("Your public face", f'<div class="pcardwrap">{card}</div>', gid="profile", lock="profile",
                       desc="This is what friends see when they click your face on a board. Click your face, name or about line to change them."
                            + ("" if self.store.boards() else " You're on no boards yet, so nobody sees it."))
                + _group("Links", f'<div class="srow pfull">{links}</div>', gid="links",
                         desc="Where to find you. Only what you fill in is shown, each with its logo.")
                + goals
                + _group("Topics", f'<div class="srow pfull">{topics}</div>', gid="topics",
                         desc="From your biggest piles; take off any you don't want to show, or add your own.")
                , _group("Your identity", _row(
                    "Your key", "Made on this Mac. It signs everything you add to a board, so nobody can act as you. It never leaves this Mac.",
                    f'<button type="button" class="btn sm" data-copy="{e(identity.public_key())}">{ui.icon("copy")}Copy ID</button>'
                    + self._finder("identity", "/settings/profile"), lead=ui.icon("lock"),
                    info=f"Stored at {identity._key_path()} with owner-only access. It is a Nostr-compatible key; your short ID is its first "
                         "characters, so friends can tell two people with the same name apart."), gid="identity"))

    def _boards_part(self, q: dict) -> tuple[str, str, bool]:
        from magpiary.hub_boards import new_board_via

        mine = boardsync.load_bucket()
        found = self.store.boards()
        broken = [b for b in found if b["sync_error"]]
        if broken:
            line = _status(f'{len(broken)} board{"" if len(broken) == 1 else "s"} couldn\'t sync. Open Advanced settings to check the relays or your bucket.', "bad")
        elif mine and new_board_via(self.store) == "bucket":
            line = _status("New boards sync through your own bucket.", "ok")
        else:
            line = _status("Boards sync through free public relays. Nothing to set up.", "ok")
        top = self._boards_group(q) or _group("Your boards", _row("No boards yet", "Make or join one under Library → Boards.", cls="emptyrow"), gid="boards")
        return top.replace('</header>', '</header>' + line, 1), self._sync_group(), bool(broken)

    def _boards_group(self, q: dict) -> str:
        from magpiary import boards

        back, me = "/settings/profile", identity.public_key()
        rows = ""
        found = self.store.boards()
        for b in found:
            v = boards.view(self.store, b["id"])
            via = "Nostr relays" if b["via"] == "nostr" else "your bucket" if b["creator"] == me else "the creator's bucket"
            from magpiary.hub_boards import sync_words

            state = (f'<span class="kstat bad" title="{e(b["sync_error"])}"><i></i>{e(sync_words(b["sync_error"]))}</span>' if b["sync_error"] else
                     f'Synced {e(ago(b["synced_at"]))} through {via}' if b["synced_at"] else f"Not synced yet · {via}")
            rows += _row(f'<a class="link" href="/board/{b["id"]}">{e(v["name"])}</a>',
                         f'{len(v["members"])} member{"" if len(v["members"]) == 1 else "s"} · '
                         f'{len(v["cards"])} card{"" if len(v["cards"]) == 1 else "s"} · {state}', lead=ui.icon("people"), cls="keep")
        if not found:
            return ""
        return _group("Your boards", rows, gid="boards", tag=str(len(found)),
                      desc="Boards sync every 15 minutes while this Mac is awake, and soon after you change one. "
                           "Invite friends and join boards under Library → Boards.",
                      action=ui.button_form(self.csrf, "/hub/boards/sync", {"next": back}, ui.icon("refresh") + "Sync now", "btn sm"))

    def _sync_group(self) -> str:
        back = "/settings/profile"
        relays = ", ".join(boardsync._host(r) for r in boardsync.RELAYS)
        nostr = _row("Nostr relays", f"The default: free public relays ({e(relays)}). Nothing to sign up for.",
                     self._form("/hub/boards/check-relays", {"next": back}, "Check relays", "btn sm"),
                     lead=ui.icon("links"), info="Relays are run by volunteers and small companies. They may drop old "
                     "posts, so a group that wants dependable sync can use its own bucket instead.")
        mine = boardsync.load_bucket()
        if mine:
            bucket = _row(e(boardsync.PROVIDERS.get(mine["provider"], "Own bucket")),
                          f'Bucket <span class="mono">{e(mine["bucket"])}</span> · connected {e(mine.get("added", ""))}. '
                          "Boards you create can sync here instead of the relays.",
                          self._form("/hub/boards/check-bucket", {"next": back}, "Check", "btn sm")
                          + self._form("/hub/boards/remove-bucket", {"next": back}, "Remove", "btn sm danger",
                                       confirm="Remove the bucket from this Mac? Its boards stop syncing here; "
                                               "the bucket and what's in it stay with the storage service."),
                          lead=ui.icon("folder"))
            from magpiary.hub_boards import new_board_via

            via = new_board_via(self.store)
            choice = (f'<form method="post" action="/hub/boards/via" class="seg">{ui.hidden(self.csrf, next=back)}'
                      + "".join(f'<button type="submit" name="via" value="{k}" class="{"on" if k == via else ""}" '
                                f'aria-pressed="{str(k == via).lower()}">{label}</button>'
                                for k, label in (("nostr", "Nostr relays"), ("bucket", "Your bucket"))) + "</form>")
            bucket += _row("New boards sync through", "Boards you already made keep where they sync.", choice,
                           lead=ui.icon("plus"))
        else:
            spare = boardsync.saved_b2_env()
            b2_form = (f'<form method="post" action="/hub/boards/b2" class="sform">{ui.hidden(self.csrf, next=back)}'
                       '<label>keyID<input name="key_id" autocomplete="off" spellcheck="false" required></label>'
                       '<label>applicationKey<input name="key" type="password" autocomplete="off" required></label>'
                       '<button class="btn sm dark">Connect</button></form>')
            s3_form = (f'<form method="post" action="/hub/boards/s3" class="sform">{ui.hidden(self.csrf, next=back)}'
                       '<label>Service<select name="provider"><option value="r2">Cloudflare R2</option>'
                       '<option value="s3">Another S3 service</option></select></label>'
                       '<label>Address (S3 API)<input name="endpoint" placeholder="https://….r2.cloudflarestorage.com" '
                       'spellcheck="false" required></label><label>Bucket name<input name="bucket" spellcheck="false" required></label>'
                       '<label>Access key ID<input name="key_id" autocomplete="off" spellcheck="false" required></label>'
                       '<label>Secret access key<input name="secret" type="password" autocomplete="off" required></label>'
                       '<button class="btn sm dark">Connect</button></form>')
            steps = ('<div class="bkstep"><span class="on"><i>1</i>Pick a service</span><span><i>2</i>Paste its key</span>'
                     '<span><i>3</i>Connected</span></div>')
            bucket = (_row("Your own bucket", "Optional, for dependable sync. You sign up once with a storage service; "
                           "friends you invite get a key limited to your boards.",
                           self._form("/hub/boards/b2-env", {"next": back}, "Use my saved Backblaze key", "btn sm dark")
                           if spare else _stat("Not connected", "idle"), lead=ui.icon("folder"),
                           more=steps + _more(f"<p>Backblaze B2: free up to 10 GB. Paste the main key (Application Keys → "
                                      f"Generate New Master Application Key); Magpiary makes a private bucket and the "
                                      f"keys it needs.</p>{b2_form}", "Connect Backblaze B2")
                           + _more(f"<p>Cloudflare R2 or another S3 service: make a bucket and a key that may read and "
                                   f"write it, then fill these in.</p>{s3_form}", "Connect Cloudflare R2 or another")))
        return _group("Where boards sync", nostr + bucket, gid="sync", lock="sync",
                      desc="Each board syncs through Nostr relays (the default) or your own bucket.")

    def _sync_one_board(self, board_id: str) -> Response:
        """Sync now on a board's page: sync it here and now, and when that fails, check each relay and say which
        answered. Back to the board either way."""
        from magpiary import boards
        from magpiary.hub_boards import sync_words

        back = f"/board/{board_id}?"
        boards.settle_pending(self.store, self.library)
        board = self.store.board(board_id)
        connector = boards.connector_for(board, self.relay_connect, self.sync_call)
        result = (boards.sync(self.store, board_id, connector, self.sync_call, self.relay_connect) if connector
                  else {"ok": False, "got": 0, "error": "No bucket is connected on this Mac."})
        if result["ok"]:
            got = result["got"]
            note = f"Synced: {got} new change{'' if got == 1 else 's'} from friends." if got else "Synced: up to date."
            return Response(303, b"", headers={"Location": back + "note=" + quote(note)})
        words = sync_words(result["error"]).replace(" Trying again in 15 minutes.", "")
        if board["via"] == "nostr":
            status = boardsync.Nostr(connect=self.relay_connect).check()
            words += " " + "; ".join(f"{n}: {'answered' if ok else d}" for n, ok, d in status.parts) + "."
        return Response(303, b"", headers={"Location": back + "error=" + quote(words[:300])})

    def _look_section(self, q: dict) -> str:
        look = ui.appearance(self.store)
        width = "full" if look["layout"] == "full" else str(look["box"])

        def picks(name: str, choices: list, current: str) -> str:
            return (f'<form method="post" action="/hub/ui" class="picks">{ui.hidden(self.csrf, next="/settings/appearance")}'
                    + "".join(f'<button type="submit" name="{name}" value="{k}" class="pick{" on" if k == current else ""}" '
                              f'aria-pressed="{str(k == current).lower()}">{art}<span>{e(label)}</span></button>'
                              for k, label, art in choices) + "</form>")

        def bar(name: str, choices: list, current: str) -> str:
            return (f'<form method="post" action="/hub/ui" class="segbar" role="radiogroup">{ui.hidden(self.csrf, next="/settings/appearance")}'
                    + "".join(f'<button type="submit" name="{name}" value="{k}" role="radio" class="{"on" if k == current else ""}" '
                              f'aria-checked="{str(k == current).lower()}">{e(label)}</button>' for k, label in choices) + "</form>")

        art = settings_art
        return (_group("Theme", picks("theme", [(k, v, art.theme(k)) for k, v in ui.THEMES.items()], look["theme"]),
                       desc="Indigo is colourful; Dark is plainer.", gid="theme", cls="plain")
                + _group("Tile size", picks("size", [(k, v.replace(" tiles", ""), art.tiles(k)) for k, v in ui.SIZES.items()],
                                            look["size"]),
                         desc="The same as the tile-size control above the wall.", gid="tiles", cls="plain")
                + _group("Fine tuning", _row("Tile labels", "The text on each tile.", bar("labels", list(ui.CHOICES["labels"].items()), look["labels"]),
                                             info="Black overlay: a dark fade over the picture, with small coloured dots for the source and the "
                                                  "kind. Coloured: the label takes the colour of the kind of post.", sid="labels")
                              + _row("Glass", "Floating layers turn see-through, with blur and a bright top edge.", bar("glass", list(ui.CHOICES["glass"].items()), look["glass"]),
                                                  info="On: the nav, search, sheets, pop-ups and corner buttons float as glass, in both themes. "
                                                       "Off: plain solid surfaces.", sid="glass")
                              + (_row("Glass strength", "How much the surfaces glow, blur and lift.",
                                      f'<form class="glasslvl" id="glasslvl" onsubmit="return false">{ui.hidden(self.csrf)}'
                                      f'<input type="range" name="glass_level" min="25" max="100" step="25" value="{look["glass_level"]}" '
                                      f'aria-label="Glass strength">'
                                      '<div class="glassticks">' + "".join(f'<button type="button" data-lv="{n}"{" class=on" if n == look["glass_level"] else ""}>{n}</button>'
                                                                           for n in ui.GLASS_STOPS) + "</div></form>",
                                      info="Four steps, from a hint of glass (25%) to the full effect (100%). Moving the slider changes the whole hub at once, "
                                           "and the slider itself turns to glass as you go up.",
                                      sid="glassstrength", cls="sub") if look["glass"] == "on" else "")
                              + _row("Interface size", "How big everything is. Automatic makes it a little smaller on a laptop screen.",
                                     bar("scale", list(ui.CHOICES["scale"].items()), look["scale"]),
                                     info="Automatic: 90% when the window is narrower than 1,600 px (a 14-inch MacBook), 85% under 1,400 px, "
                                          "full size on a bigger screen. You can also pick a size. Your browser's own zoom (⌘ and − or +) still works on top.",
                                     sid="scale")
                              + _row("Page width", "How wide the hub can grow on a large screen.",
                                     bar("width", [(str(w), f"{w:,} px") for w in ui.BOX_PRESETS] + [("full", "Full")], width),
                                     info="A width only shows when the window is wider than it. Full stretches edge to edge.", sid="width"),
                              gid="tuning")
                + self._beta_group())

    def _beta_group(self) -> str:
        """Features still being tried: off unless the owner turns them on."""
        from magpiary.hub_map import map_on

        on = map_on(self.store)
        back = "/settings/appearance#betamap"
        return _group("Beta", _row("Connections map", "A Map button in the top bar and a small map on each post's Related "
                                   "tab, showing how your saves connect. Still being tried.",
                                   self._switch("/hub/beta/map", on, {"enabled": "0", "next": back}, {"enabled": "1", "next": back},
                                                "Show the Connections map"), lead=ui.icon("sparkle"), sid="betamap"),
                      gid="beta", desc="Early features. They may change or go away.")

    def _privacy_section(self, q: dict) -> str:
        mode = modes.current(self.store)
        has_search = any(keyring.PROVIDERS[k.provider]["kind"] == "search" for k in keyring.load())
        day = login.connected(self.store)
        from magpiary import agent_policy, askconfig, proxy, update
        from magpiary import digest as dg

        private = mode == "private"
        digest_on = not private and self.store.get_setting(dg.EVERY, "monthly") != "off"
        asking = askconfig.enabled(self.store)
        agents = agent_policy.enabled(self.store)
        checking = self.store.get_setting(update.CHECK_SETTING, "1") != "0"
        boards_on = bool(self.store.boards())
        routed = proxy.get()

        def leaves(icon: str, title: str, text: str, state: str) -> str:
            return _row(e(title), e(text), _stat(state, "idle" if state == "Off" else "warn"), lead=ui.icon(icon))

        journey = (
            _row("Stays on this Mac", "Your videos, transcripts, library, keys and logins. Your phone sends links straight here, with no server in between. "
                 "Nothing else ever leaves, and there is no telemetry.", _stat("Never leaves", "ok"), lead=ui.icon("lock"), cls="staysrow")
            + leaves("links", "Opening a post", "The post's address goes to the site it came from, logged out"
                     + ("; your Instagram login only when you ask, on a blocked post." if day else "."), "Always")
            + leaves("search", "Finding links", "The names a post mentions go to free directories"
                     + (" and your web search service." if has_search else "."), "Always")
            + leaves("sparkle", "Summaries", "The caption, the transcript and a few frames go to the AI service of the key in use.", "Off" if private else "On")
            + leaves("digest", "Your digest", "Each save's summary, the first 300 words of what was said and your goals go to Claude Code or your AI key.",
                     "On" if digest_on else "Off")
            + leaves("comment", "Ask Magpiary", "Your question, the saves it needs and your goals go to whoever answers.", "On" if asking else "Off")
            + leaves("people", "Shared boards", "Cards are sealed here first: relays and storage services can't read them, only board members can.", "On" if boards_on else "Off")
            + leaves("terminal", "AI agents", "An AI you connect can read what you allow, and your goals. What it does next follows that AI's own rules.", "On" if agents else "Off")
            + (leaves("refresh", "Proxy for refreshes", "The addresses of the posts being refreshed go through the proxy you set.", "On") if routed else "")
            + leaves("refresh", "Version check", "Once a day, GitHub is asked for the latest version number. Nothing about you is sent.", "On" if checking else "Off"))
        folders = self._folders()
        lives = (_row("Your library", f'<span class="path mono">{e(folders["library"].parent)}</span>The database, media and '
                      f'notes, in folders you own.', self._finder("library", "/settings/privacy"), lead=ui.icon("folder"))
                 + _row("Your keys", f'<span class="path mono">{e(keyring._path())}</span>Owner-only access; never shown '
                        'again after you save them.', lead=ui.icon("lock"))
                 + _row("Your bucket key", f'<span class="path mono">{e(boardsync._settings_path())}</span>'
                        + ("Owner-only access; it never leaves this Mac." if boardsync.load_bucket() else "No bucket connected: no file."),
                        lead=ui.icon("lock"))
                 + _row("Your board identity", f'<span class="path mono">{e(identity._key_path())}</span>Owner-only access; '
                        'it never leaves this Mac.', lead=ui.icon("lock"))
                 + _row("Instagram login", f'<span class="path mono">{e(login.login_path())}</span>'
                        + ("Owner-only access." if day else "Not connected: no file."), lead=ui.icon("lock")))
        trash = self.store.hub_counts()["shelves"].get("trash", 0)
        delete = (_row("Forget my Instagram login", "Deletes Magpiary's copy of it." if day else "Not connected.",
                       self._form("/hub/login/disconnect", {"next": "/settings/privacy"}, "Forget it", "btn sm danger",
                                  confirm="Delete Magpiary's copy of your Instagram login?") if day else "")
                  + _row("Remove all keys", "Every AI and web search key is deleted from this Mac.",
                         self._form("/hub/keys/remove-all", {"next": "/settings/privacy"}, "Remove all", "btn sm danger",
                                    confirm="Remove every AI and web search key from this Mac? Summaries wait until you add one.")
                         if keyring.load() else "")
                  + _row("Empty the Trash", f"{trash} post{'' if trash == 1 else 's'}, with their files, deleted for good.",
                         self._form("/hub/empty-trash", {"next": "/settings/privacy"}, "Empty", "btn sm danger",
                                    confirm="Delete everything in the Trash for good, with its files?") if trash else "")
                  + (_row("Delete everything", "Uninstall Magpiary from Settings, Storage, and choose to delete your library.")
                     if in_mac_app() else
                     _row("Delete everything", "In Terminal, run <code>magpiary uninstall --delete-library</code>. It "
                          "removes the program and your library folder.")))
        return (self.lock_group()
                + _group("What leaves this Mac", journey, gid="leaves",
                         desc="Everything that can go elsewhere, and exactly what. Off means nothing goes.")
                + _adv(self.activity_group()
                       + _group("Where your data lives", lives, gid="lives")
                       + _group("Delete my data", delete, gid="delete", cls="careful"), "Your activity, where your data lives, delete my data"))

    def settings_post(self, path: str, form: dict) -> bool:
        """Settings changes that end with a plain redirect to `next`. False for a path this does not handle."""
        if path == "/hub/ui":
            for name, allowed in (("size", ui.SIZES), ("theme", ui.THEMES), ("layout", ui.LAYOUTS),
                                  *ui.CHOICES.items()):
                if form.get(name) in allowed:
                    self.store.set_setting(f"ui_{name}", form[name])
            if form.get("glass_level", "").isdigit():
                self.store.set_setting("ui_glass_level", str(ui.glass_stop(form["glass_level"])))
            if form.get("box", "").isdigit():
                self.store.set_setting("ui_box", str(min(max(int(form["box"]), ui.BOX_MIN), ui.BOX_MAX)))
            width = form.get("width", "")
            if width == "full":
                self.store.set_setting("ui_layout", "full")
            elif width.isdigit() and int(width) in ui.BOX_PRESETS:
                self.store.set_setting("ui_layout", "boxed")
                self.store.set_setting("ui_box", width)
            return True
        if path == "/hub/agents/on":
            self.store.set_setting("agents_on", "1" if form.get("enabled") == "1" else "0")
            return True
        if path == "/hub/agents/perm":
            if form.get("which") in ("read", "add", "note"):
                self.store.set_setting(f"agents_{form['which']}", "1" if form.get("enabled") == "1" else "0")
            return True
        if path == "/hub/agents/limits":
            for kind in ("add", "note"):
                if form.get(kind, "").isdigit() and int(form[kind]) in (10, 30, 100, 0):
                    self.store.set_setting(f"agents_limit_{kind}", form[kind])
            return True
        if path == "/hub/agents/hide":
            tags = []
            for part in form.get("tags", "").split(","):
                tag = re.sub(r"\s+", " ", part).strip().lower()[:40]
                if tag and tag not in tags:
                    tags.append(tag)
            self.store.set_setting("agents_hide_tags", ",".join(tags[:30]))
            return True
        if path == "/hub/agents/clearlog":
            from magpiary import agent_log

            agent_log.clear()
            return True
        if path == "/hub/digest/on":
            from magpiary import engines

            engines.set_on(self.store, "digest", form.get("enabled") == "1")
            return True
        if path == "/hub/digest/engine":
            from magpiary import engines

            engines.choose(self.store, "digest", form.get("engine", ""))
            return True
        if path == "/hub/deep/on":
            from magpiary import engines as eng

            eng.set_on(self.store, "deep", form.get("enabled") == "1")
            return True
        if path == "/hub/beta/map":
            from magpiary.hub_map import BETA_SETTING

            self.store.set_setting(BETA_SETTING, "1" if form.get("enabled") == "1" else "0")
            return True
        if path == "/hub/versioncheck":
            from magpiary import update

            self.store.set_setting(update.CHECK_SETTING, "1" if form.get("enabled") == "1" else "0")
            return True
        if path == "/hub/phones/wifi":
            self.store.set_wifi_mode(form.get("name", "").strip(), form.get("mode", ""))
            return True
        if path == "/hub/extension/get":  # copy the bundled Chrome extension to a stable folder, show it, and open Chrome's page for it
            from magpiary import chrome_ext

            folder = chrome_ext.prepare()
            subprocess.run(["open", str(folder)], check=False, timeout=10)
            subprocess.run(["open", "-a", "Google Chrome", "chrome://extensions"], check=False, timeout=10, stderr=subprocess.DEVNULL)
            return True
        if path == "/hub/reveal":
            folder = self._folders().get(form.get("which", ""))
            if folder and folder.exists():
                subprocess.run(["open", str(folder)], check=False, timeout=10)
            return True
        if path == "/hub/keys/remove-all":
            for k in keyring.load():
                keyring.remove(k.id)
            return True
        if path == "/hub/digest/when":
            from magpiary import digest as dg

            if form.get("day", "").isdigit() and int(form["day"]) < 7:
                self.store.set_setting(dg.DAY, form["day"])
            if form.get("hour", "").isdigit() and int(form["hour"]) < 24:
                self.store.set_setting(dg.HOUR, form["hour"])
            if form.get("every") in dg.EVERY_CHOICES:
                self.store.set_setting(dg.EVERY, form["every"])
            return True
        if path == "/hub/digest/goals":
            from magpiary import digest as dg

            self.store.set_setting(dg.GOALS, " ".join(form.get("goals", "").split())[:dg.GOALS_MAX])
            return True
        if path == "/hub/awake":
            enabled = form.get("enabled") == "1"
            if self.setup:
                self.setup.set_awake(enabled)
            elif getattr(self, "keep_awake", None):
                (self.keep_awake.start if enabled else self.keep_awake.stop)()
                self.store.set_setting("stay_awake", "1" if enabled else "0")
            return True
        if path == "/hub/keys/order":
            from magpiary import engines as eng

            eng.set_order(self.store, [i for i in form.get("ids", "").split(",") if re.fullmatch(r"key:[0-9a-f]{8}|claude_code|codex", i)])
            return True
        if path in ("/hub/keys/up", "/hub/keys/down"):
            keyring.move(form.get("key_id", ""), -1 if path.endswith("up") else 1)
            return True
        if path == "/hub/keys/remove":
            keyring.remove(form.get("key_id", ""))
            return True
        if path == "/hub/settings/again-all":
            self.store.summarise_again()
            self.wake()
            return True
        return False

    def settings_redirects(self, path: str, form: dict) -> Response | None:
        """Settings changes that come back with a message. None for a path this does not handle."""
        if path == "/hub/engine/allow":
            from magpiary import engines as eng

            kind = form.get("kind", "")
            if kind in eng.LOCAL:
                if form.get("enabled") == "1":
                    ok, why = eng.allow(self.store, kind)
                    if not ok:
                        return Response(303, b"", headers={"Location": "/settings/ai?error=" + quote(why) + "#keys"})
                    return Response(303, b"", headers={"Location": "/settings/ai?saved=allowed#keys"})
                eng.disallow(self.store, kind)
            return Response(303, b"", headers={"Location": "/settings/ai?saved=stopped#keys"})
        if path == "/hub/askset":
            return self.askset_post(form)
        if path == "/hub/versioncheck/now":
            from magpiary import __version__
            from magpiary import update

            found = update.latest(update._get)  # asked for by hand, so it runs even with the daily check off
            if found:
                self.store.set_setting(update.LATEST_SETTING, found)
            words = ("Couldn't get an answer from GitHub. Try again later." if not found else
                     f"Version {found} is available." if update.newer(found) else f"You're up to date: version {__version__} is the latest.")
            return Response(303, b"", headers={"Location": "/settings/storage?note=" + quote(words) + "#versioncheck"})
        if path == "/hub/restore":
            folder = self._folders()["backups"]
            name = form.get("file", "")
            source = folder / name
            if not re.fullmatch(r"[A-Za-z0-9._ -]+\.db", name) or not source.is_file():
                return Response(303, b"", headers={"Location": "/settings/storage?error=" + quote("That backup was not found.") + "#restore"})
            safety = folder / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.db"
            try:
                self.store.restore_from(source, safety)
                from magpiary import boards
                boards.restore_keys(source)
            except (ValueError, OSError, sqlite3.Error) as err:
                words = str(err) if isinstance(err, ValueError) else f"The restore did not finish: {type(err).__name__}"
                return Response(303, b"", headers={"Location": "/settings/storage?error=" + quote(words) + "#restore"})
            return Response(303, b"", headers={"Location": "/settings/storage?note=" + quote(
                f"Restored from {name}. What you had before is kept as {safety.name} in the Backups folder.") + "#restore"})
        if path == "/hub/backup":
            name = f"magpiary-{datetime.now():%Y%m%d-%H%M%S}.db"
            try:
                self.store.backup_to(self._folders()["backups"] / name)
                from magpiary import boards
                boards.back_up_keys(self._folders()["backups"] / name)
            except (OSError, sqlite3.Error) as err:
                return Response(303, b"", headers={"Location": "/settings/storage?error=" + quote(f"The backup did not finish: {type(err).__name__}") + "#backup"})
            self.store.set_setting(BACKUP_SETTING, datetime.now().isoformat(timespec="seconds"))
            return Response(303, b"", headers={"Location": "/settings/storage?note=" + quote(f"Backed up as {name}.") + "#backup"})
        back = form.get("next", "/settings/ai")
        back = back if back in ("/settings/ai", "/welcome/reading") else "/settings/ai"
        if path == "/hub/phones/wait":
            ok = form.get("retry_wait", "").isdigit() and self.store.set_retry_wait(form.get("name", "").strip(), int(form["retry_wait"]))
            note = "Saved. Make a new install code so the phone gets it." if ok else ""
            return Response(303, b"", headers={"Location": "/settings/phones" + (f"?note={quote(note)}" if note else "")})
        if path == "/hub/keys/add":
            error = keyring.add(form.get("provider", ""), form.get("tier", ""), form.get("key", ""),
                                form.get("label", ""), self.call, model=form.get("model", ""))
            if error:
                return Response(303, b"", headers={"Location": back + "?error=" + quote(error)})
            if keyring.PROVIDERS.get(form.get("provider", ""), {}).get("kind") != "search" and \
                    modes.current(self.store) != "private":
                self.store.set_setting(modes.SETTING, "smart")
            self.store.summarise_again()  # anything that waited for a key gets its turn
            self.wake()
            return Response(303, b"", headers={"Location": back + "?saved=key"})
        if path == "/hub/profile/photo":
            error = identity.set_photo(form.get("photo", ""))
            self._send_profile()
            return Response(303, b"", headers={"Location": "/settings/profile" + ("?error=" + quote(error) if error else "?saved=photo")})
        if path in ("/hub/boards/b2", "/hub/boards/b2-env", "/hub/boards/s3"):
            if path == "/hub/boards/s3":
                error = boardsync.connect_s3(form.get("provider", ""), form.get("endpoint", ""), form.get("key_id", ""),
                                             form.get("secret", ""), form.get("bucket", ""), self.sync_call)
            else:
                pair = boardsync.saved_b2_env() if path.endswith("env") else (form.get("key_id", ""), form.get("key", ""))
                error = boardsync.connect_b2(*pair, self.sync_call) if pair else "No saved Backblaze key was found."
                if not error and path.endswith("env"):
                    boardsync.forget_b2_env()  # now kept in storage.json; one copy of a secret is enough
            return Response(303, b"", headers={"Location": "/settings/profile" + ("?error=" + quote(error) if error else "?saved=bucket") + "#sync"})
        if path == "/hub/boards/sync" and self.store.board(form.get("board", "")):
            return self._sync_one_board(form["board"])
        if path == "/hub/boards/sync":
            self.sync_boards()
            return Response(303, b"", headers={"Location": "/settings/profile?note=" + quote("Syncing your boards now.") + "#boards"})
        if path == "/hub/boards/via":
            self.store.set_setting("board_via", "bucket" if form.get("via") == "bucket" else "nostr")
            return Response(303, b"", headers={"Location": "/settings/profile?saved=via#sync"})
        if path == "/hub/boards/remove-bucket":
            boardsync.remove_bucket(self.sync_call)
            return Response(303, b"", headers={"Location": "/settings/profile?saved=nobucket#sync"})
        if path in ("/hub/boards/check-bucket", "/hub/boards/check-relays"):
            conn = boardsync.Nostr(connect=self.relay_connect) if path.endswith("relays") else boardsync.bucket_connector(call=self.sync_call)
            status = conn.check() if conn else boardsync.Status(False, "No bucket is connected.")
            detail = status.detail + ("" if all(ok for _, ok, _ in status.parts) else
                                      " (" + "; ".join(f"{n}: {d}" for n, ok, d in status.parts if not ok) + ")")
            return Response(303, b"", headers={"Location": "/settings/profile?" + ("note=" if status.ok else "error=")
                                                + quote(detail[:200]) + "#sync"})
        if path in ("/hub/profile", "/hub/profile/about", "/hub/profile/links", "/hub/profile/topic"):
            if path == "/hub/profile":
                if "name" in form:
                    identity.set_name(self.store, form["name"])
                identity.set_colour(self.store, form.get("colour", ""))
            elif path.endswith("about"):
                identity.set_about(self.store, form.get("about", ""))
            elif path.endswith("links"):
                identity.set_links(self.store, {slot: form.get(slot, "") for slot in identity.LINK_SLOTS})
            elif form.get("act") == "add":
                identity.add_topic(self.store, form.get("topic", ""))
            elif form.get("act") == "remove":
                identity.hide_topic(self.store, form.get("topic", ""))
            self._send_profile()
            return Response(303, b"", headers={"Location": "/settings/profile?saved=profile#profile"})
        if path == "/hub/profile/photo/remove":
            identity.remove_photo()
            self._send_profile()
            return Response(303, b"", headers={"Location": "/settings/profile?saved=nophoto"})
        if path == "/hub/deep/engine":
            from magpiary import deepdive
            from magpiary import engines as eng

            before = (eng.choice(self.store, "deep") or {}).get("id")
            if form.get("engine") and form["engine"] != before and eng.choose(self.store, "deep", form["engine"]):
                self.store.set_setting(deepdive.MODEL, "")  # a new engine starts on its own defaults
            else:
                chosen = deepdive.engine(self.store)
                if form.get("model", "") in deepdive.models_for(chosen["kind"], chosen["key"]):
                    self.store.set_setting(deepdive.MODEL, form["model"])
                if form.get("effort", "") in deepdive.efforts_for(chosen["kind"], chosen["key"]):
                    self.store.set_setting(deepdive.EFFORT, form["effort"])
            return Response(303, b"", headers={"Location": "/settings/ai?saved=deep#deepengine"})
        if path == "/hub/settings/long-video":
            minutes = form.get("minutes", "").strip()
            if minutes.isdigit() and int(minutes) <= 600:
                self.store.set_setting("long_video_minutes", str(int(minutes)))
            return Response(303, b"", headers={"Location": "/settings/ai?saved=longvideo#longvideo"})
        if path == "/hub/settings/search-limit":
            limit = form.get("limit", "").strip()
            if limit.isdigit() and int(limit) <= 10000:
                self.store.set_setting("search_limit", str(int(limit)))
            return Response(303, b"", headers={"Location": "/settings/ai?saved=limit#search"})
        if path == "/hub/keys/model":
            if not keyring.change_model(form.get("key_id", ""), form.get("model", "")):
                return Response(303, b"", headers={"Location": "/settings/ai?error=" + quote("That does not look like a model name.")})
            self.store.summarise_again()  # anything that waited gets its turn with the new model
            self.wake()
            return Response(303, b"", headers={"Location": "/settings/ai?saved=model"})
        if path == "/hub/settings/mode":
            if form.get("mode") == "smart" and not form.get("next", "").startswith("/welcome/"):
                from magpiary import engines as eng

                if not eng.options(self.store):  # nothing could write a summary: add a key first
                    return Response(303, b"", headers={"Location": "/settings/ai?note=" + quote("Add an AI key first; Smart turns on by itself once it works.") + "#keys"})
            if form.get("mode") in modes.MODES:
                self.store.set_setting(modes.SETTING, form["mode"])
                self.wake()
            target = form.get("next", "")
            if target.startswith("/welcome/"):
                return Response(303, b"", headers={"Location": target})
            return Response(303, b"", headers={"Location": "/settings/ai?saved=mode#mode"})
        if path == "/hub/settings/budget":
            choice = form.get("mode", "")
            if choice == "paused":
                self.store.set_setting("ai_budget", "0")
            elif choice == "all":
                self.store.set_setting("ai_budget", "all")
            elif choice == "next" and form.get("count", "").isdigit():
                self.store.set_setting("ai_budget", str(min(int(form["count"]), 1000)))
            self.wake()
            return Response(303, b"", headers={"Location": "/nest?tab=now"})
        return None

    # ---- the health check ----------------------------------------------------------------------

    def doctor_json(self, q: dict, *, authorized_start: bool = False) -> Response:
        """The health check as it runs, for the Health page: each check as it finishes. `start=1` begins a run (one at a time),
        `since=N` returns what came after the Nth."""
        import json
        import threading

        from magpiary import doctor

        if q.get("start") == "1" and not authorized_start:
            return Response(403, b'{"error":"start checks with a CSRF-protected POST"}', "application/json")
        run = getattr(self, "_health", None)
        if q.get("start") == "1" and (not run or run["done"]):
            run = {"checks": [], "done": False, "phase": "offline", "live": q.get("live") == "1"}
            self._health = run

            def work() -> None:
                try:
                    run["checks"] += self._offline_checks()
                    if run["live"]:
                        run["phase"] = "live"
                        doctor.live(self.store, emit=run["checks"].append)
                except Exception as err:  # the page must always reach its end
                    run["checks"].append(doctor.Check("Health check", "The check itself", doctor.FAIL, f"Stopped: {type(err).__name__}"))
                problems = sum(c.state == doctor.FAIL for c in run["checks"])
                warnings = sum(c.state == doctor.WARN for c in run["checks"])
                self.store.set_setting(HEALTH, self.health_stamp(problems, warnings))
                run["done"] = True
            threading.Thread(target=work, daemon=True).start()
        if not run:
            return Response(404, b"{}", "application/json")
        since = int(q.get("since", "0")) if q.get("since", "0").isdigit() else 0
        items = [{"area": c.area, "name": c.name, "state": c.state, "detail": c.detail, "fix": c.fix, "link": c.link, "label": c.link_label}
                 for c in run["checks"][since:]]
        body = {"items": items, "next": since + len(items), "done": run["done"], "phase": run["phase"], "live": run["live"]}
        if run["done"]:
            body["problems"] = sum(c.state == doctor.FAIL for c in run["checks"])
            body["warnings"] = sum(c.state == doctor.WARN for c in run["checks"])
        return Response(200, json.dumps(body).encode(), "application/json", headers={"Cache-Control": "no-store"})

    def _claude_check(self):
        """Claude Code and Codex for the health check: allowed or not, and whether an allowed one can still run."""
        from magpiary import doctor
        from magpiary import engines

        allowed = engines.allowed(self.store)
        if not allowed:
            return doctor.Check("Claude Code and Codex", "On this Mac", doctor.OK, "Not allowed, so Magpiary does not use them.")
        missing = [engines.SHORT[k] for k in allowed if not engines.installed(k)]
        if missing:
            return doctor.Check("Claude Code and Codex", "On this Mac", doctor.WARN, f"Allowed but not found: {', '.join(missing)}.",
                                "Set it up again from Ask Magpiary's settings, or stop it in AI keys.")
        return doctor.Check("Claude Code and Codex", "On this Mac", doctor.OK, "Allowed: " + ", ".join(engines.SHORT[k] for k in allowed) + ".")

    def _offline_checks(self):
        """Everything that needs no outside request. The page and the live run both start from this, so they never disagree."""
        from magpiary import doctor

        checks = doctor.offline(self.store, ping=lambda port: True)  # the page being served is the service answering
        checks.append(self._claude_check())
        return doctor.linked(checks)

    def doctor_page(self, run_live: bool) -> Response:
        """The health check: one verdict up top, what needs a look next, then everything that is fine, folded by area.
        The site and key test (one request each, up to a minute) streams in from the page's script."""
        from magpiary import doctor

        started = time.monotonic()
        checks = self._offline_checks()
        took = time.monotonic() - started
        problems = sum(c.state == doctor.FAIL for c in checks)
        warnings = sum(c.state == doctor.WARN for c in checks)
        self.store.set_setting(HEALTH, self.health_stamp(problems, warnings))
        tone = "bad" if problems else "warn" if warnings else "ok"
        head = {"ok": "Everything works", "warn": f"Working, with {warnings} thing{'' if warnings == 1 else 's'} to look at",
                "bad": f"{problems} thing{'' if problems == 1 else 's'} need{'s' if problems == 1 else ''} fixing"}[tone]
        mark = {"ok": ui.icon("check"), "warn": "!", "bad": "!"}[tone]
        when = datetime.now().strftime("%H:%M")
        need = sorted((c for c in checks if c.state != doctor.OK), key=lambda c: c.state != doctor.FAIL)
        fine = [c for c in checks if c.state == doctor.OK]

        def row(c) -> str:
            cls = {doctor.OK: "ok", doctor.WARN: "warn", doctor.FAIL: "bad"}[c.state]
            glyph = ui.icon("check") if cls == "ok" else "!"
            act = f'<a class="btn sm" href="{e(c.link)}">{e(c.link_label)}</a>' if c.link else ""
            return (f'<div class="hk {cls}" data-k="{e(c.area)}|{e(c.name)}" data-state="{cls}" data-name="{e(c.name)}" data-detail="{e(c.detail)}">'
                    f'<span class="hkm">{glyph}</span><div class="hkt"><b>{e(c.name)}</b><small>{e(c.detail)}</small>'
                    + (f'<small class="fix">{e(c.fix)}</small>' if c.fix else "") + f"</div>{act}</div>")

        needs = (f'<h2 class="hc-h">Needs a look<span>{len(need)}</span></h2><div class="hc-list" id="hc-need">{"".join(row(c) for c in need)}</div>'
                 if need else '<div class="hc-list" id="hc-need" hidden></div>')
        groups, order = {}, []
        for c in fine:
            if c.area not in groups:
                groups[c.area] = []
                order.append(c.area)
            groups[c.area].append(c)
        folds = "".join(f'<details class="hc-grp"><summary><span class="hc-area">{e(a)}</span>'
                        f'<span class="hc-n">{len(groups[a])} fine</span><span class="hc-chev">{ui.icon("chev")}</span></summary>'
                        f'<div class="hc-list">{"".join(row(c) for c in groups[a])}</div></details>' for a in order)
        body = (f'<a class="back" href="/settings/storage#health">← Settings</a><div id="hc-page">'
                f'<section class="hc hc-{tone}" id="hc" data-live="{1 if run_live else 0}" data-total="{len(checks)}">'
                f'<div class="hc-orb">{mark}</div><div class="hc-tx"><h1 id="hc-h1">{e(head)}</h1>'
                f'<p id="hc-sub">{len(checks)} things checked at {when}, in {took:.1f} s. Nothing was sent anywhere.</p>'
                f'<div class="hc-bar" id="hc-bar"><i></i></div></div>'
                f'<div class="hc-act"><a class="btn dark" href="/doctor" id="hc-again">Run again</a>'
                f'<button type="button" class="btn" id="hc-live">Also test each site and key</button>'
                f'<button type="button" class="btn" id="hc-copy">Copy report</button></div>'
                f'<p class="hc-note">The site test makes one request per site, using your newest save from it. Keys are checked without using any quota. '
                f'Takes up to a minute.</p></section>'
                f'{needs}<h2 class="hc-h">Working</h2><div class="hc-groups" id="hc-groups">{folds}</div></div>')
        return self.shell("Health check", body, "doctor", active="settings")


def photo_url() -> str:
    try:
        return f"/profile/photo.jpg?v={int(identity.photo_path().stat().st_mtime)}"
    except OSError:
        return ""


def ago(stamp: str) -> str:
    """How long ago a stored moment was, in plain words."""
    from datetime import datetime

    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return "a while ago"
    mins = int((datetime.now(then.tzinfo) - then).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"
