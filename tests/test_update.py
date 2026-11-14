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
    assert "On My iPhone" in page(mac, "/welcome/phone")[2] and "Chrome" in page(mac, "/welcome/browser")[2]
    assert "Private" in page(mac, "/welcome/reading")[2]
    body = page(mac, "/welcome/share")[2]
    assert "Listening for your first save" in body and "Skip for now" in body and "Go to my library" in body  # a way out with no phone
    post(mac, "/hub/welcome/done", next="/")
    assert request(mac, "GET", "/")[0] == 200  # the guide never traps anyone: skipping opens the library

    mac.store.set_setting("setup_done", "")
    mac.store.add_phone("Test iPhone")
    assert request(mac, "GET", "/")[0] == 200  # a paired phone opens the library
    post(mac, "/hub/settings/mode", mode="private", next="/welcome/reading")
    assert 'wp on' in page(mac, "/welcome/reading")[2] and mac.store.get_setting("ai_mode") == "private"
    body = page(mac, "/welcome/share")[2]
    assert "Go to my library" in body
    status, _, data = request(mac, "GET", "/welcome.json")
    got = json.loads(data)
    assert got["phones"] == 1 and got["delivered"] is False and got["sig"]

def test_a_pasted_link_counts_as_the_first_share_so_a_mac_only_user_can_finish(mac):
    from test_hub import request

    mac.store.set_setting("setup_done", "")
    post(mac, "/hub/settings/mode", mode="private", next="/welcome/reading")
    body = page(mac, "/welcome/share")[2]
    assert "Listening for your first save" in body and "Skip for now" in body and "Open my library" not in body
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


def _app(tmp_path, monkeypatch):
    app = tmp_path / "Applications" / "Magpiary.app"
    (app / "Contents").mkdir(parents=True)
    monkeypatch.setenv("MAGPIARY_PROGRAM", f"{app}/Contents/Resources/python/bin/magpiary")
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path / "home"))
    return app


def _fake_download(dmg_bytes, sums_for=None, name="Magpiary-9.0.0.dmg", seen=None):
    import hashlib
    digest = hashlib.sha256(sums_for if sums_for is not None else dmg_bytes).hexdigest()

    def download(url, to, limit=None):
        if seen is not None:
            seen.append((url, limit))
        to.write_bytes(dmg_bytes if url.endswith(".dmg") else f"{digest}  {name}\n".encode())
        return True
    return download


