"""The library tool process cannot create or migrate the user's database."""

import io
import json
import sqlite3

import pytest

from magpiary import mcp_library
from magpiary.config import db_path
from magpiary.store import Store


def test_read_only_store_can_read_but_cannot_write(tmp_path):
    path = tmp_path / "library with spaces?.db"
    store = Store(path)
    store.set_setting("audit_fixture", "synthetic")
    store.close()
    before = path.read_bytes()
    reader = Store(path, read_only=True)
    try:
        assert reader.get_setting("audit_fixture") == "synthetic"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.set_setting("audit_fixture", "changed")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader._db.execute("CREATE TABLE unwanted (id INTEGER)")
    finally:
        reader.close()
    assert path.read_bytes() == before


def test_read_only_store_does_not_create_missing_folder_or_database(tmp_path):
    path = tmp_path / "absent" / "library.db"
    with pytest.raises(sqlite3.OperationalError):
        Store(path, read_only=True)
    assert not path.parent.exists()


def test_mcp_process_uses_read_only_connection_and_closes_it(monkeypatch):
    writer = Store(db_path())
    writer.close()
    real_store, readers = Store, []

    def connect(*args, **kwargs):
        reader = real_store(*args, **kwargs)
        assert kwargs.get("read_only") is True
        readers.append(reader)
        return reader

    monkeypatch.setattr(mcp_library, "Store", connect)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "search_saves", "arguments": {"query": "synthetic"}}}
    monkeypatch.setattr(mcp_library.sys, "stdin", io.StringIO(json.dumps(request) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(mcp_library.sys, "stdout", output)
    mcp_library.main()
    assert "No saved post matches" in json.loads(output.getvalue())["result"]["content"][0]["text"]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        readers[0]._db.execute("SELECT 1")
