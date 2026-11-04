import subprocess
import json
import shutil
from types import SimpleNamespace

import pytest

from magpiary import thumbs


def fake_ffmpeg(calls):
    def run(command, **kwargs):
        calls.append(command)
        open(command[-1], "wb").write(b"\xff\xd8\xff")
        return SimpleNamespace(returncode=0)
    return run


def test_a_small_copy_is_made_once_and_kept_beside_the_original(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "find", lambda name: "/usr/bin/ffmpeg")
    original = tmp_path / "thumbnail.jpg"
    original.write_bytes(b"x" * 100)
    calls = []
    first = thumbs.small(original, 600, fake_ffmpeg(calls))
    again = thumbs.small(original, 600, fake_ffmpeg(calls))
    assert first == again == tmp_path / ".thumbs" / "thumbnail-600x800.jpg" and len(calls) == 1
    assert "max(600/iw,800/ih)" in " ".join(calls[0]) and "-ss" not in calls[0]  # tall enough to fill a portrait tile


def test_a_video_gets_its_first_moment_and_odd_sizes_or_a_failure_give_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "find", lambda name: "/usr/bin/ffmpeg")
    video = tmp_path / "media-01.mp4"
    video.write_bytes(b"v")
    calls = []
    assert thumbs.small(video, 160, fake_ffmpeg(calls)) and "-ss" in calls[0]
    assert thumbs.small(video, 999, fake_ffmpeg(calls)) is None  # only the sizes the hub asks for
    broken = tmp_path / "media-02.mp4"
    broken.write_bytes(b"v")
    assert thumbs.small(broken, 160, lambda *a, **k: SimpleNamespace(returncode=1)) is None
    assert thumbs.small(broken, 160, lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1))) is None


@pytest.mark.parametrize("video,width,size", [(False, 600, (640, 480)), (True, 160, (160, 120))])
def test_real_ffmpeg_produces_a_decodable_cached_jpeg(tmp_path, monkeypatch, video, width, size):
    """A tile copy is never larger than the original (640 x 480 here: not enough to fill 800 high, so kept whole)."""
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are not installed")
    monkeypatch.setattr(thumbs, "find", lambda name: ffmpeg)
    original = tmp_path / ("slide.mp4" if video else "photo.jpg")
    options = ["-t", "0.3", "-c:v", "mpeg4"] if video else ["-frames:v", "1"]
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x480:rate=10", *options, str(original)], check=True, capture_output=True, timeout=30)
    original_bytes = original.read_bytes()
    calls = []

    def convert(command, **kwargs):
        calls.append(command)
        return subprocess.run(command, **kwargs)

    small = thumbs.small(original, width, run=convert)
    assert small is not None and small.read_bytes().startswith(b"\xff\xd8\xff")
    info = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "json", str(small)],
                          check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(info.stdout)["streams"] == [{"width": size[0], "height": size[1]}]
    assert thumbs.small(original, width, run=convert) == small and len(calls) == 1
    assert original.read_bytes() == original_bytes
