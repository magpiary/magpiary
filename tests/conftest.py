import pytest

from fakephone import Clock, Mac, Phone


@pytest.fixture(autouse=True)
def private_folders(tmp_path, monkeypatch):
    """No test may read or write the owner's real keys, settings or library."""
    monkeypatch.setenv("MAGPIARY_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path / "home"))


@pytest.fixture(autouse=True)
def no_real_relays(monkeypatch):
    """No test may reach the public Nostr relays: a test that needs relays passes a fake one."""
    from magpiary import boardsync

    def refuse(url):
        raise ConnectionError("tests don't reach real relays")
    monkeypatch.setattr(boardsync, "_connect", refuse)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def mac(tmp_path, clock):
    m = Mac(tmp_path / "magpiary.db", clock)
    m.store.set_setting("setup_done", "1")  # the first-run guide has its own tests (test_update.py)
    yield m
    m.stop()
    m.store.close()


@pytest.fixture
def phone(mac):
    _, key = mac.store.add_phone("Test iPhone")
    return Phone(mac, key)
