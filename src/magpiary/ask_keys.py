"""Ask Magpiary on one of the owner's AI keys (Gemini, OpenAI, Claude API or OpenRouter), the open way: the question is answered
like any AI app would, the posts in front of the person are background, and each provider's own web search is switched on when
the web is allowed. No tools of ours run here: the saves it may use are the best matches, sent as text, like a post's own text.

One request, one answer (no word-by-word): the page shows "Searching the web: ..." for each search the provider ran, then the
answer. Web search is billed by the provider on a paid key; the Settings page says so."""

from collections.abc import Callable

from magpiary import ask as asking
from magpiary import ask_open, providers
from magpiary.brain import API, BrainFailed, http_call

SEARCHES = 3  # at most this many web searches per question, where the provider lets us say


def _sources(links: list[tuple[str, str]]) -> str:
    """A short "Sources" line of markdown links, each once, at most four."""
    out, seen = [], set()
    for url, title in links:
        if url and url not in seen and url.startswith("http"):
            seen.add(url)
            out.append(f"[{(title or url.split('/')[2])[:60].replace(']', ')')}]({url})")
    return ("\n\nSources: " + " · ".join(out[:4])) if out else ""


def _history(history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [("user" if role == "user" else "assistant", text[:1500]) for role, text in history[-asking.HISTORY:]]


def gemini(key, prompt: str, history, web: bool, on_event, system: str | None = None) -> tuple[str, dict]:
    contents = [{"role": "user" if r == "user" else "model", "parts": [{"text": t}]} for r, t in _history(history)]
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {"system_instruction": {"parts": [{"text": system or ask_open.SYSTEM}]}, "contents": contents, "generationConfig": {"temperature": 0.4}}
    if web:
        body["tools"] = [{"google_search": {}}]
    try:
        status, answer = http_call("POST", f"{API}/models/{key.model}:generateContent", key.secret, body, 300)
    except TimeoutError as err:
        raise BrainFailed("busy", "Gemini did not answer within 5 minutes") from err
    except OSError as err:
        raise BrainFailed("unknown", f"network error: {type(err).__name__}") from err
    from magpiary.brain import _check_status

    _check_status(status, answer)
    cand = (answer.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])).strip()
    meta = cand.get("groundingMetadata") or {}
    for q in (meta.get("webSearchQueries") or [])[:SEARCHES]:
        on_event(_search(q))
    links = [((c.get("web") or {}).get("uri", ""), (c.get("web") or {}).get("title", "")) for c in meta.get("groundingChunks") or []]
    u = answer.get("usageMetadata") or {}
    return text + _sources(links), {"in": int(u.get("promptTokenCount", 0)), "out": int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))}


def _search(query: str) -> dict:
    return {"step": f"Searching the web: {query[:90]}", "kind": "search", "arg": query[:90]}


def openai(key, prompt: str, history, web: bool, on_event, system: str | None = None) -> tuple[str, dict]:
    body = {"model": key.model, "instructions": system or ask_open.SYSTEM,
            "input": [*({"role": r, "content": t} for r, t in _history(history)), {"role": "user", "content": prompt}]}
    if web:
        body["tools"] = [{"type": "web_search"}]
    status, answer = _post(providers.OPENAI + "/responses", providers._chat_headers("openai", key.secret), body, "OpenAI")
    text, links = "", []
    for item in answer.get("output") or []:
        if item.get("type") == "web_search_call":
            on_event(_search(str((item.get("action") or {}).get("query") or "")))
        for part in item.get("content") or [] if item.get("type") == "message" else []:
            text += part.get("text", "")
            links += [(a.get("url", ""), a.get("title", "")) for a in part.get("annotations") or [] if a.get("type") == "url_citation"]
    u = answer.get("usage") or {}
    return text.strip() + _sources(links) if links and "](http" not in text else text.strip(), \
        {"in": int(u.get("input_tokens", 0)), "out": int(u.get("output_tokens", 0))}


