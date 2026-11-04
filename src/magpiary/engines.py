"""Who may do the AI work, and in what order (owner decisions 4 Nov 2026, docs/specs.md "Local engines need permission").

One list in Settings > AI & digest holds the AI keys and Claude Code and Codex on this Mac, in the order the owner drags
them into. Summaries are written by the first one in that order that can (an engine not allowed is skipped). The Digest,
Ask and Deeper dive use the first allowed engine or paid key in that order.

Claude Code and Codex on this Mac are used only once the owner allows them in Settings > AI & digest > AI keys, after a
dialog and a test run. They start off for everyone. The order of preference: the allowed local engines (the first one
allowed first), then paid keys, then free-tier keys. With a local engine or a paid key, the three features are on by
themselves; with only free-tier keys they are off (the Digest and Ask can be turned on anyway, with a warning; Deeper dive
never uses a free-tier key). Each feature remembers the owner's own on, off and engine choice.
"""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime

ALLOWED = "local_allowed"  # JSON list of the allowed local engines, in the order they were allowed
ORDER = "engine_order"  # JSON list of ids ("key:<id>", "claude_code", "codex"): the order the owner dragged them into
LOCAL = {"claude_code": "Claude Code on this Mac", "codex": "Codex on this Mac"}
SHORT = {"claude_code": "Claude Code", "codex": "Codex"}
PLAN = {"claude_code": "your Claude plan", "codex": "your ChatGPT plan"}
FEATURES = {"digest": "the Digest", "ask": "Ask Magpiary", "deep": "Deeper dive"}
NO_FREE = {"deep"}  # features that never use a free-tier key
FREE_WARNING = ("Using {feature} on a free key spends a lot of your AI quota, and other saves may wait for their summaries. "
                "Allow Claude Code or Codex in AI keys to run it on the plan you already have.")


def _state_key(feature: str) -> str:
    return f"{feature}_state"  # "" (decided by the rule), "on" or "off" (the owner's own choice)


def _choice_key(feature: str) -> str:
    return f"{feature}_engine_choice"


# ---- the local engines ---------------------------------------------------------------------------

def allowed(store) -> list[str]:
    try:
        value = json.loads(store.get_setting(ALLOWED, "[]") or "[]")
    except ValueError:
        return []
    return [v for v in value if v in LOCAL] if isinstance(value, list) else []


def is_allowed(store, kind: str) -> bool:
    return kind in allowed(store)


def installed(kind: str) -> bool:
    from magpiary import ask, ask_codex

    return ask.claude_available() if kind == "claude_code" else ask_codex.available() if kind == "codex" else False


def test_run(kind: str, run=subprocess.run) -> tuple[bool, str]:
    """A tiny prompt through the engine, the same headless way Magpiary uses it (a few tokens of the plan). (ok, why)."""
    from magpiary import ask_codex, claude_code
    from magpiary.config import data_dir

    if not installed(kind):
        return False, (f"{SHORT[kind]} isn't on this Mac" + (" or isn't signed in" if kind == "codex" else "")
                       + ". Set it up in Ask Magpiary's settings, then try again.")
    folder = data_dir() / ("claude" if kind == "claude_code" else "codex")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "claude_code":
            done = run([claude_code.command(), "-p", "--model", "haiku", "--system-prompt", "Reply with the single word ok.",
                        "--tools", "", "--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence"],
                       input="ok?", capture_output=True, text=True, timeout=120, cwd=folder)
        else:
            done = run([ask_codex.binary(), "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
                        *ask_codex.profile_config(folder), "-c", 'web_search="disabled"', "-c", "model_reasoning_effort=low", "-"],
                       input="Reply with the single word ok.", capture_output=True, text=True, timeout=180, cwd=folder)
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"{SHORT[kind]} did not finish the test ({type(err).__name__})."
    if done.returncode == 0 and (done.stdout or "").strip():
        return True, ""
    hint = "Run claude in Terminal once and sign in." if kind == "claude_code" else "Run codex in Terminal once and sign in."
    return False, f"{SHORT[kind]} did not answer the test. {hint}"


def allow(store, kind: str, test=None) -> tuple[bool, str]:
    """The owner allowed it in the dialog: it is tested, and only a passing test allows it. The three features then follow
    the rule again (on, using it). Returns (ok, why it failed)."""
    if kind not in LOCAL:
        return False, "Unknown engine."
    ok, why = (test or test_run)(kind)
    if not ok:
        return False, why
    now = allowed(store)
    if kind not in now:
        store.set_setting(ALLOWED, json.dumps([*now, kind]))
        ids = [i for i in order(store) if i != kind]  # it joins the end of the ones in use, ready to be dragged up
        in_use = {o["id"] for o in options(store)}
        at = max((n for n, i in enumerate(ids) if i in in_use), default=-1) + 1
        store.set_setting(ORDER, json.dumps(ids[:at] + [kind] + ids[at:]))
    store.set_setting(f"{kind}_allowed_at", datetime.now().isoformat(timespec="seconds"))
    for feature in FEATURES:
        store.set_setting(_state_key(feature), "")
    return True, ""


