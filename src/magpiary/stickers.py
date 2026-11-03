"""Board stickers: an emoji drawn like a die-cut sticker, picked from the board's name by matching words on this Mac
(no AI). Every Mac picks the same one from the same name, so a board needs no extra data until its creator chooses
another; that choice travels with a rename event."""

import json
import re
from pathlib import Path

# id: (emoji, words that pick it). Order matters only for ties: earlier wins.
STICKERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "coffee": ("☕", ("coffee", "cafe", "espresso", "latte", "cortado", "barista", "brew", "gaggia", "cappuccino", "mocha")),
    "tea": ("🍵", ("tea", "matcha", "chai")),
    "food": ("🍜", ("food", "eat", "eats", "ramen", "noodle", "restaurant", "dinner", "lunch", "brunch", "foodie")),
    "recipe": ("🍳", ("recipe", "recipes", "cook", "cooking", "kitchen", "bake", "meal", "meals")),
    "pizza": ("🍕", ("pizza", "pasta", "italian")),
    "cake": ("🍰", ("cake", "dessert", "sweet", "sweets", "baking", "bakery", "pastry")),
    "drinks": ("🍸", ("drink", "drinks", "cocktail", "cocktails", "bar", "bars", "wine", "beer")),
    "plane": ("✈️", ("trip", "travel", "flight", "flights", "holiday", "vacation", "abroad", "journey")),
    "beach": ("🏖️", ("beach", "island", "goa", "summer", "sea", "coast", "bali")),
    "mountain": ("🏔️", ("mountain", "mountains", "hike", "hiking", "trek", "trekking", "ski", "himalaya")),
    "camping": ("🏕️", ("camp", "camping", "outdoors", "nature", "forest")),
    "city": ("🏙️", ("city", "cities", "lisbon", "paris", "london", "tokyo", "mumbai", "delhi", "york", "berlin", "weekend")),
    "map": ("🗺️", ("map", "places", "explore", "guide", "itinerary", "spots")),
    "home": ("🏠", ("home", "house", "flat", "flats", "apartment", "rent", "renting", "move", "moving")),
    "sofa": ("🛋️", ("interior", "interiors", "decor", "furniture", "living", "room", "sofa")),
    "plant": ("🪴", ("plant", "plants", "garden", "gardening", "balcony", "green")),
    "gift": ("🎁", ("gift", "gifts", "present", "presents", "birthday", "wishlist", "christmas", "diwali")),
    "party": ("🎉", ("party", "celebration", "celebrate", "wedding", "event", "events", "anniversary")),
    "heart": ("❤️", ("love", "date", "dates", "romance", "couple", "us", "favourites", "favorites")),
    "music": ("🎵", ("music", "song", "songs", "playlist", "band", "concert", "gig")),
    "guitar": ("🎸", ("guitar", "instrument", "jam")),
    "film": ("🎬", ("film", "films", "movie", "movies", "cinema", "watch", "watchlist", "series", "shows")),
    "book": ("📚", ("book", "books", "read", "reading", "library", "novel", "study", "learn", "learning")),
    "art": ("🎨", ("art", "design", "designs", "drawing", "paint", "painting", "creative", "inspo", "inspiration")),
    "camera": ("📷", ("photo", "photos", "photography", "camera", "shoot", "reels", "video", "content")),
    "fashion": ("👗", ("fashion", "outfit", "outfits", "clothes", "style", "wardrobe", "dress")),
    "sneaker": ("👟", ("shoes", "sneaker", "sneakers", "running", "run", "marathon")),
    "beauty": ("💄", ("beauty", "makeup", "skincare", "skin", "hair")),
    "fitness": ("💪", ("fitness", "gym", "workout", "workouts", "training", "strength", "exercise")),
    "yoga": ("🧘", ("yoga", "meditation", "calm", "mindful", "wellness", "health", "selfcare")),
    "bike": ("🚲", ("bike", "bikes", "cycling", "cycle", "ride")),
    "car": ("🚗", ("car", "cars", "drive", "roadtrip", "road", "auto")),
    "football": ("⚽", ("football", "soccer", "sport", "sports", "match", "game")),
    "game": ("🎮", ("gaming", "games", "videogame", "console", "play")),
    "puzzle": ("🧩", ("puzzle", "puzzles", "boardgames", "fun")),
    "laptop": ("💻", ("code", "coding", "dev", "developer", "software", "programming", "tech", "laptop", "app", "apps")),
    "robot": ("🤖", ("ai", "robot", "automation", "agents", "llm", "gpt", "claude")),
    "tools": ("🛠️", ("tools", "tool", "diy", "fix", "repair", "build", "making", "maker", "restoration")),
    "rocket": ("🚀", ("startup", "startups", "launch", "growth", "product", "side", "project", "projects", "ship")),
    "chart": ("📈", ("business", "marketing", "sales", "money", "finance", "invest", "investing", "stocks", "crypto")),
    "work": ("💼", ("work", "job", "jobs", "career", "office", "team", "meeting", "hiring")),
    "idea": ("💡", ("idea", "ideas", "brainstorm", "tips", "hacks", "think")),
    "school": ("🎓", ("school", "college", "university", "course", "courses", "exam", "class")),
    "baby": ("🍼", ("baby", "babies", "kids", "kid", "parenting", "family", "toddler")),
    "dog": ("🐶", ("dog", "dogs", "puppy", "pet", "pets")),
    "cat": ("🐱", ("cat", "cats", "kitten")),
    "flower": ("🌸", ("flower", "flowers", "spring", "bloom", "wedding")),
    "sun": ("☀️", ("sun", "sunny", "morning", "routine", "day")),
    "moon": ("🌙", ("night", "sleep", "evening", "dream", "dreams")),
    "snow": ("❄️", ("winter", "snow", "cold")),
    "leaf": ("🍂", ("autumn", "fall", "cozy", "cosy")),
    "shopping": ("🛍️", ("shop", "shopping", "buy", "deals", "sale", "store", "stores")),
    "cart": ("🛒", ("grocery", "groceries", "list", "lists", "essentials")),
    "star": ("⭐", ("best", "top", "star", "must", "picks", "favourite", "favorite")),
    "fire": ("🔥", ("hot", "trending", "viral", "fire", "spicy")),
    "sparkles": ("✨", ("magic", "aesthetic", "pretty", "cute", "vibes", "vibe")),
    "laugh": ("😂", ("funny", "memes", "meme", "lol", "jokes", "comedy", "humour", "humor")),
    "globe": ("🌍", ("world", "global", "news", "culture", "languages", "language")),
    "pin": ("📌", ()),  # the fallback: a pin on a board
    "rainbow": ("🌈", ("pride", "colour", "color", "colourful", "colorful", "kids")),
}

