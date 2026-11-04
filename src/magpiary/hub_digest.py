"""The digest pages (M7c), mixed into Hub: /digest (the newest, with past ones alongside), /digest/N, and making one
now for the last 7 or 30 days. The top bar's Digest button carries a dot, and the wall a banner, until a new one is
opened."""

from datetime import datetime, timedelta

from magpiary import digest as dg
from magpiary import ui
from magpiary.web import Response, e

RANGES = {"7": "the last 7 days", "30": "the last 30 days"}
KINDS = {"weekly": "Week", "monthly": "Month", "manual": "Made by you"}
# the digest's colours: indigo and violet, with gold and pink as the accents (dark words on those two)
GRADIENTS = [("#ffc23d", "#ffe08a"), ("#5b5bf0", "#7b8cff"), ("#ff5a92", "#ff9fc0"), ("#6d4df0", "#8b5cf6"),
             ("#4338ca", "#6366f1"), ("#7a3fd0", "#a78bfa")]
DARK_WORDS = {"#ffc23d": "#2a1a00", "#ff5a92": "#3a0620"}


def _tilt(word: str) -> int:
    """A tilt between -8 and 8 degrees that looks random but stays the same for a word (owner: not all one way)."""
    import hashlib

    return hashlib.sha256(word.encode()).digest()[0] % 17 - 8


def _section(title: str, body: str) -> str:
    """One part of the digest: its title in the left rail, its content beside it, a hairline above."""
    return f'<section class="dgsec"><h2 class="dgsh">{e(title)}</h2><div class="dgsecb">{body}</div></section>'


def _story_of(data: dict) -> dict:
    """The written story; a digest from the four-tone trial reads its playful version."""
    story = data.get("story") or {}
    return story if "headline" in story else story.get("playful") or story.get("warm") or {}


def _highlight(headline: str) -> str:
    """[[words]] the writer marked become highlights, each with its own colour."""
    import re

    parts, out, n = re.split(r"(\[\[.+?\]\])", headline), [], 0
    for part in parts:
        if part.startswith("[[") and part.endswith("]]"):
            out.append(f'<mark class="hl hl{n}">{e(part[2:-2])}</mark>')
            n += 1
        else:
            out.append(e(part))
    return "".join(out)


def _period(d: dict) -> str:
    start, end = datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"]) - timedelta(seconds=1)
    if start.year != end.year:
        return f"{start:%-d %b %Y} – {end:%-d %b %Y}"
    return f"{start:%-d %b} – {end:%-d %b %Y}" if start.month != end.month else f"{start:%-d}–{end:%-d %b %Y}"


