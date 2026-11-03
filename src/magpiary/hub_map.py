"""The connections map, mixed into Hub: /map (every save as a dot, joined to the saves related to it), /graph.json (what
map.js draws), the Map button for the top bar, and the small "Connected to" map for a post's Related tab. The scores
come from Related (graph.py); nothing here uses an AI or leaves this Mac.

The map is a beta: everything here stays hidden until the owner turns it on in Settings > Appearance > Beta."""

import json

from magpiary import graph
from magpiary.hub_wall import empty_state
from magpiary.web import Response, e

MAP_ICON = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="7" r="2.2"/><circle cx="18" cy="6" r="2.2"/>'
            '<circle cx="12" cy="17.5" r="2.2"/><path d="M8 7.4l8-.9M7.2 9l3.6 6.4M16.9 8l-3.8 7.6"/></svg>')


BETA_SETTING = "beta_map"


def map_on(store) -> bool:
    """The Connections map is a beta, off unless the owner turned it on."""
    return store.get_setting(BETA_SETTING, "0") == "1"


class MapPages:
    """Needs Hub's store, shell and related_library."""

    def map_button(self, active: str = "") -> str:
        """The way into the map, shown once there are two saves to join."""
        if not map_on(self.store) or len(self.related_library().rows) < 2:
            return ""
        return (f'<a class="ubtn mapbtn{" on" if active == "map" else ""}" href="/map" id="t-map" aria-label="Map" '
                f'title="Map: how your saves connect">{MAP_ICON}<span class="lbl">Map</span></a>')

    def map_page(self, q: dict) -> Response:
        if not map_on(self.store):
            return Response(303, b"", headers={"Location": "/"})
        lib = self.related_library()
        if len(lib.rows) < 2:
            return self.shell("Map", empty_state("Nothing to connect yet", "Once you have a few saves, the map shows how "
                                                 "they relate.", '<a class="btn dark" href="/">Back to the library</a>'),
                              "map", active="map")
        focus = q.get("focus", "")
        body = ('<a class="back" href="/">← Library</a><div class="hero" style="margin-top:12px"><h1 class="mid">'
                'How your saves <em>connect.</em></h1><p>Each dot is a save, coloured by its pile. A line joins two saves '
                'that are about the same thing; the small labels are tools, places and tags several saves share. '
                'Click a pile to open it up, a dot to open the post.</p></div>'
                f'<div class="cmap cmap-full" data-map-src="/graph.json?scope=all"'
                f'{f" data-focus={chr(34)}p{e(focus)}{chr(34)}" if focus.isdigit() else ""} role="group" aria-label="Map of your saves">'
                '<canvas aria-hidden="true"></canvas><div class="cmap-tip" role="status" hidden></div></div>'
                '<noscript><p class="empty">The map needs JavaScript. Related saves are still listed on each post.</p></noscript>')
        return self.shell("Map", body, "map", active="map")

    def graph_json(self, q: dict) -> Response:
        if not map_on(self.store):
            return Response(404, b"{}", "application/json")
        lib = self.related_library()
        if q.get("scope") == "item" and q.get("id", "").isdigit():
            data = graph.item_graph(lib, self.store, int(q["id"]))
        else:
            data = graph.library_graph(lib, self.store)
        return Response(200, json.dumps(data).encode(), "application/json", headers={"Cache-Control": "no-store"})


def local_map_html(store, item_id: int, lib=None) -> str:
    """The "Connected to" map for one post: it in the middle, its related saves around it, the shared things between.
    Pass `lib` (Hub.related_library()) to skip loading the scores again."""
    from magpiary import related as rel

    if not map_on(store):
        return ""
    lib = lib or rel.load(store)
    row = next((r for r in lib.rows if r["id"] == item_id), None)
    if row is None or not rel.related(lib, row["canonical_url"]):
        return '<p class="empty cmap-none">Nothing is connected to this post yet.</p>'
    return (f'<div class="cmap cmap-local" data-map-src="/graph.json?scope=item&amp;id={int(item_id)}" role="group" '
            f'aria-label="Saves connected to this post"><canvas aria-hidden="true"></canvas>'
            f'<div class="cmap-tip" role="status" hidden></div></div>'
            f'<p class="cmap-more"><a class="btn sm" href="/map?focus={int(item_id)}">Open the full map</a></p>')
