"""Links v2: every named thing gets its own home (the product's site, a skill's repository, a book's Wikipedia page,
a cited paper's DOI), with recorded directory and page answers (no live calls)."""

import json
from urllib.parse import quote

import pytest

from magpiary import keys as keyring
from magpiary.hub import rich_text
from magpiary.links import (Found, SearchLimit, Target, check, citations, counted, find_links, name_score, read_page,
                            tavily, targets_for, urls_in)
from magpiary.store import Store
from magpiary.worker import links_due, searches_used, web_search


def pages(mapping):
    """Answers by address prefix, longest prefix first. Anything else is a 404."""
    ordered = sorted(mapping.items(), key=lambda kv: -len(kv[0]))

    def get(url, headers=None):
        for prefix, value in ordered:
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                status, body, *final = value if isinstance(value, tuple) else (200, value)
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                return status, final[0] if final else url, body
        return 404, url, b""
    return get


def site(title, text="", description=""):
    return (f'<html><head><title>{title}</title><meta name="description" content="{description}"></head>'
            f'<body>{text}</body></html>').encode()


def wikidata(name, hits, sparql=None):
    """A Wikidata search for `name` and the SPARQL answer for its chosen entry."""
    answers = {f"https://www.wikidata.org/w/api.php?action=wbsearchentities&language=en&uselang=en&type=item&limit=7"
               f"&format=json&search={quote(name)}": {"search": hits}}
    if sparql is not None:
        answers["https://query.wikidata.org/sparql"] = {"results": {"bindings": sparql}}
    return answers


def binding(**values):
    return {k: {"type": "uri", "value": v} for k, v in values.items()}


def mains(found):
    return {f.name: f.url for f in found if f.role == "main"}


# ---- matching and targets -----------------------------------------------------------------

def test_names_must_really_match():
    assert name_score("frontend-design", "frontend-design") == 3
    assert name_score("Voice Studio", "voice-studio") == 3
    assert name_score("Notion", "Notion Calendar") == 2
    assert name_score("Signal", "Railway") == 0
    assert name_score("Anthropic Skills", "anthropics skills") == 3


def test_urls_are_found_in_text_with_or_without_https():
    assert urls_in("see magpiary.app and https://x.example.dev/a?b=1, or voicestudio.ai.") == [
        "https://magpiary.app", "https://x.example.dev/a?b=1", "https://voicestudio.ai"]


def test_targets_merge_the_ai_tags_with_the_named_things():
    record = {"title": "Three example projects for a studio", "summary": "NocoDB replaces Airtable",
              "link_targets": [{"name": "NocoDB", "kind": "tool", "role": "central", "domain": "nocodb.com",
                                "open_source": True},
                               {"name": "Airtable", "kind": "product", "role": "passing"}],
              "entities": {"tools": ["NocoDB", "Jira", "Google"], "skills_code": ["example-maker/workshop-notes", "workshop-notes"],
                           "people": ["Jules Example", "Casey Example", "Exampleton"]}}
    caption = "Made by Jules Example.\n\nCredits:\n- photo by Casey Example"
    targets, _ = targets_for(record, caption, "", None, author="Someone Else")
    by = {t.name: t for t in targets}
    assert by["NocoDB"].central and by["NocoDB"].domain == "nocodb.com" and by["NocoDB"].open_source
    assert not by["Airtable"].central and not by["Jira"].central and by["Jira"].guessed
    assert by["example-maker/workshop-notes"].kind == "code" and "workshop-notes" not in by  # one thing, given twice
    assert "Jules Example" in by and "Casey Example" not in by and "Exampleton" not in by  # credits and lone surnames
    assert "Someone Else" not in by


def test_the_posts_author_and_big_names_in_passing_get_no_link():
    record = {"summary": "a dashboard", "entities": {"tools": ["Google", "Cloudflare"], "people": ["Jules Example"]}}
    found = find_links(record, "by Jules Example", "", None, get=pages({}), author="Jules Example")
    assert found == []


