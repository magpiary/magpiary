"""OpenRouter, OpenAI and Claude with recorded answers: no keys, no network, no cost."""

import json
import types

import pytest

from magpiary import keys as keyring
from magpiary import providers
from magpiary.brain import BrainFailed, summarise

GOOD = {"title": "Pasta in 10 minutes", "summary": "A quick carbonara.", "type": "recipe",
        "key_points": [{"text": "Use guanciale", "at": "0:05"}], "entities": {"tools": []},
        "suggested_tags": ["Pasta", "recipes"]}
PARTS = [{"text": "POST DETAILS: {}"}, {"text": "FRAME at 0:01"},
         {"inline_data": {"mime_type": "image/jpeg", "data": "AAAA"}}]


class FakeRequest:
    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def __call__(self, method, url, headers, body, timeout):
        self.sent.append((method, url, headers, body))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def chat(content, **extra):
    return 200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], **extra}


def test_json_schema_is_standard_and_closed():
    schema = providers.json_schema()
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["properties"]["key_points"]["items"]["additionalProperties"] is False
    assert schema["properties"]["type"]["enum"][0] == "howto" and "required" in schema


def test_openrouter_sends_frames_and_a_schema_and_the_record_is_checked():
    fake = FakeRequest(chat("```json\n" + json.dumps(GOOD) + "\n```"))
    ask = lambda parts, history: providers.ask_chat("openrouter", parts, history, "sk-or-x",  # noqa: E731
                                                    "nvidia/nemotron-3.5-super-vl:free", fake)
    record = summarise(PARTS, "sk-or-x", "m", provider="openrouter", ask=ask)
    assert record["title"] == "Pasta in 10 minutes" and record["suggested_tags"] == ["pasta", "recipes"]
    method, url, headers, body = fake.sent[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions" and headers["Authorization"] == "Bearer sk-or-x"
    assert body["model"] == "nvidia/nemotron-3.5-super-vl:free" and body["response_format"]["type"] == "json_schema"
    user = body["messages"][1]["content"]
    assert user[2] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}


def test_a_model_without_schema_support_gets_plain_json_and_a_bad_answer_is_asked_again():
    fake = FakeRequest((400, {"error": {"message": "response_format json_schema is not supported"}}),
                       chat("not json"), chat(json.dumps(GOOD)))
    ask = lambda parts, history: providers.ask_chat("openrouter", parts, history, "k", "google/gemma-4-31b-it:free", fake)  # noqa: E731
    assert summarise(PARTS, "k", "m", provider="openrouter", ask=ask)["type"] == "recipe"
    assert fake.sent[1][3]["response_format"] == {"type": "json_object"}
    assert "not usable" in fake.sent[2][3]["messages"][-1]["content"]


@pytest.mark.parametrize("reply, reason", [
    ((401, {"error": {"message": "No auth credentials found"}}), "bad_key"),
    ((402, {"error": {"message": "Insufficient credits"}}), "rate_limited"),
    ((429, {"error": {"message": "free-models-per-day"}}), "rate_limited"),
    ((502, {}), "busy"),
    ((404, {"error": {"message": "0 endpoints out of 1 requested are available matching your guardrail restrictions "
                                 "and data policy"}}), "blocked"),
    ((200, {"error": {"code": 429, "message": "Rate limit exceeded upstream"}}), "rate_limited"),
    (TimeoutError(), "busy"),
])
def test_openrouter_errors_map_to_the_shared_reasons(reply, reason):
    with pytest.raises(BrainFailed) as err:
        providers.ask_chat("openrouter", PARTS, [], "k", "m", FakeRequest(reply))
    assert err.value.reason == reason


def test_keys_are_checked_for_free_and_get_the_right_default_model():
    fake = FakeRequest((200, {"data": {"label": "sk-or-v1-abc...", "is_free_tier": True}}))
    assert providers.check_chat("openrouter", "sk-or-x", fake) == "nvidia/nemotron-3.5-super-vl:free"
    assert fake.sent[0][:2] == ("GET", "https://openrouter.ai/api/v1/key")
    models = {"data": [{"id": "gpt-5.4"}, {"id": "gpt-5-mini"}, {"id": "gpt-5.4-mini"}, {"id": "gpt-5.4-nano"}]}
    assert providers.check_chat("openai", "sk-x", FakeRequest((200, models))) == "gpt-5.4-mini"
    with pytest.raises(BrainFailed) as err:
        providers.check_chat("openrouter", "bad", FakeRequest((401, {})))
    assert err.value.reason == "bad_key"


def test_an_openrouter_key_is_saved_with_the_owners_model(tmp_path):
    ok = FakeRequest((200, {"data": {}}), (200, {"data": {}}))
    assert keyring.add("openrouter", "free", "sk-or-1", "", request=ok) is None
    assert keyring.add("openrouter", "paid", "sk-or-2", "", request=ok, model="qwen/qwen3.8-flash") is None
    saved = keyring.load()
    assert [(k.provider, k.model) for k in saved] == [("openrouter", "nvidia/nemotron-3.5-super-vl:free"),
                                                      ("openrouter", "qwen/qwen3.8-flash")]
    assert keyring.change_model(saved[0].id, "google/gemma-4-31b-it:free") and not keyring.change_model(saved[0].id, "bad name!")
    assert keyring.load()[0].model == "google/gemma-4-31b-it:free"
    assert keyring.repick(keyring.load()[0]) is False  # only Gemini models are probed
    assert "refused" in keyring.add("openrouter", "free", "sk-or-3", "", request=FakeRequest((401, {})))


class FakeClaude:
    def __init__(self, text="", stop="end_turn", error=None):
        self.calls, self.text, self.stop, self.error = [], text, stop, error
        self.messages = types.SimpleNamespace(create=self.create)
        self.models = types.SimpleNamespace(list=lambda limit: [])

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return types.SimpleNamespace(stop_reason=self.stop,
                                     content=[types.SimpleNamespace(type="text", text=self.text)])


def test_claude_gets_images_a_schema_and_low_effort():
    fake = FakeClaude(json.dumps(GOOD))
    ask = lambda parts, history: providers.ask_claude(parts, history, "sk-ant-x", "claude-haiku-5-5", fake)  # noqa: E731
    assert summarise(PARTS, "sk-ant-x", "m", provider="claude", ask=ask)["title"] == "Pasta in 10 minutes"
    sent = fake.calls[0]
    assert sent["model"] == "claude-haiku-5-5" and sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema" and "temperature" not in sent
    assert sent["messages"][0]["content"][2] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                             "data": "AAAA"}}
    assert providers.check_claude("sk-ant-x", FakeClaude()) == "claude-haiku-5-5"


def test_claude_refusals_and_errors_map_to_the_shared_reasons():
    import anthropic
    import httpx2

    with pytest.raises(BrainFailed) as err:
        providers.ask_claude(PARTS, [], "k", "m", FakeClaude(stop="refusal"))
    assert err.value.reason == "blocked"
    response = httpx2.Response(529, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    overloaded = anthropic.InternalServerError("Overloaded", response=response, body=None)
    with pytest.raises(BrainFailed) as err:
        providers.ask_claude(PARTS, [], "k", "m", FakeClaude(error=overloaded))
    assert err.value.reason == "busy"
