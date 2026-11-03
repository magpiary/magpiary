"""Remote errors and CLI diagnostics may echo arbitrary credentials or private text."""

import json
from types import SimpleNamespace

import pytest

from magpiary import ask, ask_codex, ask_open, boardsync, brain, claude_code, digest, providers

PRIVATE = "synthetic-context-" + "x" * 40


@pytest.mark.parametrize("status", [402, 418, 429])
def test_provider_errors_do_not_echo_remote_messages(status):
    failure = providers._failure("OpenRouter", status, {"error": {"message": PRIVATE}})
    assert PRIVATE not in str(failure)
    assert str(status) in str(failure)
    with pytest.raises(brain.BrainFailed) as err:
        brain._check_status(status, {"error": {"message": PRIVATE}})
    assert PRIVATE not in str(err.value)


def test_sdk_error_does_not_echo_the_remote_message():
    import anthropic
    import httpx2

    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.BadRequestError(PRIVATE, response=response, body=None)
    assert PRIVATE not in str(providers._claude_failure(error))


def test_streamed_cli_errors_do_not_echo_remote_messages():
    with pytest.raises(brain.BrainFailed) as err:
        ask_open.handle(json.dumps({"type": "result", "is_error": True, "result": PRIVATE}), {}, lambda e: None)
    assert PRIVATE not in str(err.value)
    with pytest.raises(brain.BrainFailed) as err:
        ask_codex.handle(json.dumps({"type": "turn.failed", "error": {"message": PRIVATE}}), lambda e: None, {})
    assert PRIVATE not in str(err.value)


def test_cli_writers_and_check_do_not_persist_raw_diagnostics(tmp_path):
    from magpiary.store import Store

    def failure(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout=json.dumps({"is_error": True, "result": PRIVATE}), stderr=PRIVATE)

    with pytest.raises(brain.BrainFailed) as err:
        ask.write_with_claude(None, "synthetic question", run=failure)
    assert PRIVATE not in str(err.value)
    with pytest.raises(ValueError) as err:
        digest.write_with_claude("synthetic question", run=failure)
    assert PRIVATE not in str(err.value)
    store = Store(tmp_path / "library.db")
    try:
        result = claude_code.tiny_test(store, run=failure)
        assert not result["ok"]
        assert PRIVATE not in json.dumps(result)
        assert PRIVATE not in store.get_setting(claude_code.TEST)
    finally:
        store.close()
    assert PRIVATE not in boardsync._why(RuntimeError(PRIVATE))
