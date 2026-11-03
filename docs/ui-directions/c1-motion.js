// Motion pass for C1+ (GSAP + Flip). Wraps the page's render functions instead of changing them:
// grid changes morph with Flip, a tile flies into the post card and back, pages enter with a short stagger.
// Skipped entirely when the viewer asks for reduced motion.
(function () {
  if (!window.gsap || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  gsap.registerPlugin(Flip);
  document.documentElement.classList.add("gs");
  const css = document.createElement("style");
  css.textContent = `.gs .cardm, .gs .scrim { transition: none !important; } .gs .tile.new { animation: none; }`;
  document.head.appendChild(css);
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  const EASE = "power3.out";

  function tagTiles() { qa("#view .tile[data-id]").forEach(t => t.dataset.flipId = "t" + t.dataset.id); }
  function enter(sel, opts = {}) {
    const els = qa(sel); if (!els.length) return;
    gsap.from(els, { y: 22, opacity: 0, duration: .55, ease: EASE, stagger: { amount: Math.min(.45, els.length * .03) }, clearProps: "transform,opacity", ...opts });
  }
  function enterPage() {
    enter("#view .hero > *, #view .banner, #view .ctrl", { stagger: .06 });
    enter("#view .tile, #view .pile, #view .sec", { delay: .1 });
  }

  // Wall: same page re-rendered (filter, search, new tile) → Flip; arriving from elsewhere or switching piles/everything → entrance.
  let last = "", lastMode = "";
  const _wall = window.wall;
  window.wall = function () {
    const same = last === "wall" && lastMode === wallMode;
    const state = same ? Flip.getState("#view .tile[data-flip-id]") : null;
    _wall.apply(this, arguments); tagTiles();
    if (state) Flip.from(state, { targets: "#view .tile[data-flip-id]", duration: .5, ease: "power3.inOut", nested: true, prune: true,
      onEnter: els => gsap.fromTo(els, { opacity: 0, scale: .85 }, { opacity: 1, scale: 1, duration: .45, ease: "back.out(1.6)" }) });
    else enterPage();
    last = "wall"; lastMode = wallMode;
  };
  for (const name of ["pileView", "relatedView", "settings", "nest"]) {
    const orig = window[name];
    window[name] = function () {
      orig.apply(this, arguments); last = name; tagTiles();
      if (name === "nest") {
        enter("#view .hero > *, #view .now, #view .panel, #view .cbox, #view .sec", { stagger: .05 });
        gsap.from("#view .sbar", { scaleX: 0, transformOrigin: "0 50%", duration: .8, ease: "expo.out", stagger: .05, delay: .35 });
        qa("#view .stat b").forEach(b => { const n = parseFloat(b.textContent); if (isNaN(n)) return; const unit = b.textContent.replace(/[\d.]/g, ""); const o = { v: 0 };
          gsap.to(o, { v: n, duration: 1, ease: "power2.out", delay: .2, onUpdate: () => b.textContent = Math.round(o.v) + unit }); });
      } else if (name === "settings") enter("#view .hero > *, #view .set nav a, #view .box", { stagger: .04 });
      else enterPage();
    };
  }

  // Tile size (A/A/A): capture positions before the size flips, then morph every tile to its new box.
  document.addEventListener("click", e => {
    const b = e.target.closest(".sizes button"); if (!b || b.getAttribute("aria-pressed") === "true") return;
    const state = Flip.getState("#view .tile, #view .pile");
    setTimeout(() => Flip.from(state, { duration: .55, ease: "power3.inOut", nested: true }));
  }, true);

  // Post card: the tile's picture flies into the player; the information slides in beside it. Closing reverses it.
  let openId = null, closing = false, finishClose = null;
  const rect = el => el && el.getBoundingClientRect();
  const delta = (from, to) => ({ x: from.left - to.left, y: from.top - to.top, scaleX: from.width / to.width, scaleY: from.height / to.height });
  const _open = window.openItem;
  window.openItem = function (id) {
    if (closing && finishClose) finishClose(); // a post opened mid-close: finish the close first
    const wasOpen = q("#cardm").classList.contains("on") && !closing;
    const from = rect(q(`#view .tile[data-id="${id}"] .sq`));
    _open.apply(this, arguments);
    const cm = q("#cardm"), pl = q("#cardm .stage .pl");
    if (!cm.classList.contains("on")) return;
    openId = id;
    if (wasOpen) {
      gsap.from("#cardm .main > *", { opacity: 0, x: 18, duration: .35, ease: EASE, stagger: .02, clearProps: "all" });
      gsap.from("#cardm .vid > *", { opacity: 0, duration: .3, clearProps: "opacity" });
      return;
    }
    gsap.fromTo("#scrim", { opacity: 0 }, { opacity: 1, duration: .35 });
    gsap.fromTo(cm, { opacity: 0 }, { opacity: 1, duration: .22 });
    const to = rect(pl);
    if (from && to && to.width) gsap.from(pl, { ...delta(from, to), transformOrigin: "0 0", duration: .7, ease: "expo.out", clearProps: "transform" });
    else gsap.from(cm, { scale: .96, duration: .4, ease: EASE, clearProps: "transform" });
    gsap.from("#cardm .main > *", { opacity: 0, x: 28, duration: .55, ease: EASE, stagger: .035, delay: .12, clearProps: "all" });
    gsap.from("#cardm .vid .fr > div, #cardm .vid .cap", { opacity: 0, y: 12, duration: .4, stagger: .025, delay: .3, clearProps: "all" });
  };
  const _close = window.closeItem;
  window.closeItem = function () {
    const cm = q("#cardm");
    if (!cm.classList.contains("on") || closing) return closing ? undefined : _close.apply(this, arguments);
    closing = true;
    const pl = q("#cardm .stage .pl"), tile = q(`#view .tile[data-id="${openId}"] .sq`);
    const done = () => { gsap.killTweensOf([cm, "#scrim", pl, "#cardm .main", "#cardm .vid"].filter(Boolean)); gsap.set([cm, "#scrim", pl].filter(Boolean), { clearProps: "all" }); closing = false; finishClose = null; _close(); };
    const tl = gsap.timeline({ onComplete: () => { clearTimeout(safety); done(); } });
    finishClose = () => { clearTimeout(safety); tl.kill(); done(); };
    // Animation frames stop in hidden windows; a timer makes sure the card still closes.
    const safety = setTimeout(() => tl.progress(1), 800);
    const tr = rect(tile), pr = rect(pl);
    if (tr && pr && tr.width && tr.bottom > 0 && tr.top < innerHeight) {
      tl.to("#cardm .main", { opacity: 0, x: 20, duration: .2, ease: "power2.in" }, 0)
        .to(cm, { backgroundColor: "rgba(0,0,0,0)", boxShadow: "none", duration: .25 }, 0)
        .to("#cardm .vid", { backgroundColor: "rgba(0,0,0,0)", duration: .25 }, 0)
        .to("#cardm .vid .fr, #cardm .vid .cap", { opacity: 0, duration: .15 }, 0)
        .to(pl, { x: tr.left - pr.left, y: tr.top - pr.top, scaleX: tr.width / pr.width, scaleY: tr.height / pr.height, transformOrigin: "0 0", duration: .45, ease: "power3.inOut" }, .05)
        .to("#scrim", { opacity: 0, duration: .4 }, 0)
        .to(cm, { opacity: 0, duration: .1 }, .45);
    } else tl.to([cm, "#scrim"], { opacity: 0, duration: .22 });
  };

  // Key moments: pop the matching frame and scroll it into view in the strip.
  document.addEventListener("click", e => {
    if (!e.target.closest("#cardm .kp")) return;
    setTimeout(() => {
      const f = q("#cardm .fr div.on"); if (f) { f.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" }); gsap.fromTo(f, { scale: 1.25 }, { scale: 1, duration: .5, ease: "back.out(3)" }); }
      const tc = q("#cardm #tc"); if (tc) gsap.fromTo(tc, { y: 6, opacity: .4 }, { y: 0, opacity: 1, duration: .35, ease: EASE });
    });
  });

  // Setup flow: each step slides in; checks pop as they tick.
  const _welcome = window.welcome;
  window.welcome = function (step) {
    _welcome.apply(this, arguments);
    last = "welcome";
    if (step === "arrived") return;
    gsap.from("#wel .w-body > div > *", { y: 30, opacity: 0, duration: .65, ease: EASE, stagger: .06, clearProps: "transform,opacity" });
    gsap.from("#wel .w-prog span.on", { scale: .85, duration: .5, ease: "back.out(2.5)" });
  };
  new MutationObserver(ms => ms.forEach(m => {
    const t = m.target;
    if (t.classList && t.classList.contains("ck") && t.classList.contains("ok") && !(m.oldValue || "").includes("ok"))
      gsap.fromTo(t.querySelectorAll(".n, .st"), { scale: .5 }, { scale: 1, duration: .55, ease: "back.out(3)" });
  })).observe(document.getElementById("wel"), { attributes: true, attributeFilter: ["class"], attributeOldValue: true, subtree: true });

  // First paint.
  tagTiles();
  if (q("#wel.on")) gsap.from("#wel .w-body > div > *", { y: 30, opacity: 0, duration: .7, ease: EASE, stagger: .07, clearProps: "transform,opacity" });
  else enterPage();
  last = q("#view .nest") ? "nest" : "wall"; lastMode = wallMode;
})();
