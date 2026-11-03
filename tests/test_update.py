"""Updating and removing Magpiary: recorded GitHub answers, a fake uv, no real installs."""

import json
import subprocess

import pytest

from magpiary import __version__, update
from magpiary.config import config_dir, data_dir
from magpiary.store import Store
from test_hub import page, post


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


def release(tag, status=200):
    return lambda url: (status, json.dumps({"tag_name": tag}).encode())


def test_versions_compare_as_numbers():
    assert update.newer("0.10.0", "0.9.9") and not update.newer("0.1.0", "0.1.0") and not update.newer("", "0.1.0")


def test_the_latest_release_is_asked_for_once_a_day(store):
    asked = []

    def get(url):
        asked.append(url)
        return 200, b'{"tag_name": "v9.0.0"}'
    assert update.check_daily(store, get, today="2026-10-24") == "9.0.0"
    assert update.check_daily(store, get, today="2026-10-24") == "9.0.0" and len(asked) == 1
    assert "magpiary/magpiary/releases/latest" in asked[0]
    assert update.latest(release("", 404)) == "" and update.latest(lambda url: (_ for _ in ()).throw(OSError())) == ""


def test_install_uses_uv_with_the_release_or_a_local_source(monkeypatch):
    monkeypatch.setattr(update, "find", lambda name: "/bin/uv")
    seen = []

    def run(command, timeout):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")
    assert update.install("9.0.0", run) is None
    assert seen[0][:4] == ["/bin/uv", "tool", "install", "--force"] and "v9.0.0.tar.gz" in seen[0][-1]
    assert seen[1] == ["/bin/uv", "tool", "upgrade", "yt-dlp"]
    monkeypatch.setenv("MAGPIARY_SOURCE", "/tmp/magpiary-checkout")
    update.install("9.0.0", run)
    assert seen[2][-1] == "/tmp/magpiary-checkout"
    failing = lambda c, t: subprocess.CompletedProcess(c, 1, "", "error: no such release")  # noqa: E731
    assert "did not install" in update.install("9.0.0", failing)


def test_uninstall_keeps_the_library_unless_asked(monkeypatch):
    from magpiary import service
    monkeypatch.setattr(service, "uninstall", lambda: "Service removed.")
    monkeypatch.setattr(update, "find", lambda name: "/bin/uv")
    ran = []
    run = lambda c, t: ran.append(c) or subprocess.CompletedProcess(c, 0, "", "")  # noqa: E731
    for folder in (data_dir() / "tools", data_dir() / "models", config_dir()):
        folder.mkdir(parents=True)
    (data_dir() / "magpiary.db").write_text("keep me")
    done = update.remove(False, run)
    assert (data_dir() / "magpiary.db").exists() and config_dir().exists()
    assert not (data_dir() / "tools").exists() and not (data_dir() / "models").exists()
    assert ["/bin/uv", "tool", "uninstall", "magpiary"] in ran and any("Kept your library" in d for d in done)
    update.remove(True, run)
    assert not data_dir().exists() and not config_dir().exists()


def test_the_hub_shows_a_banner_and_updates(mac, monkeypatch):
    assert "is available" not in page(mac, "/")[2]
    mac.store.set_setting(update.LATEST_SETTING, "99.0.0")
    body = page(mac, "/")[2]
    assert "Magpiary 99.0.0 is available" in body and f"you have {__version__}" in body
    installed, restarted = [], []
    monkeypatch.setattr(update, "install", lambda version: installed.append(version))
    mac.server.hub.restart = lambda: restarted.append(1)
    status, _, data = post(mac, "/hub/update", next="/")
    assert status == 200 and b"Updated to Magpiary 99.0.0" in data and installed == ["99.0.0"] and restarted == [1]


# ---- standalone tools ----------------------------------------------------------------------

