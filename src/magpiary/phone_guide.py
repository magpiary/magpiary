"""The three pages a phone sees while it is being set up (docs/specs.md, "Phone access to the library on the local network"):
the certificate steps with a live check, the name-this-phone page, and the Add to Home Screen page. Built for a phone first:
one column, text 15px and up, tap targets 52px, safe areas respected, nothing wider than the screen.

The wording follows iOS: "Profile Downloaded", Install, "Certificate Trust Settings", "Open as Web App"."""

from magpiary import access
from magpiary.web import e, phone_page

CA_NAME = "Magpiary local network CA"

CSS = """
.g{padding-bottom:max(24px,env(safe-area-inset-bottom))}
.g h1{font-size:30px;margin:22px 0 6px}
.g .sub{font-size:16px;margin:0 0 20px}
.stp{list-style:none;margin:0;padding:0;display:grid;gap:10px;counter-reset:s}
.stp>li{counter-increment:s;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:14px 14px 14px 62px;position:relative;
transition:opacity .2s,border-color .2s}
.stp>li::before{content:counter(s);position:absolute;left:14px;top:14px;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;
font:800 16px var(--display);background:var(--line);color:var(--fg-2)}
.stp>li h3{font-size:17px;margin:2px 0 4px}
.stp>li p{margin:0;color:var(--fg-2);font-size:15px;line-height:1.45}
.stp>li p+p{margin-top:8px}
.stp>li .more{display:none;margin-top:8px}
.stp>li.now{border-color:var(--indigo)}
.stp>li.now::before{background:var(--indigo);color:#fff}
.stp>li.now .more{display:block}
.stp>li.next{opacity:.62}
.stp>li.done::before{content:"\\2713";background:var(--ok);color:#06140d}
.stp>li.done{opacity:.8}
.btn2{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:52px;margin-top:12px;border-radius:999px;border:0;
background:var(--indigo);color:#fff;font:700 17px var(--sans);text-decoration:none;cursor:pointer}
.btn2[aria-disabled=true]{background:var(--line);color:var(--fg-3);pointer-events:none}
.live{display:flex;align-items:center;gap:10px;margin:14px 2px 0;color:var(--fg-2);font-size:15px}
.live i{flex:none;width:10px;height:10px;border-radius:50%;background:var(--fg-3)}
.live.wait i{background:var(--indigo);animation:pulse 1.4s ease-in-out infinite}
.live.ok i{background:var(--ok);box-shadow:0 0 0 4px rgba(30,194,122,.2)}
@media (prefers-reduced-motion:reduce){.live.wait i{animation:none}}
@keyframes pulse{50%{opacity:.35}}
.fine{margin:18px 2px 0;color:var(--fg-3);font-size:14px;line-height:1.45}
.fine summary{cursor:pointer;min-height:44px;display:flex;align-items:center;color:var(--fg-2)}
.fld{display:block;width:100%;min-height:52px;margin-top:6px;padding:0 16px;border-radius:16px;border:1px solid var(--line);background:var(--card);
color:var(--fg);font:16px var(--sans)}
.lbl{display:block;margin-top:14px;font-weight:700}
.shareic{display:inline-block;vertical-align:-5px;width:24px;height:24px;color:var(--blue)}
"""

SHARE = ('<svg class="shareic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
         'stroke-linejoin="round" aria-hidden="true"><path d="M12 15V3M8 7l4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 '
         '1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/></svg>')


def _page(title: str, body: str, head: str = "") -> object:
    page = phone_page(title, f'<div class="g"><style>{CSS}</style>{body}</div>')
    if head:
        page.body = page.body.replace(b"<title>", head.encode() + b"<title>", 1)
    return page


