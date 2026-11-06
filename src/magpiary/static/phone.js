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

/* Pull to refresh on the library: at the top of the page, pull down and let go. Phone-sized screens only. */
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
  const allowed = (t) => phone.matches && location.pathname === "/" && !busy && !document.body.classList.contains("lock")
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

/* Swipe left/right on the library moves between Everything, Piles and Boards; the page follows your finger. */
(() => {
  if (window.__phoneSwipe) return;
  window.__phoneSwipe = true;
  const phone = window.matchMedia("(max-width: 760px)");
  const tabs = () => [...document.querySelectorAll("#wallctl #views a")];
  const content = () => { const v = document.getElementById("view"); return v ? [...v.children].filter((e) => e.id !== "wallctl" && !e.classList.contains("lhero")) : []; };
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
  const move = (x, o) => content().forEach((e) => { e.style.transition = "none"; e.style.transform = x ? `translateX(${x}px)` : ""; e.style.opacity = o === undefined ? "" : String(o); });
  const clear = () => content().forEach((e) => { e.style.transition = ""; e.style.transform = ""; e.style.opacity = ""; });
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
      const i = tabs().findIndex((a) => a.classList.contains("on"));
      const j = i + (x < 0 ? 1 : -1);
      if (i < 0 || j < 0 || j >= tabs().length) { mode = ""; return; }            // nothing further in that direction
      mode = "drag";
    }
    dx = x;
    move(dx * 0.9, 1 - Math.min(Math.abs(dx) / 420, 0.6));
  }, { passive: true });
  const end = () => {
    if (mode !== "drag") { mode = ""; return; }
    mode = "";
    const i = tabs().findIndex((a) => a.classList.contains("on")), dir = dx < 0 ? 1 : -1, j = i + dir;
    const fast = Math.abs(dx) / Math.max(performance.now() - t0, 1) > 0.5;
    if (j < 0 || j >= tabs().length || (Math.abs(dx) < 70 && !fast)) {   // not far enough: spring back
      content().forEach((e) => { e.style.transition = "transform .25s cubic-bezier(.2,.8,.2,1), opacity .25s"; e.style.transform = ""; e.style.opacity = ""; });
      setTimeout(clear, 280); return;
    }
    busy = true;
    content().forEach((e) => { e.style.transition = "transform .18s ease-in, opacity .18s"; e.style.transform = `translateX(${dir * -110}%)`; e.style.opacity = "0"; });
    setTimeout(() => {
      const view = document.getElementById("view");
      let done = false;
      const arrive = () => {
        if (done) return; done = true; mo.disconnect(); busy = false;
        content().forEach((e) => e.animate([{ transform: `translateX(${dir * 45}%)`, opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" }));
        window.scrollTo(0, Math.min(scrollY, 0));
      };
      const mo = new MutationObserver(() => setTimeout(arrive, 30));
      if (view) mo.observe(view, { childList: true, subtree: true });
      tabs()[j].click();
      clear();
      setTimeout(arrive, 900);   // if nothing changed, never stay stuck
    }, 190);
  };
  document.addEventListener("touchend", end, { passive: true });
  document.addEventListener("touchcancel", () => { if (mode === "drag") { mode = ""; clear(); } else mode = ""; }, { passive: true });
})();