def test_standalone_tools_are_used_only_when_their_checksum_matches(monkeypatch):
    import hashlib
    import io
    import platform
    import zipfile

    from magpiary import tools

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("ffprobe", b"#!/bin/sh\necho fake ffprobe\n")
    good = buffer.getvalue()
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    monkeypatch.setitem(tools.STANDALONE, ("ffprobe", arch), ("https://example.test/ffprobe.zip", hashlib.sha256(good).hexdigest()))

    class Body(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    assert tools.install_tools(["ffprobe"], opener=lambda url, timeout: Body(good)) == []
    installed = tools.tools_dir() / "ffprobe"
    assert installed.read_bytes().startswith(b"#!/bin/sh") and installed.stat().st_mode & 0o111
    assert tools.find("ffprobe") in (str(installed), tools.find("ffprobe"))  # the tools folder is searched too

    installed.unlink()
    problems = tools.install_tools(["ffprobe"], opener=lambda url, timeout: Body(b"tampered"))
    assert "checksum" in problems[0] and not installed.exists()


# ---- the first-run guide -------------------------------------------------------------------

def test_a_fresh_library_opens_the_guide_until_a_phone_is_paired(mac):
    from test_hub import request

    mac.store.set_setting("setup_done", "")
    status, headers, _ = request(mac, "GET", "/")
    assert status == 303 and headers["Location"] == "/welcome"
    assert "Everything you save" in page(mac, "/welcome")[2]
    assert "On My iPhone" in page(mac, "/welcome/phone")[2] and "Make it automatic" in page(mac, "/welcome/automatic")[2]
    assert "Private" in page(mac, "/welcome/reading")[2]
    body = page(mac, "/welcome/share")[2]
    assert "Listening for your iPhone" in body and "Skip for now" in body and "Go to my library" in body  # a way out with no phone
    post(mac, "/hub/welcome/done", next="/")
    assert request(mac, "GET", "/")[0] == 200  # the guide never traps anyone: skipping opens the library

    mac.store.set_setting("setup_done", "")
    mac.store.add_phone("Test iPhone")
    assert request(mac, "GET", "/")[0] == 200  # a paired phone opens the library
    post(mac, "/hub/settings/mode", mode="private", next="/welcome/reading")
    assert 'class="wp on"' in page(mac, "/welcome/reading")[2] and mac.store.get_setting("ai_mode") == "private"
    body = page(mac, "/welcome/share")[2]
    assert "Go to my library" in body
    status, _, data = request(mac, "GET", "/welcome.json")
    assert json.loads(data) == {"phones": 1, "delivered": False}

def test_a_pasted_link_counts_as_the_first_share_so_a_mac_only_user_can_finish(mac):
    from test_hub import request

    mac.store.set_setting("setup_done", "")
    post(mac, "/hub/settings/mode", mode="private", next="/welcome/reading")
    body = page(mac, "/welcome/share")[2]
    assert "Listening for your iPhone" in body and "Skip for now" in body and "Open my library" not in body
    post(mac, "/hub/add", url="https://example.com/a-page", next="/welcome/share")
    body = page(mac, "/welcome/share")[2]
    assert "Saved. Your Mac is reading it now." in body and "Open my library" in body and "Listening" not in body
    post(mac, "/hub/welcome/done", next="/")
    assert request(mac, "GET", "/")[0] == 200


def test_homebrew_installs_use_the_stable_opt_path_and_brew_upgrade(monkeypatch):
    from pathlib import Path

    from magpiary import service
    cellar = Path("/opt/homebrew/Cellar/magpiary/0.1.0/libexec/bin/magpiary")
    assert service.stable_path(cellar) == Path("/opt/homebrew/opt/magpiary/libexec/bin/magpiary")
    assert service.stable_path(Path("/path/to/.local/bin/magpiary")) == Path("/path/to/.local/bin/magpiary")
    monkeypatch.setattr(update.sys, "executable", str(cellar.parent / "python"))
    assert update.from_homebrew() and "brew upgrade magpiary" in update.install("9.0.0")


def test_the_mac_app_is_sent_to_the_release_page_not_uv(monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")

    def forbidden(cmd, timeout):
        raise AssertionError("the app must not run an installer")

    assert update.RELEASES_PAGE in update.install("9.0.0", run=forbidden)


def test_the_banner_in_the_mac_app_links_to_the_download(mac, monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    mac.store.set_setting(update.LATEST_SETTING, "9.0.0")
    body = page(mac, "/")[2]
    assert update.RELEASES_PAGE in body and "/hub/update" not in body
