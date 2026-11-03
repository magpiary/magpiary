"""Text that is on screen in a post's frames and photos, read on this Mac with Apple's own text recognition (Vision).
Nothing leaves the Mac. Without the Vision bindings (not a Mac, or not installed) nothing is read and nothing fails."""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

MIN_CONFIDENCE = 0.5
MIN_LENGTH = 3
IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def read_lines(path: Path) -> list[tuple[str, float]]:
    """(text, confidence) for each line of text Vision finds in an image. [] when it cannot be read."""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError:
        return []
    try:
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)  # the accurate level needs the neural engine and fails on some Macs
        ok, _ = handler.performRequests_error_([request], None)
        if not ok:
            return []
        return [(c.string(), float(c.confidence())) for o in (request.results() or []) if (c := (o.topCandidates_(1) or [None])[0])]
    except Exception:
        return []


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    """English words on this Mac (macOS ships a word list). Empty if there is none: the shape rules still apply."""
    for name in ("/usr/share/dict/words", "/usr/share/dict/web2"):
        try:
            return frozenset(w.strip().lower() for w in Path(name).read_text(errors="ignore").splitlines() if len(w.strip()) >= 2)
        except OSError:
            continue
    return frozenset()


def _fold(token: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", token.lower()) if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return [t for t in (re.sub(r"^[^\w]+|[^\w]+$", "", t) for t in text.split()) if t]


def _good(token: str, known: frozenset[str], dictionary: frozenset[str]) -> bool:
    """A real word: in the dictionary, or a word the post itself uses (names, products), or a clean capitalised word."""
    word = _fold(token)
    if not re.fullmatch(r"[a-z]+(?:['’-][a-z]+)*", word):
        return False
    if word in known or (not dictionary and len(word) >= 3 and re.search(r"[aeiouy]", word)):
        return True
    parts = re.split(r"['’-]", word)
    return all(part in dictionary or part in known for part in parts if part)


def clean(lines: list[tuple[str, float]], known: frozenset[str] = frozenset()) -> list[str]:
    """Keep lines of real words. Dropped: low confidence, broken characters, lots of symbols, and lines where fewer than two
    thirds of the words are words (credits in tiny print and half-read text come out as junk like "Jozge )araffiillo")."""
    dictionary = _dictionary()
    out = []
    for text, confidence in lines:
        text = re.sub(r"\s+", " ", text).strip()
        if confidence < MIN_CONFIDENCE or len(text) < MIN_LENGTH or "\ufffd" in text or "\uffff" in text:
            continue
        odd = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in ".,'’\"!?-:;%$&()/"))
        if odd / len(text) > 0.05:
            continue
        tokens = _tokens(text)
        if not tokens or not re.search(r"[^\W\d_]{3}", text):
            continue
        words = [t for t in tokens if len(t) >= 2]
        good = [t for t in words if _good(t, known, dictionary)]
        if len(words) >= 2:
            ok = len(good) / len(words) >= 0.66 and len(good) >= 2
        else:
            ok = bool(good) and len(words[0]) >= 4 and confidence >= 0.6 if words else False
        if ok:
            out.append(text)
    return out


def read_post(folder: Path, frames: list[dict], photos: list[str], read=read_lines, known: frozenset[str] = frozenset()) -> list[dict]:
    """[{"at": seconds or None, "text": line}] across a post's frames and photos, each line once (the same text shows in
    many frames)."""
    seen: set[str] = set()
    found: list[dict] = []
    sources = [(f.get("at"), folder / f["path"]) for f in frames if f.get("path")] + [(None, folder / p) for p in photos]
    for at, path in sources:
        if not path.exists():
            continue
        for line in clean(read(path), known):
            key = re.sub(r"\W+", "", line.lower())
            if key and key not in seen:
                seen.add(key)
                found.append({"at": at, "text": line})
    return found


def known_words(*texts: str) -> frozenset[str]:
    """The words the post itself uses (title, caption, summary, what was said): a name or product it shows on screen counts."""
    return frozenset(_fold(w) for t in texts for w in re.findall(r"[^\W\d_]{3,}", t or ""))


def cloud(lines: list[dict], limit: int = 60) -> list[dict]:
    """Words for a small word cloud: [{"word", "count", "at": [seconds…]}], most shown first. Stop words and short words out."""
    from magpiary.related import STOP

    seen: dict[str, dict] = {}
    for line in lines:
        for token in _tokens(line["text"]):
            word = _fold(token)
            if len(word) < 3 or word in STOP or not re.fullmatch(r"[a-z]+(?:['’-][a-z]+)*", word):
                continue
            entry = seen.setdefault(word, {"word": token if not token.isupper() else token.capitalize(), "count": 0, "at": []})
            entry["count"] += 1
            if line.get("at") is not None and line["at"] not in entry["at"]:
                entry["at"].append(line["at"])
    return sorted(seen.values(), key=lambda e: (-e["count"], e["word"].lower()))[:limit]
