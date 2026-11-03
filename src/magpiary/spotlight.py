"""The Spotlight score: how much weight a post deserves, from its own numbers and from what this library is about.

One score drives both "Most popular" and the big tiles. The recipe follows what ranking systems have settled on:
counts go through a log (Reddit: the first 10 likes weigh as much as the next 100, so one viral post cannot own the
wall); every post is ranked only against posts from its own site (percentiles, so Instagram likes and YouTube views
never meet); a Bayesian pull towards the middle stops a site with few posts from producing extreme ranks; engagement
rate (interactions per view, or comments per like where views are not shown) is blended in; a mild age term favours
newer posts (Hacker News-style, but gentle); a post with no numbers gets a neutral middle score, never zero. Then
the library's own context nudges the result up to about 25%: topics the owner saves often (piles, tags), with
recent saves counting more (60-day half-life), plus a small boost for the best post of each large pile.
Traction decides; interest nudges.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone

SHRINK = 5                  # pseudo-posts at the middle rank that every site's percentile is pulled towards
MEMORY_DAYS = 60            # half-life of how much a past save says about current interest
INTEREST_MAX = 0.25         # the most a topic can add
OPEN_MAX = 0.12             # the most a post's own opens can add (log-scaled, recent opens count more, capped)
OPEN_TOPIC = 0.5            # each open adds this much of a save's worth to the post's topics
PILE_BOOST = 1.08           # the best post of a large pile
BIG_PILE = 5                # members that make a pile "large"
AGE_PENALTY = 0.15          # the most age takes off (reached at two years)
NEUTRAL = 0.5               # a post with no numbers
BIG_TOP_SHARE = 0.10        # the big tile is picked from this top share of scored posts
REPEAT_DAYS = 14            # a post that was big is not picked again for this long


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Rank within a group, 0..1, ties sharing their average rank, then pulled towards 0.5 for small groups."""
    if not values:
        return {}
    ordered = sorted(values.values())
    n = len(ordered)
    out = {}
    for key, v in values.items():
        below = bisect_left(ordered, v)
        same = bisect_right(ordered, v) - below
        rank = (below + (same - 1) / 2) / max(n - 1, 1) if n > 1 else 0.5
        out[key] = (n * rank + SHRINK * 0.5) / (n + SHRINK)
    return out


def _age_days(item: dict, now: datetime) -> float:
    when = _parse(item.get("published_at")) or _parse(item.get("created_at"))
    return max((now - when).total_seconds() / 86400, 0.0) if when else 0.0


