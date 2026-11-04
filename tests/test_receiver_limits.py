"""Incomplete LAN requests do not retain unbounded handler threads."""

import socket
import threading
import urllib.request

import pytest

from fakephone import Mac
from magpiary import receiver


@pytest.mark.parametrize("partial", [b"GET /v1/ping HTTP/1.1\r\n",
                                    b"POST /hub/add HTTP/1.1\r\nContent-Length: 100\r\n\r\ncsrf="])
def test_incomplete_requests_time_out_and_capacity_recovers(tmp_path, clock, monkeypatch, partial):
    monkeypatch.setattr(receiver.Server, "request_timeout", 0.1)
    monkeypatch.setattr(receiver.Server, "max_connections", 1)
    mac = Mac(tmp_path / "receiver.db", clock)
    try:
        with socket.create_connection(("127.0.0.1", mac.port), timeout=2) as client:
            client.sendall(partial)
            assert client.recv(1) == b""  # the idle request was closed by the handler
        assert mac.server._slots.acquire(timeout=2)
        mac.server._slots.release()
        with urllib.request.urlopen(mac.url + "/v1/ping", timeout=2) as response:
            assert response.status == 200
    finally:
        mac.stop()
        mac.store.close()


def test_saturated_server_refuses_extra_connections_then_recovers(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(receiver.Server, "max_connections", 2)
    entered, exited, guard = [], [], threading.Lock()
    full, freed = threading.Event(), threading.Event()
    original = receiver.Handler.handle

    def handle(self):
        with guard:
            entered.append(1)
            if len(entered) == 2:
                full.set()
        try:
            return original(self)
        finally:
            with guard:
                exited.append(1)
                if len(exited) == 2:
                    freed.set()

    monkeypatch.setattr(receiver.Handler, "handle", handle)
    mac = Mac(tmp_path / "receiver.db", clock)
    clients = []
    try:
        for _ in range(2):
            client = socket.create_connection(("127.0.0.1", mac.port), timeout=2)
            client.sendall(b"GET /v1/ping HTTP/1.1\r\n")
            clients.append(client)
        assert full.wait(2)
        with socket.create_connection(("127.0.0.1", mac.port), timeout=2) as extra:
            try:
                assert extra.recv(1) == b""
            except ConnectionResetError:
                pass
        assert len(entered) == 2
        for client in clients:
            client.close()
        assert freed.wait(2)
        # The handler's final slot release follows its handle() return; wait on the
        # actual capacity rather than sleeping or racing that final instruction.
        assert mac.server._slots.acquire(timeout=2)
        mac.server._slots.release()
        with urllib.request.urlopen(mac.url + "/v1/ping", timeout=2) as response:
            assert response.status == 200
    finally:
        for client in clients:
            client.close()
        mac.stop()
        mac.store.close()


def test_a_device_on_the_wifi_that_trickles_bytes_is_cut_off_at_the_deadline(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(receiver.Server, "is_local", staticmethod(lambda address: False))  # as if from the Wi-Fi
    monkeypatch.setattr(receiver.Server, "lan_deadline", 0.5)
    mac = Mac(tmp_path / "receiver.db", clock)
    try:
        with socket.create_connection(("127.0.0.1", mac.port), timeout=3) as client:
            client.sendall(b"GET /v1/ping HTTP/1.1\r\n")
            closed = False
            for _ in range(30):  # a header line every 0.1 s: never idle long enough for the idle timeout
                try:
                    client.sendall(b"X-Slow: 1\r\n")
                    client.settimeout(0.1)
                    if client.recv(1) == b"":
                        closed = True
                        break
                except socket.timeout:
                    continue
                except OSError:
                    closed = True
                    break
            assert closed
        for _ in range(100):  # the handler lets go of its share a moment after the cut
            if not mac.server._lan_open:
                break
            threading.Event().wait(0.02)
        assert not mac.server._lan_open
    finally:
        mac.stop()
        mac.store.close()


def test_one_device_on_the_wifi_cannot_take_every_connection(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(receiver.Server, "is_local", staticmethod(lambda address: False))
    monkeypatch.setattr(receiver.Server, "max_per_address", 2)
    mac = Mac(tmp_path / "receiver.db", clock)
    clients = []
    try:
        for _ in range(2):
            clients.append(socket.create_connection(("127.0.0.1", mac.port), timeout=2))
            clients[-1].sendall(b"GET /v1/ping HTTP/1.1\r\n")
        for _ in range(50):  # both are counted once the server has accepted them
            if mac.server._lan_open.get("127.0.0.1") == 2:
                break
            threading.Event().wait(0.02)
        with socket.create_connection(("127.0.0.1", mac.port), timeout=2) as extra:
            extra.sendall(b"GET /v1/ping HTTP/1.1\r\n\r\n")
            try:
                assert extra.recv(1) == b""  # refused: this device already has its share
            except ConnectionResetError:
                pass
        assert mac.server._slots.acquire(blocking=False)  # the Mac's own hub still has room
        mac.server._slots.release()
        for client in clients:
            client.close()
        clients.clear()
        for _ in range(100):
            if not mac.server._lan_open:
                break
            threading.Event().wait(0.02)
        with urllib.request.urlopen(mac.url + "/v1/ping", timeout=2) as response:
            assert response.status == 200
    finally:
        for client in clients:
            client.close()
        mac.stop()
        mac.store.close()