def test_the_mac_app_downloads_the_offered_version_checks_it_and_hands_over_to_a_helper(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    spawned, seen = [], []
    assert update.install_app("9.0.0", _fake_download(b"disk image", seen=seen), spawned.append) is None
    assert [u for u, _ in seen] == [f"{update.RELEASE_BASE}/v9.0.0/Magpiary-9.0.0.dmg", f"{update.RELEASE_BASE}/v9.0.0/SHA256SUMS"]
    assert seen[0][1] == update.MAX_DMG and seen[1][1] == update.MAX_SUMS  # each download has its own size limit
    command, = spawned
    assert command[0] == "/bin/bash" and command[3] == str(app) and command[5] == "9.0.0"
    assert command[6] == str(update.result_path())
    helper = open(command[1]).read()
    assert 'mkdir "$LOCK"' in helper and "CFBundleShortVersionString" in helper and "pkill" not in helper


def test_no_update_for_an_older_or_same_version_or_while_one_runs(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    for version in (update.__version__, "0.0.1", "nope"):
        assert update.install_app(version, lambda *a: 1 / 0, lambda c: 1 / 0) == "There is no newer version."
    (tmp_path / "Applications" / "Magpiary.app.updating").mkdir()
    assert "already running" in update.install_app("9.0.0", lambda *a: 1 / 0, lambda c: 1 / 0) and app.exists()


def test_a_bad_checksum_another_file_or_failed_download_changes_nothing(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    spawned = []
    assert "checksum" in update.install_app("9.0.0", _fake_download(b"tampered", sums_for=b"real"), spawned.append)
    assert "checksum" in update.install_app("9.0.0", _fake_download(b"img", name="Magpiary-8.0.0.dmg"), spawned.append)
    assert "could not be downloaded" in update.install_app("9.0.0", lambda url, to, limit=None: False, spawned.append)
    assert spawned == []


def test_downloads_stop_past_their_size_limit(tmp_path, monkeypatch):
    import io

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: Answer(b"x" * 5000))
    to = tmp_path / "f"
    assert not update._download("https://example.invalid/f", to, limit=1000) and not to.exists()
    assert update._download("https://example.invalid/f", to, limit=10_000) and to.stat().st_size == 5000


def test_the_app_path_is_the_nearest_magpiary_bundle(monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Box.app/Contents/Apps/Magpiary.app/Contents/Resources/bin/magpiary")
    assert str(update.app_path()) == "/Applications/Box.app/Contents/Apps/Magpiary.app"
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Other.app/Contents/Resources/bin/magpiary")
    assert update.app_path() is None


def test_an_app_in_a_folder_it_cannot_write_to_falls_back_to_the_release_page(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(update.os, "access", lambda path, mode: False)
    assert update.RELEASES_PAGE in update.install_app("9.0.0", lambda *a: 1 / 0, lambda c: 1 / 0) and app.exists()


def test_the_helper_script_is_valid_shell():
    assert subprocess.run(["/bin/bash", "-n"], input=update.HELPER, text=True).returncode == 0


def _helper_world(tmp_path, version="9.0.0", bundle="org.magpiary.app", starts=True):
    """A fake Mac for the helper: hdiutil, osascript, open and ps stand-ins on PATH, an installed app and a disk image."""
    import os
    import stat
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    vol = tmp_path / "Volumes" / "Magpiary"
    src = vol / "Magpiary.app" / "Contents"
    (src / "MacOS").mkdir(parents=True)
    (src / "MacOS" / "Magpiary").write_text("#!/bin/sh\n")
    (src / "MacOS" / "Magpiary").chmod(0o755)
    (src / "NEWMARK").write_text("new")
    (src / "Info.plist").write_text(f'<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>{bundle}</string>'
                                    f'<key>CFBundleShortVersionString</key><string>{version}</string></dict></plist>')
    app = tmp_path / "Applications" / "Magpiary.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "OLDMARK").write_text("old")
    running = tmp_path / "running"
    scripts = {"hdiutil": f'[ "$1" = attach ] && printf "/dev/disk9\\tApple\\t{vol}\\n"; exit 0',
               "osascript": f'rm -f "{running}"', "sleep": "exit 0",
               "open": f'[ "{"1" if starts else ""}" = 1 ] && touch "{running}"; exit 0',
               "ps": f'[ -e "{running}" ] && echo "  42 {app}/Contents/MacOS/Magpiary"; exit 0'}
    for name, body in scripts.items():
        f = bin_ / name
        f.write_text("#!/bin/bash\n" + body + "\n")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    work = tmp_path / "work"
    work.mkdir()
    script = work / "helper.sh"
    script.write_text(update.HELPER)
    result = tmp_path / "data" / "update-result.txt"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
    run = lambda want="9.0.0": subprocess.run(["/bin/bash", str(script), str(work / "x.dmg"), str(app), str(work), want, str(result)],  # noqa: E731
                                              env=env, capture_output=True, text=True, timeout=60)
    return app, result, run


def test_the_helper_swaps_the_app_and_reports_it(tmp_path):
    app, result, run = _helper_world(tmp_path)
    run()
    assert (app / "Contents" / "NEWMARK").exists() and not (app / "Contents" / "OLDMARK").exists()
    assert result.read_text().startswith("ok\t9.0.0\t") and not list(app.parent.glob("Magpiary.app.*"))


def test_the_helper_keeps_the_old_app_for_a_wrong_version_or_bundle(tmp_path):
    app, result, run = _helper_world(tmp_path, version="8.0.0")
    run()
    assert (app / "Contents" / "OLDMARK").exists() and result.read_text().startswith("failed\t9.0.0\t")


def test_the_helper_puts_the_old_app_back_when_the_new_one_does_not_start(tmp_path):
    app, result, run = _helper_world(tmp_path, starts=False)
    run()
    assert (app / "Contents" / "OLDMARK").exists() and "did not start" in result.read_text()
    assert not list(app.parent.glob("Magpiary.app.*"))


def test_the_banner_in_the_mac_app_offers_update_now(mac, monkeypatch):
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    mac.store.set_setting(update.LATEST_SETTING, "9.0.0")
    body = page(mac, "/")[2]
    assert "/hub/update" in body and "Update now" in body and "drag the new version" not in body
    monkeypatch.setattr(update, "install", lambda version: None)
    mac.server.hub.restart = lambda: (_ for _ in ()).throw(AssertionError("the helper restarts the app, not the hub"))
    status, _, data = post(mac, "/hub/update", next="/")
    assert status == 200 and b"close and open again" in data
