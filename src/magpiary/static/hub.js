// Magpiary's progressive enhancements for the server-rendered hub: in-place navigation, GSAP tile motion,
// post playback, hover previews, selection and menus, Nest, search, Settings, onboarding and Ask Magpiary.
// Motion respects reduced motion. The service renders the pages; this file coordinates their live interactions.
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const root = document.documentElement;
  root.classList.add("js");
  const csrf = $('meta[name="csrf"]')?.content || "";
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const G = () => (!calm && window.gsap) ? window.gsap : null;
  // the focus ring is for the keyboard only: it shows once a key has been used and goes at the next click or touch
  addEventListener("keydown", (ev) => { if (!ev.metaKey && !ev.ctrlKey && !ev.altKey) document.documentElement.dataset.kb = "1"; }, true);
  addEventListener("pointerdown", () => { delete document.documentElement.dataset.kb; }, true);
  const F = () => (G() && window.Flip) ? window.Flip : null;
  if (window.gsap && window.Flip) window.gsap.registerPlugin(window.Flip);
  const page = () => document.body.dataset.page || "";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const store = { get: (k, d) => { try { return JSON.parse(localStorage.getItem("mag-" + k)) ?? d; } catch (e) { return d; } },
                  set: (k, v) => { try { localStorage.setItem("mag-" + k, JSON.stringify(v)); } catch (e) { /* private window */ } } };
  const FORM = { "Content-Type": "application/x-www-form-urlencoded" };
  const rand = (a, b) => a + Math.random() * (b - a);
  const inView = (r) => r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  // a picture that fails to load is tried once more, then gives way to a designed "no preview" (the tile's title and
  // colour stay, and it still opens the post); never the browser's broken-image mark, and nothing about the save changes
  const failedPic = (img) => {
    if (!img.closest(".sq, .stack, .peek, .th")) return;
    if (!img.dataset.retried) { img.dataset.retried = "1"; setTimeout(() => { img.src = img.src.split("#")[0] + "#again"; }, rand(500, 1500)); return; }
    const box = img.parentElement;
    img.remove();
    box.classList.add("noimg");
  };
  document.addEventListener("error", (ev) => { if (ev.target instanceof HTMLImageElement) failedPic(ev.target); }, true);
  $$("img").forEach((img) => { if (img.complete && img.getAttribute("src") && !img.naturalWidth) failedPic(img); });
  // while GSAP moves tiles, the CSS hover transitions on them are switched off so the two never fight
  let movingT = null;
  const moving = (ms = 800) => { root.classList.add("moving"); clearTimeout(movingT); movingT = setTimeout(() => root.classList.remove("moving"), ms); };
  // keep the first tile under the bar where it was across a layout change (the browser's own anchoring is off
  // while things move, because it shifts the page after GSAP has measured and makes headers leap)
  const topH = () => parseInt(getComputedStyle(root).getPropertyValue("--top-h")) || 64;
  function anchored(change) {
    const under = topH();
    const a = $$("#view .tile[data-id], #view .pile").find((t) => t.getBoundingClientRect().bottom > under + 20);
    const y0 = a && scrollY > 0 ? a.getBoundingClientRect().top : null;
    const s0 = scrollY;
    change();
    if (y0 !== null && a.isConnected) scrollTo({ top: scrollY + a.getBoundingClientRect().top - y0, behavior: "instant" });
    return scrollY - s0;
  }

  // ---- toasts and the confirm dialog ------------------------------------------------------------------
  let toastBox = $("#toasts");
  if (!toastBox) { toastBox = document.createElement("div"); toastBox.id = "toasts"; toastBox.setAttribute("aria-live", "polite"); document.body.append(toastBox); }
  function toast(text, opts = {}) {
    if (!text) return;
    const t = document.createElement("div");
    t.className = "toast" + (opts.bad ? " bad" : "");
    t.innerHTML = `<span>${esc(text)}</span>` + (opts.undo ? '<button type="button">Undo</button>' : "");
    toastBox.append(t);
    const g = G();
    const drop = () => { if (!t.isConnected) return; if (g) g.to(t, { y: 20, opacity: 0, duration: .25, onComplete: () => t.remove() }); else t.remove(); };
    if (opts.undo) $("button", t).onclick = () => { opts.undo(); drop(); };
    if (g) g.fromTo(t, { y: 30, opacity: 0, scale: .96 }, { y: 0, opacity: 1, scale: 1, duration: .45, ease: "back.out(1.8)" });
    setTimeout(drop, opts.ms || (opts.undo ? 6000 : 3000));
  }
  function ask(text, ok = "Continue", danger = false) {
    return new Promise((resolve) => {
      const d = document.createElement("div");
      d.className = "dlg-wrap";
      d.innerHTML = `<div class="dlg" role="alertdialog" aria-modal="true"><p>${esc(text)}</p><div class="row">` +
        `<button type="button" class="btn" data-no>Cancel</button><button type="button" class="btn ${danger ? "dangerfill" : "dark"}" data-yes>${esc(ok)}</button></div></div>`;
      document.body.append(d);
      const done = (v) => { document.removeEventListener("keydown", key, true); const g = G(); if (g) g.to(d, { opacity: 0, duration: .15, onComplete: () => d.remove() }); else d.remove(); resolve(v); };
      const key = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); done(false); } if (ev.key === "Enter") { ev.preventDefault(); done(true); } };
      document.addEventListener("keydown", key, true);
      d.addEventListener("click", (ev) => { if (ev.target === d || ev.target.closest("[data-no]")) done(false); if (ev.target.closest("[data-yes]")) done(true); });
      $("[data-yes]", d).focus();
      G()?.from($(".dlg", d), { y: 14, opacity: 0, scale: .97, duration: .25, ease: "power3.out" });
    });
  }
  // a job that costs time or quota says so first: how many posts, how long, what it spends (numbers come from the server)
  function askJob(title, lines, ok = "Continue") {
    return new Promise((resolve) => {
      const d = document.createElement("div");
      d.className = "dlg-wrap";
      d.innerHTML = `<div class="dlg dlgjob" role="alertdialog" aria-modal="true"><h3>${esc(title)}</h3><div class="jobrows">` +
        lines.filter((l) => l[1]).map(([k, v]) => `<div class="jr"><span>${esc(k)}</span><p>${esc(v)}</p></div>`).join("") +
        `</div><div class="row"><button type="button" class="btn" data-no>Cancel</button><button type="button" class="btn dark" data-yes>${esc(ok)}</button></div></div>`;
      document.body.append(d);
      const done = (v) => { document.removeEventListener("keydown", key, true); const g = G(); if (g) g.to(d, { opacity: 0, duration: .15, onComplete: () => d.remove() }); else d.remove(); resolve(v); };
      const key = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); done(false); } if (ev.key === "Enter") { ev.preventDefault(); done(true); } };
      document.addEventListener("keydown", key, true);
      d.addEventListener("click", (ev) => { if (ev.target === d || ev.target.closest("[data-no]")) done(false); if (ev.target.closest("[data-yes]")) done(true); });
      $("[data-yes]", d).focus();
      G()?.from($(".dlg", d), { y: 14, opacity: 0, scale: .97, duration: .25, ease: "power3.out" });
    });
  }
  // more than a few posts: ask the server what it would take, show it, and go on only if the owner agrees
  async function confirmBulk(job, ids) {
    let est = null;
    try { est = await (await fetch(`/stats/estimate.json?job=${job}&ids=${ids.join(",")}`, { cache: "no-store" })).json(); } catch (e) { /* fall through to a plain question */ }
    if (est && !est.confirm) return true;
    const n = ids.length, s = n === 1 ? "" : "s";
    if (!est) return ask(`${job === "again" ? "Re-read" : "Refresh the numbers of"} ${n} posts?`, "Continue");
    return askJob(job === "again" ? `Write ${n} new summar${n === 1 ? "y" : "ies"}?` : `Refresh numbers for ${n} post${s}?`,
      [["Posts", String(est.posts)], ["How long", est.time], ["What it costs", est.cost], ["How it runs", est.note]],
      job === "again" ? "Write them" : "Start refreshing");
  }
  // a button's icon turns into a tick that draws itself, then goes back: proof that the thing happened, beside the toast
  function confirmIcon(btn) {
    const svg = btn && $("svg", btn);
    if (!svg || btn.dataset.ticking) return;
    btn.dataset.ticking = "1";
    const was = svg.innerHTML, colour = svg.style.color;
    svg.innerHTML = '<path d="M5 12.5l4.5 4.5L19 7" pathLength="1" style="stroke-dasharray:1;stroke-dashoffset:1"/>';
    svg.style.color = "#4fe0a4";
    $("path", svg).animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 340, delay: 90, easing: "cubic-bezier(.3,.7,.2,1)", fill: "forwards" });
    btn.animate([{ transform: "scale(.78)" }, { transform: "scale(1.2)", offset: .45 }, { transform: "scale(1)" }], { duration: 440, easing: "cubic-bezier(.2,.9,.3,1)" });
    setTimeout(() => {
      if (!svg.isConnected) return;
      svg.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160 }).finished.then(() => { svg.innerHTML = was; svg.style.color = colour; delete btn.dataset.ticking; svg.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 }); });
    }, 1500);
  }
  const writeCopy = async (text) => {  // some browsers and panes refuse the clipboard call; the older way still works there
    try { await navigator.clipboard.writeText(text); return; } catch (e) { /* try the older way */ }
    const box = document.createElement("textarea");
    box.value = text; box.style.position = "fixed"; box.style.opacity = "0";
    document.body.append(box); box.select();
    const done = document.execCommand("copy");
    box.remove();
    if (!done) throw new Error("copy refused");
  };
  const copy = async (text, what, btn) => { try { await writeCopy(text); toast(what + " copied"); confirmIcon(btn); } catch (e) { toast("Couldn't copy", { bad: true }); } };

  // the post page's own bar sits outside the post, so wireCard never saw its copy button
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest(".crumbbar [data-copylink]"); if (!b) return;
    copy(b.dataset.copylink, "Link", b); b.closest("details")?.removeAttribute("open");
  });

  // ---- talking to the hub -------------------------------------------------------------------------------
  const post = (action, fields) => fetch(action, { method: "POST", body: new URLSearchParams({ csrf, ...fields }), headers: FORM });
  async function getDoc(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok && r.status !== 404) throw new Error(String(r.status));
    return { doc: new DOMParser().parseFromString(await r.text(), "text/html"), url: r.url };
  }
  const hubPath = (u) => {
    const url = new URL(u, location.href);
    if (url.origin !== location.origin) return false;
    const p = url.pathname;
    return p === "/" || p === "/help" || p === "/digest" || p.startsWith("/digest/") || p === "/nest" || p === "/queue" || p === "/doctor" || p === "/add" || p.startsWith("/settings") ||
      /^\/pile\/\d+$/.test(p) || /^\/item\/\d+\/related$/.test(p);
  };

  // ---- sliding highlights (shelves, views, card tabs) ----------------------------------------------------
  function placeSlider(box, sel, instant, from) {
    if (!box) return;
    const slider = $(":scope > .slider, :scope > .vline, :scope > .tline", box);
    if (!slider) return;
    const on = $(sel, box);
    if (!on) { slider.style.opacity = "0"; box.classList.remove("slid"); return; }
    const r = on.getBoundingClientRect(), b = box.getBoundingClientRect();
    const to = { x: r.left - b.left + box.scrollLeft, width: r.width, opacity: 1 };
    const g = G();
    if (g && from) { g.set(slider, from); g.to(slider, { ...to, duration: .42, ease: "power3.inOut" }); }
    else if (g && !instant && slider.dataset.placed) g.to(slider, { ...to, duration: .42, ease: "power3.inOut" });
    else if (g) g.set(slider, to);
    else { slider.style.transform = `translateX(${to.x}px)`; slider.style.width = to.width + "px"; slider.style.opacity = "1"; }
    slider.dataset.placed = "1";
    box.classList.add("slid");
  }
  const sliderAt = (box) => { const s = box && $(":scope > .slider, :scope > .vline", box); if (!s || !window.gsap) return null; return { x: gsap.getProperty(s, "x"), width: s.getBoundingClientRect().width, opacity: 1 }; };
  const placeAll = (instant) => { placeSlider($("#shelfsw"), "a.on", instant); placeSlider($("#views"), "a.on", instant); };

  // ---- ghosts: copies of tiles that leave, animated where they were ---------------------------------------
  let ghostLayer = null;
  function ghost(el) {
    if (!ghostLayer) { ghostLayer = document.createElement("div"); ghostLayer.className = "ghosts"; document.body.append(ghostLayer); }
    const r = el.getBoundingClientRect();
    const c = el.cloneNode(true);
    c.removeAttribute("id"); c.removeAttribute("data-flip-id"); $$("[data-flip-id]", c).forEach((x) => x.removeAttribute("data-flip-id"));
    c.classList.add("ghost");
    Object.assign(c.style, { position: "fixed", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px", margin: "0", transform: "none" });
    ghostLayer.append(c);
    return c;
  }

  // Tiles move to their new places; leavers fade where they stood; newcomers grow in. Nothing is lifted out of
  // the layout, so sections and sticky headers never collapse or jump.
  function flipTo(host, html, opts = {}) {
    const g = G(), Fl = F();
    if (!g || !Fl) { opts.before?.(); host.innerHTML = html; return; }
    moving();
    const before = $$("[data-flip-id]", host).filter((el) => !el.closest(".stack, .peek"));
    const state = Fl.getState(before);
    const tmp = document.createElement("div"); tmp.innerHTML = html;
    const keep = new Set($$("[data-flip-id]", tmp).map((e) => e.dataset.flipId));
    before.filter((el) => !keep.has(el.dataset.flipId) && inView(el.getBoundingClientRect())).forEach((el) => {
      const c = ghost(el);
      g.to(c, { opacity: 0, scale: .85, duration: .25, ease: "power2.in", onComplete: () => c.remove() });
    });
    opts.before?.();
    host.innerHTML = html;
    const targets = $$("[data-flip-id]", host).filter((el) => !el.closest(".stack, .peek"));
    Fl.from(state, { targets, duration: .5, ease: "power3.inOut", absolute: false, scale: true, prune: true,
      onEnter: (els) => g.fromTo(els.filter((e) => inView(e.getBoundingClientRect())), { opacity: 0, scale: opts.pop ? .6 : .88 },
        { opacity: 1, scale: 1, duration: opts.pop ? .55 : .4, delay: .1, ease: opts.pop ? "back.out(1.7)" : "power2.out", clearProps: "opacity,transform" }) });
  }

  // Everything -> Piles: each tile flies into the stack of its pile. Piles -> Everything: stacks deal their cards out.
  function gather(host, html, before) {
    const g = G();
    if (!g) { before?.(); host.innerHTML = html; return; }
    moving(1400);
    const tiles = $$(".tile[data-id]", host).filter((t) => inView(t.getBoundingClientRect()));
    const ghosts = tiles.map((t) => ({ pile: t.dataset.pile, el: ghost(t) }));
    before?.();
    host.innerHTML = html;
    const piles = $$(".pile[data-pile]", host);
    g.set(piles, { opacity: 0, y: 14, scale: .96 });
    ghosts.forEach(({ pile, el }, i) => {
      const visible = pile && $(`.pile[data-pile="${pile}"] ${root.dataset.piles === "folder" ? ".peek" : ".stack"}`, host);
      const r0 = el.getBoundingClientRect();
      if (!visible) { g.to(el, { opacity: 0, scale: .8, duration: .3, delay: i * .01, onComplete: () => el.remove() }); return; }
      const r1 = visible.getBoundingClientRect();
      const s = Math.min(r1.width * .6 / r0.width, 1);
      g.to(el, { x: r1.left + r1.width / 2 - (r0.left + r0.width / 2), y: r1.top + r1.height / 2 - (r0.top + r0.height / 2), scale: s,
                 rotation: rand(-14, 14), duration: .62, delay: i * .018, ease: "power3.inOut" });
      g.to(el, { opacity: 0, duration: .18, delay: .5 + i * .018, onComplete: () => el.remove() });
    });
    g.to(piles, { opacity: 1, y: 0, scale: 1, duration: .45, delay: .38, stagger: .04, ease: "back.out(1.4)", clearProps: "opacity,transform" });
    $$(".pile .stack > div", host).forEach((d) => g.from(d, { rotation: 0, x: 0, y: -8, duration: .5, delay: .6, ease: "back.out(2)" }));
  }
  function deal(host, html, before) {
    const g = G();
    if (!g) { before?.(); host.innerHTML = html; return; }
    moving(1400);
    const from = {};
    $$(".pile[data-pile]", host).forEach((p) => { from[p.dataset.pile] = ($(root.dataset.piles === "folder" ? ".peek" : ".stack", p) || p).getBoundingClientRect(); });
    $$(".pile[data-pile]", host).filter((p) => inView(p.getBoundingClientRect())).forEach((p) => {
      const c = ghost(p); g.to(c, { opacity: 0, scale: .9, duration: .25, onComplete: () => c.remove() });
    });
    before?.();
    host.innerHTML = html;
    const tiles = $$(".tile[data-id]", host).filter((t) => inView(t.getBoundingClientRect()));
    tiles.forEach((t, i) => {
      const r = t.getBoundingClientRect(), f = from[t.dataset.pile];
      if (!f) { g.from(t, { opacity: 0, scale: .9, duration: .4, delay: .15 + i * .02, clearProps: "opacity,transform" }); return; }
      g.from(t, { x: f.left + f.width / 2 - (r.left + r.width / 2), y: f.top + f.height / 2 - (r.top + r.height / 2),
                  scale: .3, rotation: rand(-12, 12), opacity: 0, duration: .62, delay: .08 + i * .022, ease: "power3.out", clearProps: "opacity,transform" });
    });
    $$(".sec", host).forEach((s) => g.from(s, { opacity: 0, duration: .4, delay: .2 }));
  }

  // ---- in-place navigation -----------------------------------------------------------------------------
  let navigating = false, pendingGo = null;
  const SHELF_ORDER = { inbox: 0, archive: 1, trash: 2 };
  const shelfOf = (u) => { const p = new URL(u, location.href); return p.pathname === "/" && !p.searchParams.get("q") ? (p.searchParams.get("shelf") || "inbox") : null; };

  function syncTop(doc) {
    const fresh = doc.getElementById("shelfsw"), mine = $("#shelfsw");
    if (fresh && mine) {
      $$("a", fresh).forEach((a) => {
        const m = $(`a[data-shelf="${a.dataset.shelf}"]`, mine); if (!m) return;
        m.className = a.className; m.innerHTML = a.innerHTML;
        if (a.hasAttribute("aria-current")) m.setAttribute("aria-current", "page"); else m.removeAttribute("aria-current");
      });
    }
    for (const id of ["t-nest", "t-set"]) {
      const f = doc.getElementById(id), m = document.getElementById(id);
      if (f && m) m.classList.toggle("on", f.classList.contains("on"));
    }
    const dg = document.getElementById("t-digest"), fdg = doc.getElementById("t-digest");  // the button's dot clears as soon as the digest is opened
    if (dg && fdg) dg.replaceWith(document.importNode(fdg, true));
    else if (fdg) $("#t-nest")?.before(document.importNode(fdg, true));
    else dg?.remove();
    const mp = document.getElementById("t-map"), fmp = doc.getElementById("t-map");  // the Map beta: its button comes and goes with the switch
    if (mp && fmp) mp.replaceWith(document.importNode(fmp, true));
    else if (fmp) $("#t-nest")?.before(document.importNode(fmp, true));
    else mp?.remove();
    const q = $("#q"), fq = doc.getElementById("q");
    if (q && fq && document.activeElement !== q) { q.value = fq.value; $("#sclear").hidden = !q.value; }
  }

  // Appearance saved elsewhere on the page (layout, box width, piles, search, tile labels) applies at once, no reload
  function syncRoot(doc) {
    const d = doc.documentElement;
    const box = d.style.getPropertyValue("--box");
    const changed = d.dataset.layout !== root.dataset.layout || box !== root.style.getPropertyValue("--box");
    if (changed && !calm) { root.classList.add("relayout"); setTimeout(() => root.classList.remove("relayout"), 600); }
    for (const k of ["size", "layout", "piles", "search", "labels", "glass", "world"]) if (d.dataset[k]) root.dataset[k] = d.dataset[k];
    if (box) root.style.setProperty("--box", box);
  }

  async function swapAll(view, fresh, how, dir = 1) {
    const g = G();
    if (!g) { view.innerHTML = fresh.innerHTML; return; }
    if (how === "flip") { flipTo(view, fresh.innerHTML); return; }
    const dx = how === "slide" ? 40 * dir : 0, dy = how === "slide" ? 0 : 10;
    await g.to(view, { x: -dx * .5, y: -dy * .3, opacity: 0, duration: .15, ease: "power2.in" });
    view.innerHTML = fresh.innerHTML;
    g.fromTo(view, { x: dx, y: dy, opacity: 0 }, { x: 0, y: 0, opacity: 1, duration: .38, ease: "power3.out", clearProps: "transform,opacity" });
  }

  // The wall keeps its heading still: controls update in place (the underline slides), only the body moves.
  function swapWall(view, fresh, kind) {
    const ctl = $("#wallctl", view), fctl = $("#wallctl", fresh);
    const body = $("#wallbody", view), fbody = $("#wallbody", fresh);
    const was = sliderAt($("#views", view));
    // scrolled past the controls: bring them back under the bar first, so the new body starts in view
    const ctlTop = ctl ? ctl.getBoundingClientRect().top + scrollY - topH() - 8 : 0;
    if (ctl && scrollY > ctlTop) scrollTo({ top: ctlTop, behavior: "instant" });
    // runs after the tiles were measured, so a filter row coming or going moves them smoothly too
    const before = () => {
      if (ctl && fctl) { ctl.innerHTML = fctl.innerHTML; placeSlider($("#views", view), "a.on", false, was); }
      for (const id of ["nokey", "needsb"]) {
        const a = view.querySelector("#" + id), b = fresh.querySelector("#" + id);
        if (a && !b) a.remove();
      }
      body.dataset.view = fbody.dataset.view;
    };
    if (kind === "gather") gather(body, fbody.innerHTML, before);
    else if (kind === "deal") deal(body, fbody.innerHTML, before);
    else flipTo(body, fbody.innerHTML, { before });
  }

  function syncDock(doc) {  // the Ask bar belongs to some pages and not others; the top of the page isn't reloaded, so follow it here
    const f = doc.querySelector(".askdockwrap"), m = $(".askdockwrap");
    if (f && !m) document.body.append(f.cloneNode(true)); else if (!f && m) m.remove();
    else if (f && m && f.className !== m.className) m.replaceWith(f.cloneNode(true));  // Help alone, or Help and Ask
  }
  // the post's open page or card shows the note at once when an answer is added to it (it was only there after reopening the post)
  function showSavedNote(text) {
    const block = $$(".pvnoteblock:not(.pvagentnote)").find((b) => b.closest("#view, body"));
    if (!block || !text) return;
    let p = $(".pvnote", block);
    if (!p) { p = document.createElement("p"); p.className = "pvnote"; block.prepend(p); }
    p.textContent = text;
    const ta = $("textarea.note", block); if (ta) ta.value = text;
    const btn = $("[data-pvshow]", block); if (btn?.lastChild?.nodeType === 3) btn.lastChild.textContent = "Edit note";
    p.classList.remove("fresh"); void p.offsetWidth; p.classList.add("fresh");
    p.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }
  // a thin line under the top edge shows a page is on its way (after a short wait, so quick pages never flash it)
  const navBar = (() => {
    let el, wait, fail;
    const bar = () => { if (!el) { el = document.createElement("div"); el.id = "navbar"; el.setAttribute("aria-hidden", "true"); document.body.append(el); } return el; };
    const api = {
      start() {
        clearTimeout(wait);
        wait = setTimeout(() => {
          const b = bar(); b.classList.remove("done"); void b.offsetWidth; b.classList.add("on");
          document.documentElement.classList.add("navigating");
          clearTimeout(fail); fail = setTimeout(api.done, 15000);  // a download or a stuck request must not leave it running
        }, 120);
      },
      done() {
        clearTimeout(wait); clearTimeout(fail);
        document.documentElement.classList.remove("navigating");
        if (!el || !el.classList.contains("on")) return;
        el.classList.add("done"); setTimeout(() => el.classList.remove("on", "done"), 450);
      },
    };
    return api;
  })();
  addEventListener("pageshow", (ev) => { if (ev.persisted) { navBar.done(); $$("a.navwait").forEach((a) => a.classList.remove("navwait")); } });
  // any link that leaves this page the ordinary way marks itself and starts the line (links the hub handles in place start it in go())
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[href]");
    if (!a || ev.button || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    setTimeout(() => {  // after every other handler has had its say
      const href = a.getAttribute("href") || "";
      if (ev.defaultPrevented || a.target === "_blank" || a.hasAttribute("download") || a.dataset.busy || href.startsWith("#") || /^(javascript|mailto|tel):/i.test(href)) return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin) return;
      navBar.start(); a.classList.add("navwait");
      if (a.classList.contains("btn") && !$(".ld", a)) { a.setAttribute("aria-busy", "true"); a.prepend(loaderMark()); }
    }, 0);
  });

  async function go(url, opts = {}) {
    const view = $("#view");
    if (!view || new URL(url, location.href).pathname === "/ask") { location.href = url; return; }
    if (navigating) { pendingGo = [url, opts]; return; }
    navigating = true;
    navBar.start();
    try {
      const from = location.href;
      const { doc, url: final } = await getDoc(url);
      const fresh = doc.getElementById("view");
      if (!fresh) { location.href = final; return; }
      closeNest();
      if (opts.push !== false) history[opts.replace ? "replaceState" : "pushState"]({ hub: 1 }, "", final.replace("&words=1", ""));
      document.title = doc.title;
      const samePage = page() === (doc.body.dataset.page || "");
      document.body.dataset.page = doc.body.dataset.page || "";
      syncTop(doc); syncDock(doc); askFollow();
      placeAll(false);
      const a = shelfOf(from), b = shelfOf(final);
      if (samePage && $("#setpane", view) && $("#setpane", fresh)) {
        // Settings: the list on the left stays, only the open section changes
        $(".setnav", view).innerHTML = $(".setnav", fresh).innerHTML;
        const help = $("#sethelp", view), fhelp = $("#sethelp", fresh);
        if (help && fhelp) { help.innerHTML = fhelp.innerHTML; G()?.from($$(".hwrap > *", help), { opacity: 0, y: 10, duration: .35, stagger: .04, clearProps: "opacity,transform" }); }
        if (scrollY > 0) scrollTo({ top: 0, behavior: "instant" });
        await swapAll($("#setpane", view), $("#setpane", fresh), "fade");
      } else if (samePage && $("#ntbody", view) && $("#ntbody", fresh)) {
        // Nest tabs: the heading and tabs stay; only what is under the tabs changes
        $(".ntabs", view).innerHTML = $(".ntabs", fresh).innerHTML;
        patchChildren($(".nhead", view), $(".nhead", fresh));
        await swapAll($("#ntbody", view), $("#ntbody", fresh), "fade");
      } else if (samePage && $("#wallbody", view) && $("#wallbody", fresh)) {
        const va = $("#wallbody", view).dataset.view, vb = $("#wallbody", fresh).dataset.view;
        swapWall(view, fresh, va === vb ? "flip" : vb === "piles" ? "gather" : "deal");
      } else {
        let how = opts.how || "", dir = 1;
        if (!how && a && b && a !== b) { how = "slide"; dir = SHELF_ORDER[b] > SHELF_ORDER[a] ? 1 : -1; }
        if (!how) {
          const mine = new Set($$("[data-flip-id]", view).map((e) => e.dataset.flipId));
          how = samePage && $$("[data-flip-id]", fresh).some((e) => mine.has(e.dataset.flipId)) ? "flip" : "fade";
        }
        await swapAll(view, fresh, how, dir);
        if (!opts.typing) scrollTo({ top: 0, behavior: "instant" });
      }
      initView();
    } catch (e) {
      location.href = url;
    } finally {
      navigating = false;
      navBar.done();
      if (pendingGo) { const [u, o] = pendingGo; pendingGo = null; go(u, o); }
    }
  }

  document.addEventListener("click", (ev) => {
    if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button) return;
    const folder = ev.target.closest("a.bpile:not(.bnew)");
    if (folder && G() && $("#view")) {  // a board page loads in full, so the folder's motion plays first and the page rises in after
      ev.preventDefault();
      try { sessionStorage.setItem("mag-enter", "1"); } catch (e) { /* fine */ }
      enterFolder(folder);
      location.href = folder.href;  // straight away: the board's frame is on screen while its page loads, however long that takes
      return;
    }
    const a = ev.target.closest("a[href]");
    if (!a || a.target || a.hasAttribute("download") || !$("#view") || a.classList.contains("mktab")) return;  // tabs switch in place
    const href = a.getAttribute("href");
    if (href.startsWith("#") || /^\/item\/\d+$/.test(href) || !hubPath(a.href)) return;
    if (href === "/nest" && !a.closest("#nestsheet") && openNest()) { ev.preventDefault(); return; }
    ev.preventDefault();
    a.closest("details")?.removeAttribute("open");
    closeSearch();
    go(a.href, { how: a.closest(".pile") || a.classList.contains("back") ? "flip" : "" });
  });
  document.addEventListener("click", (ev) => {  // Cancel in an "Add a …" form folds it back to its button
    const b = ev.target.closest("[data-closedetails]"); if (!b) return;
    const d = b.closest("details"); if (!d) return;
    d.removeAttribute("open"); d.querySelector("form")?.reset();
  });
  addEventListener("popstate", (ev) => {
    if (boardSwapped && location.pathname.startsWith("/board/")) { location.reload(); return; }
    if ($("#view") && hubPath(location.href)) go(location.href, { push: false });
  });

  // ---- forms post in the background, the page updates in place -------------------------------------------
  const toastText = (action) => ({ "/hub/shelf": "Moved", "/hub/note": "Note saved", "/hub/tags": "Tags saved", "/hub/tag/remove": "Tag removed",
    "/hub/empty-trash": "Trash emptied", "/hub/piles/regroup": "Grouped again", "/hub/control": "Saved", "/hub/awake": "Saved",
    "/hub/links/add": "Link added", "/hub/links/again": "Looking for links", "/hub/links/remove": "Link removed", "/hub/refresh-stats": "Counts refreshed",
    "/hub/again": "Queued for a new summary", "/hub/retry": "Trying again", "/hub/not-related": "Taken out of Related",
    "/hub/accept-tags": "Tags added", "/hub/keys/remove": "Key removed", "/hub/keys/up": "Order changed",
    "/hub/keys/down": "Order changed", "/hub/reveal": "Opened in Finder", "/hub/keys/remove-all": "All keys removed",
    "/hub/login/disconnect": "Instagram login deleted", "/hub/settings/budget": "Summary limit saved",
    "/hub/boards/invite": "Invite ready", "/hub/boards/new-code": "New code made", "/hub/boards/new": "Board made", "/hub/boards/vote": "Vote saved",
    "/hub/boards/remove-card": "Taken off the board", "/hub/boards/rename": "Renamed", "/hub/boards/offer": "Not now", "/hub/boards/remove-member": "Removed from the board", "/hub/boards/delete": "", "/hub/boards/restore": "Board restored",
    "/hub/boards/share": "Board shared", "/hub/boards/unshare": "Board is only on this Mac again", "/hub/boards/leave": "You left the board" }[action] ?? "Saved");

  // ---- working animations: a small set, never the same one twice in a row (GSAP; static dots when motion is reduced) ----
  const LOADERS = {
    dots(h) { for (let i = 0; i < 3; i++) h.append(document.createElement("i")); return G()?.to($$("i", h), { y: -5, duration: .35, ease: "power2.out", yoyo: true, repeat: -1, stagger: .12 }); },
    bars(h) { for (let i = 0; i < 4; i++) h.append(document.createElement("i")); return G()?.fromTo($$("i", h), { scaleY: .35 }, { scaleY: 1, duration: .4, ease: "sine.inOut", yoyo: true, repeat: -1, stagger: { each: .1, repeat: -1, yoyo: true } }); },
    orbit(h) { const r = document.createElement("b"); r.append(document.createElement("i"), document.createElement("i")); h.append(r); return G()?.to(r, { rotation: 360, duration: .9, ease: "none", repeat: -1 }); },
    morph(h) { const s = document.createElement("i"); h.append(s); return G()?.timeline({ repeat: -1 }).to(s, { borderRadius: "50%", rotation: 180, duration: .45, ease: "power2.inOut" }).to(s, { borderRadius: "22%", rotation: 360, duration: .45, ease: "power2.inOut" }); },
    ripple(h) { for (let i = 0; i < 2; i++) h.append(document.createElement("i")); return G()?.fromTo($$("i", h), { scale: .2, opacity: .9 }, { scale: 1, opacity: 0, duration: 1, ease: "power1.out", repeat: -1, stagger: .5 }); },
    hop(h) { const s = document.createElement("i"); h.append(s); return G()?.timeline({ repeat: -1 }).to(s, { y: -7, scaleX: .85, scaleY: 1.15, duration: .22, ease: "power2.out" }).to(s, { y: 0, scaleX: 1.2, scaleY: .8, duration: .2, ease: "power2.in" }).to(s, { scaleX: 1, scaleY: 1, duration: .15 }); },
  };
  let lastLoader = "";
  function loaderMark(kind) {
    const names = Object.keys(LOADERS).filter((n) => n !== lastLoader);
    kind = kind || names[Math.floor(Math.random() * names.length)]; lastLoader = kind;
    const h = document.createElement("span"); h.className = "ld ld-" + kind; h.setAttribute("aria-hidden", "true");
    const tween = LOADERS[kind](h);
    h._stop = () => { tween?.kill(); h.remove(); };
    return h;
  }
  // a button shows it is working until the page answers, and a second press does nothing meanwhile
  const busyOn = (f, submitter) => {
    const b = submitter || $("button[type=submit], button:not([type])", f);
    f.dataset.busy = "1";
    if (!b) return () => { delete f.dataset.busy; };
    // the button's icon gives way to a small working animation; its label stays (or says what is happening)
    const ico = $(".ico", b), lbl = $("span:not(.ld)", b), said = lbl && lbl.textContent;
    if (lbl && f.dataset.busyLabel) { b.style.minWidth = b.offsetWidth + "px"; lbl.textContent = f.dataset.busyLabel; }
    const mark = b.classList.contains("sw") || b.closest(".swatches, .bcols") ? null : loaderMark();
    if (mark) { b.prepend(mark); if (ico) ico.hidden = true; }
    b.classList.add("busy"); b.setAttribute("aria-busy", "true");
    return () => {
      delete f.dataset.busy;
      mark?._stop(); if (ico) ico.hidden = false;
      b.classList.remove("busy"); b.removeAttribute("aria-busy");
      if (lbl) { lbl.textContent = said; b.style.minWidth = ""; }
    };
  };
  // a button that is not in a form (save to note, the selection bar) shows the same working mark until its job answers
  const working = async (b, job) => {
    if (!b || b.classList.contains("busy")) return job;
    const mark = loaderMark(); b.prepend(mark); b.classList.add("busy"); b.setAttribute("aria-busy", "true");
    try { return await job; } finally { mark._stop(); b.classList.remove("busy"); b.removeAttribute("aria-busy"); }
  };
  // cards arriving (after a skeleton, a sort, or more scrolling): dealt in one after another with a small tilt
  function dealIn(els) {
    const g = G(); if (!g || !els.length) return;
    g.fromTo(els, { y: 46, scale: .9, rotate: () => g.utils.random(-5, 5), opacity: 0, transformOrigin: "50% 100%" },
      { y: 0, scale: 1, rotate: 0, opacity: 1, duration: .75, ease: "back.out(1.5)", stagger: { each: .05, from: "start" }, clearProps: "transform,opacity" });
  }
  document.addEventListener("submit", (ev) => {  // first: refuse a second press while the first is working
    const f = ev.target;
    if (f instanceof HTMLFormElement && f.dataset.busy) { ev.preventDefault(); ev.stopImmediatePropagation(); }
  }, true);
  document.addEventListener("submit", async (ev) => {
    const f = ev.target;
    if (ev.defaultPrevented || !(f instanceof HTMLFormElement)) return;
    // a form may have fields named "action" or "method": read the attributes, not the properties
    const target = new URL(f.getAttribute("action") || location.href, location.href);
    if ((f.getAttribute("method") || "get").toLowerCase() === "get") {
      if (!$("#view") || !hubPath(target.href)) return;
      ev.preventDefault();
      new FormData(f).forEach((v, k) => { if (v) target.searchParams.set(k, v); });
      closeSearch();
      return go(target.href, { how: "flip" });
    }
    const action = target.pathname;
    const inNest = f.closest("#nestsheet");
    if (action === "/hub/update" || f.closest(".wel") || f.closest(".dgmake") || !$("#view")) {
      if (f.dataset.confirm) { ev.preventDefault(); if (await ask(f.dataset.confirm)) { busyOn(f, ev.submitter); f.submit(); } }
      else { busyOn(f, ev.submitter); navBar.start(); }  // the browser loads the next page; the button and the line say so until then
      return;
    }
    ev.preventDefault();
    if (f.dataset.confirm) {
      const remove = /trash|delete/i.test(f.dataset.confirm);
      if (!(await ask(f.dataset.confirm, f.dataset.confirmOk || (remove ? (/empty|everything/i.test(f.dataset.confirm) ? "Delete for good" : "Move to Trash") : "Continue"), remove))) return;
    }
    const data = new FormData(f);
    if (ev.submitter?.name) data.append(ev.submitter.name, ev.submitter.value);
    if (f.id === "sizes") return setSize(ev.submitter?.value, f, data);
    if (data.get("theme") && ev.submitter?.name === "theme") return setTheme(data.get("theme"), ev.submitter, f, data);
    $$("details.menu[open]").forEach((d) => { if (d.contains(f)) d.removeAttribute("open"); });
    if (action === "/hub/links/again") {  // every Find button on the post turns into "Looking…" where it is: no reload, no jump to the top
      const place = f.closest(".cardm") || document, before = $$(".lk:not(.pvnolink)", place).length;
      $$('form[action="/hub/links/again"]', place).forEach((form) => {
        const mark = document.createElement("span");
        if ($(".pvprimary", form)) { mark.className = "pvprimary wait"; mark.innerHTML = "<span><b>Looking for the link…</b><small>This can take a minute</small></span>"; }
        else { mark.className = "bd looking"; mark.textContent = "Looking…"; }
        form.replaceWith(mark);
        mark.animate([{ opacity: 0, translate: "0 4px" }, { opacity: 1, translate: "0 0" }], { duration: 240, easing: "cubic-bezier(.2,.8,.2,1)" });
      });
      toast(toastText(action));
      fetch(target.href, { method: "POST", body: new URLSearchParams(data), headers: FORM })
        .then((r) => { if (!r.ok) throw new Error(String(r.status)); looking = { before }; })
        .catch(() => { toast("Couldn't start looking. Try again."); location.reload(); });
      return;
    }
    const done = busyOn(f, ev.submitter);
    try {
      if (f.dataset.hold) await new Promise((res) => setTimeout(res, +f.dataset.hold));  // a pause that shows the work, not a delay of the work
      const r = await fetch(target.href, { method: "POST", body: new URLSearchParams(data), headers: FORM });
      const to = new URL(r.url);
      const html = await r.text();
      if (inNest) { done(); await fillNest(); toast(toastText(action)); refresh(true); return; }
      if (/^\/item\/\d+$/.test(to.pathname)) {
        if (to.searchParams.get("tab")) { location.href = r.url; return; }  // a form that names a tab comes back to that tab
        closeAdd(); goPage(to.pathname.split("/")[2]); return;
      }
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById("view");
      if (!fresh) { location.href = r.url; return; }
      if (f.hasAttribute("data-morph") && morphDialog(doc, to)) { done(); return; }
      if (f.hasAttribute("data-dissolve") && G()) {  // Delete: the page and its dialog dissolve into the Boards view, then the folder goes
        const g = G(), view = $("#view");
        await g.to(view, { opacity: 0, duration: .5, ease: "power1.inOut" });
        history.pushState({ hub: 1 }, "", to.pathname + to.search + to.hash);
        document.body.dataset.page = doc.body.dataset.page || "";
        syncTop(doc); syncRoot(doc);
        view.innerHTML = fresh.innerHTML;
        scrollTo({ top: 0, behavior: "instant" });
        goneDelay = .55;
        initView();
        goneDelay = .3;
        await g.to(view, { opacity: 1, duration: .5, ease: "power1.inOut", clearProps: "opacity" });
        done(); return;
      }
      closeAdd();
      const flash = $(".flash", fresh);
      const err = flash && flash.classList.contains("err");
      if (flash) flash.remove();
      if (to.pathname + to.search !== location.pathname + location.search) history.pushState({ hub: 1 }, "", to.pathname + to.search + to.hash);
      document.body.dataset.page = doc.body.dataset.page || "";
      syncTop(doc);
      syncRoot(doc);
      const view = $("#view");
      if ($("#wallbody", view) && $("#wallbody", fresh)) swapWall(view, fresh, "flip");
      else if ($$(".tile[data-id]", fresh).length) patchTiles(view, fresh);
      else patchChildren(view, fresh);
      initView(true);
      const adding = f.hasAttribute("data-addpicks");
      if (adding) picked.clear();
      toast(flash ? flash.textContent.trim() : adding ? "Added to the board" : toastText(action), { bad: err });
      if (to.hash) document.getElementById(to.hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
      done();
    } catch (e) { done(); f.submit(); }
  });

  function patchChildren(view, fresh) {
    const g = G();
    const old = [...view.children], neu = [...fresh.children];
    if (old.length !== neu.length) { view.innerHTML = fresh.innerHTML; return; }
    neu.forEach((n, i) => {
      if (old[i].outerHTML === n.outerHTML) return;
      if (old[i].children.length && old[i].children.length === n.children.length && old[i].className === n.className) {
        if (old[i].getAttribute("style") !== n.getAttribute("style")) old[i].setAttribute("style", n.getAttribute("style") || "");
        patchChildren(old[i], n); return;
      }
      const el = n.cloneNode(true);
      old[i].replaceWith(el);
      if (g) g.from(el, { opacity: .5, duration: .3 });
    });
  }

  // ---- tile sizes and the theme -------------------------------------------------------------------------
  function setSize(size, form, data) {
    if (!size || root.dataset.size === size) return;
    const Fl = F();
    const els = $$("#view .tile, #view .pile, #view .secblock > .sec");
    if (true) {  // instant: moving every tile is what made this button slow (owner, 1 Nov); both themes work this way
      anchored(() => { root.dataset.size = size; });
      $("#wallbody")?.animate([{ opacity: .55 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
    }
    const state = null;
    if (state) moving();
    const names = { s: "Small tiles", m: "Medium tiles", l: "Large tiles" }, after = { s: "m", m: "l", l: "s" }[size];
    form.dataset.cur = size;  // one icon that cycles: it shows the size now and asks for the next
    $$("button", form).forEach((x) => { x.value = after; x.title = `${names[size]} (click for ${names[after].toLowerCase()})`; x.setAttribute("aria-label", `Tile size: ${names[size]}`); });
    if (state) Fl.from(state, { targets: els, duration: .5, ease: "power3.inOut", absolute: false, scale: true, prune: true });
    fetch("/hub/ui", { method: "POST", body: new URLSearchParams(data), headers: FORM });
  }
  function setTheme(theme, btn, form, data) {
    const apply = () => {
      if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
      $$("button", form).forEach((x) => { const on = x.value === theme; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
    };
    const r = btn.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const end = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    if (document.startViewTransition && !calm) {
      const t = document.startViewTransition(apply);
      t.ready.then(() => root.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${end}px at ${x}px ${y}px)`] },
        { duration: 600, easing: "cubic-bezier(.2,.8,.2,1)", pseudoElement: "::view-transition-new(root)" })).catch(() => {});
    } else apply();
    fetch("/hub/ui", { method: "POST", body: new URLSearchParams(data), headers: FORM }).then(() => toast("Theme saved"));
  }

  // ---- add a post ------------------------------------------------------------------------------------------
  const addm = $("#addm"), scrim = $("#scrim");
  function openAdd() {
    if (!addm) return false;
    addm.hidden = false; scrim.hidden = false; $("input[type=url]", addm).focus();
    G()?.fromTo(addm, { y: 14, opacity: 0 }, { y: 0, opacity: 1, duration: .28, ease: "power3.out" });
    return true;
  }
  function closeAdd() { if (!addm || addm.hidden) return; addm.hidden = true; if (!nestOpen()) scrim.hidden = true; }
  $("#addbtn")?.addEventListener("click", (ev) => { if (openAdd()) ev.preventDefault(); });
  addm?.addEventListener("click", (ev) => { if (ev.target.closest("[data-close]")) closeAdd(); });

  // ---- the Nest: a side sheet or a drop-down (a design trial) ---------------------------------------------------
  const nestEl = $("#nestsheet"), nsin = $("#nsin");
  const nestOpen = () => !!nestEl && !nestEl.hidden;
  async function fillNest() {
    if (!nsin) return;
    try {
      const r = await fetch("/nest?frag=1", { cache: "no-store" });
      if (!r.ok) return;
      const html = await r.text();
      if (!nsin.firstElementChild || $(".sk", nsin)) { nsin.innerHTML = html; return; }
      const tmp = document.createElement("div"); tmp.innerHTML = html;
      patchChildren(nsin, tmp);
    } catch (e) { /* keep what is shown */ }
  }
  function openNest() {
    if (!nestEl || page() === "nest") return false;
    if (typeof closeHelp === "function" && $("#helpsheet") && !$("#helpsheet").hidden) closeHelp();
    if (nestOpen()) { closeNest(); return true; }
    stopPreview();
    const btn = $("#t-nest"), r = btn.getBoundingClientRect();
    nestEl.style.top = Math.min(r.bottom + 10, innerHeight - 200) + "px";
    nestEl.style.right = Math.max(12, innerWidth - r.right - 8) + "px";
    nestEl.hidden = false;
    btn.classList.add("open");
    G()?.fromTo(nestEl, { opacity: 0, scale: .92, y: -10, transformOrigin: "top right" }, { opacity: 1, scale: 1, y: 0, duration: .32, ease: "back.out(1.6)" });
    if (!nsin.firstElementChild) nsin.innerHTML = '<div class="nest2"><div class="sk skl"></div><div class="sk skl"></div><div class="sk skl short"></div></div>';
    fillNest().then(() => { const g2 = G(); if (g2) g2.from($$(".nest2 > *", nsin), { opacity: 0, y: 10, duration: .35, stagger: .04, clearProps: "opacity,transform" }); });
    return true;
  }
  function closeNest() {
    if (!nestOpen()) return;
    const g = G();
    const done = () => { nestEl.hidden = true; g?.set(nestEl, { clearProps: "transform,opacity" }); };
    $("#t-nest")?.classList.remove("open");
    if (g) g.to(nestEl, { opacity: 0, scale: .95, y: -6, duration: .18, onComplete: done }); else done();
  }
  $("#ticker")?.addEventListener("click", (ev) => { if (openNest()) ev.preventDefault(); });
  document.addEventListener("pointerdown", (ev) => {
    if (nestOpen() && !ev.target.closest("#nestsheet, #t-nest, #ticker, .dlg-wrap")) closeNest();
  });

  // ---- a post as its own page ----------------------------------------------------------------------------------
  let stale = false;  // the list changed while it was busy: redraw it once it is free

  // sound: a post opens muted; once you unmute, the posts you step to keep it (kept for this tab, cleared when you open a post from a list)
  const soundKey = "mag-sound";
  let cardMuted = true;
  try { cardMuted = sessionStorage.getItem(soundKey) !== "1"; } catch (e) { /* muted */ }
  const rememberSound = (muted) => { cardMuted = muted; try { muted ? sessionStorage.removeItem(soundKey) : sessionStorage.setItem(soundKey, "1"); } catch (e) { /* fine */ } };
  let seekAfterOpen = null;  // a cited moment in an Ask answer: the post opens and jumps there
  function wireCard(host) {
    const main = $(".main", host); if (!main) return;
    const want = new URLSearchParams(location.search).get("tab") || host.dataset.tab || "sum";
    const tabs = $$("[data-tab]", host), bar = $(".tabs", host);
    if (bar && !$(".tline", bar)) { const i = document.createElement("i"); i.className = "tline"; bar.prepend(i); }
    const show = (k, animate) => {
      tabs.forEach((t) => { const on = t.dataset.tab === k; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
      $$("[data-pane]", host).forEach((p) => { p.hidden = p.dataset.pane !== k; });
      host.dataset.tab = k;
      placeSlider(bar, "a.on", !animate);
      const pane = $(`[data-pane="${k}"]`, host);
      if (pane?.dataset.relatedSrc && !pane.hasAttribute("aria-busy")) {
        pane.setAttribute("aria-busy", "true");
        fetch(pane.dataset.relatedSrc, { cache: "no-store" }).then(async (r) => {
          if (!r.ok) throw new Error("Related unavailable");
          const doc = new DOMParser().parseFromString(await r.text(), "text/html");
          const loaded = $('[data-pane="rel"]', doc);
          if (!loaded || loaded.dataset.relatedSrc) throw new Error("Related unavailable");
          pane.innerHTML = loaded.innerHTML;
          delete pane.dataset.relatedSrc;
          const count = $('[data-tab="rel"] small', doc), tab = $('[data-tab="rel"]', host);
          if (count && tab) { $("small", tab)?.remove(); tab.append(count.cloneNode(true)); }
        }).catch(() => { /* the link stays usable; switching back retries */ })
          .finally(() => pane.removeAttribute("aria-busy"));
      }
      if (animate && pane) G()?.fromTo(pane, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: .3, ease: "power2.out" });
    };
    tabs.forEach((t) => t.addEventListener("click", (ev) => { ev.preventDefault(); if (!t.classList.contains("off")) show(t.dataset.tab, true); }));
    // "Add tag" / "Add note": the form stays hidden until its button is pressed
    $$("[data-tabto]", host).forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault();
      $(`[data-tab="${a.dataset.tabto}"]`, host)?.click();
      const sc = $(".pscroll", host), bar2 = $(".tabs", host);  // bring the tab's content to the top of the page
      if (host.classList.contains("pagemode") && bar2) {  // a page: the window scrolls, under the site bar and the breadcrumb bar
        const stick = (parseFloat(getComputedStyle(root).getPropertyValue("--top-h")) || 64) + ($(".crumbbar")?.offsetHeight || 0) + 6;
        scrollTo({ top: scrollY + bar2.getBoundingClientRect().top - stick, behavior: calm ? "auto" : "smooth" });
      } else if (sc && bar2) sc.scrollTo({ top: sc.scrollTop + bar2.getBoundingClientRect().top - sc.getBoundingClientRect().top, behavior: calm ? "auto" : "smooth" });
    }));
    $$("[data-pvmore]", host).forEach((b) => b.addEventListener("click", () => {
      const box = b.parentElement, open = b.dataset.open !== "1";
      $$(".pvx", box).forEach((x) => { x.hidden = !open; });
      b.dataset.open = open ? "1" : ""; b.textContent = open ? "Show fewer" : b.dataset.more;
    }));
    $$("[data-pvshow]", host).forEach((btn) => {
      const box = btn.parentElement, f = $("form", box), note = $(".pvnote", box);
      if (!f) return;
      const toggle = (open) => { f.hidden = !open; btn.hidden = open; if (note) note.hidden = open; if (open) setTimeout(() => $("input, textarea", f)?.focus(), 0); };
      btn.addEventListener("click", () => toggle(true));
      $("[data-pvhide]", f)?.addEventListener("click", () => toggle(false));
    });
    show(tabs.some((t) => t.dataset.tab === want && !t.classList.contains("off")) ? want : "sum", false);
    requestAnimationFrame(() => placeSlider(bar, "a.on", true));
    $$("[data-fold]", host).forEach((c) => {
      const b = $(".capt", c), slot = c.closest(".capslot"), vid = c.closest(".vid");
      c.classList.add("folded"); b.hidden = false;
      const outside = (ev) => {
        if (!c.isConnected) { document.removeEventListener("click", outside, true); return; }
        if (c.contains(ev.target)) return;
        ev.stopPropagation(); ev.preventDefault();  // the first click outside only closes the caption: it must not also play the video
        fold();
      };
      const fold = () => {
        c.classList.remove("pvopen"); c.classList.add("folded"); b.textContent = "Show the whole caption";
        if (slot) slot.style.height = ""; document.removeEventListener("click", outside, true);
      };
      const open = () => {
        if (slot && vid) { slot.style.height = c.offsetHeight + "px"; slot.style.setProperty("--maxh", Math.round(vid.clientHeight * .7) + "px"); }
        c.classList.remove("folded"); c.classList.add("pvopen"); b.textContent = "Fold it again";
        setTimeout(() => document.addEventListener("click", outside, true), 0);
      };
      b.onclick = () => (c.classList.contains("pvopen") ? fold() : open());
    });
    const vid = $("video", host);
    // a carousel's videos share one timeline (the one the summary and the key moments use): vnow() is where we are on it,
    // vseek() jumps to a moment on it, switching slide when needed. A single video is just its own time.
    let vnow = () => (vid ? vid.currentTime : 0), vseek = (s) => { if (vid) { vid.currentTime = s; vid.play().catch(() => {}); } };
    $$("[data-t]", host).forEach((b) => b.addEventListener("click", () => {
      const s = b.dataset.t.split(":").map(Number).reduce((a, x) => a * 60 + x, 0);
      $$(".kp.on", host).forEach((k) => k.classList.remove("on")); if (b.classList.contains("kp")) b.classList.add("on");
      vseek(s);
    }));
    $$("[data-gallery]", host).forEach((w) => {
      const gal = $(".gal", w), prev = $(".gprev", w), next = $(".gnext", w), count = $(".gcount", w), n = $$("img", gal).length;
      const at = () => Math.min(n - 1, Math.max(0, Math.round(gal.scrollLeft / (gal.clientWidth || 1))));
      const show = () => { const i = at(); count.textContent = `${i + 1} / ${n}`; prev.disabled = i === 0; next.disabled = i === n - 1; };
      const go = (d) => { gal.scrollLeft = (at() + d) * gal.clientWidth; };  // eases through CSS scroll-behavior; jumps under reduced motion
      prev.addEventListener("click", () => { go(-1); setTimeout(show, calm ? 0 : 450); }); next.addEventListener("click", () => { go(1); setTimeout(show, calm ? 0 : 450); });
      gal.addEventListener("scroll", show, { passive: true }); gal.addEventListener("scrollend", show);
    });
    // Autoplay and sound follow one setting for every post: remembered in this browser
    const stage = $(".stage", host), sw = $("[data-autoplay]", host);
    const store = { get: (k, d) => { try { return localStorage.getItem("magpiary." + k) ?? d; } catch { return d; } },
                    set: (k, v) => { try { localStorage.setItem("magpiary." + k, v); } catch {} } };
    if (vid && stage) {
      let hushed = false;  // our own muting (sound refused by the browser) must not overwrite what you chose
      vid.muted = cardMuted; vid.volume = 1;  // sound is on or off; the loudness is the computer's own volume
      vid.addEventListener("volumechange", () => { if (hushed) { if (vid.muted) return; hushed = false; } rememberSound(vid.muted); $(".pvunmute", stage)?.remove(); });
      const fit = () => stage.classList.toggle("wide", vid.videoWidth / (vid.videoHeight || 1) > 1.1);
      // our own controls: play, time, seek, sound, fit (the whole video, no crop), full screen
      const bar = $(".pvbar", stage), seek = $(".pvseek", bar), time = $(".pvtime", bar);
      const clock = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
      const paintBar = () => {
        stage.classList.toggle("pvplaying", !vid.paused); stage.classList.toggle("pvsilent", vid.muted);
        time.textContent = `${clock(vid.currentTime)} / ${clock(vid.duration || 0)}`;
        if (!seek.dataset.drag && vid.duration) seek.value = Math.round(vid.currentTime / vid.duration * 1000);
        $('[data-pv="play"]', bar).setAttribute("aria-label", vid.paused ? "Play" : "Pause");
        $('[data-pv="mute"]', bar).setAttribute("aria-label", vid.muted ? "Unmute" : "Mute");
      };
      ["play", "pause", "timeupdate", "volumechange", "loadedmetadata", "durationchange", "ended"].forEach((n) => vid.addEventListener(n, paintBar)); paintBar();
      const toggle = () => (vid.paused ? vid.play().catch(() => {}) : vid.pause());
      $('[data-pv="play"]', bar).addEventListener("click", toggle); vid.addEventListener("click", toggle);
      $("[data-bigplay]", stage)?.addEventListener("click", toggle);
      $('[data-pv="mute"]', bar).addEventListener("click", () => { vid.muted = !vid.muted; });
      seek.addEventListener("input", () => { seek.dataset.drag = "1"; if (vid.duration) vid.currentTime = seek.value / 1000 * vid.duration; });
      seek.addEventListener("change", () => { delete seek.dataset.drag; });
      const fitBtn = $('[data-pv="fit"]', bar);
      const paintFit = () => { const on = store.get("fit", "0") === "1"; stage.classList.toggle("pvfit", on); fitBtn.setAttribute("aria-pressed", String(on)); };
      paintFit(); fitBtn.addEventListener("click", () => { store.set("fit", store.get("fit", "0") === "1" ? "0" : "1"); paintFit(); });
      $('[data-pv="full"]', bar).addEventListener("click", () => {
        const full = document.fullscreenElement || document.webkitFullscreenElement;
        if (full) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
        else (stage.requestFullscreen || stage.webkitRequestFullscreen)?.call(stage);
      });
      vid.addEventListener("loadedmetadata", fit); if (vid.readyState >= 1) fit();
      const start = async () => {
        try { await vid.play(); } catch {
          if (vid.muted) return;
          hushed = true; vid.muted = true;
          try { await vid.play(); } catch { hushed = false; vid.muted = false; return; }
          const b = document.createElement("button"); b.type = "button"; b.className = "pvunmute"; b.textContent = "Tap to unmute";
          b.onclick = () => { hushed = false; vid.muted = false; b.remove(); };
          stage.append(b);
        }
      };
      const paint = () => sw?.setAttribute("aria-checked", store.get("autoplay", "0") === "1" ? "true" : "false");
      paint();
      sw?.addEventListener("click", () => { const on = store.get("autoplay", "0") !== "1"; store.set("autoplay", on ? "1" : "0"); paint(); if (on && vid.paused) start(); });
      if (store.get("autoplay", "0") === "1") start();
    } else if (stage && $("img", stage)) {
      const im = $("img", stage), fit = () => stage.classList.toggle("wide", im.naturalWidth / (im.naturalHeight || 1) > 1.1);
      im.complete ? fit() : im.addEventListener("load", fit);
    }
    // a carousel: arrows, the slide strip and keeping on to the next slide when a video ends
    const strip = $(".pvstrip", host), slides = strip ? $$(".pvsl", strip) : [];
    if (vid && stage && slides.length) {
      const img = $(".pvslide", stage), prev = $(".gprev", stage), next = $(".gnext", stage), count = $(".gcount", stage);
      const videos = slides.filter((b) => b.dataset.start !== undefined);
      let cur = 0;
      const show = (i, play) => {  // returns true when the player had to load another file
        i = Math.max(0, Math.min(slides.length - 1, i)); cur = i;
        const b = slides[i];
        slides.forEach((x, k) => x.classList.toggle("on", k === i));
        count.textContent = `${i + 1} / ${slides.length}`; prev.disabled = i === 0; next.disabled = i === slides.length - 1;
        strip.scrollTo({ left: b.offsetLeft - (strip.clientWidth - b.offsetWidth) / 2, behavior: calm ? "auto" : "smooth" });
        if (b.dataset.k === "i") { vid.pause(); img.src = b.dataset.src; img.hidden = false; stage.classList.add("pvimg"); stage.classList.toggle("wide", false); return false; }
        stage.classList.remove("pvimg"); img.hidden = true;
        const changed = vid.getAttribute("src") !== b.dataset.src;
        if (changed) { vid.src = b.dataset.src; vid.load(); }
        else vid.currentTime = 0;
        if (play) vid.play().catch(() => {});
        return changed;
      };
      slides.forEach((b, i) => b.addEventListener("click", () => show(i, true)));
      prev.addEventListener("click", () => show(cur - 1, true)); next.addEventListener("click", () => show(cur + 1, true));
      vid.addEventListener("ended", () => { if (cur < slides.length - 1) show(cur + 1, true); });
      vnow = () => (+slides[cur].dataset.start || 0) + vid.currentTime;
      vseek = (s) => {
        let k = videos.findLastIndex((b) => +b.dataset.start <= s + .01);
        const b = videos[Math.max(0, k)], local = Math.max(0, s - (+b.dataset.start || 0));
        const apply = () => { vid.currentTime = local; vid.play().catch(() => {}); };
        if (show(slides.indexOf(b), false)) vid.addEventListener("loadedmetadata", apply, { once: true }); else apply();
      };
    }
    if (seekAfterOpen && vid) {
      const at = seekAfterOpen.split(":").map(Number).reduce((a, x) => a * 60 + x, 0); seekAfterOpen = null;
      vseek(at);
    }
    const lines = $$(".tline[data-t]", host);  // the Transcript tab: the line being spoken lights up, and stays in view
    if (vid && lines.length) {
      const starts = lines.map((b) => b.dataset.t.split(":").map(Number).reduce((a, x) => a * 60 + x, 0));
      let lit = -1;
      vid.addEventListener("timeupdate", () => {
        let i = starts.findLastIndex((t) => t <= vnow() + .15);
        if (i === lit) return;
        lines[lit]?.classList.remove("pvon"); lit = i; lines[i]?.classList.add("pvon");
        const pane = $('[data-pane="tr"]', host);
        if (i >= 0 && pane && !pane.hidden) lines[i].scrollIntoView({ block: "nearest", behavior: calm ? "auto" : "smooth" });
      });
    }
    $$("[data-copy]", host).forEach((b) => b.addEventListener("click", () => copy(b.dataset.copy, b.dataset.copyname || "Summary")));
    $$("[data-copylink]", host).forEach((b) => b.addEventListener("click", () => { copy(b.dataset.copylink, "Link", b); b.closest("details")?.removeAttribute("open"); }));
    initMenus(host);
  }

  // A post as a page: the list fades and slides left, the page slides in from the right (and the other way back).
  let leaving = false;  // one way out at a time: a double click or a fast second click must not start two page changes
  function leave(url, dir, replace = false) {
    if (leaving) return;
    leaving = true;
    try { sessionStorage.setItem("mag-slide", dir); } catch (e) { /* fine */ }
    const go = () => (replace ? location.replace(url) : location.assign(url));
    const g = G(), view = $("#view");
    if (!g || !view || calm) { go(); return; }
    root.classList.add("slidefx");
    g.to(view, { opacity: 0, x: dir === "left" ? -22 : 22, duration: .16, ease: "power1.in", overwrite: true, onComplete: go });
    setTimeout(go, 600);  // never stuck if the animation is paused (a hidden tab)
  }
  function goPage(id, dir = "left") {
    const from = $(".postpage")?.dataset.from ?? (location.pathname + location.search);
    rememberSound(true);  // a post opened from a list starts muted
    leave(`/item/${id}` + (from && from !== "/" ? `?from=${encodeURIComponent(from)}` : ""), dir);
  }
  // arriving: the page is held invisible by CSS until here (no flash of the finished page), then fades and slides in
  function arrive() {
    let dir = ""; try { dir = sessionStorage.getItem("mag-slide") || ""; sessionStorage.removeItem("mag-slide"); } catch (e) { /* fine */ }
    const g = G(), view = $("#view");
    leaving = false;
    if (!view || !dir || !g || calm) { root.classList.remove("slide-in", "slidefx"); return; }
    g.set(view, { opacity: 0, x: dir === "left" ? 24 : -24 });
    root.classList.remove("slide-in");
    g.to(view, { opacity: 1, x: 0, duration: .3, ease: "power2.out", overwrite: true, clearProps: "transform,opacity", onComplete: () => root.classList.remove("slidefx") });
    setTimeout(() => { if (view.style.opacity === "0") { g.set(view, { clearProps: "transform,opacity" }); root.classList.remove("slidefx"); } }, 900);
  }


  // ---- Ask about these saves: a side panel with a chat, opened from a post, a pile or a board ---------------------------
  let askPanel = null;
  const askRemember = (v) => { try { v ? sessionStorage.setItem("mag-ask", JSON.stringify(v)) : sessionStorage.removeItem("mag-ask"); } catch (e) { /* fine */ } };
  // the bar is hidden while the sheet is open (a class on the page, not a style rule that looks inside it)
  const askClass = () => document.body.classList.toggle("askopen", !!askPanel && !askPanel.classList.contains("min"));
  function closeAsk() { askPanel?.remove(); askPanel = null; askRemember(null); askClass(); }
  // a small question over the sheet: resolves true for the main button, false for the other or Escape
  function askSure(panel, title, text, yes, no) {
    return new Promise((done) => {
      const d = document.createElement("div"); d.className = "askdlg";
      d.innerHTML = `<div class="askdlgcard" role="alertdialog" aria-label="${title}"><b>${title}</b><p>${text}</p><div class="row"><button type="button" class="btn dark sm" data-y>${yes}</button><button type="button" class="btn sm ghost" data-n>${no}</button></div></div>`;
      panel.append(d);
      const key = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); end(false); } };
      const end = (v) => { document.removeEventListener("keydown", key, true); d.remove(); done(v); };
      document.addEventListener("keydown", key, true);
      $("[data-y]", d).addEventListener("click", () => end(true)); $("[data-n]", d).addEventListener("click", () => end(false)); $("[data-n]", d).focus();
      G()?.from($(".askdlgcard", d), { opacity: 0, y: 8, duration: .2, ease: "power2.out" });
    });
  }
  const askWriting = (p) => !!$(".askm.live, [data-thinking]", p), askAnswered = (p) => !!$(".askm.ai:not(.live):not(.thinking):not(.askerr)", p);
  // X: the chat is kept in the list (if it has an answer) and the sheet goes away; the next opening starts a new chat.
  // Minimise keeps the chat as it is. Both slide down to the bar.
  const fall = (p, done) => { if (!G()) { done(); return; } G().to(p, { opacity: 0, y: 28, scale: .96, transformOrigin: "100% 100%", duration: .22, ease: "power2.in", onComplete: done }); };
  function minAsk(p) {
    if (!p || p.classList.contains("min")) return;
    fall(p, () => { p.classList.add("min"); askClass(); G()?.set(p, { clearProps: "opacity,y,scale,transformOrigin" }); p._say?.(""); });
    askRemember({ scope: p.dataset.scope, min: true });
  }
  function showAsk(p) {
    p.classList.remove("min"); askClass(); askRemember({ scope: p.dataset.scope, min: false }); p._say?.("");
    G()?.fromTo(p, { opacity: 0, y: 28, scale: .96, transformOrigin: "100% 100%" }, { opacity: 1, y: 0, scale: 1, duration: .28, ease: "power3.out", clearProps: "opacity,y,scale,transformOrigin" });
    $("textarea", p)?.focus();
  }
  async function leaveAsk() {
    const p = askPanel; if (!p || $(".askdlg", p)) return;
    if (askWriting(p)) { minAsk(p); return; }  // an answer is being written: keep it going in the bar
    // a post has exactly one conversation: closing the sheet keeps it, and opening Ask on that post brings it back
    if (p.matches("aside") && askAnswered(p) && !p.dataset.scope.startsWith("post:")) await post("/hub/ask/clear", { scope: p.dataset.scope });
    askRemember(null); fall(p, closeAsk);
  }
  // the past chats: a layer over the whole sheet, a list first, then one chat to read
  async function askLayer(panel, url) {
    const r = await fetch(url, { cache: "no-store" }); if (!r.ok) { toast("Couldn't open that chat", { bad: true }); return; }
    const w = document.createElement("div"); w.innerHTML = await r.text();
    const open = $("[data-askhistwrap]", panel);
    if (open) { $("[data-askhistv]", open).replaceWith($("[data-askhistv]", w)); return; }  // list to chat and back: the layer stays
    const wrap = w.firstElementChild; panel.append(wrap);
    G()?.fromTo(wrap, { backgroundColor: "rgba(0,0,0,0)" }, { backgroundColor: "rgba(0,0,0,.26)", duration: .25 });
    G()?.fromTo($("[data-askhistv]", wrap), { xPercent: -100 }, { xPercent: 0, duration: .3, ease: "power3.out" });
  }
  function closeLayer(panel) {
    const wrap = $("[data-askhistwrap]", panel); if (!wrap || wrap.dataset.closing) return;
    wrap.dataset.closing = "1";
    if (!G()) { wrap.remove(); return; }
    G().to(wrap, { backgroundColor: "rgba(0,0,0,0)", duration: .2 });
    G().to($("[data-askhistv]", wrap), { xPercent: -100, duration: .22, ease: "power2.in", onComplete: () => wrap.remove() });
  }
  async function openAsk(scope, opts = {}) {
    closeAsk();
    const r = await fetch("/ask/panel?scope=" + encodeURIComponent(scope), { cache: "no-store" });
    if (!r.ok) { if (!opts.quiet) toast("Couldn't open Ask", { bad: true }); return; }
    const wrap = document.createElement("div"); wrap.innerHTML = await r.text();
    askPanel = wrap.firstElementChild; document.body.append(askPanel);
    if (opts.min) askPanel.classList.add("min");
    askClass();
    askRemember({ scope, min: !!opts.min });
    if (!opts.min) G()?.fromTo(askPanel, { x: 36, opacity: 0 }, { x: 0, opacity: 1, duration: .3, ease: "power3.out", clearProps: "x" });
    wireAsk(askPanel);
    if (!opts.min && !opts.quiet) $("textarea", askPanel)?.focus();  // a sheet restored after a page change must not grab the keyboard
  }
  // The sheet follows the post being viewed: step to another post (arrow keys, Previous/Next) and a sheet that is on a post moves to
  // that post's own conversation, with its title in the header. A sheet on a pile, board or the library stays where it is. An answer
  // still being written for the post you left is stored in that post's chat and is there when you come back.
  let askFollowing = Promise.resolve();
  function askPlace() {
    const m = $("[data-askscope]")?.dataset.askscope || "";
    return m.startsWith("post:") ? m : "";
  }
  function askFollow() {
    const want = askPlace();
    if (!want || !askPanel || !askPanel.dataset.scope.startsWith("post:") || askPanel.dataset.scope === want) return;
    askFollowing = askFollowing.then(async () => {
      const now = askPlace(), old = askPanel;
      if (!old || !now || old.dataset.scope === now || !old.dataset.scope.startsWith("post:")) return;
      const r = await fetch("/ask/panel?scope=" + encodeURIComponent(now), { cache: "no-store" });
      if (!r.ok || askPlace() !== now || askPanel !== old) return;  // moved on again while loading: the latest step wins
      const wrap = document.createElement("div"); wrap.innerHTML = await r.text();
      const next = wrap.firstElementChild;
      if (old.classList.contains("min")) next.classList.add("min");
      const w = old.style.getPropertyValue("--askw"); if (w) next.style.setProperty("--askw", w);
      old.replaceWith(next); askPanel = next;
      askRemember({ scope: now, min: next.classList.contains("min") });
      wireAsk(next);
      G()?.fromTo(next, { opacity: .35 }, { opacity: 1, duration: .22, ease: "power2.out", clearProps: "opacity" });
    }).catch(() => {});
  }
  // a minimised sheet stays across pages: open it again, as a bar, on the next page
  try { const keep = JSON.parse(sessionStorage.getItem("mag-ask") || "null"); if (keep && !document.querySelector(".askpage")) openAsk(keep.scope.startsWith("post:") && askPlace() ? askPlace() : keep.scope, { min: keep.min, quiet: true }); } catch (e) { /* none */ }
  // The open version answers as a job: a glowing "Thinking" card shows each step as it happens (what it searched or read), then the
  // answer is written below it, then the finished message replaces the lot. Returns the finished message's html; `ctl.job` lets the
  // Stop button find the job.
  const STEP_WORDS = { search: "Searching the web", read: "Reading a page", saves: "Searching your saves", save: "Reading a save", work: "Working" };
  const SEARCH_ICON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>';
  const PAGE_ICON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/></svg>';
  async function followJob(id, thread, down, ctl = {}) {
    ctl.job = id;
    const live = document.createElement("div");
    live.className = "askm ai open live";
    live.innerHTML = '<div class="askthink"><div class="askthinkhead"><span class="askpulse"></span><b>Thinking</b><em data-elapsed>0 s</em></div><ol class="askthinksteps"></ol></div><div class="askbody asklivetext"></div>';
    $("[data-thinking]", thread)?.replaceWith(live); down();
    const card = $(".askthink", live), list = $(".askthinksteps", live), textEl = $(".asklivetext", live), head = $("b", card), clock = $("[data-elapsed]", card);
    const t0 = Date.now(); let after = 0, text = "", steps = 0, lost = false;
    const tick = setInterval(() => { clock.textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 500);
    const esc2 = (x) => String(x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const addStep = (ev) => {
      $$("li.cur", list).forEach((x) => x.classList.remove("cur"));
      const arg = ev.kind === "read" ? String(ev.arg || "").replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : String(ev.arg || "");
      const icon = ev.kind === "read" || ev.kind === "save" ? PAGE_ICON : SEARCH_ICON;
      list.insertAdjacentHTML("beforeend", `<li class="cur">${icon}<span class="lab">${STEP_WORDS[ev.kind] || "Working"}</span>${arg ? `<span class="arg">${esc2(arg.slice(0, 80))}</span>` : ""}</li>`);
      steps++;
      const li = list.lastElementChild; G()?.from(li, { opacity: 0, y: 4, duration: .25, ease: "power2.out" });
    };
    try {
      for (let tries = 0; tries < 900; tries++) {  // about five minutes
        await new Promise((ok) => setTimeout(ok, tries ? 400 : 120));
        let d;
        try { const r = await fetch(`/ask/poll?job=${id}&after=${after}`, { cache: "no-store" }); if (!r.ok) { lost = true; break; } d = await r.json(); } catch { continue; }
        after = d.n;
        if (d.live) textEl.innerHTML = d.live;
        for (const ev of d.events) {
          if (ev.step) addStep(ev);
          if (ev.text) {
            if (!text) {  // the answer begins: the thinking card folds into a small line
              $$("li.cur", list).forEach((x) => x.classList.remove("cur"));
              head.textContent = `Thought for ${Math.round((Date.now() - t0) / 1000)} s${steps ? " · " + steps + " step" + (steps === 1 ? "" : "s") : ""}`;
              card.classList.add("done"); clearInterval(tick); clock.remove();
            }
            text += ev.text; if (!d.live) textEl.textContent = text;
          }
        }
        if (!steps && !text) head.textContent = "Thinking";
        down();
        if (d.done) { live.remove(); return d.html; }
      }
    } finally { clearInterval(tick); }
    live.remove();
    // "lost": Magpiary no longer knows this answer (it was restarted while writing it); otherwise it really ran out of time
    return lost ? '<div class="askm ai nofind askerr">Magpiary lost track of that answer (it restarted while writing it). Your question is kept: send it again.</div>'
                : '<div class="askm ai nofind askerr">That took too long. Try again, or pick Short under the box.</div>';
  }
  // Short / Normal / Deep under the box: remembered, applies to the next question
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-askdepth]");
    if (!b) return;
    $$("[data-askdepth]").forEach((x) => { const on = x.dataset.askdepth === b.dataset.askdepth; x.classList.toggle("on", on); x.setAttribute("aria-checked", String(on)); });
    post("/hub/ask/depth", { depth: b.dataset.askdepth });
  });
  function wireAsk(panel) {
    const scope = panel.dataset.scope, thread = $("[data-askthread]", panel), form = $("[data-askform]", panel);
    const suggest = $("[data-asksuggest]", panel), confirm = $("[data-askconfirm]", panel);
    const down = () => { thread && (thread.scrollTop = thread.scrollHeight); };
    down();
    $("[data-askclose]", panel)?.addEventListener("click", () => (panel.matches("aside") ? leaveAsk() : closeAsk()));
    // speaking a question: recorded here, turned into text on this Mac (the sound never leaves it), then put in the box to read and send
    const mic = $("[data-askmic]", panel), vst = $("[data-askvoicest]", panel);
    if (mic) {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) mic.hidden = true;
      let rec = null, stream = null, began = 0, clock = null, stopTimer = null;
      const say = (t) => { if (vst) vst.textContent = t; };
      const end = () => { clearInterval(clock); clearTimeout(stopTimer); stream?.getTracks().forEach((t) => t.stop()); stream = null; };
      mic.addEventListener("click", async () => {
        if (rec) { rec.stop(); return; }
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { toast("The microphone is blocked for this page", { bad: true }); return; }
        const chunks = []; rec = new MediaRecorder(stream, { audioBitsPerSecond: 24000 });
        rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
        rec.onstop = async () => {
          const type = rec.mimeType; rec = null; end(); mic.classList.remove("rec"); mic.classList.add("busy"); say("Turning your voice into text…");
          try {
            const blob = new Blob(chunks, { type });
            const b64 = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.readAsDataURL(blob); });
            const d = await (await post("/hub/ask/voice", { audio: b64 })).json();
            if (d.text) { const ta = form.q; ta.value = (ta.value ? ta.value.trimEnd() + " " : "") + d.text; grow(ta); ta.focus(); say(""); }
            else { say(""); toast(d.error || "Couldn't hear that", { bad: true }); }
          } catch { say(""); toast("Couldn't reach the hub", { bad: true }); }
          mic.classList.remove("busy");
        };
        rec.start(); began = Date.now(); mic.classList.add("rec"); say("Listening 0:00 · tap to stop");
        clock = setInterval(() => { if (!panel.isConnected) { rec?.stop(); return; } const s = Math.round((Date.now() - began) / 1000); say(`Listening ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} · tap to stop`); }, 500);
        stopTimer = setTimeout(() => rec?.stop(), 60000);
      });
    }
    // the empty chat: example questions type themselves out under the heading, one after another
    const typer = $("[data-asktype]", panel);
    if (typer) {
      let examples = []; try { examples = JSON.parse(typer.dataset.examples); } catch (e) { /* none */ }
      if (calm) typer.textContent = examples[0] || "";
      else if (examples.length) {
        let n = 0, i = 0, dir = 1, wait = 0;
        const tick = setInterval(() => {
          if (!typer.isConnected) { clearInterval(tick); return; }
          if (wait > 0) { wait--; return; }
          const text = examples[n]; i += dir;
          typer.textContent = text.slice(0, i);
          if (dir === 1 && i >= text.length) { dir = -1; wait = 22; }
          else if (dir === -1 && i <= 0) { dir = 1; n = (n + 1) % examples.length; wait = 4; }
        }, 55);
      }
    }
    // width: drag the left edge, remembered; double-click to reset
    const grip = $("[data-askgrip]", panel);
    if (grip) {
      const KEY = "magpiary.askw", MIN = 560, MAXW = 720, max = () => Math.max(MIN, Math.min(MAXW, Math.round(innerWidth * .7)));
      const set = (w) => panel.style.setProperty("--askw", Math.min(max(), Math.max(MIN, Math.round(w))) + "px");
      try { const w = parseInt(localStorage.getItem(KEY), 10); if (w) set(w); } catch (e) { /* default */ }
      grip.addEventListener("pointerdown", (ev) => {
        ev.preventDefault(); grip.setPointerCapture(ev.pointerId); panel.classList.add("resizing");
        const move = (e) => set(innerWidth - 12 - e.clientX);
        const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); panel.classList.remove("resizing");
          try { localStorage.setItem(KEY, String(parseInt(getComputedStyle(panel).getPropertyValue("--askw"), 10) || panel.offsetWidth)); } catch (e) { /* fine */ } };
        grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", up);
      });
      grip.addEventListener("dblclick", () => { panel.style.removeProperty("--askw"); try { localStorage.removeItem(KEY); } catch (e) { /* fine */ } });
      grip.addEventListener("keydown", (ev) => { if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); set(panel.offsetWidth + (ev.key === "ArrowLeft" ? 24 : -24)); } });
    }
    let pending = null;
    let over = false;  // the spend guard was shown and the person chose to go on
    const sendBtn = $("[data-asksend]", panel), ctl = {};
    const say = (t) => { const d = $("[data-askdockstate]"); if (d) d.textContent = panel.classList.contains("min") ? (t || "") : ""; };
    panel._say = say;
    const busy = (on) => { say(on ? "Thinking…" : "Answer ready"); if (sendBtn) { sendBtn.classList.toggle("stopping", on); sendBtn.type = on ? "button" : "submit"; sendBtn.setAttribute("aria-label", on ? "Stop" : "Send"); } };
    sendBtn?.addEventListener("click", () => { if (sendBtn.classList.contains("stopping") && ctl.job) post("/hub/ask/stop", { job: ctl.job }); });
    const send = async (q, widen, goOn) => {
      if (!thread) return;
      busy(true);
      if (!widen) thread.insertAdjacentHTML("beforeend", `<div class="askm me">${esc(q)}</div>`);
      thread.insertAdjacentHTML("beforeend", '<div class="askm ai thinking" data-thinking><i></i><i></i><i></i></div>');
      if (suggest) suggest.hidden = true;
      $(".askhello", thread)?.remove(); down();
      let html;
      try {
        const r = await post("/hub/ask/send", { scope, q, widen: widen ? "1" : "", again: widen ? "1" : "", over: goOn ? "1" : "" });
        if ((r.headers.get("content-type") || "").includes("json")) {
          const d = await r.json();
          if (d.warn) {  // past the limit set in Settings: say so, and send only if asked again
            $("[data-thinking]", thread)?.remove(); [...$$(".askm.me", thread)].pop()?.remove();
            pending = q; over = true;
            $("p", confirm).textContent = d.warn + " Send this question anyway?";
            confirm.hidden = false; form.hidden = true; busy(false); return;
          }
          try { sessionStorage.setItem("mag-ask-job", JSON.stringify({ scope, job: d.job })); } catch (e) { /* fine */ }
          html = await followJob(d.job, thread, down, ctl);
        } else html = await r.text();
      }
      catch { html = '<div class="askm ai nofind askerr">Couldn\'t reach the hub. Try again.</div>'; }
      busy(false); ctl.job = null; try { sessionStorage.removeItem("mag-ask-job"); } catch (e) { /* fine */ }
      const t = $("[data-thinking]", thread);
      if (t) { t.insertAdjacentHTML("beforebegin", html); t.remove(); } else thread.insertAdjacentHTML("beforeend", html);
      const added = thread.lastElementChild; if (added) G()?.from(added, { opacity: 0, y: 8, duration: .35, ease: "power2.out" });
      down();
    };
    // a page change in the middle of an answer: pick the answer up again where it is
    (async () => {
      let saved = null; try { saved = JSON.parse(sessionStorage.getItem("mag-ask-job") || "null"); } catch (e) { /* none */ }
      if (!saved || saved.scope !== scope || !thread) return;
      const forget = () => { try { sessionStorage.removeItem("mag-ask-job"); } catch (e) { /* fine */ } };
      const r = await fetch(`/ask/poll?job=${saved.job}&after=0`, { cache: "no-store" }).catch(() => null);
      if (!r || !r.ok || (await r.json()).done) { forget(); return; }
      busy(true); suggest && (suggest.hidden = true); $(".askhello", thread)?.remove();
      thread.insertAdjacentHTML("beforeend", '<div class="askm ai thinking" data-thinking><i></i><i></i><i></i></div>'); down();
      const html = await followJob(saved.job, thread, down, ctl);
      busy(false); ctl.job = null; forget();
      const t = $("[data-thinking]", thread); if (t) t.remove();
      thread.insertAdjacentHTML("beforeend", html); down();
    })();
    const ask = (q, widen) => {
      q = (q || "").trim(); if (!q) return;
      let seen = false; try { seen = sessionStorage.getItem("mag-ask-ok") === "1"; } catch {}
      if (seen || widen || !confirm) return send(q, widen);
      pending = q; confirm.hidden = false; form.hidden = true;
    };
    const grow = (ta) => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, Math.round(innerHeight * .4)) + "px"; };
    $("textarea", form || panel)?.addEventListener("input", (ev) => grow(ev.target));
    form?.addEventListener("submit", (ev) => { ev.preventDefault(); const ta = form.q; const q = ta.value; ta.value = ""; grow(ta); ask(q, false); });
    $("textarea", form || panel)?.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); } });
    $("[data-askgo]", panel)?.addEventListener("click", () => { try { sessionStorage.setItem("mag-ask-ok", "1"); } catch {} confirm.hidden = true; form.hidden = false; const q = pending; pending = null; const goOn = over; over = false; send(q, false, goOn); });
    $("[data-askno]", panel)?.addEventListener("click", () => { confirm.hidden = true; form.hidden = false; if (pending) form.q.value = pending; pending = null; });
    $$("[data-askq]", panel).forEach((b) => b.addEventListener("click", () => ask(b.dataset.askq, false)));
    const refresh = async () => {  // fetch the chat again (after New chat, or after switching who answers)
      if (panel.matches("aside")) return openAsk(scope);
      location.reload();  // the full Ask page
    };
    $("[data-askclear]", panel)?.addEventListener("click", async () => {
      await post("/hub/ask/clear", { scope }); refresh();
    });
    $("[data-askclearpost]", panel)?.addEventListener("click", async () => {
      if (!await askSure(panel, "Clear this conversation?", "The whole conversation about this post is deleted. This can't be undone.", "Clear conversation", "Keep it")) return;
      await post("/hub/ask/live-delete", { scope }); refresh();
    });
    $("[data-askengine]", panel)?.addEventListener("click", async (ev) => { await post("/hub/ask/engine", { engine: ev.currentTarget.dataset.askengine }); refresh(); });
    if (panel.dataset.wired) return;
    panel.dataset.wired = "1";
    panel.addEventListener("click", async (ev) => {
      if (ev.target.closest("[data-askmin]")) { minAsk(panel); return; }
      const hist = ev.target.closest("[data-askhist]"), back = ev.target.closest("[data-askhistback]"), shut = ev.target.closest("[data-askhistclose]"), del = ev.target.closest("[data-askhistdel]");
      if (hist && !hist.closest("[data-askhistv]")) { if ($("[data-askhistwrap]", panel)) closeLayer(panel); else askLayer(panel, "/ask/sessions"); }
      if (ev.target.matches("[data-askhistwrap]")) closeLayer(panel);
      if (back) askLayer(panel, "/ask/sessions");
      if (shut) closeLayer(panel);
      if (del && await askSure(panel, "Delete this chat?", "It is removed for good.", "Delete", "Keep it")) { await post("/hub/ask/session-delete", { id: del.dataset.askhistdel }); askLayer(panel, "/ask/sessions"); }
      const wide = ev.target.closest("[data-askwide]"), save = ev.target.closest("[data-asksave]"), cite = ev.target.closest(".askcite");
      if (wide) { const q = [...$$(".askm.me", thread)].pop()?.textContent; wide.remove(); if (q) send(q, true); }
      if (save) { const r = await working(save, post("/hub/ask/note", { scope, message: save.dataset.asksave })); toast(r.ok ? (scope.startsWith("pile:") ? "Saved to the pile's notes" : "Added to your note") : "Couldn't save", r.ok ? undefined : { bad: true }); if (r.ok) { if (scope.startsWith("post:")) showSavedNote(await r.text()); save.remove(); } }
      if (cite) {
        if (cite.dataset.t) { seekAfterOpen = cite.dataset.t; try { sessionStorage.setItem("mag-seek", cite.dataset.t); } catch (e) { /* fine */ } }
        minAsk(panel);
      }
    });
  }
  // the full page: past chats on the left, the chat on the right
  const askFull = $(".askfull");
  if (askFull) {
    wireAsk(askFull);
    const main = $(".askmain");
    askRemember(null);  // the sheet is not open behind this page, and must not spring open when you go back
    const back = $("[data-askback]"); let from = ""; try { from = sessionStorage.getItem("mag-ask-from") || ""; } catch (e) { /* none */ }
    if (!from && document.referrer) { try { const r = new URL(document.referrer); if (r.origin === location.origin && !r.pathname.startsWith("/ask")) from = r.pathname + r.search; } catch (e) { /* none */ } }
    if (back && from) back.href = from;
    const pageEl = $(".askpage"), ctlKey = "mag-askctl";  // the controls column: closed until opened, then remembered
    const ctlShow = (on) => { pageEl.classList.toggle("ctl", on); try { localStorage.setItem(ctlKey, on ? "1" : "0"); } catch (e) { /* fine */ } };
    let ctlOn = true; try { ctlOn = localStorage.getItem(ctlKey) !== "0"; } catch (e) { /* open */ }  // open until it is closed once
    pageEl.classList.toggle("ctl", ctlOn);
    $$(".actl-form").forEach((f) => {  // Save shows only once something was changed
      const save = $(".actl-save", f), start = [...$$("select", f)].map((x) => x.value);
      f.addEventListener("change", () => { save.hidden = [...$$("select", f)].every((x, i) => x.value === start[i]); });
    });
    $("[data-askctl]")?.addEventListener("click", () => ctlShow(!pageEl.classList.contains("ctl")));
    $("[data-askplace]")?.addEventListener("change", (ev) => { location.href = "/ask?scope=" + encodeURIComponent(ev.target.value); });
    $("[data-asknewchat]")?.addEventListener("click", async (ev) => {
      ev.preventDefault();
      await post("/hub/ask/clear", { scope: askFull.dataset.scope }); location.href = "/ask?scope=library:all";
    });
    main?.addEventListener("click", async (ev) => {
      const del = ev.target.closest("[data-askhistdel]");
      if (del && await askSure(main, "Delete this chat?", "It is removed for good.", "Delete", "Keep it")) { await post("/hub/ask/session-delete", { id: del.dataset.askhistdel }); location.href = "/ask?scope=" + encodeURIComponent(askFull.dataset.scope); }
    });
  }
  // the chat list (in the sheet and on the full page): open a chat to carry on, and the menu (pin, delete)
  const askHere = () => {  // which place this page is: a pile, a board, a tab of the library, or the whole library
    const mark = $("[data-askscope]")?.dataset.askscope;
    if (mark && mark !== "library:auto") return mark;
    return "library:" + ($("#views a.on")?.dataset.view || (mark ? "everything" : "all"));
  };
  const goChat = (scope) => { if (document.querySelector(".askpage")) location.href = "/ask?scope=" + encodeURIComponent(scope); else { if (askPanel) closeLayer(askPanel); openAsk(scope); } };
  let askMenu = null;
  const closeMenu = () => { askMenu?.remove(); askMenu = null; };
  function openMenu(row, x, y) {
    closeMenu();
    const past = row.dataset.kind === "past", pinned = row.dataset.pinned === "1";
    askMenu = document.createElement("div"); askMenu.className = "askmenu"; askMenu.setAttribute("role", "menu");
    askMenu.innerHTML = (past ? `<button type="button" role="menuitem" data-m="pin">${pinned ? "Unpin" : "Pin to the top"}</button>` : "") + '<button type="button" role="menuitem" data-m="del" class="bad">Delete</button>';
    document.body.append(askMenu);
    askMenu.style.left = Math.min(x, innerWidth - 190) + "px"; askMenu.style.top = Math.min(y, innerHeight - 110) + "px";
    askMenu.addEventListener("click", async (ev) => {
      const what = ev.target.closest("[data-m]")?.dataset.m; if (!what) return; closeMenu();
      const host = askPanel || $(".askmain");
      const done = () => { if (document.querySelector(".askpage")) location.reload(); else if (askPanel) askLayer(askPanel, "/ask/sessions?scope=" + encodeURIComponent(askPanel.dataset.scope)); };
      if (what === "pin") { await post("/hub/ask/session-pin", { id: row.dataset.id, on: pinned ? "0" : "1" }); done(); }
      if (what === "del" && await askSure(host, "Delete this chat?", "It is removed for good.", "Delete", "Keep it")) {
        if (row.dataset.kind === "past") await post("/hub/ask/session-delete", { id: row.dataset.id }); else await post("/hub/ask/live-delete", { scope: row.dataset.scope });
        done();
      }
    });
  }
  document.addEventListener("click", async (ev) => {
    if (ev.target.closest("[data-askexpand]")) { try { sessionStorage.setItem("mag-ask-from", location.pathname + location.search); } catch (e) { /* fine */ } }  // so "Back" on the full page knows where you were
    if (askMenu && !ev.target.closest(".askmenu")) closeMenu();
    const dots = ev.target.closest("[data-askmenu]");
    if (dots) { const r = dots.getBoundingClientRect(); openMenu(dots.closest("[data-kind]"), r.left, r.bottom + 4); return; }
    const live = ev.target.closest("[data-asklive]"), past = ev.target.closest("[data-askopen]");
    if (live) goChat(live.dataset.asklive);
    if (past) { const r = await post("/hub/ask/session-resume", { id: past.dataset.askopen }); const d = await r.json().catch(() => ({})); if (d.scope) goChat(d.scope); }
    if (ev.target.closest("[data-askdock]")) { if (askPanel) showAsk(askPanel); else openAsk(askHere()); }
    const pa = ev.target.closest("[data-askpost]");  // the pink Ask button on a post: that post's side sheet
    if (pa) { const sc = "post:" + pa.dataset.askpost; if (askPanel && askPanel.dataset.scope === sc) showAsk(askPanel); else openAsk(sc); return; }
  });
  document.addEventListener("contextmenu", (ev) => { const row = ev.target.closest(".askhrow2"); if (row) { ev.preventDefault(); openMenu(row, ev.clientX, ev.clientY); } });
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-ask]");
    if (b) {  // the library button asks about the tab you are on: piles, everything or boards
      ev.preventDefault();
      openAsk(b.dataset.ask === "library:auto" ? "library:" + ($("#views a.on")?.dataset.view || "everything") : b.dataset.ask);
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || !askPanel || askPanel.classList.contains("min") || $(".askdlg", askPanel)) return;
    ev.stopPropagation(); if ($("[data-askhistwrap]", askPanel)) closeLayer(askPanel); else leaveAsk();
  }, true);


  document.addEventListener("click", (ev) => {
    if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
    const a = ev.target.closest('a[href^="/item/"]');
    if (!a || !$("#view")) return;
    const m = a.getAttribute("href").match(/^\/item\/(\d+)$/);
    if (!m) return;
    ev.preventDefault();
    if (a.closest("#nestsheet")) closeNest();
    goPage(m[1]);
  });
  scrim?.addEventListener("click", () => {
    if (addm && !addm.hidden) closeAdd(); else closeNest();
  });

  // ---- live updates: the strip, the Nest button, tile steps, and only the tiles that changed --------------------------
  const ticker = $("#ticker");
  let sig = null, lanesSig = "", itemSig = null, itemOf = "", askOn = null, looking = null;

  async function refresh(force) {
    const view = $("#view");
    if (!view || navigating) return;
    const active = document.activeElement;
    const busy = view.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName);
    if (!force && (busy || $("details[open]", view) || $(".editing, [data-stkpop]:not([hidden])", view) || document.body.classList.contains("selecting") || $(".ctx, .chooser"))) { stale = true; return; }
    let doc;
    try { ({ doc } = await getDoc(location.pathname.startsWith("/item/") ? "/" : location.href)); } catch (e) { return; }
    const fresh = doc.getElementById("view");
    if (!fresh) return;
    syncTop(doc);
    if ($$(".tile[data-id]", view).length || $$(".tile[data-id]", fresh).length) patchTiles(view, fresh);
    else patchChildren(view, fresh);
    initView(true);
  }

  function patchTiles(view, fresh) {
    const g = G(), Fl = F();
    const cur = new Map($$(".tile[data-id]", view).map((t) => [t.dataset.id, t]));
    const neu = $$(".tile[data-id]", fresh);
    const neuIds = new Set(neu.map((t) => t.dataset.id));
    const complete = !$("a[data-more]", fresh);
    const state = Fl ? Fl.getState([...cur.values(), ...$$(".secblock > .sec", view)]) : null;
    let moved = false;
    neu.forEach((t, i) => {
      const old = cur.get(t.dataset.id);
      if (old) {
        if (old.dataset.v !== t.dataset.v) {
          const el = t.cloneNode(true);
          if (old.classList.contains("sel")) el.classList.add("sel");
          old.replaceWith(el); cur.set(t.dataset.id, el);
          if (g) { g.fromTo(el, { scale: .94 }, { scale: 1, duration: .5, ease: "back.out(2)", clearProps: "transform" }); g.fromTo($(".label", el), { filter: "saturate(0)" }, { filter: "saturate(1)", duration: .7, clearProps: "filter" }); }
        }
        return;
      }
      const el = t.cloneNode(true);
      const prevId = neu[i - 1]?.dataset.id, prevEl = prevId && cur.get(prevId);
      const freshBlock = t.closest("[data-sec]"), sec = freshBlock?.dataset.sec;
      if (prevEl && prevEl.closest("[data-sec]")?.dataset.sec === sec) prevEl.after(el);
      else {
        let grid = sec ? $(`[data-sec="${CSS.escape(sec)}"] .grid`, view) : $(".grid", view);
        if (!grid && freshBlock) {
          const block = freshBlock.cloneNode(false);
          block.innerHTML = ($(".sec", freshBlock)?.outerHTML || "") + '<div class="grid"></div>';  // the Featured block has no heading
          const first = $("[data-sec]", view);
          if (first) first.before(block); else ($("#wallbody", view) || view).append(block);
          grid = $(".grid", block);
        }
        grid?.prepend(el);
      }
      cur.set(t.dataset.id, el); moved = true;
      el.classList.add("new");
    });
    cur.forEach((el, id) => {
      if (neuIds.has(id)) return;
      const pos = $$(".tile[data-id]", view).indexOf(el);
      if (complete || pos < neu.length) {
        moved = true;
        if (g && inView(el.getBoundingClientRect())) { const c = ghost(el); g.to(c, { opacity: 0, scale: .85, duration: .25, onComplete: () => c.remove() }); }
        el.remove();
      }
    });
    $$("[data-sec] .sec span", view).forEach((s) => {
      const b = s.closest("[data-sec]"); const f = $(`[data-sec="${CSS.escape(b.dataset.sec)}"] .sec span`, fresh);
      if (f) s.textContent = f.textContent;
    });
    $$(".secblock", view).forEach((b) => { if (!$(".tile", b)) b.remove(); });
    if (moved && state) moving();
    if (moved && state) Fl.from(state, { targets: [...$$(".tile[data-id]", view), ...$$(".secblock > .sec", view)], duration: .5, ease: "power3.inOut", absolute: false, scale: true, prune: true });
    for (const id of ["nokey", "needsb"]) {
      const a = document.getElementById(id), b = fresh.querySelector("#" + id);
      if (a && !b) a.remove();
      if (!a && b && $(".hero", view)) $(".hero", view).before(b.cloneNode(true));
    }
  }

  // writes only when the text differs: a rewrite under a blurred dialog makes Safari repaint the blur (a flicker)
  function setText(el, text) { if (el && el.textContent !== String(text)) el.textContent = text; }

  function paint(a) {
    if (ticker) {
      const show = a.lanes.length || a.waiting_total;
      ticker.classList.toggle("gone", !show);
      ticker.classList.toggle("paused", !a.lanes.length && a.paused_any);
      setText($("#tk-h", ticker), a.lanes.length ? "Working" : a.paused_any ? "Paused" : "Waiting");
      const box = $("#tks", ticker), key = a.lanes.map((l) => l.item_id + l.step).join();
      if (box.dataset.ids !== key) {
        box.innerHTML = a.lanes.map((l) =>
          `<span class="tk" data-lane="${l.item_id}"><span class="th"${l.thumb ? ` style="background-image:url('${esc(l.thumb)}')"` : ""}></span>` +
          `${esc(l.step_label)} · ${esc(l.label.slice(0, 60))}<span class="pb"><i class="${l.percent == null ? "ind" : ""}"` +
          ` style="width:${l.percent == null ? 35 : Math.round(l.percent)}%"></i></span></span>`).join("");
        box.dataset.ids = key;
        if (a.lanes.length) G()?.from($$(".tk", box), { x: -10, opacity: 0, duration: .3, stagger: .05 });
      } else a.lanes.forEach((l) => { const i = $(`[data-lane="${l.item_id}"] .pb i`, box); if (i && l.percent != null) i.style.width = Math.round(l.percent) + "%"; });
      setText($("#tk-more", ticker), a.waiting_total ? a.waiting_total + " waiting" : "");
    }
    const nest = $("#t-nest");
    if (nest) {
      nest.classList.toggle("busy", a.busy);
      if (nest.dataset.mood !== (a.mood || "quiet")) nest.dataset.mood = a.mood || "quiet";
      if (nest.title !== "The nest: " + (a.line || "")) nest.title = "The nest: " + (a.line || "");
      const nl = $("#nline"); if (nl && nl.textContent !== a.line) { nl.textContent = a.line || ""; G()?.from(nl, { opacity: 0, y: 4, duration: .25 }); }
    }
    $$("[data-badge]").forEach((badge) => {
      const was = badge.textContent; setText(badge, a.needs || ""); if (badge.hidden !== !a.needs) badge.hidden = !a.needs;
      if (a.needs && String(a.needs) !== was) G()?.fromTo(badge, { scale: .4 }, { scale: 1, duration: .45, ease: "back.out(3)" });
    });
    window.__keyName = a.key_name || "";
    // Ask Magpiary was switched on or off (here or in another tab): close its panel and show the page as it now is
    if (a.ask !== undefined) {
      if (askOn === null) askOn = a.ask;
      else if (askOn !== a.ask) { askOn = a.ask; closeAsk(); location.reload(); return; }
    }
    const byId = {};
    a.lanes.forEach((l) => { byId[l.item_id] = l; });
    $$("#view .tile[data-id]").forEach((t) => {
      const l = byId[t.dataset.id], bar = $(".prog", t);
      if (l && bar) { bar.classList.toggle("ind", l.percent == null); if (l.percent != null) $("i", bar).style.width = Math.round(l.percent) + "%"; }
    });
    const ls = a.lanes.map((l) => l.item_id + l.step).join(",");
    const lanesChanged = ls !== lanesSig;
    lanesSig = ls;
    // An open post follows its own changes, not every save elsewhere: a reload or a redraw would stop the video you are watching.
    const own = a.item_signature;
    const mine = own !== undefined && itemSig !== null && own !== itemSig, watching = [...$$("video")].some((v) => !v.paused && !v.ended);
    if (own !== undefined && itemSig === null) itemSig = own;
    // A search that finds nothing new changes nothing the signature counts, so "Looking…" follows the search itself.
    if (a.item_looking) looking ??= { before: null };
    else if (a.item_looking === false && looking && !watching && !$(".cardm input:focus, .cardm textarea:focus")) {
      const { before } = looking; looking = null; itemSig = own;
      if (page() === "card") {  // a post as its own page comes back on the same tab, then says what the search found
        try { if (before !== null) sessionStorage.setItem("mag-links-before", before); } catch (e) { /* fine */ }
        const u = new URL(location.href), tab = $(".tabs [data-tab].on")?.dataset.tab;
        if (tab) { u.searchParams.set("tab", tab); history.replaceState(history.state, "", u); }
        location.reload();
      }
    }
    if (sig !== null && (a.signature !== sig || lanesChanged)) {
      if (nestOpen()) fillNest();
      if (page() === "card") { /* handled below */ }
      else if (["wall", "search", "shelf", "pile", "related", "nest", "board"].includes(page())) refresh();
    }
    if (page() === "card" && mine && !watching && !$("textarea:focus, input:focus")) { itemSig = own; location.reload(); }
    sig = a.signature;
  }

  function linksResult(before) {
    if (before === null) return;
    const found = $$(".lk:not(.pvnolink)").length - before;
    toast(found > 0 ? `Found ${found} new link${found === 1 ? "" : "s"}` : "No new links found");
  }
  try {
    const before = sessionStorage.getItem("mag-links-before");
    if (before !== null) { sessionStorage.removeItem("mag-links-before"); linksResult(+before); }
  } catch (e) { /* fine */ }

  async function tick() {
    if (document.hidden) return;
    try { const open = $(".main[data-item]")?.dataset.item;
      if (String(open) !== itemOf) { itemOf = String(open); itemSig = null; looking = null; }  // another post: start counting its changes afresh
      const qs = [page() === "board" || new URLSearchParams(location.search).get("view") === "boards" ? "boards=1" : "", open ? "item=" + open : ""].filter(Boolean).join("&");
      const r = await fetch("/activity.json" + (qs ? "?" + qs : ""), { cache: "no-store" }); if (r.ok) paint(await r.json()); } catch (e) { /* restarting */ }
  }
  if (ticker || page() === "card") { tick(); setInterval(tick, 2000); document.addEventListener("visibilitychange", tick); }

  // ---- search: spotlight overlay or grows in place -------------------------------------------
  const q = $("#q"), sform = $("#searchform"), panel = $("#spanel"), sclear = $("#sclear");
  const sover = $("#sover"), q2 = $("#q2"), panel2 = $("#spanel2");
  let sTimer = null, mTimer = null, hintTimer = null, sIndex = -1;
  const recent = () => store.get("recent", []);
  function remember(text) { text = text.trim(); if (text.length < 2) return; store.set("recent", [text, ...recent().filter((x) => x !== text)].slice(0, 6)); }
  const bigSearch = () => true;  // on the library the search always grows into the big box
  const activeInput = () => (bigSearch() && sover && !sover.hidden ? q2 : q);
  const activePanel = () => (bigSearch() && sover && !sover.hidden ? panel2 : panel);
  function openSearch() {
    if (bigSearch() && sover) {
      if (!sover.hidden) return;
      sover.hidden = false;
      q2.value = q.value; document.body.classList.add("lock");
      const g = G();
      if (g && !window.MagMorph?.open(sover)) {
        g.fromTo($(".sbox", sover), { y: -24, scale: .96, opacity: 0 }, { y: 0, scale: 1, opacity: 1, duration: .42, ease: "back.out(1.5)" });
        g.fromTo(sover, { opacity: 0 }, { opacity: 1, duration: .25 });
        g.from($(".smag", sover), { rotation: -40, scale: .5, duration: .5, ease: "back.out(2.5)" });
      }
      q2.focus(); q2.setSelectionRange(q2.value.length, q2.value.length);
      hints(); return;
    }
    if (!sform || sform.classList.contains("open")) return;
    sform.classList.add("open"); panel.hidden = false; q.setAttribute("aria-expanded", "true");
    document.body.classList.add("searching");
    G()?.fromTo(panel, { opacity: 0, y: -6 }, { opacity: 1, y: 0, duration: .25, ease: "power2.out" });
    hints();
  }
  function closeSearch() {
    if (sover && !sover.hidden) {
      const g = G(), done = () => { sover.hidden = true; document.body.classList.remove("lock"); g?.set(sover, { clearProps: "opacity" }); };
      if (q2.value.trim()) remember(q2.value);
      if (window.MagMorph?.close(sover, done)) { /* it shrinks back into the box it came from */ }
      else if (g) g.to(sover, { opacity: 0, duration: .18, onComplete: done }); else done();
      if (document.activeElement === q2) q2.blur();
    }
    if (!sform || !sform.classList.contains("open")) return;
    sform.classList.remove("open"); panel.hidden = true; q.setAttribute("aria-expanded", "false"); sIndex = -1;
    document.body.classList.remove("searching");
  }
  const SRC = ["instagram", "threads", "youtube", "reddit", "x", "linkedin"];
  async function hints() {
    const input = activeInput(), box = activePanel();
    if (!input || !box) return;
    const text = input.value.trim();
    let d;
    try { d = await (await fetch("/search.json?q=" + encodeURIComponent(text), { cache: "no-store" })).json(); } catch (e) { return; }
    if (input.value.trim() !== text) return;
    const row = (href, label, sub, icon = "") => `<a class="sopt" role="option" href="${esc(href)}">${icon}<span>${label}</span>${sub ? `<small>${esc(sub)}</small>` : ""}</a>`;
    let html = "";
    if (!text) {
      const r = recent();
      if (r.length) html += '<div class="sh">Recent</div>' + r.map((x) => row("/?q=" + encodeURIComponent(x), esc(x), "", '<i class="si">↺</i>')).join("");
      html += '<div class="sh">Try describing what you remember</div>' + ["a calm recipe from last month", "screen recording on instagram", "the one filmed in a kitchen"].map((x) => row("/?q=" + encodeURIComponent(x), esc(x), "", '<i class="si">✎</i>')).join("");
      if (d.views && d.views.length) html += '<div class="sh">Your views</div>' + d.views.map((v) => row("/?q=" + encodeURIComponent(v.q) + (v.no ? "&no=" + encodeURIComponent(v.no) : ""), esc(v.name), v.n + (v.n === 1 ? " save" : " saves"), '<i class="si">◎</i>')).join("");
      html += '<div class="sh">Sources</div><div class="schips">' + d.sources.map((s) =>
        `<a class="sopt chip" role="option" href="/?source=${esc(s.source)}"><i style="background:var(--s-${SRC.includes(s.source) ? s.source : "other"})"></i>${esc(s.name)} <small>${s.n}</small></a>`).join("") + "</div>";
      if (d.types.length) html += '<div class="sh">Types</div><div class="schips">' + d.types.map((t) =>
        `<a class="sopt chip" role="option" href="/?type=${esc(t.type)}"><i style="background:var(--t-${esc(t.type)})"></i>${esc(t.name)} <small>${t.n}</small></a>`).join("") + "</div>";
    } else {
      const items = [...d.piles.map((p) => row("/pile/" + p.id, esc(p.name), p.n + " in the pile", '<i class="si">▤</i>')),
                     ...d.tags.map((t) => row("/?tag=" + encodeURIComponent(t.tag), "#" + esc(t.tag), t.n + (t.n === 1 ? " save" : " saves"), '<i class="si">#</i>')),
                     ...d.names.map((n) => row("/?q=" + encodeURIComponent(n), esc(n), "mentioned", '<i class="si">✦</i>'))];
      html = (items.length ? '<div class="sh">Jump to</div>' + items.join("") : "") +
        `<div class="sh enter">↵ Enter shows the results for “${esc(text)}”</div>`;
    }
    box.innerHTML = html; sIndex = -1;
    G()?.from($$(".sopt", box).slice(0, 12), { opacity: 0, x: -6, duration: .2, stagger: .015 });
  }
  function onType(input) {
    if (input === q2) q.value = q2.value;
    sclear.hidden = !q.value;
    clearTimeout(hintTimer); hintTimer = setTimeout(hints, 150);
    clearTimeout(sTimer); clearTimeout(mTimer);
    sTimer = setTimeout(() => {
      const text = input.value.trim();
      const url = text ? "/?q=" + encodeURIComponent(text) : "/";
      if (!$("#view")) { location.replace(url); return; }
      // word matches at once; saves close in meaning join after a further pause (M7b)
      go(text ? url + "&words=1" : url, { how: "flip", replace: page() === "search", typing: true });
      if (text) mTimer = setTimeout(() => go(url, { how: "flip", replace: true, typing: true }), 500);
    }, 280);
    const g = G();
    if (g && input === q2) g.fromTo($(".smag", sover), { rotation: -8 }, { rotation: 0, duration: .3, ease: "elastic.out(1, .4)" });
  }
  function onKey(ev, input) {
    const box = activePanel(), opts = $$(".sopt", box);
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault(); if (!opts.length) return;
      sIndex = (sIndex + (ev.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle("on", i === sIndex)); opts[sIndex].scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (sIndex >= 0 && opts[sIndex]) { const h = opts[sIndex].href; closeSearch(); input.blur(); go(h); return; }
      remember(input.value); closeSearch(); input.blur();
      if (input.value.trim() && page() !== "search") go("/?q=" + encodeURIComponent(input.value.trim()), { how: "flip" });
    } else if (ev.key === "Escape") {
      ev.stopPropagation(); ev.preventDefault();
      if (bigSearch() && sover && !sover.hidden && input.value) { input.value = ""; onType(input); return; }
      if (!bigSearch() && input.value) { input.value = ""; sclear.hidden = true; go("/", { how: "flip" }); }
      closeSearch(); input.blur();
    }
  }
  if (q && sform) {
    q.addEventListener("focus", () => { if (bigSearch()) { q.blur(); openSearch(); } else openSearch(); });
    sform.addEventListener("click", (ev) => { if (!ev.target.closest("#spanel, #sclear")) openSearch(); });
    q.addEventListener("input", () => { openSearch(); onType(q); });
    q.addEventListener("keydown", (ev) => onKey(ev, q));
    sclear?.addEventListener("click", (ev) => { ev.stopPropagation(); q.value = ""; sclear.hidden = true; go("/", { how: "flip" }); });
    panel.addEventListener("click", (ev) => { if (ev.target.closest("a")) { if (q.value) remember(q.value); closeSearch(); q.blur(); } });
    document.addEventListener("pointerdown", (ev) => { if (!ev.target.closest("#searchform") && sform.classList.contains("open")) { if (q.value) remember(q.value); closeSearch(); } });
  }
  if (sover) {
    q2.addEventListener("input", () => onType(q2));
    q2.addEventListener("keydown", (ev) => onKey(ev, q2));
    sover.addEventListener("click", (ev) => { if (ev.target === sover || ev.target.closest("[data-sclose]")) closeSearch(); if (ev.target.closest("#spanel2 a")) closeSearch(); });
  }

  // ---- hover previews: the whole tile plays from the first key moment; photos take turns ----------------------------------
  let pv = null, pvTimer = null;
  function stopPreview() {
    clearTimeout(pvTimer);
    if (!pv) return;
    const { tile, layer, el, timer } = pv;
    clearInterval(timer);
    tile.classList.remove("previewing");
    const done = () => { if (el.tagName === "VIDEO") { el.pause(); el.removeAttribute("src"); el.load(); } layer.remove(); };
    if (G()) G().to(layer, { opacity: 0, duration: .15, onComplete: done }); else done();
    pv = null;
  }
  function startPreview(tile) {
    stopPreview();
    if (!tile.isConnected) return;
    const layer = document.createElement("div"); layer.className = "pvl"; layer.setAttribute("aria-hidden", "true");
    const title = $(".label .t, h3", tile)?.textContent || "";
    const host = tile.classList.contains("mx") ? $(".sq", tile) : tile;  // a board card plays in its picture
    layer.innerHTML = `<div class="pvcap"><b>${esc(title)}</b></div><div class="pvbar"><i></i></div>`;
    if (tile.dataset.video) {
      const v = document.createElement("video");
      v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("muted", "");
      const start = Number(tile.dataset.start) || 0;
      v.addEventListener("loadedmetadata", () => { if (start && start < v.duration - 1) v.currentTime = start; v.play().catch(() => {}); }, { once: true });
      let shown = false;
      v.addEventListener("timeupdate", () => {
        if (!shown && v.currentTime > (start && start < v.duration - 1 ? start : 0) + 0.05) {
          shown = true; tile.classList.add("previewing");
          if (G()) G().to(layer, { opacity: 1, duration: .3, ease: "power1.out" }); else layer.style.opacity = "1";
        }
        if (v.duration) $(".pvbar i", layer).style.width = (v.currentTime / v.duration * 100) + "%";
      });
      v.src = tile.dataset.video;
      layer.prepend(v);
      host.append(layer);
      pv = { tile, layer, el: v };
    } else if (tile.dataset.photos) {
      let list = []; try { list = JSON.parse(tile.dataset.photos); } catch (e) { return; }
      if (list.length < 2) return;
      const img = document.createElement("img"); img.alt = ""; let n = 0;
      layer.prepend(img); host.append(layer); tile.classList.add("previewing");
      const show = () => { n = (n + 1) % list.length; const pre = new Image(); pre.onload = () => { img.src = list[n]; G()?.fromTo(img, { opacity: .3 }, { opacity: 1, duration: .3 }); }; pre.src = list[n]; };
      img.src = list[0];
      if (G()) G().to(layer, { opacity: 1, duration: .25 }); else layer.style.opacity = "1";
      pv = { tile, layer, el: img, timer: setInterval(show, 1000) };
    }
  }
  if (fine && !calm) {
    document.addEventListener("pointerover", (ev) => {
      const tile = ev.target.closest("#view .tile[data-video], #view .tile[data-photos], #view .mx[data-video]:not(.dim), #view .mx[data-photos]:not(.dim)");
      if (!tile || pv?.tile === tile || document.body.classList.contains("selecting") || navigating) return;
      clearTimeout(pvTimer); pvTimer = setTimeout(() => startPreview(tile), 300);
    });
    document.addEventListener("pointerout", (ev) => {
      const tile = ev.target.closest(".tile, .mx"); if (!tile) return;
      if (ev.relatedTarget && tile.contains(ev.relatedTarget)) return;
      clearTimeout(pvTimer); if (pv?.tile === tile) stopPreview();
    });
  }

  // ---- selection: the Select button turns into a dark toolbar under the nav -----------------------------------------------------
  const selected = new Set();
  let lastPicked = null, selbar = null;
  function selectMode(on) {
    document.body.classList.toggle("selecting", on);
    $$("#selbtn").forEach((b) => { b.setAttribute("aria-pressed", String(on)); b.classList.toggle("on", on); });
    if (!on) { selected.clear(); $$(".tile.sel").forEach((t) => t.classList.remove("sel")); if (stale) { stale = false; refresh(true); } }
    stopPreview(); drawBar(true);
  }
  function pick(tile, range) {
    const id = tile.dataset.id;
    if (range && lastPicked) {
      const all = $$("#view .tile[data-id]"), a = all.indexOf(lastPicked), b = all.indexOf(tile);
      if (a >= 0 && b >= 0) all.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((t) => { selected.add(t.dataset.id); t.classList.add("sel"); });
    } else if (selected.has(id)) { selected.delete(id); tile.classList.remove("sel"); }
    else { selected.add(id); tile.classList.add("sel"); G()?.fromTo(tile, { scale: .96 }, { scale: 1, duration: .3, ease: "back.out(2)", clearProps: "transform" }); }
    lastPicked = tile;
    if (!document.body.classList.contains("selecting")) selectMode(true); else drawBar();
  }
  const clipFrom = (r, br) => `inset(${Math.max(0, r.top - br.top)}px ${Math.max(0, br.right - r.right)}px ${Math.max(0, br.bottom - r.bottom)}px ${Math.max(0, r.left - br.left)}px round 999px)`;
  function drawBar(morph) {
    const on = document.body.classList.contains("selecting");
    const g = G();
    if (!on) {
      if (selbar) {
        const b = selbar; selbar = null;
        const btn = $("#selbtn");
        if (g && btn && btn.offsetParent !== null) g.to(b, { clipPath: clipFrom(btn.getBoundingClientRect(), b.getBoundingClientRect()), opacity: 0, duration: .3, ease: "power2.in", onComplete: () => b.remove() });
        else b.remove();
      }
      return;
    }
    const shelves = new Set([...selected].map((id) => $(`#view .tile[data-id="${id}"]`)?.dataset.shelf));
    const n = selected.size;
    const allIds = (($("#wallids")?.dataset.ids || "").split(",").filter(Boolean));
    const total = allIds.length || $$("#view .tile[data-id]").length;
    const html = `<span class="bn"><b>${n}</b> ${n === 1 ? "post" : "posts"} selected</span><span class="bsp"></span>` +
      (total > n ? `<button type="button" data-bulk="all">Select all ${total}</button>` : "") +
      (!n || shelves.has("inbox") ? '<button type="button" data-bulk="archive">Archive</button>' : "") +
      (shelves.has("archive") || shelves.has("trash") ? '<button type="button" data-bulk="inbox">Restore</button>' : "") +
      (!n || [...shelves].some((s) => s !== "trash") ? '<button type="button" class="bad" data-bulk="trash">Move to Trash</button>' : "") +
      '<button type="button" data-bulk="pile">Move to pile ▾</button><button type="button" data-bulk="tag">Tag ▾</button>' +
      '<button type="button" data-bulk="board">Add to board ▾</button>' +
      '<button type="button" data-bulk="again">✦ Summarise again</button><button type="button" data-bulk="stats">↻ Refresh stats</button><button type="button" class="bdone" data-bulk="done">Done</button>';
    if (!selbar) {
      selbar = document.createElement("div"); selbar.className = "selbar"; selbar.setAttribute("role", "toolbar"); selbar.setAttribute("aria-label", "Selected posts");
      document.body.append(selbar); selbar.innerHTML = html;
      const btn = $("#selbtn");
      if (g && btn && morph && btn.offsetParent !== null) {
        g.fromTo(selbar, { clipPath: clipFrom(btn.getBoundingClientRect(), selbar.getBoundingClientRect()) },
                 { clipPath: "inset(0px 0px 0px 0px round 999px)", duration: .45, ease: "power3.inOut", clearProps: "clipPath" });
        g.from($$("button, .bn", selbar), { opacity: 0, y: 4, duration: .25, delay: .2, stagger: .03, clearProps: "opacity,transform" });
      }
    } else selbar.innerHTML = html;
    $$("button", selbar).forEach((b) => { if (b.dataset.bulk !== "done" && b.dataset.bulk !== "all") b.disabled = !n; });
  }
  async function bulk(action, ids, anchor) {
    if (action === "all") {  // everything the current view matches, loaded on screen or not
      const all = ($("#wallids")?.dataset.ids || "").split(",").filter(Boolean);
      (all.length ? all : $$("#view .tile[data-id]").map((t) => t.dataset.id)).forEach((id) => selected.add(id));
      $$("#view .tile[data-id]").forEach((t) => t.classList.toggle("sel", selected.has(t.dataset.id)));
      drawBar(); return;
    }
    ids = [...ids]; if (!ids.length) return;
    const n = ids.length, s = n === 1 ? "" : "s";
    const fields = { ids: ids.join(","), action, next: location.pathname + location.search };
    if (action === "trash" && !(await ask(`Move ${n} post${s} to the Trash? ${n === 1 ? "It is" : "They are"} deleted for good after 30 days.`, "Move to Trash", true))) return;
    if (action === "again") {
      const key = window.__keyName;
      if (!key) { toast("Add an AI key in Settings first (or switch from Private to Smart)", { bad: true }); return; }
      if (!(await confirmBulk("again", ids))) return;
    }
    if (action === "stats" && !(await confirmBulk("refresh", ids))) return;
    if (action === "pile" || action === "tag" || action === "board") return choose(action, ids, anchor);
    await post("/hub/bulk", fields);
    const words = { archive: `Archived ${n}`, trash: `Moved ${n} to the Trash`, inbox: `Restored ${n}`, again: `Queued ${n} for a new summary`, stats: `Queued ${n} for a careful stats refresh (see the Nest)` }[action];
    if (action === "archive" || action === "trash") toast(words, { undo: () => post("/hub/bulk", { ...fields, action: "inbox" }).then(() => refresh(true)) });
    else toast(words);
    selectMode(false); refresh(true);
  }
  async function choose(kind, ids, anchor) {
    $(".chooser")?.remove();
    const box = document.createElement("div"); box.className = "chooser pop";
    if (kind === "pile") {
      let piles = [];
      try { piles = (await (await fetch("/search.json?q=&piles=1", { cache: "no-store" })).json()).all_piles || []; } catch (e) { /* none */ }
      box.innerHTML = '<div class="sh">Move to pile</div><div class="plist">' + piles.map((p) =>
        `<button type="button" data-p="${p.id}" data-name="${esc(p.name)}"><i style="background:${esc(p.colour)}"></i>${esc(p.name)}<small>${p.n}</small></button>`).join("") +
        '</div><form class="newp"><input type="text" placeholder="Or a new pile…" maxlength="60" aria-label="New pile name"><button class="btn sm" type="submit">Create</button></form>';
    } else if (kind === "board") {
      let list = [];
      try { list = await (await fetch("/boards.json", { cache: "no-store" })).json(); } catch (e) { /* none */ }
      box.innerHTML = '<div class="sh">Add to board</div>' + (list.length ? '<div class="plist">' + list.map((b) =>
        `<button type="button" data-b="${esc(b.id)}" data-name="${esc(b.name)}"><i style="background:var(--t-place)"></i>${esc(b.name)}<small>${b.n}</small></button>`).join("") + "</div>"
        : '<p class="small muted" style="margin:4px 10px 10px">No boards yet.</p>') + '<div class="row"><a class="btn sm" href="/?view=boards&make=new">New board…</a></div>';
    } else {
      box.innerHTML = '<div class="sh">Tag</div><form class="newp"><input type="text" placeholder="tag name" maxlength="40" aria-label="Tag"></form>' +
        '<div class="row"><button type="button" class="btn sm dark" data-t="tag">Add tag</button><button type="button" class="btn sm" data-t="untag">Remove tag</button></div>';
    }
    document.body.append(box);
    const r = (anchor && anchor.isConnected ? anchor : selbar || document.body).getBoundingClientRect();
    box.style.left = Math.max(8, Math.min(r.left, innerWidth - box.offsetWidth - 8)) + "px";
    box.style.top = (r.bottom + box.offsetHeight + 16 < innerHeight ? r.bottom + 8 : Math.max(8, r.top - box.offsetHeight - 8)) + "px";
    G()?.from(box, { y: -6, opacity: 0, duration: .2 });
    const close = () => box.remove();
    const send = async (fields, msg) => { close(); await post("/hub/bulk", { ids: ids.join(","), next: location.pathname, ...fields }); toast(msg); selectMode(false);
      const mine = anchor?.matches?.("[data-addboard]") ? anchor.dataset.addboard : "";
      await refresh(true);  // the page redraws from the server first, so it cannot cut the tick short
      if (mine) confirmIcon($(`[data-addboard="${mine}"]`) || anchor);
    };
    box.addEventListener("click", (ev) => {
      const p = ev.target.closest("[data-p]");
      if (p) return send({ action: "pile", pile: p.dataset.p }, `Moved ${ids.length} to ${p.dataset.name}`);
      const b = ev.target.closest("[data-b]");
      if (b) return send({ action: "board", board: b.dataset.b }, `Added ${ids.length} to ${b.dataset.name}`);
      const t = ev.target.closest("[data-t]"); const v = $("input", box).value.trim();
      if (t && v) send({ action: t.dataset.t, tag: v }, `${t.dataset.t === "tag" ? "Tagged" : "Untagged"} #${v.replace(/^#/, "")}`);
    });
    $("form", box)?.addEventListener("submit", (ev) => {
      ev.preventDefault(); const v = $("input", box).value.trim(); if (!v) return;
      if (kind === "pile") send({ action: "pile", pile: "new", name: v }, `New pile “${v}”`); else send({ action: "tag", tag: v }, `Tagged #${v.replace(/^#/, "")}`);
    });
    $("input", box)?.focus();
    setTimeout(() => document.addEventListener("pointerdown", function off(ev) { if (!box.contains(ev.target)) { close(); document.removeEventListener("pointerdown", off); } }), 0);
  }
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("#selbtn")) { selectMode(!document.body.classList.contains("selecting")); return; }
    const bb = ev.target.closest("[data-bulk]");
    if (bb) { if (bb.dataset.bulk === "done") selectMode(false); else working(bb, Promise.resolve(bulk(bb.dataset.bulk, selected, bb))); return; }
    const tile = ev.target.closest("#view .tile[data-id]");
    if (!tile && document.body.classList.contains("selecting") && !ev.target.closest(".selbar, dialog, .pop, .ctx, .chooser, .toast, a, button, input, select, textarea, label")) { selectMode(false); return; }  // a click on the empty page leaves Select
    if (!tile || ev.target.closest("form, .acts")) return;
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || document.body.classList.contains("selecting")) {
      ev.preventDefault(); ev.stopImmediatePropagation(); pick(tile, ev.shiftKey);
    }
  }, true);

  // ---- the right-click menu (long-press on touch) -------------------------------------------------------------------------
  function menuFor(tile, x, y) {
    $(".ctx")?.remove();
    stopPreview();
    const id = tile.dataset.id, shelf = tile.dataset.shelf;
    const m = document.createElement("div"); m.className = "ctx pop"; m.setAttribute("role", "menu");
    m.innerHTML = `<button data-c="open" role="menuitem">Open</button><a href="${esc(tile.dataset.url)}" target="_blank" rel="noopener noreferrer" role="menuitem">Open original ↗</a><hr>` +
      (shelf === "inbox" ? '<button data-c="archive" role="menuitem">Archive</button>' : '<button data-c="inbox" role="menuitem">Back to library</button>') +
      (shelf !== "trash" ? '<button data-c="trash" class="bad" role="menuitem">Remove…</button>' : "") +
      '<hr><button data-c="pile" role="menuitem">Move to pile…</button><button data-c="tag" role="menuitem">Tag…</button>' +
      '<button data-c="board" role="menuitem">Add to board…</button>' +
      '<button data-c="again" role="menuitem">Summarise again</button><hr><button data-c="copy" role="menuitem">Copy link</button>' +
      '<button data-c="select" role="menuitem">Select</button>';
    document.body.append(m);
    m.style.left = Math.max(8, Math.min(x, innerWidth - m.offsetWidth - 8)) + "px";
    m.style.top = Math.max(8, Math.min(y, innerHeight - m.offsetHeight - 8)) + "px";
    G()?.fromTo(m, { opacity: 0, scale: .96, transformOrigin: "top left" }, { opacity: 1, scale: 1, duration: .16 });
    $("button", m).focus();
    m.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) { m.remove(); return; }
      const c = ev.target.closest("[data-c]")?.dataset.c; if (!c) return;
      m.remove();
      if (c === "open") goPage(id);
      else if (c === "copy") copy(tile.dataset.url, "Link");
      else if (c === "select") pick(tile);
      else bulk(c, [id], tile);
    });
    setTimeout(() => document.addEventListener("pointerdown", function off(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("pointerdown", off); } }), 0);
  }
  document.addEventListener("click", (ev) => {  // a post's … menu: Add to board
    const b = ev.target.closest("[data-addboard]"); if (!b) return;
    b.closest("details")?.removeAttribute("open");
    choose("board", [b.dataset.addboard], b);
  });
  // the board's Add posts window: every letter narrows the list; ticks are kept while the list changes
  const picked = new Set();
  function showPicks(f) {
    f.elements.ids.value = [...picked].join(",");
    const n = picked.size, go = $("[data-addgo]", f), count = $("[data-addcount]", f);
    if (go) { go.disabled = !n; go.textContent = n ? `Add ${n} to the board` : "Add to the board"; }
    if (count) count.textContent = n ? `${n} ticked` : "Tick the posts to add";
  }
  document.addEventListener("change", (ev) => {
    const f = ev.target.closest("[data-addpicks]"); if (!f || ev.target.name !== "pick") return;
    if (ev.target.checked) picked.add(ev.target.value); else picked.delete(ev.target.value);
    showPicks(f);
  });
  let addTimer = 0, addAbort = null;
  document.addEventListener("input", (ev) => {
    const box = ev.target.closest("[data-addsearch]"); if (!box) return;
    clearTimeout(addTimer);
    addTimer = setTimeout(async () => {
      addAbort?.abort(); addAbort = new AbortController();
      const list = $("[data-addlist]"); if (!list) return;
      list.classList.add("loading");
      try {
        const r = await fetch(box.dataset.addsearch + "?q=" + encodeURIComponent(box.value), { signal: addAbort.signal, cache: "no-store" });
        if (!r.ok) return;
        list.innerHTML = await r.text();
        $$("input[name=pick]:not(:disabled)", list).forEach((x) => { x.checked = picked.has(x.value); });
        list.scrollTop = 0;
      } catch (e) { /* a newer letter replaced it */ } finally { list.classList.remove("loading"); }
    }, 90);
  });
  // a board's heading: the sticker opens a small panel (any emoji from the Mac's emoji window, or a colour);
  // the pencil makes the name editable where it is, Enter or Save keeps it, Esc or Cancel puts it back
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-stickerpick]");
    const pop = $("#view [data-stkpop]");
    if (b && pop) {
      pop.hidden = !pop.hidden;
      if (!pop.hidden) { $("[data-stkin]", pop).value = ""; openEmoji(pop); G()?.from(pop, { y: -6, opacity: 0, duration: .2, ease: "power2.out" }); }
      return;
    }
    const em = ev.target.closest("[data-em]");
    if (em && pop) { pickEmoji(pop, em.dataset.em); return; }
    const etab = ev.target.closest("[data-emtab]");
    if (etab && pop) { showEmoji(pop, "", +etab.dataset.emtab); return; }
    if (pop && !pop.hidden && !ev.target.closest("[data-stkpop]")) pop.hidden = true;
    const pen = ev.target.closest("[data-renamebtn]");
    if (pen) { nameEdit(pen.closest("[data-nameform]"), true); return; }
    const cancel = ev.target.closest("[data-namecancel]");
    if (cancel) nameEdit(cancel.closest("[data-nameform]"), false);
  });
  // the whole emoji set, in the sticker panel: groups, and a search over names and keywords
  const ASSET_V = document.currentScript ? new URL(document.currentScript.src).search : "";
  let emojiSet = null;
  const EMOJI_TABS = ["😀", "👋", "🐶", "🍔", "✈️", "⚽", "💡", "❤️", "🏁"];
  async function openEmoji(pop) {
    if (!emojiSet) { try { emojiSet = await (await fetch("/static/emoji.json" + ASSET_V)).json(); } catch (e) { emojiSet = { groups: [], e: [] }; } }
    const box = $("[data-emtabs]", pop);
    if (!box.children.length) box.innerHTML = emojiSet.groups.map((g, i) => `<button type="button" role="tab" data-emtab="${i}" title="${esc(g)}" aria-label="${esc(g)}">${EMOJI_TABS[i] || "•"}</button>`).join("");
    const s = $("[data-empsearch]", pop); s.value = "";
    showEmoji(pop, "", 0);
    s.focus({ preventScroll: true });
  }
  function showEmoji(pop, query, group) {
    if (!emojiSet) return;
    const q = query.trim().toLowerCase(), grid = $("[data-emgrid]", pop);
    const words = q.split(/\s+/).filter(Boolean);
    const list = q ? emojiSet.e.filter((x) => words.every((w) => x[1].includes(w) || x[2].includes(w))).slice(0, 160)
                   : emojiSet.e.filter((x) => x[3] === group);
    $$("[data-emtab]", pop).forEach((t) => t.classList.toggle("on", !q && +t.dataset.emtab === group));
    grid.innerHTML = list.length ? list.map((x) => `<button type="button" data-em="${x[0]}" title="${esc(x[1])}" role="option" aria-label="${esc(x[1])}">${x[0]}</button>`).join("")
      : '<p class="emnone">No emoji for that. Try another word.</p>';
    grid.scrollTop = 0;
  }
  function pickEmoji(pop, char) {
    $("[data-stkin]", pop).value = char;
    const mark = $("#view .bstk .stk"); if (mark) mark.textContent = char;
    pop.hidden = true;
    $("[data-stkform]", pop).requestSubmit();
  }
  document.addEventListener("input", (ev) => {
    const s = ev.target.closest("[data-empsearch]"); if (!s) return;
    const pop = s.closest("[data-stkpop]"); showEmoji(pop, s.value, 0);
  });
  const oneEmoji = (text) => {
    const parts = [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(text.trim())].map((x) => x.segment);
    const last = parts[parts.length - 1] || "";
    return /\p{Extended_Pictographic}|\p{Regional_Indicator}/u.test(last) ? last : "";
  };
  document.addEventListener("input", (ev) => {
    const i = ev.target.closest("[data-stkin]"); if (!i) return;
    const pick = oneEmoji(i.value);
    if (!pick) return;
    i.value = pick;
    const f = i.closest("form");
    $("#view .bstk .stk").textContent = pick;
    $("#view [data-stkpop]").hidden = true;
    f.requestSubmit();
  });
  function nameEdit(f, on) {
    if (!f) return;
    const h = $("[data-name]", f), keep = f.elements.name.value;
    f.classList.toggle("editing", on);
    h.contentEditable = on ? "plaintext-only" : "false";
    if (on) {
      h.focus();
      const r = document.createRange(); r.selectNodeContents(h);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    } else h.textContent = keep;
  }
  document.addEventListener("keydown", (ev) => {
    const pop = $("#view [data-stkpop]:not([hidden])");
    if (pop && ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); pop.hidden = true; return; }
    const h = ev.target.closest && ev.target.closest("[data-nameform] [data-name]");
    if (!h || h.contentEditable !== "plaintext-only") return;
    const f = h.closest("[data-nameform]");
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); nameEdit(f, false); }
    if (ev.key === "Enter") { ev.preventDefault(); f.requestSubmit($("[data-namesave]", f)); }
  }, true);
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest && ev.target.closest("[data-nameform]"); if (!f) return;
    const name = $("[data-name]", f).textContent.replace(/\s+/g, " ").trim().slice(0, 60);
    if (!name) { ev.preventDefault(); ev.stopImmediatePropagation(); nameEdit(f, false); return; }
    f.elements.name.value = name;
  }, true);

  // a board's people and sorts: the same cards glide to their new places (no picture reloads) while the ones left out
  // fade to grey; the chosen person's row opens in place and the previous one folds away
  document.addEventListener("click", async (ev) => {
    const jump = ev.target.closest("[data-peoplejump]");
    if (jump) {
      ev.preventDefault();
      const side = $("#view .bside"); if (!side) return;
      sideOpen = true; initSide();
      const ppl = $("#people", side);
      ppl?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "center" });
      ppl?.classList.remove("pulse"); void ppl?.offsetWidth; ppl?.classList.add("pulse");
      return;
    }
    const a = ev.target.closest("#view .bperson, #view .bsort:not(.badd)");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || page() !== "board") return;
    ev.preventDefault();
    let got;
    try { got = await getDoc(a.href); } catch (e) { location.href = a.href; return; }
    const fresh = got.doc.getElementById("view"), view = $("#view");
    const grid = $(".mixes", view), ngrid = fresh && $(".mixes", fresh);
    if (!grid || !ngrid) { location.href = got.url; return; }
    history.pushState({ hub: 1 }, "", got.url);
    const g = G(), Fl = F();
    const cards = $$(":scope > [data-flip-id]", grid);
    const state = Fl ? Fl.getState(cards, { props: "opacity,filter" }) : null;
    const keep = new Map(cards.map((c) => [c.dataset.flipId, c]));
    const next = [...ngrid.children].map((n) => {
      const old = n.dataset.flipId && keep.get(n.dataset.flipId);
      if (!old) return n;
      old.className = n.className;
      ["aria-hidden", "inert"].forEach((k) => (n.hasAttribute(k) ? old.setAttribute(k, n.getAttribute(k)) : old.removeAttribute(k)));
      return old;
    });
    grid.replaceChildren(...next);
    if (Fl && state) Fl.from(state, { targets: $$(":scope > [data-flip-id]", grid), duration: .6, ease: "power3.inOut",
                                     props: "opacity,filter", stagger: .015, prune: true });
    const sorts = $(".bsorts", view), nsorts = $(".bsorts", fresh);
    if (sorts && nsorts) $$(".bsort", sorts).forEach((s, i) => { const n = $$(".bsort", nsorts)[i]; if (n) { s.className = n.className; s.href = n.href; } });
    const rows = $$(".bpwrap", view), nrows = $$(".bpwrap", fresh);
    rows.forEach((row, i) => {
      const n = nrows[i]; if (!n) return;
      const link = $(".bperson", row), nlink = $(".bperson", n);
      link.href = nlink.href; link.setAttribute("aria-expanded", nlink.getAttribute("aria-expanded"));
      const more = $(".bmore", row), nmore = $(".bmore", n);
      row.classList.toggle("open", n.classList.contains("open"));
      if (more && !nmore) {
        if (g) g.to(more, { height: 0, opacity: 0, paddingBottom: 0, duration: .35, ease: "power2.inOut", onComplete: () => more.remove() });
        else more.remove();
      } else if (nmore) {
        if (more) more.remove();
        row.append(nmore);
        if (g) g.from(nmore, { height: 0, opacity: 0, paddingBottom: 0, duration: .45, ease: "power3.out", clearProps: "height,opacity,paddingBottom" });
      }
    });
    initView(true);
  });

  function initSynced() {  // "Up to date ✓" after Sync now, then back to the button
    const b = $("#view .cbtn.fresh"); if (!b) return;
    if (/[?&]note=Synced/.test(location.search)) history.replaceState(history.state, "", location.pathname + location.search.replace(/[?&]note=[^&]*/, "").replace(/^&/, "?"));
    setTimeout(() => { b.classList.remove("fresh"); const l = $("span", b); if (l) l.textContent = "Sync now"; }, 2600);
  }
  function initAdd() {
    const f = $("[data-addpicks]"); if (!f) { picked.clear(); return; }
    showPicks(f);
    const box = $("[data-addsearch]");
    if (box && document.activeElement !== box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
  }
  document.addEventListener("contextmenu", (ev) => {
    const tile = ev.target.closest("#view .tile[data-id]"); if (!tile) return;
    ev.preventDefault(); menuFor(tile, ev.clientX, ev.clientY);
  });
  // a board card: Open, Open original, Add to my library (a friend's post kept only for the board), Take it off
  document.addEventListener("contextmenu", (ev) => {
    const card = ev.target.closest(".mx[data-url]"); if (!card || ev.target.closest("a:not(.cover), button")) return;
    ev.preventDefault(); $(".ctx")?.remove();
    const m = document.createElement("div"); m.className = "ctx pop"; m.setAttribute("role", "menu");
    m.innerHTML = '<button data-c="open" role="menuitem">Open</button>' +
      `<a href="${esc(card.dataset.url)}" target="_blank" rel="noopener noreferrer" role="menuitem">Open original ↗</a><hr>` +
      (card.dataset.shelf === "board" ? '<button data-c="library" role="menuitem">Add to my library</button>' : "") +
      '<button data-c="copy" role="menuitem">Copy link</button>' +
      (card.dataset.mine ? '<hr><button data-c="off" class="bad" role="menuitem">Take it off the board…</button>' : "");
    document.body.append(m);
    m.style.left = Math.max(8, Math.min(ev.clientX, innerWidth - m.offsetWidth - 8)) + "px";
    m.style.top = Math.max(8, Math.min(ev.clientY, innerHeight - m.offsetHeight - 8)) + "px";
    $("button", m).focus();
    m.addEventListener("click", async (e2) => {
      if (e2.target.closest("a")) { m.remove(); return; }
      const c = e2.target.closest("[data-c]")?.dataset.c; if (!c) return;
      m.remove();
      if (c === "open") $("a.cover", card)?.click();
      else if (c === "copy") copy(card.dataset.url, "Link");
      else if (c === "library") { await post("/hub/bulk", { ids: card.dataset.id, action: "inbox", next: location.pathname + location.search }); toast("Added to your library"); refresh(true); }
      else if (c === "off" && await ask("Take your card off the board? Friends who already synced it are asked to hide it.", "Take it off", true)) {
        await post("/hub/boards/remove-card", { board: card.dataset.board, url: card.dataset.url, next: location.pathname }); refresh(true);
      }
    });
    setTimeout(() => document.addEventListener("pointerdown", function off(e3) { if (!m.contains(e3.target)) { m.remove(); document.removeEventListener("pointerdown", off); } }), 0);
  });
  let press = null;
  document.addEventListener("touchstart", (ev) => {
    const tile = ev.target.closest("#view .tile[data-id]"); if (!tile) return;
    const t = ev.touches[0];
    press = setTimeout(() => { menuFor(tile, t.clientX, t.clientY); press = "done"; }, 550);
  }, { passive: true });
  document.addEventListener("touchend", (ev) => { if (press === "done") ev.preventDefault(); clearTimeout(press); press = null; });
  document.addEventListener("touchmove", () => { clearTimeout(press); press = null; }, { passive: true });

  // ---- getting started: the floating checklist ticks itself as each real step is done ----------------------------------------------
  const GUIDE = {  // what to point at for each step, and what to say
    watch: ["Click a key moment to jump to it in the video", () => $$(".kp[data-t]").find((x) => x.offsetParent) || $$(".tline").find((x) => x.offsetParent)],
    link: ["Open the link this post is about", () => $$("a.pvprimary[href^=http]").find((x) => x.offsetParent) || $$(".pvprimary.find").find((x) => x.offsetParent)],
    note: ["Write why you saved it", () => $$("[data-pvshow]").find((x) => x.offsetParent)],
    search: ["Type a word you remember from a post", () => (typeof q !== "undefined" && q && q.offsetParent ? q : null)],
  };
  let guideEnd = null;
  function gGuideStop() { guideEnd?.(); guideEnd = null; }
  function gGuide(step) {
    gGuideStop();
    const g = GUIDE[step]; const el = g && g[1](); if (!el) return false;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("gglow");
    const tip = document.createElement("div"); tip.className = "gtip"; tip.textContent = g[0]; document.body.append(tip);
    let live = true;
    const place = () => {
      if (!live) return;
      const r = el.getBoundingClientRect(), up = r.top > 90;
      tip.className = "gtip " + (up ? "up" : "down");
      tip.style.left = Math.max(130, Math.min(innerWidth - 130, r.left + r.width / 2)) + "px";
      tip.style.top = (up ? r.top - tip.offsetHeight - 14 : r.bottom + 14) + "px";
      requestAnimationFrame(place);
    };
    place();
    const end = () => { live = false; el.classList.remove("gglow"); tip.remove(); document.removeEventListener("click", end, true); clearTimeout(t); };
    const t = setTimeout(end, 20000);
    setTimeout(() => document.addEventListener("click", end, true), 400);
    guideEnd = end;
    return true;
  }
  const act = (kind) => fetch("/hub/activity", { method: "POST", keepalive: true, headers: FORM, body: new URLSearchParams({ csrf, kind }) }).catch(() => {});  // counted on this Mac only
  const gTick = (step) => {
    const g = $("#gstart"); if (!g || g.querySelector(`[data-gs="${step}"].done`)) return;
    fetch("/hub/checklist", { method: "POST", keepalive: true, headers: FORM, body: new URLSearchParams({ csrf, action: "tick", step }) }).then(gRefresh).catch(() => {});
  };
  async function gRefresh() {
    const g = $("#gstart"); if (!g) return;
    const was = new Set($$("li.done", g).map((x) => x.dataset.gs));
    const r = await fetch("/checklist/panel", { cache: "no-store" }); if (!r.ok) return;
    const html = await r.text(); if (!html.trim()) { g.remove(); return; }
    g.innerHTML = html;
    $$("li.done", g).forEach((x) => { if (!was.has(x.dataset.gs)) { x.classList.add("just"); gGuideStop(); } });
    if (!g.querySelector("li:not(.done)")) { g.classList.add("fin"); setTimeout(() => { post("/hub/checklist", { action: "off" }); G()?.to(g, { opacity: 0, y: 12, duration: .4, onComplete: () => g.remove() }) || g.remove(); }, 4500); }
  }
  try { if (localStorage.getItem("mag-gstart") === "1") $("#gstart")?.classList.add("min"); } catch (e) { /* fine */ }
  // arriving from the checklist: point at the thing to do
  try { const s = sessionStorage.getItem("mag-guide"); if (s) { sessionStorage.removeItem("mag-guide"); setTimeout(() => gGuide(s), 900); } } catch (e) { /* fine */ }
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (t.closest("[data-gcollapse]")) { const g = $("#gstart"); g.classList.toggle("min"); try { localStorage.setItem("mag-gstart", g.classList.contains("min") ? "1" : "0"); } catch (e) { /* fine */ } return; }
    if (t.closest("[data-goff]")) { gGuideStop(); post("/hub/checklist", { action: "off" }); $("#gstart")?.remove(); return; }
    const row = t.closest("[data-gstep]");
    if (row) {
      const step = row.dataset.gstep;
      if (step === "search") { if (typeof openSearch === "function") { openSearch(); if (!bigSearch()) q?.focus(); } setTimeout(() => gGuide("search"), 200); return; }
      if (!GUIDE[step][1]()) { try { sessionStorage.setItem("mag-guide", step); } catch (e) { /* fine */ } location.href = "/item/" + row.dataset.post; return; }
      gGuide(step); return;
    }
    if (t.closest(".kp[data-t], .tline")) gTick("watch");
    if (t.closest("a.pvprimary[href^=http]")) { gTick("link"); act("link"); }
    if (t.closest("[data-copy]")) act("copy");
  });
  document.addEventListener("submit", (ev) => { const f = ev.target; if (f.matches?.(".pvnoteform") && f.querySelector("textarea")?.value.trim()) gTick("note"); }, true);
  if (q) { let gt; q.addEventListener("input", () => { clearTimeout(gt); if (q.value.trim().length >= 3) gt = setTimeout(() => gTick("search"), 900); }); }

  // ---- Digest: "I tried this" and Dismiss on a Worth-doing pick; Undo stays on the page until you leave it -------------------------
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-pick]"); if (!b) return;
    const row = b.closest(".dgrow"); if (!row) return;
    const state = b.dataset.pick, id = row.dataset.digest, idx = row.dataset.idx;
    await post("/hub/digest/pick", { digest: id, idx, state });
    if (state === "dismissed") {
      const stub = document.createElement("div"); stub.className = "dgstub"; stub.dataset.digest = id; stub.dataset.idx = idx;
      stub.innerHTML = '<span>Dismissed. It won\'t be suggested again.</span><button type="button" data-pickback>Undo</button>';
      stub._row = row; row.replaceWith(stub);
      G()?.from(stub, { opacity: 0, height: 0, duration: .3, ease: "power2.out" });
    } else if (state === "tried") {
      row.classList.add("tried");
      $(".dgpa", row).innerHTML = '<button type="button" class="dgundo" data-pick="clear">Tried it · Undo</button>';
      G()?.from($(".dgpa .dgundo", row), { opacity: 0, y: 4, duration: .3 });
      window.MagDigest?.tried(row, $(".dgpa .dgundo", row));
      toast("Nice. Marked as tried");
    } else {
      row.classList.remove("tried");
      $(".dgpa", row).innerHTML = '<button type="button" class="dgtry" data-pick="tried">' + (row._try || "I tried this") + '</button><button type="button" class="dgskip" data-pick="dismissed" title="Not for me: don\'t suggest it again">Dismiss</button>';
    }
  });
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-pickback]"); if (!b) return;
    const stub = b.closest(".dgstub"); await post("/hub/digest/pick", { digest: stub.dataset.digest, idx: stub.dataset.idx, state: "clear" });
    stub.replaceWith(stub._row); G()?.from(stub._row, { opacity: 0, duration: .3 });
  });

  // ---- keyboard ---------------------------------------------------------------------------------------------------------------
  let kIndex = -1;
  function focusTile(id, scroll = true) {
    const tiles = $$("#view .tile[data-id]");
    tiles.forEach((t) => t.classList.remove("kfocus"));
    const i = tiles.findIndex((t) => t.dataset.id === String(id));
    if (i >= 0) { kIndex = i; tiles[i].classList.add("kfocus"); if (scroll) tiles[i].scrollIntoView({ block: "nearest", behavior: calm ? "auto" : "smooth" }); }
  }
  function sheet() {
    if ($(".keys")) { $(".keys").remove(); return; }
    const k = document.createElement("div"); k.className = "dlg-wrap keys";
    k.innerHTML = '<div class="dlg"><h3>Shortcuts</h3><dl>' + [["/", "Search"], ["Esc", "Close or clear"], ["J / K", "Next / previous post on the wall"],
      ["Enter", "Open the post with the ring"], ["← →", "Previous / next inside a post"], ["⌘-click, Shift-click", "Select posts"],
      ["Right-click", "Actions for a post"], ["?", "This list"]]
      .map(([a, b]) => `<dt><kbd>${a}</kbd></dt><dd>${b}</dd>`).join("") + '</dl><div class="row"><button class="btn dark" type="button">Got it</button></div></div>';
    document.body.append(k);
    k.addEventListener("click", (ev) => { if (ev.target === k || ev.target.closest("button")) k.remove(); });
    G()?.from($(".dlg", k), { y: 12, opacity: 0, duration: .25 });
    $("button", k).focus();
  }
  document.addEventListener("keydown", (ev) => {
    // a dialog is open, unless it is a board card's under a post opened from it
    if ($$(".dlg-wrap:not(.keys)").length) return;
    const ae = document.activeElement;
    const typing = /INPUT|TEXTAREA|SELECT/.test(ae?.tagName || "") && !(ae.matches?.(".askp textarea") && !ae.value && (ev.key === "ArrowLeft" || ev.key === "ArrowRight"));  // an empty Ask box: the arrows still step through posts
    if (ev.key === "Escape") {
      if ($(".keys")) { $(".keys").remove(); return; }
      if ($(".ctx")) { $(".ctx").remove(); return; }
      if ($(".chooser")) { $(".chooser").remove(); return; }
      if (sover && !sover.hidden) { closeSearch(); return; }
      if (addm && !addm.hidden) { closeAdd(); return; }
      if (helpOpen()) { closeHelp(); return; }
      if (nestOpen()) { closeNest(); return; }
      if (document.body.classList.contains("selecting")) { selectMode(false); return; }
      $$("details.menu[open], details.trials[open]").forEach((d) => d.removeAttribute("open"));
    }
    if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === "/" && q) { ev.preventDefault(); openSearch(); if (!bigSearch()) q.focus(); return; }
    if (ev.key === "?") { ev.preventDefault(); sheet(); return; }
    const tiles = $$("#view .tile[data-id]");
    if ((ev.key === "j" || ev.key === "k") && tiles.length) {
      kIndex = Math.max(0, Math.min(tiles.length - 1, kIndex + (ev.key === "j" ? 1 : -1)));
      focusTile(tiles[kIndex].dataset.id);
    }
    if (ev.key === "Enter" && kIndex >= 0 && tiles[kIndex] && document.activeElement === document.body) goPage(tiles[kIndex].dataset.id);
  });

  // ---- things each page sets up after it arrives ------------------------------------------------------------------------------
  function initBanners() {
    $$("[data-dismiss]").forEach((b) => {
      if (store.get("dismissed", []).includes(b.dataset.dismiss)) { b.remove(); return; }
      const btn = $("[data-dismiss-btn]", b);
      if (btn) btn.onclick = () => {
        store.set("dismissed", [...store.get("dismissed", []), b.dataset.dismiss].slice(-20));
        if (G()) G().to(b, { height: 0, opacity: 0, marginBottom: 0, paddingTop: 0, paddingBottom: 0, duration: .3, onComplete: () => b.remove() }); else b.remove();
      };
    });
  }
  // a long board: the next chunk of cards loads as the page is scrolled to it
  let bmoreObs = null;
  function initBMore() {
    bmoreObs?.disconnect();
    const more = $("#view [data-bmore]"); if (!more) return;
    bmoreObs = new IntersectionObserver(async (entries) => {
      if (!entries[0].isIntersecting) return;
      bmoreObs.disconnect();
      let html = "";
      try { const r = await fetch(more.dataset.href, { cache: "no-store" }); if (!r.ok) throw 0; html = await r.text(); } catch (e) { setTimeout(initBMore, 2000); return; }
      const box = document.createElement("div"); box.innerHTML = html;
      const next = $("[data-bmore]", box), cards = $$("article.mx", box).filter((a) => !a.closest("[data-bmore]"));
      const grid = $("#view .grid.mixes:not(.bmore .grid)");
      (grid || more.parentElement).append(...cards);
      if (next) more.replaceWith(next); else more.remove();
      dealIn(cards);
      initBMore();
    }, { rootMargin: "1100px 0px" });
    bmoreObs.observe(more);
  }
  let moreObs = null;
  function initMore() {
    moreObs?.disconnect();
    const more = $("#view a[data-more]"); if (!more) return;  // the library's Show more link, not a post's "+N more" button
    moreObs = new IntersectionObserver(async (entries) => {
      if (!entries[0].isIntersecting) return;
      moreObs.disconnect();
      const r = await fetch(more.href, { cache: "no-store" }); if (!r.ok) return;
      const box = document.createElement("div"); box.innerHTML = await r.text();
      const added = [];
      $$(":scope > [data-sec]", box).forEach((blk) => {
        const mine = $(`#view [data-sec="${CSS.escape(blk.dataset.sec)}"] .grid`);
        const tiles = $$(".tile", blk);
        if (mine) mine.append(...tiles); else more.before(blk);
        added.push(...tiles);
      });
      const next = $("[data-more]", box);
      if (next) more.replaceWith(next); else more.remove();
      /* indigo.js eases the new tiles in */
      initMore();
    }, { rootMargin: "900px 0px" });
    moreObs.observe(more);
  }
  let heroBound = false;
  function heroShrink() {
    if (calm) return;
    const upd = () => {
      const hero = $("#hero"); if (!hero || hero.classList.contains("compact")) return;  // one line already: nothing to shrink
      const h1 = $("h1", hero), p = $("p", hero);
      const t = Math.min(1, Math.max(0, scrollY / 240));
      h1.style.transform = `scale(${1 - .45 * t})`;
      if (p) p.style.opacity = String(Math.max(0, 1 - t * 1.4));
    };
    if (!heroBound) { heroBound = true; let raf = null; addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(() => { raf = null; upd(); }); }, { passive: true }); }
    upd();
  }
  addEventListener("scroll", () => $("#top")?.classList.toggle("scrolled", scrollY > 4), { passive: true });
  function topHeight() {
    const top = $("#top"); if (!top) return;
    const set = () => root.style.setProperty("--top-h", Math.round(top.getBoundingClientRect().bottom) + "px");
    if (!top.dataset.watched) { top.dataset.watched = "1"; new ResizeObserver(set).observe(top); }
    set();
  }
  function initMenus(scope = document) {
    $$("details.menu", scope).forEach((d) => {
      if (d.dataset.wired) return; d.dataset.wired = "1";
      d.addEventListener("toggle", () => {
        if (!d.open) return;
        $$("details.menu[open]").forEach((o) => { if (o !== d) o.removeAttribute("open"); });
        G()?.fromTo($(".pop", d), { opacity: 0, y: -6, scale: .98 }, { opacity: 1, y: 0, scale: 1, duration: .2, ease: "power2.out" });
      });
    });
  }
  document.addEventListener("pointerdown", (ev) => { if (!ev.target.closest("details.menu")) $$("details.menu[open]").forEach((d) => d.removeAttribute("open")); });
  function initProvider() {
    // every key form (AI keys, web-search keys, the Welcome step) shows the guide of its own chosen provider
    $$("select[name=provider]").forEach((prov) => {
      if (prov.dataset.wired) return; prov.dataset.wired = "1";
      const form = prov.closest("form") || document;
      const show = () => {
        $$(".guide2[data-provider]", form).forEach((g) => { g.hidden = g.dataset.provider !== prov.value; });
        const pickModel = ["openrouter", "claude", "openai"].includes(prov.value);
        const m = $("#model", form), ml = $("#model-label", form);
        if (m) { m.hidden = !pickModel; m.setAttribute("list", "models-" + prov.value); }
        if (ml) ml.hidden = !pickModel;
      };
      prov.addEventListener("change", show); show();
    });
  }
  // ---- help: the third column on Settings (a panel when narrow), and the "?" panel everywhere else ------------
  const helpEl = $("#helpsheet"), hsin = $("#hsin");
  const setHelp = () => $("#view #sethelp");
  const helpOpen = () => (helpEl && !helpEl.hidden) || !!setHelp()?.classList.contains("open");
  function showScrim(on) { const s = $("#scrim"); if (s) s.hidden = !on; }
  async function openHelp() {
    if (page() === "help") return;
    const sh = setHelp();
    if (sh) {  // Settings: the column itself slides in when it can't sit beside the content
      sh.classList.add("open"); showScrim(true);
      G()?.fromTo(sh, { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: .32, ease: "power3.out", clearProps: "transform,opacity" });
      return;
    }
    if (!helpEl) return;
    closeNest();
    const ctx = page();
    hsin.innerHTML = '<div class="hwrap"><div class="sk skl"></div><div class="sk skl"></div><div class="sk skl short"></div></div>';
    // the same size, place and slide-in as Ask's sheet; like Ask it takes the bottom-right corner while it is open
    const btn = $("#t-help");
    try { const w = parseInt(localStorage.getItem("magpiary.askw"), 10); helpEl.style.width = w ? Math.min(w, innerWidth - 24) + "px" : ""; } catch (e) { /* default */ }  // as wide as Ask's sheet
    helpEl.hidden = false;
    document.body.classList.add("helpopen");
    btn?.classList.add("open");
    G()?.fromTo(helpEl, { x: 36, opacity: 0 }, { x: 0, opacity: 1, duration: .3, ease: "power3.out", clearProps: "x" });
    try {
      const r = await fetch(`/help?frag=1&ctx=${encodeURIComponent(ctx)}`, { cache: "no-store" });
      hsin.innerHTML = await r.text();
      G()?.from($$(".hwrap > *", hsin), { opacity: 0, y: 10, duration: .35, stagger: .04, clearProps: "opacity,transform" });
    } catch (e) { location.href = "/help"; }
  }
  function closeHelp() {
    const sh = setHelp(), g = G();
    if (sh?.classList.contains("open")) {
      const done = () => { sh.classList.remove("open"); g?.set(sh, { clearProps: "transform,opacity" }); };
      if (g) g.to(sh, { x: 40, opacity: 0, duration: .2, onComplete: done }); else done();
      showScrim(false); return;
    }
    if (!helpEl || helpEl.hidden) return;
    $("#t-help")?.classList.remove("open");
    document.body.classList.remove("helpopen");
    const done = () => { helpEl.hidden = true; g?.set(helpEl, { clearProps: "transform,opacity" }); };
    if (g) g.to(helpEl, { x: 36, opacity: 0, duration: .2, ease: "power2.in", onComplete: done }); else done();
  }
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("#t-help, #sethelpbtn")) { ev.preventDefault(); ev.stopPropagation(); helpOpen() ? closeHelp() : openHelp(); return; }
    if (ev.target.closest("[data-hclose]")) { closeHelp(); return; }
    if (helpEl && !helpEl.hidden && ev.target.closest("#helpsheet a[href]")) closeHelp();
  }, true);
  document.addEventListener("pointerdown", (ev) => {
    if (helpOpen() && !ev.target.closest("#helpsheet, #sethelp, #t-help, #sethelpbtn, .dlg-wrap, .pop")) closeHelp();
  });
  // the digest (Spotlight, one column): pills packed into a cloud, a click on one swaps the content below the hero to
  // its saves; a slow dark glow behind; confetti once per new digest
  function initDigest() {
    const box = $("#dgstory");
    if (!box) return;
    const calmMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const show = (n) => {
      const panel = n == null ? null : $(`.dgword[data-word="${n}"]`, box);
      $$(".dgword", box).forEach((w) => { w.hidden = w !== panel; });
      $$(".dgpill", box).forEach((p) => p.classList.toggle("on", panel && p.dataset.pill === String(n)));
      if (!panel) return;
      G()?.fromTo(panel, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" });
      panel.scrollIntoView({ behavior: calmMotion ? "auto" : "smooth", block: "start" });
    };
    box.addEventListener("click", (ev) => {
      const pill = ev.target.closest(".dgpill"), back = ev.target.closest("[data-wordback]");
      if (pill) show(pill.classList.contains("on") ? null : pill.dataset.pill);
      else if (back) show(null);
    });
    shader(box);
    packPills(box);
    let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => packPills(box), 150); });
    const seen = store.get("digest.confetti", []), first = !box.dataset.waiting && !seen.includes(box.dataset.digest);
    if (first) store.set("digest.confetti", [...seen, box.dataset.digest].slice(-30));
    window.MagDigest?.play(box, { first });
    if (box.dataset.waiting) setTimeout(() => { if ($("#dgstory") === box) go(location.href, { push: false }); }, 20000);
  }

  function packPills(box) {
    const cloud = $("#dgpills", box);
    if (!cloud || !box.isConnected) return;
    const pills = $$(".dgpill", cloud);
    cloud.classList.remove("packed"); cloud.style.minHeight = "";
    pills.forEach((p) => { p.style.left = p.style.top = ""; });
    const cs = getComputedStyle(cloud), padL = parseFloat(cs.paddingLeft) || 0;
    const W = cloud.clientWidth - padL - (parseFloat(cs.paddingRight) || 0); // pills stay inside a tile's padding
    if (W < 420) return; // a phone keeps the plain wrapped row
    const sizes = pills.map((p) => [p.offsetWidth, p.offsetHeight]);
    const placed = [];
    const hits = (x, y, w, h) => placed.some((r) => Math.abs(x - r.x) * 2 < w + r.w - 12 && Math.abs(y - r.y) * 2 < h + r.h - 12);
    sizes.forEach(([w, h], i) => {
      for (let s = 0; s < 4000; s++) {
        const a = s * 0.33, r = i ? 4 + s * 0.8 : 0;
        const x = Math.cos(a) * r * 1.9, y = Math.sin(a) * r * 0.75;
        if (Math.abs(x) + w / 2 > W / 2) continue;
        if (!hits(x, y, w, h)) { placed.push({ x, y, w, h }); return; }
      }
      placed.push({ x: 0, y: 0, w, h });
    });
    const top = Math.min(...placed.map((r) => r.y - r.h / 2)), bottom = Math.max(...placed.map((r) => r.y + r.h / 2));
    cloud.classList.add("packed");
    // placed from the middle, so a cloud that is stretched taller (the bento's tile) stays centred in it
    const mid = (top + bottom) / 2;
    cloud.style.minHeight = `${bottom - top + 24}px`;
    pills.forEach((p, i) => { const r = placed[i]; p.style.left = `${padL + W / 2 + r.x - r.w / 2}px`; p.style.top = `calc(50% + ${r.y - r.h / 2 - mid}px)`; p.style.zIndex = pills.length - i; });
  }

  function shader(box) {
    const canvas = $("#dgshader", box);
    if (!canvas || canvas.dataset.on) return;
    const gl = canvas.getContext("webgl", { premultipliedAlpha: false, antialias: false });
    if (!gl) return; // the CSS glow stays
    canvas.dataset.on = "1";
    const src = (type, code) => { const sh = gl.createShader(type); gl.shaderSource(sh, code); gl.compileShader(sh); return sh; };
    const prog = gl.createProgram();
    gl.attachShader(prog, src(gl.VERTEX_SHADER, "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}"));
    gl.attachShader(prog, src(gl.FRAGMENT_SHADER, `precision mediump float;uniform vec2 r;uniform float t;uniform vec3 a,b,c,d,bg;
      void main(){vec2 u=gl_FragCoord.xy/r;u.x*=r.x/r.y;float k=r.x/r.y;
      vec2 p1=vec2(k*(.25+.18*sin(t*.11)),.72+.16*cos(t*.13)),p2=vec2(k*(.78+.14*cos(t*.09)),.66+.2*sin(t*.12)),
           p3=vec2(k*(.32+.2*cos(t*.07)),.18+.14*sin(t*.1)),p4=vec2(k*(.8+.12*sin(t*.08)),.2+.18*cos(t*.11));
      float w1=1./(.02+pow(distance(u,p1),2.)),w2=1./(.02+pow(distance(u,p2),2.)),w3=1./(.02+pow(distance(u,p3),2.)),w4=1./(.02+pow(distance(u,p4),2.));
      vec3 col=(a*w1+b*w2+c*w3+d*w4)/(w1+w2+w3+w4);float fade=smoothstep(.0,.9,u.y);
      gl_FragColor=vec4(mix(bg,col,.22+.2*fade),1.);}`));
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const colours = () => ["#2b2aa0", "#16307a", "#4a2a9a", "#0e1a5a", "#05051a"]; // the Spotlight page is always dark
    const size = () => { canvas.width = Math.max(1, innerWidth / 3); canvas.height = Math.max(1, innerHeight / 3); gl.viewport(0, 0, canvas.width, canvas.height); };
    size(); addEventListener("resize", size);
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let last = 0;
    const frame = (now) => {
      if (!canvas.isConnected) { canvas.dataset.on = ""; return; }
      if (!document.hidden && now - last > 33) {
        last = now;
        const [a, b, c, d, bg] = colours().map(hex);
        gl.uniform2f(u("r"), canvas.width, canvas.height); gl.uniform1f(u("t"), still ? 4 : now / 1000);
        gl.uniform3fv(u("a"), a); gl.uniform3fv(u("b"), b); gl.uniform3fv(u("c"), c); gl.uniform3fv(u("d"), d); gl.uniform3fv(u("bg"), bg);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        if (still) { canvas.dataset.on = ""; return; }
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  // the /help page: search as you type
  function initHelpSearch() {
    const input = $("#view #helpq"); if (!input || input.dataset.wired) return; input.dataset.wired = "1";
    input.addEventListener("input", () => {
      const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      $$("#view .htopic").forEach((t) => {
        let any = false;
        $$(".hitem", t).forEach((it) => {
          const hit = words.every((w) => it.textContent.toLowerCase().includes(w));
          it.hidden = !hit; if (hit) any = true;
          if (words.length) it.open = hit && it.classList.contains("hfaq"); else it.open = false;
        });
        $$(".hguides, .hfaqs", t).forEach((list) => { const h = list.previousElementSibling; if (h) h.hidden = !$$(".hitem", list).some((it) => !it.hidden); });
        t.hidden = !any; if (any) shown++;
      });
      const none = $("#view .hnone"); if (none) none.hidden = shown > 0;
    });
  }

  // A dialog the hub draws over a page (a board card, an invite, a phone's QR code): focus goes into it, Tab stays in
  // it, the page behind is inert, and once it is gone focus goes back to what opened it (or that page's heading)
  const TABBABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"])';
  let dlgInert = [], dlgBack = "";
  function holdFocus(w) {
    dlgInert.forEach((el) => { el.inert = false; });
    dlgInert = [];
    for (let el = w; el && el !== document.body; el = el.parentElement) {
      [...(el.parentElement?.children || [])].forEach((s) => { if (s !== el && s.id !== "toasts" && !s.inert) { s.inert = true; dlgInert.push(s); } });
    }
    const card = new URLSearchParams(location.search).get("card");
    const member = new URLSearchParams(location.search).get("member");
    dlgBack = member ? `#view a.pface[href$="member=${CSS.escape(member)}"], #view .bperson, #view [data-profile$="member=${CSS.escape(member)}"]`
      : card ? `#view a.cover[href$="card=${CSS.escape(card)}"]` : $(".invdlg", w) ? '#view form[action="/hub/boards/invite"] button' : "";
    // board pages load in full, so closing by the dialog's own link leaves a note for the page that comes next
    w.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[href]");
      if (a && a.getAttribute("href") === w.dataset.close) try { sessionStorage.setItem("mag-dlgback", JSON.stringify({ path: new URL(a.href).pathname, sel: dlgBack })); } catch (e) { /* fine */ }
    });
    const dlg = $(".dlg", w);
    dlg.tabIndex = -1;
    if (!dlg.contains(document.activeElement)) dlg.focus({ preventScroll: true });
    w.addEventListener("keydown", (ev) => {
      if (ev.key !== "Tab") return;
      const all = $$(TABBABLE, dlg).filter((x) => x.offsetParent !== null);
      if (!all.length) { ev.preventDefault(); return; }
      const first = all[0], last = all[all.length - 1], at = document.activeElement;
      if (ev.shiftKey && (at === first || at === dlg)) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && at === last) { ev.preventDefault(); first.focus(); }
    });
  }
  function releaseFocus() {
    let note = null;
    try { note = JSON.parse(sessionStorage.getItem("mag-dlgback") || "null"); sessionStorage.removeItem("mag-dlgback"); } catch (e) { /* fine */ }
    if (note && note.path === location.pathname && !dlgInert.length) dlgBack = note.sel;
    else if (!dlgInert.length) return;
    dlgInert.forEach((el) => { el.inert = false; });
    dlgInert = [];
    let to = dlgBack && $(dlgBack);
    if (!to) { to = $("#view h1, #view h2"); if (to) to.tabIndex = -1; }
    dlgBack = "";
    to?.focus({ preventScroll: !to.matches("a.cover") });
  }

  // ---- profiles: See all, and editing in place ----------------------------------------------------------------------------
  // a form that shows its Save and Cancel only once something changed; filled link chips look filled
  function markDirty(f) {
    const dirty = [...f.elements].some((el) => el.name && el.type === "text" && el.value !== el.defaultValue);
    const acts = $(".pform-acts", f); if (acts) acts.hidden = !dirty;
    $$(".lchip", f).forEach((c) => c.classList.toggle("filled", !!$("input", c).value.trim()));
  }
  document.addEventListener("input", (ev) => {
    const f = ev.target.closest?.("[data-dirty]"); if (f) markDirty(f);
    const add = ev.target.closest?.("[data-addtopic]");  // Add stays off until something is typed
    if (add) $(".btn", add).disabled = !ev.target.value.trim();
  });
  // a row of a person's cards shows one row; See all appears only when more would not fit in it
  function initTiles() {
    $$("[data-clamp]").forEach((t) => {
      const cols = getComputedStyle(t).gridTemplateColumns.split(" ").length, btn = t.nextElementSibling;
      if (btn?.matches("[data-seeall]")) btn.hidden = t.children.length <= cols && !t.classList.contains("open");
    });
  }
  addEventListener("resize", initTiles);

  // a profile tilts toward the pointer and its shine follows it (not while someone is typing in it, nor with reduced motion)
  if (!calm) {
    document.addEventListener("pointermove", (ev) => {
      const p = ev.target.closest?.(".person");
      if (!p || p.matches(":focus-within") || ev.pointerType === "touch" || p.closest("#setpane")) return;  // never tilt under the edit buttons
      const r = p.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
      p.style.setProperty("--tilt-y", ((x - .5) * 9).toFixed(2) + "deg"); p.style.setProperty("--tilt-x", ((.5 - y) * 7).toFixed(2) + "deg");
      p.style.setProperty("--mx", (x * 100).toFixed(1) + "%"); p.style.setProperty("--my", (y * 100).toFixed(1) + "%");
    });
    document.addEventListener("pointerout", (ev) => {
      const p = ev.target.closest?.(".person");
      if (p && !p.contains(ev.relatedTarget)) { p.style.setProperty("--tilt-x", "0deg"); p.style.setProperty("--tilt-y", "0deg"); }
    });
  }
  const closeEd = (form) => { $(".pedview", form).hidden = false; $(".pedform", form).hidden = true; };
  document.addEventListener("click", (ev) => {
    const all = ev.target.closest("[data-seeall]");
    if (all) {
      const tiles = all.previousElementSibling; if (!tiles) return;
      all.dataset.label ||= all.textContent;
      const open = tiles.classList.toggle("open");
      all.setAttribute("aria-expanded", String(open)); all.textContent = open ? "Show fewer" : all.dataset.label;
      return;
    }
    const cancelDirty = ev.target.closest("[data-dirtycancel]");
    if (cancelDirty) { const f = cancelDirty.closest("[data-dirty]"); f.reset(); markDirty(f); return; }
    const open = ev.target.closest("[data-edopen]");
    if (open) {
      const form = open.closest("[data-ed]");
      $$("[data-ed]").forEach((f) => { if (f !== form) closeEd(f); });
      $(".pedview", form).hidden = true; const box = $(".pedform", form); box.hidden = false;
      const field = $("input, textarea", box); field.focus(); field.setSelectionRange?.(field.value.length, field.value.length);
      return;
    }
    const cancel = ev.target.closest("[data-edcancel]");
    if (cancel) { const form = cancel.closest("[data-ed]"); form.reset(); closeEd(form); $("[data-edopen]", form)?.focus(); return; }
    const pav = ev.target.closest("[data-pavpop]");
    const box = $("[data-pavbox]");
    if (pav && box) { box.hidden = !box.hidden; pav.setAttribute("aria-expanded", String(!box.hidden)); return; }
    if (box && !box.hidden && !ev.target.closest("[data-pavbox]")) { box.hidden = true; $("[data-pavpop]")?.setAttribute("aria-expanded", "false"); }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const form = ev.target.closest?.("[data-ed]");
    if (form && !$(".pedform", form).hidden) { ev.stopPropagation(); form.reset(); closeEd(form); $("[data-edopen]", form)?.focus(); return; }
    const box = $("[data-pavbox]");
    if (box && !box.hidden) { ev.stopPropagation(); box.hidden = true; const b = $("[data-pavpop]"); b?.setAttribute("aria-expanded", "false"); b?.focus(); }
  }, true);

  // Faces on a board's folder open that person's profile: the folder itself is a link, so this is a click handler, not a link
  document.addEventListener("click", (ev) => {
    const f = ev.target.closest("[data-profile]");
    if (!f || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault(); ev.stopPropagation();
    location.href = f.dataset.profile;
  }, true);

  // The QR code for a new phone: a ring that empties over the code's minutes, and steps that tick themselves off as
  // the phone opens the page, downloads the Shortcut and sends its first share (asked of the Mac every 2 s)
  let qrTimer = 0, qrPoll = 0, qrPair = "";
  function initQr() {
    const w = $("#view .qrwrap") || $(".w-body .qrwrap");
    const d = w && $(".pairdlg", w);
    if (!d || d.dataset.pair !== qrPair) { clearInterval(qrTimer); clearTimeout(qrPoll); qrTimer = 0; qrPair = d ? d.dataset.pair : ""; }
    if (!w) { releaseFocus(); return; }
    if (d && !qrTimer) {
      const total = 900, prog = $(".pprog", d), lb = $(".pleft b", d), ls = $(".pleft small", d), lis = $$(".pticks li", d);
      let end = Date.now() + Number(d.dataset.left || 0) * 1000;
      const paint = (st) => {
        if (st) {
          end = Date.now() + st.left * 1000;
          const reached = st.shared ? 3 : st.downloaded ? 2 : st.opened ? 1 : 0;
          lis.forEach((li, i) => {
            const was = li.className, now = i < reached ? "pd" : i === reached ? "pn" : "";
            if (was !== now) li.className = now;
            setText($("em", li), i < reached ? li.dataset.done : i === reached ? li.dataset.wait : "");
            if (was !== "pd" && li.className === "pd") G()?.fromTo($(".pdot", li), { scale: .6 }, { scale: 1, duration: .45, ease: "back.out(2.5)" });
          });
          d.classList.toggle("sent", st.downloaded && !st.shared);
          d.classList.toggle("paired", st.shared);
        }
        const s = Math.max(0, Math.round((end - Date.now()) / 1000)), held = d.matches(".sent, .paired");
        d.classList.toggle("dead", !s && !held);
        d.classList.toggle("low", s > 0 && s < 120 && !held);
        const off = (100 - s / total * 100).toFixed(2);
        if (prog && prog.style.strokeDashoffset !== off) prog.style.strokeDashoffset = off;
        const [big, small] = d.matches(".paired") ? ["Paired", "This code is no longer needed"]
          : d.matches(".sent") ? ["Shortcut sent", "Now add it on the phone"]
          : !s ? ["0:00", "Make a new code to carry on"]
          : [`${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`, "until this code stops working"];
        setText(lb, big); setText(ls, small);
      };
      const poll = async () => {
        if (!document.body.contains(d)) return;
        try {
          const r = await fetch("/pair.json?qr=" + encodeURIComponent(d.dataset.pair), { cache: "no-store" });
          if (r.ok) paint(await r.json());
        } catch (_) { /* the Mac answers again on the next round */ }
        if (!d.matches(".paired, .dead")) qrPoll = setTimeout(poll, 2000);
      };
      paint(null); qrTimer = setInterval(() => paint(null), 1000); qrPoll = setTimeout(poll, 1500);
    }
    if (w.dataset.wired) return; w.dataset.wired = "1";
    holdFocus(w);
    G()?.from($(".dlg", w), { y: 14, opacity: 0, scale: .97, duration: .3, ease: "power3.out" });
    // closing leaves the page behind as it is (reloading it made the whole section blink); only the address changes
    const close = () => {
      clearInterval(qrTimer); clearTimeout(qrPoll); qrTimer = 0; qrPair = "";
      const gone = () => { w.remove(); releaseFocus(); history.replaceState({ hub: 1 }, "", w.dataset.close); };
      const g = G(); if (g) g.to(w, { opacity: 0, duration: .2, ease: "power2.out", onComplete: gone }); else gone();
    };
    w.addEventListener("click", (ev) => {
      if (ev.target === w || ev.target.closest("[data-qrdone]")) { ev.preventDefault(); close(); }
    });
    $$(".purl .btn", w).forEach((b) => b.addEventListener("click", () => {  // Copy says it worked, then goes back
      const was = b.innerHTML; b.classList.add("ok"); b.innerHTML = b.innerHTML.replace(/Copy$/, "Copied");
      G()?.fromTo(b, { scale: .92 }, { scale: 1, duration: .35, ease: "back.out(3)" });
      setTimeout(() => { b.innerHTML = was; b.classList.remove("ok"); }, 1600);
    }));
    // capture, so a post opened over this dialog (or a confirm) still counts as open when Escape closes it
    const key = (ev) => {
      if (!document.body.contains(w)) { document.removeEventListener("keydown", key, true); return; }
      if (ev.key === "Escape" && !$("body > .dlg-wrap")) close();
    };
    document.addEventListener("keydown", key, true);
  }
  function initProfile() {
    // choosing a photo opens the crop step; the framed square is shrunk to 256 px here, then sent (the Mac re-makes it)
    $$("[data-copycode]").forEach((b) => { if (!b.dataset.wired) { b.dataset.wired = "1"; b.addEventListener("click", () => copy(b.dataset.copycode, b.dataset.copywhat || "Invite")); } });
    $$("[data-share]").forEach((b) => {  // the Mac's own Share menu: Messages, WhatsApp, Mail, AirDrop
      if (b.dataset.wired) return; b.dataset.wired = "1";
      b.addEventListener("click", async () => {
        const text = b.dataset.share, title = b.dataset.sharetitle || "Magpiary";
        let files = [];
        try {
          const bin = atob(b.dataset.sharepng || ""), bytes = new Uint8Array(bin.length);
          for (let n = 0; n < bin.length; n++) bytes[n] = bin.charCodeAt(n);
          if (bytes.length) files = [new File([bytes], "magpiary-invite.png", { type: "image/png" })];
        } catch (e) { files = []; }
        try {
          if (navigator.share) {
            const data = files.length && navigator.canShare && navigator.canShare({ files }) ? { title, text, files } : { title, text };
            await navigator.share(data);
            return;
          }
        } catch (e) { if (e && e.name === "AbortError") return; }
        copy(text, "Message");  // no Share menu in this browser: the message is copied instead
      });
    });
    const pick = $("#view #photopick"); if (!pick || pick.dataset.wired) return; pick.dataset.wired = "1";
    pick.addEventListener("change", () => {
      const file = pick.files && pick.files[0]; if (!file) return;
      const reader = new FileReader();  // a data URL: the page's rules allow no blob: pictures
      reader.onerror = () => toast("That photo could not be read.", { bad: true });
      reader.onload = () => cropPhoto(reader.result).then((url) => {
        pick.value = "";
        if (!url) return;
        const form = $("#photoform"); form.elements.photo.value = url; form.requestSubmit();
      });
      reader.readAsDataURL(file);
    });
  }
  function cropPhoto(src) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onerror = () => { toast("That photo could not be read.", { bad: true }); resolve(null); };
      img.onload = () => {
        const d = document.createElement("div");
        d.className = "dlg-wrap";
        d.innerHTML = `<div class="dlg cropdlg" role="dialog" aria-modal="true" aria-labelledby="croph"><h3 id="croph">Frame your photo</h3>` +
          `<p>Drag to move it, zoom to fit. What's inside the circle is what friends see.</p>` +
          `<div class="cropstage" tabindex="0" aria-label="Photo: drag or use the arrow keys to move it"><img alt=""><i class="cropring"></i></div>` +
          `<label class="cropzoom"><span>−</span><input type="range" min="1" max="4" step="0.01" value="1" aria-label="Zoom"><span>+</span></label>` +
          `<div class="row"><button type="button" class="btn" data-no>Cancel</button><button type="button" class="btn dark" data-yes>Use photo</button></div></div>`;
        document.body.append(d);
        const stage = $(".cropstage", d), pic = $("img", stage), zoom = $("input", d);
        pic.src = src; pic.style.width = `${img.naturalWidth}px`; pic.style.height = `${img.naturalHeight}px`;
        const S = stage.clientWidth, W = img.naturalWidth, H = img.naturalHeight, base = S / Math.min(W, H);
        let z = 1, x = (S - W * base) / 2, y = (S - H * base) / 2;
        const draw = () => {
          const s = base * z;
          x = Math.min(0, Math.max(S - W * s, x)); y = Math.min(0, Math.max(S - H * s, y));
          pic.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
        };
        const zoomTo = (nz, cx = S / 2, cy = S / 2) => {  // keep the point under (cx, cy) still
          nz = Math.min(4, Math.max(1, nz));
          const k = nz / z; x = cx - (cx - x) * k; y = cy - (cy - y) * k; z = nz; zoom.value = String(z); draw();
        };
        draw();
        let drag = null;
        stage.addEventListener("pointerdown", (ev) => { drag = { px: ev.clientX, py: ev.clientY, x, y }; stage.setPointerCapture(ev.pointerId); stage.classList.add("dragging"); });
        stage.addEventListener("pointermove", (ev) => { if (!drag) return; x = drag.x + ev.clientX - drag.px; y = drag.y + ev.clientY - drag.py; draw(); });
        const up = () => { drag = null; stage.classList.remove("dragging"); };
        stage.addEventListener("pointerup", up); stage.addEventListener("pointercancel", up);
        stage.addEventListener("wheel", (ev) => {
          ev.preventDefault();
          const r = stage.getBoundingClientRect();
          zoomTo(z * Math.exp(-ev.deltaY * .002), ev.clientX - r.left, ev.clientY - r.top);
        }, { passive: false });
        zoom.addEventListener("input", () => zoomTo(Number(zoom.value)));
        const done = (ok) => {
          document.removeEventListener("keydown", key, true);
          let url = null;
          if (ok) {
            const s = base * z, side = S / s, out = Math.min(256, Math.round(side));
            const c = document.createElement("canvas"); c.width = c.height = out;
            c.getContext("2d").drawImage(img, -x / s, -y / s, side, side, 0, 0, out, out);
            url = c.toDataURL("image/jpeg", .88);
          }
          const g = G(); if (g) g.to(d, { opacity: 0, duration: .15, onComplete: () => d.remove() }); else d.remove();
          resolve(url);
        };
        const key = (ev) => {
          if (ev.key === "Escape") { ev.stopPropagation(); done(false); return; }
          if (ev.key === "Enter" && ev.target.tagName !== "BUTTON") { ev.preventDefault(); done(true); return; }
          if (document.activeElement !== stage) return;
          const step = ev.shiftKey ? 30 : 8, moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
          if (moves[ev.key]) { ev.preventDefault(); x += moves[ev.key][0]; y += moves[ev.key][1]; draw(); }
          if (ev.key === "+" || ev.key === "=") zoomTo(z * 1.1);
          if (ev.key === "-") zoomTo(z / 1.1);
        };
        document.addEventListener("keydown", key, true);
        d.addEventListener("click", (ev) => { if (ev.target === d || ev.target.closest("[data-no]")) done(false); if (ev.target.closest("[data-yes]")) done(true); });
        stage.focus();
        G()?.from($(".dlg", d), { y: 14, opacity: 0, scale: .97, duration: .25, ease: "power3.out" });
      };
      img.src = src;
    });
  }
  // a board's column folds into one "About this board" bar on a phone; it stays as the person left it
  let sideOpen = false;
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-sidetoggle]");
    if (!b) return;
    sideOpen = !sideOpen; b.closest(".bside").classList.toggle("open", sideOpen); b.setAttribute("aria-expanded", String(sideOpen));
  });
  // one dialog turning into the next (Share → Invite): the frame stays, its content fades out, the frame grows to the new
  // height, the new content fades in
  function morphDialog(doc, to) {
    const old = $(".dlg-wrap .dlg"), next = $(".dlg-wrap .dlg", doc);
    if (!old || !next) return false;
    const wrap = old.closest(".dlg-wrap"), h0 = old.offsetHeight, g = G();
    const swap = () => {
      old.className = next.className;
      old.removeAttribute("aria-labelledby");
      if (next.getAttribute("aria-labelledby")) old.setAttribute("aria-labelledby", next.getAttribute("aria-labelledby"));
      old.innerHTML = next.innerHTML;
      wrap.dataset.close = $(".dlg-wrap", doc).dataset.close || wrap.dataset.close;
      history.pushState({ hub: 1 }, "", to.pathname + to.search + to.hash);
      old.focus({ preventScroll: true });
      $("form[data-auto]", old)?.requestSubmit();
    };
    if (!g) { swap(); return true; }
    old.style.height = h0 + "px"; old.style.overflow = "hidden";
    g.to([...old.children], { opacity: 0, y: -6, duration: .16, onComplete: () => {
      swap();
      old.style.height = "auto"; const h1 = old.offsetHeight; old.style.height = h0 + "px";
      g.to(old, { height: h1, duration: .38, ease: "power2.inOut", onComplete: () => { old.style.height = ""; old.style.overflow = ""; } });
      g.from([...old.children], { opacity: 0, y: 10, duration: .3, stagger: .05, delay: .1, clearProps: "all" });
    } });
    return true;
  }
  // New board: an idea fills the name; Join: the code is formatted as it is typed or pasted
  document.addEventListener("click", async (ev) => {
    const idea = ev.target.closest("[data-idea]");
    if (idea) { const i = $("input[name=name]", idea.closest("form")); i.value = idea.dataset.idea; i.focus({ preventScroll: true }); return; }
    const paste = ev.target.closest("[data-paste]"); if (!paste) return;
    const i = $("input[data-code]", paste.closest("form"));
    try { i.value = fmtCode(await navigator.clipboard.readText()); i.focus({ preventScroll: true }); } catch (e) { toast("Couldn't read the clipboard. Paste with ⌘V instead.", { bad: true }); }
  });
  const fmtCode = (t) => {
    const raw = t.toUpperCase().replace(/^MAG-?/, "").replace(/[^0-9A-Z]/g, "").slice(0, 12);
    return raw ? "MAG-" + (raw.match(/.{1,4}/g) || []).join("-") : "";
  };
  document.addEventListener("input", (ev) => { const i = ev.target.closest("input[data-code]"); if (i) i.value = fmtCode(i.value); });
  // a board's sort and filter change the cards in place: the choice is marked at once, the cards ripple and dim while the new
  // order comes, a thin line sweeps the toolbar, then the new cards are dealt in
  let boardSwapped = false;
  document.addEventListener("click", async (ev) => {
    const a = ev.target.closest(".bmain a.bopt, .bmain a.bfilter");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || !$("#view .bpage")) return;
    ev.preventDefault();
    const main = $("#view .bmain"), g = G();
    if (main.dataset.busy) return;
    main.dataset.busy = "1";
    if (a.classList.contains("bopt")) {
      $$(".bopt", main).forEach((o) => { o.classList.toggle("on", o === a); o.setAttribute("aria-checked", String(o === a)); });
      const b = $(".bchip b", main); if (b) b.textContent = $("span", a).textContent;
      a.closest("details")?.removeAttribute("open");
    } else a.classList.toggle("on");
    const cards = $$(".grid.mixes:not(.bmore .grid) .mx", main);
    const line = document.createElement("div"); line.className = "bswp"; line.innerHTML = "<i></i>";
    $(".bsorts", main)?.after(line);
    const sweep = g?.fromTo($("i", line), { xPercent: -100 }, { xPercent: 260, duration: 1.1, ease: "power1.inOut", repeat: -1 });
    const wave = g?.to(cards, { opacity: .35, scale: .975, duration: .3, ease: "power1.out", stagger: { each: .025, from: "start" } });
    try {
      const r = await fetch(a.href, { cache: "no-store" }); if (!r.ok) throw 0;
      const doc = new DOMParser().parseFromString(await r.text(), "text/html"), fresh = $("#view .bmain", doc);
      if (!fresh) throw 0;
      wave?.kill(); sweep?.kill();
      main.innerHTML = fresh.innerHTML;
      history.pushState({ hub: 1, bswap: 1 }, "", a.href); boardSwapped = true;
      dealIn($$(".grid.mixes:not(.bmore .grid) .mx", main));
      delete main.dataset.busy;
      initBMore();
    } catch (e) { location.href = a.href; }
  });
  // a colour for the board: the swatch rings, the page's glow turns to the new colour, and it is saved quietly; the panel
  // stays open with everything in it
  document.addEventListener("click", (ev) => {
    const sw = ev.target.closest(".bcol"); if (!sw) return;
    ev.preventDefault(); ev.stopPropagation();
    const form = sw.closest("form"), page = $("#view .bpage"); if (!page || sw.classList.contains("on")) return;
    $$(".bcol", form).forEach((x) => x.classList.toggle("on", x === sw));
    page.style.setProperty("--bc", sw.style.getPropertyValue("--c"));
    const g = G();
    if (g) {
      const ring = document.createElement("i"); ring.className = "bring"; sw.append(ring);
      g.fromTo(ring, { scale: .6, opacity: .9 }, { scale: 2.4, opacity: 0, duration: .7, ease: "power2.out", onComplete: () => ring.remove() });
      g.fromTo(sw, { scale: .7 }, { scale: 1, duration: .5, ease: "back.out(3)", clearProps: "transform" });
    }
    const data = new URLSearchParams(new FormData(form)); data.set("colour", sw.value);
    fetch(form.action, { method: "POST", body: data, headers: FORM }).then(() => toast("Colour changed")).catch(() => toast("Couldn't save the colour", { bad: true }));
  }, true);
  // a link that opens a dialog on a long board's page can take a moment: it shows it is working at once
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-opening]");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || a.dataset.busy) return;
    a.dataset.busy = "1"; a.classList.add("opening"); a.setAttribute("aria-busy", "true");
    const label = $("span:not(.ico):not(.ld)", a); if (label && a.dataset.opening) label.textContent = a.dataset.opening;
    const ico = $(".ico", a); if (ico) ico.hidden = true;
    a.prepend(loaderMark(a.classList.contains("sw") ? "morph" : ""));
  });
  // the board's first visit: step 1 → step 2 in one frame (fade with a small slide)
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-wl]"); if (!b) return;
    const box = b.closest(".wldlg"), to = $(`[data-step="${b.dataset.wl}"]`, box), from = $(".wlpane:not([data-off])", box);
    if (!to || !from || to === from) return;
    const g = G(), settle = () => { from.dataset.off = ""; delete to.dataset.off; if (g) g.set([from, to], { clearProps: "opacity,transform" }); };
    if (!g) { settle(); return; }
    g.killTweensOf([from, to]); delete to.dataset.off;
    g.to(from, { opacity: 0, x: -14, duration: .16, ease: "power1.in", overwrite: true });
    g.fromTo(to, { opacity: 0, x: 14 }, { opacity: 1, x: 0, duration: .28, delay: .1, ease: "power2.out", overwrite: true, onComplete: settle });
    clearTimeout(box._settle); box._settle = setTimeout(settle, 700);
  });
  // Delete board stays off until "I understand" is ticked
  document.addEventListener("change", (ev) => {
    const box = ev.target.closest('input[name="ack"]'); if (!box) return;
    const btn = $("button[type=submit]", box.closest("form")); if (btn) btn.disabled = !box.checked;
  });
  // Make a new board / Join a board: two tabs in one dialog. Both panes sit in one grid cell (the frame is as tall as the
  // taller one and never changes size); the one that is off is only invisible. Switching fades the text out and in.
  document.addEventListener("click", (ev) => {
    const tab = ev.target.closest(".mktab"); if (!tab) return;
    ev.preventDefault();
    const box = tab.closest(".mkdlg"), panes = $("[data-mkpanes]", box);
    const tabs = $$(".mktab", box), cur = tabs.find((t) => t.classList.contains("on"));
    const pane = (t) => $("#" + t.getAttribute("aria-controls"), box);
    const to = pane(tab), from = pane(cur);
    if (!to || to === from) return;
    const dir = tabs.indexOf(tab) > tabs.indexOf(cur) ? 1 : -1;
    tabs.forEach((t) => { t.classList.toggle("on", t === tab); t.setAttribute("aria-selected", String(t === tab)); });
    history.replaceState(history.state, "", tab.getAttribute("href"));
    const heading = $("#mkh", box); if (heading && tab.dataset.title) { heading.textContent = tab.dataset.title; $(".mkhead p", box).textContent = tab.dataset.sub; }
    const g = G();
    const settle = () => { from.dataset.off = ""; delete to.dataset.off; if (g) g.set([from, to], { clearProps: "opacity,transform" }); };
    $$(".mkpane", panes).forEach((p) => { if (p !== from && p !== to) p.dataset.off = ""; });
    if (!g) { settle(); $("input", to)?.focus({ preventScroll: true }); return; }
    g.killTweensOf([from, to]);  // a quick second click takes over cleanly
    delete to.dataset.off;
    g.to(from, { opacity: 0, x: -14 * dir, duration: .16, ease: "power1.in", overwrite: true });
    g.fromTo(to, { opacity: 0, x: 14 * dir }, { opacity: 1, x: 0, duration: .28, delay: .1, ease: "power2.out", overwrite: true,
      onComplete: settle });
    clearTimeout(box._settle);
    box._settle = setTimeout(settle, 700);  // settled even where animation frames are paused
    $("input", to)?.focus({ preventScroll: true });
  });
  // entering a board: the folder lifts and its cards pop up a little, the others dim, then the board page rises in
  let entering = false;
  function enterFolder(a) {
    entering = true;
    return new Promise((done) => {
      const g = G(), rest = $$("#view .piles.boards > .pile").filter((x) => x !== a), tpl = $("#bskel");
      g.to(rest, { opacity: .3, duration: .2 });
      g.to($$(".peek > div", a), { y: "-14%", duration: .22, stagger: .02, ease: "power2.out" });
      g.to(a, { scale: 1.04, y: -5, duration: .22, ease: "power2.out", onComplete: () => {
        done();
        if (!tpl) return;
        // the board's frame (name, sticker, grey cards) takes the place of the folders until its page is ready
        const node = tpl.content.firstElementChild.cloneNode(true), b = $(".flap b", a).cloneNode(true), stk = $(".stk", b);
        node.style.setProperty("--bc", a.style.getPropertyValue("--pc"));
        if (stk) { stk.className = "stk big"; $("[data-skel-sticker]", node).append(stk); }
        $("[data-skel-name]", node).textContent = b.textContent.trim();
        const view = $("#view");
        g.to(view, { opacity: 0, duration: .16, onComplete: () => { view.replaceChildren(node); scrollTo({ top: 0, behavior: "instant" }); g.to(view, { opacity: 1, duration: .22 }); } });
      } });
    });
  }
  function initEnter() {
    let flag = false;
    try { flag = sessionStorage.getItem("mag-enter") === "1"; sessionStorage.removeItem("mag-enter"); } catch (e) { /* fine */ }
    if (!entering && !flag) { root.classList.remove("entering"); return; }
    entering = false;
    const g = G(), lay = $("#view .blay");
    if (g && lay) {
      const cards = $$(".mx", lay), side = $$(".bside > .bsidein > *, .bsorts > *", lay);
      g.set([...cards, ...side], { opacity: 0 });
      root.classList.remove("entering");
      dealIn(cards);
      g.fromTo(side, { x: 18, opacity: 0 }, { x: 0, opacity: 1, duration: .6, stagger: .06, delay: .15, ease: "power3.out", clearProps: "transform,opacity" });
    } else root.classList.remove("entering");
  }
  // a board brought back: its folder grows into its place, the others make room
  function initBack() {
    const el = $("#view [data-back]"); if (!el || el.dataset.done) return;
    el.dataset.done = "1";
    const name = el.dataset.name, rest = $$("#view .piles.boards > .pile").filter((x) => x !== el), flip = F(), g = G();
    history.replaceState(history.state, "", "/?view=boards");
    toast(`“${name}” is back`);
    if (!g) return;
    el.style.display = "none";
    const state = flip ? flip.getState(rest) : null;
    el.style.display = "";
    if (state) flip.from(state, { duration: .5, ease: "power2.inOut" });
    g.fromTo(el, { scale: .7, opacity: 0, rotate: 5, y: 14 }, { scale: 1, opacity: 1, rotate: 0, y: 0, duration: .65, delay: .15, ease: "back.out(1.5)", clearProps: "transform,opacity" });
  }
  // a board just deleted: its folder shrinks away, the others close the gap, and a toast keeps Undo for a few seconds
  let goneDelay = .3;
  function initGone() {
    const ghost = $("#view .bgone"); if (!ghost || ghost.dataset.done) return;
    ghost.dataset.done = "1";
    const id = ghost.dataset.gone, name = ghost.dataset.name;
    const rest = $$("#view .piles.boards > .pile").filter((x) => x !== ghost), flip = F();
    const state = flip ? flip.getState(rest) : null;
    const finish = () => {
      ghost.remove();
      if (state) flip.from(state, { duration: .5, ease: "power2.inOut" });
      history.replaceState(history.state, "", "/?view=boards");
      toast(`“${name}” deleted. You can restore it for 30 days.`, { ms: 8000,
        undo: () => post("/hub/boards/restore", { board: id, next: "/?view=boards" }).then(() => refresh(true)) });
    };
    const g = G();
    if (!g) return finish();
    g.to(ghost, { delay: goneDelay, scale: .72, opacity: 0, rotate: -5, y: 14, duration: .6, ease: "power2.in", onComplete: finish });
  }
  function initSide() {
    const side = $("#view .bside");
    if (!side) return;
    side.classList.toggle("open", sideOpen);
    $("[data-sidetoggle]", side)?.setAttribute("aria-expanded", String(sideOpen));
  }

  function initView(quiet) {
    placeAll(true); initSide(); initAdd(); initSynced(); initGone(); initBack(); initEnter(); initBMore();
    $("#view form[data-auto]")?.requestSubmit();  // the invite code is made as the invite dialog opens
    initTiles(); initBanners(); initMore(); initMenus(); initProvider(); initQr(); initHelpSearch(); initDigest(); initProfile();
    if (page() === "wall") heroShrink();
    if (!quiet) kIndex = -1;
    $$("#view [data-standalone]").forEach(wireCard);
    if (document.body.classList.contains("selecting")) {
      $$("#view .tile[data-id]").forEach((t) => t.classList.toggle("sel", selected.has(t.dataset.id)));
      $("#selbtn")?.classList.add("on");
      drawBar();
    }
  }

  // ---- a post opened as its own page -----------------------------------------------------------------------------------------------
  const standalone = $("[data-standalone]");
  if (standalone) {
    if (!standalone.closest("#view")) wireCard(standalone);  // inside #view, initView has wired it already
    const pp = $(".postpage");
    if (pp) {
      const frm = pp.dataset.from || "";
      // the breadcrumb link for the list you came from is the browser's Back: same scroll, same filters
      const parents = [$("[data-pgback]", pp), [...$$(".crumbs a", pp)].pop()].filter(Boolean);
      parents.forEach((parent) => {
        if (parent.getAttribute("href") === (frm || "/") && document.referrer.startsWith(location.origin) && history.length > 1) {
          parent.addEventListener("click", (ev) => { ev.preventDefault(); if (leaving) return; leaving = true; try { sessionStorage.setItem("mag-slide", "right"); } catch (e) { /* fine */ } history.back(); });
        }
      });
      $$("a[data-pagenav]", pp).forEach((a) => a.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
        ev.preventDefault();
        // replace, not push: stepping through posts adds no history, so Back still goes to the list you started from
        leave(a.href, a.getAttribute("aria-label") === "Next post" ? "left" : "right", true);
      }));
      document.addEventListener("keydown", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.altKey || (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight")) return;
        const t = ev.target; if (t && ((t.closest?.("input, textarea, select, video, [contenteditable]") && !(t.matches?.(".askp textarea") && !t.value)) || t.tagName === "BUTTON" && t.closest(".pvbar"))) return;
        $(`a[data-pagenav][aria-label="${ev.key === "ArrowRight" ? "Next" : "Previous"} post"]`, pp)?.click();
      });
      // a Ask Magpiary cite that named a moment: jump there once the page is up
      try { const t = sessionStorage.getItem("mag-seek"); if (t) { sessionStorage.removeItem("mag-seek"); seekAfterOpen = t; } } catch (e) { /* fine */ }
    }
  }
  // arriving by a page change (and coming back from the browser's memory): fade the page in
  arrive();
  addEventListener("pageshow", (ev) => {
    if (!ev.persisted) return;
    const view = $("#view"); leaving = false;
    G()?.set(view, { clearProps: "transform,opacity" });
    root.classList.remove("slide-in", "slidefx");
    try { if (sessionStorage.getItem("mag-slide")) arrive(); } catch (e) { /* fine */ }
  });
  history.replaceState({ ...(history.state || {}), hub: 1 }, "", location.href);

  // ---- first run: listening for the first share ------------------------------------------------------------------
  // The Welcome guide ticks itself: when the Mac sees a step happen (/welcome.json changes), the open page reloads, unless something is being typed.
  const wel = $(".wel[data-wsig]");
  if (wel) {
    setInterval(async () => {
      if (document.hidden) return;
      const typing = document.activeElement?.matches?.("input:not([type=hidden]), textarea") && document.activeElement.value;
      if (typing) return;
      try { const d = await (await fetch("/welcome.json", { cache: "no-store" })).json(); if (d.sig && d.sig !== wel.dataset.wsig) location.reload(); } catch (e) { /* again */ }
    }, 2500);
    // the right column starts where the first card on the left starts (not on Hello, whose tile stays centred)
    $$(".wel .w-body").forEach((b) => {
      if (b.classList.contains("al") || b.children.length !== 2 || $(".priv", b)) return;
      const [L, R] = b.children, head = document.createElement("div"), main = document.createElement("div");
      head.className = "head"; main.className = "main";
      let inHead = true;
      [...L.children].forEach((c) => { if (inHead && !c.matches(".w-kick,.w-h,.w-p")) inHead = false; (inHead ? head : main).append(c); });
      R.classList.add("side"); b.classList.add("al"); b.replaceChildren(head, main, R);
    });
    // the provider picker (our own list) and the folded key guide
    const btn = $("#provbtn");
    if (btn) {
      const list = $("#provlist"), opts = $$("[role=option]", list), input = $("input[name=provider]", btn.closest(".dd"));
      let cur = Math.max(0, opts.findIndex((o) => o.dataset.v === input.value));
      const mark = (i) => { cur = (i + opts.length) % opts.length; opts.forEach((o, n) => o.classList.toggle("act", n === cur)); list.setAttribute("aria-activedescendant", opts[cur].id); opts[cur].scrollIntoView({ block: "nearest" }); };
      const open = () => { list.hidden = false; btn.setAttribute("aria-expanded", "true"); mark(cur); list.focus(); };
      const close = (back) => { list.hidden = true; btn.setAttribute("aria-expanded", "false"); list.removeAttribute("aria-activedescendant"); if (back) btn.focus(); };
      const pick = (i) => {
        input.value = opts[i].dataset.v;
        btn.firstElementChild.replaceChildren(...[$(".plogo", opts[i])?.cloneNode(true), Object.assign(document.createElement("span"), { textContent: $("b", opts[i]).textContent })].filter(Boolean));
        opts.forEach((o) => o.setAttribute("aria-selected", String(o === opts[i])));
        $$(".guide2").forEach((g) => { g.hidden = g.dataset.provider !== input.value; });
        close(true);
      };
      btn.addEventListener("click", () => (list.hidden ? open() : close(true)));
      btn.addEventListener("keydown", (ev) => { if (["ArrowDown", "ArrowUp", "Enter", " "].includes(ev.key)) { ev.preventDefault(); open(); } });
      list.addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowDown") { ev.preventDefault(); mark(cur + 1); } else if (ev.key === "ArrowUp") { ev.preventDefault(); mark(cur - 1); }
        else if (ev.key === "Home") { ev.preventDefault(); mark(0); } else if (ev.key === "End") { ev.preventDefault(); mark(opts.length - 1); }
        else if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(cur); } else if (ev.key === "Escape") { ev.preventDefault(); close(true); } else if (ev.key === "Tab") close(false);
      });
      list.addEventListener("click", (ev) => { const o = ev.target.closest("[role=option]"); if (o) pick(opts.indexOf(o)); });
      list.addEventListener("mousemove", (ev) => { const o = ev.target.closest("[role=option]"); if (o) mark(opts.indexOf(o)); });
      document.addEventListener("pointerdown", (ev) => { if (!list.hidden && !ev.target.closest("#prov")) close(false); }, true);
    }
    const hb = $("[data-helpbtn]");
    if (hb) hb.addEventListener("click", () => { const open = hb.getAttribute("aria-expanded") !== "true"; hb.setAttribute("aria-expanded", String(open)); $("#guidewrap").hidden = !open; });
  }

  // ---- first arrival ------------------------------------------------------------------------------------------------------------------
  topHeight();
  initView();
  requestAnimationFrame(() => placeAll(true));
  document.fonts?.ready.then(() => { placeAll(true); topHeight(); });
  addEventListener("resize", () => { placeAll(true); topHeight(); });
  const g = G();
  let arrived = false;
  try { arrived = !!sessionStorage.getItem("mag-arrived"); sessionStorage.setItem("mag-arrived", "1"); } catch (e) { /* fine */ }
  if (g && !arrived && ["wall", "search", "shelf", "pile", "related"].includes(page())) {
    g.from($$("#view .tile, #view .pile").slice(0, 36), { opacity: 0, y: 16, duration: .45, ease: "power2.out", stagger: .025, clearProps: "opacity,transform" });
  }
  if (g && page() === "welcome") g.from($$(".w-body > div > *"), { opacity: 0, y: 18, duration: .5, ease: "power3.out", stagger: .06, clearProps: "opacity,transform" });
  window.__hub = { go, setSize, openNest, closeNest, openSearch, closeSearch, showSavedNote }; // for the browser checks
})();
