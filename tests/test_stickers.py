"""Board stickers: the curated ones first, then the whole emoji set by name and keywords."""

from magpiary import stickers


def test_the_automatic_sticker_searches_the_whole_emoji_set_when_the_curated_ones_do_not_fit():
    assert stickers.emoji(stickers.pick("Lisbon trip")) == "✈️"      # curated
    assert stickers.emoji(stickers.pick("Flat hunt")) == "🏠"        # curated beats a flat shoe
    assert stickers.emoji(stickers.pick("Zebra ideas")) == "🦓"      # "ideas" is generic, zebra is in the full set
    assert stickers.emoji(stickers.pick("Dinosaur facts")) == "🦕"
    assert stickers.emoji(stickers.pick("Xyzzy")) == "📌"            # nothing fits: the pin


def test_search_finds_emoji_by_name_or_keyword_and_the_set_is_all_there():
    data = stickers.emoji_set()
    assert len(data["e"]) > 1800 and len(data["groups"]) == 9
    assert stickers.search("telescope")[0] == "🔭"
    assert "🦓" in stickers.search("zebra") and stickers.search("a") == []
