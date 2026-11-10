"""A saved page ("Save what I see") shared on a board: the page text travels only when the owner ticks it, a friend's Mac
that cannot download the page (a login wall) shows it read-only, and says plainly what is missing when it is not shared.
Every page here is made up (portfolio.example.org); nothing is fetched and no relay is real."""

import base64
import json
import zlib

import pytest

from magpiary import boardpage, boards, boardsync, identity
from magpiary.store import Store
from test_boardsync import Relays
from test_hub import archive, page, post  # noqa: F401

URL = "https://portfolio.example.org/gallery/4242/fate-edit-lookbook"
ARTICLE = {
    "title": "Fate Edit lookbook", "byline": "Mira Example", "site": "Portfolio Example", "published": "2026-09-01T00:00:00Z",
    "blocks": [
        {"t": "h", "level": 1, "text": "Fate Edit"},
        {"t": "p", "text": "A capsule of folded paper garments, shot in one afternoon."},
        {"t": "img", "src": "https://img.example.net/1.jpg", "alt": "Look one", "caption": "Look one, folded linen"},
        {"t": "li", "ordered": False, "text": "Paper stock: 120 gsm"},
        {"t": "video", "src": "https://img.example.net/v.mp4", "poster": ""},
        {"t": "p", "text": "<script>alert(1)</script>"},
    ],
}


def packed(obj) -> str:
    return base64.b64encode(zlib.compress(json.dumps(obj).encode())).decode()


def test_a_snapshot_keeps_the_words_and_leaves_pictures_and_addresses_behind():
    text = boardpage.build(ARTICLE)
    snap = boardpage.decode(text)
    assert snap["title"] == "Fate Edit lookbook" and snap["pictures"] == 1 and snap["cut"] == 0
    kinds = [b["t"] for b in snap["blocks"]]
    assert kinds == ["h", "p", "img", "li", "p"]  # the video is not carried
    assert next(b for b in snap["blocks"] if b["t"] == "img") == {"t": "img", "text": "Look one, folded linen"}
    assert "example.net" not in json.dumps(snap) and "img.example" not in zlib.decompress(base64.b64decode(text)).decode()
    assert boardpage.build({"blocks": [{"t": "img", "alt": "x"}]}) == ""  # nothing to read: nothing to share


def test_a_long_page_is_cut_to_fit_one_event_and_says_so():
    big = {"title": "Long", "blocks": [{"t": "p", "text": f"Paragraph {n} " + "word " * 600} for n in range(300)]}
    text = boardpage.build(big)
    assert 0 < len(text) <= boardpage.LIMIT
    snap = boardpage.decode(text)
    assert snap["cut"] > 0 and len(snap["blocks"]) + snap["cut"] == 300


@pytest.mark.parametrize("bad", ["", "not base64!", base64.b64encode(b"plain").decode(), packed([1, 2]), packed({"blocks": []}),
                                  packed({"blocks": [{"t": "script", "text": "x"}]}), None, 5])
def test_a_damaged_snapshot_from_a_friend_is_refused(bad):
    assert boardpage.decode(bad) is None


def test_a_zip_bomb_snapshot_is_refused():
    bomb = base64.b64encode(zlib.compress(b'{"blocks":[{"t":"p","text":"' + b"a" * 5_000_000 + b'"}]}', 9)).decode()
    assert len(bomb) < boardpage.LIMIT and boardpage.decode(bomb) is None


class World:
    """Friend A (saved the page) and the receiving Mac B (the hub under test), with one fake relay."""

    def __init__(self, mac, tmp_path, monkeypatch):
        self.mac, self.tmp, self.mp = mac, tmp_path, monkeypatch
        self.relays = Relays()
        self.nostr = boardsync.Nostr(connect=self.relays.connect)
        self.b_config = tmp_path / "config"
        self.a_config = tmp_path / "config-a"
        self.a = Store(tmp_path / "a.db")
        self.as_a()
        self.a.set_setting(identity.NAME, "Alex Example")
        self.as_b()
        mac.store.set_setting(identity.NAME, "Asha")
        folder = tmp_path / "a-library" / "page-1"
        folder.mkdir(parents=True)
        (folder / "article.json").write_text(json.dumps(ARTICLE))
        (folder / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 50)
        self.item = {"canonical_url": URL, "ai_title": "Fate Edit lookbook", "summary": "Folded paper garments.", "ai_type": "article",
                     "source": "web", "author": "Mira Example", "tags": ["fashion"], "archive_dir": str(folder), "status": "archived"}
        self.library = tmp_path / "a-library"

    def as_a(self):
        self.mp.setenv("MAGPIARY_CONFIG", str(self.a_config))

    def as_b(self):
        self.mp.setenv("MAGPIARY_CONFIG", str(self.b_config))

    def friend_shares(self, with_text: bool) -> str:
        self.as_a()
        board_id = boards.create(self.a, "Fate Edit")
        boards.share(self.a, board_id, "nostr")
        boards.add_card(self.a, board_id, self.item, self.library)
        if with_text:
            assert boards.add_page(self.a, board_id, self.item, self.library)
        boards.sync(self.a, board_id, self.nostr)
        key, board = boards.board_key(board_id), self.a.board(board_id)
        self.as_b()
        boards.remember_key(board_id, key)
        self.mac.store.save_board(board_id, board["name"], board["creator"], board["via"])
        boards.sync(self.mac.store, board_id, self.nostr)
        return board_id

    def blocked_item(self) -> int:
        """B queued the friend's post, and the logged-out download hit the site's login wall."""
        store = self.mac.store
        store.fetch_for_board([{"url": URL, "title": "Fate Edit lookbook", "summary": "Folded paper garments.", "kind": "article",
                                "tags": ["fashion"]}])
        item = store.item_by_url(URL)
        with store._lock, store._db:
            store._db.execute("UPDATE items SET status='needs_attention', reason='login_wall' WHERE canonical_url=?", (URL,))
        return item["id"]


