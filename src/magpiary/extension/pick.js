/* Pick mode. Injected only when the owner presses "Pick a post on this page" (activeTab), so nothing runs on a site until asked.
 * It reads post addresses already on the page (anchors), makes no request, scrolls and clicks nothing for the owner, and draws
 * in a closed shadow root outside the site's own markup. A click on a post opens a small panel; nothing is sent until Save. */
(function () {
  if (globalThis.__magpiaryPick) { globalThis.__magpiaryPick.stop(); return; }
  const clean = MagpiaryClean.clean;
  const ago = (iso) => {
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (!(mins >= 0)) return "";
    if (mins < 2) return "just now";
    if (mins < 90) return `${mins} minutes ago`;
    const hours = Math.round(mins / 60);
    if (hours < 36) return `${hours} hours ago`;
    const days = Math.round(hours / 24);
    return days < 45 ? `${days} days ago` : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };
  /** Is this post already in the library? Asked of the owner's Mac only (never of the site), once per post. */
  const seenCache = new Map();
  const lookupSeen = (url) => {
    if (!seenCache.has(url)) {
      seenCache.set(url, chrome.runtime.sendMessage({ type: "seen", urls: [url] }).then((m) => (m && m[url]) || { saved: false }).catch(() => ({ saved: false })));
    }
    return seenCache.get(url);
  };

  /** One entry per post: Instagram /p/ID and /reels/ID are the same post; Threads /media is the same post. */
  function postOf(href) {
    let abs;
    try { abs = new URL(href, location.href).href; } catch (_) { return null; }
    if (/instagram\.com\/(?:[^/]+\/)?reels?\/audio\b/i.test(abs)) return null; // an audio page, not a post
    const c = clean(abs);
    if (c.error || c.source === "other" || !c.kind) return null; // a profile, a tag or a short link: not one post
    return { url: c.url, key: c.url.replace(/\/(p|reel|tv)\//, "/x/"), label: `${c.source} ${c.kind}` };
  }

  function postsIn(node) {
    const found = new Map();
    const anchors = node.matches && node.matches("a[href]") ? [node] : [];
    for (const a of [...anchors, ...node.querySelectorAll("a[href]")]) {
      const p = postOf(a.getAttribute("href"));
      if (p && !found.has(p.key)) found.set(p.key, p);
    }
    return [...found.values()];
  }

  /** The largest ancestor holding exactly one post address is the card. If the nearest card holds several, offer them all. */
  function resolve(el) {
    let best = null, many = null;
    for (let n = el; n && n !== document.documentElement && n !== document.body; n = n.parentElement) {
      const posts = postsIn(n);
      if (posts.length === 1) best = { node: n, posts };
      else if (posts.length > 1) { if (!best) many = posts.length <= 4 ? { node: n, posts } : null; break; }
    }
    return best || many;
  }

  const host = document.createElement("magpiary-" + Math.random().toString(36).slice(2, 10));
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    :host{all:initial}
    .box{position:fixed;pointer-events:none;border:2px solid #ff2e93;background:rgba(255,46,147,.10);border-radius:14px;z-index:2147483646;display:none}
    .bar{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:8px 16px;border-radius:999px;background:#111;color:#fff;font:600 13px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.3)}
    .panel{position:fixed;z-index:2147483647;width:290px;padding:14px;border-radius:18px;background:#fff;color:#111;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;box-shadow:0 24px 60px -12px rgba(0,0,0,.4),0 0 0 1px rgba(0,0,0,.06);display:none}
    @media (prefers-color-scheme:dark){.panel{background:#1c1c1c;color:#f5f3ee;box-shadow:0 24px 60px -12px rgba(0,0,0,.7),0 0 0 1px rgba(255,255,255,.1)}.panel textarea{background:#0f0f0f;color:#f5f3ee;border-color:#2a2a2a}.row button{background:transparent;color:#f5f3ee;border-color:#2a2a2a}.row .go{background:#f5f3ee;color:#111;border-color:#f5f3ee}.panel label,.panel small{color:#97948b}}
    .panel label{display:block;margin:0 0 10px;color:#555;font-weight:600;font-size:12.5px}.panel small{color:#6b6b6b;font-weight:400}
    .panel textarea{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:8px 10px;border:1px solid #ececec;border-radius:12px;font:14px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;color:#111;background:#fff}
    .fl{margin:0 0 10px}.fl-t{display:block;color:#555;font-weight:600;font-size:12.5px}
    .pb{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;box-sizing:border-box;margin-top:5px;padding:8px 10px;border:0;border-radius:12px;background:#f4f4f2;color:#111;font:14px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;text-align:left;cursor:pointer}
    .pb svg{flex:none;width:14px;height:14px;color:#888;transition:transform .15s}.pb[aria-expanded="true"] svg{transform:rotate(180deg)}
    .pu{margin:6px 0 0;padding:4px;list-style:none;background:#f4f4f2;border-radius:14px;max-height:170px;overflow-y:auto}
    .pu li{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-radius:10px;cursor:pointer;color:#111}
    .pu li:hover,.pu li:focus{background:rgba(0,0,0,.07);outline:none}.pu li svg{flex:none;width:15px;height:15px;color:#0a7a4a;visibility:hidden}
    .pu li[aria-selected="true"]{font-weight:700}.pu li[aria-selected="true"] svg{visibility:visible}
    @media (prefers-color-scheme:dark){.fl-t{color:#97948b}.pb,.pu{background:#2a2a2a;color:#f5f3ee}.pu li{color:#f5f3ee}.pu li:hover,.pu li:focus{background:rgba(255,255,255,.09)}.panel textarea{background:#2a2a2a;border-color:transparent}}
    .add{display:inline-block;margin:0 0 12px;padding:6px 12px;border-radius:12px;border:1px dashed #cfcfcf;background:transparent;color:#555;font:600 13px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;cursor:pointer}
    @media (prefers-color-scheme:dark){.add{border-color:#3a3a3a;color:#b9b6ae}}
    .row{display:flex;gap:8px}.row button{flex:1;padding:9px;border-radius:12px;border:1px solid #ececec;background:#fff;color:#111;font:700 14px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;cursor:pointer}
    .row .go{background:#111;color:#fff;border-color:#111}.cand{display:block;margin:0 0 8px;padding:8px 10px;border-radius:12px;background:rgba(127,127,127,.1);word-break:break-all;font-weight:600;font-size:13px}
    button:focus-visible,select:focus-visible,textarea:focus-visible,input:focus-visible{outline:2px solid #ff2e93;outline-offset:1px}
    .tag{position:absolute;top:8px;left:8px;display:none;padding:2px 10px;border-radius:999px;background:#0a7a4a;color:#fff;font:700 12px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
    .sn{margin:0 0 10px;padding:8px 10px;border-radius:12px;background:rgba(10,122,74,.13);color:#0a7a4a;font-weight:700;font-size:13px}
    .sg{margin:0 0 10px}.sg button{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:8px 10px;border-radius:12px;border:1px solid rgba(255,46,147,.35);background:rgba(255,46,147,.1);color:inherit;font:700 13px -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;text-align:left;cursor:pointer}.sg small{display:block;font-weight:400;opacity:.7}
    .msg{margin:8px 0 0;min-height:1.3em;font-size:13px}.ok{color:#0a7a4a;font-weight:600}.bad{color:#c9252d}
  </style><div class="box"><span class="tag"></span></div><div class="bar">Click the post you want · Esc to cancel</div><div class="panel"></div>`;
  const box = root.querySelector(".box"), tag = root.querySelector(".tag"), panel = root.querySelector(".panel"), bar = root.querySelector(".bar");
  document.documentElement.append(host);

  let current = null, frozen = false, queued = false, lastEl = null;

  function draw() {
    queued = false;
    const r = current && current.node.getBoundingClientRect();
    if (!r || !r.width) { box.style.display = "none"; return; }
    Object.assign(box.style, { display: "block", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
    tag.style.display = "none";
    if (current.posts.length === 1) {   // a post you already saved says so before you click it
      const url = current.posts[0].url;
      lookupSeen(url).then((info) => {
        if (info.saved && current && current.posts.length === 1 && current.posts[0].url === url) {
          tag.textContent = `Saved${info.count > 1 ? ` · ${info.count} times` : ""}`;
          tag.style.display = "inline-block";
        }
      });
    }
  }
  function onMove(e) {
    if (frozen) return;
    lastEl = e.target;
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { current = lastEl && lastEl !== host ? resolve(lastEl) : null; draw(); });
  }
  const swallow = (e) => { if (!frozen && current) { e.preventDefault(); e.stopImmediatePropagation(); } };
  function onClick(e) {
    if (frozen || !current) return;
    e.preventDefault(); e.stopImmediatePropagation();
    openPanel(e.clientX, e.clientY);
  }

  async function openPanel(x, y) {
    frozen = true;
    bar.style.display = "none";
    const posts = current.posts;
    panel.innerHTML = "";
    const pick = posts.map((p, i) => `<label class="cand"><input type="radio" name="p" value="${i}"${i === 0 ? " checked" : ""}> ${p.label}<br><small>${p.url.replace(/^https:\/\/(www\.)?/, "")}</small></label>`).join("");
    panel.insertAdjacentHTML("beforeend", `<div id="sn" class="sn" style="display:none"></div>${pick}<div class="fl"><span class="fl-t">Board</span><button type="button" id="bb" class="pb" aria-haspopup="listbox" aria-expanded="false"><span id="bl">Just my library</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button><ul id="bu" class="pu" role="listbox" style="display:none"></ul></div>
      <div id="sg" class="sg" style="display:none"><span class="fl-t">Looks like</span><button type="button" id="sgb"></button></div>
      <button id="an" class="add">+ Add note</button><label id="nb" style="display:none">Note<textarea id="n" rows="2" maxlength="2000"></textarea></label>
      <div class="row"><button id="c">Cancel</button><button id="s" class="go">Save</button></div><p class="msg" id="m"></p>`);
    panel.style.display = "block";
    panel.style.left = Math.max(8, Math.min(innerWidth - 296, x + 12)) + "px";
    panel.style.top = Math.max(8, Math.min(innerHeight - 260, y + 12)) + "px";
    const $ = (id) => panel.querySelector(id);
    let picked = "";
    const boards = [{ id: "", name: "Just my library" }];
    const draw = () => {
      const ul = $("#bu");
      ul.innerHTML = "";
      for (const b of boards) {
        const li = document.createElement("li");
        li.setAttribute("role", "option"); li.tabIndex = -1; li.setAttribute("aria-selected", String(b.id === picked));
        const t = document.createElement("span"); t.textContent = b.name; li.append(t);
        li.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>');
        li.onclick = () => { setBoard(b); $("#bb").focus({ preventScroll: true }); };
        li.onkeydown = (e) => {
          const items = [...ul.children], i = items.indexOf(li);
          if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(i + 1, items.length - 1)].focus(); }
          else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(i - 1, 0)].focus(); }
          else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); li.click(); }
          else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); shut(); $("#bb").focus({ preventScroll: true }); }
        };
        ul.append(li);
      }
    };
    const setBoard = (b) => { picked = b.id; $("#bl").textContent = b.name; shut(); draw(); };
    const shut = () => { $("#bu").style.display = "none"; $("#bb").setAttribute("aria-expanded", "false"); };
    $("#bb").onclick = () => {
      if ($("#bu").style.display === "none") { draw(); $("#bu").style.display = "block"; $("#bb").setAttribute("aria-expanded", "true"); $("#bu").querySelector('[aria-selected="true"]').focus({ preventScroll: true }); }
      else shut();
    };
    const showSeen = async () => {   // already saved? asked about whichever post is chosen
      const chosen = posts[Number((panel.querySelector("input[name=p]:checked") || { value: 0 }).value)];
      const info = await lookupSeen(chosen.url);
      $("#sn").style.display = info.saved ? "block" : "none";
      $("#sn").textContent = info.saved ? `Already saved ${ago(info.last)}${info.count > 1 ? ` · ${info.count} times` : ""}`.replace("saved  ", "saved ") : "";
      $("#s").textContent = info.saved ? "Save again" : "Save";
    };
    showSeen();
    panel.querySelectorAll("input[name=p]").forEach((r) => r.addEventListener("change", showSeen));
    chrome.runtime.sendMessage({ type: "suggest", url: posts[0].url }).then((sg) => {   // the board that fits, from what you just saved
      if (!sg) return;
      $("#sg").style.display = "block";
      $("#sgb").innerHTML = "";
      $("#sgb").append(sg.name, Object.assign(document.createElement("small"), { textContent: sg.reason }));
      $("#sgb").onclick = () => { if (!boards.some((b) => b.id === sg.id)) boards.push({ id: sg.id, name: sg.name }); setBoard({ id: sg.id, name: sg.name }); $("#sg").style.display = "none"; };
    }).catch(() => {});
    $("#an").onclick = () => { $("#an").style.display = "none"; $("#nb").style.display = "block"; $("#n").focus({ preventScroll: true }); };
    $("#s").focus({ preventScroll: true });
    chrome.runtime.sendMessage({ type: "boards" }).then((list) => {
      boards.push(...(list || []));
    });
    $("#c").onclick = () => { frozen = false; panel.style.display = "none"; bar.style.display = ""; };
    $("#s").onclick = async () => {
      $("#s").disabled = true;
      const chosen = posts[Number((panel.querySelector("input[name=p]:checked") || { value: 0 }).value)];
      const res = await chrome.runtime.sendMessage({ type: "save", url: chosen.url, note: $("#n").value, board: picked });
      const m = $("#m");
      if (res.state === "ok") { m.className = "msg ok"; m.textContent = res.savedCount > 1 ? `Saved again (${res.savedCount} times).` : "Saved to Magpiary."; setTimeout(stop, 1100); }
      else if (res.state === "offline") { m.className = "msg bad"; m.textContent = "Magpiary isn't answering. It will save when your Mac is ready."; setTimeout(stop, 2200); }
      else { m.className = "msg bad"; m.textContent = res.state === "unpaired" || res.state === "revoked" ? "Pair this browser in the Magpiary toolbar panel." : "That link can't be saved."; $("#s").disabled = false; }
    };
  }

  function onKey(e) { if (e.key === "Escape") stop(); }
  function stop() {
    for (const t of ["mousemove", "pointerdown", "mousedown", "mouseup"]) document.removeEventListener(t, t === "mousemove" ? onMove : swallow, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKey, true);
    host.remove();
    delete globalThis.__magpiaryPick;
  }
  document.addEventListener("mousemove", onMove, true);
  for (const t of ["pointerdown", "mousedown", "mouseup"]) document.addEventListener(t, swallow, true);
  document.addEventListener("click", onClick, true);
  document.addEventListener("keydown", onKey, true);
  globalThis.__magpiaryPick = { stop };
})();
