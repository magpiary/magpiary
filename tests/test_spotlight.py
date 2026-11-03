"""The Spotlight score: fair across sites, gentle with little data, nudged by what the library is about."""

from datetime import datetime, timezone

from magpiary import spotlight

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def item(n, source="instagram", tags=(), created="2026-10-25T10:00:00+00:00"):
    return {"canonical_url": f"https://x/{source}/{n}", "source": source, "tags": list(tags), "created_at": created, "published_at": ""}


def test_each_post_is_ranked_against_its_own_site_so_youtube_views_do_not_swamp_instagram():
    ig = [item(i) for i in range(6)]
    yt = [item(i, "youtube") for i in range(6)]
    stats = {i["canonical_url"]: {"likes": 100 * (n + 1), "comments": 5 * (n + 1), "views": None} for n, i in enumerate(ig)}
    stats |= {i["canonical_url"]: {"likes": 1_000_000 * (n + 1), "comments": None, "views": 50_000_000 * (n + 1)} for n, i in enumerate(yt)}
    out = spotlight.compute(ig + yt, stats, [], NOW)
    best_ig, best_yt = out[ig[-1]["canonical_url"]]["score"], out[yt[-1]["canonical_url"]]["score"]
    assert abs(best_ig - best_yt) < 0.15 and min(best_ig, best_yt) > 0.6  # the top of each site scores alike
    assert out[ig[0]["canonical_url"]]["score"] < best_ig


def test_a_post_without_numbers_is_neutral_not_zero_and_one_viral_post_is_damped():
    posts = [item(i) for i in range(8)]
    stats = {p["canonical_url"]: {"likes": 50, "comments": 2, "views": 1000} for p in posts[:6]}
    stats[posts[0]["canonical_url"]] = {"likes": 5_000_000, "comments": 90_000, "views": 90_000_000}  # a viral outlier
    out = spotlight.compute(posts, stats, [], NOW)
    assert not out[posts[7]["canonical_url"]]["known"] and 0.4 < out[posts[7]["canonical_url"]]["score"] < 0.6
    assert out[posts[0]["canonical_url"]]["score"] <= 1.4  # rank, not size: the outlier does not run away


def test_topics_saved_often_and_recently_nudge_up_but_traction_still_decides():
    coffee = [item(i, tags=["coffee"], created="2026-10-30T10:00:00+00:00") for i in range(5)]
    old = [item(10 + i, tags=["rocks"], created="2025-01-01T10:00:00+00:00") for i in range(2)]
    same = {"likes": 100, "comments": 3, "views": 2000}
    stats = {p["canonical_url"]: dict(same) for p in coffee + old}
    out = spotlight.compute(coffee + old, stats, [], NOW)
    assert out[coffee[0]["canonical_url"]]["score"] > out[old[0]["canonical_url"]]["score"]
    strong = {**same, "likes": 5000, "comments": 300}
    stats[old[0]["canonical_url"]] = strong
    out = spotlight.compute(coffee + old, stats, [], NOW)
    assert out[old[0]["canonical_url"]]["score"] > out[coffee[0]["canonical_url"]]["score"]


def test_the_best_post_of_a_large_pile_is_boosted_and_the_reason_line_names_it():
    posts = [item(i) for i in range(6)]
    stats = {p["canonical_url"]: {"likes": 10 * (n + 1), "comments": 1, "views": 500} for n, p in enumerate(posts)}
    piles = [{"id": 1, "name": "Design", "members": [p["canonical_url"] for p in posts]}]
    out = spotlight.compute(posts, stats, piles, NOW)
    top = posts[-1]["canonical_url"]
    assert out[top]["pile"] == "Design" and out[posts[0]["canonical_url"]]["pile"] == ""
    assert spotlight.reason(posts[-1], out[top], stats[top]) == "Top of Design · 60 likes · 1 comments"
    assert spotlight.compact(3400) == "3.4K" and spotlight.compact(2_000_000) == "2M" and spotlight.compact(12) == "12"


def test_the_big_tile_changes_by_day_stays_put_within_a_day_and_never_repeats_a_pile():
    scored = [(f"u{i}", 1 - i / 100, "A" if i < 5 else f"P{i}") for i in range(40)]
    a1 = spotlight.pick_big(scored, 100, set(), 2)
    assert a1 == spotlight.pick_big(scored, 100, set(), 2)  # the same all day
    assert a1 != spotlight.pick_big(scored, 101, set(), 2)  # another tomorrow
    pool = spotlight.pick_big(scored, 7, set(), 4)
    assert len({p for u, _, p in scored if u in pool and p == "A"}) <= 1  # never two from pile A
    assert not set(spotlight.pick_big(scored, 100, set(a1), 2)) & set(a1)  # not again within the memory


def test_posts_you_open_often_rise_a_little_and_lift_their_topics_but_never_beat_strong_traction():
    posts = [item(i, tags=["coffee"] if i < 2 else ["rocks"]) for i in range(6)]
    same = {"likes": 100, "comments": 3, "views": 2000}
    stats = {p["canonical_url"]: dict(same) for p in posts}
    plain = spotlight.compute(posts, stats, [], NOW)
    opened = spotlight.compute(posts, stats, [], NOW, opens={posts[0]["canonical_url"]: 5.0})
    assert opened[posts[0]["canonical_url"]]["score"] > plain[posts[0]["canonical_url"]]["score"]
    assert opened[posts[1]["canonical_url"]]["score"] > plain[posts[1]["canonical_url"]]["score"]  # a sibling topic rises too
    lift = opened[posts[0]["canonical_url"]]["score"] / plain[posts[0]["canonical_url"]]["score"]
    assert lift <= 1 + spotlight.INTEREST_MAX + spotlight.OPEN_MAX + 0.001  # a bounded nudge


def test_trending_ranks_growth_within_a_site_and_skips_posts_with_one_refresh():
    items = [{"canonical_url": u, "source": "instagram", "tags": []} for u in "abcd"]
    stats = {
        "a": {"likes": 500, "comments": 5, "views": None, "fetched_at": "2026-11-08T00:00:00+00:00",
              "prev_likes": 100, "prev_comments": 5, "prev_views": None, "prev_at": "2026-11-01T00:00:00+00:00"},
        "b": {"likes": 110, "comments": 5, "views": None, "fetched_at": "2026-11-08T00:00:00+00:00",
              "prev_likes": 100, "prev_comments": 5, "prev_views": None, "prev_at": "2026-11-01T00:00:00+00:00"},
        "c": {"likes": 90, "comments": 1, "views": None, "fetched_at": "2026-11-08T00:00:00+00:00",
              "prev_likes": 90, "prev_comments": 1, "prev_views": None, "prev_at": "2026-11-01T00:00:00+00:00"},
        "d": {"likes": 50, "comments": 1, "views": None, "fetched_at": "2026-11-08T00:00:00+00:00",
              "prev_likes": None, "prev_comments": None, "prev_views": None, "prev_at": None},
    }
    out = spotlight.trending(items, stats, {})
    assert set(out) == {"a", "b"}  # c did not grow, d has only one refresh
    assert out["a"]["score"] > out["b"]["score"]
    assert spotlight.gain_text(out["a"]["gain"]) == "+400 likes"
    interested = spotlight.trending(items, stats, {"b": {"interest": 1.0}})
    assert interested["b"]["score"] > out["b"]["score"]

