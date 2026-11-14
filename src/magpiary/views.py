"""A post's view: its category and the content of its category tabs (owner decisions 14 Nov 2026).

The category comes from the AI (`by: "ai"`), from the owner ("owner": Change category), or, until the AI has read the
post or in Private mode, from rules over what is already known (`guess`, "rules"). The tabs' content is `view.json` in
the post's folder; without one, `free_view` fills the tabs it can without AI (ingredients and steps the summary already
holds, list items, places, products, chapters). `tab_plan` puts the tabs in order and folds extras into More.

Everything in a view came from the post or from an AI reading it: untrusted text, escaped wherever it is shown.
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from magpiary import categories as cats
from magpiary.config import load_json

VERSION = 1
FILE = "view.json"
ITEM_FIELDS = ("name", "detail", "at", "amount", "group", "kind", "value")
LIMITS = {"name": 200, "detail": 400, "at": 8, "amount": 60, "group": 80, "kind": 30, "value": 4000}
MAX_TABS, MAX_ITEMS, MAX_TEXT = 12, 40, 1500
VISIBLE = 7  # up to this many tabs all show, with no More (owner, 15 Nov); Summary and Details always among them
VISIBLE_WITH_MORE = 6  # above VISIBLE, this many show and the rest wait in More
BY = ("ai", "rules", "owner")


# ---- shape ------------------------------------------------------------------------------------------------------

def _clean(value, cap: int) -> str:
    return re.sub(r"[ \t]+", " ", str(value if value is not None else "")).strip()[:cap]


def tidy_item(raw) -> dict | None:
    """One item in the expected shape (strings only, known fields, capped), or None without a name."""
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    item = {k: _clean(raw.get(k), LIMITS[k]) for k in ITEM_FIELDS}
    item = {k: v for k, v in item.items() if v}
    return item if item.get("name") else None


def tidy_items(raw) -> list[dict]:
    """Known items, each once: a repeat is the same item in every field (Hello by Adele and Hello by Lionel Richie
    are two songs; review 14 Nov 2026)."""
    out, seen = [], set()
    for r in raw if isinstance(raw, list) else []:
        item = tidy_item(r)
        key = item and tuple(item.get(k, "").casefold() for k in ITEM_FIELDS)
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out[:MAX_ITEMS]


def tidy_tabs(raw) -> dict[str, dict]:
    """Tabs keyed by known tab id. Accepts the AI's list shape [{tab, text, items}] or the file's dict shape."""
    if isinstance(raw, list):  # a tab id that is not a string (a list, a number) is junk, never a crash
        raw = {t.get("tab"): t for t in raw if isinstance(t, dict) and isinstance(t.get("tab"), str)}
    out: dict[str, dict] = {}
    for tab_id, body in (raw or {}).items() if isinstance(raw, dict) else []:
        if tab_id not in cats.TABS or not isinstance(body, dict) or len(out) >= MAX_TABS:
            continue
        items, text = tidy_items(body.get("items")), _clean(body.get("text"), MAX_TEXT)
        if items or text:
            out[tab_id] = {"text": text, "items": items}
    return out


def tidy_view(raw, *, category: str = "", category2: str = "", by: str = "ai", engine: str = "") -> dict:
    """A whole view in the file's shape. Unknown categories become other; a second category equal to the first is dropped."""
    raw = raw if isinstance(raw, dict) else {}
    category = category or _str(raw.get("category"))
    category = category if category in cats.CATEGORIES else "other"
    second = category2 or _str(raw.get("category2"))
    second = second if second in cats.CATEGORIES and second not in (category, "other") else ""
    by, old_by = _str(by), _str(raw.get("by"))
    return {"version": VERSION, "category": category, "category2": second,
            "by": by if by in BY else (old_by if old_by in BY else "ai"),
            "made_at": _clean(raw.get("made_at"), 30) or datetime.now().isoformat(timespec="seconds"),
            "engine": _clean(engine or raw.get("engine"), 80),
            "tabs": tidy_tabs(raw.get("tabs") if "tabs" in raw else raw.get("view")), "lookups": tidy_lookups(raw.get("lookups"))}


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def tidy_lookups(raw) -> dict:
    """lookups.py's results in their only shape, {tab: {key: {api: {field: value}}}}; anything else in a file that was
    edited or broken is dropped, so the wall, the post and the worker never trip over it."""
    out: dict = {}
    for tab_id, keys in raw.items() if isinstance(raw, dict) else ():
        if not isinstance(tab_id, str) or not isinstance(keys, dict):
            continue
        tab = {k: {api: dict(entry) for api, entry in apis.items() if isinstance(api, str) and isinstance(entry, dict)}
               for k, apis in keys.items() if isinstance(k, str) and isinstance(apis, dict)}
        out[tab_id] = {k: v for k, v in tab.items() if v}
    return out


