"""Exercise the real opener against synthetic HTTP sockets; never contact external sites."""

import io
import socket
import urllib.error
import urllib.request

import pytest

from magpiary import network


def answer(ip, port=80):
    return (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


class Wire:
    def __init__(self, response, connected):
        self.response, self.connected = response, connected

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        pass

    def connect(self, address):
        self.connected.append(address)

    def sendall(self, data):
        pass

    def makefile(self, *args):
        return io.BytesIO(self.response)

    def close(self):
        pass


def sockets(monkeypatch, responses, dns):
    connected = []
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    replies = iter(responses)
    monkeypatch.setattr(socket, "socket", lambda *a: Wire(next(replies), connected))
    return connected


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"])
def test_private_destinations_never_connect(monkeypatch, ip):
    connected = sockets(monkeypatch, [], lambda *a, **kw: [answer(ip)])
    with pytest.raises(OSError):
        network.public_urlopen("http://host.example/", timeout=1)
    assert connected == []


def test_public_connection_uses_the_address_already_checked(monkeypatch):
    resolutions = []

    def dns(*args, **kwargs):
        resolutions.append(args)
        return [answer("93.184.215.14" if len(resolutions) == 1 else "127.0.0.1")]

    connected = sockets(monkeypatch, [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"], dns)
    with network.public_urlopen("http://public.example/", timeout=1) as response:
        assert response.read() == b"ok"
    assert len(resolutions) == 1
    assert connected == [("93.184.215.14", 80)]


def test_public_redirect_to_private_destination_is_blocked(monkeypatch):
    connected = sockets(monkeypatch, [b"HTTP/1.1 302 Found\r\nLocation: http://private.example/\r\nContent-Length: 0\r\n\r\n"],
                        lambda host, *a, **kw: [answer("127.0.0.1" if host == "private.example" else "93.184.215.14")])
    with pytest.raises(OSError):
        network.public_urlopen("http://public.example/", timeout=1)
    assert connected == [("93.184.215.14", 80)]


def test_mixed_dns_answers_fail_closed(monkeypatch):
    connected = sockets(monkeypatch, [], lambda *a, **kw: [answer("93.184.215.14"), answer("10.0.0.1")])
    with pytest.raises(OSError):
        network.public_urlopen("http://public.example/", timeout=1)
    assert not connected


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://public.example/file", "https://user:password@public.example/", "https://public.example:99999/"])
def test_invalid_schemes_credentials_and_ports_are_rejected(url):
    with pytest.raises(urllib.error.URLError):
        network.public_urlopen(url, timeout=1)


def test_tls_keeps_original_hostname_and_verified_context(monkeypatch):
    connected = sockets(monkeypatch, [b""], lambda *a, **kw: [answer("93.184.215.14", 443)])
    conn = network._HTTPSConnection("public.example", timeout=1)
    wrapped = []
    monkeypatch.setattr(conn._context, "wrap_socket", lambda sock, **kw: wrapped.append(kw) or sock)
    assert conn._context.check_hostname and conn._context.verify_mode == 2
    conn.connect()
    assert wrapped == [{"server_hostname": "public.example"}]
    assert connected == [("93.184.215.14", 443)]


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "X-Goog-Api-Key", "X-Subscription-Token", "X-Api-Key"])
def test_authenticated_requests_never_follow_a_redirect(monkeypatch, header):
    connected = sockets(monkeypatch, [b"HTTP/1.1 302 Found\r\nLocation: http://other.example/\r\nContent-Length: 0\r\n\r\n"],
                        lambda *a, **kw: [answer("93.184.215.14")])
    request = urllib.request.Request("http://provider.example/", headers={header: "synthetic"})
    with pytest.raises(urllib.error.HTTPError) as err:
        network.public_urlopen(request, timeout=1)
    assert err.value.code == 302
    assert connected == [("93.184.215.14", 80)]


@pytest.mark.parametrize("client", ["gemini", "provider", "bucket", "search", "search-post"])
def test_service_clients_do_not_forward_credentials_or_post_data(monkeypatch, client):
    from magpiary import boardsync, brain, links, providers

    connected = sockets(monkeypatch, [b"HTTP/1.1 303 See Other\r\nLocation: http://other.example/\r\nContent-Length: 0\r\n\r\n"],
                        lambda *a, **kw: [answer("93.184.215.14")])
    url = "http://provider.example/"
    headers = {"Authorization": "synthetic"}
    calls = {
        "gemini": lambda: brain.http_call("POST", url, "synthetic", {"data": "private"}),
        "provider": lambda: providers.http_request("POST", url, headers, {"data": "private"}),
        "bucket": lambda: boardsync.http_call("GET", url, None, headers),
        "search": lambda: links.http_get(url, headers),
        "search-post": lambda: links.http_post_json(url, headers, {"data": "private"}),
    }
    assert calls[client]()[0] == 303
    assert connected == [("93.184.215.14", 80)]


def test_environment_proxy_is_not_used(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.example:8888")
    hosts = []

    def dns(host, *args, **kwargs):
        hosts.append(host)
        return [answer("93.184.215.14")]

    sockets(monkeypatch, [b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"], dns)
    with network.public_urlopen("http://public.example/", timeout=1):
        pass
    assert hosts == ["public.example"]
