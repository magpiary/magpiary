"""How summaries are made (owner's decision, 24 Oct 2026). In both modes the transcript and frames are made on the
Mac and the video never leaves it.

- smart: the owner's AI keys (Gemini, OpenRouter, Claude, OpenAI; free or paid), in their order. When every key
  has reached its limit, saves wait.
- private: no AI at all. Nothing about a save is sent to any AI service. Saves are still downloaded, transcribed
  on the Mac, grouped into piles, related and searchable; there are no summaries, key points or AI tags.

A local AI model (Ollama) is deferred until there is demand: see docs/specs.md, "Later: a local AI model". When it
comes, `summarisers` is the one place it plugs in (a Balanced mode falling back to it, and Private using it).
"""

SETTING = "ai_mode"
MODES = {
    "smart": ("Smart", "Your AI keys (free or paid), in your order: summaries, key points, tags and links. Only the "
                       "caption, transcript and a few frames are sent. When every key has reached its limit, saves wait."),
    "private": ("Private", "No AI at all: nothing about your saves is sent to any AI service. Saves are still "
                           "downloaded, transcribed on this Mac, grouped into piles and searchable, without summaries."),
}


def current(store) -> str:
    chosen = store.get_setting(SETTING, "")
    if chosen in MODES:
        return chosen
    if chosen == "none" or store.get_setting("no_ai_for_now") == "1":
        return "private"  # the earlier "No AI for now" choice
    return "smart"  # the default before modes existed (and the earlier "balanced": keys first)


def summarisers(store, key_source) -> list:
    """Who can write the next summary, best first, in the current mode (empty: no summary now).
    A local model would be added here, later."""
    if current(store) == "private":
        return []
    from magpiary import keys as keyring

    if key_source is keyring:  # the real keys: the owner's one order, with Claude Code and Codex where they were dragged
        from magpiary import engines

        return engines.summarisers(store)
    return list(key_source.usable())


def waiting_reason(store, key_source) -> str:
    """Why summaries are not being made right now, in plain words ("" when they are)."""
    if current(store) == "private":
        return "Private mode: no AI summaries."
    if summarisers(store, key_source):
        return ""
    if hasattr(key_source, "load") and not key_source.load():
        return "Add an AI key in Settings for summaries."
    return "Every AI key has reached its limit; summaries continue when one is back."
