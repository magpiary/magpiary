"""iPhone video: an iPhone asking for a VP9 video gets it converted to H.264 and the original is replaced, never kept."""
import shutil
import stat
import subprocess
import threading
import time

import pytest

from magpiary import phone_video

pytestmark = pytest.mark.skipif(not (phone_video.find("ffmpeg") and phone_video.find("ffprobe")), reason="needs ffmpeg")


def make(path, codec):
    ffmpeg = phone_video.find("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", codec, "-c:a", "aac", "-shortest", str(path)], check=True)


@pytest.fixture(autouse=True)
def clean():
    phone_video._reset()


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


def wait_ready(video, seconds=90):
    """Ask again, as the phone does, until the answer is no longer 'converting'."""
    end = time.time() + seconds
    while (state := phone_video.ensure(video)) == "converting" and time.time() < end:
        time.sleep(0.2)
    return state


def test_slow_conversion_answers_converting_then_ready(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    monkeypatch.setattr(phone_video, "WAIT_FOR_RESULT_SECONDS", 0)
    assert phone_video.ensure(video) == "converting"
    assert wait_ready(video) == "ready"
    assert phone_video.probe(video)["codec"] == "h264"


def shorter(extra):
    """A stand-in for the ffmpeg command whose result is cut short: `extra` goes in front of the output file."""
    real = phone_video._command
    return lambda ffmpeg, source, target: real(ffmpeg, source, target)[:-1] + extra + [str(target)]


@pytest.mark.parametrize("extra", [["-t", "1"], ["-af", "atrim=duration=1"]], ids=["video and audio cut", "audio only cut"])
def test_shortened_result_never_replaces_the_original(tmp_path, monkeypatch, extra):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    original = video.read_bytes()
    monkeypatch.setattr(phone_video, "_command", shorter(extra))
    assert phone_video.ensure(video) == "failed"
    assert video.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["media-01.mp4"]


def stub_ffmpeg(tmp_path, monkeypatch, good, body):
    """A fake ffmpeg: copies a good H.264 file to the output name, then runs `body`."""
    script = tmp_path / "bin" / "ffmpeg"
    script.parent.mkdir()
    script.write_text(f'#!/bin/sh\nfor a; do last="$a"; done\ncp "{good}" "$last"\n{body}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    real = phone_video.find
    monkeypatch.setattr(phone_video, "find", lambda name: str(script) if name == "ffmpeg" else real(name))


def test_decode_errors_on_stderr_fail_the_job(tmp_path, monkeypatch):
    good = tmp_path / "good.mp4"
    make(good, "libx264")
    video = tmp_path / "lib" / "media-01.mp4"
    video.parent.mkdir()
    make(video, "libvpx-vp9")
    original = video.read_bytes()
    stub_ffmpeg(tmp_path, monkeypatch, good, 'echo "error while decoding MB" >&2')
    assert phone_video.ensure(video) == "failed"
    assert video.read_bytes() == original


def test_the_same_stub_without_errors_is_accepted(tmp_path, monkeypatch):
    """Control for the test above: with no error text the identical good file is taken, so the stderr rule is what failed it."""
    good = tmp_path / "good.mp4"
    make(good, "libx264")
    video = tmp_path / "lib" / "media-01.mp4"
    video.parent.mkdir()
    make(video, "libvpx-vp9")
    stub_ffmpeg(tmp_path, monkeypatch, good, "true")
    assert phone_video.ensure(video) == "ready"


def test_ffmpeg_that_hangs_is_killed_at_the_timeout(tmp_path, monkeypatch):
    video = tmp_path / "lib" / "media-01.mp4"
    video.parent.mkdir()
    make(video, "libvpx-vp9")
    original = video.read_bytes()
    stub_ffmpeg(tmp_path, monkeypatch, video, "sleep 30")
    monkeypatch.setattr(phone_video, "_timeout", lambda duration: 0.5)
    started = time.time()
    assert phone_video.ensure(video) == "failed"
    assert time.time() - started < 15 and video.read_bytes() == original


def test_timeout_rule():
    assert phone_video._timeout(5) == 600 and phone_video._timeout(1000) == 3000 and phone_video._timeout(99999) == 7200


def test_many_requests_for_one_file_run_ffmpeg_once(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    runs, real = [], phone_video._run_ffmpeg
    monkeypatch.setattr(phone_video, "_run_ffmpeg", lambda *a: runs.append(1) or real(*a))
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(phone_video.ensure(video))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    assert answers == ["ready"] * 12 and len(runs) == 1
    assert phone_video.ensure(video) == "ready" and len(runs) == 1, "already converted: not encoded again"


def test_at_most_two_ffmpeg_at_once(tmp_path, monkeypatch):
    lock, now, peak = threading.Lock(), [0], [0]
    def slow(path, before):
        with lock:
            now[0] += 1; peak[0] = max(peak[0], now[0])
        time.sleep(0.3)
        with lock:
            now[0] -= 1
        return False
    monkeypatch.setattr(phone_video, "_convert", slow)
    monkeypatch.setattr(phone_video, "WAIT_FOR_RESULT_SECONDS", 0)
    videos = []
    for i in range(6):
        v = tmp_path / f"media-0{i}.mp4"
        make(v, "libvpx-vp9")
        videos.append(v)
        assert phone_video.ensure(v) == "converting"
    [wait_ready(v) for v in videos]
    assert peak[0] == 2


def test_failure_is_retried_after_a_backoff_that_grows(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    make(video, "libvpx-vp9")
    clock, calls, real = [1000.0], [], phone_video._convert
    monkeypatch.setattr(phone_video, "_now", lambda: clock[0])
    def flaky(path, before):
        calls.append(1)
        return real(path, before) if len(calls) > 2 else False
    monkeypatch.setattr(phone_video, "_convert", flaky)
    assert phone_video.ensure(video) == "failed" and len(calls) == 1
    clock[0] += 30
    assert phone_video.ensure(video) == "failed" and len(calls) == 1, "too soon"
    clock[0] += 31  # 61 s after the first failure
    assert phone_video.ensure(video) == "failed" and len(calls) == 2
    clock[0] += 61  # the wait is now 120 s
    assert phone_video.ensure(video) == "failed" and len(calls) == 2
    clock[0] += 60
    assert phone_video.ensure(video) == "ready" and len(calls) == 3
    assert phone_video.probe(video)["codec"] == "h264"


def test_a_changed_source_is_retried_at_once(tmp_path, monkeypatch):
    video = tmp_path / "media-01.mp4"
    video.write_bytes(b"not a video")
    assert phone_video.ensure(video) == "failed"
    make(video, "libvpx-vp9")
    assert phone_video.ensure(video) == "ready"


def test_only_iphones_trigger_it():
    assert phone_video.is_iphone("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15")
    assert not phone_video.is_iphone("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15")


def test_backoff_stops_growing_at_an_hour(monkeypatch):
    path = phone_video.Path("x")
    phone_video._failed[path] = (0.0, (1, 1), 30)
    monkeypatch.setattr(phone_video, "_now", lambda: 3599.0)
    assert not phone_video._may_retry(path, (1, 1))
    monkeypatch.setattr(phone_video, "_now", lambda: 3601.0)
    assert phone_video._may_retry(path, (1, 1))


def test_clean_stale_temporaries_removes_only_exact_leftovers(tmp_path):
    lib = tmp_path / "library"
    stale = []
    for n in ("a", "b", "c"):
        d = lib / n
        d.mkdir(parents=True)
        (d / "media-01.mp4").write_bytes(b"original")
        t = d / ".media-01.h264.tmp.mp4"
        t.write_bytes(b"x")
        stale.append(t)
    keep_names = ["media-01.mp4", ".media-01.mp4", ".media-01.h264.tmp.mp4.keep", ".notes.h264.tmp.mp4", ".media-.h264.tmp.mp4"]
    keep = lib / "a"
    for name in keep_names:
        (keep / name).write_bytes(b"k")
    deep = lib / "a" / "nested"
    deep.mkdir()
    (deep / ".media-01.h264.tmp.mp4").write_bytes(b"deep")
    (lib / ".media-02.h264.tmp.mp4").write_bytes(b"at library level")
    target = tmp_path / "precious.bin"
    target.write_bytes(b"precious")
    (lib / "b" / ".media-09.h264.tmp.mp4").symlink_to(target)

    assert phone_video.clean_stale_temporaries(lib) == 3
    assert not any(t.exists() for t in stale)
    for name in keep_names:
        assert (keep / name).exists(), name
    assert (lib / "b" / "media-01.mp4").read_bytes() == b"original"
    assert (deep / ".media-01.h264.tmp.mp4").exists()
    assert (lib / ".media-02.h264.tmp.mp4").exists()
    assert (lib / "b" / ".media-09.h264.tmp.mp4").is_symlink() and target.read_bytes() == b"precious"


def test_clean_stale_temporaries_missing_folder(tmp_path):
    assert phone_video.clean_stale_temporaries(tmp_path / "nope") == 0


def test_clean_in_background_runs(tmp_path):
    d = tmp_path / "item"
    d.mkdir()
    t = d / ".media-03.h264.tmp.mp4"
    t.write_bytes(b"x")
    phone_video._clean_in_background(tmp_path)
    for _ in range(100):
        if not t.exists():
            break
        time.sleep(0.05)
    assert not t.exists()
