"""A tiny MCP server (stdio) that lets Claude Code look through the owner's saves while it answers a question in Ask Magpiary.
Two read-only tools: search_saves and read_save. It runs on this Mac, opens the library's database for reading only, and
returns text from the saves, which the AI treats as untrusted data. Started by ask_open.py, not by hand."""

import json
import sys

from magpiary import ask as asking
from magpiary import ui
from magpiary.config import db_path
from magpiary.store import Store

TOOLS = [
    {"name": "search_saves", "description": "Search the person's saved posts (Instagram, Threads, YouTube, X, Reddit...) by words. "
     "Returns up to 6 matches with an id, title, author and a one-line summary.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_save", "description": "Read one saved post in full by its id: summary, key moments, caption, note, text on screen "
     "and spoken words.", "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
]


def call(store: Store, name: str, args: dict) -> str:
    if name == "search_saves":
        items = store.hub_items("kept", str(args.get("query", ""))[:200], limit=6)
        if not items:
            return "No saved post matches those words. Try different or fewer words."
        out = []
        for item in items:
            summary = (item.get("summary") or item.get("caption") or "")[:120].replace("\n", " ")
            out.append(f'id {item["id"]}: {ui.title_of(item)} — {item.get("author") or ""} '
                       f'({item.get("source", "")}). {summary}')
        return "\n".join(out)
    if name == "read_save":
        item = store.item_by_id(int(args.get("id", 0))) if str(args.get("id", "")).lstrip("-").isdigit() else None
        if not item or item.get("shelf") == "trash":
            return "There is no saved post with that id."
        return asking.post_text(item, "", int(item["id"]))[:asking.PER_POST]
    return "Unknown tool."


def reply(message: dict, store: Store) -> dict | None:
    method, ident = message.get("method"), message.get("id")
    if ident is None:  # a notification: nothing to answer
        return None
    if method == "initialize":
        result = {"protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "magpiary", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        try:
            text = call(store, params.get("name", ""), params.get("arguments") or {})
        except Exception as err:  # the AI gets a plain failure, not a crash
            text = f"The library could not be read ({type(err).__name__})."
        result = {"content": [{"type": "text", "text": text}]}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main() -> None:
    store = Store(db_path(), read_only=True)
    try:
        for line in sys.stdin:
            try:
                out = reply(json.loads(line), store)
            except ValueError:
                continue
            if out is not None:
                sys.stdout.write(json.dumps(out) + "\n")
                sys.stdout.flush()
    finally:
        store.close()


if __name__ == "__main__":
    main()
