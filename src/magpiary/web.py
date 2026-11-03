"""Shared pieces of the Mac's own web pages (setup and queue)."""

import html
from dataclasses import dataclass, field

from magpiary.protocol import DEFAULT_PORT

LOCAL_ADDRESSES = ("127.0.0.1", "::1")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")

STYLE = """
body{font:16px/1.5 system-ui,-apple-system,sans-serif;max-width:44rem;margin:2rem auto;padding:0 1rem;color:#16213e}
h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:2rem}
.card{border:1px solid #d8dde6;border-radius:12px;padding:1rem 1.25rem;margin:1rem 0}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.4rem .5rem;border-bottom:1px solid #e6e9ef}
input[type=text]{font:inherit;padding:.5rem;border:1px solid #b9c0cc;border-radius:8px;width:100%;box-sizing:border-box}
button,.btn{font:inherit;font-weight:600;background:#0E6B66;color:#fff;border:0;border-radius:10px;padding:.55rem 1rem;
cursor:pointer;text-decoration:none;display:inline-block}
button.quiet{background:#fff;color:#0E6B66;border:1px solid #0E6B66}
.hint{color:#5b6475;font-size:.9rem}.error{background:#fdecea;border-radius:8px;padding:.6rem .9rem}
form.inline{display:inline}.qr{background:#fff;display:inline-block;padding:12px;border:1px solid #d8dde6}
"""


# The pages a phone (or any other device) sees: the hub's dark look, its two fonts served from /install/fonts/
PHONE_STYLE = """
@font-face{font-family:"Bricolage Grotesque";src:url(/install/fonts/bricolage-grotesque.woff2) format("woff2");font-weight:200 800}
@font-face{font-family:"DM Sans";src:url(/install/fonts/dm-sans.woff2) format("woff2");font-weight:100 1000}
:root{--bg:#0f0f0f;--fg:#f5f3ee;--fg-2:#b9b6ae;--fg-3:#858279;--line:#262626;--card:#161616;--pink:#ff2e93;--blue:#2f6bff;
--indigo:#6a4cff;--purple:#8a3ffc;--green:#00a37a;--ok:#1ec27a;--display:"Bricolage Grotesque",system-ui,sans-serif;
--sans:"DM Sans",system-ui,-apple-system,sans-serif;color-scheme:dark}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0 auto;max-width:30rem;padding:max(28px,env(safe-area-inset-top)) 20px 40px;background:var(--bg);color:var(--fg);
font:16px/1.5 var(--sans);-webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
h1,h3{font-family:var(--display);margin:0}
a{color:inherit}
b{font-weight:700;color:var(--fg)}
.brand{display:flex;align-items:center;gap:8px;font:800 18px var(--display);letter-spacing:-.01em}
.brand svg{width:26px;height:26px}
h1{font-size:34px;line-height:1.04;letter-spacing:-.025em;margin:26px 0 10px}
h1 em{font-style:normal;color:var(--pink)}
.sub{color:var(--fg-2);margin:0 0 22px}
.get{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;height:58px;border-radius:999px;
background:var(--pink);color:#fff;font:700 18px var(--sans);text-decoration:none;box-shadow:0 14px 30px -12px rgba(255,46,147,.7)}
.get.calm{background:var(--fg);color:#111;box-shadow:none}
.get svg{width:22px;height:22px}
.timer{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:12px;color:var(--fg-3);font-size:13px}
.timer i{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px rgba(30,194,122,.18)}
.sect{font:700 12px var(--sans);text-transform:uppercase;letter-spacing:.09em;color:var(--fg-3);margin:34px 0 12px}
.cards{display:grid;gap:10px;margin:0;padding:0;list-style:none}
.cards li{display:grid;grid-template-columns:48px 1fr;gap:14px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:20px;padding:14px 40px 14px 14px;position:relative}
.ic{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;color:#fff}
.ic svg{width:24px;height:24px}
.cards h3{font-size:16px;margin-bottom:2px}
.cards p{margin:0;color:var(--fg-2);font-size:13.5px;line-height:1.4}
.num{position:absolute;right:14px;top:12px;font:800 12px var(--display);color:var(--fg-3)}
.c1{background:var(--blue)}.c2{background:var(--indigo)}.c3{background:var(--purple)}.c4{background:var(--green)}
.note{margin-top:26px;padding:16px;border-radius:20px;background:color-mix(in srgb,var(--blue) 13%,var(--card));
border:1px solid color-mix(in srgb,var(--blue) 35%,transparent);font-size:14px;color:var(--fg-2)}
.note h3{font-size:16px;color:var(--fg);margin-bottom:4px}
.foot{margin-top:26px;color:var(--fg-3);font-size:12.5px;text-align:center}
.alone{min-height:70vh;display:grid;align-content:center;text-align:center;justify-items:center}
.alone .big{width:64px;height:64px;border-radius:20px;display:grid;place-items:center;color:#fff;margin-bottom:18px}
.alone .big svg{width:30px;height:30px}
.alone h1{margin:0 0 10px;font-size:30px}
.alone p{color:var(--fg-2);margin:0 0 22px;max-width:22rem}
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
.in{animation:rise .55s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(var(--i,0) * 70ms)}
.get{transition:transform .15s,background .3s,box-shadow .3s;-webkit-tap-highlight-color:transparent}
.get:active{transform:scale(.97)}
.get .spin{display:none;width:22px;height:22px;border-radius:50%;border:2.5px solid rgba(255,255,255,.35);border-top-color:#fff;animation:spin .8s linear infinite}
.get.busy{pointer-events:none}.get.busy .spin{display:block}.get.busy svg{display:none}
.get.ready{background:var(--ok);box-shadow:0 14px 30px -12px rgba(30,194,122,.6)}
.get.ready svg{animation:pop .45s cubic-bezier(.3,1.6,.5,1)}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pop{from{transform:scale(.3)}}
.cards li{transition:border-color .3s,background .3s,opacity .3s}
.cards li.done{opacity:.55}.cards li.done .ic{background:var(--ok)}
.cards li.next{border-color:var(--purple);background:color-mix(in srgb,var(--purple) 12%,var(--card));animation:glow 1.8s ease-in-out infinite}
@keyframes glow{50%{box-shadow:0 0 0 6px color-mix(in srgb,var(--purple) 18%,transparent)}}
@media (prefers-reduced-motion:reduce){.in,.cards li.next,.get.ready svg{animation:none}}
code{font:13px ui-monospace,Menlo,monospace;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:2px 6px;color:var(--fg)}
"""


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: dict = field(default_factory=dict)
    stream: tuple | None = None  # (path, start, length): a file sent in chunks instead of body


