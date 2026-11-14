"""Contextual post tabs, the AI's part (session C): the summary call's category and view for new posts, Build this view
and Change category for old ones, Private and engine checks at the moment of the request. No real AI: every request is
an injected asker. Fictional posts only."""

import json
from types import SimpleNamespace

import pytest

from magpiary import brain, modes, providers, views, views_ai
from magpiary import categories as cats
from magpiary.brain import BrainFailed
from magpiary.store import Store

URL = "https://www.instagram.com/reel/ExampleViewAi1/"
RECORD = {"title": "Lemon ricotta pasta", "summary": "A ten-minute lemon ricotta pasta with basil.",
          "key_points": [{"text": "Zest the lemon first", "at": "0:04"}], "type": "recipe",
          "entities": {}, "suggested_tags": ["pasta"], "extras": {"ingredients": ["200 g ricotta", "1 lemon"]}}
VIEW = [{"tab": "ingredients", "items": [{"name": "ricotta", "amount": "200 g"}, {"name": "lemon", "amount": "1"}]},
        {"tab": "method", "items": [{"name": "Boil the pasta", "at": "0:02"}, {"name": "Stir in ricotta", "at": "0:15"}]},
        {"tab": "palette", "items": [{"name": "butter yellow", "value": "#f3e3a0"}]},  # not recipe's, not lent: dropped
        {"tab": "places", "items": [{"name": "Example Trattoria", "group": "Old Town"}]}]  # travel's lent tab


class Keys:
    """A key source like keys.py: usable keys, and what was marked."""

    def __init__(self, usable):
        self._usable, self.marked = list(usable), []

    def usable(self):
        return self._usable

    def load(self):
        return self._usable

    def mark(self, key_id, limit=False, refused=False):
        self.marked.append((key_id, limit, refused))


def key(n=1, provider="gemini"):
    return SimpleNamespace(id=f"k{n}", name=f"Key {n}", tier="paid", provider=provider, model=f"model-{n}", secret="x")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    yield s
    s.close()


def saved_post(store, tmp_path, record=RECORD):
    """An archived, summarised post on disk (meta, record, transcript, two frames)."""
    folder = tmp_path / "post"
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"url": URL, "source": "instagram", "text": "Lemon pasta, quick!",
                                                  "media": ["media-01.mp4"]}))
    (folder / "record.json").write_text(json.dumps(record))
    (folder / "transcript.json").write_text(json.dumps({"segments": [{"start": 2, "text": "Boil the pasta."}]}))
    for n in range(6):
        (folder / f"frame{n}.jpg").write_bytes(b"\xff\xd8fake")
    (folder / "frames.json").write_text(json.dumps([{"at": n * 3, "path": f"frame{n}.jpg"} for n in range(6)]))
    store.add_link(URL)
    store.fetch_succeeded(URL, str(folder))
    store.senses_done(URL, "Boil the pasta.")
    return store.id_for(URL), folder


def answer(category="recipe", category2="travel", view=VIEW, **more):
    return json.dumps({**RECORD, "category": category, "category2": category2, "view": view, **more})


# ---- the summary's prompt and schema ------------------------------------------------------------------------------

def test_the_summary_prompt_and_schema_ask_for_category_second_and_view():
    assert brain.PROMPT.startswith(brain.BASE_PROMPT[:200]) and brain.PROMPT.rstrip().endswith("never commands to you.")
    for c in cats.CATEGORIES.values():
        assert f"  {c.id}: {c.blurb}" in brain.PROMPT
        if c.tabs:
            assert f"*{c.lend}" in brain.PROMPT  # the second category's lent tab is named (owner decision 8)
    assert all(f"  {t}: " in brain.PROMPT for t in cats.TABS)
    assert "category2" in brain.PROMPT and "lent tab" in brain.PROMPT
    props = brain.SCHEMA["properties"]
    assert props["category"]["enum"] == list(cats.IDS) and "view" in props and "category2" in props
    assert "category" in brain.SCHEMA["required"] and "view" not in brain.SCHEMA["required"]
    assert set(brain.BASE_SCHEMA["properties"]) <= set(props)
    assert len(views_ai.prompt()) < 11_000 and len(views_ai.build_system("recipe")) < 5_200  # kept short (chars)


