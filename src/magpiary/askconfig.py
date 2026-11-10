"""Settings for Ask Magpiary: on or off, who answers, which model and how hard it thinks, the web, the token display and the
spend guard. All kept in the store's settings; this module only knows the names, the choices and the defaults."""

from datetime import datetime, timedelta

ENGINE = "ask_engine"            # "claude" (Claude Code on the owner's plan), "codex" (Codex on the ChatGPT plan) or "key" (an AI key)
KEY = "ask_key"                  # which saved key answers, when the engine is "key"
CLAUDE_MODEL = "ask_claude_model"
CLAUDE_EFFORT = "ask_claude_effort"
CODEX_MODEL = "ask_codex_model"
CODEX_EFFORT = "ask_codex_effort"
WEB = "ask_web"
SHOW_TOKENS = "ask_show_tokens"
LIMIT = "ask_limit"              # a preset name from LIMITS
WARN = "ask_warn"                # "1": warn when the limit is passed; "0": never warn
LIMIT_PERIOD = "ask_limit_period"  # "day" or "month"
DEPTH = "ask_depth"              # how long and how thorough answers are: a key of DEPTHS

# Claude Code's own names for models, newest of each size; the first is the default (cheap).
CLAUDE_MODELS = {"haiku": "Haiku 5.5 (fast, cheapest)", "sonnet": "Sonnet 5.5 (balanced)", "opus": "Opus 5.5 (strongest, most tokens)"}
EFFORTS = {"low": "Low", "medium": "Medium", "high": "High"}
DEFAULT_MODEL, DEFAULT_EFFORT = "haiku", "medium"
MODEL_NAME = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5"}


# The regular per-post summary on Claude Code (owner, 10 Nov 2026): its own model and effort, apart from Ask's. A model the
# plan or CLI cannot run falls back to SUMMARY_FALLBACK (the old fixed choice) and the post says so.
SUMMARY_MODEL = "summary_claude_model"
SUMMARY_EFFORT = "summary_claude_effort"
SUMMARY_MODELS = {"sonnet": "Sonnet 5.5: balanced, the default",
                  "haiku": "Haiku 5.5: fastest, lightest on your plan",
                  "opus": "Opus 5.5: strongest, uses the most of your plan"}
SUMMARY_EFFORTS = {"low": "Low: quickest, lightest", "medium": "Medium: thinks a little longer", "high": "High: thinks longest, uses the most"}
SUMMARY_DEFAULT = ("sonnet", "low")
SUMMARY_FALLBACK = ("haiku", "low")


def summary_model(store) -> str:
    value = store.get_setting(SUMMARY_MODEL, SUMMARY_DEFAULT[0])
    return value if value in SUMMARY_MODELS else SUMMARY_DEFAULT[0]


def summary_effort(store) -> str:
    value = store.get_setting(SUMMARY_EFFORT, SUMMARY_DEFAULT[1])
    return value if value in SUMMARY_EFFORTS else SUMMARY_DEFAULT[1]


# How much an answer does (owner, 29 Oct: the first rules were all about saving tokens and made answers too short).
# Short is the old behaviour; Normal is the default; Deep goes through the web and the library properly.
DEPTHS = {"short": "Short", "normal": "Normal", "deep": "Deep"}
DEFAULT_DEPTH = "normal"
DEPTH_TURNS = {"short": 8, "normal": 14, "deep": 24}       # steps the AI may take
DEPTH_SECONDS = {"short": 300, "normal": 420, "deep": 600}  # how long before it is stopped


def depth(store) -> str:
    value = store.get_setting(DEPTH, DEFAULT_DEPTH)
    return value if value in DEPTHS else DEFAULT_DEPTH


def enabled(store) -> bool:
    """On by itself once Claude Code or Codex is allowed or a paid key is saved; with only free keys, only when the owner
    turned it on (engines.py). The old ask_on switch no longer counts: everyone starts again (owner, 4 Nov 2026)."""
    from magpiary import engines

    return engines.is_on(store, "ask")


def claude_model(store) -> str:
    value = store.get_setting(CLAUDE_MODEL, DEFAULT_MODEL)
    return value if value in CLAUDE_MODELS else DEFAULT_MODEL


