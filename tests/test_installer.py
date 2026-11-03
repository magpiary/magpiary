import errno
import hashlib
import io
import urllib.error
import zipfile

import pytest

from magpiary import installer
from magpiary.installer import FetchError, Part

DATA = bytes(range(256)) * 4000  # about 1 MB


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data, status=200, total=None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def server(data, honour_range=True, fail_first=0, kill_after=None, errors=None):
    """A fake download site. `fail_first` connections fail with a connection error; `kill_after` cuts the first answer short."""
    calls = {"n": 0, "ranges": []}

    def opener(request, timeout=0):
        calls["n"] += 1
        if calls["n"] <= fail_first:
            raise errors or urllib.error.URLError("no network")
        header = request.get_header("Range")
        calls["ranges"].append(header)
        start = int(header.split("=")[1].rstrip("-")) if header and honour_range else 0
        if start > len(data):
            raise urllib.error.HTTPError(request.full_url, 416, "range", {}, None)
        body = data[start:]
        status = 206 if header and honour_range else 200
        if kill_after is not None and calls["n"] == 1:
            class Dying(Response):
                def read(self, n=-1):
                    chunk = super().read(min(n, kill_after) if n > 0 else kill_after)
                    if not chunk:
                        return chunk
                    self.sent = getattr(self, "sent", 0) + len(chunk)
                    if self.sent > kill_after:
                        raise ConnectionResetError("cut")
                    return chunk
            return Dying(body, status)
        return Response(body, status)
    opener.calls = calls
    return opener


def part_for(tmp_path, data=DATA, **kw):
    return Part("https://example.test/file", tmp_path / "out" / "file.bin", sha(data), len(data), **kw)


def fast(**kw):
    return dict(sleep=lambda s: None, **kw)


def test_downloads_verifies_and_moves_the_file_into_place(tmp_path):
    p = part_for(tmp_path)
    seen = []
    installer.fetch(p, lambda d, t: seen.append((d, t)), server(DATA), **fast())
    assert p.target.read_bytes() == DATA and not p.target.with_name("file.bin.part").exists()
    assert seen[-1] == (len(DATA), len(DATA))


def test_resumes_from_the_part_file_with_a_range_request(tmp_path):
    p = part_for(tmp_path)
    p.target.parent.mkdir(parents=True)
    p.target.with_name("file.bin.part").write_bytes(DATA[:300_000])
    opener = server(DATA)
    installer.fetch(p, opener=opener, **fast())
    assert opener.calls["ranges"] == ["bytes=300000-"] and p.target.read_bytes() == DATA


def test_restarts_from_zero_if_the_server_ignores_range(tmp_path):
    p = part_for(tmp_path)
    p.target.parent.mkdir(parents=True)
    p.target.with_name("file.bin.part").write_bytes(DATA[:300_000])
    installer.fetch(p, opener=server(DATA, honour_range=False), **fast())
    assert p.target.read_bytes() == DATA


def test_a_dropped_connection_is_retried_quietly_and_resumes(tmp_path):
    p = part_for(tmp_path)
    retries = []
    opener = server(DATA, kill_after=200_000)
    installer.fetch(p, opener=opener, on_retry=lambda a, w, k: retries.append((a, k)), **fast())
    assert p.target.read_bytes() == DATA and retries == [(1, "offline")] and opener.calls["ranges"][1].startswith("bytes=")


def test_gives_up_after_the_quiet_retries_and_says_offline(tmp_path):
    p = part_for(tmp_path)
    retries = []
    with pytest.raises(FetchError) as err:
        installer.fetch(p, opener=server(DATA, fail_first=99), on_retry=lambda *a: retries.append(a), **fast())
    assert err.value.kind == "offline" and len(retries) == len(installer.RETRY_DELAYS) and "internet" in err.value.message


def test_a_wrong_checksum_is_never_kept_and_gets_one_clean_retry(tmp_path):
    p = part_for(tmp_path)
    p.sha256 = "0" * 64
    opener = server(DATA)
    with pytest.raises(FetchError) as err:
        installer.fetch(p, opener=opener, **fast())
    assert err.value.kind == "checksum" and not p.target.exists() and not p.target.with_name("file.bin.part").exists()
    assert opener.calls["n"] == 2


def test_a_part_file_that_is_already_whole_is_just_verified(tmp_path):
    p = part_for(tmp_path)
    p.target.parent.mkdir(parents=True)
    p.target.with_name("file.bin.part").write_bytes(DATA)
    opener = server(DATA)
    installer.fetch(p, opener=opener, **fast())
    assert opener.calls["n"] == 0 and p.target.read_bytes() == DATA