def test_a_sources_list_becomes_citations():
    caption = ("Why it works.\n\nSources:\n- Sampleton, \"Paper folding trials\", Example Materials Journal 53 (1975); Exampleton, "
               "\"Folded paper as a spring material\", Example Materials Journal 144 (1990)\n- Exampleton to Alex Example (EXAMPLE-LETTER-0001)\n\n"
               "Credits:\n- photo by examplecreator")
    assert citations(caption) == ['Sampleton, "Paper folding trials", Example Materials Journal 53 (1975)',
                                  'Exampleton, "Folded paper as a spring material", Example Materials Journal 144 (1990)',
                                  "Exampleton to Alex Example (EXAMPLE-LETTER-0001)"]


# ---- the official site --------------------------------------------------------------------

JIRA_HITS = [{"id": "Q1", "label": "Jira", "description": "family name"},
             {"id": "Q2", "label": "Jira", "description": "issue-tracking product developed by Atlassian"}]


def test_wikidatas_official_site_is_the_main_link_with_badges():
    record = {"summary": "project management for agencies",
              "link_targets": [{"name": "Jira", "kind": "product", "role": "central", "what": "issue tracking"}]}
    get = pages({**wikidata("Jira", JIRA_HITS, [binding(site="https://www.atlassian.com/software/jira",
                                                        article="https://en.wikipedia.org/wiki/Jira_(software)")]),
                 "https://www.atlassian.com/software/jira": site("Jira | Project management", "issue tracking")})
    found = find_links(record, "", "", None, get=get)
    assert mains(found) == {"Jira": "https://www.atlassian.com/software/jira"}
    assert [(f.source, f.role) for f in found[1:]] == [("Wikipedia", "badge")]


def test_a_typo_on_wikidata_is_not_trusted():
    record = {"summary": "AI video", "link_targets": [{"name": "ExampleFilm", "kind": "tool", "role": "central"}]}
    get = pages({**wikidata("ExampleFilm", [{"id": "Q9", "label": "Examplefilm Studio", "description": "AI video generation website"}],
                            [binding(site="https://examplfilm.example.com")]),
                 "https://examplfilm.example.com": site("Best deals on everything")})
    assert find_links(record, "", "", None, get=get) == []


def test_the_ai_domain_must_carry_the_name_and_fit_the_post():
    record = {"summary": "an open-source Airtable alternative for agencies",
              "link_targets": [{"name": "NocoDB", "kind": "tool", "role": "central", "domain": "nocodb.com",
                                "what": "open-source Airtable alternative"},
                               {"name": "Claude Code", "kind": "tool", "role": "central", "domain": "claude.ai"}]}
    get = pages({"https://nocodb.com": site("NocoDB Cloud", "The open source Airtable alternative"),
                 "https://claude.ai": site("Claude", "Talk with Claude")})
    assert mains(find_links(record, "", "", None, get=get)) == {"NocoDB": "https://nocodb.com/"}


def test_a_parked_domain_fails():
    record = {"summary": "notes", "link_targets": [{"name": "Example Notes", "kind": "tool", "role": "central",
                                                    "domain": "examplenotes.example.com"}]}
    get = pages({"https://examplenotes.example.com": site("examplenotes.example.com", "This domain is for sale")})
    assert find_links(record, "", "", None, get=get) == []


def test_an_open_source_products_repo_homepage_is_its_site_and_the_repo_a_badge():
    record = {"title": "5 repos", "summary": "an invented workflow assistant for a seed library",
              "link_targets": [{"name": "ExampleFlow", "kind": "tool", "role": "central", "open_source": True}]}
    repo = {"name": "exampleflow", "full_name": "example-maker/exampleflow", "html_url": "https://github.com/example-maker/exampleflow",
            "homepage": "https://exampleflow.example.com", "description": "Build agentic workflows", "stargazers_count": 150000}
    get = pages({"https://api.github.com/search/repositories?q=ExampleFlow": {"items": [repo]},
                 "https://exampleflow.example.com": site("ExampleFlow - agentic workflows")})
    found = find_links(record, "", "", None, get=get)
    assert [(f.url, f.role) for f in found] == [("https://exampleflow.example.com", "main"), ("https://github.com/example-maker/exampleflow", "badge")]


