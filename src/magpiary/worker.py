"""Background work on the queue, one item at a time with a pause between: expanding short links,
then fetching and archiving posts."""

import json
import random
import time
from urllib.parse import urlsplit
from collections.abc import Callable
from pathlib import Path

from magpiary.activity import NO_PROGRESS
from magpiary.archive import fetch_item
from magpiary import capture as captures
from magpiary import login
from magpiary.hub import details_from_folder
from magpiary.expand import ExpansionFailed, Fetch, expand, http_fetch
from magpiary.sources import FetchFailed, Get, http_get
from magpiary.store import Store
from magpiary.tools import ToolMissing, YtDlp, update_ytdlp
from magpiary.config import load_json as _load_json  # noqa: E402  (one reader for the library's JSON files)

RETRYABLE = {"rate_limited", "unknown"}  # the rest (private, deleted, login wall...) wait for Retry


def jitter_pause() -> None:
    """Serial and slow on purpose: never hammer a site with a burst of requests."""
    time.sleep(random.uniform(0.5, 2.0))


def process_due(store: Store, fetch: Fetch = http_fetch, pause: Callable[[], None] = jitter_pause) -> int:
    """Try every short link that is due. Returns how many were expanded."""
    done = 0
    for i, link in enumerate(store.due_for_expansion()):
        if i:
            pause()
        try:
            store.expansion_succeeded(link.url, expand(link, fetch))
            done += 1
        except ExpansionFailed as err:
            store.expansion_failed(link.url, err.detail)
    return done


def fetch_pause(source: str) -> None:
    """Serial with jitter; Reddit gets a slow lane (it rate-limits scripts hard, S4)."""
    time.sleep(random.uniform(20, 40) if source == "reddit" else random.uniform(3, 8))


def fetch_due(store: Store, library: Path, get: Get = http_get, ytdlp: YtDlp | None = None,
              pause: Callable[[str], None] = fetch_pause, update: Callable[..., bool] | None = None,
              activity=None, on_archived: Callable[[], None] = lambda: None) -> int:
    """Fetch and archive every item that is due. Returns how many were archived."""
    ytdlp = ytdlp or YtDlp()
    update = update or (lambda force=False: update_ytdlp(store, force=force))
    done = 0
    base = ytdlp
    for i, item in enumerate(store.due_for_fetch()):
        if i:
            pause(item["source"])
        url = item["canonical_url"]
        site = login.site_of(url)
        ytdlp = with_login(base, site) if item.get("use_login") else base
        item_get = _get_with_login(get, site) if item.get("use_login") else get
        progress = activity.begin("fetch", item) if activity else NO_PROGRESS
        seen = captures.latest(url)  # the page as the owner saw it: read from that, not fetched again
        if seen:
            ytdlp, item_get = base, get  # a capture never needs the owner's saved login
        try:
            folder = fetch_item(item, library, item_get, ytdlp, progress=progress, capture=seen)
        except ToolMissing as err:
            store.fetch_failed(url, "unknown", str(err), retry=True)
            continue
        except FetchFailed as err:
            # yt-dlp breaks when a site changes: update it (once a day at most) and try once more
            if err.reason in RETRYABLE and item["source"] in ("instagram", "youtube", "x", "linkedin") and update():
                try:
                    folder = fetch_item(item, library, item_get, ytdlp, progress=progress, capture=seen)
                except FetchFailed as again:
                    store.fetch_failed(url, *_plain_failure(again, item, ytdlp is not base))
                    continue
            else:
                reason, detail, retry = _plain_failure(err, item, ytdlp is not base)
                store.fetch_failed(url, reason, detail, retry=retry)
                continue
        except Exception as err:  # a timeout or a parse error on one post must not hold up every post after it
            store.fetch_failed(url, "unknown", f"The download stopped: {type(err).__name__}", retry=True)
            continue
        finally:
            if activity:
                activity.end("fetch")
        store.fetch_succeeded(url, str(folder))
        store.set_details(url, details_from_folder(folder))
        if seen:
            captures.done(seen)
        newer = captures.latest(url)
        if newer and (not seen or newer.id != seen.id):  # captured while this fetch ran: read it next time round
            store.recaptured(url)
        on_archived()
        done += 1
    return done