class DigestPages:
    """Needs Hub's store, shell, _form, tile and tile_context."""

    def digest_page(self, rest: str, q: dict) -> Response:
        """Only the newest digest (owner, 25 Oct: about the present; no browsing back). An older address leads to it."""
        past = [d for d in self.store.digests() if self._has_saves(d["id"])]
        latest = max(past, key=lambda d: (d["end"], d["id"])) if past else None  # the newest period
        if not latest:  # no digest yet: there is nothing to show, so the page doesn't exist yet
            return Response(303, b"", headers={"Location": "/"})
        if rest and rest != str(latest["id"]):
            return Response(303, b"", headers={"Location": "/digest"})
        chosen = self.store.digest(latest["id"])
        for d in self.store.digests():  # only the newest can be read, so opening it settles every dot and banner
            if not d["seen"]:
                self.store.digest_seen(d["id"])
        day, hour = dg.schedule(self.store)
        every = self.store.get_setting(dg.EVERY, "monthly")
        when = {"monthly": f"A new one arrives on the 1st of each month at {hour}:00.",
                "weekly": f"A new one arrives every {dg.DAYS[day]} at {hour}:00.",
                "both": f"A new one arrives every {dg.DAYS[day]} at {hour}:00, and a monthly one on the 1st."}.get(every, "")
        foot = f'<footer class="dgend"><p>{e(when)} <a class="link" href="/settings/ai#digest">Change</a></p></footer>'
        return self.shell("Digest", self._digest_body(chosen, foot), "digest", active="digest")

    def _has_saves(self, digest_id: int) -> bool:
        d = self.store.digest(digest_id)
        return bool(d and (d["data"].get("stats") or {}).get("saved"))

    def digest_button(self, active: str = "") -> str:
        """The way back to the digest (owner, 2 Nov): only once one exists, with a dot until the new one is opened."""
        if not any(self._has_saves(d["id"]) for d in self.store.digests()):
            return ""
        new = self.store.unseen_digest()
        dot = '<span class="dgdot" aria-hidden="true"></span>' if new else ""
        name = "Digest, a new one is ready" if new else "Digest"
        return (f'<a class="ubtn dgbtn{" on" if active == "digest" else ""}" href="/digest" id="t-digest" aria-label="{name}" title="{name}">'
                f'{ui.icon("digest")}<span class="lbl">Digest</span>{dot}</a>')

    # ---- the page (digest v3: centred and celebratory, three hero variations to try) ---------------------

    def _digest_body(self, d: dict, foot: str = "") -> str:
        """An editorial page (owner, 1 Nov): reading sits straight on the page between hairlines, and only what you act
        on (Worth doing) is a card. Most useful first: the headline, the numbers, the standout, what to do, then the
        themes and the words. Clicking a word opens its saves under the cloud."""
        data, stats = d["data"], d["data"].get("stats") or {}
        story = _story_of(data) if data.get("story_status") == "done" else None
        label = {"weekly": "Your week", "monthly": "Your month"}.get(d["kind"], "Your digest")
        cloud = (data.get("cloud") or [])[:20]  # owner, 25 Oct: more words, more crowded
        piles = len([g for g in data.get("groups", []) if g["pile"]])
        if story:
            headline, kicker = _highlight(story.get("headline", "")), story.get("kicker", "")
        else:
            kicker = ""
            headline = f'{stats.get("saved", 0)} saves in <mark class="hl hl0">{piles} piles</mark>'
        hero = (f'<section class="dghero2"><small class="dgeyebrow">{e(label)} · {e(_period(d))}</small>'
                f'<h1 class="dghl2">{headline}</h1>' + (f'<p class="dgkick">{e(kicker)}</p>' if kicker else "")
                + f'<span class="dgcue" aria-hidden="true">Scroll to unwrap {ui.icon("chev")}</span></section>')
        nums = [(stats.get("saved", 0), "saved"), (stats.get("read", 0), "summarised"), (piles, "piles"),
                (len(stats.get("sources") or {}), "sources")]
        numbers = ('<section class="dgstats" aria-label="By the numbers"><div class="dgbig">'
                   + "".join(f'<div><b>{v}</b><small>{e(w)}</small></div>' for v, w in nums) + '</div><p class="dgsrcs">'
                   + "".join(f'<span class="dgsrc">{ui.source_logo(k, "dgsrcl")}{e(ui.source_name(k))} <b>{v}</b></span>'
                             for k, v in (stats.get("sources") or {}).items()) + "</p></section>")
        if story:
            standout = _section("The standout", f'<p class="dgstand2">{e(story.get("standout", ""))}</p>'
                                + (f'<p class="dgshift2">{e(story["shift"])}</p>' if story.get("shift") else ""))
            found = story.get("themes") or []
            most = max((len(t.get("saves") or []) for t in found), default=1) or 1
            themes = "".join(
                f'<article class="dgtheme"><div class="dgtname"><h3><span aria-hidden="true">{e(t.get("emoji", ""))}</span> {e(t.get("name", ""))}</h3>'
                f'<small>{len(t.get("saves") or [])} saves</small><i class="dgshare" style="--s:{len(t.get("saves") or []) / most:.2f}" aria-hidden="true"></i></div>'
                f'<div class="dgtbody"><p>{e(t.get("summary", ""))}</p>{self._thumbs(t.get("saves") or [])}</div></article>'
                for t in found)
            state = data.get("pick_state") or {}
            rows = []
            for n, (p, (a, b)) in enumerate(zip((story.get("picks") or [])[:3], GRADIENTS[2:] + GRADIENTS)):
                st = state.get(str(n), "")
                if st == "dismissed":
                    continue
                acts = ('<button type="button" class="dgundo" data-pick="clear">Tried it · Undo</button>' if st == "tried" else
                        '<button type="button" class="dgtry" data-pick="tried">'
                        f'{ui.icon("check")}I tried this</button>'
                        '<button type="button" class="dgskip" data-pick="dismissed" aria-label="Dismiss this pick" title="Not for me: don\'t suggest it again">Dismiss</button>')
                rows.append(
                    f'<article class="dgrow{" tried" if st == "tried" else ""}" data-digest="{d["id"]}" data-idx="{n}" style="--c1:{a};--c2:{b};--ink:{DARK_WORDS.get(a, "#fff")}">'
                    f'<div class="dgrt"><h4><span aria-hidden="true">{e(p.get("emoji", ""))}</span> {e(p.get("do", ""))}</h4><p>{e(p.get("why", ""))}</p>'
                    f'<div class="dgrm">' + (f'<span class="dgwhy">{e(p["reason"])}</span>' if p.get("reason") else "")
                    + f'<span class="dgtime">{ui.icon("clock")} {e(p.get("time", ""))}</span>{self._thumbs(p.get("saves") or [])}</div>'
                    f'<div class="dgpa">{acts}</div></div></article>')
            picks = "".join(rows)
            nudge = "" if self.store.get_setting(dg.GOALS, "").strip() else (
                '<p class="dgnudge"><a href="/settings/profile#goals">Tell Magpiary your goals</a> for sharper picks.</p>')
            main = (standout + (_section("Worth doing", f'<div class="dgpickrows">{picks}</div>{nudge}') if picks else "")
                    + _section("What it was about", themes))
        else:
            main = self._waiting(data)
        words = "".join(
            f'<div class="dgword" data-word="{n}" hidden><button type="button" class="dgwordback" data-wordback>{ui.icon("back")} Close</button>'
            f'<h3 class="dgwordname">{e(w)}</h3>{self._save_list(dg.word_saves(self.store, data, w))}</div>'
            for n, (w, _) in enumerate(cloud))
        wordcloud = _section("In your words", self._pills(cloud) + words) if cloud else ""
        by = f' Written by {e(data["story_by"])}.' if story and data.get("story_by") else ""
        waiting = ' data-waiting="1"' if data.get("story_status") == "waiting" else ""
        return (f'<div class="dgpage" id="dgstory" data-digest="{d["id"]}"{waiting}>'
                f'<div class="dgbg" aria-hidden="true"><canvas id="dgshader"></canvas></div><div class="dgdusk" aria-hidden="true"></div>'
                f'<div class="dgbackdrop" style="--art1:url({ui.art("digest-gift-1x")});--art2:url({ui.art("digest-gift-2x")})" aria-hidden="true"></div>'
                f'<div class="dggrid">{hero}{numbers}<div class="dgmain">{main}</div>{wordcloud}'
                f'<p class="dgby">The Digest looks back at what you saved and points to what is worth trying again.{by}</p>{foot}</div></div>')

    def _pills(self, cloud: list) -> str:
        if not cloud:
            return ""
        return ('<div class="dgpills" id="dgpills" aria-label="What your saves were about">'
                + "".join(f'<button type="button" class="dgpill" data-pill="{n}" style="--w:{w};--c1:{GRADIENTS[n % len(GRADIENTS)][0]};'
                          f'--c2:{GRADIENTS[n % len(GRADIENTS)][1]};--ink:{DARK_WORDS.get(GRADIENTS[n % len(GRADIENTS)][0], "#fff")};--r:{round(_tilt(word) * (1 - 0.65 * float(w)), 1)}deg;--i:{n}">{e(word)}</button>'
                          for n, (word, w) in enumerate(cloud)) + "</div>")

    def _save_list(self, urls: list[str]) -> str:
        rows = []
        for u in urls:
            item = self.store.item_by_url(u)
            if not item or item.get("shelf") == "trash":
                continue
            thumb = self.thumb_url(item)
            title = item.get("ai_title") or item.get("title") or item["canonical_url"]
            rows.append(f'<a class="dgsave" href="/item/{item["id"]}">'
                        + (f'<img src="{e(thumb)}" alt="">' if thumb else '<span class="ph"></span>')
                        + f'<span><b>{e(title)}</b><small>{e(ui.source_label(item))}</small></span></a>')
        return (f'<div class="dgsaves">{"".join(rows)}</div>' if rows else '<p class="dgby">No saves carry this word.</p>')

    def _thumbs(self, ids: list) -> str:
        out = []
        for i in ids[:4]:
            item = self.store.item_by_id(int(i)) if str(i).isdigit() else None
            if not item or item.get("shelf") == "trash":
                continue
            thumb = self.thumb_url(item)
            title = item.get("ai_title") or item.get("title") or ""
            out.append(f'<a class="dgth" href="/item/{item["id"]}" title="{e(title)}">'
                       + (f'<img src="{e(thumb)}" alt="">' if thumb else f"<span>{e(title[:1])}</span>") + "</a>")
        return f'<div class="dgths">{"".join(out)}</div>' if out else ""

    def _waiting(self, data: dict) -> str:
        status = data.get("story_status")
        tries = data.get("story_tries") or []
        if status == "private":
            note = "Private mode: no written summary. Here's what your saves were about, by pile."
        elif tries:
            note = f"The written summary isn't ready: {tries[-1]['why']}. Magpiary tries again by itself."
        else:
            note = "The written summary is on its way: Claude Code is writing it. This page fills in by itself."
        piles = "".join(f'<details class="dgacc" style="--c1:{a};--c2:{b}"><summary><b>{e(g["name"])}</b>'
                        f'<small>{len(g["urls"])} saves</small><i aria-hidden="true">{ui.icon("chev")}</i></summary>'
                        f'{self._save_list(g["urls"])}</details>'
                        for g, (a, b) in zip(data.get("groups", []), GRADIENTS * 4))
        return (f'<p class="dgwait2">{ui.icon("clock")} {e(note)}</p>'
                + _section("By pile", f'<div class="dgaccs">{piles}</div>'))

    def digest_post(self, path: str, form: dict) -> Response | None:
        """Make one now, for testing only: no button offers it (digests come weekly or monthly by themselves)."""
        if path == "/hub/digest/pick":
            d = self.store.digest(int(form["digest"])) if form.get("digest", "").isdigit() else None
            if d and form.get("idx", "").isdigit() and form.get("state") in ("tried", "dismissed", "clear"):
                data = d["data"]
                picks = _story_of(data).get("picks") or [] if data.get("story_status") == "done" else []
                idx = form["idx"]
                if int(idx) < len(picks):
                    state = data.setdefault("pick_state", {})
                    before = state.get(idx, "")
                    if form["state"] == "clear":
                        state.pop(idx, None)
                    else:
                        state[idx] = form["state"]
                    after = state.get(idx, "")
                    if after == "tried" and before != "tried":
                        self.store.activity_add("tried")
                    elif before == "tried" and after != "tried":
                        self.store.activity_add("tried", -1)
                    self.store.update_digest(d["id"], data)
            return Response(200, b"ok", "text/plain")
        if path != "/hub/digest/make":
            return None
        days = int(form["days"]) if form.get("days") in RANGES else 7
        end = datetime.now().replace(microsecond=0)
        digest_id = dg.make(self.store, end - timedelta(days=days), end + timedelta(seconds=1), "manual")
        return Response(303, b"", headers={"Location": f"/digest/{digest_id}"})

    def digest_banner(self) -> str:
        """On the wall when a weekly or monthly digest is ready, until it is opened or put away."""
        fresh = self.store.unseen_digest()
        if not fresh or fresh["kind"] not in ("weekly", "monthly"):
            return ""
        d = self.store.digest(fresh["id"])
        saved = (d["data"].get("stats") or {}).get("saved", 0)
        word = "week" if fresh["kind"] == "weekly" else "month"
        did, plural = fresh["id"], "s" if saved != 1 else ""
        art = f"--art1:url({ui.art('digest-gift-1x')});--art2:url({ui.art('digest-gift-2x')})"
        return (f'<div class="dgcard" id="dgb" style="{art}" data-dismiss="digest-{did}"><span class="dgart" aria-hidden="true"></span>'
                f'<span class="dgglow" aria-hidden="true"></span><div class="dgnum"><b>{saved}</b><span>save{plural}</span></div>'
                f'<div class="dgtext"><span class="dgtag">{ui.icon("digest")} New digest</span>'
                f'<h3>Your {word}ly digest is ready</h3><p>{e(_period(d))}: what your saves were about, and what’s worth doing.</p></div>'
                f'<div class="dgacts"><a class="btn cta" href="/digest/{did}">Read the digest</a>'
                f'<button class="btn" type="button" data-dismiss-btn>Not now</button></div></div>')