def test_sign_in_walls_keep_the_address_asked_for():
    get = pages({"https://drive.google.com/": (200, site("Sign in"), "https://accounts.google.com/v3/signin?x=1")})
    assert read_page(get, "https://drive.google.com/").url == "https://drive.google.com/"


def test_ambiguous_names_need_a_clear_fit():
    record = {"summary": "claude code add-ons for a team", "link_targets": [{"name": "Codex", "kind": "tool",
                                                                              "role": "central"}]}
    hits = [{"id": "Q1", "label": "Codex", "description": "ancient manuscript"},
            {"id": "Q2", "label": "CodeX", "description": "center for legal research at Stanford"},
            {"id": "Q3", "label": "CodeX", "description": "2023 video game"}]
    get = pages({**wikidata("Codex", hits, [binding(site="https://law.stanford.edu/codex")]),
                 "https://law.stanford.edu/codex": site("CodeX")})
    assert find_links(record, "", "", None, get=get) == []


# ---- code -----------------------------------------------------------------------------------

def test_a_repo_given_by_the_post_is_used_directly():
    record = {"entities": {"skills_code": ["example-maker/workshop-notes"]}}
    get = pages({"https://api.github.com/repos/example-maker/workshop-notes": {
        "html_url": "https://github.com/example-maker/workshop-notes", "full_name": "example-maker/workshop-notes"}})
    assert mains(find_links(record, "", "", None, get=get)) == {
        "example-maker/workshop-notes": "https://github.com/example-maker/workshop-notes"}


def test_the_makers_own_repo_beats_a_more_popular_copy():
    record = {"summary": "MCP servers for your AI team", "entities": {"skills_code": ["Stripe MCP"]}}
    search = {"items": [{"name": "stripe-mcp", "full_name": "examplecreator/stripe-mcp", "html_url": "https://github.com/examplecreator/stripe-mcp",
                         "description": "MCP", "stargazers_count": 3000}]}
    official = {"items": [{"name": "ai", "full_name": "stripe/ai", "html_url": "https://github.com/stripe/ai",
                           "description": "Stripe's MCP server and agent toolkit", "stargazers_count": 1500}]}
    get = pages({"https://api.github.com/search/repositories?q=Stripe%20MCP": search,
                 "https://api.github.com/search/users?q=stripe": {"items": [{"login": "stripe"}, {"login": "stripe-archive"}]},
                 "https://api.github.com/search/repositories?q=mcp%20user%3Astripe": official})
    assert mains(find_links(record, "", "", None, get=get)) == {"Stripe MCP": "https://github.com/stripe/ai"}


def test_the_original_repo_beats_copies_and_owner_plus_name_counts():
    record = {"summary": "popular claude skills", "entities": {"skills_code": ["Alex Example Skills"]}}
    get = pages({"https://api.github.com/repos/alexexample/skills": {"html_url": "https://github.com/alexexample/skills",
                                                                    "full_name": "alexexample/skills"}})
    assert mains(find_links(record, "", "", None, get=get)) == {"Alex Example Skills": "https://github.com/alexexample/skills"}


def test_a_vague_name_is_only_a_possible_match():
    record = {"summary": "claude skills", "entities": {"skills_code": ["security-audit"]}}
    search = {"items": [{"name": "security-audit-skill", "full_name": "cloudflare/security-audit-skill",
                         "html_url": "https://github.com/cloudflare/security-audit-skill", "stargazers_count": 40000}]}
    found = find_links(record, "", "", None, get=pages({"https://api.github.com/search/repositories": search}))
    assert found[0].url == "https://github.com/cloudflare/security-audit-skill" and found[0].possible


def test_a_skill_in_a_post_about_skills_keeps_its_repository():
    record = {"title": "A fictional studio coding skills checklist", "summary": "skills for coding agents",
              "link_targets": [{"name": "CedarSkill", "kind": "tool", "role": "central", "open_source": True}]}
    repo = {"name": "cedarskill", "full_name": "examplecreator/cedarskill", "html_url": "https://github.com/examplecreator/cedarskill",
            "homepage": "https://cedarskill.example.com", "description": "Makes your AI agent lazy", "stargazers_count": 90000}
    get = pages({"https://api.github.com/search/repositories?q=CedarSkill": {"items": [repo]},
                 "https://cedarskill.example.com": site("CedarSkill")})
    assert mains(find_links(record, "", "", None, get=get)) == {"CedarSkill": "https://github.com/examplecreator/cedarskill"}