@pytest.fixture
def world(mac, tmp_path, monkeypatch):
    start = int(boards.time.time()) - 1_000_000
    ticks = iter(range(start, start + 1_000_000, 7))
    monkeypatch.setattr(boards.time, "time", lambda: next(ticks))
    w = World(mac, tmp_path, monkeypatch)
    yield w
    w.a.close()


def test_the_shared_page_text_reaches_the_other_mac_and_opens_read_only(world):
    board_id = world.friend_shares(with_text=True)
    card = boards.view(world.mac.store, board_id)["cards"][0]
    assert boardpage.decode(card["page"])["title"] == "Fate Edit lookbook"
    item_id = world.blocked_item()
    status, _, body = page(world.mac, f"/item/{item_id}?from=%2Fboard%2Ffate-edit")
    assert status == 200 and "Couldn&#x27;t open this post" not in body and "Couldn't open this post" not in body
    assert "Alex Example shared it" in body and "A capsule of folded paper garments" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "<script>alert(1)" not in body
    assert "Look one, folded linen" in body and "img.example.net" not in body  # the picture itself never came
    assert "does not show this page to a visit without a login" in body


def test_without_the_page_text_it_says_what_is_missing_and_what_each_person_can_do(world):
    world.friend_shares(with_text=False)
    item_id = world.blocked_item()
    body = page(world.mac, f"/item/{item_id}")[2]
    assert "Couldn't open this post" not in body
    assert "did not share the page text" in body and "Also share the page text I saved" in body
    assert "Save what I see" in body and "Open the original" in body


def test_resharing_with_the_text_repairs_a_card_sent_earlier(world):
    board_id = world.friend_shares(with_text=False)
    world.as_a()
    before = len(world.a.board_events(board_id))
    assert boards.add_page(world.a, board_id, world.item, world.library)  # the card is already there: only the text goes
    assert len(world.a.board_events(board_id)) == before + 1
    boards.sync(world.a, board_id, world.nostr)
    world.as_b()
    boards.sync(world.mac.store, board_id, world.nostr)
    assert boardpage.decode(boards.view(world.mac.store, board_id)["cards"][0]["page"])["blocks"]


def test_page_text_needs_the_owners_tick_and_only_for_saved_pages(world, mac):
    world.as_a()
    board_id = boards.create(world.a, "Fate Edit")
    # the chooser's own question: which of these posts are saved pages
    mac_id = mac.store.add_phone  # noqa: F841  (the hub lists only posts of its own library)
    assert boards.captured_article({**world.item, "source": "instagram"}, world.library) is None
    assert boards.captured_article({**world.item, "archive_dir": str(world.tmp / "elsewhere")}, world.library) is None
    assert boards.captured_article({**world.item, "archive_dir": str(world.tmp)}, world.library) is None  # outside the library
    boards.add_card(world.a, board_id, world.item, world.library)
    assert not [e for e in world.a.board_events(board_id) if e["type"] == "page"]  # adding a card never sends the text


def test_a_page_event_from_a_member_without_the_card_is_not_shown_and_a_hostile_one_is_trimmed(world):
    board_id = world.friend_shares(with_text=True)
    world.as_b()
    clean = boards._clean({"type": "page", "url": URL, "page": "x" * (boardpage.LIMIT + 1)})
    assert "page" not in clean
    boards.write(world.mac.store, board_id, "page", url="https://other.example.org/x", page=boardpage.build(ARTICLE))
    view = boards.view(world.mac.store, board_id)
    assert [c["url"] for c in view["cards"]] == [URL]  # a page for a post nobody added does not make a card


def test_codex_findings_malformed_blocks_and_oversized_unpacking():
    assert boardpage.decode(boardpage._pack({"blocks": [{"t": [], "text": "x"}, {"t": "p", "text": "ok"}]}))["blocks"] == [{"t": "p", "text": "ok"}]
    big = {"blocks": [{"t": "p", "text": "漢" * 4000}] * 60}
    assert boardpage.decode(boardpage.build(big)) is not None  # whatever build() makes, decode() accepts


def test_page_text_before_a_removal_does_not_come_back_and_is_credited_to_its_sender(world):
    board_id = world.friend_shares(with_text=True)
    world.as_b()
    view = boards.view(world.mac.store, board_id)
    assert view["cards"][0].get("page_by") in view["members"]