def _get_with_login(get: Get, site: str) -> Get:
    """Page fetches carry the owner's saved login for this one site. Only the real fetcher takes a cookie; a test double is left alone."""
    if not login.cookie_header(site) or get is not http_get:
        return get

    def fetch(url, *rest):
        # the login goes only to that site, over https, and only the cookies that belong at that exact address: never to an
        # image or page on another host the post points at (review 3), nor to a sibling tenant like b.github.io (review 5)
        header = login.cookie_header(site, url) if login.site_of(url) == site and urlsplit(url).scheme == "https" else ""
        return http_get(url, *rest, cookie=header) if header else http_get(url, *rest)
    return fetch


def with_login(ytdlp: YtDlp, domain: str = "instagram.com") -> YtDlp:
    """The same yt-dlp, carrying the owner's login to that item's site (only for items they allowed it on)."""
    from magpiary.login import login_path

    path = login_path(domain)
    if not path.exists():
        return ytdlp
    path.chmod(0o600)  # yt-dlp writes the file back after each run
    return YtDlp(run=ytdlp.run, binary=ytdlp.binary, cookies=path)


def _plain_failure(err: FetchFailed, item: dict, used_login: bool) -> tuple[str, str, bool]:
    """Instagram answers an age-limited or followers-only post with an "empty media response", which looks
    like its short-lived refusal. The same answer three times means the post needs a login."""
    empty = "empty media response" in err.detail.lower()
    site = login.site_of(item.get("canonical_url", ""))
    name = "Instagram" if site in ("", "instagram.com") else site
    if used_login and (err.reason == "login_wall" or empty):
        return ("login_wall", f"{name} still refused it with your login. If the login copy is old, connect "
                f"{name} again.", False)
    if empty and item.get("attempts", 0) >= 2:
        return ("login_wall", "Instagram shows this post only to logged-in people (often an age limit or "
                "followers only).", False)
    return err.reason, err.detail, err.reason in RETRYABLE


BRAIN_RETRYABLE = {"rate_limited", "busy", "unknown"}  # blocked and invalid wait for "Try again"


def brain_pause(tier: str = "free") -> None:
    """Free keys get a handful of requests a minute; paid keys need no wait."""
    time.sleep(random.uniform(6, 10) if tier == "free" else 0.5)


