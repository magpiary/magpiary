"""Search the way you remember: dates, sources, types and facets found inside what was typed, on this Mac, no AI.

"calm recipe from last month on instagram" becomes the filters Recipe, Last month and Instagram, a facet (Mood: calm)
and nothing left over to match as words. Each understood part is shown above the results as a chip that can be
removed (`no=` in the address), so the owner always sees what was read into the query and can undo it.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SOURCES = {"instagram": "instagram", "insta": "instagram", "threads": "threads", "youtube": "youtube",
           "reddit": "reddit", "linkedin": "linkedin", "twitter": "x"}
TYPES = {"recipe": "recipe", "recipes": "recipe", "tutorial": "howto", "tutorials": "howto", "how-to": "howto",
         "howto": "howto", "place": "place", "places": "place", "tool": "tool", "tools": "tool",
         "design": "design", "news": "news_opinion", "explainer": "explainer"}
MONTHS = ("january february march april may june july august september october november december").split()
FILLER = set("the a an one that this those of from in on about with by me my i saw saved post posts video videos reel reels "
             "thing something where there is was it and for to".split())


@dataclass
class Part:
    kind: str    # date | source | type | facet
    key: str     # what to filter on
    value: str
    label: str   # shown on the chip
    phrase: str  # the words it was read from

    @property
    def token(self) -> str:
        return f"{self.kind}:{self.key}:{self.value}"


@dataclass
class Understood:
    parts: list[Part] = field(default_factory=list)
    rest: str = ""   # what is left to match as words and meaning
    since: date | None = None
    until: date | None = None


def _span(phrase: str, today: date):
    """(label, since, until) for a date phrase, or None."""
    monday = today - timedelta(days=today.weekday())
    if phrase == "today":
        return "Today", today, today
    if phrase == "yesterday":
        return "Yesterday", today - timedelta(days=1), today - timedelta(days=1)
    if phrase == "this week":
        return "This week", monday, today
    if phrase == "last week":
        return "Last week", monday - timedelta(days=7), monday - timedelta(days=1)
    if phrase == "this month":
        return "This month", today.replace(day=1), today
    if phrase == "last month":
        end = today.replace(day=1) - timedelta(days=1)
        return "Last month", end.replace(day=1), end
    if phrase == "last year":
        return "Last year", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    m = re.fullmatch(r"(?:in )?(" + "|".join(MONTHS) + r")(?: (\d{4}))?", phrase)
    if m:
        number = MONTHS.index(m.group(1)) + 1
        year = int(m.group(2)) if m.group(2) else today.year - (1 if number > today.month else 0)
        start = date(year, number, 1)
        end = (date(year + (number == 12), number % 12 + 1, 1)) - timedelta(days=1)
        return f"{m.group(1).capitalize()} {year}", start, end
    return None


DATE_PHRASES = re.compile(r"\b(today|yesterday|this week|last week|this month|last month|last year|"
                          r"(?:in )?(?:" + "|".join(MONTHS) + r")(?: \d{4})?)\b")


def understand(query: str, known_facets: dict[str, dict[str, int]], type_name=lambda t: t, source_name=lambda s: s,
               today: date | None = None, no: set[str] | None = None) -> Understood:
    """Read dates, sources, types and known facet values out of `query`. `known_facets` is {facet: {value: count}};
    only values the library really has are used. Parts named in `no` are left as plain words."""
    today = today or datetime.now().date()
    no = no or set()
    text = " " + query.lower().strip() + " "
    out = Understood()

    def take(part: Part) -> bool:
        if part.token in no:
            return False
        out.parts.append(part)
        return True

    for m in DATE_PHRASES.finditer(text):
        span = _span(m.group(1), today)
        if span and take(Part("date", "when", m.group(1), span[0], m.group(1))):
            out.since, out.until = span[1], span[2]
            text = text.replace(m.group(0), " ", 1)
            break
    for word in re.findall(r"[\w-]+", text):
        if word in SOURCES and take(Part("source", "source", SOURCES[word], source_name(SOURCES[word]), word)):
            text = re.sub(rf"\b(?:on |from )?{re.escape(word)}\b", " ", text, 1)
        elif word in TYPES and take(Part("type", "type", TYPES[word], type_name(TYPES[word]), word)):
            text = re.sub(rf"\b{re.escape(word)}\b", " ", text, 1)
    for facet, values in known_facets.items():
        for value in sorted(values, key=len, reverse=True):  # longest first: "screen recording" before "screen"
            if len(value) > 2 and re.search(rf"\b{re.escape(value)}\b", text):
                label = f"{value}"
                if take(Part("facet", facet, value, label, value)):
                    text = re.sub(rf"\b{re.escape(value)}\b", " ", text, 1)
    rest = [w for w in re.findall(r"\w+", text, flags=re.UNICODE) if w not in FILLER or len(out.parts) == 0]
    out.rest = " ".join(rest) if out.parts else query.strip()
    return out


def keep(item: dict, understood: Understood, with_facets: set[str] | None) -> bool:
    """Does this item pass the dates, source, type and facets read from the query?"""
    for part in understood.parts:
        if part.kind == "source" and item.get("source") != part.value:
            return False
        if part.kind == "type" and (item.get("ai_type") or "other") != part.value:
            return False
    if understood.since:
        stamp = (item.get("last_shared_at") or item.get("created_at") or "")[:10]
        try:
            day = date.fromisoformat(stamp)
        except ValueError:
            return False
        if not understood.since <= day <= (understood.until or day):
            return False
    if with_facets is not None and item["canonical_url"] not in with_facets:
        return False
    return True
