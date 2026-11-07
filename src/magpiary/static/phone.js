/* Phone bar: Search opens the big search, More opens a small menu. Event delegation, so it survives page changes. */
(() => {
  if (window.__phoneBar) return;  // the page can load this file again when it swaps pages
  window.__phoneBar = true;
  const more = () => document.getElementById("pmore");
  const btn = () => document.querySelector("[data-pbar-more]");
  const close = () => { const m = more(); if (m) m.hidden = true; const b = btn(); if (b) b.setAttribute("aria-expanded", "false"); };
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!(t instanceof Element)) return;
    if (t.closest("[data-pbar-search]")) {
      close();
      // the bar's own search box is hidden on a phone, so open the big full-screen search, on any page
      const form = document.getElementById("searchform");
      if (form) form.click(); else location.assign("/");
    } else if (t.closest("[data-pbar-more]")) {
      const m = more(); if (!m) return;
      m.hidden = !m.hidden;
      btn().setAttribute("aria-expanded", String(!m.hidden));
    } else if (!t.closest("#pmore")) { close(); }
    else { close(); }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") close(); });
})();

/* The bar shrinks while you scroll down and grows back when you scroll up (or stop near the top). */
(() => {
  if (window.__phoneBarScroll) return;
  window.__phoneBarScroll = true;
  let last = window.scrollY, ticking = false;
  const update = () => {
    ticking = false;
    const y = window.scrollY, delta = y - last;
    if (Math.abs(delta) < 8) return;           // ignore jitter
    const open = document.querySelector("[data-pbar-more][aria-expanded=true]");
    document.body.classList.toggle("pbar-small", delta > 0 && y > 80 && !open);
    last = y;
  };
  window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
})();

/* The red dot on the Nest icon follows the Nest badge in the top bar (hub.js keeps that one up to date). */
(() => {
  if (window.__phoneBarDot) return;
  window.__phoneBarDot = true;
  const sync = () => {
    const badge = document.getElementById("nbadge"), dot = document.querySelector("[data-pbar-dot]");
    if (dot) dot.hidden = !badge || badge.hidden;
  };
  document.addEventListener("DOMContentLoaded", sync);
  setInterval(sync, 2000);
  sync();
})();

/* Which place is lit, and the oval that slides to it. The page swaps its content without reloading, so the bar,
   which lives outside the content, has to follow the address by itself. */
(() => {
  if (window.__phoneBarActive) return;
  window.__phoneBarActive = true;
  const which = () => {
    const open = (id) => { const e = document.getElementById(id); return !!e && !e.hidden && (id !== "nestsheet" || e.classList.contains("open")); };
    if (open("nestsheet")) return "nest";           // the Nest and Add open over the page, so the address does not change
    if (open("addm")) return "add";
    if (document.body.classList.contains("helpopen")) return "more";
    const p = location.pathname, q = new URLSearchParams(location.search);
    if (p === "/") {
      if (q.get("q")) return "search";
      const shelf = q.get("shelf");
      return shelf === "archive" || shelf === "trash" ? "more" : "library";
    }
    if (p === "/nest" || p === "/queue") return "nest";
    if (p === "/add") return "add";
    if (p === "/digest" || p.startsWith("/digest/") || p === "/map" || p === "/help") return "more";
    return "";
  };
  const apply = () => {
    const bar = document.getElementById("pbar"), slider = document.getElementById("pslider");
    if (!bar || !slider) return;
    const now = which();
    let target = null;
    bar.querySelectorAll(".pb").forEach((b) => {
      const on = b.dataset.pb === now;
      b.classList.toggle("on", on);
      if (on) { b.setAttribute("aria-current", "page"); target = b; } else b.removeAttribute("aria-current");
    });
    if (target && target.offsetWidth) {
      if (!slider.classList.contains("show")) {   // first time on this page: start in place, do not slide in from the left
        slider.style.transition = "none";
        requestAnimationFrame(() => requestAnimationFrame(() => { slider.style.transition = ""; }));
      }
      slider.style.setProperty("--px", target.offsetLeft + "px");
      slider.style.setProperty("--pw", target.offsetWidth + "px");
      slider.classList.add("show");
    } else slider.classList.remove("show");
  };
  for (const m of ["pushState", "replaceState"]) {
    const orig = history[m];
    history[m] = function () { const r = orig.apply(this, arguments); setTimeout(apply, 0); return r; };
  }
  window.addEventListener("popstate", () => setTimeout(apply, 0));
  window.addEventListener("resize", apply);
  document.addEventListener("click", () => setTimeout(apply, 60));
  document.addEventListener("DOMContentLoaded", apply);
  setInterval(apply, 1500);  // catches any page change that did not go through the history calls
  apply();
})();

