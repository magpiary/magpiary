import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from magpiary import downloads, embed, tools
from magpiary.cli import main


def test_catalog_lists_every_download_with_a_reason():
    entries = downloads.catalog()
    assert [e.id for e in entries] == ["ffmpeg", "ffprobe", "deno", "meaning-model", "whisper-model"]
    assert all(e.why and e.source and e.url.startswith("https://") for e in entries)


def test_checksums_come_from_the_files_that_install_them():
    by_id = {e.id: e for e in downloads.catalog()}
    arch = downloads._arch()
    assert by_id["ffmpeg"].url == tools.STANDALONE[("ffmpeg", arch)][0]
    assert by_id["ffmpeg"].sha256 == tools.STANDALONE[("ffmpeg", arch)][1]
    for _, sha in embed.FILES.values():
        assert sha in by_id["meaning-model"].sha256


def test_installed_follows_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))
    monkeypatch.setattr(downloads, "_whisper_here", lambda: False)
    assert not {e.id: e for e in downloads.catalog()}["meaning-model"].installed
    folder = embed.model_dir()
    folder.mkdir(parents=True)
    for name in embed.FILES:
        (folder / name).write_bytes(b"x")
    assert {e.id: e for e in downloads.catalog()}["meaning-model"].installed


def test_totals_and_sizes():
    entries = downloads.catalog()
    assert downloads.total_bytes(entries) >= downloads.total_bytes(entries, only_missing=True)
    assert downloads.human_size(487_601_967) == "488 MB"
    assert downloads.human_size(1_500_000_000) == "1.5 GB"
    assert downloads.human_size(None) == "size varies"


def test_downloads_command_prints_json(capsys):
    assert main(["downloads", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["downloads"]) == 5 and data["total_bytes"] >= data["missing_bytes"]


def test_downloads_command_prints_plain_list(capsys):
    assert main(["downloads"]) == 0
    assert "Transcript model" in capsys.readouterr().out


def test_yt_dlp_is_included_in_the_app_not_downloaded():
    assert "yt-dlp" in [name for name, _ in downloads.INCLUDED]
    assert "yt-dlp" not in [e.id for e in downloads.catalog()]


def _pip(ran, version="2026.11.1"):
    """Stands in for pip and the new yt-dlp: pip makes the folder it was pointed at."""
    def run(cmd, timeout):
        ran.append(cmd)
        if "pip" in cmd:
            new = Path(cmd[cmd.index("--target") + 1])
            (new / "yt_dlp").mkdir(parents=True)
            (new / "yt_dlp" / "version").write_text(version)
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0 if version else 1, stdout=version)
    return run


def _in_the_app(monkeypatch, tmp_path):
    monkeypatch.setenv("MAGPIARY_HOME", str(tmp_path))
    monkeypatch.setenv("MAGPIARY_PROGRAM", "/Applications/Magpiary.app/Contents/Resources/python/bin/magpiary")
    monkeypatch.setattr(tools, "find", lambda name: pytest.fail(f"the app must not look for {name}"))


def test_the_app_updates_yt_dlp_outside_its_own_folder_once_a_day(mac, monkeypatch, tmp_path):
    _in_the_app(monkeypatch, tmp_path)
    ran = []
    assert tools.update_ytdlp(mac.store, run=_pip(ran), today="2026-11-01")
    assert (tools.ytdlp_updates_dir() / "yt_dlp" / "version").read_text() == "2026.11.1"
    assert not list(tools.tools_dir().glob("*.new")) and not list(tools.tools_dir().glob("*.old"))
    assert not any(str(part).startswith("/Applications") for part in ran[0][ran[0].index("--target"):])
    assert not tools.update_ytdlp(mac.store, run=_pip(ran), today="2026-11-01")
    assert tools.update_ytdlp(mac.store, run=_pip(ran, "2026.12.1"), today="2026-11-02")
    assert (tools.ytdlp_updates_dir() / "yt_dlp" / "version").read_text() == "2026.12.1"


def test_a_yt_dlp_update_that_does_not_start_keeps_the_working_copy(mac, monkeypatch, tmp_path):
    _in_the_app(monkeypatch, tmp_path)
    assert tools.update_ytdlp(mac.store, run=_pip([]), today="2026-11-01")
    assert not tools.update_ytdlp(mac.store, run=_pip([], ""), today="2026-11-02")
    assert (tools.ytdlp_updates_dir() / "yt_dlp" / "version").read_text() == "2026.11.1"
    assert not list(tools.tools_dir().glob("*.new"))


def test_an_offline_yt_dlp_update_changes_nothing(mac, monkeypatch, tmp_path):
    _in_the_app(monkeypatch, tmp_path)

    def offline(cmd, timeout):
        raise OSError("no network")

    assert not tools.update_ytdlp(mac.store, run=offline, today="2026-11-01")
    assert not tools.ytdlp_updates_dir().exists()


def test_the_app_launcher_and_the_code_agree_on_the_updates_folder():
    script = (Path(__file__).parent.parent / "packaging" / "app" / "build-app.sh").read_text()
    assert f"tools/{tools.ytdlp_updates_dir().name}" in script


def test_the_daily_yt_dlp_update_uses_pip_beside_magpiary_when_uv_is_absent(mac, monkeypatch):
    monkeypatch.delenv("MAGPIARY_PROGRAM", raising=False)
    beside = str(Path(sys.executable).parent / "yt-dlp")
    monkeypatch.setattr(tools, "find", lambda name: beside if name == "yt-dlp" else None)
    ran = []
    assert tools.update_ytdlp(mac.store, run=lambda cmd, timeout: ran.append(cmd), today="2026-11-01")
    assert ran == [[sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp"]]
    monkeypatch.setattr(tools, "find", lambda name: "/elsewhere/yt-dlp" if name == "yt-dlp" else None)
    assert not tools.update_ytdlp(mac.store, run=lambda cmd, timeout: ran.append(cmd), today="2026-11-02", force=True)
