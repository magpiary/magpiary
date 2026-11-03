"""Boards in the hub (M9 task 7): the Boards view in Library, a board's page, adding posts, votes, a card opened,
taking a card off and removing a member."""

import json
import re

from magpiary import boards, boardsync
from test_boardsync import Relays
from test_hub import IG, YT, lib, page, post, request  # noqa: F401  (lib is a fixture)

def make(store, name, via="nostr"):
    """A board that is already shared (most tests are about syncing); a solo one comes from boards.create."""
    board_id = boards.create(store, name)
    boards.share(store, board_id, via)
    return board_id



def setup_hub(mac):
    relays = Relays()
    mac.server.hub.relay_connect = relays.connect
    mac.server.hub.sync_boards = mac.server.hub._sync_here  # no board lane in the test service
    return relays


def test_the_boards_view_makes_a_board_and_lists_it(mac):
    setup_hub(mac)
    body = page(mac, "/?view=boards")[2]
    assert 'data-view="boards" class="on"' in body and "No boards yet" in body and "/board/mock" in body
    status, headers, _ = post(mac, "/hub/boards/new", name="  Lisbon   trip ", next="/?view=boards")
    board_id = headers["Location"].rsplit("/", 1)[1].split("?")[0]
    assert status == 303 and mac.store.board(board_id)["name"] == "Lisbon trip"
    assert not mac.store.board(board_id)["shared"] and not mac.store.board(board_id)["synced_at"]  # solo: nothing synced
    body = page(mac, "/?view=boards")[2]
    assert "Lisbon trip" in body and 'href="/board/lisbon-trip"' in body  # its address is its name
    assert request(mac, "GET", f"/board/{board_id}")[1]["Location"] == "/board/lisbon-trip"
    # the first folder is an empty one that opens the make-or-join dialog; the boards follow it
    assert body.index('class="pile bpile bnew"') < body.index('href="/board/lisbon-trip"')
    assert 'Make a new board' in page(mac, "/?view=boards&make=choose")[2] and 'action="/hub/boards/join"' in page(mac, "/?view=boards&make=join")[2]
    assert 'action="/hub/boards/new"' in page(mac, "/?view=boards&make=new")[2]
    assert json.loads(request(mac, "GET", "/boards.json")[2]) == [{"id": board_id, "name": "Lisbon trip", "n": 0}]
    _, headers, _ = post(mac, "/hub/boards/new", name="   ", next="/?view=boards")
    assert "error=" in headers["Location"]
    post(mac, "/hub/boards/rename", board=board_id, name="Porto trip", next="/board/porto-trip")
    assert page(mac, "/board/porto-trip")[0] == 200
    assert request(mac, "GET", "/board/lisbon-trip")[1]["Location"] == "/board/porto-trip"  # the old name forwards
    second = make(mac.store, "Porto trip")
    assert 'href="/board/porto-trip-2"' in page(mac, "/?view=boards")[2] and second


def test_posts_go_on_a_board_from_the_library_and_open_as_cards(mac, lib):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    post(mac, "/hub/bulk", ids=f"{lib['ig']},{lib['yt']}", action="board", board=board_id, next="/")
    post(mac, "/hub/bulk", ids=f"{lib['ig']}", action="board", board=board_id, next="/")  # already there: not twice
    view = boards.view(mac.store, board_id)
    assert {c["url"] for c in view["cards"]} == {IG, YT} and len(mac.store.board_events(board_id)) == 4
    body = page(mac, f"/board/{board_id}")[2]
    assert body.count('<article class="mx') == 2 and "Add posts" in body and 'id="sizes"' in body
    assert f'href="/item/{lib["ig"]}"' in body  # a card opens like a library post...
    card = page(mac, f"/item/{lib['ig']}?frag=1&board={board_id}")[2]
    assert 'class="pctx board"' in card and "Take it off" in card and "Vote for it" in card  # ...with the board in the top bar
    assert "Open in my library" not in card and 'class="pctx board"' not in page(mac, f"/item/{lib['ig']}?frag=1")[2]

    post(mac, "/hub/boards/vote", board=board_id, url=IG, value="1", next=f"/board/{board_id}")
    assert next(c for c in boards.view(mac.store, board_id)["cards"] if c["url"] == IG)["score"] == 1
    post(mac, "/hub/boards/remove-card", board=board_id, url=YT, next=f"/board/{board_id}")
    assert [c["url"] for c in boards.view(mac.store, board_id)["cards"]] == [IG]

    panel = page(mac, f"/board/{board_id}?add=1")[2]
    assert "Add to the board" in panel and 'disabled checked' in panel  # what's already on it is ticked and fixed
    assert "Add to board…" in page(mac, f"/item/{lib['yt']}")[2]  # a post's … menu


