"""Score the link engine against the owner's answer key (evals/links-v2, kept out of git: real saves).

    uv run python scripts/links_eval.py snapshot      copy the saves' evidence from the library
    uv run python scripts/links_eval.py ai [--only SLUG]  summarise the saves again with the owner's key (one AI call
                                                      each; kept in the eval folder, the library is not touched)
    uv run python scripts/links_eval.py old           score the links the old engine stored
    uv run python scripts/links_eval.py new [--offline] [--only SLUG] [--show] [--stored]
                                                      run today's engine on the snapshot and score it
                                                      (--stored: on the old records, without the AI's link tags)

Every page and directory answer the engine asks for is recorded in <slug>/net.json.gz, so a later run
replays them (--offline: nothing new is fetched; a missing answer counts as a network failure).
"""

import base64
import gzip
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "evals" / "links-v2"
LIBRARY = Path(os.environ.get("MAGPIARY_HOME", Path.home() / "Magpiary"))
BODY_LIMIT = 200_000

sys.path.insert(0, str(ROOT / "src"))
from magpiary.links import norm  # noqa: E402


def address(url: str) -> str:
    parts = urlsplit(url if "://" in url else "https://" + url)
    host = (parts.hostname or "").removeprefix("www.")
    return (host + unquote(parts.path)).rstrip("/").lower()


def matches(url: str, accepted: list[str]) -> bool:
    got = address(url)
    return any(got == address(a) or got.startswith(address(a).rstrip("/") + "/") or
               (a.endswith("/") and got.startswith(address(a))) for a in accepted)


def key() -> list[dict]:
    return json.loads((EVAL / "key.json").read_text())["saves"]


# ---- inputs -------------------------------------------------------------------------------

def snapshot() -> None:
    db = sqlite3.connect(f"file:{LIBRARY / 'magpiary.db'}?mode=ro", uri=True)
    for save in key():
        folder, transcript = db.execute("SELECT archive_dir, transcript_text FROM items WHERE canonical_url=?",
                                        (save["url"],)).fetchone()
        folder = Path(folder)
        meta = json.loads((folder / "meta.json").read_text())
        comments = json.loads((folder / "discussion.json").read_text()) if (folder / "discussion.json").exists() else None
        out = EVAL / save["slug"]
        out.mkdir(parents=True, exist_ok=True)
        old = json.loads((out / "input.json").read_text()) if (out / "input.json").exists() else {}
        data = {"url": save["url"], "record": json.loads((folder / "record.json").read_text()),
                "caption": meta.get("text") or "", "author": meta.get("author") or "", "transcript": transcript or "", "comments": comments,
                "record_v2": old.get("record_v2")}
        (out / "input.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"{save['slug']}: saved")


def summarise_again(only: str) -> None:
    from magpiary import keys as keyring
    from magpiary.brain import build_evidence, summarise
    from magpiary.process import MAX_IMAGES, VIDEO

    key_ = keyring.usable()[0]
    db = sqlite3.connect(f"file:{LIBRARY / 'magpiary.db'}?mode=ro", uri=True)
    for save in key():
        if only and save["slug"] != only:
            continue
        folder, note = db.execute("SELECT archive_dir, note FROM items WHERE canonical_url=?", (save["url"],)).fetchone()
        folder = Path(folder)
        load = lambda name, default: json.loads((folder / name).read_text()) if (folder / name).exists() else default
        meta = load("meta.json", {})
        images = [folder / m for m in meta.get("media") or [] if not m.endswith(VIDEO)][:MAX_IMAGES]
        transcript = (load("transcript.json", None) or {}).get("segments")
        parts = build_evidence(meta, transcript, load("frames.json", []), images, folder, load("discussion.json", None),
                               note or "")
        record = summarise(parts, key_.secret, key_.model, provider=key_.provider)
        path = EVAL / save["slug"] / "input.json"
        data = json.loads(path.read_text())
        data["record_v2"] = record
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"{save['slug']}: {len(record['link_targets'])} targets ({key_.provider}:{key_.model})")


# ---- recorded network ---------------------------------------------------------------------