def compute(items: list[dict], stats: dict[str, dict], piles: list[dict], now: datetime | None = None,
            opens: dict[str, float] | None = None) -> dict[str, dict]:
    """Score every post. `items` are library rows (canonical_url, source, tags, created_at, published_at...), `stats`
    maps canonical_url to its numbers, `piles` are {id, name, members: [urls]}. Returns canonical_url -> details."""
    now = now or datetime.now(timezone.utc)
    opens = opens or {}
    by_source: dict[str, list[dict]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    def numbers(item: dict) -> tuple[int | None, int | None, int | None]:
        s = stats.get(item["canonical_url"]) or {}
        return s.get("likes"), s.get("comments"), s.get("views")

    traction: dict[str, float] = {}
    engagement: dict[str, float] = {}
    for group in by_source.values():
        per: dict[str, dict[str, float]] = {"likes": {}, "comments": {}, "views": {}, "er": {}}
        for item in group:
            likes, comments, views = numbers(item)
            url = item["canonical_url"]
            for name, v in (("likes", likes), ("comments", comments), ("views", views)):
                if v is not None:
                    per[name][url] = math.log1p(v)
            if views:
                per["er"][url] = ((likes or 0) + 3 * (comments or 0)) / max(views, 1)
            elif likes is not None and comments is not None:
                per["er"][url] = comments / (likes + 1)  # views are not shown: how much of the liking turned into talking
        pct = {name: _percentiles(vals) for name, vals in per.items()}
        for item in group:
            url = item["canonical_url"]
            parts = [(w, pct[name][url]) for name, w in (("likes", .45), ("comments", .25), ("views", .30)) if url in pct[name]]
            if parts:
                traction[url] = sum(w * p for w, p in parts) / sum(w for w, _ in parts)
            if url in pct["er"]:
                engagement[url] = pct["er"][url]

    # what the library is about: each save adds to its pile and its tags, recent saves counting more
    weight: dict[str, float] = {}
    pile_of: dict[str, dict] = {}
    for pile in piles:
        for url in pile["members"]:
            pile_of[url] = pile
    for item in items:
        w = 0.5 ** (_age_days({"created_at": item.get("created_at")}, now) / MEMORY_DAYS)
        topics = [f"tag:{t}" for t in item.get("tags") or []]
        if item["canonical_url"] in pile_of:
            topics.append(f"pile:{pile_of[item['canonical_url']]['id']}")
        w += OPEN_TOPIC * min(opens.get(item["canonical_url"], 0.0), 4.0)  # opening a post says its topics matter to you
        for topic in topics:
            weight[topic] = weight.get(topic, 0.0) + w
    top = max(weight.values(), default=0.0) or 1.0

    base: dict[str, float] = {}
    for item in items:
        url = item["canonical_url"]
        if url in traction:
            base[url] = .65 * traction[url] + .35 * engagement[url] if url in engagement else traction[url]
        else:
            base[url] = NEUTRAL
    best_of_pile: set[str] = set()
    for pile in piles:
        members = [u for u in pile["members"] if u in base]
        if len(members) >= BIG_PILE:
            best_of_pile.add(max(members, key=lambda u: base[u]))

    out: dict[str, dict] = {}
    for item in items:
        url = item["canonical_url"]
        topics = [f"tag:{t}" for t in item.get("tags") or []] + ([f"pile:{pile_of[url]['id']}"] if url in pile_of else [])
        interest = max((weight.get(t, 0.0) / top for t in topics), default=0.0)
        age = 1 - AGE_PENALTY * min(_age_days(item, now), 730) / 730
        boost = PILE_BOOST if url in best_of_pile else 1.0
        known = url in traction
        own = min(math.log1p(opens.get(url, 0.0)) / math.log1p(5), 1.0)  # about five recent opens is "a favourite"
        out[url] = {"score": base[url] * age * (1 + INTEREST_MAX * interest + OPEN_MAX * own) * boost, "known": known,
                    "pile": pile_of[url]["name"] if url in best_of_pile else "", "interest": round(interest, 2)}
    return out


def trending(items: list[dict], stats: dict[str, dict], spot: dict[str, dict]) -> dict[str, dict]:
    """Growth between the last two refreshes of a post, ranked only against posts from its own site, nudged by the
    same interest as the Spotlight score. Comments weigh three likes, a view a tenth; growth is per day, on a log scale.
    Returns canonical_url -> {score, gain} for posts that grew; a post with no earlier snapshot or no growth is absent."""
    by_source: dict[str, dict[str, float]] = {}
    gains: dict[str, dict] = {}
    for item in items:
        url = item["canonical_url"]
        s = stats.get(url) or {}
        if s.get("prev_at") is None or s.get("fetched_at") is None:
            continue
        gain = {k: (s.get(k) or 0) - (s.get("prev_" + k) or 0) for k in ("likes", "comments", "views")}
        if s.get("prev_likes") is None and s.get("prev_comments") is None and s.get("prev_views") is None:
            continue
        weighted = max(gain["likes"], 0) + 3 * max(gain["comments"], 0) + 0.1 * max(gain["views"], 0)
        if weighted <= 0:
            continue
        a, b = _parse(s["prev_at"]), _parse(s["fetched_at"])
        days = max(((b - a).total_seconds() / 86400) if a and b else 1.0, 1.0)
        by_source.setdefault(item["source"], {})[url] = math.log1p(weighted / days)
        gains[url] = gain
    out = {}
    for group in by_source.values():
        for url, p in _percentiles(group).items():
            interest = (spot.get(url) or {}).get("interest", 0.0)
            out[url] = {"score": p * (1 + INTEREST_MAX * interest), "gain": gains[url]}
    return out


def gain_text(gain: dict) -> str:
    """The one line on a trending tile: what grew most, for example '+1.2K likes'."""
    for key, word in (("likes", "likes"), ("comments", "comments"), ("views", "views")):
        if gain.get(key, 0) > 0:
            return f"+{compact(gain[key])} {word}"
    return "growing"


def compact(n: int | None) -> str:
    if n is None:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def reason(item: dict, info: dict, stat: dict | None) -> str:
    """The one line that says why a big tile was chosen."""
    s = stat or {}
    bits = [f"{compact(s['likes'])} likes" if s.get("likes") else "", f"{compact(s['comments'])} comments" if s.get("comments") else ""]
    traction = " · ".join(b for b in bits if b) or (f"{compact(s['views'])} views" if s.get("views") else "")
    lead = f"Top of {info['pile']}" if info.get("pile") else "Popular here"
    return f"{lead} · {traction}" if traction else lead


def pick_big(scored: list[tuple[str, float, str]], today_ordinal: int, recent: set[str], how_many: int) -> list[str]:
    """Pick today's big tiles. `scored` is (url, score, pile name) for posts that could be big. Chosen from the top
    10%, shuffled by the day (so the choice is stable all day and different tomorrow), skipping posts that were big
    in the last two weeks and never two from one pile."""
    if not scored or how_many <= 0:
        return []
    ranked = sorted(scored, key=lambda t: -t[1])
    pool = ranked[:max(how_many * 3, math.ceil(len(ranked) * BIG_TOP_SHARE))]
    pool = [p for p in pool if p[0] not in recent] or pool
    # a day-seeded order: rotate the pool by the day number, then take in that order
    start = today_ordinal % len(pool)
    pool = pool[start:] + pool[:start]
    chosen, piles = [], set()
    for url, _, pile in pool:
        if pile and pile in piles:
            continue
        chosen.append(url)
        if pile:
            piles.add(pile)
        if len(chosen) == how_many:
            break
    return chosen