GENERIC = {"idea", "ideas", "list", "lists", "tips", "hacks", "best", "top", "stuff", "things", "misc", "my", "our"}
DEFAULT = "pin"
WORD = re.compile(r"[a-z0-9]+")


def pick(name: str) -> str:
    """The sticker whose words best match a board's name: a whole word counts 2, a word starting with one counts 1.
    No match among the curated stickers: the best match in the whole emoji set (its name and keywords); else a pin."""
    words = WORD.findall(name.lower())
    words = [w for w in words if w not in GENERIC] or words  # "Zebra ideas" is about zebras
    best, score = DEFAULT, 0
    for sid, (_, keys) in STICKERS.items():
        s = sum(2 if w in keys else 1 if len(w) >= 4 and any(w.startswith(k) for k in keys if len(k) >= 4) else 0
                for w in words)
        if s > score:
            best, score = sid, s
    found = search(" ".join(words), 1, scored=True)
    if found and (not score or found[0][0] > score + 1):
        return found[0][1]
    return best


_SET: dict | None = None


def emoji_set() -> dict:
    """Every emoji: {"groups": [names], "e": [[emoji, name, keywords, group], ...]} (the file the picker loads too)."""
    global _SET
    if _SET is None:
        try:
            _SET = json.loads((Path(__file__).parent / "static" / "emoji.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _SET = {"groups": [], "e": []}
    return _SET


def search(query: str, limit: int = 40, scored: bool = False) -> list:
    """Emojis for some words, best first: a word in the emoji's name counts 3, in its keywords 2, a longer word starting
    with one 1; flags and symbols come after everything else of the same score."""
    words = [w for w in WORD.findall(query.lower()) if len(w) >= 3]
    if not words:
        return []
    out = []
    for i, (char, label, tags, group) in enumerate(emoji_set()["e"]):
        names, keys = set(WORD.findall(label.lower())), set(tags.split())
        s = sum(3 if w in names else 2 if w in keys else
                1 if len(w) >= 4 and any(k.startswith(w) or w.startswith(k) for k in names | keys if len(k) >= 4) else 0
                for w in words)
        if s:
            out.append((-s + (0.5 if group >= 7 else 0), i, char))
    top = sorted(out)[:limit]
    return [(round(-r), c) for r, _, c in top] if scored else [c for _, _, c in top]


def emoji(sid: str) -> str:
    """A sticker id's emoji; any other emoji (picked with the Mac's emoji window) is its own sticker."""
    if sid in STICKERS:
        return STICKERS[sid][0]
    return sid if is_emoji(sid) else STICKERS[DEFAULT][0]


def is_emoji(text) -> bool:
    """One emoji (with its joiners and skin tones), nothing typed: no letters, digits, spaces or markup."""
    return (isinstance(text, str) and 0 < len(text) <= 16 and not re.search(r"[\x00-\x7f\s]", text)
            and any(ord(ch) >= 0x2190 for ch in text))


def valid(sid) -> bool:
    return isinstance(sid, str) and (sid in STICKERS or is_emoji(sid))