def test_only_the_creator_sees_remove_on_members_and_the_example_board_writes_nothing(mac, lib, tmp_path, monkeypatch):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    friend = "f" * 64
    mac.store.add_board_event(board_id, friend, 1, 1, "profile", {"name": "Asha", "colour": "#2f6bff"}, "")
    body = page(mac, f"/board/{board_id}")[2]
    assert "bkick" not in body and f"who={friend}" in body  # no × beside a name: open the person first
    body = page(mac, f"/board/{board_id}?who={friend}")[2]
    assert "bkick" in body and "Remove Asha from the board?" in body and "Cards added" in body and "Last contribution" in body
    assert "bkick" not in page(mac, f"/board/{board_id}?who={boards.identity.public_key()}")[2]  # never yourself
    post(mac, "/hub/boards/remove-member", board=board_id, who=friend, next=f"/board/{board_id}")
    assert friend not in boards.view(mac.store, board_id)["members"]
    assert len(boards.board_keys(board_id)) == 2  # a new key after removing examplecreator

    before = len(mac.store.boards())
    mock = page(mac, "/board/mock")[2]
    assert "Example" in mock and "Asha" in mock and 'class="bkick"' not in mock and 'class="addposts"' not in mock
    assert len(mac.store.boards()) == before
    assert page(mac, "/board/0123456789abcdef")[0] == 404


def test_invite_shows_the_boards_code_on_the_board_page(mac):
    relays = setup_hub(mac)
    board_id = make(mac.store, "Food")
    assert 'action="/hub/boards/invite"' in page(mac, f"/board/{board_id}")[2]
    assert "Show the invite code" in page(mac, f"/board/{board_id}?invite=1")[2]  # not made until asked
    status, headers, _ = post(mac, "/hub/boards/invite", board=board_id, next=f"/board/{board_id}")
    assert headers["Location"] == f"/board/{board_id}?invite=1"  # the code never goes in an address
    shown = page(mac, headers["Location"])[2]
    code = re.search(r"MAG-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}", shown).group(0)
    assert "Share…" in shown and "Copy message" in shown and 'data-copywhat="Code"' in shown and "<svg" in shown
    assert f"http://localhost:8765/join/{code}" in shown and "For anyone you send it to" in shown and relays.events
    post(mac, "/hub/boards/invite", board=board_id, next=f"/board/{board_id}")
    assert code in page(mac, f"/board/{board_id}?invite=1")[2]  # pressing Invite again: the same code
    post(mac, "/hub/boards/new-code", board=board_id, next=f"/board/{board_id}")
    assert code not in page(mac, f"/board/{board_id}?invite=1")[2]
    settings = page(mac, "/settings/boards")[2]
    assert "Your boards" in settings and 'action="/hub/boards/join"' not in settings and "?invite=1" not in settings


def test_joining_by_link_and_by_code_and_an_offer_on_the_wall(mac):
    setup_hub(mac)
    join = page(mac, "/join/MAG-7K3P-QX9D-2HFW")[2]
    assert "Join a shared board" in join and 'value="MAG-7K3P-QX9D-2HFW"' in join
    assert page(mac, "/join/nonsense-code-x")[0] == 404
    _, headers, _ = post(mac, "/hub/boards/join", code="MAG-0000-0000-0000", next="/?view=boards")
    assert "error=No%20invite%20was%20found" in headers["Location"]
    assert "No invite was found" in page(mac, headers["Location"])[2]
    mac.store.save_offer("inv1", "0123456789abcdef", "Goa", "f" * 64)
    wall = page(mac, "/")[2]
    assert "invited you to “Goa”" in wall and "Not now" in wall
    post(mac, "/hub/boards/offer", invite="inv1", act="no", next="/")
    assert "invited you to" not in page(mac, "/")[2]


