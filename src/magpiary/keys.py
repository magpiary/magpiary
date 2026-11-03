"""The owner's AI keys, in their order, in ~/.config/magpiary/keys.json (mode 0600).

A key is never shown again, logged or printed after it is saved; the pages show its label, provider,
tier and state. Magpiary uses the first usable key and moves down the list when one hits its limit
(until the next day) or is refused (until it is replaced).
"""

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import date

from magpiary.brain import BrainFailed, Call, choose_model, http_call
from magpiary.config import config_dir

PROVIDERS = {
    "gemini": {"name": "Google Gemini", "ready": True, "kind": "ai", "url": "https://aistudio.google.com/apikey",
               "steps": ["Open Google AI Studio (the button above) and sign in with your Google account.",
                         "Click “Create API key”. If asked, pick or create a Google Cloud project.",
                         "Copy the key (it starts with “AIza”) and paste it here.",
                         "Free or paid: a key is free unless you turned on billing for its project in AI Studio "
                         "(“Set up billing”). With billing on, Google says it does not use your content to improve its products."]},
    "openrouter": {"name": "OpenRouter (many models, some free)", "ready": True, "kind": "ai",
                   "url": "https://openrouter.ai/settings/keys",
                   "steps": ["Open OpenRouter (the button above), sign in, and open Settings → API Keys.",
                             "Click “Create Key”, give it a name (e.g. Magpiary), and copy it (it starts with “sk-or-”).",
                             "Free or paid: free models (their names end in “:free”) cost nothing, up to 50 requests a day, "
                             "or 1,000 a day once you have bought $10 of credit. Choose “Paid” here if you added credit.",
                             "Recommended: in OpenRouter's Settings → Privacy, turn off providers that may train on your "
                             "data (there are separate switches for free and paid models).",
                             "Magpiary starts with Nemotron 3.5 Super VL (free), which reads the frames too; you can pick "
                             "another model below, for example qwen/qwen3.8-flash (about $0.002 a save)."]},
    "claude": {"name": "Anthropic Claude", "ready": True, "kind": "ai", "url": "https://platform.claude.com/settings/keys",
               "steps": ["Open the Claude Console (the button above) and sign in.",
                         "Add credits under Billing: Claude's API has no free tier.",
                         "Click “Create Key”, copy it (it starts with “sk-ant-”).",
                         "Magpiary uses Claude Haiku 5.5, the fast and cheap model (about $0.002 a save); you can pick "
                         "another model below."]},
    "openai": {"name": "OpenAI", "ready": True, "kind": "ai", "url": "https://platform.openai.com/api-keys",
               "steps": ["Open the OpenAI API keys page (the button above) and sign in.",
                         "Add a payment method under Billing: OpenAI's API has no free tier.",
                         "Click “Create new secret key”, copy it (it starts with “sk-”).",
                         "Magpiary uses OpenAI's newest mini model (fast and cheap); you can pick another model below."]},
    "tavily": {"name": "Tavily (finds links; recommended)", "ready": True, "kind": "search",
               "url": "https://app.tavily.com/",
               "steps": ["Open Tavily (the button above) and sign up. No card is needed.",
                         "The free plan gives 1,000 searches a month; when they are used up, searches simply stop "
                         "until the next month. Nothing is ever charged.",
                         "Copy the API key shown on the overview page (it starts with “tvly-”).",
                         "Paste it here. Magpiary uses it only to look up the names a post mentions, after its free "
                         "directories, so a month's searches go a long way."]},
    "brave": {"name": "Brave Search (finds links)", "ready": True, "kind": "search",
              "url": "https://api-dashboard.search.brave.com/",
              "steps": ["Open the Brave Search API dashboard (the button above) and create an account.",
                        "Choose the Search plan. Brave asks for a card and gives $5 of credit each month (about 1,000 "
                        "searches); credit you buy on top is charged, so leave Magpiary's monthly limit on.",
                        "Brave reportedly asks that projects using the free credit mention Brave Search on their site.",
                        "Open “API Keys”, click “Add API key”, copy it and paste it here."]},
}
TIERS = {"free": "Free", "paid": "Paid (billing on)"}


@dataclass
class Key:
    id: str
    provider: str
    tier: str
    secret: str
    label: str
    model: str
    added: str
    limit_day: str = ""   # hit its limit on this day: skipped until the next day
    refused: str = ""     # the provider refused it: skipped until it is replaced

    def usable(self, today: str) -> bool:
        return PROVIDERS.get(self.provider, {}).get("ready", False) and not self.refused and self.limit_day != today

    @property
    def name(self) -> str:
        return self.label or f"{PROVIDERS[self.provider]['name'].split(' (')[0]} key ({TIERS[self.tier].split(' ')[0].lower()})"


def _path():
    return config_dir() / "keys.json"


def load() -> list[Key]:
    try:
        return [Key(**k) for k in json.loads(_path().read_text())]
    except (OSError, ValueError, TypeError):
        return []


