"""Two Mac accounts must never share a hub: each gets its own port, and a hub that is not this account's is never treated as ours."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from magpiary import protocol


def test_the_first_account_keeps_8765_and_the_next_gets_the_next_port(monkeypatch):
    monkeypatch.delenv("MAGPIARY_PORT", raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 501)
    assert protocol.default_port() == 8765
    monkeypatch.setattr(os, "getuid", lambda: 502)
    assert protocol.default_port() == 8766
    monkeypatch.setattr(os, "getuid", lambda: 501 + protocol.PORT_SPAN)
    assert protocol.default_port() == 8765   # wraps inside the span the extension searches


def test_the_port_can_be_overridden(monkeypatch):
    monkeypatch.setenv("MAGPIARY_PORT", "9123")
    assert protocol.default_port() == 9123


@pytest.fixture
def fake_hub():
    """A tiny server that answers the ping with whatever user id the test chooses."""
    reply = {"ok": True, "service": "magpiary", "v": 1}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], reply
    server.shutdown()


def test_a_hub_of_another_account_is_not_ours(fake_hub):
    port, reply = fake_hub
    reply["uid"] = os.getuid() + 1
    assert not protocol.ping_is_mine(port)


def test_an_older_hub_that_does_not_say_whose_it_is_is_not_ours(fake_hub):
    port, _ = fake_hub
    assert not protocol.ping_is_mine(port)


def test_our_own_hub_is_recognised(fake_hub):
    port, reply = fake_hub
    reply["uid"] = os.getuid()
    assert protocol.ping_is_mine(port)


def test_nothing_listening_is_not_ours():
    assert not protocol.ping_is_mine(1)