# ---- the post's own links -------------------------------------------------------------------

def test_the_posts_own_page_names_its_apps_and_the_maker_site_stands_in():
    record = {"summary": "an app store for indie Mac apps",
              "link_targets": [{"name": "Pebble Desk", "kind": "tool", "role": "central"},
                               {"name": "SwatchTray", "kind": "product", "role": "passing"},
                               {"name": "Corkfolio", "kind": "tool", "role": "passing"}],
              "entities": {"links": ["pebbledesk.example.com"]}}
    shelf = site("PebbleDesk: the app store for Mac apps", 'SwatchTray and SwatchQ are our apps; others from '
                 '<a href="https://corkfolio.example.com">Corkfolio</a>. From <a href="https://example.com">Example Workshop</a>.')
    get = pages({"https://pebbledesk.example.com": shelf, "https://corkfolio.example.com": site("Corkfolio - Mac apps"),
                 "https://example.com/": site("Example Workshop")})
    assert mains(find_links(record, "", "", None, get=get)) == {
        "Pebble Desk": "https://pebbledesk.example.com", "SwatchTray": "https://example.com/",
        "Corkfolio": "https://corkfolio.example.com"}


def test_mentioned_urls_are_kept_when_they_load_but_platform_links_are_not():
    get = pages({"https://cursor.com": site("Cursor")})
    found = find_links({"entities": {}}, "Try https://cursor.com and https://www.instagram.com/examplecreator", "", None, get=get)
    assert [f.url for f in found] == ["https://cursor.com"]
    good = pages({"https://voicestudio.ai": site("Voice Studio")})
    assert check(Found("x", "links", "https://voicestudio.ai"), good)
    assert check(Found("x", "links", "javascript:alert(1)"), good) is None


# ---- books, people, places, sources ---------------------------------------------------------

def test_people_need_to_be_the_one_the_post_means():
    record = {"summary": "a fictional naturalist explains paper models",
              "link_targets": [{"name": "Casey Example", "kind": "person", "role": "central"}]}
    hits = [{"id": "Q1035", "label": "Casey Example", "description": "Fictional naturalist and biologist"},
            {"id": "Q5", "label": "Casey Example", "description": "Fictional aviator"}]
    get = pages(wikidata("Casey Example", hits, [binding(article="https://en.wikipedia.org/wiki/Casey_Example",
                                                          kind="http://www.wikidata.org/entity/Q5")]))
    assert mains(find_links(record, "", "", None, get=get)) == {
        "Casey Example": "https://en.wikipedia.org/wiki/Casey_Example"}


def test_big_places_in_passing_get_no_map_but_specific_ones_do():
    record = {"entities": {"places": ["Mumbai", "Pench National Park"]}}
    get = pages({"https://nominatim.openstreetmap.org/search?q=Mumbai": [{"addresstype": "city", "osm_type": "node", "osm_id": 1}],
                 "https://nominatim.openstreetmap.org/search?q=Pench": [{"addresstype": "national_park", "osm_type": "way",
                                                                         "osm_id": 2, "display_name": "Pench"}]})
    assert mains(find_links(record, "", "", None, get=get)) == {"Pench National Park": "https://www.openstreetmap.org/way/2"}


def test_cited_works_get_their_doi_from_crossref():
    caption = "Sources:\n- Exampleton, \"Folded paper as a spring material\", Example Materials Journal 144 (1990)\n- Some report, 2024"
    crossref = {"message": {"items": [{"DOI": "10.0000/example-paper", "title": ["Folded paper as a spring material"],
                                       "issued": {"date-parts": [[1990]]}}]}}
    get = pages({"https://api.crossref.org/works?rows=3&select=DOI,title,issued&query.bibliographic=Exampleton": crossref,
                 "https://api.crossref.org/works?rows=3&select=DOI,title,issued&query.bibliographic=Some": {"message": {"items": [
                     {"DOI": "10.1/x", "title": ["Unrelated paper on fish"], "issued": {"date-parts": [[2024]]}}]}}})
    found = find_links({"entities": {}}, caption, "", None, get=get)
    assert [(f.name, f.url, f.kind) for f in found] == [
        ("Folded paper as a spring material (1990)", "https://doi.org/10.0000/example-paper", "sources")]


