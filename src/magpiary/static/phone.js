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

/* The bar slides away while you scroll down and returns when you scroll up (or stop near the top). */
(() => {
  if (window.__phoneBarScroll) return;
  window.__phoneBarScroll = true;
  let last = window.scrollY, ticking = false;
  const update = () => {
    ticking = false;
    const y = window.scrollY, delta = y - last;
    if (Math.abs(delta) < 8) return;           // ignore jitter
    const open = document.querySelector("[data-pbar-more][aria-expanded=true]");
    document.body.classList.toggle("pbar-away", delta > 0 && y > 80 && !open);
    last = y;
  };
  window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
})();
