"""Exercise real HTTP handlers with in-memory requests, without a listening socket."""

import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from magpiary import agent_policy
from magpiary.protocol import BOARDS_PATH
from magpiary.receiver import Handler
from magpiary.store import Store

YT = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
OTHER = "https://www.youtube.com/watch?v=bbbbbbbbbbb"


@pytest.fixture
def agent_store(tmp_path):
    store = Store(tmp_path / "library.db")
    store.set_setting("agents_on", "1")
    phone, key = store.add_phone("Synthetic agent", kind="agent")
    yield store, phone, key
    store.close()


def request(store, key, path, body=None, client="127.0.0.1"):
    h = Handler.__new__(Handler)
    h.server = SimpleNamespace(store=store, fail_next_posts=0, work_wanted=threading.Event(),
                               boards_wanted=threading.Event(), setup=None)
    h.path, h.client_address = path, (client, 12345)
    payload = json.dumps(body).encode()
    h.headers = {"Content-Length": str(len(payload))}
    h.rfile = io.BytesIO(payload)
    h._bearer = lambda: key
    answer = []
    h.send_json = lambda code, value: answer.append((code, value))
    (h.do_GET if body is None else h.do_POST)()
    return answer[0]


@pytest.mark.parametrize("path,body", [(BOARDS_PATH, None), ("/v1/seen", {"urls": [YT]}),
                                        ("/v1/suggest", {"url": YT})])
def test_agent_keys_cannot_use_phone_or_browser_read_routes(agent_store, path, body):
    store, _, key = agent_store
    store.set_setting("agents_on", "0")
    assert request(store, key, path, body)[0] == 403


def test_agent_save_reply_contains_no_owner_board_or_repeat_metadata(agent_store):
    store, phone, key = agent_store
    store.save_board("a" * 16, "Private board", "owner", "", shared=False)
    store.receive(phone, [{"id": "seed", "url": YT}])
    status, reply = request(store, key, "/v1/items", {"items": [{"id": "again", "url": YT}]})
    assert status == 200
    assert "boards" not in reply and "wifi" not in reply
    assert "saved_count" not in reply["results"][0]
    assert "Private board" not in json.dumps(reply)


@pytest.mark.parametrize("kind", ["add", "note"])
def test_parallel_requests_cannot_exceed_agent_daily_limit(agent_store, monkeypatch, kind):
    store, phone, key = agent_store
    store.set_setting(f"agents_limit_{kind}", "1")
    store.receive(phone, [{"id": "seed", "url": YT}])
    item_id = store.id_for(YT)
    original = agent_policy.over_limit

    def slow_check(*args, **kwargs):
        answer = original(*args, **kwargs)
        time.sleep(0.05)  # widen the check/write gap while retaining the real policy
        return answer

    monkeypatch.setattr(agent_policy, "over_limit", slow_check)
    ready = threading.Barrier(2)

    def send(n):
        ready.wait(timeout=5)
        if kind == "add":
            url = OTHER if n else "https://www.youtube.com/watch?v=ccccccccccc"
            return request(store, key, "/v1/items", {"items": [{"id": str(n), "url": url}]})[0]
        return request(store, key, "/v1/agent/note", {"id": item_id, "text": f"note {n}"})[0]

    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(send, range(2)))
    assert statuses.count(200) == 1
    assert store.agent_used(kind) == 1


@pytest.mark.parametrize("path,body", [("/v1/items", {"items": [{"id": "remote", "url": OTHER}]}),
                                        ("/v1/agent/note", {"id": 1, "text": "remote"})])
def test_agent_writes_are_local_to_this_mac(agent_store, path, body):
    store, _, key = agent_store
    assert request(store, key, path, body, client="192.0.2.10")[0] == 403
    assert store.id_for(OTHER) is None


def test_agent_add_cannot_restore_a_trashed_save_or_change_hidden_save_metadata(agent_store):
    store, phone, key = agent_store
    store.receive(phone, [{"id": "seed", "url": YT}])
    item_id = store.id_for(YT)
    store.set_shelf(item_id, "trash")
    before = store.item_by_id(item_id)
    assert request(store, key, "/v1/items", {"items": [{"id": "again", "url": YT}]})[0] == 200
    after = store.item_by_id(item_id)
    assert after == before