/* On a phone the Nest opens as its own page: the drop-down sheet hangs from a top-bar button that is not shown here. */
document.addEventListener("click", (ev) => {
  const a = ev.target instanceof Element ? ev.target.closest('#pbar a[data-pb="nest"]') : null;
  if (!a || ev.metaKey || ev.ctrlKey) return;
  ev.preventDefault(); ev.stopImmediatePropagation();
  if (location.pathname !== "/nest") location.assign("/nest");
}, true);

/* Pull to refresh on the library and on a post page: at the top of the page, pull down and let go. Phone-sized screens only. */
(() => {
  if (window.__phonePull) return;
  window.__phonePull = true;
  const phone = window.matchMedia("(max-width: 760px)");
  const THRESHOLD = 72, MAX = 120;
  let el = null, startY = 0, startX = 0, pulling = false, pull = 0, busy = false;
  const make = () => {
    el = document.createElement("div");
    el.className = "ptr"; el.setAttribute("aria-hidden", "true");
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/></svg>';
    document.body.appendChild(el);
    return el;
  };
  const show = (px) => {
    const e = el || make();
    e.style.setProperty("--pull", px + "px");
    e.style.setProperty("--prog", Math.min(px / THRESHOLD, 1));
    e.classList.toggle("ready", px >= THRESHOLD);
  };
  const reset = () => { if (!el) return; el.classList.remove("pulling", "ready"); el.style.setProperty("--pull", "0px"); el.style.setProperty("--prog", 0); };
  const allowed = (t) => phone.matches && (location.pathname === "/" || /^\/item\/\d+/.test(location.pathname)) && !busy && !document.body.classList.contains("lock")
    && !document.body.classList.contains("askopen") && !(t instanceof Element && t.closest("input, textarea, select, [contenteditable], .spanel, .sover, .modal, .nestsheet, .pmore"))
    && !document.querySelector("#sover:not([hidden])");
  document.addEventListener("touchstart", (ev) => {
    pulling = false; pull = 0;
    if (ev.touches.length !== 1 || window.scrollY > 0 || !allowed(ev.target)) return;
    startY = ev.touches[0].clientY; startX = ev.touches[0].clientX; pulling = true;
  }, { passive: true });
  document.addEventListener("touchmove", (ev) => {
    if (!pulling) return;
    const dy = ev.touches[0].clientY - startY, dx = ev.touches[0].clientX - startX;
    if (dy <= 0 || Math.abs(dx) > dy || window.scrollY > 0) { if (pull) { pull = 0; reset(); } if (dy <= 0) pulling = false; return; }
    pull = Math.min(MAX, dy * 0.5);  // it gets harder the further you pull
    (el || make()).classList.add("pulling");
    show(pull);
  }, { passive: true });
  const end = () => {
    if (!pulling) return;
    pulling = false;
    if (pull >= THRESHOLD) {
      busy = true;
      el.classList.remove("pulling"); el.classList.add("loading");
      el.style.setProperty("--pull", THRESHOLD * 0.8 + "px"); el.style.setProperty("--prog", 1);
      setTimeout(() => location.reload(), 150);
    } else reset();
    pull = 0;
  };
  document.addEventListener("touchend", end, { passive: true });
  document.addEventListener("touchcancel", () => { pulling = false; pull = 0; reset(); }, { passive: true });
})();

/* Tiles are always Medium on a phone (owner, 6 Nov): the size button is gone, and a size saved on the Mac does not apply here.
   The page swaps its own attributes when it changes view, so the size is put back whenever it changes. */
