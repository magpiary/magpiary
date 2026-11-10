"""A throwaway hub on fictional data, for scans and screenshots. Never touches the real library or keys.
Usage: python demo_hub.py DATA_DIR PORT   (DATA_DIR is created; it holds the database, library and config)"""
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
(root / "home").mkdir(parents=True, exist_ok=True)
(root / "cfg").mkdir(parents=True, exist_ok=True)
os.environ["MAGPIARY_HOME"] = str(root / "home")
os.environ["MAGPIARY_CONFIG"] = str(root / "cfg")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from magpiary import identity  # noqa: E402
from magpiary.hub import details_from_folder  # noqa: E402
from magpiary.receiver import make_server  # noqa: E402
from magpiary.store import Store  # noqa: E402

store = Store(root / "home" / "magpiary.db")
store.set_setting("setup_done", "1")
lib = root / "home" / "library"
srv = make_server(store, "127.0.0.1", int(sys.argv[2]))
srv.hub.library = lib
items = [("https://www.instagram.com/reel/DemoReel01/", "instagram", {"text": "Pasta carbonara recipe", "author": "Chef Alex Example", "author_handle": "chef.example", "duration": 31.0}),
         ("https://www.youtube.com/watch?v=DemoVideo02", "youtube", {"title": "Rust tutorial", "text": "Learn ownership", "author": "Dev Example"}),
         ("https://www.threads.net/@demo/post/C1demoABCD", "threads", {"text": "Design tips for small teams", "author": "Sam Example"})]
for i, (url, src, meta) in enumerate(items):
    folder = lib / f"{src}-{i}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({"url": url, "source": src, **meta}))
    if store.get_item(url) is None:
        store.add_link(url)
    store.fetch_succeeded(url, str(folder))
    store.set_details(url, details_from_folder(folder))
identity.set_name(store, "Ved Example")
identity.set_about(store, "I am a designer")
pile = store.new_pile("Dinner ideas")
store.move_to_pile(items[0][0], pile)
store.move_to_pile(items[1][0], pile)
print("READY", srv.server_port, flush=True)
srv.serve_forever()
