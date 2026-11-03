"""Who may do the AI work beyond a post's normal summary (the Digest, Ask Magpiary and Deeper dive), and in what order
(owner decisions 4 Nov 2026, docs/specs.md "Local engines need permission").

Claude Code and Codex on this Mac are used only once the owner allows them in Settings > AI & digest > AI keys, after a
dialog and a test run. They start off for everyone. The order of preference: the allowed local engines (the first one
allowed first), then paid keys, then free-tier keys. With a local engine or a paid key, the three features are on by
themselves; with only free-tier keys they are off (the Digest and Ask can be turned on anyway, with a warning; Deeper dive
never uses a free-tier key). Each feature remembers the owner's own on, off and engine choice.
"""

import json
import subprocess
from datetime import datetime

ALLOWED = "local_allowed"  # JSON list of the allowed local engines, in the order they were allowed
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


def options(store, keys=None, free: bool = True) -> list[dict]:
    """Every engine that can do the work, best first: {"id", "kind" (claude_code, codex or key), "key", "label", "free"}.
    Local engines only when allowed and installed; free-tier keys last, and only when `free`."""
    from magpiary import keys as keyring

    out = [{"id": k, "kind": k, "key": None, "label": LOCAL[k], "free": False} for k in allowed(store) if installed(k)]
    ai = [k for k in _keys(keys) if keyring.PROVIDERS.get(k.provider, {}).get("kind") == "ai" and not k.refused]
    out += [{"id": f"key:{k.id}", "kind": "key", "key": k, "label": k.name, "free": False} for k in ai if not is_free(k)]
    if free:
        out += [{"id": f"key:{k.id}", "kind": "key", "key": k, "label": k.name, "free": True} for k in ai if is_free(k)]
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
    if state == "on":
        return bool(options(store, keys, free=feature not in NO_FREE))
    return strong(store, keys)


def only_free(store, keys=None) -> bool:
    """Only free-tier keys could do it: turning a feature on needs the warning."""
    return not strong(store, keys) and bool(options(store, keys, free=True))


def set_on(store, feature: str, on: bool) -> None:
    store.set_setting(_state_key(feature), "on" if on else "off")


def choice(store, feature: str, keys=None) -> dict | None:
    """The engine the feature uses: the owner's pick when it is still usable, else the first in order."""
    usable = options(store, keys, free=feature not in NO_FREE)
    wanted = store.get_setting(_choice_key(feature), "")
    return next((o for o in usable if o["id"] == wanted), usable[0] if usable else None)


def choose(store, feature: str, engine_id: str, keys=None) -> bool:
    if engine_id in {o["id"] for o in options(store, keys, free=feature not in NO_FREE)}:
        store.set_setting(_choice_key(feature), engine_id)
        return True
    return False


def warning(feature: str) -> str:
    return FREE_WARNING.format(feature=FEATURES.get(feature, feature))