def transcript_text(folder: Path) -> str:
    try:
        saved = json.loads((folder / "transcript.json").read_text())
        return " ".join(seg["text"] for seg in saved.get("segments", []))
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def brain_due(store: Store, notes_dir: Path, pause: Callable[[str], None] = brain_pause, process=None,
              log: Callable[[str], None] = lambda m: None, key_source=None, activity=None, prepare=None) -> int:
    """For each archived item: first the transcript and frames (on the Mac, saved right away), then the summary
    with the first usable key (moving to the next key on a limit, a refusal or a busy service). Each part can be
    paused; an item the owner asked to "Try again" goes even while paused. Returns how many summaries were made."""
    from magpiary import keys as keyring
    from magpiary import modes
    from magpiary.brain import BrainFailed
    from magpiary.process import process_item, senses

    key_source = key_source or keyring
    process = process or (lambda item, key, progress: process_item(item, key, notes_dir, store=store, progress=progress))
    prepare = prepare or (lambda item, progress: senses(Path(item["archive_dir"]), _meta(item), progress=progress))
    apply_tags = store.get_setting("auto_tags", "apply") == "apply"
    done = asked = 0
    for item in store.due_for_brain():
        forced = bool(item.get("ai_force"))
        url = item["canonical_url"]
        heard = str(item.get("senses_status") or "")  # not "senses": that name is the transcriber called by prepare()
        if not heard or (heard.startswith("failed:") and heard[7:] < store._stamp()[:10]):  # failed: once a day
            if store.paused("transcribe") and not forced:
                continue
            progress = activity.begin("process", item) if activity else NO_PROGRESS
            try:
                got = prepare(item, progress)
            except Exception as err:  # a broken file must not stop the others; it is tried again tomorrow
                log(f"transcript failed: {type(err).__name__}")
                store.senses_failed(url)
            else:
                problem = got[2] if isinstance(got, tuple) and len(got) == 3 else ""
                if problem:  # senses() caught Whisper's failure and said so: not done, tried again tomorrow
                    log("transcript failed: " + problem[:80])
                    store.senses_failed(url)
                else:
                    store.senses_done(url, transcript_text(Path(item["archive_dir"])))
            finally:
                if activity:
                    activity.end("process")
        if item.get("ai_status") == "done" and not forced:
            continue
        if not forced and (store.paused("summary") or not modes.summarisers(store, key_source) or not store.take_summary_turn()):
            continue  # nobody can write it now (Private, no key, all at their limit): the "next N" allowance is kept
        record, busy, repicked, last_busy, skipped = None, set(), set(), None, []
        while record is None:
            # Smart: the keys and the allowed Claude Code or Codex, in the owner's order; Private: nobody. One that was busy or
            # failed for this item is skipped for it, not for the next one.
            usable = [k for k in modes.summarisers(store, key_source) if k.id not in busy]
            if not usable:
                if last_busy:  # every key was busy: wait for the next try
                    store.brain_failed(url, last_busy.reason, last_busy.detail, retry=True)
                break  # no summary now; later items still need their local transcript
            key = usable[0]
            if asked:
                pause(key.tier)
            asked += 1
            progress = activity.begin("process", item) if activity else NO_PROGRESS
            try:
                record = process(item, key, progress)
            except BrainFailed as err:
                if getattr(key, "tier", "") == "local" and err.reason != "busy":
                    busy.add(key.id)  # Claude Code or Codex could not write it: the next in the owner's order tries it now
                    last_busy = err
                    log(f"{key.name} could not write a summary; trying the next")
                    continue
                if err.reason == "bad_key":
                    key_source.mark(key.id, refused=True)
                    log(f"key '{key.name}' was refused; trying the next key")
                    continue
                if err.reason == "rate_limited":
                    key_source.mark(key.id, limit=True)
                    log(f"key '{key.name}' reached its limit for today; trying the next key")
                    continue
                if err.reason == "busy":
                    last_busy = err
                    if key.id not in repicked and hasattr(key_source, "repick"):
                        repicked.add(key.id)
                        if key_source.repick(key):  # that model is slow or overloaded: pick another for later
                            log(f"switched key '{key.name}' to a less busy model")
                            if len(usable) == 1:
                                continue  # no other key: try this one once more on its new model
                    busy.add(key.id)
                    if len(usable) > 1:
                        log(f"key '{key.name}' is busy; trying the next key")
                    continue
                if len(usable) > 1 and getattr(key, "tier", "") != "local":
                    # a request this service rejected (for example HTTP 422) must not block the item while another key
                    # could write it: try the next key now and keep what happened for the item's note
                    busy.add(key.id)
                    skipped.append(f"{key.name}: {err.detail}")
                    log(f"key '{key.name}' failed ({err.reason}); trying the next key")
                    continue
                store.brain_failed(url, err.reason, "; ".join([*skipped, f"{key.name}: {err.detail}"] if skipped else [err.detail])[:400],
                                   retry=err.reason in BRAIN_RETRYABLE)
                break
            except Exception as err:
                store.brain_failed(url, "unknown", type(err).__name__, retry=True)
                break
            finally:
                if activity:
                    activity.end("process")
        if record is None:
            continue
        now = store.get_item(url) or {}
        if now.get("status") != "archived" or now.get("archived_at") != item.get("archived_at"):
            # captured again while this summary was being written: it describes the old page; the new one is summarised next
            log(f"{url}: saved again while it was being summarised; that summary is dropped")
            continue
        store.brain_succeeded(url, record, transcript_text(Path(item["archive_dir"])), apply_tags)
        done += 1
    return done




class _DeepStopped(Exception):
    """The owner switched to Private, turned Deeper dive off, or stopped its engine while a dive was running."""