def test_where_new_boards_sync_is_one_setting_and_needs_a_bucket(mac, monkeypatch):
    setup_hub(mac)
    body = page(mac, "/?view=boards&make=new")[2]
    assert 'name="via"' not in body and "Sharing syncs through free public Nostr relays" in body
    post(mac, "/hub/boards/via", via="bucket", next="/settings/boards")
    assert mac.store.get_setting("board_via") == "bucket"
    _, headers, _ = post(mac, "/hub/boards/new", name="Still relays", next="/?view=boards")
    assert mac.store.board(headers["Location"].rsplit("/", 1)[1].split("?")[0])["via"] == "nostr"  # no bucket connected
    monkeypatch.setattr(boardsync, "load_bucket", lambda: {"provider": "b2", "bucket": "x"})
    assert "Sharing syncs through your own storage bucket" in page(mac, "/?view=boards&make=new")[2]
    assert 'value="bucket" class="on"' in page(mac, "/settings/boards")[2]


def test_a_post_shared_to_a_board_shows_at_once_while_it_is_read(mac, lib):
    setup_hub(mac)
    board_id = make(mac.store, "Coffee")
    sig = mac.store.progress_signature()
    mac.store.add_board_pending(board_id, IG)
    assert mac.store.progress_signature() != sig  # the open board page refreshes itself
    body = page(mac, f"/board/{board_id}")[2]
    assert 'class="mx waiting"' in body and "On its way" in body and "Nothing here yet" not in body
    assert f'href="/item/{lib["ig"]}"' in body
    assert boards.view(mac.store, board_id)["cards"] == []  # friends don't get it until it's read


def test_a_board_on_screen_syncs_every_30_seconds_not_every_15_minutes(mac, monkeypatch):
    from magpiary import hub

    calls = []
    mac.server.hub.sync_boards = lambda: calls.append(1)
    clock = [1000.0]
    monkeypatch.setattr(hub.time, "monotonic", lambda: clock[0])
    request(mac, "GET", "/activity.json")
    assert calls == []  # nothing about boards on screen
    request(mac, "GET", "/activity.json?boards=1")
    request(mac, "GET", "/activity.json?boards=1")
    assert calls == [1]
    clock[0] += hub.BOARD_WATCH_EVERY
    request(mac, "GET", "/activity.json?boards=1")
    assert calls == [1, 1]


