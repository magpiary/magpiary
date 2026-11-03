from magpiary import icons

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


def test_well_known_sites_have_built_in_marks_and_others_do_not():
    assert icons.builtin("github.com") == "github" and icons.builtin("gist.github.com") == "github" and icons.builtin("youtu.be") == "youtube"
    assert icons.builtin("example.com") is None
    assert icons.host_of("https://www.Example.com/a?b=1") == "example.com"


def test_an_icon_is_fetched_once_kept_and_a_miss_is_remembered():
    calls = []

    def get(url, headers, limit):
        calls.append(url)
        return 200, url, PNG

    assert icons.fetch("example.com", get, public=lambda h: True) is True
    assert icons.cached("example.com").suffix == ".png" and icons.content_type(icons.cached("example.com")) == "image/png"
    assert icons.fetch("example.com", get, public=lambda h: True) is True and len(calls) == 1  # asked once
    assert icons.fetch("nope.example", lambda *a: (404, "", b""), public=lambda h: True) is False
    assert icons.fetch("nope.example", get, public=lambda h: True) is False and len(calls) == 1  # the miss is kept too
    assert icons.due(["https://nope.example/x", "https://github.com/a", "https://fresh.example/y"]) == ["fresh.example"]


def test_hosts_inside_the_home_network_are_never_asked(monkeypatch):
    for host in ("localhost", "192.168.1.1", "printer.local", "127.0.0.1"):
        assert icons.public_host(host) is False
    asked = []
    assert icons.fetch("192.168.1.1", lambda *a: asked.append(a) or (200, "", PNG)) is False and not asked
    assert icons.fetch("bad.example", lambda *a: (200, "", b"<html>not an image</html>" * 10), public=lambda h: True) is False


def test_a_home_page_can_name_the_icon_when_favicon_ico_is_missing():
    html = '<head><link rel="stylesheet" href="/a.css"><link rel="icon" sizes="32x32" href="/i32.png"><link rel="apple-touch-icon" sizes="180x180" href="/t.png"></head>'
    assert icons._page_icon(html, "https://site.example/") == "https://site.example/t.png"  # the larger one
    assert icons._page_icon('<link rel="icon" href="http://insecure.example/x.png">', "https://s.example/") == ""
    assert icons._page_icon('<link rel="icon" href="/logo.svg">', "https://s.example/") == ""
    calls = []

    def get(url, headers, limit):
        calls.append(url)
        return (404, url, b"") if url.endswith("favicon.ico") else (200, url, b"<link rel='icon' href='/i.png'>") if url.endswith("/") else (200, url, PNG)

    assert icons.fetch("pages.example", get, public=lambda h: True) is True and calls[-1] == "https://pages.example/i.png"