# ---- file -------------------------------------------------------------------------------------------------------

def load(folder: Path | None) -> dict | None:
    if not folder:
        return None
    raw = load_json(Path(folder) / FILE)
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return None
    try:
        return tidy_view(raw, by=_str(raw.get("by")) or "ai")
    except Exception:  # a broken file shows the post's free view, never an error page or a stopped worker
        return None


def save(folder: Path, view: dict) -> None:
    """Write view.json private from the first byte and swapped in whole (review lessons 1 and 4)."""
    folder = Path(folder)
    fd, tmp = tempfile.mkstemp(prefix=".view-", suffix=".part", dir=folder)  # mkstemp creates 0600
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(view, f, ensure_ascii=False, indent=1)
        os.replace(tmp, folder / FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---- category without AI ----------------------------------------------------------------------------------------

def _text(record: dict | None, meta: dict | None, item: dict | None) -> str:
    record, meta, item = record or {}, meta or {}, item or {}
    parts = [record.get("title"), record.get("topic"), " ".join(record.get("suggested_tags") or []),
             (record.get("extras") or {}).get("media_kind"), item.get("ai_title"), item.get("title"),
             str(meta.get("title") or ""), str(meta.get("text") or item.get("caption") or "")[:800]]
    return " " + re.sub(r"\s+", " ", " ".join(str(p) for p in parts if p)).lower() + " "


_TOKEN = re.compile(r"[a-z0-9]+")


def _word_tests() -> dict[str, tuple[set[str], list]]:
    """Per category: its plain words (each one whole token of the text) and its other words (phrases, "ad ", "café")
    with a whole-word pattern. Built once: the wall scores every post that has no stored category."""
    out = {}
    for c in cats.CATEGORIES.values():
        simple, hard = set(), []
        for w in (w.strip() for w in c.words):
            if _TOKEN.fullmatch(w):
                simple.add(w)
            else:
                hard.append((w, re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])")))
        out[c.id] = (simple, hard)
    return out


_WORDS = _word_tests()


def scores(record: dict | None, meta: dict | None = None, item: dict | None = None) -> dict[str, float]:
    """How strongly each category fits, from the old type and format, a list post's kinds and words. No AI. One
    tokenising pass for the plain words (about 0.2 ms a post, fast enough for a wall of a few thousand tiles)."""
    from magpiary.brain import type_of

    record = record or {}
    kind = type_of(record) if record.get("type") else (item or {}).get("ai_type") or ""
    fmt = record.get("format") or ""
    kinds = [x.get("kind") for x in record.get("list_items") or [] if isinstance(x, dict)]
    text = _text(record, meta, item)
    tokens = set(_TOKEN.findall(text))
    out: dict[str, float] = {}
    for c in cats.CATEGORIES.values():
        s = 0.0
        if kind and kind in c.types:
            s += 2  # an old type points at several categories (tool: apps, AI, gadgets); the words decide between them
        if fmt and fmt in c.formats:
            s += 1
        s += min(6, 2 * sum(1 for k in kinds if k in c.list_kinds))
        simple, hard = _WORDS[c.id]
        s += min(4, len(simple & tokens) + sum(1 for w, rx in hard if w in text and rx.search(text)))
        if s:
            out[c.id] = s
    return out


def guess(record: dict | None, meta: dict | None = None, item: dict | None = None) -> tuple[str, str]:
    """(category, second category or "") by rules. A category needs 2 points (its old type alone is enough); the second
    needs 3 and another group."""
    ranked = sorted(scores(record, meta, item).items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < 2:
        return "other", ""
    first = ranked[0][0]
    group = cats.CATEGORIES[first].group
    second = next((c for c, s in ranked[1:] if s >= 3 and cats.CATEGORIES[c].group != group), "")
    return first, second


def category_of(item: dict, record: dict | None, meta: dict | None = None, view: dict | None = None) -> tuple[str, str, str]:
    """(category, second, by) for a post: the owner's choice, else the built view's, else the stored one, else rules."""
    if item.get("category_by") == "owner" and item.get("category") in cats.CATEGORIES:
        return item["category"], item.get("category2") or "", "owner"
    if view:
        return view["category"], view.get("category2", ""), view.get("by", "ai")
    if item.get("category") in cats.CATEGORIES:
        return item["category"], item.get("category2") or "", item.get("category_by") or "rules"
    first, second = guess(record, meta, item)
    return first, second, "rules"


# ---- tabs without AI ----------------------------------------------------------------------------------------------

def _clock(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"{s // 60}:{s % 60:02d}"


def _free_items(source: str, tab: cats.Tab, record: dict, meta: dict) -> list[dict]:
    extras = record.get("extras") or {}
    ents = record.get("entities") or {}
    targets = record.get("link_targets") or []
    listed = record.get("list_items") or []
    if source == "ingredients":
        return tidy_items(extras.get("ingredients"))
    if source == "steps":
        if extras.get("steps"):
            return tidy_items(extras.get("steps"))
        source = "chapters"
    if source == "chapters":
        # sources.py saves a chapter as {"start", "title"} (yt-dlp's start_time, renamed): the free tab reads that
        return tidy_items([{"name": c.get("title"), "at": _clock(c.get("start", c.get("start_time")))}
                           for c in meta.get("chapters") or [] if isinstance(c, dict)])
    if source == "list_items":
        want = {"tracks": ("music",)}.get(tab.id, ())
        return tidy_items([{"name": x.get("name"), "detail": x.get("by"), "kind": x.get("kind")}
                           for x in listed if isinstance(x, dict) and x.get("kind") in want])
    if source == "books_media":
        want = {"titles": ("film", "show"), "books": ("book",)}.get(tab.id, ())
        items = [{"name": x.get("name"), "detail": x.get("by") or x.get("note"), "kind": x.get("kind")}
                 for x in listed if isinstance(x, dict) and x.get("kind") in want]
        if not items and tab.id == "titles" and extras.get("media_kind") in ("film", "show", "series", "movie"):
            items = [{"name": extras.get("media_title")}]
        if not items and tab.id == "books" and extras.get("media_kind") == "book":
            items = [{"name": extras.get("media_title")}]
        return tidy_items(items)
    if source == "places":
        names = ([{"name": extras.get("place_name"), "group": extras.get("city"), "detail": extras.get("why")}]
                 + [{"name": t.get("name"), "detail": t.get("what")} for t in targets if isinstance(t, dict) and t.get("kind") == "place"]
                 + [{"name": p} for p in ents.get("places") or []]
                 + [{"name": x.get("name"), "detail": x.get("note")} for x in listed if isinstance(x, dict) and x.get("kind") == "place"])
        return _unique(names)
    if source == "products":
        return _unique([{"name": t.get("name"), "detail": t.get("what")} for t in targets if isinstance(t, dict) and t.get("kind") == "product"]
                       + [{"name": p} for p in ents.get("products") or []])
    if source == "tools":
        return _unique([{"name": t.get("name"), "detail": t.get("what")} for t in targets if isinstance(t, dict) and t.get("kind") in ("tool", "code")]
                       + [{"name": p} for p in (ents.get("tools") or []) + (ents.get("skills_code") or [])])
    return []


def _unique(items: list[dict]) -> list[dict]:
    """Repeats by name dropped, the first (richest) kept."""
    out, seen = [], set()
    for i in tidy_items(items):
        if i["name"].lower() not in seen:
            seen.add(i["name"].lower())
            out.append(i)
    return out


def free_view(category: str, category2: str, record: dict | None, meta: dict | None) -> dict:
    """The tabs this post can fill without AI, in the view's shape (by "rules")."""
    record, meta = record or {}, meta or {}
    tabs = {}
    wanted = list(cats.CATEGORIES[category].tabs) if category in cats.CATEGORIES else []
    if category2 in cats.CATEGORIES and cats.CATEGORIES[category2].lend:
        wanted.append(cats.CATEGORIES[category2].lend)
    for tab_id in wanted:
        tab = cats.TABS[tab_id]
        items = _free_items(tab.free, tab, record, meta) if tab.free else []
        if items:
            tabs[tab_id] = {"text": "", "items": items}
    return {"version": VERSION, "category": category, "category2": category2, "by": "rules", "made_at": "",
            "engine": "", "tabs": tabs, "lookups": {}}


def current(item: dict, record: dict | None, meta: dict | None, folder: Path | None) -> dict:
    """The view to show: the built one (under the owner's category if he changed it), else what rules can fill."""
    built = load(folder)
    category, second, by = category_of(item, record, meta, built)
    if built and built["category"] == category:
        return built
    view = free_view(category, second, record, meta)
    view["by"] = by
    return view


# ---- order --------------------------------------------------------------------------------------------------------

def hidden_tabs(setting: str) -> dict[str, list[str]]:
    """The owner's per-category hidden tabs, from the `view_tabs_off` setting (JSON); broken or unknown values ignored."""
    try:
        raw = json.loads(setting or "{}")
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {c: [t for t in v if isinstance(t, str) and t in cats.TABS] for c, v in raw.items()
            if c in cats.CATEGORIES and isinstance(v, list)}


def tab_plan(view: dict, core: dict[str, bool], hidden: dict[str, list[str]] | None = None) -> tuple[list[str], list[str]]:
    """(visible tab ids, tab ids in More). `core` says which core panes have something (read, deep, links, rel, tr).

    Order: read, sum, the category's tabs with content, the second category's lent tab, then deep, links, rel, tr, det.
    Summary and Details always show. When all the tabs fit in VISIBLE they all show and there is no More; otherwise
    VISIBLE_WITH_MORE show, so the category's own tabs come before Deeper dive, Links, Related and Transcript, which fold
    into More, in that order. Read (a
    saved page) is the post itself and keeps its place first."""
    hidden = hidden or {}
    category, second = view.get("category", "other"), view.get("category2", "")
    off = set(hidden.get(category, []))
    filled = {k for k, v in (view.get("tabs") or {}).items() if v.get("items") or v.get("text")}
    middle = [k for k in ("read",) if core.get(k)]
    own = [t for t in (cats.CATEGORIES[category].tabs if category in cats.CATEGORIES else ()) if t in filled and t not in off]
    middle += own
    lent = cats.CATEGORIES[second].lend if second in cats.CATEGORIES else ""
    if lent and lent in filled and lent not in own and lent not in set(hidden.get(second, [])):
        middle.append(lent)
    middle += [k for k in ("deep", "links", "rel", "tr") if core.get(k)]
    room = len(middle) if len(middle) + 2 <= VISIBLE else VISIBLE_WITH_MORE - 2
    first, rest = middle[:room], middle[room:]
    visible = (["read"] if "read" in first else []) + ["sum"] + [k for k in first if k != "read"] + ["det"]
    return visible, rest


def needs_build(view: dict) -> bool:
    """True when the category has tabs an AI would fill and no AI has built this view yet (an AI-built view always
    names its engine, also when the owner chose the category). The caller also checks Private mode."""
    # only a view an AI built and saved names an engine: who chose the category (category_by "ai" from a summary
    # whose view was missing or broken) says nothing about whether the tabs were built (review 14 Nov 2026)
    return (not view.get("engine") and view.get("category") in cats.CATEGORIES
            and bool(cats.CATEGORIES[view["category"]].tabs))


# ---- the AI's schema (views_ai.py writes the prompt; brain.py and the Build this view pass use both) -----------------

def ai_schema() -> dict:
    """Schema fragment (Gemini style, like brain.SCHEMA) for category, category2 and view."""
    s = {"type": "STRING"}
    item = {"type": "OBJECT", "properties": {k: s for k in ITEM_FIELDS}, "required": ["name"]}
    return {"category": {"type": "STRING", "enum": list(cats.IDS)},
            "category2": s,  # "" or a category id; checked by tidy_view (an enum cannot hold "")
            "view": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "tab": {"type": "STRING", "enum": list(cats.TABS)}, "text": s,
                "items": {"type": "ARRAY", "items": item}}, "required": ["tab", "items"]}}}
