// First run for C1+: a full-screen, step-by-step setup. Shows the payoff first, explains privacy in plain
// words, checks each step live, and ends by celebrating the first real share as it is read.
(function () {
  const css = `
.wel { position: fixed; inset: 0; z-index: 75; background: var(--bg); overflow: auto; display: none; }
.wel.on { display: block; }
.w-top { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 18px; padding: 16px clamp(16px, 4vw, 48px); background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(14px); }
.w-prog { display: flex; gap: 6px; margin: 0 auto; }
.w-prog span { display: flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 999px; font-size: 13.5px; font-weight: 600; color: var(--fg-3); background: var(--chip); }
.w-prog span i { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-style: normal; font-size: 11px; background: var(--line); color: var(--fg-2); }
.w-prog span.on { background: var(--fg); color: var(--bg); } .w-prog span.on i { background: var(--t-design); color: #fff; }
.w-prog span.done i { background: var(--ok); color: #fff; } .w-prog span.done { color: var(--fg); }
.w-skip { color: var(--fg-3); font-weight: 600; font-size: 14px; white-space: nowrap; }
.w-body { max-width: 1180px; margin: 0 auto; padding: 24px clamp(16px, 4vw, 48px) 80px; display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 56px; align-items: center; min-height: calc(100vh - 80px); }
.w-body.one { grid-template-columns: minmax(0, 760px); justify-content: center; }
.w-kick { font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--t-design); }
.w-h { font: 800 clamp(40px, 5.6vw, 72px)/.95 var(--display); letter-spacing: -.045em; margin: 12px 0 16px; }
.w-h em { font-style: normal; color: var(--t-design); }
.w-p { font-size: 18px; line-height: 1.55; color: var(--fg-2); margin: 0 0 26px; max-width: 520px; }
.w-cta { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.w-cta .btn { height: 50px; padding: 0 24px; font-size: 15.5px; }
.w-cta small { color: var(--fg-3); font-size: 13px; width: 100%; }
.priv { display: grid; gap: 10px; margin: 0 0 30px; }
.priv > div { display: grid; grid-template-columns: 40px 1fr; gap: 14px; align-items: center; font-size: 15px; }
.priv > div > span { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; font-size: 18px; }
.priv b { display: block; font-family: var(--display); font-size: 16px; }
.priv small { color: var(--fg-2); font-size: 13.5px; }
/* demo loop */
.demo { position: relative; aspect-ratio: 1; max-width: 520px; width: 100%; justify-self: center; }
.demo .fr0, .demo .fr1, .demo .fr2 { position: absolute; inset: 0; display: grid; place-items: center; opacity: 0; transform: translateY(14px) scale(.98); transition: opacity .5s, transform .6s cubic-bezier(.2, .8, .2, 1); }
.demo[data-f="0"] .fr0, .demo[data-f="1"] .fr1, .demo[data-f="2"] .fr2 { opacity: 1; transform: none; }
.iph { width: 46%; aspect-ratio: 9/18.5; border-radius: 40px; background: #111; padding: 10px; box-shadow: 0 40px 80px -20px rgba(0,0,0,.45); position: relative; }
.iph .scr { width: 100%; height: 100%; border-radius: 31px; overflow: hidden; position: relative; background-size: cover; background-position: center; }
.share { position: absolute; left: 6px; right: 6px; bottom: 6px; background: rgba(245,245,245,.96); border-radius: 22px; padding: 14px 12px; color: #111; }
.share .apps { display: flex; gap: 10px; justify-content: space-between; }
.share .ap { display: grid; justify-items: center; gap: 4px; font-size: 10px; color: #444; }
.share .ap i { width: 44px; height: 44px; border-radius: 12px; background: #ddd; }
.share .ap.mg i { background: #111; position: relative; box-shadow: 0 0 0 3px var(--t-design); animation: tap 2.4s infinite; }
.share .ap.mg i::after { content: ""; position: absolute; width: 10px; height: 10px; border-radius: 50%; background: var(--t-design); right: 9px; top: 9px; }
@keyframes tap { 40%, 60% { transform: scale(.88); } }
.share .ap.mg { color: #111; font-weight: 700; }
.mini-tile { width: 54%; border-radius: 22px; overflow: hidden; background: var(--chip); box-shadow: 0 30px 60px -20px rgba(0,0,0,.4); }
.mini-tile .sq { aspect-ratio: 1; background-size: cover; background-position: center; position: relative; }
.mini-tile .lbl { padding: 12px 14px; font: 700 16px/1.15 var(--display); }
.mini-tile .stp { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 0 14px 14px; font-size: 10.5px; color: var(--fg-3); }
.mini-tile .stp i { display: block; height: 4px; border-radius: 2px; background: var(--line); margin-bottom: 4px; position: relative; overflow: hidden; }
.mini-tile .stp i::after { content: ""; position: absolute; inset: 0; background: var(--ok); transform: translateX(-100%); }
.demo[data-f="1"] .stp div:nth-child(1) i::after { animation: fill .45s .2s forwards; }
.demo[data-f="1"] .stp div:nth-child(2) i::after { animation: fill .45s .7s forwards; }
.demo[data-f="1"] .stp div:nth-child(3) i::after { animation: fill .45s 1.2s forwards; }
.demo[data-f="1"] .stp div:nth-child(4) i::after { animation: fill .45s 1.7s forwards; background: var(--t-design); }
@keyframes fill { to { transform: none; } }
.res-card { width: 88%; border-radius: 26px; background: var(--card); box-shadow: 0 30px 70px -20px rgba(0,0,0,.35); border: 1px solid var(--line); display: grid; grid-template-columns: 34% 1fr; overflow: hidden; }
.res-card .v { background-size: cover; background-position: center; min-height: 100%; }
.res-card .in { padding: 18px; }
.res-card .in b.ty { display: inline-block; font-size: 11px; padding: 3px 9px; border-radius: 999px; background: var(--t-howto); color: #fff; }
.res-card h4 { font: 800 19px/1.1 var(--display); letter-spacing: -.02em; margin: 8px 0 6px; }
.res-card p { font-size: 12.5px; color: var(--fg-2); margin: 0 0 8px; line-height: 1.45; }
.res-card .k { display: grid; grid-template-columns: 34px 1fr; font-size: 12px; padding: 4px 0; border-top: 1px solid var(--line); }
.res-card .k em { font-style: normal; color: var(--t-design); font-weight: 700; }
.demo-cap { display: flex; justify-content: center; gap: 8px; margin-top: 14px; }
.demo-cap span { font-size: 13px; font-weight: 600; padding: 6px 12px; border-radius: 999px; background: var(--chip); color: var(--fg-3); transition: all .3s; }
.demo-cap span.on { background: var(--fg); color: var(--bg); }
/* steps */
.chk { display: grid; gap: 10px; margin: 0 0 26px; }
.ck { display: grid; grid-template-columns: 36px 1fr auto; gap: 14px; align-items: center; padding: 14px 16px; border-radius: 20px; background: var(--chip); transition: background .3s; }
.ck .n { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-family: var(--display); background: var(--bg); }
.ck b { font: 700 17px var(--display); display: block; }
.ck small { color: var(--fg-2); font-size: 13.5px; }
.ck .st { font-size: 12.5px; font-weight: 700; padding: 5px 11px; border-radius: 999px; background: var(--bg); color: var(--fg-3); white-space: nowrap; }
.ck.wait .st { animation: p 1.4s infinite; color: var(--fg-2); }
.ck.ok { background: color-mix(in srgb, var(--ok) 12%, var(--bg)); }
.ck.ok .n { background: var(--ok); color: #fff; } .ck.ok .st { background: var(--ok); color: #fff; animation: none; }
.qr { justify-self: center; width: min(400px, 100%); border-radius: 30px; padding: 28px; background: var(--fg); color: var(--bg); text-align: center; }
.qr .code { aspect-ratio: 1; border-radius: 18px; background: #fff; padding: 18px; margin-bottom: 18px; position: relative; }
.qr .code div { width: 100%; height: 100%; background:
  linear-gradient(#111 0 0) 0 0/26% 26% no-repeat, linear-gradient(#111 0 0) 100% 0/26% 26% no-repeat, linear-gradient(#111 0 0) 0 100%/26% 26% no-repeat,
  repeating-conic-gradient(#111 0 25%, #fff 0 50%) 0 0/12.5% 12.5%; border-radius: 6px; }
.qr .code.done::after { content: "✓"; position: absolute; inset: 0; display: grid; place-items: center; background: rgba(30,194,122,.92); color: #fff; font-size: 80px; border-radius: 18px; animation: pop .4s; }
.qr b { font: 800 22px var(--display); display: block; }
.qr small { opacity: .7; font-size: 13px; display: block; margin-top: 6px; }
.why { font-size: 13.5px; color: var(--fg-2); background: var(--chip); border-radius: 16px; padding: 12px 14px; margin-bottom: 22px; }
.wpre { display: grid; gap: 10px; margin-bottom: 18px; }
.wp { display: grid; grid-template-columns: 22px 1fr auto; gap: 14px; align-items: start; padding: 16px; border-radius: 20px; background: var(--chip); border: 2px solid transparent; cursor: pointer; }
.wp.on { border-color: var(--fg); background: var(--bg); }
.wp .rd { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--fg-3); margin-top: 2px; }
.wp.on .rd { border: 7px solid var(--fg); }
.wp b { font: 700 18px var(--display); }
.wp b em { font: 700 11px var(--sans); font-style: normal; padding: 2px 8px; border-radius: 999px; background: var(--t-explainer); color: #fff; margin-left: 6px; vertical-align: 2px; }
.wp p { margin: 3px 0 8px; font-size: 14px; color: var(--fg-2); }
.wp .leaves { font-size: 12.5px; display: flex; gap: 6px; flex-wrap: wrap; }
.wp .leaves span { padding: 3px 9px; border-radius: 999px; background: var(--chip); color: var(--fg-2); }
.wp.on .leaves span { background: var(--chip); }
.wp .spd { font-size: 12.5px; font-weight: 700; color: var(--fg-3); white-space: nowrap; }
.keybox { border-radius: 22px; padding: 18px; background: var(--chip); }
.keybox label { font: 700 16px var(--display); display: block; margin-bottom: 8px; }
.keybox input { width: 100%; height: 50px; border-radius: 14px; border: 2px solid var(--line); background: var(--bg); color: var(--fg); font: inherit; padding: 0 14px; outline: none; }
.keybox input:focus { border-color: var(--fg); }
.kstat { margin-top: 10px; font-size: 13.5px; font-weight: 600; min-height: 20px; }
.kstat.ok { color: var(--ok); } .kstat.chk { color: var(--fg-3); animation: p 1.2s infinite; }
.guide { margin-top: 10px; font-size: 13.5px; color: var(--fg-2); }
.guide ol { margin: 8px 0 0; padding-left: 20px; } .guide li { margin: 3px 0; }
.listen { display: inline-flex; align-items: center; gap: 10px; padding: 10px 16px; border-radius: 999px; background: var(--chip); font-weight: 600; margin-bottom: 22px; }
.listen i { width: 10px; height: 10px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 0 color-mix(in srgb, var(--ok) 60%, transparent); animation: ring 1.6s infinite; }
@keyframes ring { to { box-shadow: 0 0 0 12px transparent; } }
.orpaste { display: flex; gap: 8px; }
.orpaste input { flex: 1; height: 46px; border-radius: 999px; border: 2px solid var(--line); background: var(--bg); color: var(--fg); font: inherit; padding: 0 18px; outline: none; }
.mock-hint { margin-top: 18px; font-size: 12.5px; background: #ffe14d; color: #111; padding: 8px 12px; border-radius: 12px; display: inline-flex; gap: 8px; align-items: center; }
.mock-hint button { font-weight: 800; text-decoration: underline; }
/* arrived */
.arr { text-align: center; position: relative; }
.arr .w-h { margin-top: 6px; }
.big-tile { width: min(340px, 80%); margin: 10px auto 0; border-radius: 26px; overflow: hidden; background: var(--chip); box-shadow: 0 40px 80px -24px rgba(0,0,0,.4); animation: land .8s cubic-bezier(.2, 1.3, .4, 1); text-align: left; }
@keyframes land { from { transform: translateY(-80px) scale(.6) rotate(-6deg); opacity: 0; } }
.big-tile .sq { aspect-ratio: 1; background-size: cover; background-position: center; }
.big-tile .lbl { padding: 14px 16px; font: 700 19px/1.15 var(--display); transition: background .5s, color .5s; }
.flow { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; max-width: 620px; margin: 26px auto 0; }
.flow div { font-size: 12.5px; color: var(--fg-3); font-weight: 600; }
.flow i { display: block; height: 6px; border-radius: 3px; background: var(--line); margin-bottom: 6px; position: relative; overflow: hidden; }
.flow i::after { content: ""; position: absolute; inset: 0; background: var(--ok); transform: translateX(-101%); transition: transform .7s cubic-bezier(.4, 0, .2, 1); }
.flow div.d i::after { transform: none; } .flow div.d { color: var(--fg); }
.flow div.r i::after { transform: translateX(-40%); background: var(--t-design); }
.reveal { max-width: 640px; margin: 28px auto 0; text-align: left; border-radius: 24px; background: var(--chip); padding: 22px; animation: rise .6s cubic-bezier(.2, .8, .2, 1); }
@keyframes rise { from { opacity: 0; transform: translateY(16px); } }
.reveal p { margin: 0 0 10px; font-size: 15.5px; line-height: 1.55; }
.reveal .k { display: grid; grid-template-columns: 44px 1fr; padding: 7px 0; border-top: 1px solid var(--line); font-size: 14.5px; }
.reveal .k em { font-style: normal; font-weight: 700; color: var(--t-design); }
.burst { position: absolute; left: 50%; top: 200px; width: 0; height: 0; pointer-events: none; }
.burst i { position: absolute; width: 10px; height: 10px; border-radius: 3px; animation: bur 1.1s cubic-bezier(.1, .8, .3, 1) forwards; }
@keyframes bur { from { transform: translate(0, 0) rotate(0); opacity: 1; } to { transform: translate(var(--x), var(--y)) rotate(320deg); opacity: 0; } }
@media (max-width: 860px) { .w-body { grid-template-columns: 1fr; gap: 30px; min-height: 0; } .w-prog span b { display: none; } .demo { max-width: 360px; } }
@media (prefers-reduced-motion: reduce) { .wel *, .wel *::after { animation: none !important; transition: none !important; } }
`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  const W = { preset: "smart", key: "", keyOk: false, skippedKey: false, phoneOk: false, timers: [] };
  const clear = () => { W.timers.forEach(clearTimeout); W.timers = []; clearInterval(W.loop); };
  const later = (ms, fn) => W.timers.push(setTimeout(fn, ms));
  const STEPS = [["phone", "Pair your iPhone"], ["reading", "How posts are read"], ["share", "First share"]];
  const top = cur => {
    const idx = STEPS.findIndex(s => s[0] === cur);
    return `<div class="w-top"><span class="logo">magpiary<i></i></span>
      <div class="w-prog">${STEPS.map(([k, l], i) => `<span class="${k === cur ? "on" : idx > i || cur === "arrived" ? "done" : ""}"><i>${idx > i || cur === "arrived" ? "✓" : i + 1}</i><b>${l}</b></span>`).join("")}</div>
      <span class="w-skip"></span></div>`;
  };
  const t15 = "url(example-cover.svg)";

  function hello() {
    $("#wel").innerHTML = `<div class="w-top"><span class="logo">magpiary<i></i></span></div>
    <div class="w-body"><div>
      <div class="w-kick">Welcome</div>
      <h1 class="w-h">Everything you save, <em>finally useful.</em></h1>
      <p class="w-p">Share a reel or post from your iPhone. Your Mac downloads it, watches it, and files a summary you can search by what was said, shown or written.</p>
      <div class="priv">
        <div><span style="background:color-mix(in srgb,var(--t-howto) 15%,transparent)">🖥</span><div><b>Runs on this Mac</b><small>No Magpiary account, no Magpiary server. Your library is one folder you own.</small></div></div>
        <div><span style="background:color-mix(in srgb,var(--t-design) 15%,transparent)">📶</span><div><b>Your phone only talks to this Mac</b><small>Shares wait on the phone and arrive when it's on your home Wi-Fi.</small></div></div>
        <div><span style="background:color-mix(in srgb,var(--t-explainer) 15%,transparent)">🔑</span><div><b>Videos never leave</b><small>Only the caption, transcript and a few frames go to your own AI key, or nothing at all in Private.</small></div></div>
      </div>
      <div class="w-cta"><a class="btn dark" href="#/welcome/phone">Set up · 3 steps, about 4 min</a></div>
    </div>
    <div><div class="demo" id="demo" data-f="0">
      <div class="fr0"><div class="iph"><div class="scr" style="background-image:${t15}"><div class="share"><div class="apps">
        <div class="ap"><i style="background:#25d366"></i>WhatsApp</div><div class="ap mg"><i></i>Magpiary</div><div class="ap"><i style="background:#0a84ff"></i>Messages</div><div class="ap"><i style="background:#ffcc00"></i>Notes</div></div></div></div></div></div>
      <div class="fr1"><div class="mini-tile"><div class="sq" style="background-image:${t15}"></div><div class="lbl">Build a fold-flat desk lamp</div>
        <div class="stp"><div><i></i>Fetch</div><div><i></i>Listen</div><div><i></i>Look</div><div><i></i>Write</div></div></div></div>
      <div class="fr2"><div class="res-card"><div class="v" style="background-image:${t15}"></div><div class="in"><b class="ty">How-to</b><h4>Build a fold-flat desk lamp</h4>
        <p>An invented workshop demo folds a card shade around a low-voltage light module.</p>
        <div class="k"><em>0:12</em>Score the paper hinge</div><div class="k"><em>0:31</em>Leave a cable channel</div><div class="k"><em>1:02</em>Fold flat for storage</div></div></div></div>
    </div><div class="demo-cap" id="dcap"><span class="on">1 · Share</span><span>2 · Your Mac reads it</span><span>3 · Find it any time</span></div></div></div>`;
    let f = 0; W.loop = setInterval(() => { f = (f + 1) % 3; const d = $("#demo"); if (!d) return clear(); d.dataset.f = f; document.querySelectorAll("#dcap span").forEach((s, i) => s.classList.toggle("on", i === f)); }, 2800);
  }

  function phone() {
    $("#wel").innerHTML = top("phone") + `<div class="w-body"><div>
      <div class="w-kick">Step 1 of 3</div><h1 class="w-h">Pair your <em>iPhone.</em></h1>
      <p class="w-p">Point the iPhone camera at the code. Everything below ticks itself off as it happens; you don't need to come back to the Mac.</p>
      <div class="chk">
        <div class="ck wait" id="c1"><span class="n">1</span><div><b>Scan the code</b><small>Opens the install page on your phone</small></div><span class="st">Waiting…</span></div>
        <div class="ck" id="c2"><span class="n">2</span><div><b>Add the Share shortcut</b><small>Tap “Add Shortcut”. Magpiary then shows up when you tap Share.</small></div><span class="st">Next</span></div>
        <div class="ck" id="c3"><span class="n">3</span><div><b>Send when I get home</b><small>One automation, so shares arrive by themselves</small></div><span class="st">Next</span></div>
      </div>
      <div class="why"><b>Why “when I get home”?</b> Your phone never talks to the internet for Magpiary. It keeps what you share while you're out and hands it to this Mac when it joins your home Wi-Fi.</div>
      <div class="w-cta"><a class="btn dark" id="pnext" href="#/welcome/reading" aria-disabled="true">Continue</a><a class="btn" href="#/welcome/reading" style="background:none">I'll do this later</a></div>
      <div class="mock-hint">Mockup: the checks tick by themselves. <button id="replay">Replay</button></div>
    </div><div><div class="qr"><div class="code" id="qrc"><div></div></div><b>Scan with your iPhone camera</b><small>Can't scan? On the phone, open magpiary.local:8765/install<br>The code works for 15 minutes.</small></div></div></div>`;
    const tick = (id, label) => { const c = $(id); c.classList.remove("wait"); c.classList.add("ok"); c.querySelector(".st").textContent = label; };
    const wait = id => { const c = $(id); c.classList.add("wait"); c.querySelector(".st").textContent = "Waiting…"; };
    const run = () => { later(1800, () => { tick("#c1", "✓ Opened on iPhone"); $("#qrc").classList.add("done"); wait("#c2"); });
      later(3600, () => { tick("#c2", "✓ Shortcut added"); wait("#c3"); });
      later(5600, () => { tick("#c3", "✓ Test share received"); W.phoneOk = true; $("#pnext").removeAttribute("aria-disabled"); }); };
    run(); $("#replay").onclick = () => { clear(); phone(); };
  }

  function reading() {
    // Smart (the specs' Balanced) or Private; the right side shows what that choice needs.
    const P = [["smart", "Smart", "Your Mac makes the transcript and picks a few frames; your own AI key reads them. The best summaries.", ["Leaves the Mac: caption, transcript, a few frames"], "~20 s a post", true],
      ["private", "Private", "Everything happens on this Mac. No key, nothing leaves. Simpler summaries, and slower.", ["Leaves the Mac: nothing"], "~2 min a post"]];
    const smart = W.preset === "smart";
    $("#wel").innerHTML = top("reading") + `<div class="w-body"><div>
      <div class="w-kick">Step 2 of 3</div><h1 class="w-h">How should posts be <em>read?</em></h1>
      <p class="w-p">You can change this any time in Settings. The video itself never leaves this Mac either way.</p>
      <div class="wpre">${P.map(([k, n, d, l, sp, rec]) => `<div class="wp ${W.preset === k ? "on" : ""}" data-pre="${k}"><span class="rd"></span><div><b>${n}${rec ? "<em>Recommended</em>" : ""}</b><p>${d}</p><div class="leaves">${l.map(x => `<span>${x}</span>`).join("")}</div></div><span class="spd">${sp}</span></div>`).join("")}</div>
    </div><div>
      ${smart ? `<div class="keybox"><label>Paste your Gemini key</label><input id="kin" placeholder="AIza…" autocomplete="off" value="${W.key}"><div class="kstat ${W.keyOk ? "ok" : ""}" id="kst">${W.keyOk ? "✓ Works · free · picked the newest model that answers quickly" : ""}</div>
        <details class="guide"><summary><b>Get a free key in 2 minutes</b></summary><ol><li>Open Google AI Studio and sign in with any Google account.</li><li>Click “Create API key”.</li><li>Copy it and paste it above. Magpiary checks it straight away.</li></ol></details>
        <p style="font-size:12.5px;color:var(--fg-3);margin:12px 0 0">Stored only on this Mac (~/.config/magpiary, owner-only) and never shown again. With a free key, Google may use what's sent to improve its products. You can add more keys later; Magpiary moves to the next when one hits its daily limit.</p></div>`
      : `<div class="keybox"><label>No key needed</label><p style="margin:0;color:var(--fg-2);font-size:14px">Magpiary downloads a reading model once (about 2.5 GB) and runs it on this Mac's chip, offline. On an M1 Pro, about 2 minutes a post. You can switch to Smart later.</p>
        <div class="kstat ok" style="margin-top:10px">✓ Your Mac can run it · 16 GB memory</div></div>`}
      <div class="w-cta" style="margin-top:22px"><a class="btn dark" id="rnext" href="#/welcome/share"${smart && !W.keyOk ? ' aria-disabled="true"' : ""}>${smart ? "Continue" : "Download and continue"}</a>
        ${smart ? `<a class="btn" href="#/welcome/share" id="skipkey" style="background:none">Skip · just save posts for now</a><small>Without a key, posts are still saved, searchable by caption, and playable. Summaries can be added later.</small>` : ""}</div>
    </div></div>`;
    document.querySelectorAll("[data-pre]").forEach(el => el.onclick = () => { W.preset = el.dataset.pre; reading(); });
    $("#skipkey")?.addEventListener("click", () => { W.skippedKey = true; });
    $("#rnext").addEventListener("click", () => { W.skippedKey = false; });
    const k = $("#kin");
    if (k) k.oninput = () => { W.key = k.value; W.keyOk = false; const s = $("#kst"); clear();
      if (k.value.trim().length < 8) { s.className = "kstat"; s.textContent = ""; $("#rnext").setAttribute("aria-disabled", "true"); return; }
      s.className = "kstat chk"; s.textContent = "Checking with Google…";
      later(1300, () => { W.keyOk = true; s.className = "kstat ok"; s.textContent = "✓ Works · free · picked the newest model that answers quickly"; $("#rnext").removeAttribute("aria-disabled"); }); };
  }

  function share() {
    $("#wel").innerHTML = top("share") + `<div class="w-body"><div>
      <div class="w-kick">Step 3 of 3</div><h1 class="w-h">Now share <em>something.</em></h1>
      <p class="w-p">On your iPhone, open any reel or post you like, tap <b>Share</b>, then <b>Magpiary</b>. It lands here in a few seconds.</p>
      <div class="listen"><i></i>Listening for your iPhone on home Wi-Fi…</div>
      <p style="color:var(--fg-3);font-size:14px;margin:0 0 8px">No phone handy? Paste a link instead:</p>
      <div class="orpaste"><input id="wurl" placeholder="https://www.instagram.com/reel/…"><button class="btn dark" id="wgo">Add</button></div>
      <div class="mock-hint">Mockup: <button id="simshare">Simulate a share from the iPhone</button></div>
    </div><div><div class="demo" data-f="0" style="max-width:400px"><div class="fr0"><div class="iph" style="width:62%"><div class="scr" style="background-image:url(example-cover.svg)"><div class="share"><div class="apps">
      <div class="ap"><i style="background:#25d366"></i>WhatsApp</div><div class="ap mg"><i></i>Magpiary</div><div class="ap"><i style="background:#0a84ff"></i>Messages</div><div class="ap"><i style="background:#ffcc00"></i>Notes</div></div></div></div></div></div></div></div></div>`;
    const go = () => { location.hash = "#/welcome/arrived"; };
    $("#simshare").onclick = go; $("#wgo").onclick = go; $("#wurl").onkeydown = e => { if (e.key === "Enter") go(); };
  }

  function arrived() {
    const it = M.byId[15], noKey = W.skippedKey;
    $("#wel").innerHTML = top("arrived") + `<div class="w-body one"><div class="arr"><div class="burst" id="burst"></div>
      <div class="w-kick">From your iPhone · just now</div><h1 class="w-h" id="ah">It's here.</h1>
      <div class="big-tile"><div class="sq" style="background-image:url(example-cover.svg)"></div><div class="lbl" id="alb">Build a fold-flat desk lamp</div></div>
      <div class="flow" id="aflow">${["Arrived", "Saved to Mac", "Listened", "Looked", "Written"].map(s => `<div><i></i>${s}</div>`).join("")}</div>
      <div id="arev"></div></div></div>`;
    const steps = document.querySelectorAll("#aflow div");
    const upto = noKey ? 2 : 5;
    steps.forEach((s, i) => { if (i < upto) later(500 + i * 1100, () => { s.classList.remove("r"); s.classList.add("d"); if (steps[i + 1] && i + 1 < upto) steps[i + 1].classList.add("r"); }); });
    later(500 + upto * 1100, () => {
      const lb = $("#alb"); const b = $("#burst");
      b.innerHTML = Array.from({ length: 28 }, (_, i) => { const a = i / 28 * Math.PI * 2, r = 140 + Math.random() * 120; return `<i style="--x:${Math.cos(a) * r}px;--y:${Math.sin(a) * r}px;background:${["var(--t-howto)", "var(--t-design)", "var(--t-explainer)", "var(--t-discussion)", "var(--t-tool)"][i % 5]}"></i>`; }).join("");
      if (noKey) {
        lb.style.background = SRC_C.instagram; lb.style.color = "#fff";
        $("#ah").innerHTML = "Saved. <em>You're set up.</em>";
        $("#arev").innerHTML = `<div class="reveal"><p>Your post is on this Mac, searchable by its caption, and ready to watch. Add a free key any time and Magpiary will summarise everything you've saved.</p>
          <div class="w-cta" style="justify-content:center;margin-top:14px"><a class="btn dark" href="#/" data-finish>Open my wall</a><a class="btn" href="#/welcome/reading">Add a key now</a></div></div>`;
      } else {
        lb.style.background = "var(--t-howto)"; lb.style.color = "#fff"; lb.textContent = it.title;
        $("#ah").innerHTML = "Read in 21 seconds. <em>You're set up.</em>";
        $("#arev").innerHTML = `<div class="reveal"><p>${esc(it.summary)}</p>${it.points.slice(0, 3).map(([at, t]) => `<div class="k"><em>${at}</em>${esc(t)}</div>`).join("")}
          <div class="w-cta" style="justify-content:center;margin-top:18px"><a class="btn dark" href="#/" data-finish>Open my wall</a></div>
          <p style="text-align:center;font-size:13px;color:var(--fg-3);margin:12px 0 0">From now on, just share. Magpiary handles the rest, even when you're not looking.</p></div>`;
      }
    });
  }

  document.addEventListener("click", e => {
    if (e.target.closest("[data-finish]")) { clear(); opt.state = W.skippedKey ? "nokey" : "normal"; syncMock(); ticker(); toast("Welcome to Magpiary"); }
  }, true);

  window.welcome = function (step) {
    clear();
    ({ hello, phone, reading, share, arrived }[step] || hello)();
    $("#wel").scrollTop = 0;
  };
})();
