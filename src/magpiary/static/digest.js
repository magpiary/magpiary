/* The digest's show, Wrapped-style (owner, 1 Nov): a full-screen opening on a new digest, the heading slammed in, the bird
   flying to the highlighted word, the numbers as a pinned scene, Worth doing as a stack of cards, the words bursting
   together with the scroll. The first visit gets the whole show; later visits run shorter. The page reads fine without
   any of it: nothing is hidden until this file hides it, and reduced motion only gets the bird, sitting. */
(() => {
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s), $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const clamp = (n) => Math.min(1, Math.max(0, n));
  const stamp = () => ($('link[href*="hub.css"]')?.href || "").split("?")[1] || "";
  const art = (n) => `/static/art/${n}.webp?${stamp()}`;
  const FRAMES = ["fly-a", "fly-b", "fly-c", "fly-d", "land-a", "land-b", "land-c"];
  const FLIGHT = ["fly-a", "fly-b", "fly-c", "fly-b", "fly-a", "fly-b", "fly-c", "fly-b", "fly-a", "fly-b", "fly-c", "fly-b", "fly-d", "land-a", "land-b", "land-c"];
  const COLOURS = ["#ffc23d", "#ff5a92", "#8b5cf6", "#7b8cff", "#f3efe6", "#ffe08a", "#6d4df0"];

  // ---- confetti, from a point ----
  function confetti(x = innerWidth / 2, y = innerHeight * .42, count = 170, force = 1) {
    if (calm) return;
    const c = document.createElement("canvas");
    c.className = "dgconfetti"; c.width = innerWidth; c.height = innerHeight; document.body.append(c);
    const pen = c.getContext("2d");
    const bits = Array.from({ length: count }, (_, i) => ({
      x, y, vx: (Math.random() - .5) * 16 * force, vy: (-Math.random() * 15 - 5) * force,
      s: 6 + Math.random() * 7, r: Math.random() * 6, vr: (Math.random() - .5) * .3, c: COLOURS[i % COLOURS.length], round: Math.random() < .3 }));
    const start = performance.now();
    const step = (now) => {
      pen.clearRect(0, 0, c.width, c.height);
      bits.forEach((b) => {
        b.vy += .38; b.vx *= .99; b.x += b.vx; b.y += b.vy; b.r += b.vr;
        pen.save(); pen.translate(b.x, b.y); pen.rotate(b.r); pen.fillStyle = b.c;
        if (b.round) { pen.beginPath(); pen.arc(0, 0, b.s / 2, 0, 7); pen.fill(); } else pen.fillRect(-b.s / 2, -b.s / 4, b.s, b.s / 2);
        pen.restore();
      });
      if (now - start < 3200) requestAnimationFrame(step); else c.remove();
    };
    requestAnimationFrame(step);
  }

  // ---- words into pieces that can move alone. The heading keeps its full text for screen readers ----
  function split(el) {
    el.setAttribute("aria-label", el.textContent);
    const wrap = (node) => [...node.childNodes].forEach((n) => {
      if (n.nodeType === 3) {
        const bits = n.textContent.split(/(\s+)/), frag = document.createDocumentFragment();
        bits.forEach((b) => {
          if (!b) return;
          if (!b.trim()) { frag.append(" "); return; }
          const w = document.createElement("span"); w.className = "dgw"; w.setAttribute("aria-hidden", "true"); w.textContent = b; frag.append(w);
        });
        n.replaceWith(frag);
      } else wrap(n);
    });
    wrap(el);
    return $$(".dgw", el);
  }

  // ---- the bird: sits on the highlighted word, or the middle of the heading when nothing is highlighted ----
  function birdEl(tag) {
    const b = document.createElement("span"); b.className = tag; b.setAttribute("aria-hidden", "true");
    b.innerHTML = FRAMES.map((n) => `<img data-f="${n}" src="${art(n)}" alt="">`).join("");
    return b;
  }
  const show = (b, n) => $$("img", b).forEach((i) => i.classList.toggle("on", i.dataset.f === n));
  function perchWord(h1) {
    const words = $$(".dgw", h1);
    return $("mark .dgw", h1) || words[Math.floor(words.length / 2)];
  }
  function sit(h1) {
    const word = perchWord(h1); if (!word) return null;
    const sat = birdEl("dgbird"); word.append(sat); show(sat, "land-c");
    return { sat, word };
  }
  // now and then it looks around; click it and it hops
  function idle(sat, box) {
    const g = window.gsap;
    const blink = () => {
      if (!box.isConnected) return;
      show(sat, Math.random() < .5 ? "land-b" : "land-a");
      setTimeout(() => { if (sat.isConnected) show(sat, "land-c"); }, 220);
      setTimeout(blink, 2600 + Math.random() * 3200);
    };
    setTimeout(blink, 2400);
    sat.addEventListener("click", () => {
      g.timeline().call(() => show(sat, "fly-b")).to(sat, { y: -46, rotate: -8, duration: .24, ease: "power2.out" })
        .call(() => show(sat, "fly-c")).to(sat, { y: 0, rotate: 0, duration: .5, ease: "bounce.out" })
        .call(() => show(sat, "land-c"));
    });
  }
  function fly(h1, spot, box, fast, done) {
    const g = window.gsap, { sat, word } = spot;
    const to = sat.getBoundingClientRect();
    sat.style.visibility = "hidden";
    const flyer = birdEl("dgflyer"); document.body.append(flyer);
    const hop = { p: 0 }, x0 = -to.width * 2, y0 = Math.max(40, to.top - innerHeight * .28), rise = innerHeight * .22, big = 2.4;
    g.set(flyer, { width: to.width * big, x: x0, y: y0 });
    const time = fast ? .9 : 1.7;
    g.to(flyer, { width: to.width, duration: time, ease: "power2.inOut" });
    g.to(hop, { p: 1, duration: time, ease: "sine.inOut", onUpdate() {
      const p = hop.p, now = sat.getBoundingClientRect();  // aims at where the word is now, the page may have moved
      g.set(flyer, { x: x0 + (now.left - x0) * p, y: y0 + (now.top - y0) * p - Math.sin(Math.PI * p) * rise });
      show(flyer, FLIGHT[Math.min(Math.floor(p * FLIGHT.length), FLIGHT.length - 1)]);
    }, onComplete() {
      flyer.remove(); sat.style.visibility = "";
      // the word takes its weight
      g.timeline().to(word, { y: 12, scaleY: .84, scaleX: 1.08, duration: .12, ease: "power2.out" })
        .to(word, { y: 0, scaleY: 1, scaleX: 1, duration: .9, ease: "elastic.out(1.1,.35)", clearProps: "transform" });
      g.fromTo(sat, { y: -10 }, { y: 0, duration: .5, ease: "bounce.out", clearProps: "transform" });
      const r = word.getBoundingClientRect();
      confetti(r.left + r.width / 2, r.top, fast ? 16 : 34, .55);
      idle(sat, box);
      done?.();
    } });
  }

  // ---- the opening: three full-screen cuts, then a circle opens on the page. A click skips it ----
  function opening(box, label, saved, then) {
    const g = window.gsap;
    const curtain = document.createElement("div"); curtain.className = "dgcurtain"; curtain.setAttribute("aria-hidden", "true");
    const cuts = [["#2b2aa0", "#fff", label], ["#6d4df0", "#fff", saved ? `${saved} saves` : "Your saves"], ["#ffc23d", "#2a1a00", "Let’s unwrap it"]];
    curtain.innerHTML = cuts.map(([bg, ink, words]) => `<div class="dgcut" style="background:${bg};color:${ink}"><b>${words}</b></div>`).join("");
    document.body.append(curtain);
    const parts = $$(".dgcut", curtain), t = g.timeline();
    let over = false;
    const end = () => { if (over) return; over = true; t.kill(); curtain.remove(); then(); };
    curtain.addEventListener("click", end);
    g.set(parts, { autoAlpha: 0 });
    parts.forEach((p, i) => {
      const at = i * .72;
      t.set(p, { autoAlpha: 1 }, at);
      t.fromTo($("b", p), { scale: 2.6, rotate: i % 2 ? 7 : -7, opacity: 0 }, { scale: 1, rotate: 0, opacity: 1, duration: .42, ease: "back.out(2.2)" }, at);
      t.to($("b", p), { scale: 1.08, duration: .3, ease: "none" }, at + .42);
    });
    t.fromTo(curtain, { clipPath: "circle(150% at 50% 50%)" }, { clipPath: "circle(0% at 50% 50%)", duration: .6, ease: "power3.inOut" }, parts.length * .72);
    t.call(end);
    return curtain;
  }

  // ---- the heading arrives ----
  function hero(box, words, spot, first, fast) {
    const g = window.gsap, h1 = $(".dghl2", box);
    const t = g.timeline();
    t.fromTo($(".dgeyebrow", box), { y: 30, opacity: 0, scale: .7 }, { y: 0, opacity: 1, scale: 1, duration: .5, ease: "back.out(2.4)" }, 0);
    t.fromTo(words, { yPercent: 130, rotate: () => g.utils.random(-14, 14), opacity: 0, scale: .6 },
      { yPercent: 0, rotate: 0, opacity: 1, scale: 1, duration: fast ? .5 : .85, stagger: fast ? .025 : .06, ease: "back.out(2.2)", clearProps: "transform" }, .1);
    t.fromTo($$("mark", h1), { "--pop": 1.5 }, { "--pop": 1, duration: .8, ease: "elastic.out(1.2,.4)" }, fast ? .4 : .9);
    t.fromTo($$(".dgkick, .dgcue", box), { y: 34, opacity: 0 }, { y: 0, opacity: 1, duration: .6, stagger: .12, ease: "power3.out", clearProps: "transform,opacity" }, fast ? .35 : .95);
    if (spot) t.call(() => fly(h1, spot, box, fast, first ? () => confetti() : null), null, fast ? .3 : 1);
    else if (first) t.call(() => confetti(), null, 1);
  }

  // ---- scroll: anything tied to it is a paused timeline and a rule for how far along it is ----
  function scrollDriver(box) {
    const g = window.gsap, jobs = [];
    let queued = false;
    const run = (instant) => {
      queued = false;
      if (!box.isConnected) { removeEventListener("scroll", onScroll); return; }
      const vh = innerHeight;
      jobs.forEach((j) => {
        const p = clamp(j.at(j.el.getBoundingClientRect(), vh));
        if (p === j.last || (j.keep && j.last === 1)) return;
        j.last = p;
        if (instant) j.tl.progress(p); else g.to(j.tl, { progress: p, duration: j.lag ?? .3, ease: "power2.out", overwrite: true });
      });
    };
    const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(() => run(false)); } };
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", onScroll, { passive: true });
    return { add(el, tl, at, lag, keep) { tl.pause(0); jobs.push({ el, tl, at, lag, keep, last: -1 }); }, start() { run(true); } };
  }
  const pinned = (r, vh) => -r.top / Math.max(1, r.height - vh);
  // from `from` (its top this far down the screen) to `to`
  const passing = (from, to) => (r, vh) => (vh * from - r.top) / (vh * (from - to));

  // ---- the numbers: pinned; each fills the screen in turn and counts up, then they settle into the four columns ----
  function numbers(box, driver, fast) {
    const g = window.gsap, stats = $(".dgstats", box);
    const cols = $$(".dgbig > div", stats);
    if (!stats || cols.length !== 4) return;
    const scene = document.createElement("div"); scene.className = "dgscene";
    scene.style.height = `${100 + cols.length * (fast ? 45 : 80) + 30}svh`;
    stats.before(scene); scene.append(stats); stats.classList.add("pinned");
    const inner = document.createElement("div"); inner.className = "dgstatsin"; inner.append(...stats.childNodes); stats.append(inner);
    const stage = document.createElement("div"); stage.className = "dgstage"; stage.setAttribute("aria-hidden", "true");
    const looks = [["#2b2aa0", "#fff"], ["#5b2ee0", "#fff"], ["#ff5a92", "#3a0620"], ["#ffc23d", "#2a1a00"]];
    const facts = cols.map((c) => ({ v: parseInt($("b", c).textContent, 10) || 0, w: $("small", c).textContent }));
    stage.innerHTML = facts.map((f, i) => `<div class="dgone" style="background:${looks[i][0]};color:${looks[i][1]}"><b>0</b><span>${f.w}</span></div>`).join("");
    stats.append(stage);
    const ones = $$(".dgone", stage), t = g.timeline();
    ones.forEach((one, i) => {
      const num = $("b", one), say = $("span", one), n = { v: 0 }, at = i * 1.1;
      t.fromTo(one, { clipPath: "circle(0% at 50% 55%)" }, { clipPath: "circle(150% at 50% 55%)", duration: .55, ease: "power3.in" }, at);
      t.fromTo(num, { scale: .3, rotate: i % 2 ? 12 : -12 }, { scale: 1, rotate: 0, duration: .6, ease: "back.out(2)" }, at + .2);
      t.to(n, { v: facts[i].v, duration: .6, ease: "power2.out", onUpdate() { num.textContent = Math.round(n.v); } }, at + .2);
      t.fromTo(say, { y: 50, opacity: 0 }, { y: 0, opacity: 1, duration: .35, ease: "back.out(2)" }, at + .4);
      if (i < ones.length - 1) t.to(num, { scale: 1.12, duration: .4, ease: "none" }, at + .75);
    });
    const end = ones.length * 1.1;
    t.to(stage, { clipPath: "inset(45% 45% 45% 45% round 40px)", opacity: 0, duration: .55, ease: "power3.in" }, end);
    t.fromTo(inner, { "--stat-line": "rgba(255,255,255,0)" }, { "--stat-line": "rgba(255,255,255,.1)", duration: .3 }, end + .3);
    t.fromTo(cols, { y: 90, opacity: 0, scale: .7 }, { y: 0, opacity: 1, scale: 1, duration: .5, stagger: .07, ease: "back.out(2)" }, end + .3);
    t.fromTo($(".dgsrcs", stats), { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: .35 }, end + .65);
    t.to({}, { duration: .35 });  // a beat to look at them before the page moves on
    // while a number fills the screen, the dock's glow and the top bar's shade step aside
    const stageEnds = (end + .4) / t.duration();
    t.eventCallback("onUpdate", () => document.documentElement.classList.toggle("dgstaged", box.isConnected && t.progress() > .01 && t.progress() < stageEnds));
    driver.add(scene, t, pinned, .25);
  }

  // ---- Worth doing: the cards stick and pile up; each one shrinks back as the next lands on it ----
  function stack(box, driver) {
    const g = window.gsap, list = $(".dgpickrows", box), rows = $$(".dgrow", box);
    if (!list || rows.length < 2 || !matchMedia("(min-width: 861px) and (min-height: 640px)").matches) return;
    list.classList.add("stacked");
    rows.forEach((row, i) => {
      row.style.setProperty("--i", i);
      driver.add(row, g.timeline().fromTo(row, { "--sa": .72 }, { "--sa": 1, ease: "back.out(1.3)", duration: 1 }), passing(1, .35), .2);
      const next = rows[i + 1];
      if (next) driver.add(next, g.timeline().fromTo(row, { "--sb": 1 }, { "--sb": .95, ease: "none", duration: 1 }), passing(.7, .16), .2);
    });
  }

  // ---- the words fly in from all over and snap together with the scroll; afterwards they lean away from the cursor ----
  function cloud(box, driver) {
    const g = window.gsap, wrap = $("#dgpills", box), pills = $$(".dgpill", box);
    if (!wrap || !pills.length) return;
    const t = g.timeline();
    pills.forEach((p, i) => {
      const a = i * 2.4, far = Math.max(innerWidth, innerHeight) * (.5 + (i % 3) * .14);
      t.fromTo(p, { "--dx": `${Math.cos(a) * far}px`, "--dy": `${Math.sin(a) * far * .7}px`, "--dr": `${(i % 2 ? 1 : -1) * (90 + i * 22)}deg`, "--ds": .3, opacity: 0 },
        { "--dx": "0px", "--dy": "0px", "--dr": "0deg", "--ds": 1, opacity: 1, duration: 1, ease: "back.out(1.4)" }, (pills.length - i) * .018);
    });
    driver.add(wrap, t, (r, vh) => {
      const bottom = r.top + scrollY - (document.documentElement.scrollHeight - vh);  // where its top is when the page can't scroll further
      const to = Math.max(vh * .4, bottom + vh * .06), from = Math.max(vh * 1.05, to + vh * .3);
      return (from - r.top) / (from - to);
    }, .35, true);
    if (matchMedia("(hover: none)").matches) return;
    wrap.addEventListener("pointermove", (ev) => {
      pills.forEach((p) => {
        const r = p.getBoundingClientRect(), dx = r.left + r.width / 2 - ev.clientX, dy = r.top + r.height / 2 - ev.clientY;
        const d = Math.hypot(dx, dy) || 1, push = Math.max(0, 1 - d / 150) * 26;
        g.to(p, { "--mx": `${dx / d * push}px`, "--my": `${dy / d * push}px`, duration: .4, ease: "power3.out", overwrite: "auto" });
      });
    });
    wrap.addEventListener("pointerleave", () => g.to(pills, { "--mx": "0px", "--my": "0px", duration: 1, ease: "elastic.out(1,.35)", overwrite: "auto" }));
  }

  // ---- the rest rises as it arrives, once, with a bit of a bounce ----
  function reveals(box, driver) {
    const g = window.gsap, plays = new Map();
    const when = (el, fn) => plays.set(el, fn);
    $$(".dgsh", box).forEach((h) => { g.set(h, { x: -60, opacity: 0 }); when(h, () => g.to(h, { x: 0, opacity: 1, duration: .7, ease: "back.out(2)", clearProps: "transform" })); });
    $$(".dgtheme", box).forEach((row) => {
      const name = $("h3", row), small = $("small", row), bar = $(".dgshare", row), text = $(".dgtbody p", row), thumbs = $$(".dgth", row);
      g.set(name, { x: -90, opacity: 0, rotate: -3 }); g.set([small, text], { y: 26, opacity: 0 });
      g.set(bar, { scaleX: 0, transformOrigin: "0 50%" }); g.set(thumbs, { scale: 0, rotate: () => g.utils.random(-30, 30) });
      when(row, () => g.timeline()
        .to(name, { x: 0, opacity: 1, rotate: 0, duration: .75, ease: "back.out(2)", clearProps: "transform" }, 0)
        .to(small, { y: 0, opacity: 1, duration: .4 }, .2)
        .to(bar, { scaleX: 1, duration: 1.2, ease: "elastic.out(1,.5)" }, .25)
        .to(text, { y: 0, opacity: 1, duration: .55, ease: "power3.out" }, .2)
        .to(thumbs, { scale: 1, rotate: 0, duration: .75, stagger: .07, ease: "elastic.out(1.1,.55)", clearProps: "transform" }, .35));
    });
    $$(".dgrow", box).forEach((row) => {
      const bits = $$(".dgrm > *, .dgpa > *", row);
      g.set(bits, { y: 18, opacity: 0, scale: .8 });
      when(row, () => g.to(bits, { y: 0, opacity: 1, scale: 1, duration: .5, stagger: .05, ease: "back.out(2.5)", clearProps: "transform,opacity" }));
    });
    const seen = new IntersectionObserver((list) => list.forEach((e) => {
      if (!e.isIntersecting) return;
      seen.unobserve(e.target); plays.get(e.target)?.();
    }), { rootMargin: "0px 0px -12% 0px" });
    plays.forEach((_, el) => seen.observe(el));
    // the standout lights up word by word with the scroll
    const quote = $(".dgstand2", box);
    if (quote) {
      const words = split(quote);
      driver.add(quote, g.timeline().fromTo(words, { opacity: .14 }, { opacity: 1, duration: .2, stagger: .8 / words.length, ease: "none" }), passing(.92, .42), .15);
    }
    // the heading and picture leave as you scroll on
    const heroBox = $(".dghero2", box), back = $(".dgbackdrop", box);
    const out = g.timeline();
    out.to(heroBox, { y: -70, scale: .9, opacity: .1, ease: "none", duration: 1 }, 0);
    if (back) out.to(back, { y: 140, scale: 1.14, ease: "none", duration: 1 }, 0);
    driver.add(heroBox, out, (r, vh) => -r.top / (r.height * .85), .15);
  }

  // ---- "I tried this": the stamp comes down, the card takes the hit, and confetti ----
  function tried(row, button) {
    row.classList.add("justnow");
    const r = button.getBoundingClientRect();
    setTimeout(() => confetti(r.left + r.width / 2, r.top, 90, .8), 170);
    const g = !calm && window.gsap;
    if (g) g.timeline({ delay: .17 })
      .to(row, { y: 9, scale: .975, duration: .06, ease: "power4.out" })
      .to(row, { y: 0, scale: 1, duration: .75, ease: "elastic.out(1.2,.3)", clearProps: "y" });
    setTimeout(() => row.classList.remove("justnow"), 1100);
  }

  function play(box, { first } = {}) {
    if (box.dataset.shown) return;
    box.dataset.shown = "1";
    const h1 = $(".dghl2", box), g = window.gsap;
    const words = split(h1);
    const spot = sit(h1);
    if (calm || !g) return;
    const fast = !first;
    const driver = scrollDriver(box);
    numbers(box, driver, fast);
    stack(box, driver);
    cloud(box, driver);
    reveals(box, driver);
    driver.start();
    // ready and hidden before the first paint, so nothing shows twice
    g.set(words, { opacity: 0 }); g.set($$(".dgeyebrow, .dgkick, .dgcue", box), { opacity: 0 });
    if (spot) spot.sat.style.visibility = "hidden";
    if (first && !box.dataset.waiting) {
      const label = ($(".dgeyebrow", box)?.textContent || "").split("·")[0].trim() || "Your digest";
      opening(box, label, parseInt($(".dgbig b", box)?.textContent, 10) || 0, () => hero(box, words, spot, true, false));
    } else requestAnimationFrame(() => hero(box, words, spot, false, true));
    // whatever happens to the show, the words are never left hidden
    setTimeout(() => {
      if (!box.isConnected || $(".dgcurtain")) return;
      const stuck = [...words, ...$$(".dgeyebrow, .dgkick, .dgcue", box)].filter((el) => getComputedStyle(el).opacity === "0" && !g.isTweening(el));
      if (stuck.length) g.set(stuck, { clearProps: "opacity,transform" });
      if (spot && !$(".dgflyer")) spot.sat.style.visibility = "";
    }, 6000);
  }

  window.MagDigest = { play, tried, confetti };
})();