def openrouter(key, prompt: str, history, web: bool, on_event, system: str | None = None) -> tuple[str, dict]:
    body = {"model": key.model, "messages": [{"role": "system", "content": system or ask_open.SYSTEM},
                                              *({"role": r, "content": t} for r, t in _history(history)), {"role": "user", "content": prompt}]}
    if web:
        body["plugins"] = [{"id": "web", "max_results": SEARCHES}]
    status, answer = _post(providers.OPENROUTER + "/chat/completions", providers._chat_headers("openrouter", key.secret), body, "OpenRouter")
    msg = (answer.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    links = [((a.get("url_citation") or {}).get("url", ""), (a.get("url_citation") or {}).get("title", ""))
             for a in msg.get("annotations") or [] if a.get("type") == "url_citation"]
    if links:
        on_event({"step": "Searching the web", "kind": "search", "arg": ""})
    u = answer.get("usage") or {}
    return text.strip() + (_sources(links) if links and "](http" not in text else ""), \
        {"in": int(u.get("prompt_tokens", 0)), "out": int(u.get("completion_tokens", 0))}


def claude(key, prompt: str, history, web: bool, on_event, system: str | None = None) -> tuple[str, dict]:
    messages = [*({"role": r, "content": t} for r, t in _history(history)), {"role": "user", "content": prompt}]
    args = {"model": key.model or providers.DEFAULT_MODELS["claude"], "max_tokens": 4000, "system": system or ask_open.SYSTEM, "messages": messages}
    if web:
        args["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": SEARCHES}]
    try:
        response = providers._claude_client(key.secret).messages.create(**args)
    except Exception as err:  # the library's errors, mapped to the shared reasons
        raise providers._claude_failure(err) from err
    text, links = "", []
    for block in response.content:
        if block.type == "server_tool_use":
            on_event(_search(str((block.input or {}).get("query", ""))))
        elif block.type == "text":
            text += block.text
            links += [(getattr(c, "url", ""), getattr(c, "title", "")) for c in getattr(block, "citations", None) or []]
    return text.strip() + (_sources(links) if links and "](http" not in text else ""), \
        {"in": int(response.usage.input_tokens), "out": int(response.usage.output_tokens)}


def _post(url: str, headers: dict, body: dict, service: str) -> tuple[int, dict]:
    try:
        status, answer = providers.http_request("POST", url, headers, body, 300)
    except TimeoutError as err:
        raise BrainFailed("busy", f"{service} did not answer within 5 minutes") from err
    except OSError as err:
        raise BrainFailed("unknown", f"network error: {type(err).__name__}") from err
    if status != 200 or answer.get("error"):
        code = (answer.get("error") or {}).get("code") if isinstance(answer.get("error"), dict) else None
        raise providers._failure(service, status if status != 200 else (code if isinstance(code, int) else 500), answer)
    return status, answer


ASKERS: dict[str, Callable] = {"gemini": gemini, "openai": openai, "openrouter": openrouter, "claude": claude}


def run(key, question: str, items: list[dict], history: list[tuple[str, str]], scope: str, on_event: Callable[[dict], None],
        cancelled: Callable[[], bool] = lambda: False, web: bool = True, context: str = "", depth: str = "short", goals: str = "") -> str:
    """Ask a key's provider. Emits steps, then the answer and its usage; returns the answer text. Raises BrainFailed."""
    posts = ask_open.posts_for(items, question)
    prompt = ask_open.build_prompt(question, posts, [], scope, context, goals)  # earlier turns go as real turns, not pasted into the text
    text, used = ASKERS[key.provider](key, prompt, history, web, on_event, ask_open.system(depth))
    if cancelled():
        raise BrainFailed("unknown", "stopped")
    if not text:
        raise BrainFailed("blocked", "The AI gave no answer")
    on_event({"text": text})
    on_event({"usage": {**used, "cost": 0.0}})
    return text
