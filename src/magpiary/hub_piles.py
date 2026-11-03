"""Related saves and Piles (M4; C1+ look in M7a), mixed into Hub: "More like this" for a post, a pile's page
(overview, rename, merge, split off ticked, remove, delete), and the owner's corrections. The piles themselves are
shown on the wall (hub_wall), and a post's Related tab is in hub_card."""

import re
from datetime import date

from magpiary.hub_wall import empty_state
from magpiary import related as rel
from magpiary import ui
from magpiary.web import Response, e


def _day(stamp: str) -> str:
    try:
        d = date.fromisoformat(stamp[:10])
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%b')} {d.year}"


class RelatedPages:
    """Needs Hub's store, csrf, shell, _form, tile, tile_context and activity."""

    _lib, _lib_sig = None, None

    def related_library(self) -> rel.Library:
        """Loaded again only when vectors, Not-related marks or the Trash changed."""
        sig = self.store.related_signature()
        if self._lib is None or sig != self._lib_sig:
            self._lib, self._lib_sig = rel.load(self.store), sig
        return self._lib

    def related_page(self, item_id: int) -> Response:
        item = self.store.item_by_id(item_id)
        if not item:
            return self.shell("Not found", empty_state("This post is gone", "It may have been deleted, or the link is old.",
                                                              '<a class="btn dark" href="/">Back to the library</a>'), "missing", 404)
        here = f"/item/{item_id}/related"
        ctx = self.tile_context()
        tiles = []
        for r in rel.related(self.related_library(), item["canonical_url"]):
            other = self.store.item_by_id(r["row"]["id"])
            if other:
                why = f'<div class="why"><small>Why</small>{e(r["reason"])}</div>'
                acts = ('<div class="acts">' + self._form("/hub/not-related", {"id": item_id, "other": other["id"], "next": here},
                                                          "Not related", "dk") + "</div>")
                tiles.append(self.tile(other, ctx, over=acts, extra=why))
        title = ui.title_of(item)
        grid = f'<div class="grid">{"".join(tiles)}</div>' if tiles else '<div class="empty">Nothing related yet.</div>'
        body = (f'<a class="back" href="/item/{item_id}">← Back to the post</a><div class="hero" style="margin-top:12px">'
                f'<h1 class="mid">More like<br><em>{e(title[:80])}</em></h1><p>{len(tiles)} related save'
                f'{"" if len(tiles) == 1 else "s"}, best match first. The same topic, the same named things and the same tags '
                f'all count. “Not related” takes one out for good.</p></div>{grid}')
        return self.shell("Related", body, "related")

    def pile_page(self, pile_id: int) -> Response:
        pile = self.store.pile(pile_id)
        if not pile:
            return self.shell("Not found", '<p class="empty">This pile is gone. <a class="link" href="/?view=piles">All piles</a></p>',
                              "missing", 404)
        lib = self.related_library()
        o = rel.overview(lib, pile["members"])
        sub = rel.subtitle(lib, pile["members"], pile["name"])
        self.store.pile_seen(pile_id)
        here = f"/pile/{pile_id}"
        ctx = self.tile_context()
        tiles = []
        for url in pile["members"]:
            item_id = self.store.id_for(url)
            item = self.store.item_by_id(item_id) if item_id else None
            if not item or item["shelf"] == "trash":
                continue
            tick = (f'<label class="tick"><input type="checkbox" name="item_{item["id"]}" form="split" '
                    f'aria-label="Tick to split off">Split off</label>')
            acts = ('<div class="acts">'
                    + self._form("/hub/pile/remove", {"pile": pile_id, "id": item["id"], "next": here}, "Remove from pile", "dk")
                    + "</div>")
            tiles.append(self.tile(item, ctx, over=acts, extra=tick))
        n = o["count"]
        sources = ", ".join(f"{ui.source_name(s)} ({k})" for s, k in sorted(o["sources"].items(), key=lambda kv: -kv[1]))
        dates = _day(o["first"]) if o["first"] == o["last"] else f"{_day(o['first'])} – {_day(o['last'])}"
        common = "".join(f'<span>{e(name)} <em>{k}</em></span>' for name, k in o["common"])
        # one summary line and the shared tags, no cards; Edit pile sits on the right of the same line (owner, 26 Oct)
        facts = [f"<b>{n} save{'' if n == 1 else 's'}</b>"]
        if dates.strip(" –"):
            facts.append(e(dates))
        if sources:
            facts.append(e(sources))
        overview = (f'<div class="prow"><p class="pline">{" · ".join(facts)}</p>'
                    f'<label for="pileedit" class="btn sm ghost peditbtn"><span class="mo">{ui.icon("gear")}Edit pile</span>'
                    f'<span class="mc">Done editing</span></label>{self.ask_button(f"pile:{pile_id}")}</div>'
                    + (f'<div class="chips ptags">{common}</div>' if common else ""))
        others = "".join(f'<option value="{p["id"]}">{e(p["name"])}</option>' for p in self.store.piles() if p["id"] != pile_id)
        # browsing first: editing (rename, merge, delete, and the Split off ticks) opens from one button (owner, 26 Oct)
        manage = (f'<div class="mbody manage">'
                  f'<form method="post" action="/hub/pile/rename">{ui.hidden(self.csrf, pile=pile_id, next=here)}'
                  f'<input type="text" name="name" maxlength="60" value="{e(pile["name"])}" aria-label="Pile name">'
                  f'<button class="btn sm" type="submit">Rename</button></form>'
                  + (f'<form method="post" action="/hub/pile/merge">{ui.hidden(self.csrf, pile=pile_id, next="/?view=piles")}'
                     f'<select name="into" aria-label="Pile to merge into">{others}</select>'
                     f'<button class="btn sm" type="submit">Merge into</button></form>' if others else "")
                  + self._form("/hub/pile/delete", {"pile": pile_id, "next": "/?view=piles"}, "Delete pile", "btn sm danger",
                               confirm="Delete this pile? Your saves stay in the library, and it is not made again.")
                  + "</div>")
        split = (f'<form method="post" action="/hub/pile/split" id="split" class="pickbar">'
                 f'{ui.hidden(self.csrf, pile=pile_id, next="/?view=piles")}<span>Split the ticked saves into</span>'
                 f'<input type="text" name="name" maxlength="60" placeholder="Name for the new pile" aria-label="Name for the new pile">'
                 f'<button class="btn sm" type="submit">Split off ticked</button></form>') if len(tiles) > 1 else ""
        grid = f'<div class="grid">{"".join(tiles)}</div>' if tiles else '<div class="empty">This pile is empty.</div>'
        body = (f'<a class="back" href="/?view=piles">← Piles</a><div class="hero" style="margin-top:12px"><h1 class="mid">'
                f'{e(pile["name"])}</h1>' + (f'<p>{e(sub)}</p>' if sub else "") + "</div>"
                f'<input type="checkbox" id="pileedit" class="sr" aria-label="Edit pile">'
                f'<section class="phead">{overview}{manage}</section>' + self.pile_notes_html(pile_id) + grid + split)
        return self.shell(pile["name"], body, "pile")

    def pile_post(self, path: str, form: dict) -> bool:
        """The owner's corrections. Returns False for a path this mixin does not handle."""
        pile_id = int(form["pile"]) if form.get("pile", "").isdigit() else 0
        if path == "/hub/not-related":
            a = self.store.item_by_id(int(form["id"])) if form.get("id", "").isdigit() else None
            b = self.store.item_by_id(int(form["other"])) if form.get("other", "").isdigit() else None
            if a and b:
                self.store.mark_not_related(a["canonical_url"], b["canonical_url"])
                for p in self.store.piles():  # both in one pile: the one being looked at leaves it
                    if a["canonical_url"] in p["members"] and b["canonical_url"] in p["members"]:
                        self.store.remove_from_pile(p["id"], b["canonical_url"])
        elif path == "/hub/pile/rename":
            self.store.rename_pile(pile_id, form.get("name", ""))
        elif path == "/hub/pile/delete":
            self.store.delete_pile(pile_id)
        elif path == "/hub/pile/merge":
            if form.get("into", "").isdigit():
                self.store.merge_piles(pile_id, int(form["into"]))
        elif path == "/hub/pile/split":
            ids = [int(m.group(1)) for k in form if (m := re.fullmatch(r"item_(\d+)", k))]
            urls = [i["canonical_url"] for i in map(self.store.item_by_id, ids) if i]
            self.store.split_pile(pile_id, urls, form.get("name", ""))
        elif path == "/hub/pile/remove":
            item = self.store.item_by_id(int(form["id"])) if form.get("id", "").isdigit() else None
            if item:
                self.store.remove_from_pile(pile_id, item["canonical_url"])
        elif path == "/hub/piles/regroup":
            rel.rebuild_piles(self.store, regroup=True)
            return True
        else:
            return False
        rel.rebuild_piles(self.store)
        return True