def disallow(store, kind: str, keys=None) -> None:
    """Stopped: features move to the next usable engine; with only free-tier keys left they turn off."""
    store.set_setting(ALLOWED, json.dumps([k for k in allowed(store) if k != kind]))
    for feature in FEATURES:
        if store.get_setting(_choice_key(feature), "") == kind:
            store.set_setting(_choice_key(feature), "")
        if not strong(store, keys):
            store.set_setting(_state_key(feature), "")


# ---- engines in order --------------------------------------------------------------------------

def _keys(keys):
    from magpiary import keys as keyring

    return keys if keys is not None else keyring.load()


def is_free(key) -> bool:
    return getattr(key, "tier", "free") == "free"


def order(store, keys=None) -> list[str]:
    """Every AI key and both local engines, in the owner's order: the saved order first, then keys not in it (in the keys'
    own order), then the local engines not in it."""
    from magpiary import keys as keyring

    ids = [f"key:{k.id}" for k in _keys(keys) if keyring.PROVIDERS.get(k.provider, {}).get("kind") == "ai"] + list(LOCAL)
    try:
        saved = json.loads(store.get_setting(ORDER, "[]") or "[]")
    except ValueError:
        saved = []
    saved = [i for i in saved if i in ids] if isinstance(saved, list) else []
    return saved + [i for i in ids if i not in saved]


def set_order(store, ids: list[str], keys=None) -> bool:
    """The owner dragged the list into this order. The keys' own file follows, so every reader sees the same order."""
    from magpiary import keys as keyring

    known = order(store, keys)
    if sorted(ids) != sorted(known) or len(set(ids)) != len(ids):
        return False
    store.set_setting(ORDER, json.dumps(ids))
    keyring.reorder([i[4:] for i in ids if i.startswith("key:")])
    return True


def options(store, keys=None, free: bool = True) -> list[dict]:
    """Every engine that can do the work, in the owner's order: {"id", "kind" (claude_code, codex or key), "key", "label",
    "free"}. Local engines only when allowed and installed; free-tier keys only when `free`."""
    from magpiary import keys as keyring

    by_id = {f"key:{k.id}": k for k in _keys(keys) if keyring.PROVIDERS.get(k.provider, {}).get("kind") == "ai" and not k.refused}
    ok = set(allowed(store))
    out = []
    for i in order(store, keys):
        if i in LOCAL:
            if i in ok and installed(i):
                out.append({"id": i, "kind": i, "key": None, "label": LOCAL[i], "free": False})
        elif i in by_id and (free or not is_free(by_id[i])):
            out.append({"id": i, "kind": "key", "key": by_id[i], "label": by_id[i].name, "free": is_free(by_id[i])})
    return out


def strong(store, keys=None) -> bool:
    """A local engine is allowed or a paid key is saved: the three features are on by themselves."""
    return any(not o["free"] for o in options(store, keys, free=False))


def is_on(store, feature: str, keys=None) -> bool:
    from magpiary import modes

    if modes.current(store) == "private":
        return False
    state = store.get_setting(_state_key(feature), "")
    if state == "off":
        return False
    if state == "on":  # the owner's own choice; the feature itself says when nobody can answer (Deeper dive: never a free key)
        return bool(options(store, keys, free=False)) if feature in NO_FREE else True
    return strong(store, keys)


def only_free(store, keys=None) -> bool:
    """Only free-tier keys could do it: turning a feature on needs the warning."""
    return not strong(store, keys) and bool(options(store, keys, free=True))


def set_on(store, feature: str, on: bool) -> None:
    store.set_setting(_state_key(feature), "on" if on else "off")


def choice(store, feature: str, keys=None) -> dict | None:
    """The engine the feature uses: the owner's pick when it is still usable, else the first local engine or paid key in
    the owner's order, else (Digest and Ask only) the first free key."""
    usable = options(store, keys, free=feature not in NO_FREE)
    wanted = store.get_setting(_choice_key(feature), "")
    return next((o for o in usable if o["id"] == wanted), next((o for o in usable if not o["free"]), usable[0] if usable else None))


# ---- summaries ----------------------------------------------------------------------------------

@dataclass
class LocalEngine:
    """Claude Code or Codex standing where a key stands in the summary queue (brain.summarise knows how to ask it)."""
    id: str
    provider: str
    model: str
    tier: str = "local"
    secret: str = "local"
    refused: str = ""

    @property
    def name(self) -> str:
        return SHORT[self.id]


SUMMARY_MODELS = {"claude_code": "haiku", "codex": "gpt-6-luna"}  # light and quick: a summary is short work


def summarisers(store, keys=None, today: str | None = None) -> list:
    """Who can write the next summary, in the owner's order: usable AI keys and allowed local engines."""
    from datetime import date

    today = today or date.today().isoformat()
    usable = {f"key:{k.id}": k for k in _keys(keys) if k.usable(today)}
    ok = set(allowed(store))
    out = []
    for i in order(store, keys):
        if i in LOCAL:
            if i in ok and installed(i):
                out.append(LocalEngine(i, i, SUMMARY_MODELS[i]))
        elif i in usable:
            out.append(usable[i])
    return out


def choose(store, feature: str, engine_id: str, keys=None) -> bool:
    if engine_id in {o["id"] for o in options(store, keys, free=feature not in NO_FREE)}:
        store.set_setting(_choice_key(feature), engine_id)
        return True
    return False


def warning(feature: str) -> str:
    return FREE_WARNING.format(feature=FEATURES.get(feature, feature))