class Recorder:
    def __init__(self, slug: str, offline: bool):
        self.path = EVAL / slug / "net.json.gz"
        self.offline = offline
        self.data = json.loads(gzip.decompress(self.path.read_bytes())) if self.path.exists() else {}
        self.missing, self.live = [], 0
        self.token = ""
        if not offline:
            try:  # a token only lifts GitHub's hourly limit while recording; answers are the same
                self.token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
            except OSError:
                pass

    def get(self, url: str, headers: dict | None = None) -> tuple[int, str, bytes]:
        from magpiary.links import http_get

        if url in self.data and (self.offline or self.data[url][0] not in (429, 503, 599)):
            status, final, body = self.data[url]
            return status, final, base64.b64decode(body)
        if self.offline:
            self.missing.append(url)
            raise OSError("not recorded")
        headers = dict(headers or {})
        if self.token and url.startswith("https://api.github.com/"):
            headers["Authorization"] = f"Bearer {self.token}"
        time.sleep(2.1 if "api.github.com/search" in url else 1.1 if "nominatim" in url or "wikidata" in url else 0.3)
        self.live += 1
        try:
            status, final, body = http_get(url, headers)
        except OSError:
            status, final, body = 599, url, b""  # recorded as a failure, replayed as one
        self.data[url] = [status, final, base64.b64encode(body[:BODY_LIMIT]).decode()]
        if status == 599:
            raise OSError("network failure (recorded)")
        return status, final, body

    def save(self) -> None:
        if not self.offline:
            self.path.write_bytes(gzip.compress(json.dumps(self.data).encode()))


# ---- rows and scores ----------------------------------------------------------------------

def rows_from_found(found: list) -> list[dict]:
    """One row per name: its main link, badges, where it shows, whether it is only a possible match."""
    rows: dict[str, dict] = {}
    for f in found:
        row = rows.setdefault(norm(f.name), {"name": f.name, "main": "", "badges": [], "possibles": [],
                                             "shown": "more" if getattr(f, "central", True) is False else "top",
                                             "possible": False, "source": ""})
        role = getattr(f, "role", "main")
        if role == "badge":
            row["badges"].append(f.url)
        elif not row["main"]:
            row["main"], row["source"] = f.url, f.source
            row["possible"] = getattr(f, "possible", False)
        else:
            row["possibles"].append(f.url)
    return list(rows.values())


def rows_from_store(url: str) -> list[dict]:
    db = sqlite3.connect(f"file:{LIBRARY / 'magpiary.db'}?mode=ro", uri=True)
    rows: dict[str, dict] = {}
    for name, link, rank, source in db.execute(
            "SELECT name, url, rank, source FROM links WHERE canonical_url=? AND removed=0 ORDER BY rank='possible', rowid",
            (url,)):
        row = rows.setdefault(norm(name), {"name": name, "main": "", "badges": [], "possibles": [], "shown": "top",
                                           "possible": False, "source": ""})
        if not row["main"]:
            row["main"], row["source"], row["possible"] = link, source, rank == "possible"
        else:
            row["possibles"].append(link)
    return list(rows.values())