# ---- web search and alternatives ------------------------------------------------------------

def test_a_search_key_fills_gaps_and_the_monthly_limit_holds():
    record = {"summary": "a note app", "link_targets": [{"name": "Example Notes", "kind": "tool", "role": "central",
                                                         "what": "note app"}]}
    asked = []

    def search(query):
        asked.append(query)
        return [{"title": "Example Notes - write fast", "url": "https://examplenotes.example.com/blog/launch"},
                {"title": "Unrelated", "url": "https://other.example"}]
    get = pages({"https://examplenotes.example.com/": site("Example Notes", "the note app for fast writers")})
    found = find_links(record, "", "", None, get=get, search=search)
    assert mains(found) == {"Example Notes": "https://examplenotes.example.com/"} and found[0].source == "web search"
    assert find_links(record, "", "", None, get=get, search=search, skip={"https://examplenotes.example.com/"}) == []
    assert find_links(record, "", "", None, get=get) == []  # no key: nothing from the open web
    used = [5]
    limited = counted(search, lambda: used[0], lambda: used.append(0), limit=5)
    with pytest.raises(SearchLimit):
        limited("x")
    assert find_links(record, "", "", None, get=get, search=limited) == []  # the limit stops it quietly


def test_tavily_answers_become_results_and_a_used_up_month_stops():
    sent = []
    search = tavily("tvly-1", lambda url, headers, body: (sent.append((url, headers, body)) or
                                                          (200, {"results": [{"title": "A", "url": "https://a.dev", "content": "x"}]})))
    assert search("NocoDB") == [{"title": "A", "url": "https://a.dev", "snippet": "x"}]
    assert sent[0][1] == {"Authorization": "Bearer tvly-1"} and sent[0][2]["query"] == "NocoDB"
    with pytest.raises(SearchLimit):
        tavily("tvly-1", lambda *a: (432, {}))("x")


def test_alternatives_are_found_only_when_the_post_asks_for_them():
    record = {"summary": "what can replace Jira for a small team?", "alternatives_to": "Jira",
              "link_targets": [{"name": "Jira", "kind": "product", "role": "central", "domain": "atlassian.com/software/jira"}]}
    about = site("Jira alternatives", '<a href="https://alternativeto.net/software/linear/about/">Linear</a>'
                 '<a href="https://alternativeto.net/software/plane/about/">Plane</a>')
    get = pages({"https://atlassian.com/software/jira": site("Jira | project management", "team project tool"),
                 "https://alternativeto.net/software/jira/about/": about,
                 **wikidata("Linear", [{"id": "Q7", "label": "Linear", "description": "project management software for teams"}],
                            [binding(site="https://linear.app")]),
                 "https://linear.app": site("Linear - plan and build")})
    found = find_links(record, "", "", None, get=get)
    assert [(f.name, f.section) for f in found if f.role == "main"] == [("Jira", "named"), ("Linear", "alternative")]
    assert all(f.section == "named" for f in find_links({**record, "alternatives_to": ""}, "", "", None, get=get))


# ---- storage, the owner's edits, the worker ------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "m.db")
    phone, _ = s.add_phone("p")
    url = "https://www.instagram.com/reel/L1/"
    s.receive(phone, [{"id": "d1", "url": url}])
    folder = tmp_path / "lib" / "instagram-L1"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"text": "Get it: https://cursor.com", "author": "Ana"}))
    (folder / "record.json").write_text(json.dumps({"title": "t", "summary": "s", "entities": {"tools": ["Cursor"]}}))
    s.fetch_succeeded(url, str(folder))
    s._db.execute("UPDATE items SET ai_status='done'")
    s.url = url
    return s


