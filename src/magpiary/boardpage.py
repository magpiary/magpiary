"""A captured page's text as a board member can read it ("Save what I see" pages shared on a board).

A page the Chrome extension saved only exists on the Mac that saved it, and sites such as Behance refuse a logged-out
fetch, so a friend's Mac can never download it again. When the owner explicitly ticks "share the page text", the card is
followed by one more sealed event carrying this snapshot: the title, byline and the readable blocks in order (headings,
paragraphs, lists, quotes, code, picture captions), squeezed with zlib. No pictures, videos, screenshots or the page copy
travel, and no address inside the page is kept except the post's own link, which is already on the card.
Everything that arrives from a friend is cleaned again here: it is data, never trusted."""

import base64
import json
import zlib

LIMIT = 30_000          # characters of base64 in one snapshot: with its envelope it stays under every relay's event limit
RAW_MAX = 250_000        # characters of text in one snapshot
INFLATED_MAX = 400_000  # bytes a snapshot may unpack to (a zip bomb from a friend is refused)
TEXT_KINDS = {"h", "p", "li", "quote", "code", "caption"}
BLOCK_CHARS = 4000
MAX_BLOCKS = 800


def _blocks(article: dict) -> list[dict]:
    out = []
    for raw in article.get("blocks") or []:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("t")
        if not isinstance(kind, str):
            continue
        if kind in TEXT_KINDS and isinstance(raw.get("text"), str) and raw["text"].strip():
            block = {"t": kind, "text": raw["text"].strip()[:BLOCK_CHARS]}
            if kind == "h":
                block["level"] = raw.get("level") if raw.get("level") in (2, 3, 4, 5, 6) else 2
            if kind == "li":
                block["ordered"] = raw.get("ordered") is True
            out.append(block)
        elif kind == "row" and isinstance(raw.get("items"), list):
            items = [str(i).strip()[:300] for i in raw["items"][:20] if str(i).strip()]
            if items:
                out.append({"t": "row", "items": items})
        elif kind == "img":  # the picture itself stays home; its words go along
            said = raw.get("caption") or raw.get("alt") or raw.get("text")
            words = said.strip() if isinstance(said, str) else ""
            out.append({"t": "img", "text": words[:500]})
    return out


def _pack(snapshot: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode(), 9)).decode()


def build(article: dict) -> str:
    """The snapshot as base64 text that fits one event, cutting from the end (and saying so) when the page is longer.
    Empty when the page has no readable text."""
    blocks, chars = [], 0
    for b in _blocks(article)[:MAX_BLOCKS]:  # also what a Mac will agree to unpack: the cut never depends on how well it squeezes
        chars += len(b.get("text", "")) + sum(map(len, b.get("items", [])))
        if chars > RAW_MAX:
            break
        blocks.append(b)
    if not any(b["t"] != "img" for b in blocks):
        return ""
    head = {"title": str(article.get("title") or "")[:300], "byline": str(article.get("byline") or "")[:200],
            "site": str(article.get("site") or "")[:100], "published": str(article.get("published") or "")[:40]}
    total = len(_blocks(article))
    pictures = sum(b["t"] == "img" for b in _blocks(article))
    lo, hi, best = 0, len(blocks), ""
    while lo <= hi:  # the most blocks that still fit
        mid = (lo + hi) // 2
        snapshot = {**head, "blocks": blocks[:mid], "cut": total - mid, "pictures": pictures}
        packed = _pack(snapshot)
        # also what a Mac will agree to unpack: the same limit decode() applies, counted in bytes
        if len(packed) <= LIMIT and len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()) <= INFLATED_MAX:
            best, lo = packed, mid + 1
        else:
            hi = mid - 1
    return best


def size_note(article: dict) -> str:
    """How big the snapshot would be, for the share window: "about 12 KB"."""
    packed = build(article)
    return f"about {max(1, round(len(packed) * 3 / 4 / 1024))} KB" if packed else ""


def decode(text) -> dict | None:
    """A friend's snapshot, opened and cleaned; None when it is not a good one."""
    if not isinstance(text, str) or not text or len(text) > LIMIT:
        return None
    try:
        unpacker = zlib.decompressobj()
        data = unpacker.decompress(base64.b64decode(text, validate=True), INFLATED_MAX)
        if unpacker.unconsumed_tail:
            return None
        raw = json.loads(data)
    except (ValueError, zlib.error, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    clean = _blocks({"blocks": raw.get("blocks") if isinstance(raw.get("blocks"), list) else []})[:MAX_BLOCKS]
    if not clean:
        return None
    number = lambda v: v if isinstance(v, int) and 0 <= v < 1_000_000 else 0  # noqa: E731
    return {**{k: str(raw.get(k) or "")[:300] for k in ("title", "byline", "site", "published")},
            "blocks": clean, "cut": number(raw.get("cut")), "pictures": number(raw.get("pictures"))}