def claude_effort(store) -> str:
    value = store.get_setting(CLAUDE_EFFORT, DEFAULT_EFFORT)
    return value if value in EFFORTS else DEFAULT_EFFORT


# Codex's models (names as `codex` knows them) and efforts: never above medium, so a question stays light on the plan.
CODEX_MODELS = {"gpt-6-luna": "GPT-6 Luna (fast, cheapest)", "gpt-6-sol": "GPT-6 Sol (stronger)"}
CODEX_NAME = {"gpt-6-luna": "GPT-6 Luna", "gpt-6-sol": "GPT-6 Sol"}
CODEX_EFFORTS = {"low": "Low", "medium": "Medium"}


def codex_model(store) -> str:
    value = store.get_setting(CODEX_MODEL, "gpt-6-luna")
    return value if value in CODEX_MODELS else "gpt-6-luna"


def codex_effort(store) -> str:
    value = store.get_setting(CODEX_EFFORT, "medium")
    return value if value in CODEX_EFFORTS else "medium"


def removed(store, engine: str) -> bool:
    """Taken out of Ask by the owner (Settings → Remove): not offered or used until set up again."""
    return store.get_setting(f"ask_removed_{engine}", "0") == "1"


def set_removed(store, engine: str, value: bool) -> None:
    store.set_setting(f"ask_removed_{engine}", "1" if value else "0")


def web_allowed(store) -> bool:
    return store.get_setting(WEB, "1") == "1"


def show_tokens(store) -> bool:
    return store.get_setting(SHOW_TOKENS, "1") == "1"


# The spend guard is a preset, not a number: about how many questions a day. A question averages about 14k tokens (measured on
# the owner's library with Haiku 5.5: 3k about a post, 17k across the library, 39k with a web search; a day of 50 messages
# was about 720k).
TOKENS_PER_QUESTION = 15_000
LIMITS = {"none": ("No limit", 0), "low": ("Low", 10), "medium": ("Medium", 25), "high": ("High", 50), "xhigh": ("Extra high", 100)}


def limit_preset(store) -> str:
    value = store.get_setting(LIMIT, "none")
    return value if value in LIMITS else "none"


def warn_on(store) -> bool:
    return store.get_setting(WARN, "1") == "1"


def limit_period(store) -> str:
    return "month" if store.get_setting(LIMIT_PERIOD, "day") == "month" else "day"


def limit(store) -> int:
    """The soft limit in tokens for the chosen period; 0 for no limit."""
    questions = LIMITS[limit_preset(store)][1]
    return questions * TOKENS_PER_QUESTION * (30 if limit_period(store) == "month" else 1)


def limit_words(store) -> str:
    """"about 25 questions a day"."""
    questions = LIMITS[limit_preset(store)][1]
    return f"about {questions} questions a {limit_period(store)}" if questions and limit_period(store) == "day" else \
        f"about {questions * 30} questions a month" if questions else "no limit"


def compact(n: int) -> str:
    """12345 -> "12.3k"."""
    return str(n) if n < 1000 else f"{n / 1000:.1f}k" if n < 100_000 else f"{n / 1000:.0f}k" if n < 1_000_000 else f"{n / 1e6:.1f}M"


def usage_line(usage: dict) -> str:
    """The small line under an answer: "2.1k in · 340 out · Haiku 5.5"."""
    if not usage:
        return ""
    bits = [f'{compact(int(usage.get("in", 0)))} in', f'{compact(int(usage.get("out", 0)))} out']
    if usage.get("model"):
        bits.append(str(usage["model"]))
    if usage.get("cost"):
        bits.append(f'about ${usage["cost"]:.3f}')
    return " · ".join(bits)


def periods(now: datetime | None = None) -> dict[str, str]:
    """Where "today", "this week" and "this month" start, as ISO stamps."""
    now = now or datetime.now().astimezone()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"day": day.isoformat(timespec="seconds"), "week": (day - timedelta(days=day.weekday())).isoformat(timespec="seconds"),
            "month": day.replace(day=1).isoformat(timespec="seconds")}
