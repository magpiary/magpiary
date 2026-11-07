"""Media answers describe the file they send (one open file), carry a strong validator, and honour If-Range."""

import os

from test_hub import IG, archive, request

from magpiary.hub_media import MediaPages


def test_answer_follows_the_open_file_even_if_the_path_is_swapped(tmp_path):
    path = tmp_path / "media-01.mp4"
    path.write_bytes(b"0123456789")
    other = tmp_path / "new.mp4"
    other.write_bytes(b"ABCDEFGHIJKLMNOPQRST")
    with open(path, "rb") as f:
        response = MediaPages._ranged(f, path, "bytes=2-", "")
        os.replace(other, path)  # a conversion swaps the file after the headers were worked out
        source, start, length = response.stream
        source.seek(start)
        assert response.headers["Content-Range"] == "bytes 2-9/10"
        assert source.read(length) == b"23456789"


def test_media_has_a_strong_etag_and_if_range_is_honoured(mac, tmp_path):
    item_id, folder = archive(mac, tmp_path, IG, "instagram", {"media": ["media-01.mp4"]}, {"media-01.mp4": b"0123456789"})
    url = f"/media/{item_id}/media-01.mp4"
    status, headers, data = request(mac, "GET", url)
    etag = headers["ETag"]
    assert status == 200 and etag.startswith('"') and not etag.startswith("W/")
    status, _, data = request(mac, "GET", url, headers={"Range": "bytes=2-3", "If-Range": etag})
    assert status == 206 and data == b"23"
    status, _, data = request(mac, "GET", url, headers={"Range": "bytes=2-3", "If-Range": '"someone-elses"'})
    assert status == 200 and data == b"0123456789", "a different version: the whole file, not a slice of it"
    (folder / "media-01.mp4").write_bytes(b"xyz")  # the bytes change: the validator changes with them
    assert request(mac, "GET", url)[1]["ETag"] != etag