def deep_due(store: Store, notes_dir: Path, activity=None, log: Callable[[str], None] = lambda m: None, asker=None) -> int:
    """Deeper dives the owner asked for, one at a time with the engine chosen in Settings. Returns how many were made."""
    from magpiary import deepdive
    from magpiary.brain import BrainFailed

    from magpiary import modes

    done = 0
    for item in store.due_for_deep():
        # Private mode, or Deeper dive turned off after it was queued: nothing goes to any AI; it waits, queued.
        if modes.current(store) == "private" or (asker is None and not deepdive.enabled(store)):
            return done
        url = item["canonical_url"]
        store.deep_running(url)
        progress = activity.begin("process", item) if activity else NO_PROGRESS
        try:
            chosen = None if asker else deepdive.engine(store)
            real = asker or deepdive.asker_for(chosen)

            def ask(*args, real=real, chosen=chosen):
                # checked again before every request, not only at the start: Private, Deeper dive off, or its engine
                # stopped in AI keys mid-dive sends nothing more (review 3, 4 Nov 2026)
                now = None if asker else deepdive.engine(store)
                if modes.current(store) == "private" or (asker is None and (
                        not deepdive.enabled(store) or not now or now["kind"] != chosen["kind"] or now.get("key") != chosen.get("key"))):
                    raise _DeepStopped
                return real(*args)
            result = deepdive.run(item, store, ask, progress=progress)
        except _DeepStopped:
            store.deep_requeue(url)
            log("deeper dive stopped: Private mode, switched off, or its engine changed; it waits")
            return done
        except BrainFailed as err:
            store.deep_failed(url, err.detail)
            log(f"deeper dive failed: {err.reason}")
            continue
        except Exception as err:  # one broken post must not stop the rest
            store.deep_failed(url, type(err).__name__)
            log(f"deeper dive failed: {type(err).__name__}")
            continue
        finally:
            if activity:
                activity.end("process")
        store.deep_done(url, deepdive.as_text(result))
        _rewrite_note(item, notes_dir)
        done += 1
    return done


def _rewrite_note(item: dict, notes_dir: Path) -> None:
    """The post's Markdown note again, now with its Deeper dive section."""
    from magpiary.process import write_note

    folder = Path(item["archive_dir"])
    record = _load_json(folder / "record.json")
    if not record:
        return
    transcript = (_load_json(folder / "transcript.json") or {}).get("segments")
    try:
        write_note(item, _meta(item), record, transcript, notes_dir / f"{folder.name}.md")
    except (OSError, KeyError):
        pass


def _with_deep(record: dict, folder: Path) -> dict:
    """The record plus the things its deeper dive named, so the link search looks for them too."""
    deep = _load_json(folder / "deep.json")
    if not deep or not deep.get("named"):
        return record
    record = dict(record)
    targets, items = list(record.get("link_targets") or []), list(record.get("list_items") or [])
    from magpiary.deepdive import tidy_named

    for n in tidy_named(deep["named"]):  # an older deep.json has no role: those stay "passing", as before
        if n["kind"] in ("video", "article"):
            items.append({"name": n["name"], "kind": n["kind"], "by": "", "note": "", "slide": 0})
        else:
            targets.append({"name": n["name"], "kind": n["kind"], "role": n.get("role") or "passing",
                            "what": n.get("what") or "", "domain": n.get("domain") or ""})
    record["link_targets"], record["list_items"] = targets, items
    return record


def _meta(item: dict) -> dict:
    try:
        return json.loads((Path(item["archive_dir"]) / "meta.json").read_text())
    except (OSError, ValueError):
        return {}


def link_pause(source: str) -> None:
    """GitHub allows about 10 searches a minute without a login; OpenStreetMap and Wikidata ask for one request
    a second."""
    time.sleep({"github": 6.5, "github_guess": 1.0, "catalog_skill": 1.0, "places": 1.1, "wikidata": 1.1,
                "search": 1.1, "youtube": 1.0, "crossref": 0.5, "alternativeto": 2.0}.get(source, 0.3))


SEARCH_LIMIT = 500  # web searches a month, whatever the provider allows (Settings can change it)


def searches_used(store: Store) -> int:
    month, _, count = store.get_setting("search_month", "").partition(":")
    return int(count or 0) if month == time.strftime("%Y-%m") else 0


def web_search(store: Store, key):
    """The owner's search key as a search, counted against the monthly limit. None without a key."""
    from magpiary.links import brave, counted, http_get, tavily

    if key is None:
        return None
    search = tavily(key.secret) if key.provider == "tavily" else brave(key.secret, http_get)
    limit = int(store.get_setting("search_limit", str(SEARCH_LIMIT)) or SEARCH_LIMIT)

    def spend():
        store.set_setting("search_month", f"{time.strftime('%Y-%m')}:{searches_used(store) + 1}")
    return counted(search, lambda: searches_used(store), spend, limit)


