"""Behaviour at the storage and media seams before the cleanup moves code."""

import json

import pytest
from test_hub import IG, archive, request

from magpiary.store import Store


@pytest.fixture
def store(tmp_path, clock):
    saved = Store(tmp_path / "chat.db", clock.now)
    yield saved
    saved.close()


def test_chat_limits_keep_the_latest_messages_in_conversation_order(store):
    ids = [store.ask_add("pile:1", "user", str(n), {"n": n}) for n in range(4)]
    other = store.ask_add("pile:2", "assistant", "Other place")
    thread = store.ask_thread("pile:1", limit=2)
    assert [m["id"] for m in thread] == ids[-2:]
    assert [m["meta"] for m in thread] == [{"n": 2}, {"n": 3}]
    assert store.ask_message(other)["scope"] == "pile:2"
    store.ask_clear("pile:1")
    assert store.ask_thread("pile:1") == []
    assert store.ask_message(ids[0]) is None
    assert store.ask_message(other)["meta"] == {}


def test_only_answered_chats_are_kept_and_their_metadata_survives_resume(store):
    scope = "pile:1"
    store.ask_add(scope, "user", "  A question\nwith spaces  ")
    assert store.ask_end(scope, "Recipes") is None
    assert store.ask_sessions() == []
    assert store.ask_thread(scope) == []
    store.ask_add(scope, "user", "  A question\nwith spaces  ")
    store.ask_add(scope, "assistant", "An answer", {"cites": [3], "tokens": 42})
    before = store.ask_thread(scope)
    session_id = store.ask_end(scope, "Recipes")
    session = store.ask_session(session_id)
    assert session["title"] == "A question with spaces"
    assert session["label"] == "Recipes" and session["count"] == 2
    store.ask_session_pin(session_id, True)
    assert store.ask_sessions()[0]["pinned"] == 1
    store.ask_add(scope, "user", "A newer question")
    store.ask_add(scope, "assistant", "A newer answer")
    assert store.ask_session_resume(session_id, "Current place") == scope
    assert [
        {k: m[k] for k in ("role", "text", "meta", "at")}
        for m in store.ask_thread(scope)
    ] == session["messages"]
    assert store.ask_thread(scope)[0]["at"] == before[0]["at"]
    assert store.ask_session(session_id) is None
    kept = store.ask_sessions()
    assert len(kept) == 1 and kept[0]["title"] == "A newer question"
    assert kept[0]["label"] == "Current place"
    store.ask_session_delete(kept[0]["id"])
    assert store.ask_sessions() == []
    assert store.ask_session_resume(999999) is None


def test_chat_usage_and_notes_stay_separate_from_chat_deletion(store):
    store.ask_add("pile:1", "user", "Question")
    store.ask_usage_add("pile:1", "key", "small", 10, 3, 0.25)
    store.ask_usage_add("pile:2", "key", "small", 20, 4, 0.5)
    store.ask_usage_add("pile:1", "codex", "luna", 30, 5)
    store.ask_note_add("pile:1", "First note")
    store.ask_note_add("pile:1", "Second note")
    store.ask_note_add("pile:2", "Other note")
    store.ask_clear("pile:1")
    assert store.ask_usage_since("2000-01-01") == [
        {
            "engine": "codex",
            "questions": 1,
            "tokens_in": 30,
            "tokens_out": 5,
            "cost": 0.0,
        },
        {
            "engine": "key",
            "questions": 2,
            "tokens_in": 30,
            "tokens_out": 7,
            "cost": 0.75,
        },
    ]
    notes = store.ask_notes("pile:1")
    assert [n["text"] for n in notes] == ["Second note", "First note"]
    store.ask_note_delete(notes[0]["id"])
    assert [n["text"] for n in store.ask_notes("pile:1")] == ["First note"]
    assert [n["text"] for n in store.ask_notes("pile:2")] == ["Other note"]


@pytest.mark.parametrize(
    ("byte_range", "status", "body", "content_range"),
    [
        ("bytes=2-999", 206, b"23456789", "bytes 2-9/10"),
        ("bytes=3-", 206, b"3456789", "bytes 3-9/10"),
        ("bytes=-99", 206, b"0123456789", "bytes 0-9/10"),
        ("bytes=5-3", 416, b"", "bytes */10"),
        ("bytes=-0", 416, b"", "bytes */10"),
        ("bytes=", 200, b"0123456789", None),
        ("bytes=0-1,4-5", 200, b"0123456789", None),
    ],
)
def test_media_range_edge_cases(mac, tmp_path, byte_range, status, body, content_range):
    item_id, _ = archive(
        mac,
        tmp_path,
        IG,
        "instagram",
        {"media": ["media-01.mp4"]},
        {"media-01.mp4": b"0123456789"},
    )
    actual, headers, data = request(
        mac, "GET", f"/media/{item_id}/media-01.mp4", headers={"Range": byte_range}
    )
    assert (actual, data, headers.get("Content-Range")) == (status, body, content_range)
    if status != 416:
        assert headers["Accept-Ranges"] == "bytes"
        assert headers["X-Content-Type-Options"] == "nosniff"


