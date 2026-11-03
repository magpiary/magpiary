"""The AI services besides Gemini: OpenRouter and OpenAI (the same chat format) and Claude (Anthropic's library).

Each `ask_*` sends the evidence (brain.build_evidence's parts: text and inline images) plus any earlier turns,
and returns the answer's text, which brain.summarise checks. Each `check_*` validates a key without using any
of its quota and returns the model to use. Errors become BrainFailed with the same reasons as Gemini's, so the
worker's key fallback works the same for every service. Keys are never logged or printed.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable

from magpiary.brain import PROMPT, SCHEMA, BrainFailed
from magpiary.network import public_urlopen

# (method, url, headers, json body or None, timeout) -> (status, parsed json). Raises OSError.
Request = Callable[[str, str, dict, dict | None, float], tuple[int, dict]]

OPENROUTER = "https://openrouter.ai/api/v1"
OPENAI = "https://api.openai.com/v1"
DEFAULT_MODELS = {"openrouter": "nvidia/nemotron-3.5-super-vl:free", "claude": "claude-haiku-5-5"}
SUGGESTED_MODELS = {  # shown in Settings; any model name the service offers can be typed instead
    "openrouter": ["nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it:free", "qwen/qwen3.8-flash",
                   "z-ai/glm-5.3-flash"],
    "claude": ["claude-haiku-5-5", "claude-sonnet-5-5"],
    "openai": [],
}
NAMES = {"openrouter": "OpenRouter", "openai": "OpenAI", "claude": "Claude"}


def http_request(method: str, url: str, headers: dict, body: dict | None, timeout: float = 180) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with public_urlopen(request, timeout=timeout, redirects=False) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except ValueError:
            return err.code, {}


def json_schema(schema: dict = SCHEMA) -> dict:
    """Gemini's schema written as standard JSON Schema: lower-case types, no extra fields allowed."""
    out = {k: v for k, v in schema.items() if k not in ("type", "properties", "items")}
    out["type"] = schema["type"].lower()
    if "properties" in schema:
        out["properties"] = {k: json_schema(v) for k, v in schema["properties"].items()}
        out["additionalProperties"] = False
    if "items" in schema:
        out["items"] = json_schema(schema["items"])
    return out


def strict_schema(schema: dict) -> dict:
    """A standard JSON Schema in OpenAI's strict form, which Codex's --output-schema demands: every field listed as
    required, and the ones that were optional allowed to be null instead."""
    out = dict(schema)
    if "properties" in schema:
        needed = set(schema.get("required", []))
        props = {}
        for name, sub in schema["properties"].items():
            sub = strict_schema(sub)
            if name not in needed:
                sub = dict(sub, type=[sub["type"], "null"]) if isinstance(sub.get("type"), str) else sub
                if "enum" in sub:
                    sub["enum"] = [*sub["enum"], None]
            props[name] = sub
        out.update(properties=props, required=list(schema["properties"]), additionalProperties=False)
    if "items" in schema:
        out["items"] = strict_schema(schema["items"])
    return out