def links_due(store: Store, activity=None, get=None, pause: Callable[[str], None] = link_pause,
              key_source=None, log: Callable[[str], None] = lambda m: None) -> int:
    """Find links for summarised items with the free directories and, if the owner added one, a web search key
    (Tavily or Brave). Never uses the AI key. Returns how many items were done."""
    from magpiary import keys as keyring
    from magpiary.links import find_links, http_get, youtube_search

    key_source = key_source or keyring
    get = get or http_get
    done = 0
    for item in store.due_for_links():
        forced = bool(item.get("links_force"))
        if store.paused("links") and not forced:
            return done
        folder = Path(item["archive_dir"])
        try:
            record = _with_deep(json.loads((folder / "record.json").read_text()), folder)
        except (OSError, ValueError):
            store.save_found_links(item["canonical_url"], [])
            continue
        comments = None
        try:
            comments = json.loads((folder / "discussion.json").read_text())
        except (OSError, ValueError):
            pass
        search = web_search(store, key_source.search_key())
        progress = activity.begin("process", item) if activity else None
        if progress:
            progress.step("links")
        try:
            meta = _meta(item)
            found = find_links(record, meta.get("text") or "", item.get("transcript_text") or "", comments,
                               get=get, search=search, skip=store.removed_links(item["canonical_url"]),
                               author=meta.get("author") or "", pause=pause,
                               videos=youtube_search() if record.get("list_items") else None)
        except Exception as err:  # one bad page must not stop the rest; the links already found stay
            log(f"link search failed: {type(err).__name__}")
            found = None
        finally:
            if activity:
                activity.end("process")
        had = [l for l in store.links_for(item["canonical_url"]) if l.get("origin") == "auto" and not l.get("removed")]
        if found is None or (not found and had):  # failed, or nothing at all (offline?): keep what was there
            store.save_found_links(item["canonical_url"], [], status="done", keep=True)
        else:
            store.save_found_links(item["canonical_url"], found)
        done += 1
    return done


def screen_due(store: Store, activity=None, read=None, log: Callable[[str], None] = lambda m: None, limit: int = 5) -> int:
    """Read the text on screen in a few posts that have not had it read (quietly, after summaries). Returns how many."""
    from magpiary import ocr

    done = 0
    for item in store.due_for_screen(limit):
        folder = Path(item["archive_dir"])
        meta = _meta(item)
        frames = _load_json(folder / "frames.json") or []
        photos = [m for m in meta.get("media") or [] if m.lower().endswith(ocr.IMAGE)][:10]
        progress = activity.begin("process", item) if activity else None
        if progress:
            progress.step("screen")
        try:
            known = ocr.known_words(item.get("title"), item.get("ai_title"), item.get("caption"), item.get("summary"), item.get("transcript_text"))
            lines = ocr.read_post(folder, frames, photos, read or ocr.read_lines, known)
            (folder / "ocr.json").write_text(json.dumps(lines, ensure_ascii=False))
            store.screen_done(item["canonical_url"], " ".join(l["text"] for l in lines))
            done += 1
        except Exception as err:  # one unreadable post must not stop the rest
            log(f"on-screen text failed: {type(err).__name__}")
            store.screen_done(item["canonical_url"], "")
        finally:
            if activity:
                activity.end("process")
    return done




def icons_due(store: Store, get=None, log: Callable[[str], None] = lambda m: None, limit: int = 8) -> int:
    """Fetch the little site icon for a few sites that have none yet (sites posts were saved from, then link sites), once
    each, on this Mac. Returns how many were kept."""
    from magpiary import icons

    kept = 0
    for host in icons.due(store.site_urls() + store.link_urls(), limit):
        try:
            kept += bool(icons.fetch(host, get))
        except Exception as err:  # one odd site must not stop the rest
            log(f"site icon failed: {type(err).__name__}")
    return kept


def related_due(store: Store, embedder=None, log: Callable[[str], None] = lambda m: None) -> int:
    """Meaning vectors for new or changed items (on this Mac), then piles again if anything changed or the
    owner asked for it. Returns how many vectors were made."""
    from magpiary.embed import EmbedFailed
    from magpiary.related import rebuild_piles, refresh_vectors

    try:
        made = refresh_vectors(store, embedder) if embedder else refresh_vectors(store)
    except EmbedFailed as err:
        log(f"related: {err}")
        return 0
    if made or store.get_setting("piles_dirty", "1") == "1":
        store.set_setting("piles_dirty", "0")
        rebuild_piles(store)
    return made

