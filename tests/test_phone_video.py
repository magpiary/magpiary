"""iPhone video: an iPhone asking for a VP9 video gets it converted to H.264 and the original is replaced, never kept."""
import shutil
import subprocess

import pytest

from magpiary import phone_video

pytestmark = pytest.mark.skipif(not (phone_video.find("ffmpeg") and phone_video.find("ffprobe")), reason="needs ffmpeg")


def make(path, codec):
    ffmpeg = phone_video.find("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", codec, "-c:a", "aac", "-shortest", str(path)], check=True)


@pytest.fixture(autouse=True)
def clean():
    phone_video._failed.clear(); phone_video._locks.clear(); phone_video._background.clear()


def test_vp9_becomes_h264_and_only_one_file_remains(tmp_path):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    assert phone_video.probe(video)["codec"] == "vp9"
    assert phone_video.ensure(video) == "ready"
    after = phone_video.probe(video)
    assert after["codec"] == "h264" and after["audio"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["media-01.mp4"], "no second copy, no leftovers"


def test_h264_is_left_alone(tmp_path):
    video = tmp_path / "media-01.mp4"
    make(video, "libx264")
    before = video.read_bytes()
    assert phone_video.ensure(video) == "ready"
    assert video.read_bytes() == before


def test_unreadable_file_is_kept_and_not_retried(tmp_path):
    video = tmp_path / "media-01.mp4"
    video.write_bytes(b"not a video")
    assert phone_video.ensure(video) == "failed"
    assert video.read_bytes() == b"not a video"
    assert phone_video.ensure(video) == "failed"


def test_failed_conversion_keeps_the_original(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    original = video.read_bytes()
    real = phone_video.find
    monkeypatch.setattr(phone_video, "find", lambda name: shutil.which("false") if name == "ffmpeg" else real(name))
    assert phone_video.ensure(video) == "failed"
    assert video.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["media-01.mp4"]


def test_long_video_converts_in_the_background(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    monkeypatch.setattr(phone_video, "WAIT_UP_TO_SECONDS", 0)
    assert phone_video.ensure(video) == "converting"
    for thread in list(phone_video._background.values()):
        thread.join(60)
    assert phone_video.ensure(video) == "ready"
    assert phone_video.probe(video)["codec"] == "h264"


def test_only_iphones_trigger_it():
    assert phone_video.is_iphone("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15")
    assert not phone_video.is_iphone("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15")