def score(save: dict, rows: list[dict], show: bool = False) -> dict:
    by_name = {}
    for row in rows:
        by_name[norm(row["name"])] = row
    used = set()
    s = {"rows": len(rows), "links": sum(1 + len(r["possibles"]) + len(r["badges"]) for r in rows),
         "right": 0, "wrong": 0, "missed": 0, "unwanted": 0, "fold": 0, "extra": 0, "badges": 0, "badges_want": 0}
    notes = []
    mains = {address(r["main"]): r for r in rows if r["main"]}
    for want in save["expect"]:
        names = [norm(n) for n in [want["name"], *want.get("aliases", [])]]
        row = next((by_name[n] for n in names if n in by_name), None)
        accepted = want.get("main")
        if want["shown"] == "none":
            if row and row["main"]:
                s["unwanted"] += 1
                notes.append(f"  unwanted  {want['name']} → {row['main']}")
            if row:
                used.add(norm(row["name"]))
            continue
        if row is None and accepted and accepted != "?":  # a different name for the same link still counts
            row = next((r for a, r in mains.items() if matches(a, accepted)), None)
        if row:
            used.add(norm(row["name"]))
        if row is None or not row["main"]:
            s["missed"] += 1
            notes.append(f"  missed    {want['name']}")
            continue
        if accepted == "?" or matches(row["main"], accepted):
            s["right"] += 1
            if row["shown"] != want["shown"]:
                s["fold"] += 1
                notes.append(f"  fold      {want['name']}: {row['shown']}, want {want['shown']}")
        else:
            s["wrong"] += 1
            notes.append(f"  wrong     {want['name']} → {row['main']}  (want {accepted[0]})")
        for badge in want.get("badges", []):
            s["badges_want"] += 1
            if any(matches(b, [badge]) for b in row["badges"]) or matches(row["main"], [badge]):
                s["badges"] += 1
    for row in rows:
        if norm(row["name"]) not in used:
            s["extra"] += 1
            notes.append(f"  extra     {row['name']} → {row['main']}")
    if show:
        print("\n".join(notes))
    return s


def report(results: dict[str, dict]) -> None:
    cols = ["rows", "links", "right", "wrong", "missed", "unwanted", "extra", "fold", "badges"]
    print(f"{'save':10}" + "".join(f"{c:>9}" for c in cols))
    total = dict.fromkeys(cols, 0)
    for slug, s in results.items():
        cells = {**s, "badges": f"{s['badges']}/{s['badges_want']}"}
        print(f"{slug:10}" + "".join(f"{cells[c]:>9}" for c in cols))
        for c in cols:
            if c != "badges":
                total[c] += s[c]
    print(f"{'total':10}" + "".join(f"{total[c]:>9}" for c in cols if c != "badges"))


# ---- commands -----------------------------------------------------------------------------

def run_old(show: bool) -> None:
    results = {}
    for save in key():
        if show:
            print(save["slug"])
        results[save["slug"]] = score(save, rows_from_store(save["url"]), show)
    report(results)


def eval_search(net: "Recorder"):
    """MAGPIARY_EVAL_SEARCH=tavily or brave: the owner's saved search key, answers recorded like pages."""
    provider = os.environ.get("MAGPIARY_EVAL_SEARCH", "")
    if not provider:
        return None
    from magpiary import keys as keyring
    from magpiary import links

    key_ = keyring.search_key()
    if provider == "brave":
        return links.brave(key_.secret, net.get)

    def post(url, headers, body):  # recorded under the query, never the key
        name = f"{url}?q={body['query']}"
        if name not in net.data:
            if net.offline:
                net.missing.append(name)
                return 599, {}
            net.data[name] = list(links.http_post_json(url, headers, body))
        return net.data[name][0], net.data[name][1]
    return links.tavily(key_.secret, post)


def run_new(offline: bool, only: str, show: bool, stored: bool = False) -> None:
    from magpiary.links import find_links

    results = {}
    for save in key():
        if only and save["slug"] != only:
            continue
        data = json.loads((EVAL / save["slug"] / "input.json").read_text())
        record = data["record"] if stored or not data.get("record_v2") else data["record_v2"]
        net = Recorder(save["slug"], offline)
        try:
            found = find_links(record, data["caption"], data["transcript"], data["comments"], get=net.get,
                               search=eval_search(net), author=data.get("author", ""))
        finally:
            net.save()
        if show:
            print(f"{save['slug']}  ({'stored names only' if record is data['record'] else 'AI tags'}, "
                  f"{net.live} fetched, {len(net.missing)} not recorded)")
        results[save["slug"]] = score(save, rows_from_found(found), show)
    report(results)


if __name__ == "__main__":
    args = sys.argv[1:]
    command = args[0] if args else "old"
    only = args[args.index("--only") + 1] if "--only" in args else ""
    if command == "snapshot":
        snapshot()
    elif command == "ai":
        summarise_again(only)
    elif command == "old":
        run_old("--show" in args)
    elif command == "new":
        run_new("--offline" in args, only, "--show" in args, "--stored" in args)