def test_http_416_means_the_part_is_complete(tmp_path):
    p = part_for(tmp_path)
    p.bytes = None  # size unknown, so only the server can say the part is whole
    p.target.parent.mkdir(parents=True)
    p.target.with_name("file.bin.part").write_bytes(DATA)

    def past_the_end(request, timeout=0):
        raise urllib.error.HTTPError("u", 416, "range", {}, None)
    installer.fetch(p, opener=past_the_end, **fast())
    assert p.target.read_bytes() == DATA


def test_disk_full_stops_at_once_without_retrying(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 1000)
    opener = server(DATA)
    with pytest.raises(FetchError) as err:
        installer.fetch(part_for(tmp_path), opener=opener, **fast())
    assert err.value.kind == "disk_full" and opener.calls["n"] == 0


def test_a_write_error_for_a_full_disk_is_classified(tmp_path):
    full = OSError(errno.ENOSPC, "No space left on device")
    with pytest.raises(FetchError) as err:
        installer.fetch(part_for(tmp_path), opener=server(DATA, fail_first=1, errors=full), **fast())
    assert err.value.kind == "disk_full"


def test_cancel_keeps_the_part_file_for_next_time(tmp_path):
    p = part_for(tmp_path)
    with pytest.raises(FetchError) as err:
        installer.fetch(p, opener=server(DATA), cancelled=lambda: True, **fast())
    assert err.value.kind == "cancelled" and p.target.with_name("file.bin.part").exists()


def test_a_zip_part_is_unpacked_to_an_executable(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("deno", b"#!/bin/sh\necho hi\n")
    blob = buf.getvalue()
    p = Part("https://example.test/deno.zip", tmp_path / "tools" / "deno", sha(blob), len(blob), unzip="deno")
    path = installer.fetch(p, opener=server(blob), **fast())
    installer._unzip(path, p)
    assert p.target.read_bytes().startswith(b"#!/bin/sh") and p.target.stat().st_mode & 0o111 and not path.exists()


def test_precheck_explains_a_full_disk_an_old_mac_and_an_unsupported_chip(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 500_000_000)
    kinds = [p["kind"] for p in installer.precheck(700_000_000, tmp_path, macos="11.6", machine="ppc")]
    assert kinds == ["macos", "chip", "disk"]
    monkeypatch.setattr(installer, "free_bytes", lambda path: 50_000_000_000)
    assert installer.precheck(700_000_000, tmp_path, macos="15.1", machine="arm64") == []


def test_install_emits_a_clean_event_stream_and_stops_at_the_first_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 50_000_000_000)
    a = Part("https://example.test/a", tmp_path / "a.bin", sha(DATA), len(DATA))
    b = Part("https://example.test/b", tmp_path / "b.bin", "0" * 64, len(DATA))
    steps = [installer.Step("a", "File A", [a]), installer.Step("b", "File B", [b]), installer.Step("c", "File C", [])]
    events = []
    ok = installer.install(events.append, steps, opener=server(DATA), sleep=lambda s: None)
    kinds = [e["event"] for e in events]
    assert not ok and kinds[0] == "plan" and kinds.count("step_done") == 1 and kinds[-2:] == ["step_error", "finished"]
    assert events[-2]["id"] == "b" and events[-2]["kind"] == "checksum" and events[-1] == {"event": "finished", "ok": False, "reason": "checksum"}
    progress = [e for e in events if e["event"] == "progress"]
    assert progress[0]["overall_total"] == 2 * len(DATA)


def test_install_stops_before_downloading_when_the_mac_cannot_take_it(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 10)
    events = []
    steps = [installer.Step("a", "File A", [Part("https://example.test/a", tmp_path / "a", sha(DATA), len(DATA))])]
    assert not installer.install(events.append, steps, opener=lambda *a, **k: pytest.fail("must not download"))
    assert [e["event"] for e in events] == ["plan", "precheck", "finished"] and events[1]["problems"][0]["kind"] == "disk"


def test_plan_lists_only_what_is_missing(tmp_path, monkeypatch):
    names = [s.id for s in installer.plan(only_missing=False)]
    assert names == ["ffprobe", "ffmpeg", "deno", "meaning-model", "whisper-model"]
    assert all(p.sha256 and p.url.startswith("https://") for s in installer.plan(only_missing=False) for p in s.parts)


def test_install_with_nothing_missing_finishes_at_once_without_checking_the_disk(monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 0)
    events = []
    assert installer.install(events.append, [])
    assert [e["event"] for e in events] == ["plan", "finished"] and events[-1]["ok"]


def test_the_plan_event_says_where_each_download_comes_from_and_why(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "free_bytes", lambda path: 50_000_000_000)
    events = []
    step = installer.Step("ffmpeg", "ffmpeg", [Part("https://example.test/f", tmp_path / "f", sha(DATA), len(DATA))])
    installer.install(events.append, [step], opener=server(DATA), sleep=lambda s: None)
    first = events[0]["steps"][0]
    assert first["source"] and "frames" in first["why"].lower() or "sound" in first["why"].lower()
