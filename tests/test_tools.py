

def test_a_download_cut_short_is_not_taken_for_the_media(tmp_path, monkeypatch):
    """Review 4 Nov 2026: yt-dlp failed and left media-01.mp4.part; that counted as a saved video."""
    from types import SimpleNamespace

    import pytest

    from magpiary import tools

    def fake_run(cmd, timeout):
        (tmp_path / "media-01.mp4.part").write_bytes(b"half")
        return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: interrupted")
    y = tools.YtDlp(run=fake_run)
    monkeypatch.setattr(y, "_base", lambda *a: ["yt-dlp"])
    with pytest.raises(tools.YtDlpError):
        y.download("https://example.com/v", tmp_path)
    assert not (tmp_path / "media-01.mp4.part").exists() and tools.media_files(tmp_path) == []
