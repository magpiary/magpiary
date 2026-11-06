/* Phone bar: Search focuses the search box, More opens a small menu. Event delegation, so it survives page changes. */
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
      const q = document.getElementById("q");
      window.scrollTo({ top: 0, behavior: "smooth" });
      if (q) setTimeout(() => q.focus(), 120);
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