def test_current_post_uses_key_points_without_the_retired_dot_timeline(mac, tmp_path):
    item_id, folder = archive(
        mac,
        tmp_path,
        IG,
        "instagram",
        {"media": ["media-01.mp4"], "duration": 30},
        {"media-01.mp4": b"video"},
    )
    (folder / "record.json").write_text(
        json.dumps(
            {
                "title": "Pasta",
                "summary": "Cook it",
                "type": "recipe",
                "key_points": [{"at": "0:08", "text": "Add the egg"}],
            }
        )
    )
    for suffix in ("", "?frag=1"):
        status, _, body = request(mac, "GET", f"/item/{item_id}{suffix}")
        assert status == 200 and b"Add the egg" in body and b'data-t="0:08"' in body
        assert b'class="tdot"' not in body and b'class="tl"' not in body


def test_media_cannot_follow_a_symlink_out_of_its_archive(mac, tmp_path):
    item_id, folder = archive(mac, tmp_path, IG, "instagram", {})
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    (folder / "media-01.mp4").symlink_to(outside)
    assert request(mac, "GET", f"/media/{item_id}/media-01.mp4")[0] == 404


def test_an_archive_outside_the_configured_library_is_not_served(mac, tmp_path):
    item_id, _ = archive(mac, tmp_path, IG, "instagram", {}, {"media-01.mp4": b"video"})
    mac.server.hub.library = tmp_path / "another-library"
    assert request(mac, "GET", f"/media/{item_id}/media-01.mp4")[0] == 404


def test_range_requests_do_not_generate_thumbnails(mac, tmp_path, monkeypatch):
    from magpiary import thumbs

    def no_thumbnail(*args):
        pytest.fail("a ranged response must serve the original file")

    monkeypatch.setattr(thumbs, "small", no_thumbnail)
    item_id, _ = archive(mac, tmp_path, IG, "instagram", {}, {"media-01.mp4": b"video"})
    status, headers, data = request(
        mac,
        "GET",
        f"/media/{item_id}/media-01.mp4?w=600",
        headers={"Range": "bytes=1-2"},
    )
    assert (status, data) == (206, b"id")
    assert headers["Cache-Control"] == "private, max-age=3600"


def test_profile_photo_response_and_missing_photo(mac, tmp_path, monkeypatch):
    from magpiary import identity

    photo = tmp_path / "photo.jpg"
    monkeypatch.setattr(identity, "photo_path", lambda: photo)
    assert request(mac, "GET", "/profile/photo.jpg")[0] == 404
    photo.write_bytes(b"jpeg")
    status, headers, data = request(mac, "GET", "/profile/photo.jpg")
    assert (status, data) == (200, b"jpeg")
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["Cache-Control"] == "private, max-age=31536000"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("failure", [OSError, RuntimeError])
def test_preview_fetch_failures_keep_the_optional_card_fallback(
    monkeypatch, failure, caplog
):
    from magpiary import ask_cards

    def failed_get(*args):
        raise failure("private response detail")

    monkeypatch.setattr(ask_cards.icons, "fetch", lambda *args: None)
    caplog.set_level("DEBUG", logger="magpiary.ask_cards")
    assert (
        ask_cards.card("https://example.com/page", failed_get, public=lambda host: True)
        is None
    )
    assert f"Preview page or image unavailable ({failure.__name__})" in caplog.text
    assert (
        "private response detail" not in caplog.text
        and "example.com" not in caplog.text
    )


def test_a_preview_keeps_its_title_when_the_optional_icon_fetch_fails(
    monkeypatch, caplog
):
    from magpiary import ask_cards

    def failed_icon(*args):
        raise OSError("private response detail")

    monkeypatch.setattr(ask_cards.icons, "fetch", failed_icon)
    caplog.set_level("DEBUG", logger="magpiary.ask_cards")
    result = ask_cards.card(
        "https://example.com/page",
        lambda *args: (200, "https://example.com/page", b"<title>Example</title>"),
        public=lambda host: True,
    )
    assert result["title"] == "Example" and result["img"] == ""
    assert "Preview icon unavailable (OSError)" in caplog.text
    assert (
        "private response detail" not in caplog.text
        and "example.com" not in caplog.text
    )


def test_search_suggestions_remain_optional_when_the_vocabulary_is_unavailable(
    store, monkeypatch, caplog
):
    from types import SimpleNamespace

    def unavailable(*args):
        raise RuntimeError("private database detail")

    caplog.set_level("DEBUG", logger="magpiary.store")
    with monkeypatch.context() as patch:
        patch.setattr(store, "_db", SimpleNamespace(execute=unavailable))
        assert store.did_you_mean("recpie") == ""
    assert "Search vocabulary unavailable (RuntimeError)" in caplog.text
    assert "private database detail" not in caplog.text and "recpie" not in caplog.text
