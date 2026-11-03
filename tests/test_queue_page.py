"""The queue page, seen over HTTP the way a browser on the Mac sees it."""

import http.client


from fakephone import Phone
from magpiary.queuepage import MAX_ROWS
from magpiary.worker import process_due

IG = "https://www.instagram.com"
A, B = f"{IG}/reel/AAAA111/", f"{IG}/reel/BBBB222/"
SHORT = "https://www.threads.com/share/ExampleShare3"


def get(mac, path="/queue", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", mac.port, timeout=10)
    conn.request("GET", path, headers={"Host": host or f"localhost:{mac.port}"})
    r = conn.getresponse()
    body = r.read().decode()
    conn.close()
    return r.status, dict(r.getheaders()), body


def test_an_empty_queue_says_so(mac):
    status, _, body = get(mac)
    assert status == 200 and "Nothing has arrived yet" in body


def test_each_item_shows_link_source_times_shared_phone_and_status(mac, phone):
    phone.run(A + "?igsh=x")
    phone.run(A)
    phone.run(B)
    status, _, body = get(mac)
    assert status == 200
    assert A in body and B in body and "igsh" not in body
    assert "Instagram" in body and "2×" in body and "1×" in body
    assert "Test iPhone" in body and "Saved" in body
    assert "2 items" in body


def test_newest_share_comes_first(mac, phone, clock):
    phone.run(A)
    clock.advance(60)
    phone.run(B)
    _, _, body = get(mac)
    assert body.index(B) < body.index(A)


def test_links_open_safely(mac, phone):
    phone.run(A)
    _, _, body = get(mac)
    assert f'href="{A}" rel="noopener noreferrer"' in body


def test_a_short_link_shows_its_progress_and_trouble(mac, phone, clock):
    phone.run(SHORT)
    assert "Looking up the full link" in get(mac)[2]
    process_due(mac.store, lambda url: (_ for _ in ()).throw(ConnectionError(url)), pause=lambda: None)
    _, _, body = get(mac)
    assert "Needs attention: The short link could not be opened" in body
    assert "network error" in body and "Will try again about" in body
    assert "1 need" in body


def test_when_the_retries_run_out_the_page_says_the_link_is_kept(mac, phone, clock):
    from magpiary.expand import RETRY_DELAYS_SECONDS
    phone.run(SHORT)
    fail = lambda url: (_ for _ in ()).throw(ConnectionError(url))
    for delay in RETRY_DELAYS_SECONDS:
        process_due(mac.store, fail, pause=lambda: None)
        clock.advance(delay + 1)
    process_due(mac.store, fail, pause=lambda: None)
    assert "Not trying again by itself; the link is kept." in get(mac)[2]


def test_values_from_phones_are_escaped(mac):
    _, key = mac.store.add_phone("<img src=x onerror=alert(1)>")
    Phone(mac, key).run(A)
    _, _, body = get(mac)
    assert "<img src=x" not in body and "&lt;img src=x" in body


def test_it_is_for_this_mac_only(mac, phone):
    phone.run(A)
    assert get(mac, host="evil.example:8765")[0] == 403
    assert get(mac, host=f"test-mac.local:{mac.port}")[0] == 403
    assert A not in get(mac, host="evil.example")[2]


def test_the_front_door_is_the_hub_and_pages_are_not_cached(mac):
    status, headers, body = get(mac, "/")
    assert status == 200 and "Your library is empty" in body
    assert get(mac)[1]["Cache-Control"] == "no-store"


def test_a_long_queue_is_capped(mac, phone):
    mac.store.receive(mac.store.phone_for_key(phone.key), [
        {"id": f"id-{n}", "url": f"{IG}/reel/X{n:05d}/"} for n in range(MAX_ROWS + 20)])
    _, _, body = get(mac)
    assert body.count("<tr><td") == MAX_ROWS
    assert f"Showing the newest {MAX_ROWS} of {MAX_ROWS + 20}" in body
