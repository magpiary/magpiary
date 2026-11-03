"""Security checks on hub routing with a synthetic Store and no listener."""

import json
import time

import pytest

from magpiary import doctor
from magpiary.hub import Hub
from magpiary.hub_settings import PAGES
from magpiary.store import Store


@pytest.fixture
def hub(tmp_path, monkeypatch):
    store = Store(tmp_path / "library.db")
    store.set_setting("setup_done", "1")
    instance = Hub(store)
    monkeypatch.setattr(instance, "_offline_checks", lambda: [])
    yield instance
    store.close()


def test_live_health_checks_need_a_local_csrf_protected_action(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(doctor, "live", lambda *args, **kwargs: calls.append("synthetic call"))
    assert hub.get("/doctor.json", {"start": ["1"], "live": ["1"]}, "127.0.0.1", "localhost:8765").status == 403
    page = hub.get("/doctor", {"live": ["1"]}, "127.0.0.1", "localhost:8765")
    assert page.status == 200 and b'data-live="0"' in page.body
    assert calls == []
    for ip, origin, fields in [("192.0.2.10", None, {"csrf": hub.csrf}),
                                ("127.0.0.1", "https://attacker.example", {"csrf": hub.csrf}),
                                ("127.0.0.1", None, {})]:
        assert hub.post("/hub/doctor", {"live": "1", **fields}, ip, "localhost:8765", origin).status == 403
    assert calls == []
    assert hub.post("/hub/doctor", {"live": "1", "csrf": hub.csrf}, "127.0.0.1", "localhost:8765", None).status == 200
    for _ in range(200):
        result = hub.doctor_json({})
        if json.loads(result.body)["done"]:
            break
        time.sleep(0.005)
    assert json.loads(result.body)["done"] and calls == ["synthetic call"]


@pytest.mark.parametrize("section", list(PAGES))
def test_all_nine_settings_pages_reject_lan_and_rebinding_hosts(hub, section):
    for ip, host in [("192.0.2.10", "localhost:8765"), ("127.0.0.1", "attacker.example:8765")]:
        assert hub.get(f"/settings/{section}", {}, ip, host).status == 403