(() => {
  if (window.__phoneSize) return;
  window.__phoneSize = true;
  const root = document.documentElement, phone = window.matchMedia("(max-width: 760px)");
  const fix = () => { if (phone.matches && root.dataset.size !== "m") root.dataset.size = "m"; };
  fix();
  new MutationObserver(fix).observe(root, { attributes: true, attributeFilter: ["data-size"] });
  phone.addEventListener?.("change", fix);
})();

/* Soft cross-fade between the pages the bottom bar leads to (owner, 6 Nov): the old page fades out, the new one fades in
   (phone.css does the fading in on every load). Library from another page, Nest, and the pages under More. */
document.addEventListener("click", (ev) => {
  if (!window.matchMedia("(max-width: 760px)").matches || ev.defaultPrevented || ev.button || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
  const a = ev.target instanceof Element ? ev.target.closest('#pbar a[data-pb="nest"], #pbar a[data-pb="library"], #pmore a') : null;
  if (!a) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin || url.pathname + url.search === location.pathname + location.search) return;
  if (a.matches('[data-pb="library"]') && location.pathname === "/") return;  // inside the library the page's own switching handles it
  ev.preventDefault(); ev.stopImmediatePropagation();
  const root = document.documentElement;
  root.classList.add("pfade-out");
  setTimeout(() => location.assign(url.href), window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 170);
}, true);
window.addEventListener("pageshow", () => document.documentElement.classList.remove("pfade-out"));  // back button from the bfcache

/* Swipe left/right on the library moves between Everything, Piles and Boards. The page does not move or rearrange: it fades out,
   the view changes while it is hidden, and it fades in (owner, 6 Nov). */
(() => {
  if (window.__phoneSwipe) return;
  window.__phoneSwipe = true;
  const root = document.documentElement, phone = window.matchMedia("(max-width: 760px)");
  const tabs = () => [...document.querySelectorAll("#wallctl #views a")];
  const blocked = (t) => {
    if (!(t instanceof Element)) return true;
    if (t.closest("input, textarea, select, video, .fmenu, .spanel, .sover, .modal, .nestsheet, .selbar, [contenteditable]")) return true;
    for (let el = t; el && el !== document.body; el = el.parentElement) {   // something that scrolls sideways keeps its swipe
      const o = getComputedStyle(el).overflowX;
      if ((o === "auto" || o === "scroll") && el.scrollWidth > el.clientWidth + 2) return true;
    }
    return document.body.classList.contains("lock") || document.body.classList.contains("askopen") || document.body.classList.contains("selecting");
  };
  let sx = 0, sy = 0, dx = 0, mode = "", busy = false, t0 = 0;
  document.addEventListener("touchstart", (ev) => {
    mode = ""; dx = 0;
    if (busy || !phone.matches || location.pathname !== "/" || ev.touches.length !== 1 || tabs().length < 2 || blocked(ev.target)) return;
    sx = ev.touches[0].clientX; sy = ev.touches[0].clientY; t0 = performance.now(); mode = "wait";
  }, { passive: true });
  document.addEventListener("touchmove", (ev) => {
    if (!mode) return;
    const x = ev.touches[0].clientX - sx, y = ev.touches[0].clientY - sy;
    if (mode === "wait") {
      if (Math.abs(y) > 14 && Math.abs(y) > Math.abs(x)) { mode = ""; return; }   // it is a scroll
      if (Math.abs(x) < 12 || Math.abs(x) < Math.abs(y) * 1.4) return;
      mode = "drag";
    }
    dx = x;
  }, { passive: true });
  const end = () => {
    if (mode !== "drag") { mode = ""; return; }
    mode = "";
    const i = tabs().findIndex((a) => a.classList.contains("on")), j = i + (dx < 0 ? 1 : -1);
    const fast = Math.abs(dx) / Math.max(performance.now() - t0, 1) > 0.5;
    if (i < 0 || j < 0 || j >= tabs().length || (Math.abs(dx) < 70 && !fast)) return;   // not far enough, or nothing further that way
    busy = true;
    window.__phoneHold = performance.now() + 3000;   // the top bar stays as it is while the view changes
    root.classList.add("pswipe");                    // phone.css: the content fades out (and stays hidden)
    setTimeout(() => {
      const view = document.getElementById("view");
      let quiet = null, finished = false;
      const finish = () => { if (finished) return; finished = true; mo.disconnect(); clearTimeout(quiet); root.classList.remove("pswipe"); setTimeout(() => { busy = false; }, 260); };
      const mo = new MutationObserver(() => { clearTimeout(quiet); quiet = setTimeout(finish, 320); });   // wait until the page has stopped changing
      if (view) mo.observe(view, { childList: true, subtree: true });
      tabs()[j].click();
      quiet = setTimeout(finish, 700);
      setTimeout(finish, 1500);                      // never stay hidden
    }, 170);
  };
  document.addEventListener("touchend", end, { passive: true });
  document.addEventListener("touchcancel", () => { mode = ""; }, { passive: true });
})();