def _save(keys: list[Key]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump([asdict(k) for k in keys], f)
    path.chmod(0o600)


def add(provider: str, tier: str, secret: str, label: str = "", call: Call = http_call, model: str = "",
        request=None) -> str | None:
    """Check the key with its provider (without using any of its quota), then append it.
    Returns an error to show, or None."""
    secret = secret.strip()
    if provider not in PROVIDERS or tier not in TIERS:
        return "Pick a provider and whether the key is free or paid."
    if not PROVIDERS[provider]["ready"]:
        return f"{PROVIDERS[provider]['name']} keys cannot be used yet."
    if not secret or len(secret) > 300 or any(c.isspace() for c in secret):
        return "That does not look like an API key."
    keys = load()
    if any(k.secret == secret for k in keys):
        return "This key is already saved."
    if PROVIDERS[provider]["kind"] == "search":
        problem = check_search_key(secret, provider)
        if problem:
            return problem
        model = "web search"
    elif provider == "gemini":
        try:
            model = choose_model(secret, call, probe=False)  # a key is saved at once; a slow model is swapped at first use
        except BrainFailed as err:
            return "Google refused this key." if err.reason == "bad_key" else f"Could not check the key: {err.detail}"
    else:
        from magpiary import providers

        try:
            default = (providers.check_claude(secret) if provider == "claude"
                       else providers.check_chat(provider, secret, request or providers.http_request))
        except BrainFailed as err:
            name = providers.NAMES[provider]
            return f"{name} refused this key." if err.reason == "bad_key" else f"Could not check the key: {err.detail}"
        model = _model_name(model) or default
    keys.append(Key(secrets.token_hex(4), provider, tier, secret, label.strip()[:40], model, date.today().isoformat()))
    _save(keys)
    return None


def remove(key_id: str) -> None:
    _save([k for k in load() if k.id != key_id])


def move(key_id: str, step: int) -> None:
    keys = load()
    i = next((n for n, k in enumerate(keys) if k.id == key_id), None)
    if i is None or not 0 <= i + step < len(keys):
        return
    keys[i], keys[i + step] = keys[i + step], keys[i]
    _save(keys)


def reorder(ids: list[str]) -> None:
    """The keys named in `ids` take that order among themselves (dragged in Settings); the others keep their places.
    The order is the order they are tried in."""
    keys = load()
    wanted = [k for i in ids for k in keys if k.id == i]
    if len({k.id for k in wanted}) != len(wanted) or not wanted:
        return
    slots = [n for n, k in enumerate(keys) if k.id in {w.id for w in wanted}]
    for n, k in zip(slots, wanted):
        keys[n] = k
    _save(keys)


def mark(key_id: str, limit: bool = False, refused: bool = False, today: str | None = None) -> None:
    keys = load()
    for k in keys:
        if k.id == key_id:
            if limit:
                k.limit_day = today or date.today().isoformat()
            if refused:
                k.refused = today or date.today().isoformat()
    _save(keys)


def set_model(key_id: str, model: str) -> None:
    keys = load()
    for k in keys:
        if k.id == key_id:
            k.model = model
    _save(keys)


def usable(today: str | None = None) -> list[Key]:
    """AI keys that can write summaries now, in the owner's order."""
    today = today or date.today().isoformat()
    return [k for k in load() if k.usable(today) and PROVIDERS[k.provider]["kind"] == "ai"]


def search_key(today: str | None = None) -> Key | None:
    """The first usable web search key (Tavily or Brave), or None."""
    today = today or date.today().isoformat()
    return next((k for k in load() if k.usable(today) and PROVIDERS[k.provider]["kind"] == "search"), None)


def check_search_key(secret: str, provider: str = "brave", get=None) -> str | None:
    """Check a search key: Tavily's usage page (no search spent), or one test search with Brave.
    Returns an error to show, or None."""
    from magpiary.links import http_get

    if provider == "tavily":
        try:
            status, _, _ = (get or http_get)("https://api.tavily.com/usage", {"Authorization": f"Bearer {secret}"})
        except OSError as err:
            return f"Could not check the key: {type(err).__name__}"
        if status in (401, 403):
            return "Tavily refused this key."
        return None if status in (200, 429, 432, 433) else f"Could not check the key (HTTP {status})"
    try:
        status, _, _ = (get or http_get)("https://api.search.brave.com/res/v1/web/search?q=magpiary&count=1",
                                         {"X-Subscription-Token": secret, "Accept": "application/json"})
    except OSError as err:
        return f"Could not check the key: {type(err).__name__}"
    if status in (401, 403, 422):
        return "Brave refused this key."
    if status == 429:
        return None  # a valid key that is resting
    return None if status == 200 else f"Could not check the key (HTTP {status})"


def _model_name(text: str) -> str:
    """A model name as the owner typed it, or "" if it does not look like one."""
    text = text.strip()
    return text if re.fullmatch(r"[A-Za-z0-9._:/@-]{2,100}", text) else ""


def change_model(key_id: str, model: str) -> bool:
    model = _model_name(model)
    if not model:
        return False
    set_model(key_id, model)
    return True


def repick(key: Key, call: Call = http_call) -> bool:
    """The key's model is busy or slow: choose another one (Gemini only). True if the model changed."""
    if key.provider != "gemini":
        return False
    try:
        model = choose_model(key.secret, call, avoid=key.model)
    except BrainFailed:
        return False
    if model == key.model:
        return False
    set_model(key.id, model)
    return True