def test_owner_edits_win_and_removed_links_never_come_back(store):
    store.save_found_links(store.url, [Found("Cursor", "tools", "https://cursor.com", "Cursor", "Wikidata", 6),
                                       Found("Cursor", "tools", "https://github.com/cursor/cursor", "", "GitHub", 5,
                                             role="badge"),
                                       Found("Zed", "tools", "https://zed.dev", "", "Wikidata", 6, central=False,
                                             possible=True)])
    links = store.links_for(store.url)
    assert [(l["url"], l["role"], l["central"], l["rank"]) for l in links] == [
        ("https://cursor.com", "main", 1, "best"), ("https://github.com/cursor/cursor", "badge", 1, "best"),
        ("https://zed.dev", "main", 0, "possible")]
    store.remove_link(links[1]["id"])
    item_id = store.id_for(store.url)
    assert store.add_link_by_owner(item_id, "Cursor docs", "https://docs.cursor.com", "tools")
    assert not store.add_link_by_owner(item_id, "bad", "javascript:alert(1)")
    store.save_found_links(store.url, [Found("Cursor", "tools", "https://github.com/cursor/cursor", "", "GitHub", 5)])
    assert [l["url"] for l in store.links_for(store.url)] == ["https://docs.cursor.com"]  # removed stays out
    assert store.hub_items(query="Cursor docs")  # linked names are searchable


def test_the_worker_finds_links_without_ever_calling_the_ai(store):
    keyring.add("gemini", "free", "AIza-1", "k", lambda *a, **k: (200, {"models": [
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]}]}))
    asked = []
    get = pages({"https://cursor.com": site("Cursor"), "https://generativelanguage.googleapis.com": asked.append})
    assert links_due(store, get=get, pause=lambda s: None) == 1
    assert [l["url"] for l in store.links_for(store.url)] == ["https://cursor.com"] and asked == []
    assert store.due_for_links() == []
    store.set_paused("links", True)
    store.find_links_again(store.id_for(store.url))  # "Find more links" goes even while paused
    assert links_due(store, get=get, pause=lambda s: None) == 1


def test_searches_are_counted_per_month_against_the_owners_limit(store, monkeypatch):
    calls = []
    monkeypatch.setattr("magpiary.links.http_post_json", lambda url, h, b: calls.append(b) or (200, {"results": []}))
    key = keyring.Key(id="s", provider="tavily", tier="free", secret="tvly-1", label="Tavily", model="web search",
                      added="2026-10-24")
    store.set_setting("search_limit", "2")
    search = web_search(store, key)
    search("a"), search("b")
    with pytest.raises(SearchLimit):
        search("c")
    assert searches_used(store) == 2 and len(calls) == 2
    assert web_search(store, None) is None


def test_search_keys_are_checked_and_kept_apart_from_ai_keys(monkeypatch):
    monkeypatch.setattr(keyring, "check_search_key", lambda secret, provider="brave": None)
    assert keyring.add("tavily", "free", "tvly-1", "Tavily") is None
    assert keyring.search_key().provider == "tavily" and keyring.usable() == []
    monkeypatch.setattr(keyring, "check_search_key", lambda secret, provider="brave": "Brave refused this key.")
    assert keyring.add("brave", "free", "BSA-2") == "Brave refused this key."


def test_tavily_keys_are_checked_without_spending_a_search():
    seen = []
    get = lambda url, headers: seen.append(url) or (200, url, b"{}")  # noqa: E731
    assert keyring.check_search_key("tvly-1", "tavily", get) is None and seen == ["https://api.tavily.com/usage"]
    assert keyring.check_search_key("tvly-1", "tavily", lambda u, h: (401, u, b"")) == "Tavily refused this key."


# ---- rich captions ------------------------------------------------------------------------

def test_captions_get_clickable_links_mentions_and_hashtags():
    html = rich_text("By @chef.example: recipe at https://x.dev/r?a=1&b=2. #pasta <b>", "instagram")
    assert '<a href="https://x.dev/r?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">https://x.dev/r?a=1&amp;b=2</a>.' in html
    assert '<a href="https://www.instagram.com/chef.example/"' in html and ">@chef.example</a>:" in html
    assert '<a href="/?q=pasta">#pasta</a>' in html and "&lt;b&gt;" in html
    assert "@examplecreator" in rich_text("hi @examplecreator", "linkedin") and "<a" not in rich_text("hi @examplecreator", "linkedin")