/* Changing the view from the pill must not bring the top bar back: scrolling jumps while the page changes are not "scroll up". */
document.addEventListener("click", (ev) => {
  if (ev.target instanceof Element && ev.target.closest("#wallctl #views a")) window.__phoneHold = performance.now() + 3000;
}, true);

/* The underline / oval under the tabs is measured again whenever the tabs change size or the active one changes, so it never
   keeps the wrong width from the other state (top row vs floating pill). */
(() => {
  if (window.__phoneLine) return;
  window.__phoneLine = true;
  let timer = null;
  const fix = () => {
    const views = document.getElementById("views"), on = views && views.querySelector("a.on"), line = views && views.querySelector(".vline");
    if (!on || !line || !window.gsap) return;
    const r = on.getBoundingClientRect(), b = views.getBoundingClientRect();
    if (!r.width) return;
    window.gsap.set(line, { x: r.left - b.left + views.scrollLeft, width: r.width, opacity: 1 });
  };
  const later = () => { clearTimeout(timer); timer = setTimeout(fix, 520); };   // after hub.js has finished its own slide
  new MutationObserver(later).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  document.addEventListener("click", (ev) => { if (ev.target instanceof Element && ev.target.closest("#views a")) later(); }, true);
  window.addEventListener("resize", later);
  window.addEventListener("scroll", later, { passive: true });
})();

