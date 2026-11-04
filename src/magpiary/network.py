"""HTTP for untrusted public URLs: check the actual destination, including every redirect.

Resolve once per connection and connect directly to the checked socket address. TLS still
uses the original hostname for SNI/certificate verification. Environment proxies and URL
credentials are deliberately unsupported. Requests carrying credentials never redirect.
"""

import http.client
import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def _check_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None \
                or parts.password is not None or not 1 <= (parts.port or 443) <= 65535:
            raise ValueError("invalid public URL")
    except ValueError as err:
        raise urllib.error.URLError("Only public HTTP(S) URLs without credentials are allowed") from err


def _connect_public(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    host, port = address
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    # Reject mixed public/private answers too; never fall back to a private address.
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise OSError("Nonpublic network destination refused")
    failure = None
    for family, kind, proto, _, target in addresses:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(target)
            return sock
        except OSError as err:
            failure = err
            sock.close()
    raise failure or OSError("Public destination unavailable")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.enabled:
            return None  # urllib returns HTTPError: callers already handle HTTP failures
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_urlopen(request, *, timeout: float, redirects: bool = True):
    """Open only public HTTP(S); callers retain their existing response-size limits."""
    if isinstance(request, str):
        request = urllib.request.Request(request)
    _check_url(request.full_url)
    sensitive = {"authorization", "cookie", "x-goog-api-key", "x-subscription-token", "x-api-key"}
    authenticated = any(k.lower() in sensitive for k, _ in request.header_items())
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(), _Redirect(redirects and not authenticated))
    return opener.open(request, timeout=timeout)


# ---- a public-only proxy for the page renderer -------------------------------------------------------------------
# Headless Chrome draws pages made by scripts (sources.chrome_render). A page could point Chrome at this Mac's hub or
# the home network. Every request Chrome makes, loopback included, goes through this proxy, which connects only to
# public addresses it checked itself (review 3, 4 Nov 2026). Chrome ignores PAC scripts headless, so a proxy it is.

import select  # noqa: E402
import socketserver  # noqa: E402
import threading  # noqa: E402

_PIPE_SECONDS = 30


def _pipe(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    while True:
        ready, _, broken = select.select(sockets, [], sockets, _PIPE_SECONDS)
        if broken or not ready:
            return
        for s in ready:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(_PIPE_SECONDS)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
        line, _, rest = head.partition(b"\r\n")
        try:
            method, target, version = line.decode("latin-1").split(" ", 2)
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                upstream = _connect_public((host.strip("[]"), int(port)), timeout=_PIPE_SECONDS)
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                extra = rest.partition(b"\r\n\r\n")[2]
            else:
                _check_url(target)
                parts = urlsplit(target)
                upstream = _connect_public((parts.hostname, parts.port or 80), timeout=_PIPE_SECONDS)
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                extra = f"{method} {path} {version}\r\n".encode("latin-1") + rest
        except (ValueError, OSError, urllib.error.URLError):
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        try:
            if extra:
                upstream.sendall(extra)
            _pipe(client, upstream)
        except OSError:
            pass
        finally:
            upstream.close()


class _ProxyServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PublicProxy:
    """`with PublicProxy() as address:` a proxy on 127.0.0.1 for the length of one render."""

    def __enter__(self) -> str:
        self._server = _ProxyServer(("127.0.0.1", 0), _ProxyHandler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
