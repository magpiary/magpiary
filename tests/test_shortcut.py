"""The generated Shortcut, checked as data. (Whether iOS runs it is checked on the phone, task 9.)"""

import plistlib
import re
from types import SimpleNamespace

import pytest

from fakephone import Phone
from magpiary.protocol import ACK
from magpiary import shortcut
from magpiary.shortcut import SLOT_RULES, share_shortcut

CONFIG = {"host": "test-mac.local", "port": 8765, "key": "KEY-abc_123", "home_wifi": "Example Net"}
NO_HOME = {k: v for k, v in CONFIG.items() if k != "home_wifi"}


def actions(config=CONFIG):
    return share_shortcut(config)["WFWorkflowActions"]


def ident(action):
    return action["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.")


def params(action):
    return action["WFWorkflowActionParameters"]


def test_it_is_a_share_sheet_shortcut_taking_links_and_text():
    wf = share_shortcut(CONFIG)
    assert wf["WFWorkflowTypes"] == ["ActionExtension"]
    assert {"WFURLContentItem", "WFStringContentItem"} <= set(wf["WFWorkflowInputContentItemClasses"])


def test_it_survives_being_written_as_a_shortcut_file():
    wf = share_shortcut(CONFIG)
    assert plistlib.loads(plistlib.dumps(wf, fmt=plistlib.FMT_BINARY)) == wf