def certificate_guide(token: str, https_port: int, fingerprint_on_mac: bool = True):
    """Plain HTTP. Steps 1 to 3 are the phone's own settings; step 4 lights up when the phone really trusts the Mac, which
    the page checks itself by loading the public logo over HTTPS (it only loads once the certificate is trusted)."""
    probe = f"https://{access.NAME}:{https_port}/static/apple-touch-icon.png"
    pair = f"https://{access.NAME}:{https_port}/phone/pair/{token}"
    body = f"""
<h1>Set up this phone</h1>
<p class="sub">Three quick steps on this phone, about a minute. This page ticks them off as they work.</p>
<ol class="stp" id="stp">
<li class="now" data-s="1"><h3>Get the certificate</h3>
<p>It lets your phone know it is really talking to your Mac.</p>
<div class="more"><a class="btn2" id="dl" href="/phone-access/{e(token)}/ca.crt">Download certificate</a>
<p>Safari asks to allow a configuration profile: tap <b>Allow</b>, then <b>Close</b>.</p></div></li>
<li class="next" data-s="2"><h3>Install it</h3>
<p>Open the <b>Settings</b> app.</p>
<div class="more"><p>Tap <b>Profile Downloaded</b> at the top. Tap <b>Install</b> (top right), enter your passcode, then tap
<b>Install</b> and <b>Install</b> again, then <b>Done</b>.</p>
<p>No <b>Profile Downloaded</b> at the top? Go to <b>General → VPN &amp; Device Management</b> and tap <b>{e(CA_NAME)}</b>.</p>
<button class="btn2" id="inst" type="button">I've installed the profile</button>
<p class="fine" style="margin-top:8px">This page can't see inside Settings, so tell it when you're done.</p></div></li>
<li class="next" data-s="3"><h3>Trust it</h3>
<p>One more switch in Settings.</p>
<div class="more"><p>Go to <b>General → About → Certificate Trust Settings</b>. Under <b>Enable full trust for root certificates</b>,
switch on <b>{e(CA_NAME)}</b>, then tap <b>Continue</b>.</p>
<p id="hint" hidden>Still waiting? Make sure that switch is green. This page checks again every 2 seconds.</p></div></li>
<li class="next" data-s="4"><h3>Pair this phone</h3>
<p>Your phone opens your Mac over a secure connection.</p>
<div class="more"><a class="btn2" id="go" href="{e(pair)}" aria-disabled="true">Continue</a></div></li>
</ol>
<div class="live wait" id="live" role="status" aria-live="polite"><i></i><span id="livet">Waiting for your phone to trust this Mac…</span></div>
<details class="fine"><summary>Check it is really your Mac's certificate</summary>
<p>Before you trust it, tap <b>More Details</b> on the certificate in Settings and compare its <b>SHA-256</b> fingerprint with the one
on your Mac's screen. This page cannot show it, because anything on a network could change a page like this.</p></details>
<script>
(function(){{
var steps=document.querySelectorAll("#stp>li"),live=document.getElementById("live"),t=document.getElementById("livet"),
go=document.getElementById("go"),hint=document.getElementById("hint"),trusted=false,tapped=false,started=Date.now();
function mark(n){{steps.forEach(function(li,i){{li.className=i+1<n?"done":i+1===n?"now":"next"}})}}
document.getElementById("dl").addEventListener("click",function(){{tapped=true;if(!trusted)mark(2)}});
document.getElementById("inst").addEventListener("click",function(){{if(!trusted)mark(3)}});
function ok(){{trusted=true;mark(4);go.removeAttribute("aria-disabled");live.className="live ok";
t.textContent="Your phone trusts this Mac. Tap Continue."}}
function probe(){{if(trusted)return;var i=new Image();i.onload=ok;
i.onerror=function(){{if(Date.now()-started>25000&&tapped)hint.hidden=false;setTimeout(probe,2000)}};
i.src={probe!r}+"?t="+Date.now()}}
probe();
document.addEventListener("visibilitychange",function(){{if(!document.hidden&&!trusted)probe()}});
}})();
</script>"""
    return _page("Set up this phone", body)


def pair_form(token: str, path: str):
    """HTTPS: reaching this page already proves the phone trusts the Mac."""
    body = f"""
<h1>Almost done</h1>
<p class="sub">The secure connection works. Give this phone a name, so you can tell it apart on your Mac.</p>
<form method="post" action="{e(path)}">
<label class="lbl" for="n">Name</label>
<input class="fld" id="n" name="name" value="iPhone" maxlength="40" autocomplete="off" enterkeyhint="done">
<button class="btn2" type="submit">Pair this phone</button></form>"""
    return _page("Pair this phone", body)


def home_screen(link: str):
    """HTTPS, paired. The address is swapped for the one-time link, so the icon opens already paired."""
    body = f"""
<h1>Add it to your Home Screen</h1>
<p class="sub">So Magpiary opens like an app, full screen, with its own icon.</p>
<ol class="stp">
<li class="now"><h3>Tap Share</h3><p>The square with an arrow {SHARE} in Safari's toolbar.</p></li>
<li class="now"><h3>Add to Home Screen</h3><p>Scroll down the list and tap <b>Add to Home Screen</b>.</p></li>
<li class="now"><h3>Add</h3><p>Leave <b>Open as Web App</b> switched on, then tap <b>Add</b> (top right).</p></li>
</ol>
<a class="btn2" href="/">Open the library</a>
<p class="fine">Do this from this page, not from another one: the icon needs this page's special address to open already paired.</p>
<script>history.replaceState(null,"",{link!r});</script>"""
    return _page("Add to Home Screen", body, head=f'<link rel="manifest" href="{e(link)}/manifest.webmanifest">')
