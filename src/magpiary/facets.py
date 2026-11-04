"""Facets: what a post is like, not only what it says (format, setting, look, mood, what is on screen, who is seen).

The AI fills them in the same call that writes the summary, from the frames and transcript only. The Mac adds the
ones it can work out without AI (length, and the format when the post has no speech or is a still), so Private mode
has some too. The owner's edits are kept apart from the automatic ones: a summary run again replaces only the
automatic values.
"""

import re

FACETS = {  # key -> label shown in the hub
    "format": "Format", "setting": "Setting", "look": "Look", "mood": "Mood",
    "on_screen": "On screen", "people": "People", "length": "Length"}
ORDER = tuple(FACETS)
MAX_VALUES, MAX_LEN = 4, 40
FORMATS = ("talking head", "screen recording", "b-roll montage", "slideshow", "text on screen", "interview",
           "tutorial demo", "voiceover", "animation", "photo", "thread")
LENGTHS = ((30, "short"), (180, "medium"), (10 ** 9, "long"))  # seconds


def clean_value(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower().strip(".,;:!")[:MAX_LEN]


def tidy_facets(raw) -> dict[str, list[str]]:
    """The AI's facets in expected shape: known keys only, short lower-case values, no repeats, at most four each."""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    for key in ORDER:
        values = raw.get(key)
        values = [values] if isinstance(values, str) else values if isinstance(values, list) else []
        seen: list[str] = []
        for v in values:
            v = clean_value(v)
            if v and v not in seen:
                seen.append(v)
        if seen:
            out[key] = seen[:MAX_VALUES]
    return out


def tidy_look(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:400]


def length_value(seconds) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    return next(name for limit, name in LENGTHS if s <= limit)


def local_facets(duration, has_speech: bool | None, is_video: bool) -> dict[str, list[str]]:
    """What the Mac can say without AI: how long it is, and a plain format guess when nothing else is known."""
    out: dict[str, list[str]] = {}
    length = length_value(duration) if is_video else ""
    if length:
        out["length"] = [length]
    if is_video and has_speech is False:
        out["format"] = ["text on screen"]
    return out


def labelled(facets: dict[str, list[str]]) -> list[tuple[str, str, list[str]]]:
    """(key, label, values) in display order, only those that have values."""
    return [(k, FACETS[k], facets[k]) for k in ORDER if facets.get(k)]
