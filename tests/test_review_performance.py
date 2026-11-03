"""Synthetic regression cases for measured read-path candidates; no network or model."""

from datetime import datetime, timedelta, timezone

import pytest

from magpiary import spotlight
from magpiary.hub import Hub
from magpiary.store import Store


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path / 'library.db')
    folder = tmp_path / 'archive'
    folder.mkdir()
    (folder / 'meta.json').write_text('{"media": ["media-01.mp4"], "duration": 30}')
    now = datetime.now(timezone.utc)
    urls = [f'https://example.invalid/{i}' for i in range(405)]
    with store._db:
        for i, url in enumerate(urls):
            store._db.execute(
                'INSERT INTO items(canonical_url,source,status,shelf,created_at,updated_at,last_shared_at,'
                'title,caption,summary,transcript_text,ai_status,ai_type,author,archive_dir,thumb) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (url, 'other', 'archived', 'trash' if i == 404 else 'archive' if i == 403 else 'inbox',
                 (now - timedelta(hours=i)).isoformat(), now.isoformat(), (now - timedelta(hours=i)).isoformat(),
                 f'Save {i}', 'caption', f'Full summary {i}', 'spoken text', 'done', 'other', 'Author',
                 str(folder), 'thumbnail.jpg'))
            store._db.executemany('INSERT INTO tags VALUES (?,?)', [(url, 'zeta'), (url, 'alpha')])
            store._db.execute('INSERT INTO stats(canonical_url,likes,comments) VALUES (?,?,?)', (url, i, i % 7))
        store._db.execute("INSERT INTO piles(id,name,auto_name,created_at,seen_at) VALUES (1,'Pile','Pile',?,?)",
                          (now.isoformat(), now.isoformat()))
        store._db.executemany("INSERT INTO pile_items(pile_id,canonical_url,origin) VALUES (1,?,'owner')", [(u,) for u in urls])
    store.set_setting('ai_mode', 'private')
    yield store, Hub(store, folder), urls
    store.close()


@pytest.mark.parametrize('values', [[], [2], [1, 1, 1], [3, 0, 3, 2, 8, 2], list(range(401))])
def test_percentile_ranks_preserve_exact_ties_and_shrinkage(values):
    expected = {}
    n = len(values)
    for i, value in enumerate(values):
        below = sum(x < value for x in values)
        same = sum(x == value for x in values)
        rank = (below + (same - 1) / 2) / max(n - 1, 1) if n > 1 else .5
        expected[str(i)] = (n * rank + spotlight.SHRINK * .5) / (n + spotlight.SHRINK)
    assert spotlight._percentiles({str(i): v for i, v in enumerate(values)}) == expected


def test_batch_reads_preserve_order_duplicates_missing_and_sorted_tags(library):
    store, _, urls = library
    requested = list(reversed(urls)) + ['missing', urls[0]]
    rows = store.items_by_urls(requested)
    assert rows == [store.item_by_id(store.id_for(u)) for u in requested if u != 'missing']
    assert store.items_by_ids([r['id'] for r in rows] + [99999]) == rows
    assert store.items_by_urls([]) == store.items_by_ids([]) == []


def test_ask_pile_and_board_keep_member_order_and_exclude_trash(library, monkeypatch):
    from magpiary import boards
    store, hub, urls = library
    expected = [store.item_by_id(store.id_for(u)) for u in urls[:-1]]
    assert hub.ask_scope('pile:1') == ('Pile', expected)
    monkeypatch.setattr(store, 'board', lambda ident: {'name': 'Board'})
    monkeypatch.setattr(boards, 'view', lambda store, ident: {'cards': [{'url': u} for u in reversed(urls)]})
    assert hub.ask_scope('board:0123456789abcdef') == ('Board', list(reversed(expected)))
    assert hub.ask_scope('pile:99999') is None


@pytest.mark.parametrize('query', [{}, {'sort': 'popular'}, {'sort': 'trending'}, {'tag': 'alpha'},
                                   {'type': 'other'}, {'author': 'Author'}, {'part': '1'}, {'attention': '1'}])
def test_compact_wall_preserves_full_row_rendering_and_selection(library, monkeypatch, query):
    store, hub, _ = library
    monkeypatch.setattr("magpiary.hub.secrets.token_urlsafe", lambda n: "synthetic-nonce")
    original = store.hub_items
    measured = hub.wall_page(query).body
    def full_rows(*args, **kwargs):
        kwargs.pop('compact', None)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, 'hub_items', full_rows)
    assert hub.wall_page(query).body == measured


def test_closed_related_never_loads_library_or_vectors_and_explicit_tab_still_works(library, monkeypatch):
    store, hub, urls = library
    def refuse(*args):
        pytest.fail('closed Related tab must not load the library or vectors')
    monkeypatch.setattr(hub, 'related_library', refuse)
    monkeypatch.setattr(store, 'vectors', refuse)
    for tab in ('', 'sum', 'links', 'tr', 'det'):
        body = hub.card_page(1, fragment=True, tab=tab).body.decode()
        assert 'data-related-src=' in body and '?tab=rel' in body
    monkeypatch.setattr(hub, 'related_library', lambda: None)
    monkeypatch.setattr('magpiary.hub_card.rel.related', lambda lib, url: [{'row': store.item_by_id(2), 'reason': 'Both tagged alpha'}])
    body = hub.card_page(1, fragment=True, tab='rel').body.decode()
    assert 'Both tagged alpha' in body and 'data-related-src=' not in body
    store.set_shelf(1, 'trash')
    body = hub.card_page(1, fragment=True).body.decode()
    assert 'data-related-src=' not in body


def test_lexical_agent_search_limits_hydration_after_hidden_saves(library):
    from magpiary import library as agent_library
    store, _, urls = library
    with store._db:
        store._db.executemany('INSERT INTO search(url,title) VALUES (?,?)', [(u, 'synthetic') for u in urls])
        store._db.executemany('INSERT INTO tags VALUES (?,?)', [(u, 'private') for u in urls[:20]])
    store.set_setting('agents_hide_tags', 'private')
    expected = [i for i in store.hub_items('kept', 'synthetic', limit=5000) if i['canonical_url'] not in set(urls[:20])][:10]
    out = agent_library.search(store, 'synthetic', limit=10, words_only=True)
    assert [r['id'] for r in out['results']] == [i['id'] for i in expected]
    assert out['count'] == 10 and out['search'] == 'words'