/* Post view tab strip: mark which side still has more tabs, so the CSS can fade that edge. */
(function () {
  "use strict";
  function mark(nav) {
    const max = nav.scrollWidth - nav.clientWidth;
    nav.classList.toggle("pmoreR", max > 4 && nav.scrollLeft < max - 4);
    nav.classList.toggle("pmoreL", max > 4 && nav.scrollLeft > 4);
  }
  function scan() {
    document.querySelectorAll(".tabs.pvtabs").forEach(function (nav) {
      if (!nav.__pmore) { nav.__pmore = true; nav.addEventListener("scroll", function () { mark(nav); }, { passive: true }); }
      mark(nav);
    });
  }
  addEventListener("resize", scan);
  addEventListener("load", scan);
  new MutationObserver(function () { clearTimeout(scan.t); scan.t = setTimeout(scan, 120); }).observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();

/* Post view: swipe left/right goes to the next/previous post, and two faint arrows on the media do the same by tap.
   It reuses the page's own Previous/Next links (hub.js slides the page), so history and "n of m" behave as on the Mac.
   Not started from: the tab strip, inputs, anything that scrolls sideways, or the bottom of the video (its controls). */
(function () {
  "use strict";
  const ARROW = (d) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  const link = (label) => document.querySelector('.postpage a[data-pagenav][aria-label="' + label + '"]');
  function edges() {
    const stage = document.querySelector(".cardm.pagemode .stage");
    if (!stage || stage.querySelector(".pedge")) return;
    [["Previous post", "pl", "M15 5l-7 7 7 7"], ["Next post", "pr", "M9 5l7 7-7 7"]].forEach(function (s) {
      if (!link(s[0])) return;
      const b = document.createElement("button");
      b.type = "button"; b.className = "pedge " + s[1]; b.setAttribute("aria-label", s[0]); b.innerHTML = ARROW(s[2]);
      b.addEventListener("click", function () { const a = link(s[0]); if (a) a.click(); });
      stage.appendChild(b);
    });
  }
  function sideways(el) {
    for (; el && el !== document.body; el = el.parentElement) {
      if (el.scrollWidth > el.clientWidth + 2 && /(auto|scroll)/.test(getComputedStyle(el).overflowX)) return true;
    }
    return false;
  }
  let t0 = null;
  document.addEventListener("touchstart", function (ev) {
    t0 = null;
    if (innerWidth > 760 || ev.touches.length !== 1 || !document.querySelector(".postpage")) return;
    const el = ev.target, p = ev.touches[0];
    if (el.closest("input, textarea, select, .pvtabs, .pedge, .pop, .chooser, .sover, .modal")) return;
    if (el.tagName === "VIDEO" || el.closest(".stage")) {
      const v = el.closest(".stage") && el.closest(".stage").getBoundingClientRect();
      if (v && p.clientY > v.bottom - 64) return;  // the player's own controls
    }
    if (sideways(el)) return;
    t0 = { x: p.clientX, y: p.clientY, t: performance.now() };
  }, { passive: true });
  document.addEventListener("touchend", function (ev) {
    if (!t0) return;
    const p = ev.changedTouches[0], dx = p.clientX - t0.x, dy = p.clientY - t0.y, dt = performance.now() - t0.t;
    t0 = null;
    if (Math.abs(dx) < 64 || Math.abs(dx) < Math.abs(dy) * 1.8 || dt > 700) return;
    const a = link(dx > 0 ? "Previous post" : "Next post");
    if (a) a.click();
  }, { passive: true });
  new MutationObserver(function () { clearTimeout(edges.t); edges.t = setTimeout(edges, 80); }).observe(document.documentElement, { childList: true, subtree: true });
  edges();
})();

/* Post view Back: one tap must leave the post. Back normally uses the browser's history (same scroll, same filters), but when the
   entry before this one is another copy of a post page (a reload, a deep link, posts stepped through), the first tap only lands on
   a post again and a second tap is needed. So a tap on Back leaves a short note; a post page that opens while the note is fresh
   goes on to the list the Back button points at. List pages clear the note. */
(function () {
  "use strict";
  const KEY = "mag-backing";
  const read = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const clear = () => { try { sessionStorage.removeItem(KEY); } catch (e) { /* fine */ } };
  document.addEventListener("click", function (ev) {
    const b = ev.target instanceof Element ? ev.target.closest(".postpage [data-pgback]") : null;
    if (!b || innerWidth > 760) return;
    try { sessionStorage.setItem(KEY, JSON.stringify({ href: b.getAttribute("href") || "/", t: Date.now() })); } catch (e) { /* fine */ }
  }, true);
  function check() {
    const n = read();
    if (!n) return;
    if (!/^\/item\/\d+/.test(location.pathname)) { clear(); return; }
    clear();
    if (Date.now() - n.t < 4000 && innerWidth <= 760 && /^\/(\?|$|pile\/|board\/)/.test(n.href)) location.replace(n.href);
  }
  addEventListener("pageshow", check);
  check();
})();

/* Post tab strip: while it is stuck near the top, a full-width layer in the page's top colour sits behind it and runs off the left,
   right and top edges. It is not there when the tabs are in their place in the page. */
(function () {
  "use strict";
  let bg = null, queued = false;
  function update() {
    queued = false;
    const nav = document.querySelector(".cardm.pagemode .tabs.pvtabs");
    if (!nav || innerWidth > 760) { if (bg) bg.classList.remove("show"); return; }
    if (!bg) { bg = document.createElement("div"); bg.className = "ptabsbg"; bg.setAttribute("aria-hidden", "true"); document.body.appendChild(bg); }
    const r = nav.getBoundingClientRect(), stick = parseFloat(getComputedStyle(nav).top) || 0;
    const stuck = r.top <= stick + 0.5 && r.bottom > 0 && window.scrollY > 0;
    bg.style.height = Math.max(0, r.bottom) + "px";
    bg.classList.toggle("show", stuck);
  }
  const queue = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  addEventListener("pageshow", queue);
  new MutationObserver(queue).observe(document.documentElement, { childList: true, subtree: true });
  update();
})();