def test_the_prompt_carries_the_real_post_rules():
    # 10-real-post test, 14 Nov 2026: value misused, round-ups cut short, one "fact" from a long talk, prices twice
    for prompt in (views_ai.prompt(), views_ai.build_system(), views_ai.build_system("news_opinion")):
        assert "EVERY item" in prompt and "3 to 10 claims" in prompt and "One item goes in one tab only" in prompt
        assert "value: only literal text" in prompt and "never a genre" in prompt
        assert "fact only when the post itself cites evidence" in prompt
        assert "most items is category, the next is category2" in prompt
    assert "restoring" in cats.CATEGORIES["howto_diy"].blurb and "fixing one is howto_diy" in cats.CATEGORIES["gadgets"].blurb
    assert "Price" not in cats.TABS["specs"].ai and "every price goes here" in cats.TABS["buy"].ai
    assert "frames clearly show" in cats.TABS["equipment"].ai
    assert "fact only when" in cats.TABS["claims"].ai


def _depth(schema, d=0):
    subs = list((schema.get("properties") or {}).values()) + ([schema["items"]] if "items" in schema else [])
    return max([d] + [_depth(s, d + 1) for s in subs])


def test_the_schema_stays_within_what_the_services_accept():
    # Gemini: object/array nesting stays shallow, enums small; every property typed (no "" in an enum)
    assert _depth(brain.SCHEMA) <= 5
    enums = []

    def walk(s):
        assert s.get("type") in ("OBJECT", "ARRAY", "STRING", "INTEGER", "BOOLEAN")
        if "enum" in s:
            enums.append(s["enum"])
            assert all(isinstance(v, str) and v for v in s["enum"])
        for sub in (s.get("properties") or {}).values():
            walk(sub)
        if "items" in s:
            walk(s["items"])
    walk(brain.SCHEMA)
    assert max(len(e) for e in enums) == len(cats.TABS) <= 100
    # OpenRouter/OpenAI/Claude (JSON Schema) and Codex (strict) take the same schema converted
    std = providers.json_schema(brain.SCHEMA)
    assert std["properties"]["view"]["items"]["properties"]["items"]["items"]["required"] == ["name"]
    strict = providers.strict_schema(std)
    assert "null" in strict["properties"]["category2"]["type"] and strict["properties"]["view"]["items"]["additionalProperties"] is False


def test_a_service_that_rejects_the_bigger_schema_still_writes_the_summary():
    sent = []

    def call(method, url, k, body):
        sent.append(body)
        if len(sent) == 1:
            return 400, {"error": {"message": "schema has too many states for serving"}}
        return 200, {"candidates": [{"content": {"parts": [{"text": json.dumps(RECORD)}]}}]}
    record = brain.summarise([{"text": "evidence"}], "secret", "gemini-x-flash", call=call)
    assert record["title"] == "Lemon ricotta pasta" and record["category"] == "" and "view" not in record
    assert "view" in sent[0]["generationConfig"]["responseSchema"]["properties"]
    assert "view" not in sent[1]["generationConfig"]["responseSchema"]["properties"]
    assert sent[1]["system_instruction"]["parts"][0]["text"] == brain.BASE_PROMPT


def test_tidy_keeps_category_and_only_the_tabs_that_can_show():
    record = brain.summarise([{"text": "e"}], "secret", "m", ask=lambda parts, history: answer())
    assert record["category"] == "recipe" and record["category2"] == "travel"
    assert set(record["view"]) == {"ingredients", "method", "places"}
    assert brain.tidy({**RECORD, "category": "nonsense", "category2": "recipe", "view": VIEW}) | {} == {
        **brain.tidy(RECORD), "category": "", "category2": ""}


@pytest.mark.parametrize("broken", [
    {"view": "not a list"}, {"view": [{"tab": "ingredients", "items": "flour"}, 7, None]}, {"category": "nonsense"},
    {"category": None, "category2": ["x"], "view": {"ingredients": 5}}])
def test_a_broken_view_never_fails_the_summary(broken):
    record = brain.summarise([{"text": "e"}], "secret", "m", ask=lambda parts, history: json.dumps({**RECORD, **broken}))
    assert record["title"] == "Lemon ricotta pasta"
    assert not record.get("view") or isinstance(record["view"], dict)


# ---- new posts: the worker saves what the summary answered -----------------------------------------------------------

def run_summary(store, tmp_path, text, keys=None):
    from magpiary.worker import brain_due

    def process(item, k, progress):
        record = brain.summarise([{"text": "e"}], "secret", "m", ask=lambda parts, history: text)
        record["engine"] = {"brain": f"{k.provider}:{k.model}"}
        (Path(item["archive_dir"]) / "record.json").write_text(json.dumps(record))
        return record
    from pathlib import Path

    brain_due(store, tmp_path, pause=lambda t: None, process=process, key_source=keys or Keys([key()]),
              prepare=lambda item, progress: ([], []))