def test_sync_now_on_a_board_syncs_it_there_and_names_the_relays_when_it_fails(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Trip")
    _, headers, _ = post(mac, "/hub/boards/sync", board=board_id, next=f"/board/{board_id}")
    assert headers["Location"].startswith(f"/board/{board_id}?note=Synced")
    assert mac.store.board(board_id)["synced_at"]

    def down(relay):
        raise OSError("no route")
    mac.server.hub.relay_connect = down
    boards.add_card(mac.store, board_id, {"canonical_url": IG, "title": "x"})
    _, headers, _ = post(mac, "/hub/boards/sync", board=board_id, next=f"/board/{board_id}")
    where = headers["Location"]
    assert where.startswith(f"/board/{board_id}?error=") and "damus" in where and "15%20minutes" not in where


def test_stickers_board_tags_faded_filters_and_the_live_add_search(mac, lib):
    from magpiary import stickers

    setup_hub(mac)
    board_id = make(mac.store, "Coffee corner")
    assert boards.view(mac.store, board_id)["sticker"] == "coffee"  # picked from the name, the same on every Mac
    body = page(mac, f"/board/{board_id}")[2]
    assert stickers.emoji("coffee") in body and "data-stickerpick" in body and "data-renamebtn" in body
    post(mac, "/hub/boards/rename", board=board_id, name="Coffee corner", sticker="🫖", next=f"/board/{board_id}")
    assert boards.view(mac.store, board_id)["sticker"] == "🫖"  # any emoji, from the Mac's emoji window
    colour = next(c for c in ("#00a37a", "#ff2e93") if c != boards.view(mac.store, board_id)["colour"])
    post(mac, "/hub/boards/rename", board=board_id, name="Coffee corner", sticker="tea<b>", colour=colour, next="/")
    v = boards.view(mac.store, board_id)
    assert v["sticker"] == "🫖" and v["colour"] == colour  # typed text is not a sticker; the colour is kept
    assert mac.store.board_events(board_id)[-1]["body"] == {"name": "Coffee corner", "colour": colour}

    post(mac, "/hub/bulk", ids=f"{lib['ig']},{lib['yt']}", action="board", board=board_id, next="/")
    wall = page(mac, "/?view=all")[2]
    assert wall.count('class="onb"') == 2 and "Coffee corner" in wall  # tagged in the library

    friend = "f" * 64
    mac.store.add_board_event(board_id, friend, 1, 1, "profile", {"name": "Asha"}, "")
    mac.store.add_board_event(board_id, friend, 2, 2, "add", {"url": IG, "title": "x"}, "")
    shared = page(mac, f"/board/{board_id}?only=shared")[2]
    assert shared.count('class="mx shared') == 1 and shared.count(" dim\"") == 1  # the other card fades, still there
    person = page(mac, f"/board/{board_id}?who={friend}")[2]
    assert 'bpwrap open' in person and "Votes given" in person and "Remove Asha" in person
    assert " dim\"" not in person  # opening a person doesn't filter the cards

    rows = request(mac, "GET", f"/board/{board_id}/pick?q=")[2].decode()
    assert rows.count('class="apick there"') == 2  # already on the board: ticked and fixed
    assert "Nothing matches" in request(mac, "GET", f"/board/{board_id}/pick?q=zzqqxx")[2].decode()


def test_friends_posts_download_for_playing_but_stay_out_of_the_library_and_away_from_ai(mac, lib, tmp_path):
    setup_hub(mac)
    board_id = make(mac.store, "Trip")
    friend, url = "f" * 64, "https://www.instagram.com/reel/FRIENDPOST/"
    mac.store.add_board_event(board_id, friend, 1, 1, "profile", {"name": "Asha"}, "")
    mac.store.add_board_event(board_id, friend, 2, 2, "add", {"url": url, "title": "x"}, "")
    body = page(mac, f"/board/{board_id}")[2]
    item = mac.store.get_item(url)
    assert item and item["shelf"] == "board" and item["media_only"] == 1 and item["status"] == "queued"
    assert body.count('class="bfaces"') == 1 and "Asha" in body  # who is on it, beside the name
    assert item["ai_status"] == "done" and item["ai_title"] == "x"  # the friend's card stands in for a summary
    with mac.store._lock:
        mac.store._db.execute("UPDATE items SET status='archived', archive_dir='/nowhere' WHERE canonical_url=?", (url,))
        mac.store._db.execute("UPDATE items SET senses_status='done', ai_status='done' WHERE canonical_url!=?", (url,))
    from magpiary import worker

    made, sent = [], []
    worker.brain_due(mac.store, tmp_path,
                     pause=lambda tier: None, prepare=lambda item, progress: made.append(item["canonical_url"]),
                     process=lambda item, key, progress: sent.append(item["canonical_url"]))
    assert url in made and url not in sent  # the transcript and frames are made here; nothing goes to the AI
    assert url not in {i["canonical_url"] for i in mac.store.hub_items("kept")}  # not in the library
    mac.store.add_link(url)  # saved on purpose later: a normal post from then on
    item = mac.store.get_item(url)
    assert item["shelf"] == "inbox" and item["media_only"] == 0


def test_a_solo_board_hides_sharing_until_switched_on_and_deleting_needs_the_tick(mac):
    setup_hub(mac)
    _, headers, _ = post(mac, "/hub/boards/new", name="Mine", next="/?view=boards")
    board_id = headers["Location"].rsplit("/", 1)[1].split("?")[0]
    wall = page(mac, "/?view=boards")[2]
    assert "Shared ·" not in wall and "members" not in wall
    solo = page(mac, f"/board/{board_id}")[2]
    assert "Share this board" in solo and "Only on this Mac" in solo and "/hub/boards/invite" not in solo
    assert "Delete this board" in solo and "Leave this board" not in solo
    post(mac, "/hub/boards/share", board=board_id, next=f"/board/{board_id}")
    shared = page(mac, f"/board/{board_id}")[2]
    assert "/hub/boards/invite" in shared and "Shared · 1" in page(mac, "/?view=boards")[2]
    _, headers, _ = post(mac, "/hub/boards/delete", board=board_id)
    assert "Tick%20the%20box" in headers["Location"] and mac.store.boards()
    post(mac, "/hub/boards/delete", board=board_id, ack="1")
    assert mac.store.boards() == [] and "Deleted boards · 1" in page(mac, "/?view=boards")[2]
    post(mac, "/hub/boards/restore", board=board_id)
    assert [b["id"] for b in mac.store.boards()] == [board_id]


def test_sharing_with_invite_goes_straight_to_the_invite_with_a_code_ready(mac):
    setup_hub(mac)
    _, headers, _ = post(mac, "/hub/boards/new", name="Trip", next="/?view=boards")
    board_id = headers["Location"].rsplit("/", 1)[1].split("?")[0]
    assert "Share and invite" in page(mac, f"/board/{board_id}?share=1")[2]
    _, headers, _ = post(mac, "/hub/boards/share", board=board_id, invite="1")
    assert headers["Location"].endswith("?invite=1&code=1")
    assert "data-auto" in page(mac, headers["Location"])[2]  # the dialog makes the code as it opens
    post(mac, "/hub/boards/invite", board=board_id, next=f"/board/{board_id}")
    assert "MAG-" in page(mac, f"/board/{board_id}?invite=1")[2]
    assert "Delete “Trip”?" in page(mac, f"/board/{board_id}?delete=1")[2]


def test_restoring_from_the_deleted_list_lands_on_the_boards_view_with_the_folder_marked(mac):
    setup_hub(mac)
    _, headers, _ = post(mac, "/hub/boards/new", name="Back", next="/?view=boards")
    board_id = headers["Location"].rsplit("/", 1)[1].split("?")[0]
    _, headers, _ = post(mac, "/hub/boards/delete", board=board_id, ack="1")
    assert headers["Location"].endswith("&gone=" + board_id) and 'data-gone="' in page(mac, headers["Location"])[2]
    _, headers, _ = post(mac, "/hub/boards/restore", board=board_id, next="/?view=boards")
    assert headers["Location"].endswith("&back=" + board_id) and 'data-back="1"' in page(mac, headers["Location"])[2]


def test_a_new_board_opens_with_the_first_visit_dialog_and_a_joined_one_with_a_shorter_one(mac):
    setup_hub(mac)
    _, headers, _ = post(mac, "/hub/boards/new", name="Trip", next="/?view=boards")
    assert headers["Location"].endswith("?welcome=1")
    body = page(mac, headers["Location"])[2]
    assert "Two ways to fill it" in body and "From your library" in body and "From your iPhone" in body
    assert "Share this board?" in body and 'data-step="2"' in body and "Not now" in body
    board_id = headers["Location"].rsplit("/", 1)[1].split("?")[0]
    short = page(mac, f"/board/{board_id}?welcome=join")[2]
    assert "You joined" in short and "Got it" in short and "Share this board?" not in short
    assert 'id="bskel"' in page(mac, "/?view=boards")[2]  # the board's frame, shown while its page loads


def test_the_first_visit_dialog_comes_with_the_first_board_only(mac):
    setup_hub(mac)
    _, headers, _ = post(mac, "/hub/boards/new", name="One", next="/?view=boards")
    assert headers["Location"].endswith("?welcome=1")
    _, headers, _ = post(mac, "/hub/boards/new", name="Two", next="/?view=boards")
    assert "welcome" not in headers["Location"] and mac.store.get_setting("board_welcome_seen") == "1"


def test_examplecreator_who_already_has_boards_never_gets_the_first_visit_dialog(mac):
    setup_hub(mac)
    boards.create(mac.store, "Older")
    _, headers, _ = post(mac, "/hub/boards/new", name="Newer", next="/?view=boards")
    assert "welcome" not in headers["Location"]


def test_a_long_board_shows_a_chunk_at_a_time_and_the_next_chunk_comes_on_request(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Long")
    friend = "f" * 64
    mac.store.add_board_event(board_id, friend, 1, 1, "profile", {"name": "Asha"}, "")
    for i in range(30):
        mac.store.add_board_event(board_id, friend, i + 2, 10 + i, "add",
                                  {"url": f"https://www.instagram.com/reel/AAAA{i:02d}/", "title": f"Card {i}"}, "")
    first = page(mac, f"/board/{board_id}")[2]
    assert first.count("<article") == 24 + 4 and "data-bmore" in first   # 24 cards, 4 placeholders in the loader
    rest = page(mac, f"/board/{board_id}?part=1")[2]
    assert rest.count("<article") == 6 and "data-bmore" not in rest and "<!doctype" not in rest


FRIEND = "f" * 64


def test_a_friends_profile_opens_from_their_face_with_about_links_and_topics(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    mac.store.add_board_event(board_id, FRIEND, 1, 1, "profile", {
        "name": "Asha", "colour": "#2f6bff", "about": "Designer who collects chairs.",
        "links": {"website": "asha.example", "instagram": "https://instagram.com/asha.makes/?igsh=abc", "github": "no way",
                  "x": "javascript:alert(1)"}, "topics": ["Furniture", "Travel"]}, "")
    body = page(mac, f"/board/{board_id}?member={FRIEND}")[2]
    assert 'aria-label="Profile: Asha"' in body and "Designer who collects chairs." in body
    assert '<span>Furniture</span>' in body and "Into" in body
    assert 'href="https://asha.example" target="_blank" rel="noopener noreferrer"' in body
    assert 'href="https://www.instagram.com/asha.makes"' in body  # a pasted address is cut down to the handle
    assert "javascript:" not in body.split("Profile: Asha")[1] and "github.com" not in body  # invalid links are dropped
    opened = page(mac, f"/board/{board_id}?who={FRIEND}")[2]
    assert f'class="bface pface" href="/board/{board_id}?member={FRIEND}"' in opened  # the faces by the title open it
    assert "Open profile" not in opened  # no extra button in the people list
    assert 'class="soc"' in body and 'class="pstub"' in body and "data-plook" not in body  # logos on links; the ticket stub
    assert 'class="dlg bmember"' not in page(mac, f"/board/{board_id}?member={'a' * 64}")[2]  # not a member: no dialog


def test_a_newer_profile_message_replaces_the_extras_so_a_cleared_field_clears(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    mac.store.add_board_event(board_id, FRIEND, 1, 1, "profile", {"name": "Asha", "about": "One", "topics": ["A"]}, "")
    mac.store.add_board_event(board_id, FRIEND, 2, 2, "profile", {"name": "Asha"}, "")
    m = boards.view(mac.store, board_id)["members"][FRIEND]
    assert m["about"] == "" and m["topics"] == [] and m["links"] == {}


def test_your_profile_is_resent_to_your_boards_only_when_it_changed(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    me = boards.identity.public_key()

    def sent() -> int:
        return sum(1 for ev in mac.store.board_events(board_id) if ev["member"] == me and ev["type"] == "profile")
    assert boards.republish_profile(mac.store) == 0 and sent() == 1  # nothing changed since the board was made
    post(mac, "/hub/profile/about", about="Collector of small shops", next="/settings/boards")
    assert sent() == 2 and mac.store.board_events(board_id)[-1]["body"]["about"] == "Collector of small shops"
    assert boards.republish_profile(mac.store) == 0 and sent() == 2


def test_settings_edits_about_links_and_topics_and_shows_how_friends_see_you(mac, monkeypatch):
    setup_hub(mac)
    monkeypatch.setattr(mac.store, "piles", lambda deleted=False: [
        {"id": 1, "name": "Design", "members": ["a", "b", "c"]}, {"id": 2, "name": "Coffee", "members": ["d"]},
        {"id": 3, "name": "Empty", "members": []}])
    body = page(mac, "/settings/profile")[2]
    assert "How friends see you" in body and "<span>Design</span>" in body and "<span>Empty</span>" not in body
    post(mac, "/hub/profile/links", website="me.example", instagram="@me.made", x="", github="me-codes", next="/settings/profile")
    assert boards.identity.profile(mac.store)["links"] == {"website": "https://me.example", "instagram": "me.made",
                                                           "github": "me-codes"}
    post(mac, "/hub/profile/topic", act="remove", topic="Coffee", next="/settings/profile")
    post(mac, "/hub/profile/topic", act="add", topic="Type design", next="/settings/profile")
    assert boards.identity.profile(mac.store)["topics"] == ["Design", "Type design"]
    post(mac, "/hub/profile/topic", act="add", topic="Coffee", next="/settings/profile")  # typing a pile's name puts it back
    assert boards.identity.profile(mac.store)["topics"] == ["Design", "Coffee", "Type design"]


def test_a_profile_shows_one_row_of_cards_newest_first_and_the_rest_behind_see_all(mac):
    setup_hub(mac)
    board_id = make(mac.store, "Food")
    mac.store.add_board_event(board_id, FRIEND, 1, 1, "profile", {"name": "Asha"}, "")
    for n in range(2, 12):  # ten cards, none with a picture
        mac.store.add_board_event(board_id, FRIEND, n, n, "add", {"url": f"https://x.com/a/status/{n}", "title": f"Post {n}",
                                                                   "kind": "tool", "source": "x"}, "")
    dialog = page(mac, f"/board/{board_id}?member={FRIEND}")[2].split('class="dlg bmember"')[1]
    tiles = dialog.split('data-clamp>')[1].split("</div>")[0]  # every card is there; CSS and the script keep it to one row
    assert tiles.count('class="ptile bare"') == 10 and tiles.index("Post 11") < tiles.index("Post 2<")  # newest first
    assert 'data-seeall hidden aria-expanded="false">See all 10<' in dialog  # the script shows it only when more than a row exists