def drop_nulls(text: str) -> str:
    """A strict-schema answer with the empty optional fields left out again, as the readers expect."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if x is not None}
        return [clean(x) for x in v] if isinstance(v, list) else v
    try:
        return json.dumps(clean(json.loads(text)))
    except ValueError:
        return text


def _images(parts: list[dict]):
    """(kind, value) in order: ("text", str) or ("image", (mime type, base64 data))."""
    for p in parts:
        if "text" in p:
            yield "text", p["text"]
        elif "inline_data" in p:
            yield "image", (p["inline_data"]["mime_type"], p["inline_data"]["data"])


def _failure(service: str, status: int, answer: dict) -> BrainFailed:
    error = answer.get("error") if isinstance(answer.get("error"), dict) else {}
    message = str(error.get("message") or answer.get("message") or "")[:160]
    if status in (401, 403):
        return BrainFailed("bad_key", f"{service} refused the key (HTTP {status})")
    if status == 404 and re.search(r"guardrail|data policy", message, re.I):
        # found 24 Oct: with "no providers that may train" on, a free model can have no provider left
        return BrainFailed("blocked", f"{service}'s privacy settings leave no provider for this model. Allow it in "
                           "OpenRouter's Settings → Privacy, or pick another model for this key in Settings")
    if status in (402, 429):  # 402: OpenRouter credits used up; 429: a rate or daily limit
        return BrainFailed("rate_limited", f"{service}: limit reached (HTTP {status}); trying again later")
    if status >= 500:
        return BrainFailed("busy", f"{service} is busy right now (HTTP {status})")
    return BrainFailed("unknown", f"{service} request failed (HTTP {status})")


# ---- OpenRouter and OpenAI (the same chat format) ---------------------------------------------

def _chat_base(provider: str) -> str:
    return OPENROUTER if provider == "openrouter" else OPENAI


def _chat_headers(provider: str, secret: str) -> dict:
    headers = {"Authorization": f"Bearer {secret}"}
    if provider == "openrouter":
        headers["X-Title"] = "Magpiary"  # shows on the owner's OpenRouter activity page
    return headers


def ask_chat(provider: str, parts: list[dict], history: list[tuple[str, str]], secret: str, model: str,
             request: Request = http_request, system: str = PROMPT, schema: dict = SCHEMA) -> str:
    """One request to OpenRouter or OpenAI. `history` is earlier (role, text) turns after the evidence. `system` and
    `schema` default to the summary's; a deeper dive passes its own."""
    service = NAMES[provider]
    content = [{"type": "text", "text": v} if kind == "text" else
               {"type": "image_url", "image_url": {"url": f"data:{v[0]};base64,{v[1]}"}}
               for kind, v in _images(parts)]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content},
                *({"role": "assistant" if r == "model" else "user", "content": t} for r, t in history)]
    formats = [{"type": "json_schema", "json_schema": {"name": "record", "strict": False, "schema": json_schema(schema)}},
               {"type": "json_object"}]  # a model without schema support may still promise JSON
    for n, response_format in enumerate(formats):
        body = {"model": model, "messages": messages, "response_format": response_format}
        try:
            status, answer = request("POST", f"{_chat_base(provider)}/chat/completions",
                                     _chat_headers(provider, secret), body, 300)
        except TimeoutError as err:
            raise BrainFailed("busy", f"{service} did not answer within 5 minutes") from err
        except OSError as err:
            raise BrainFailed("unknown", f"network error: {type(err).__name__}") from err
        if status == 400 and n == 0 and re.search(r"response_format|json_schema|structured", json.dumps(answer), re.I):
            continue  # this model cannot follow a schema: ask for plain JSON instead
        if status != 200 or answer.get("error"):
            code = (answer.get("error") or {}).get("code") if isinstance(answer.get("error"), dict) else None
            raise _failure(service, status if status != 200 else (code if isinstance(code, int) else 500), answer)
        choice = (answer.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise BrainFailed("blocked", f"{service} declined to answer")
        text = (choice.get("message") or {}).get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        return _strip_fences(text)
    raise BrainFailed("unknown", f"{service} could not return JSON with {model}")


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in ``` fences even when asked not to."""
    m = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.S)
    return m.group(1) if m else text


def check_chat(provider: str, secret: str, request: Request = http_request) -> str:
    """Validate a key without spending anything; returns the default model. Raises BrainFailed."""
    service = NAMES[provider]
    url = f"{OPENROUTER}/key" if provider == "openrouter" else f"{OPENAI}/models"
    try:
        status, answer = request("GET", url, _chat_headers(provider, secret), None, 20)
    except OSError as err:
        raise BrainFailed("unknown", f"could not reach {service}: {type(err).__name__}") from err
    if status != 200:
        raise _failure(service, status, answer)
    if provider == "openrouter":
        return DEFAULT_MODELS["openrouter"]
    ids = [m.get("id", "") for m in answer.get("data", [])]
    minis = sorted((i for i in ids if re.fullmatch(r"gpt-(\d+(?:\.\d+)?)-mini", i)),
                   key=lambda i: float(re.findall(r"\d+(?:\.\d+)?", i)[0]), reverse=True)
    if not minis:
        raise BrainFailed("unknown", "no suitable OpenAI model is available to this key")
    return minis[0]  # the fast, cheap class (owner's choice)


# ---- Claude (Anthropic's library) -------------------------------------------------------------

def _claude_client(secret: str):
    import anthropic

    return anthropic.Anthropic(api_key=secret, max_retries=2, timeout=300)


def _claude_failure(err: Exception) -> BrainFailed:
    import anthropic

    if isinstance(err, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return BrainFailed("bad_key", "Claude refused the key")
    if isinstance(err, anthropic.RateLimitError):
        return BrainFailed("rate_limited", "Claude's rate limit was reached; trying again later")
    if isinstance(err, anthropic.APITimeoutError):
        return BrainFailed("busy", "Claude did not answer in time")
    if isinstance(err, anthropic.APIStatusError):
        if err.status_code >= 500:  # 529: overloaded
            return BrainFailed("busy", f"Claude is busy right now (HTTP {err.status_code})")
        return BrainFailed("unknown", f"Claude request failed (HTTP {err.status_code})")
    if isinstance(err, anthropic.APIConnectionError):
        return BrainFailed("unknown", "network error reaching Claude")
    return BrainFailed("unknown", f"Claude: {type(err).__name__}")


def ask_claude(parts: list[dict], history: list[tuple[str, str]], secret: str, model: str, client=None,
               system: str = PROMPT, schema: dict = SCHEMA, effort: str = "low") -> str:
    content = [{"type": "text", "text": v} if kind == "text" else
               {"type": "image", "source": {"type": "base64", "media_type": v[0], "data": v[1]}}
               for kind, v in _images(parts)]
    messages = [{"role": "user", "content": content},
                *({"role": "assistant" if r == "model" else "user", "content": t} for r, t in history)]
    try:
        response = (client or _claude_client(secret)).messages.create(
            model=model, max_tokens=16000, system=system, messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": json_schema(schema)}})
    except Exception as err:  # the library's errors, mapped to the shared reasons
        raise _claude_failure(err) from err
    if response.stop_reason == "refusal":
        raise BrainFailed("blocked", "Claude declined to answer")
    return "".join(b.text for b in response.content if b.type == "text")


def check_claude(secret: str, client=None) -> str:
    """Listing models costs nothing and proves the key works. Returns the default model."""
    try:
        (client or _claude_client(secret)).models.list(limit=1)
    except Exception as err:
        raise _claude_failure(err) from err
    return DEFAULT_MODELS["claude"]


# ---- a few plain sentences (the digest's intro, M7c) ------------------------------------------

def write_text(key, prompt: str, request: Request = http_request, call=None, client=None, max_tokens: int = 400) -> str:
    """A short plain-text answer from the owner's key, any provider. Raises BrainFailed."""
    if key.provider == "gemini":
        from magpiary.brain import API, http_call

        status, answer = (call or http_call)("POST", f"{API}/models/{key.model}:generateContent", key.secret,
                                             {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                              "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens}})
        if status != 200:
            raise _failure("Gemini", status, answer)
        candidate = (answer.get("candidates") or [{}])[0]
        return "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", [])).strip()
    if key.provider == "claude":
        try:
            response = (client or _claude_client(key.secret)).messages.create(
                model=key.model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        except Exception as err:
            raise _claude_failure(err) from err
        return "".join(b.text for b in response.content if b.type == "text").strip()
    try:
        status, answer = request("POST", f"{_chat_base(key.provider)}/chat/completions",
                                 _chat_headers(key.provider, key.secret),
                                 {"model": key.model, "messages": [{"role": "user", "content": prompt}]}, 120)
    except OSError as err:
        raise BrainFailed("unknown", f"network error: {type(err).__name__}") from err
    if status != 200 or answer.get("error"):
        raise _failure(NAMES[key.provider], status if status != 200 else 500, answer)
    text = ((answer.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return (text if isinstance(text, str) else "").strip()