def e(text: object) -> str:
    return html.escape(str(text), quote=True)


def page(title: str, body: str, status: int = 200, extra_head: str = "") -> Response:
    doc = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"{extra_head}<title>{e(title)} \u2013 Magpiary</title><style>{STYLE}</style><body>{body}</body>")
    return Response(status, doc.encode(), headers={"Cache-Control": "no-store"})


def phone_page(title: str, body: str, status: int = 200) -> Response:
    """A page for the phone or another device, in the hub's dark look."""
    doc = (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
           f'initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0f0f0f"><title>{e(title)} – Magpiary'
           f"</title><style>{PHONE_STYLE}</style><body>{body}</body></html>")
    return Response(status, doc.encode(), headers={"Cache-Control": "no-store"})


ICONS = {  # the phone pages' few icons (24 px, drawn with the text colour)
    "tap": '<path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11"/><path d="M12 10.5v-1a1.5 1.5 0 0 1 3 0v1.5"/><path d="M15 11a1.5 1.5 0 0 1 '
           '3 0v3.5a6 6 0 0 1-6 6h-.6a6 6 0 0 1-4.6-2.2L4.2 15a1.5 1.5 0 0 1 2.3-1.9L9 15.5"/>',
    "down": '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
    "open": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8"/><path d="m8.5 12.5 3.5 3.5 3.5-3.5"/>',
    "add": '<rect x="4" y="4" width="16" height="16" rx="5"/><path d="M12 8.5v7M8.5 12h7"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "retry": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "mac": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "lost": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
}


def icon(name: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def alone_page(title: str, colour: str, icon_name: str, heading: str, text: str, action: str = "",
               status: int = 200) -> Response:
    """A one-message phone page (expired, try again, not found, this Mac only)."""
    return phone_page(title, f'<main class="alone"><div class="big" style="background:{colour}">{icon(icon_name)}</div>'
                             f'<h1>{heading}</h1><p>{text}</p>{action}</main>', status)


def local_only(client_ip: str, host: str) -> Response | None:
    """None if the request comes from this Mac itself (address and Host header); otherwise a refusal.
    The Host check also stops DNS rebinding: a website cannot make a browser reach us under its own name."""
    hostname = host if host.endswith("]") else host.rsplit(":", 1)[0]
    if client_ip not in LOCAL_ADDRESSES or hostname.lower() not in LOCAL_HOSTS:
        return alone_page("This Mac only", "var(--indigo)", "mac", "Open this on your Mac",
                          f"Your library only opens on the Mac that runs Magpiary, at <code>http://localhost:{DEFAULT_PORT}/</code>. "
                          "Phones just send posts to it.", status=403)
    return None
