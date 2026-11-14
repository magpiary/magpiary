"""A throwaway hub on the contextual-tabs fixtures (tests/fixtures/views: one fictional post per category), for clicking
through the post views. Private mode, every background step paused and no worker loops: nothing calls an AI service
or the network. Never touches the real library or keys. Run it through views_sandbox.sh.
Usage: views_sandbox_hub.py DATA_DIR PORT   (DATA_DIR is created; it holds the database, library and config)"""
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "views"


def load_fixtures(store, library: Path, fixtures: Path = FIXTURES) -> dict[str, int]:
    """Every fixture post as a saved, summarised post with its view built: {category folder name: item id}."""
    from magpiary.hub import details_from_folder

    out = {}
    for src in sorted(p for p in fixtures.iterdir() if (p / "meta.json").is_file()):
        folder = library / f"fixture-{src.name}"
        folder.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.json"):
            shutil.copyfile(f, folder / f.name)
        meta = json.loads((folder / "meta.json").read_text())
        record = json.loads((folder / "record.json").read_text())
        url = store.add_link(meta["url"]).id  # the canonical URL
        store.fetch_succeeded(url, str(folder))
        store.set_details(url, details_from_folder(folder))
        segs = (json.loads((folder / "transcript.json").read_text()).get("segments")
                if (folder / "transcript.json").is_file() else [])
        spoken = " ".join(s["text"] for s in segs)
        if segs:
            store.senses_done(url, spoken)
        store.brain_succeeded(url, record, spoken, apply_tags=True)
        item_id = store.id_for(url)
        store.set_category(item_id, record.get("category") or "other", record.get("category2") or "", "ai")
        store.set_view_status(item_id, "done")
        out[src.name] = item_id
    return out


def quiet(store) -> None:
    """Private mode and every background step paused: no AI, no links, no lookups, no transcribing."""
    store.set_setting("setup_done", "1")
    store.set_setting("ai_mode", "private")
    store.set_setting("checklist", '{"done": [], "off": true}')  # the getting-started panel would cover the wall
    for part in ("transcribe", "summary", "links"):
        store.set_paused(part, True)


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    (root / "home").mkdir(parents=True, exist_ok=True)
    (root / "cfg").mkdir(parents=True, exist_ok=True)
    os.environ["MAGPIARY_HOME"] = str(root / "home")      # before any magpiary import: config paths come from these
    os.environ["MAGPIARY_CONFIG"] = str(root / "cfg")
    sys.path.insert(0, str(REPO / "src"))

    from magpiary import config  # noqa: E402
    from magpiary.receiver import make_server  # noqa: E402
    from magpiary.store import Store  # noqa: E402

    assert str(config.data_dir()).startswith(str(root)) and str(config.config_dir()).startswith(str(root)), "not sandboxed"
    store = Store(root / "home" / "magpiary.db")
    quiet(store)
    library = root / "home" / "library"
    ids = load_fixtures(store, library)
    srv = make_server(store, "127.0.0.1", int(sys.argv[2]))
    srv.hub.library = library
    print("POSTS", json.dumps(ids), flush=True)
    print("READY", srv.server_port, flush=True)
    srv.serve_forever()
