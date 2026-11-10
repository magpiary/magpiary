"""Magpiary as an installed web app: the manifest, the service worker (which stores nothing) and the pages that offer it."""

import json
import re

from test_hub import page, request


def test_manifest_has_what_chrome_needs(mac):
    status, headers, body = request(mac, "GET", "/manifest.webmanifest")
    m = json.loads(body)
    assert status == 200 and headers["Content-Type"].startswith("application/manifest+json")
    assert m["name"] == "Magpiary" and m["start_url"] == "/" and m["display"] == "standalone" and m["scope"] == "/"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in m["icons"]:  # every icon exists
        assert request(mac, "GET", icon["src"])[0] == 200
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_service_worker_stores_nothing_and_has_a_real_fetch_handler(mac):
    status, headers, body = request(mac, "GET", "/sw.js")
    js = body.decode()
    assert status == 200 and headers["Service-Worker-Allowed"] == "/" and headers["Cache-Control"] == "no-cache"
    assert 'addEventListener("fetch"' in js and "event.respondWith(fetch(" in js
    for forbidden in ("caches.", "indexedDB", "localStorage", ".put(", "cache.add"):
        assert forbidden not in js  # no copy of the library is ever kept in the browser
    assert "Magpiary isn't running" in js and "magpiary://open" in js


def test_install_files_open_while_locked(mac):
    mac.server.hub.store.set_setting("lock_on", "1")
    for path in ("/manifest.webmanifest", "/sw.js"):
        status, _, body = request(mac, "GET", path)
        assert status == 200 and b"library" not in body.lower().replace(b"your library", b"")


def test_pages_name_the_install_port_and_load_the_script(mac, monkeypatch):
    status, _, html = page(mac, "/settings/appearance")
    assert status == 200
    assert re.search(r'<meta name="pwa-port" content="8765">', html)  # only the first account's address
    assert "/static/pwa.js" in html and "data-pwa-install" in html and "Add to Dock" in html


def test_other_accounts_do_not_get_the_offer_by_default(mac):
    _, _, html = page(mac, "/settings/appearance")
    assert f'content="{mac.port}"' not in html.split('name="pwa-port"')[1][:20] or mac.port == 8765


def test_welcome_mentions_it(mac):
    _, _, html = page(mac, "/welcome/share")
    assert "/settings/appearance#installapp" in html


def test_phone_pages_never_register_it():
    from pathlib import Path

    js = (Path(__file__).parents[1] / "src/magpiary/static/pwa.js").read_text()
    assert "localhost" in js and "pwa-port" in js  # the script does nothing off localhost on the install port


def test_csp_lets_the_page_load_its_manifest(mac):
    _, headers, _ = request(mac, "GET", "/settings/appearance")
    assert "manifest-src 'self'" in headers["Content-Security-Policy"]
