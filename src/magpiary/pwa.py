"""Magpiary as an installed web app (a standalone window with its own Dock icon, from Chrome, Edge or Brave).

Only the Mac itself, on the first account's port, can install it: an installed app belongs to one address
(http://localhost:8765), and a PWA needs HTTPS or localhost. The phone comes later with the HTTPS phone access work.
The service worker keeps nothing: no library data, media or pages are ever cached. It only answers a page load with an
"isn't running" page when the service is down."""

import json
import os

from magpiary.protocol import PORT_BASE
from magpiary.web import Response


def install_port() -> int:
    """The one address that may be installed: the first account's hub. MAGPIARY_PWA_PORT is for testing on another port."""
    try:
        return int(os.environ["MAGPIARY_PWA_PORT"])
    except (KeyError, ValueError):
        return PORT_BASE


THEME = "#0f0f0f"  # the hub's dark background, so the window frame and the splash match it

MANIFEST = {
    "name": "Magpiary", "short_name": "Magpiary", "description": "Your saved posts, on your Mac.",
    "id": "/", "start_url": "/", "scope": "/", "display": "standalone",
    "background_color": THEME, "theme_color": THEME,
    "icons": [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# What the window shows when the service is down. Inline, because nothing is fetched while the hub is off.
OFFLINE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Magpiary isn't running</title><style>
html{background:#0f0f0f;color:#f5f3ee;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
body{margin:0;min-height:100vh;display:grid;place-items:center;text-align:center;padding:24px;box-sizing:border-box}
main{max-width:420px}h1{font-size:24px;margin:0 0 8px}p{color:#b9b6ae;margin:0 0 20px}
a.b{display:inline-block;background:#f5f3ee;color:#111;border-radius:10px;padding:10px 18px;font-weight:600;text-decoration:none}
a.b:focus-visible{outline:2px solid #97948b;outline-offset:3px}small{display:block;margin-top:22px;color:#97948b}
code{background:#1c1c1c;border-radius:6px;padding:2px 6px}
</style></head><body><main><h1>Magpiary isn't running</h1>
<p>The Magpiary service on this Mac is off. Start it, and this window opens your library again on its own.</p>
<a class="b" href="magpiary://open">Start Magpiary</a>
<small id="s">Waiting for Magpiary…</small>
<small>Button does nothing? Open Magpiary from your Applications folder, or run <code>magpiary doctor</code> in Terminal.</small>
<script>setInterval(function(){fetch("/sw.js",{cache:"no-store"}).then(function(r){if(r.ok)location.reload()}).catch(function(){})},3000)</script>
</main></body></html>"""

WORKER = """// Magpiary's service worker. It stores nothing. A page load that fails (the service is off) shows the "isn't running" page.
const OFFLINE = %s;
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => new Response(OFFLINE,
    {status: 503, headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}})));
});
"""


def manifest() -> Response:
    return Response(200, json.dumps(MANIFEST).encode(), "application/manifest+json", {"Cache-Control": "no-cache"})


def worker() -> Response:
    body = (WORKER % json.dumps(OFFLINE)).replace("</", "<\\/")
    return Response(200, body.encode(), "text/javascript; charset=utf-8",
                    {"Cache-Control": "no-cache", "Service-Worker-Allowed": "/", "X-Content-Type-Options": "nosniff"})