def test_unused_target_fields_default_sensibly():
    t = Target("x", "tool")
    assert t.central and t.section == "named" and not t.guessed


def test_a_badge_must_carry_the_things_own_name():
    from magpiary.links import _names_page
    assert _names_page("PHP", "https://github.com/php/php-src")
    assert _names_page("Claude Code", "https://github.com/anthropics/claude-code")
    assert _names_page("Node.js", "https://en.wikipedia.org/wiki/Node.js")
    assert not _names_page("Node.js", "https://github.com/iojs")              # a predecessor's repository
    assert not _names_page("Node.js", "https://en.wikipedia.org/wiki/Io.js")
    assert not _names_page("Railway", "https://en.wikipedia.org/wiki/Railroad")  # a broader topic
    assert _names_page("React.js", "https://en.wikipedia.org/wiki/React_(software)")


def test_web_search_only_takes_the_things_own_site():
    from magpiary.links import _own_root, Target, from_search
    assert _own_root("ManyChat", "https://careers.manychat.com/jobs/1") == "https://manychat.com/"
    assert _own_root("Perplexity", "https://research.perplexity.ai/") == "https://perplexity.ai/"
    ads = [{"url": "https://job-boards.greenhouse.io/figma/jobs/1", "title": "Figma - Engineer"},
           {"url": "https://www.lennysnewsletter.com/p/x", "title": "Notion and Figma"}]
    assert from_search(Target("Figma", "tool", "central", "design tool"), lambda q: ads,
                       lambda *a, **k: (200, "text/html", b"<title>Figma</title>"), set()) is None


def test_a_failed_or_empty_search_keeps_the_links_already_found(store, monkeypatch):
    """Review 2, 4 Nov 2026: "Find more links" offline wiped the links and marked the job done."""
    from magpiary import worker

    store.save_found_links(store.url, [Found("Cursor", "tools", "https://cursor.com", "Cursor", "Wikidata", 6)])
    for broken in (lambda *a, **k: (_ for _ in ()).throw(OSError("offline")), lambda *a, **k: []):
        store.find_links_again(store.id_for(store.url))
        monkeypatch.setattr(worker, "find_links", broken, raising=False)
        monkeypatch.setattr("magpiary.links.find_links", broken)
        links_due(store, get=pages({}), pause=lambda s: None)
        assert [l["url"] for l in store.links_for(store.url)] == ["https://cursor.com"]


def test_an_address_only_the_ai_proposed_is_fetched_only_when_it_is_a_bare_site():
    """Review 3, 4 Nov 2026: an AI answer could put private text in an address and have this Mac request it."""
    from magpiary.links import targets_for

    record = {"entities": {"links": ["https://collector.test/c?note=PRIVATE", "https://pebbledesk.example.com",
                                     "https://given.example.com/page/2"]}}
    _, urls = targets_for(record, "See https://given.example.com/page/2", "", None)
    assert "https://pebbledesk.example.com" in urls and "https://given.example.com/page/2" in urls
    assert not any("collector" in u for u in urls)


def test_an_app_store_listing_counts_only_when_its_developer_is_one_the_post_names():
    from magpiary.links import app_store
    about = "An open AI model you can run on your phone, offline and private, for chat and writing help."

    def store_answer(seller):
        return {"results": [{"trackName": "Gemma 4", "sellerName": seller, "artistName": seller, "description": about,
                             "trackViewUrl": "https://apps.apple.com/us/app/gemma-4/id1?uo=4"}]}
    target = Target("Gemma 4", "product", what="Google's open AI model for phones")
    context = {"google", "model", "phone", "offline", "open"}
    stranger = pages({"https://itunes.apple.com/search": store_answer("Example Indie Dev LLC")})
    assert app_store(target, stranger, context) is None  # the same name, someone else's app
    maker = pages({"https://itunes.apple.com/search": store_answer("Google LLC")})
    assert app_store(target, maker, context).url == "https://apps.apple.com/us/app/gemma-4/id1"
