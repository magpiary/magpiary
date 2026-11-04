"""Pairing the Chrome extension: a one-time code from Settings is traded for a save key, and the key saves like a phone's."""

import json
from datetime import datetime
from urllib.parse import unquote

from test_setup import Env, A, env  # noqa: F401  (env is the fixture)
from magpiary.setup import BROWSER_CODE_TRIES, TOKEN_TTL_SECONDS


def add_browser(env, name=""):
    status, headers, _ = env.post("/hub/browsers/add", name=name, next="/settings/phones")
    assert status == 303
    where = headers["Location"]
    return where, unquote(where.split("chromecode=")[1].split("&")[0]) if "chromecode=" in where else ""


def redeem(env, code):
    return _post(env, "/v1/pair", json.dumps({"code": code}))


def _post(env, path, body, key=None):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", env.mac.port, timeout=10)
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    conn.request("POST", path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def test_code_is_traded_for_a_key_that_saves_like_a_phone(env):
    where, code = add_browser(env)
    assert len(code) == 14 and code.count("-") == 2
    status, data = redeem(env, code)
    assert status == 200
    key = json.loads(data)["key"]
    assert key not in where                      # a key is never shown on a page
    status, data = _post(env, "/v1/items", json.dumps({"items": [{"id": "b1", "url": A + "?igsh=abc", "shared_at": "2026-10-30T10:00:00Z"}]}), key)
    assert status == 200 and env.mac.counts() == {A: 1}   # cleaned on the Mac, like a phone share
    kinds = {p["name"]: p["kind"] for p in env.mac.store.list_phones()}
    assert kinds == {"Chrome": "browser"}


def test_code_works_once_and_typed_loosely(env):
    _, code = add_browser(env)
    assert redeem(env, code.lower().replace("-", " "))[0] == 200
    assert redeem(env, code)[0] == 403


def test_wrong_code_is_refused_and_tries_run_out(env):
    _, code = add_browser(env)
    for _ in range(BROWSER_CODE_TRIES):
        assert redeem(env, "AAAA-BBBB-CCCC")[0] == 403
    assert redeem(env, code)[0] == 403           # too many misses: even the right code waits


def test_code_expires(env):
    _, code = add_browser(env)
    env.clock.advance(TOKEN_TTL_SECONDS + 1)
    assert redeem(env, code)[0] == 403


def test_removed_browser_can_no_longer_save(env):
    _, code = add_browser(env)
    key = json.loads(redeem(env, code)[1])["key"]
    env.post("/hub/phones/remove", name="Chrome")
    assert _post(env, "/v1/items", json.dumps({"items": []}), key)[0] == 401


def test_settings_shows_chrome_apart_from_phones_and_pairs_only_one(env):
    page = env.request("GET", "/settings/phones")[2].decode()
    assert ">Pair Chrome</button>" in page and 'id="chrome"' in page          # its own group, with a button while unpaired
    assert page.index('id="phones"') < page.index('id="chrome"')
    where, code = add_browser(env)
    waiting = env.request("GET", where)[2].decode()
    assert code in waiting and "Waiting for the extension" in waiting
    assert env.mac.store.list_phones() == []                         # a code alone pairs nothing
    key = json.loads(redeem(env, code)[1])["key"]
    paired = env.request("GET", "/settings/phones")[2].decode()
    assert "Paired" in paired and ">Pair Chrome</button>" not in paired        # one Chrome: no button once paired
    assert "Chrome on this Mac" not in paired and "saves on this Mac only" not in paired
    # a new code re-pairs the same Chrome: its key is replaced, still one row, the old key stops working
    _, again = add_browser(env)
    new_key = json.loads(redeem(env, again)[1])["key"]
    assert new_key != key and len([p for p in env.mac.store.list_phones() if not p["revoked_at"]]) == 1
    assert _post(env, "/v1/items", json.dumps({"items": []}), key)[0] == 401


def test_phones_group_has_no_chrome_row(env):
    _, code = add_browser(env)
    redeem(env, code)
    page = env.request("GET", "/settings/phones")[2].decode()
    phones_block = page[page.index('id="phones"'):page.index('id="chrome"')]
    assert "Chrome" not in phones_block and "No phone yet" in phones_block
    assert "● No phone yet" in page                                   # the sidebar card does not count Chrome as a phone


def test_bad_pair_requests(env):
    assert _post(env, "/v1/pair", "not json")[0] == 400
    assert _post(env, "/v1/pair", json.dumps({"nope": 1}))[0] == 400


def test_extension_command_copies_the_extension_to_one_stable_folder(tmp_path, monkeypatch, capsys):
    from magpiary import cli, config

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    assert cli.main(["extension", "--no-open"]) == 0
    folder = tmp_path / "chrome-extension"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3 and (folder / "icons" / "128.png").exists()
    assert "Load unpacked" in capsys.readouterr().out
    assert cli.main(["extension", "--no-open"]) == 0   # again after an update: replaced, not duplicated


def test_a_share_time_without_an_offset_is_read_as_local_and_the_post_page_opens(env):
    _, code = add_browser(env)
    key = json.loads(redeem(env, code)[1])["key"]
    body = json.dumps({"items": [{"id": "n1", "url": A, "shared_at": "2026-10-31T00:42:51"}]})   # no offset: a client that forgot it
    assert _post(env, "/v1/items", body, key)[0] == 200
    item = env.mac.store.items()[0]
    assert item["first_shared_at"].startswith("2026-10-31T00:42:51") and item["first_shared_at"][19:] != ""   # now carries an offset
    assert datetime.fromisoformat(item["created_at"]) - datetime.fromisoformat(item["first_shared_at"]) is not None  # same kind: no TypeError
    status, _, _ = env.request("GET", f"/item/{item['id']}")
    assert status == 200