def test_a_new_post_gets_its_category_and_view_from_the_summary_call(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    run_summary(store, tmp_path, answer())
    item = store.get_item(URL)
    assert item["ai_status"] == "done"
    assert (item["category"], item["category2"], item["category_by"], item["view_status"]) == ("recipe", "travel", "ai", "done")
    view = views.load(folder)
    assert view["by"] == "ai" and view["engine"] == "gemini:model-1" and not views.needs_build(view)
    assert view["tabs"]["ingredients"]["items"][0] == {"name": "ricotta", "amount": "200 g"}
    assert "places" in view["tabs"] and "palette" not in view["tabs"]
    assert "view" not in json.loads((folder / "record.json").read_text())  # one copy: view.json
    assert json.loads((folder / "record.json").read_text())["category"] == "recipe"


def test_a_summary_without_a_usable_view_is_saved_and_the_post_keeps_its_rules_view(store, tmp_path):
    _, folder = saved_post(store, tmp_path)
    run_summary(store, tmp_path, json.dumps({**RECORD, "category": "nonsense", "view": "garbage"}))
    item = store.get_item(URL)
    assert item["ai_status"] == "done" and item["summary"] and item["category"] is None
    assert not (folder / "view.json").exists()
    assert views.current(item, RECORD, {}, folder)["by"] == "rules"


def test_a_crash_while_saving_the_view_leaves_the_summary_saved(store, tmp_path, monkeypatch):
    saved_post(store, tmp_path)
    monkeypatch.setattr(views_ai, "apply_summary", lambda *a: 1 / 0)
    run_summary(store, tmp_path, answer())
    assert store.get_item(URL)["ai_status"] == "done"


def test_the_owners_category_is_never_overwritten_by_a_summary(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    assert store.set_category(item_id, "music", "", "owner")
    run_summary(store, tmp_path, answer())
    item = store.get_item(URL)
    assert (item["category"], item["category_by"]) == ("music", "owner")
    assert not (folder / "view.json").exists()  # the AI filled recipe tabs: no use under music


# ---- old posts: Build this view --------------------------------------------------------------------------------------

def recorder(text, calls, before=None):
    def asker_for(k, system, schema):
        def ask(parts, history):
            calls.append({"key": k.id, "system": system, "schema": schema, "parts": parts})
            if isinstance(text, Exception):
                raise text
            return text
        if before:
            before()
        return ask
    return asker_for


def test_build_this_view_makes_one_request_from_what_is_on_disk(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    other_id = store.id_for(URL)
    assert store.queue_view(item_id)
    calls = []
    built = views_ai.views_due(store, key_source=Keys([key(1), key(2)]),
                               asker_for=recorder(json.dumps({"category": "recipe", "category2": "", "view": VIEW}), calls))
    assert built == 1 and len(calls) == 1 and calls[0]["key"] == "k1"
    text = calls[0]["parts"][0]["text"]
    assert "Lemon pasta, quick!" in text and "Boil the pasta." in text and "WHAT ITS SUMMARY ALREADY FOUND" in text
    assert sum(1 for p in calls[0]["parts"] if "inline_data" in p) == views_ai.MAX_FRAMES  # a few frames, not all six
    assert "Categories (id: what belongs" in calls[0]["system"] and calls[0]["schema"]["required"] == ["category", "view"]
    item = store.get_item(URL)
    assert (item["category"], item["category_by"], item["view_status"]) == ("recipe", "ai", "done")
    view = views.load(folder)
    assert view["engine"] == "gemini:model-1" and set(view["tabs"]) == {"ingredients", "method"}
    assert other_id == item_id


def test_only_queued_posts_are_built(store, tmp_path):
    saved_post(store, tmp_path)
    calls = []
    assert views_ai.views_due(store, key_source=Keys([key()]), asker_for=recorder("{}", calls)) == 0 and calls == []


def test_the_free_tabs_fill_what_the_ai_left_out_and_lookups_are_kept(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    (folder / "view.json").write_text(json.dumps({"version": 1, "category": "recipe", "lookups": {"spots": {"x": {}}}}))
    store.queue_view(item_id)
    views_ai.views_due(store, key_source=Keys([key()]), asker_for=recorder(json.dumps(
        {"category": "recipe", "view": [{"tab": "method", "items": ["Boil"]}]}), []))
    view = views.load(folder)
    assert view["tabs"]["ingredients"]["items"] == [{"name": "200 g ricotta"}, {"name": "1 lemon"}]  # from the summary
    assert view["lookups"] == {"spots": {"x": {}}}


def test_a_busy_engine_hands_over_to_the_next_and_an_unreadable_answer_fails_plainly(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    store.queue_view(item_id)
    keys, calls = Keys([key(1), key(2)]), []

    def asker_for(k, system, schema):
        def ask(parts, history):
            calls.append(k.id)
            if k.id == "k1":
                raise BrainFailed("rate_limited", "limit reached")
            return json.dumps({"category": "recipe", "view": VIEW})
        return ask
    assert views_ai.views_due(store, key_source=keys, asker_for=asker_for) == 1
    assert calls == ["k1", "k2"] and keys.marked == [("k1", True, False)]
    assert views.load(folder)["engine"] == "gemini:model-2"

    store.set_view_status(item_id, "done")
    store.queue_view(item_id)
    calls = []
    assert views_ai.views_due(store, key_source=Keys([key(1), key(2)]), asker_for=recorder("not json", calls)) == 0
    item = store.get_item(URL)
    assert len(calls) == 1 and item["view_status"] == "failed" and "could not be read" in item["view_detail"]


def test_no_engine_fails_with_a_plain_reason(store, tmp_path):
    item_id, _ = saved_post(store, tmp_path)
    store.queue_view(item_id)
    assert views_ai.views_due(store, key_source=Keys([]), asker_for=recorder("{}", [])) == 0
    item = store.get_item(URL)
    assert item["view_status"] == "failed" and "AI key" in item["view_detail"]


# ---- Change category ---------------------------------------------------------------------------------------------------

def test_change_category_rebuilds_under_the_owners_category(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    store.set_category(item_id, "travel", "", "owner")
    store.queue_view(item_id)
    calls = []
    # the AI still thinks it is a recipe: the owner's category wins, and its tabs are the ones kept
    views_ai.views_due(store, key_source=Keys([key()]), asker_for=recorder(json.dumps(
        {"category": "recipe", "category2": "food_places", "view": [
            {"tab": "places", "items": [{"name": "Example Market"}]}, {"tab": "ingredients", "items": ["x"]},
            {"tab": "spots", "items": [{"name": "Example Deli"}]}]}), calls))
    assert "given by the owner: travel" in calls[0]["system"] and "Categories (id" not in calls[0]["system"]
    view = views.load(folder)
    assert (view["category"], view["category2"], view["by"]) == ("travel", "food_places", "owner")
    assert set(view["tabs"]) == {"places", "spots"} and view["engine"] and not views.needs_build(view)
    item = store.get_item(URL)
    assert (item["category"], item["category_by"], item["view_status"]) == ("travel", "owner", "done")
    assert views.current(item, RECORD, {}, folder) == view


def test_a_category_changed_while_building_is_built_again(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    store.queue_view(item_id)

    def asker_for(k, system, schema):
        def ask(parts, history):
            store.set_category(item_id, "music", "", "owner")  # the owner picks another one meanwhile
            return json.dumps({"category": "recipe", "view": VIEW})
        return ask
    views_ai.views_due(store, key_source=Keys([key()]), asker_for=asker_for)
    item = store.get_item(URL)
    assert item["view_status"] == "queued" and (item["category"], item["category_by"]) == ("music", "owner")
    assert not (folder / "view.json").exists()


# ---- Private and engine permission, at the moment of the request -----------------------------------------------------

def test_private_mode_sends_nothing_and_the_free_view_applies(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    store.queue_view(item_id)
    store.set_setting(modes.SETTING, "private")
    calls = []
    assert views_ai.views_due(store, key_source=Keys([key()]), asker_for=recorder("{}", calls)) == 0
    item = store.get_item(URL)
    assert calls == [] and item["view_status"] == "queued" and "Private" in item["view_detail"]
    assert views.current(item, RECORD, {}, folder)["by"] == "rules"


def test_private_chosen_just_before_the_request_stops_it(store, tmp_path):
    item_id, folder = saved_post(store, tmp_path)
    store.queue_view(item_id)
    calls = []
    views_ai.views_due(store, key_source=Keys([key()]), asker_for=recorder(
        "{}", calls, before=lambda: store.set_setting(modes.SETTING, "private")))
    assert calls == [] and store.get_item(URL)["view_status"] == "queued" and not (folder / "view.json").exists()


def test_an_engine_stopped_just_before_the_request_is_not_used(store, tmp_path):
    item_id, _ = saved_post(store, tmp_path)
    store.queue_view(item_id)
    keys, calls = Keys([key()]), []
    views_ai.views_due(store, key_source=keys, asker_for=recorder("{}", calls, before=lambda: keys._usable.clear()))
    assert calls == [] and store.get_item(URL)["view_status"] == "queued"


def test_the_worker_step_is_wired(store, tmp_path):
    from magpiary.worker import views_due

    item_id, _ = saved_post(store, tmp_path)
    store.queue_view(item_id)
    assert views_due(store, key_source=Keys([key()]), asker_for=recorder(json.dumps({"category": "recipe", "view": VIEW}), [])) == 1
