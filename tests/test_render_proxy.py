"""The renderer's proxy (review 3, 4 Nov 2026): Chrome may reach public addresses only, never this Mac or its network."""

import socket

from magpiary.network import PublicProxy


def ask(proxy: str, line: str) -> bytes:
    host, port = proxy.split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s:
        s.sendall(line.encode() + b"\r\nHost: x\r\n\r\n")
        return s.recv(200)


def test_the_proxy_refuses_this_mac_and_private_networks():
    with PublicProxy() as proxy:
        for line in ("CONNECT 127.0.0.1:8765 HTTP/1.1", "GET http://localhost:8765/ HTTP/1.1",
                     "CONNECT 192.168.1.1:443 HTTP/1.1", "GET http://10.0.0.1/ HTTP/1.1", "CONNECT [::1]:8765 HTTP/1.1",
                     "GET file:///etc/passwd HTTP/1.1"):
            assert ask(proxy, line).startswith(b"HTTP/1.1 403"), line