def headers_of(action) -> dict:
    return {h["WFKey"]["Value"]["string"]: h["WFValue"]["Value"]
            for h in params(action)["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]}


def test_it_posts_to_this_mac_signed_never_with_the_key():
    import hashlib

    from magpiary.protocol import device_tag

    post = next(a for a in actions() if ident(a) == "downloadurl" and params(a)["WFHTTPMethod"] == "POST")
    assert params(post)["WFURL"] == "http://test-mac.local:8765/v1/items"
    sent = headers_of(post)
    assert set(sent) == {"X-Magpiary-Device", "X-Magpiary-Time", "X-Magpiary-Signature"}
    assert sent["X-Magpiary-Device"]["string"] == device_tag(hashlib.sha256(b"KEY-abc_123").hexdigest())
    assert "Authorization" not in repr(share_shortcut(CONFIG))


def test_the_key_itself_is_nowhere_in_the_shortcut():
    import hashlib

    wf = repr(share_shortcut(CONFIG))
    assert "KEY-abc_123" not in wf
    secret = hashlib.sha256(b"KEY-abc_123").hexdigest()
    assert wf.count(secret) == 2  # only in the two signing texts (the board list GET, the POST)
    requests = [a for a in actions() if ident(a) == "downloadurl"]
    assert len(requests) == 2 and all("X-Magpiary-Signature" in headers_of(a) for a in requests)


def test_what_the_phone_hashes_is_what_the_mac_checks(tmp_path):
    """Read the signing steps out of the Shortcut, do on the computer what the phone does, and send it to a Mac."""
    import hashlib

    from magpiary.protocol import device_tag
    from magpiary.store import Store

    acts = actions()
    texts = {params(a)["UUID"]: params(a)["WFTextActionText"]["Value"] for a in acts
             if ident(a) == "gettext" and isinstance(params(a)["WFTextActionText"], dict)}
    hashes = [a for a in acts if ident(a) == "hash"]
    assert {params(h)["WFHashType"] for h in hashes} == {"SHA256"}
    post_src = next(t for t in texts.values() if t["string"].count("|POST /v1/items|"))
    get_src = next(t for t in texts.values() if t["string"].count("|GET /v1/boards|"))
    store = Store(tmp_path / "m.db")
    phone, key = store.add_phone("Test phone")
    secret = hashlib.sha256(key.encode()).hexdigest()
    stamp = store._now().isoformat(timespec="seconds")
    body = b'{"items":[{"id":"1","url":"https://example.com/p/1"}]}'
    sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    obj = shortcut.OBJ

    def fill(src: dict, values: list) -> str:  # the phone fills each variable in order; the secret is the phone's own
        out = src["string"].replace(hashlib.sha256(b"KEY-abc_123").hexdigest(), secret)
        for v in values:
            out = out.replace(obj, v, 1)
        return out

    post_sig = sha(fill(post_src, [stamp, sha(body)]).encode())
    got, why = store.phone_for_signature(device_tag(secret), stamp, post_sig, "POST /v1/items", body)
    assert got and got.id == phone.id and why == ""
    get_sig = sha(fill(get_src, [stamp]).encode())
    assert store.phone_for_signature(device_tag(secret), stamp, get_sig, "GET /v1/boards", None)[0]
    caps = sha(fill(post_src, [stamp, sha(body).upper()]).encode())  # iOS may give the body hash in capitals
    assert store.phone_for_signature(device_tag(secret), stamp, caps, "POST /v1/items", body)[0]


def go_conditions(acts, upto=None):
    """Positions of the conditionals that test the send decision (the text the gate regex turns into @@go@@)."""
    return [n for n, a in enumerate(acts[:upto]) if ident(a) == "conditional"
            and params(a).get("WFConditionalActionString", {}).get("Value", {}).get("string") == "@@go@@"]


def test_when_the_send_decision_says_go_it_fetches_the_latest_boards_before_asking():
    acts = actions()
    get = next(n for n, a in enumerate(acts) if ident(a) == "downloadurl" and params(a)["WFHTTPMethod"] == "GET")
    assert params(acts[get])["WFURL"] == "http://test-mac.local:8765/v1/boards"
    gate = max(go_conditions(acts, get))
    ask = next(n for n, a in enumerate(acts) if ident(a) == "choosefromlist")
    saves = [n for n, a in enumerate(acts) if ident(a) == "documentpicker.save"
             and params(a)["WFFileDestinationPath"] == "magpiary-boards.txt"]
    assert gate < get < saves[0] < ask  # only when sending, and saved before the question reads it


def test_the_outbox_is_blanked_only_inside_the_ack_check():
    acts = actions()
    post = next(n for n, a in enumerate(acts) if ident(a) == "downloadurl" and params(a)["WFHTTPMethod"] == "POST")
    start = next(n for n, a in enumerate(acts) if n > post and ident(a) == "conditional"
                 and params(a).get("WFControlFlowMode") == 0
                 and params(a).get("WFConditionalActionString", {}).get("Value", {}).get("string") == ACK)
    end = next(n for n in range(start, len(acts)) if ident(acts[n]) == "conditional"
               and params(acts[n]).get("WFControlFlowMode") == 1
               and params(acts[n])["GroupingIdentifier"] == params(acts[start])["GroupingIdentifier"])
    saves = [n for n, a in enumerate(acts) if ident(a) == "documentpicker.save"
             and params(a)["WFFileDestinationPath"] == "magpiary-outbox.txt"]
    assert len(saves) == 3   # save the queue, save it again with a board choice, then blank it
    assert saves[0] < saves[1] < start < saves[2] < end
    lists = [n for n, a in enumerate(acts) if ident(a) == "documentpicker.save"
             and params(a)["WFFileDestinationPath"] == "magpiary-boards.txt"]
    assert len(lists) == 2 and start < lists[1] < end  # kept only from replies the Mac sent


def test_the_board_question_is_asked_only_with_a_link_and_library_comes_first():
    acts = actions()
    link = next(n for n, a in enumerate(acts) if ident(a) == "conditional" and params(a).get("WFControlFlowMode") == 0
                and params(a).get("WFConditionalActionString", {}).get("Value", {}).get("string") == "http")
    ends = [n for n, a in enumerate(acts) if ident(a) == "conditional" and params(a).get("WFControlFlowMode") == 2
            and params(a)["GroupingIdentifier"] == params(acts[link])["GroupingIdentifier"]]
    ask = next(n for n, a in enumerate(acts) if ident(a) == "choosefromlist")
    assert link < ask < ends[0]
    texts = [a for a in acts if ident(a) == "gettext" and isinstance(params(a)["WFTextActionText"], dict)]
    menu = next(a for a in texts if "Just my library" in params(a)["WFTextActionText"]["Value"]["string"])
    assert params(menu)["WFTextActionText"]["Value"]["string"].startswith("Just my library\n")
    first_save = next(n for n, a in enumerate(acts) if ident(a) == "documentpicker.save")
    choice = next(n for n, a in enumerate(acts) if ident(a) == "gettext" and isinstance(params(a)["WFTextActionText"], dict)
                  and '"attach":1' in params(a)["WFTextActionText"]["Value"]["string"])
    assert first_save < link < ask < choice  # the post is queued before any question or request
    joined = next(a for a in acts if ident(a) == "text.replace" and params(a)["WFReplaceTextReplace"] == ",")
    assert params(joined)["WFInput"]["Value"]["attachmentsByRange"]  # sends the queue as it stands
    assert {"Type": "Variable", "VariableName": "outbox"} in params(joined)["WFInput"]["Value"]["attachmentsByRange"].values()


def test_nothing_is_ever_deleted():
    assert not any("delete" in ident(a) for a in actions())


SLOT = "202610272214a"


def gate_text(wifi, mode, shared, config=CONFIG, marker="", slot=SLOT, token="@@go@@"):
    """What the phone's gate text becomes, run through the same regex the Shortcut uses (Python's engine reads it alike).
    `marker` is what the try note file holds (what an unanswered try left behind), `slot` the current 5-minute slot."""
    acts = actions(config)
    replace = next(a for a in acts if ident(a) == "text.replace" and params(a)["WFReplaceTextReplace"] == token)
    text = f"{wifi}\u00a7{mode}\u00a7{shared}\u00a7{marker}\u00a7{wifi}\u00a6{slot}\u00a7"
    return re.sub(params(replace)["WFReplaceTextFind"], token, text, flags=re.S)


def test_with_a_home_network_it_decides_before_sending():
    acts = actions()
    assert any(ident(a) == "getwifi" for a in acts)
    first_post = next(n for n, a in enumerate(acts) if ident(a) == "downloadurl")
    assert next(n for n, a in enumerate(acts) if ident(a) == "getwifi") < first_post
    post = next(n for n, a in enumerate(acts) if ident(a) == "downloadurl" and params(a)["WFHTTPMethod"] == "POST")
    gates = go_conditions(acts)
    assert len(gates) == 2 and gates[0] < first_post and gates[1] < post  # the board list fetch and the send each wait for it


LINK = "https://www.instagram.com/reel/Example0020/"


@pytest.mark.parametrize("wifi, mode, shared, goes", [
    ("Example Net", "home", LINK, True),            # on the home Wi-Fi
    ("example net 5G", "", LINK, True),             # the same Wi-Fi's other band, any case; no mode learned yet
    ("Cafe Wi-Fi", "home", LINK, False),         # away, Home only: queue
    ("Cafe Wi-Fi", "", LINK, False),             # away, nothing learned yet: queue
    ("Cafe Wi-Fi", "any", LINK, True),           # away, Any Wi-Fi: try
    ("Cafe Wi-Fi", "any\n", LINK, True),         # the saved file may end with a newline
    ("", "any", LINK, False),                    # mobile data (no Wi-Fi name): queue even in Any Wi-Fi
    ("Cafe Wi-Fi", "home", "", True),            # run by hand with nothing shared: Send now
    ("", "home", "", True),                      # Send now works from anywhere
])
def test_the_send_decision(wifi, mode, shared, goes):
    assert ("@@go@@" in gate_text(wifi, mode, shared)) is goes


@pytest.mark.parametrize("config", [CONFIG, NO_HOME], ids=["home set", "no home"])
@pytest.mark.parametrize("wifi, marker_slot, shared, goes", [
    ("Cafe", SLOT, LINK, False),              # the last try on this network, in this slot, never got an answer
    ("Cafe", "202610272209b", LINK, True),    # an older slot: try again
    ("Cafe", None, LINK, True),               # no note: try
    ("Cafe", SLOT, "", True),                 # Send now ignores the note
])
def test_a_try_that_got_no_answer_blocks_the_same_network_in_the_same_slot(config, wifi, marker_slot, shared, goes):
    wifi = "Example Net" if config is CONFIG else wifi  # the example network is blocked too once a try there failed
    marker = "" if marker_slot is None else f"{wifi}\u00a6{marker_slot}"
    mode = "any"
    assert ("@@go@@" in gate_text(wifi, mode, shared, config, marker)) is goes


def test_a_note_from_another_network_does_not_block_this_one():
    assert "@@go@@" in gate_text("Cafe", "any", LINK, NO_HOME, marker=f"Other Wi-Fi\u00a6{SLOT}")


def test_the_blocked_message_is_chosen_only_when_blocked():
    assert "@@blk@@" in gate_text("Cafe", "any", LINK, NO_HOME, marker=f"Cafe\u00a6{SLOT}", token="@@blk@@")
    assert "@@blk@@" not in gate_text("Cafe", "any", LINK, NO_HOME, marker="", token="@@blk@@")
    assert "@@blk@@" not in gate_text("Cafe", "any", LINK, NO_HOME, marker="Cafe\u00a6202610272209b", token="@@blk@@")


def test_every_try_leaves_a_note_first_and_clears_it_when_the_mac_answers():
    acts = actions()
    note = [n for n, a in enumerate(acts) if ident(a) == "documentpicker.save" and params(a)["WFFileDestinationPath"] == "magpiary-try.txt"]
    gets = [n for n, a in enumerate(acts) if ident(a) == "downloadurl"]
    assert len(note) == 4 and len(gets) == 2
    for first, answer in zip(gets, ("detect.dictionary", "detect.dictionary")):
        assert note[0 if first == gets[0] else 2] < first < note[1 if first == gets[0] else 3]
    texts = [params(a)["WFTextActionText"] for a in acts if ident(a) == "gettext" and "WFTextActionText" in params(a)]
    assert " " in texts  # the clearing note is a blank


def test_the_blocked_message_says_so_and_points_to_send_now():
    notes = [params(a)["WFNotificationActionBody"] for a in actions() if ident(a) == "notification"]
    assert any("wasn't reachable on this Wi-Fi" in n and "run Magpiary" in n for n in notes if isinstance(n, str))


def test_a_wifi_name_with_odd_characters_still_matches_only_itself():
    config = {**CONFIG, "home_wifi": "Bob's (2.4) Wi-Fi+"}
    assert "@@go@@" in gate_text("Bob's (2.4) Wi-Fi+", "home", LINK, config)
    assert "@@go@@" not in gate_text("Bobs 24 WiFi", "home", LINK, config)


def test_the_mode_the_mac_sends_is_saved_next_to_the_boards():
    acts = actions()
    saves = [params(a)["WFFileDestinationPath"] for a in acts if ident(a) == "documentpicker.save"]
    assert saves.count("magpiary-wifi.txt") == 2  # from a send reply, and from the boards fetch
    keys = [params(a)["WFDictionaryKey"] for a in acts if ident(a) == "getvalueforkey"]
    assert keys.count("wifi") == 2


@pytest.mark.parametrize("wifi, mode, shared, goes", [
    ("Any Cafe", "", LINK, True),        # never heard from the Mac yet: any Wi-Fi
    ("Any Cafe", "any", LINK, True),
    ("Any Cafe", "any\n", LINK, True),
    ("Any Cafe", "home", LINK, False),   # the Mac says home, and there is no home name to match: it waits
    ("", "any", LINK, False),            # mobile data: queue
    ("", "", LINK, False),
    ("", "", "", True),                  # Send now
])
def test_without_a_home_network_it_sends_on_any_wifi_only(wifi, mode, shared, goes):
    assert ("@@go@@" in gate_text(wifi, mode, shared, NO_HOME)) is goes


def test_without_a_home_network_it_still_decides_before_sending():
    acts = actions(NO_HOME)
    assert any(ident(a) == "getwifi" for a in acts)
    post = next(n for n, a in enumerate(acts) if ident(a) == "downloadurl" and params(a)["WFHTTPMethod"] == "POST")
    assert len(go_conditions(acts)) == 2 and max(go_conditions(acts)) < post
    notes = [params(a)["WFNotificationActionBody"] for a in acts if ident(a) == "notification"]
    assert "Saved. It will send when you're on Wi-Fi." in notes and "Saved. It will send when you're home." not in notes


def test_every_notification_is_titled_magpiary():
    notes = [a for a in actions() if ident(a) == "notification"]
    assert notes and all(params(a)["WFNotificationActionTitle"] == "Magpiary" for a in notes)


SAMPLES = [
    ("https://www.instagram.com/reel/AAAA111/?igsh=abc&utm_source=ig_web_copy_link", "https://www.instagram.com/reel/AAAA111/"),
    ("Look at this https://www.instagram.com/reel/AAAA111/?igsh=zzz\nthanks", "https://www.instagram.com/reel/AAAA111/"),
    ("https://www.threads.com/@examplecreator/post/CCCC333?xmt=AQ#top", "https://www.threads.com/@examplecreator/post/CCCC333"),
    ("https://www.youtube.com/watch?v=Example0005&si=track&t=42s", "https://www.youtube.com/watch?v=Example0005"),
    ("https://youtu.be/Example0006?si=track", "https://youtu.be/Example0006"),
    ("https://x.com/examplecreator/status/185?s=46&t=abc", "https://x.com/examplecreator/status/185"),
    ("no link here", "no link here"),
]


@pytest.mark.parametrize("shared, expected", SAMPLES)
def test_the_phone_side_cleaning_in_the_shortcut_does_what_the_fake_phone_does(shared, expected):
    """The three Replace Text actions, applied in order, match the harness the receiver tests rely on."""
    text = shared
    for a in actions()[:3]:
        assert ident(a) == "text.replace"
        text = re.sub(params(a)["WFReplaceTextFind"], params(a)["WFReplaceTextReplace"].replace("$1", r"\1"), text)
    assert text == expected == Phone.clean(shared)


def slot_of(minute_text, wait):
    """Run the Shortcut's own slot steps (Replace Text, regular expression) over yyyyMMddHHmm."""
    acts = actions({**NO_HOME, "retry_wait": wait})
    finds = {f for f, _ in SLOT_RULES[wait]}
    steps = [a for a in acts if ident(a) == "text.replace" and isinstance(params(a)["WFReplaceTextFind"], str)
             and params(a)["WFReplaceTextFind"] in finds]
    text = minute_text
    for a in steps:
        text = re.sub(params(a)["WFReplaceTextFind"], params(a)["WFReplaceTextReplace"], text)
    return text


@pytest.mark.parametrize("wait, same, different", [
    (5, [("0", "4")], [("4", "5"), ("9", "10")]),
    (15, [("0", "14"), ("15", "29"), ("30", "44"), ("45", "59")], [("14", "15"), ("29", "30"), ("44", "45"), ("59", "00")]),
    (30, [("0", "29"), ("30", "59")], [("29", "30")]),
    (60, [("0", "59")], []),
])
def test_the_slot_lasts_as_long_as_the_wait_chosen(wait, same, different):
    stamp = lambda hh, mm: f"2026102722{int(mm):02d}" if hh == 22 else f"2026102723{int(mm):02d}"
    for low, high in same:
        assert slot_of(stamp(22, low), wait) == slot_of(stamp(22, high), wait)
    for low, high in different:
        hour_low, hour_high = (22, 22) if int(high) > int(low) else (22, 23)
        assert slot_of(stamp(hour_low, low), wait) != slot_of(stamp(hour_high, high), wait)
    if wait == 60:
        assert slot_of(stamp(22, 5), wait) != slot_of(stamp(23, 5), wait)


def test_an_unknown_wait_and_no_wait_fall_back_to_fifteen_minutes():
    for config in ({**NO_HOME, "retry_wait": 7}, NO_HOME):
        finds = [params(a)["WFReplaceTextFind"] for a in actions(config) if ident(a) == "text.replace"]
        assert "(?:0[0-9]|1[0-4])$" in finds and "[0-4]$" not in finds


def test_a_failed_signing_reports_the_real_reason_not_the_macos_noise(monkeypatch):
    noise = 'ERROR: Unrecognized attribute string flag \'?\' in attribute string "T@"NSString",?,R,C" for property debugDescription\n' * 6
    monkeypatch.setattr(shortcut.time, "sleep", lambda s: None)
    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=noise + "Error: Couldn't communicate with a helper application.\n"))
    with pytest.raises(RuntimeError) as raised:
        shortcut.sign({"WFWorkflowActions": []})
    assert "helper application" in str(raised.value) and "Unrecognized" not in str(raised.value)
