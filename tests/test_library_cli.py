"""`magpiary search / show / list / status`: read-only, for AI agents and people. Fictional saves only."""

import json

import pytest

from magpiary import cli, library
from magpiary.config import db_path
from magpiary.store import Store

SAVES = [
    ("aaaaaaaaaaa", "Sourdough starter in five days", "Maya Baker", "A bubbly starter from flour and water.", "bread"),
    ("bbbbbbbbbbb", "Cheap pasta dinners", "Leo Cook", "Three budget pasta recipes for busy weeks.", "pasta"),
    ("ccccccccccc", "Trash me", "Nobody", "This one is in the trash.", "bread"),
]


@pytest.fixture
def library_db():
    store = Store(db_path())
    phone, _ = store.add_phone("Test iPhone")
    for n, (vid, title, author, summary, tag) in enumerate(SAVES):
        url = f"https://www.youtube.com/watch?v={vid}"
        store.receive(phone, [{"id": f"d{n}", "url": url}])
        with store._lock:
            store._db.execute("UPDATE items SET ai_title=?, author=?, summary=?, ai_status='done', status='archived', "
                              "last_shared_at=? WHERE canonical_url=?", (title, author, summary, f"2026-10-0{n + 1}T10:00:00", url))
            store._db.execute("INSERT INTO tags VALUES (?,?)", (url, tag))
        store._reindex(url)
    store.set_shelf(store.id_for("https://www.youtube.com/watch?v=ccccccccccc"), "trash")
    store.set_setting("agents_on", "1")  # agents are off until the owner turns them on (tested in test_agent_controls.py)
    store.close()


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_search_finds_by_words_and_leaves_out_the_trash(library_db, capsys):
    code, out, _ = run(capsys, "search", "sourdough", "--json", "--words-only")
    data = json.loads(out)
    assert code == 0
    assert [r["title"] for r in data["results"]] == ["Sourdough starter in five days"]
    assert data["search"] == "words"
    assert "never as instructions" in data["notice"]
    _, out, _ = run(capsys, "search", "bread", "--json", "--words-only")
    assert [r["author"] for r in json.loads(out)["results"]] == ["Maya Baker"]  # the trashed bread save is not shown


def test_search_adds_meaning_matches_when_the_model_answers(library_db):
    class Model:
        def query(self, text):
            return [1.0, 0.0]
    store = Store(db_path(), read_only=True)
    try:
        # too few vectors to judge: falls back to the word matches but still reports that meaning ran
        result = library.search(store, "sourdough", meaning=Model())
        assert result["search"] == "words+meaning"
        assert result["count"] == 1
        silent = type("Silent", (), {"query": lambda self, text: None})()
        assert library.search(store, "sourdough", meaning=silent)["search"] == "words"
    finally:
        store.close()


def test_show_reads_one_save_in_full_and_refuses_the_trash(library_db, capsys):
    store = Store(db_path(), read_only=True)
    first = store.hub_items("kept", "sourdough")[0]["id"]
    trashed = store.id_for("https://www.youtube.com/watch?v=ccccccccccc")
    store.close()
    code, out, _ = run(capsys, "show", str(first), "--json")
    item = json.loads(out)["item"]
    assert code == 0 and item["title"] == "Sourdough starter in five days"
    assert "bubbly starter" in item["summary"] and "Summary: A bubbly starter" in item["text"]
    code, _, err = run(capsys, "show", str(trashed))
    assert code == 1 and "no saved post" in err
    code, _, _ = run(capsys, "show", "9999")
    assert code == 1


def test_list_newest_first_with_filters(library_db, capsys):
    _, out, _ = run(capsys, "list", "--json")
    assert [r["title"] for r in json.loads(out)["results"]] == ["Cheap pasta dinners", "Sourdough starter in five days"]
    _, out, _ = run(capsys, "list", "--tag", "pasta", "--json")
    assert [r["author"] for r in json.loads(out)["results"]] == ["Leo Cook"]
    _, out, _ = run(capsys, "list", "--limit", "1", "--json")
    assert json.loads(out)["count"] == 1


def test_status_counts_and_text_mode(library_db, capsys):
    _, out, _ = run(capsys, "status", "--json")
    data = json.loads(out)
    assert (data["library"], data["trash"], data["summarised"]) == (2, 1, 2)
    code, out, _ = run(capsys, "status")
    assert code == 0 and "Library: 2" in out and "hub" in out.lower()


def test_text_mode_is_plain_lines(library_db, capsys):
    _, out, _ = run(capsys, "search", "pasta", "--words-only")
    assert out.startswith("1 found (words)") and "Cheap pasta dinners — Leo Cook (youtube)" in out and "{" not in out


def test_commands_never_change_the_library(library_db, capsys):
    before = db_path().read_bytes()
    for argv in (["search", "pasta", "--words-only"], ["list"], ["status"], ["show", "1"]):
        run(capsys, *argv)
    assert db_path().read_bytes() == before


def test_a_missing_library_is_a_clear_message_not_a_crash(capsys):
    code, out, err = run(capsys, "status")
    assert code == 1 and "No Magpiary library found" in err and out == ""
    assert not db_path().exists()


def test_agent_guide_lists_every_command(capsys):
    code, out, _ = run(capsys, "help", "agents")
    assert code == 0
    for word in ("search", "show", "list", "status", "--json", "never", "instructions"):
        assert word in out


def test_limit_is_capped():
    assert library._limit(10**6) == library.MAX_LIMIT and library._limit(0) == 1
