/* The landing page's world in the hub: the moving background, the bird's opening, the library's big search and slim
   bar, smooth scrolling, tiles rising into view. */
(() => {
  const root = document.documentElement;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s);
  const stamp = $('link[href*="indigo.css"]').href.split("?")[1];
  const v = (n) => `/static/art/${n}.webp?${stamp}`;

  // ---- the background (the same picture as the landing page; it rests while the page scrolls or is hidden) ---------
  const FRAG = `precision highp float;uniform vec2 r,m;uniform float t,dk;uniform vec3 c1,c2;
float h(vec2 q){q=fract(q*vec2(123.34,456.21));q+=dot(q,q+45.32);return fract(q.x*q.y);}
vec3 col;vec2 Q;float gr;
void cl(vec2 c,float R){vec2 d=Q-c;float l=length(d);float e=1.-smoothstep(R-.004,R+.004,l);
 float lit=clamp(.5+.5*dot(d/max(l,.001),normalize(vec2(-.35,.95))),0.,1.);
 float rim=smoothstep(R*.35,R,l);
 vec3 s=mix(c1*1.08,c2,lit*rim*.92);s+=(gr-.5)*.11*lit;col=mix(col,s,e);}
float star(vec2 d,float s){d=abs(d)/s;return clamp(exp(-d.x*7.)*exp(-d.y*70.)+exp(-d.y*7.)*exp(-d.x*70.)+exp(-length(d)*12.),0.,2.);}
void sq(vec2 a,float w,float y,float f,float ph){float x=Q.x-a.x;if(x<0.||x>w)return;float d=abs(Q.y-(a.y+y*sin(x*f+ph)));col=mix(col,c2*.95,(1.-smoothstep(.0015,.004,d))*.8);}
void main(){vec2 u=gl_FragCoord.xy/r;float a=r.x/r.y;Q=vec2(u.x*a,u.y);gr=h(gl_FragCoord.xy*.73+fract(t*.5)*7.);
 float dc=length((u-.5)*vec2(1.,1.1));
 col=mix(c1*.72,c1*1.16,smoothstep(.15,.85,dc));
 vec2 mm=(m-.5)*.018;vec2 D=vec2(sin(t*.09),cos(t*.07))*.012;
 Q-=mm;
 cl(vec2(.02,.0)+D,.2);cl(vec2(.2,-.04)-D,.17);cl(vec2(.0,.2)-D,.11);cl(vec2(.42,-.1)+D,.17);cl(vec2(.62,-.11)-D,.2);
 cl(vec2(a-.02,.02)-D,.24);cl(vec2(a-.26,-.03)+D,.2);cl(vec2(a-.5,-.1)-D,.17);cl(vec2(a,.28)+D,.12);
 cl(vec2(a-.1,.98)+D,.2);cl(vec2(a-.36,1.04)-D,.21);cl(vec2(a-.6,1.08)+D,.15);cl(vec2(.0,1.02)-D,.15);cl(vec2(.2,1.09)+D,.13);
 sq(vec2(.08,.28),.32,.035,22.,t*.25);sq(vec2(a-.42,.13),.3,.03,26.,-t*.2);sq(vec2(.33,.92),.3,.025,30.,t*.2);
 col+=(gr-.5)*.035;
 Q+=mm;
 col*=dk;
 vec3 g=vec3(1.,.82,.5),pk=vec3(1.,.72,.9);
 col+=pk*star(Q-vec2(a-.13,.86),.05)*(.55+.45*sin(t*1.1));
 col+=g*star(Q-vec2(.16,.16),.035)*(.55+.45*sin(t*.8+2.));
 col+=g*star(Q-vec2(a-.1,.2),.04)*(.55+.45*sin(t*1.3+4.));
 gl_FragColor=vec4(col,1.);}`;
  const FPS = 24;
  let canvas = null, draw = null, resting = 0, last = 0, ticking = false;

  function makeBackground() {
    canvas = document.createElement("canvas"); canvas.id = "bg"; canvas.setAttribute("aria-hidden", "true");
    const fade = document.createElement("div"); fade.id = "bgfade"; fade.setAttribute("aria-hidden", "true");
    document.body.prepend(fade); document.body.prepend(canvas);
    const gl = canvas.getContext("webgl", { alpha: false, antialias: false });
    if (!gl) { canvas.style.background = "#0c0c60"; draw = () => {}; return; }
    const mk = (ty, s) => { const o = gl.createShader(ty); gl.shaderSource(o, s); gl.compileShader(o); return o; };
    const pr = gl.createProgram();
    gl.attachShader(pr, mk(gl.VERTEX_SHADER, "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}"));
    gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, FRAG));
    gl.bindAttribLocation(pr, 0, "a"); gl.linkProgram(pr); gl.useProgram(pr);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const U = {}; ["r", "m", "t", "dk", "c1", "c2"].forEach((n) => { U[n] = gl.getUniformLocation(pr, n); });
    const palette = () => {  // the theme's own colours, from its CSS variables
      const v = (n) => getComputedStyle(root).getPropertyValue(n).trim().split(/\s+/).map(Number);
      const c1 = v("--wc1"), c2 = v("--wc2"), dk = v("--wdk")[0];
      if (c1.length === 3 && !c1.some(isNaN)) { gl.uniform3f(U.c1, ...c1); gl.uniform3f(U.c2, ...c2); gl.uniform1f(U.dk, dk || .86); }
    };
    palette(); new MutationObserver(() => { palette(); if (draw) draw(performance.now()); }).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    gl.uniform2f(U.m, .5, .5);
    const size = () => {
      const k = Math.min(devicePixelRatio || 1, 1.25), w = Math.round(innerWidth * k), h = Math.round(innerHeight * k);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); gl.uniform2f(U.r, w, h); }
    };
    addEventListener("resize", () => { size(); if (draw) draw(performance.now()); }, { passive: true });
    size();
    draw = (now) => { gl.uniform1f(U.t, now / 1000 + 40); gl.drawArrays(gl.TRIANGLES, 0, 3); };
  }
  const moves = () => !calm && root.dataset.world === "full";
  function tick(now) {
    if (!moves()) { ticking = false; return; }
    requestAnimationFrame(tick);
    if (document.hidden || root.classList.contains("quiet") || now < resting || now - last < 1000 / FPS) return;
    last = now; draw(now);
  }
  function applyWorld() {
    const on = true;  // both themes share the one structure, the moving background included
    root.dataset.world = "full";  // the moving background is the one background (owner, 1 Nov)
    if (on && !canvas) makeBackground();
    if (canvas) { canvas.hidden = !on; $("#bgfade").hidden = !on; }
    if (!on) return;
    draw(performance.now());
    if (moves() && !ticking) { ticking = true; requestAnimationFrame(tick); }
  }

  // ---- the opening: the bird brings a post home while pills holding your saves widen one by one as each picture loads;
  // then they expand into the page and the bird flies to its perch on the search. Once per visit; a click skips it ------
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  function opening() {
    if (!root.classList.contains("opening")) return;
    try { sessionStorage.setItem("mag-opened", "1"); } catch (e) {}
    const g = window.gsap;
    let box = null, stopped = false;
    const end = () => {
      stopped = true; root.classList.remove("opening", "mgbird"); box?.remove();
      document.dispatchEvent(new Event("mg-opened"));
    };
    if (!g) { end(); return; }
    const frames = ["fly-a", "fly-b", "fly-c", "fly-d", "land-a", "land-b", "land-c"];
    const srcs = [...document.querySelectorAll("#wallbody .tile img")].slice(0, 5).map((i) => i.src);
    box = document.createElement("div"); box.id = "mgopen"; box.setAttribute("aria-hidden", "true");
    box.innerHTML = `<div class="plate">` + srcs.map((u, i) => `<div class="lp" style="z-index:${9 - i}"><img src="${u}" alt=""></div>`).join("")
      + `<div class="lp fill" style="z-index:10"></div><img class="stack" style="z-index:11" src="${v("stack")}" alt=""></div><div class="bird">`
      + [...new Set(frames)].map((n) => `<img data-f="${n}" src="${v(n)}" alt="">`).join("")
      + `</div>`;
    document.body.append(box);
    root.classList.add("mgbird");
    box.addEventListener("click", () => { g.killTweensOf("*"); end(); });
    const plate = $(".plate", box), bird = $(".bird", box), stack = $(".stack", box);
    const pills = [...box.querySelectorAll(".lp:not(.fill)")], fill = $(".lp.fill", box);
    g.set([...pills, fill], { xPercent: -50, yPercent: -50, scale: 0 });
    g.set(stack, { xPercent: -50, yPercent: -50, scale: .8, opacity: 0 });
    const show = (n) => bird.querySelectorAll("img").forEach((i) => i.classList.toggle("on", i.dataset.f === n));
    const r = { cx: innerWidth / 2, cy: innerHeight * .54 };
    const sw = stack.offsetWidth, sh = sw * .78, bw = bird.offsetWidth, bh = bird.offsetHeight;
    const landX = r.cx - bw * .5, landY = r.cy - sh * .5 - bh * .74;  // centred on the stack, feet on its top edge
    const pos = { x: landX, y: landY };  // no flight in: the bird is already sitting on the stack
    g.set(bird, { x: pos.x, y: pos.y, opacity: 0, scale: .9, transformOrigin: "50% 100%" });
    show("land-c");
    root.classList.remove("opening");
    const intro = g.timeline();
    intro.to(stack, { opacity: 1, scale: 1, duration: .4, ease: "back.out(1.6)" }, 0)
      .to(bird, { opacity: 1, scale: 1, duration: .4, ease: "back.out(1.6)" }, .05);
    // each pill widens only when its picture is ready, so a slow start really looks slower
    const ready = pills.map((p) => $("img", p).decode().catch(() => 0));  // the pictures load while the stack appears
    const widen = (async () => {
      await wait(380);  // the shapes start as the stack settles
      for (let i = 0; i < pills.length && !stopped; i++) {
        await Promise.race([ready[i], wait(300)]);
        await wait(40);
        g.to(pills[i], { scale: .7 + i * .42, duration: .45, ease: "power3.out" });
        g.fromTo($("img", pills[i]), { scale: 1.4 }, { scale: 1, duration: .8, ease: "power3.out" });
      }
    })();
    widen.then(() => {
      if (stopped) return;
      const big = Math.max(innerWidth, innerHeight) * 1.6 / (innerHeight * .32);
      const perch = $(".lhbird") && !scrollY ? $(".lhbird").getBoundingClientRect() : null;
      const t = g.timeline({ onComplete: end });
      t.to(stack, { opacity: 0, scale: .9, duration: .25 }, 0);
      pills.forEach((d, i) => {
        const at = (pills.length - 1 - i) * .035;
        t.to(d, { scale: big, duration: .7, ease: "power3.inOut" }, at);
        t.to(d, { opacity: 0, duration: .7, ease: "power2.out" }, at + .08);  // they fade as they open out, slowing to a stop
      });
      t.to(fill, { scale: big * 1.3, duration: .66, ease: "power3.inOut" }, .16);
      t.to(fill, { opacity: 0, duration: .6, ease: "power2.out" }, .24);
      t.add(() => { reveal(300); watchTiles(); }, .6);  // the page starts to arrive as the shapes finish fading, a beat later, not at once
      t.to(plate, { opacity: 0, duration: .9, ease: "sine.out" }, .5);
      if (perch) {
        const beats = ["land-c", "land-b", "fly-a", "fly-b", "fly-c", "fly-b", "fly-a", "fly-b", "fly-c", "fly-b", "fly-a", "fly-b", "fly-c", "fly-b", "fly-d", "land-a", "land-b", "land-c"];
        const hop = { p: 0 }, x0 = pos.x, y0 = pos.y, rise = Math.max(70, innerHeight * .1);
        t.to(bird, { width: perch.width, duration: 1.5, ease: "power2.inOut" }, .25);
        t.to(hop, { p: 1, duration: 1.5, ease: "sine.inOut", onUpdate() {
          const p = hop.p;
          g.set(bird, { x: x0 + (perch.left - x0) * p, y: y0 + (perch.top - y0) * p - Math.sin(Math.PI * p) * rise });
          show(beats[Math.min(Math.floor(p * beats.length), beats.length - 1)]);
        } }, .25);
      }
      else t.to(bird, { opacity: 0, duration: .3 }, .9);
    });
  }
  // the page arrives: the heading and what follows it rise, written to no attribute (hub.js compares this HTML)
  function reveal(lead = 0) {
    introUntil = performance.now() + 1400 + lead; introLead = lead;
    const ease = "cubic-bezier(.2,.8,.2,1)";
    // the top drifts down piece by piece, then the heading, search and notices rise, then the tabs; the tiles follow (watchTiles)
    document.querySelectorAll(".top .bar > *").forEach((el, i) => el.animate(
      [{ opacity: 0, translate: "0 -28px", scale: .94 }, { opacity: 1, translate: "0 0", scale: 1 }], { duration: 760, delay: lead + i * 110, easing: ease, fill: "backwards" }));
    document.querySelectorAll(".lhero > *, #view .banner, #wallctl").forEach((el, i) => el.animate(
      [{ opacity: 0, translate: "0 48px", scale: .97 }, { opacity: 1, translate: "0 0", scale: 1 }], { duration: 900, delay: lead + 300 + i * 150, easing: ease, fill: "backwards" }));
  }

  // ---- the library's top: the bar takes over when the big search has gone by ----------------------------------------
  function topState() {
    const box = $("#lhsearch");
    if (!box) { root.classList.remove("lhtop", "lhslim"); return; }
    // on a phone the hero (and its search box) is not shown (phone.css); then the floating tabs appear once the tabs' own row
    // has gone up under the top bar. Where the row would sit is the bottom of the last visible thing before it, or the
    // top of its container
    const wc = $("#wallctl");
    let gone;
    if (box.offsetParent === null && wc) {
      let prev = wc.previousElementSibling;
      while (prev && prev.offsetParent === null) prev = prev.previousElementSibling;
      const natural = prev ? prev.getBoundingClientRect().bottom : wc.parentElement.getBoundingClientRect().top + parseFloat(getComputedStyle(wc.parentElement).paddingTop || 0);
      gone = natural < 10;  // = where the floating tabs stick, so they do not jump
    } else gone = box.getBoundingClientRect().bottom < 76;
    const was = root.classList.contains("lhslim");
    root.classList.toggle("lhslim", gone); root.classList.toggle("lhtop", !gone);
    if (was !== gone) {  // the tabs change size between big and floating: the sliding highlight is measured again
      const views = $("#views"), on = $("a.on", views), line = $(".vline", views);
      if (on && line && window.gsap) gsap.set(line, { x: on.offsetLeft, width: on.offsetWidth });
    }
  }
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("#lhsearch")) return;
    $("#searchform")?.click();  // opens the big box (hub.js)
  });

  // the same box grows where it is: hub.js asks here before opening or closing the big search
  window.MagMorph = {
    origin() { return root.classList.contains("lhtop") ? $("#lhsearch") : $("#searchform"); },
    open(sover) {
      const g = window.gsap, from = this.origin();
      if (!g || calm || !from || innerWidth < 640) return false;
      const box = $(".sbox", sover), big = $(".sbig", sover), panel = $(".spanel2", sover), r = from.getBoundingClientRect();
      const w = Math.min(760, innerWidth - 32), left = Math.round((innerWidth - w) / 2);
      // always centred across the window; the height is where the library's own search sits, wherever it was opened from
      const fromHero = root.classList.contains("lhtop") && from.id === "lhsearch";
      if (fromHero) this.rest = Math.max(16, Math.min(innerHeight - 440, r.top - (72 - r.height) / 2));
      const top = Math.max(16, Math.min(innerHeight - 440, this.rest ?? Math.round(innerHeight * .235)));
      g.killTweensOf([box, big, sover, panel]);
      sover.classList.add("morph"); root.classList.add("morphing");
      sover.style.setProperty("--spmax", `${innerHeight - top - 110}px`);
      g.fromTo(sover, { backgroundColor: "rgba(4,4,24,0)" }, { backgroundColor: "rgba(4,4,24,.68)", duration: .3 });
      g.fromTo(box, { left: r.left, top: r.top, width: r.width }, { left, top, width: w, duration: .42, ease: "power3.out" });
      g.fromTo(big, { height: r.height, fontSize: 18 }, { height: 72, fontSize: 26, duration: .42, ease: "power3.out" });
      g.fromTo(panel, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: .32, delay: .12, ease: "power2.out", clearProps: "transform" });
      return true;
    },
    close(sover, done) {
      const g = window.gsap;
      if (!g || !sover.classList.contains("morph")) return false;
      const box = $(".sbox", sover), big = $(".sbig", sover), panel = $(".spanel2", sover), r = this.origin()?.getBoundingClientRect();
      const finish = () => {
        g.set([box, big, sover, panel], { clearProps: "all" });
        sover.classList.remove("morph"); root.classList.remove("morphing"); done();
      };
      g.killTweensOf([box, big, sover, panel]);
      g.to(panel, { opacity: 0, duration: .12 });
      g.to(sover, { backgroundColor: "rgba(4,4,24,0)", duration: .26 });
      if (r) g.to(big, { height: r.height, fontSize: 18, duration: .3, ease: "power3.inOut" });
      if (r) g.to(box, { left: r.left, top: r.top, width: r.width, duration: .3, ease: "power3.inOut", onComplete: finish }); else finish();
      return true;
    },
  };

  // ---- the nav leaves while you scroll down and returns when you scroll up ------------------------------------------
  let lastY = scrollY;
  function navState() {
    const y = scrollY, slim = root.classList.contains("lhslim") || (!!$(".postpage") && y > 90);
    if (!slim) root.classList.remove("navhid");
    else if (y > lastY + 4) root.classList.add("navhid");
    else if (y < lastY - 4) root.classList.remove("navhid");
    lastY = y;
  }
  // the moving picture is for the library and the boards; reading pages and Settings stay flat
  function pageState() { root.classList.toggle("quiet", !["wall", "board"].includes(document.body.dataset.page)); }

  // ---- smooth scrolling, in the page only; a dialog or panel that scrolls itself keeps its own ------------------------
  function smooth() {
    if (calm || !window.Lenis || matchMedia("(hover: none)").matches) return;
    const scrollsItself = (node) => {
      for (let el = node; el && el !== document.body; el = el.parentElement) {
        const o = getComputedStyle(el).overflowY;
        if ((o === "auto" || o === "scroll") && el.scrollHeight > el.clientHeight) return true;
        if (el.matches("[role=dialog], .modal, .sover, video")) return true;
      }
      return false;
    };
    const lenis = new window.Lenis({ lerp: .11, prevent: scrollsItself });
    const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); };
    requestAnimationFrame(raf);
  }

  // ---- tiles rise gently into view, once. No class or style is written: hub.js compares tiles' HTML on every live update ----
  // Tiles are started a little BEFORE they reach the screen (the margin below), so they are already settled when scrolled to:
  // starting late is what made them peek, vanish and come back. The first screen is staggered in with the page; after that each
  // batch only gets a short, light fade-and-rise. Tiles are remembered by their post, so a live refresh never replays one.
  const risen = new Set();
  let introUntil = 0, introLead = 0;
  const rises = !calm && "IntersectionObserver" in window ? new IntersectionObserver((seen) => {
    const intro = performance.now() < introUntil;
    seen.filter((s) => s.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top || a.boundingClientRect.left - b.boundingClientRect.left).forEach((s, n) => {
      rises.unobserve(s.target);
      s.target.animate(intro ? [{ opacity: 0, translate: "0 56px", scale: .955 }, { opacity: 1, translate: "0 0", scale: 1 }]
                             : [{ opacity: 0, translate: "0 26px" }, { opacity: 1, translate: "0 0" }],
        { duration: intro ? 820 : 460, delay: intro ? introLead + 380 + Math.min(n, 11) * 80 : Math.min(n, 5) * 35, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" });
    });
  }, { rootMargin: "0px 0px 160px 0px" }) : null;
  function watchTiles() {
    if (!rises) return;
    document.querySelectorAll("#wallbody .tile").forEach((t) => { const id = t.dataset.id; if (!risen.has(id)) { risen.add(id); rises.observe(t); } });
  }



  // our own tooltip for anything with a title. The title is only lent while the pointer is there, so the page's HTML never changes
  function tooltips() {
    const tip = document.createElement("div"); tip.id = "mgtip"; tip.setAttribute("role", "tooltip"); tip.hidden = true;
    document.body.append(tip);
    let owner = null, text = "", timer = 0;
    const hide = () => {
      clearTimeout(timer); tip.hidden = true; tip.classList.remove("on");
      if (owner?.isConnected && text && !owner.hasAttribute("title")) owner.setAttribute("title", text);
      owner = null;
    };
    document.addEventListener("pointerover", (ev) => {
      if (ev.pointerType === "touch") return;
      const el = ev.target.closest?.("[title]");
      if (!el || el === owner || el.closest("svg")) { if (!el && owner && !owner.contains(ev.target)) hide(); return; }
      hide();
      owner = el; text = el.getAttribute("title"); el.removeAttribute("title");
      if (!text) { owner = null; return; }
      timer = setTimeout(() => {
        tip.textContent = text; tip.hidden = false;
        const b = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
        const below = b.bottom + h + 12 < innerHeight;
        tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, b.left + b.width / 2 - w / 2)) + "px";
        tip.style.top = (below ? b.bottom + 8 : b.top - h - 8) + "px";
        tip.classList.add("on");
      }, 180);
    }, true);
    document.addEventListener("pointerout", (ev) => { if (owner && !owner.contains(ev.relatedTarget)) hide(); }, true);
    addEventListener("scroll", hide, { passive: true });
    document.addEventListener("click", hide, true);
  }

  // the media frame takes the media's own shape, so the switch and the controls always sit on the picture
  function fitMedia(el) {
    const w = el.videoWidth || el.naturalWidth, h = el.videoHeight || el.naturalHeight, stage = el.closest(".cardm.pagemode .stage");
    if (stage && w && h) stage.style.setProperty("--mar", (w / h).toFixed(4));
  }
  const fitAll = () => document.querySelectorAll(".cardm.pagemode .stage video, .cardm.pagemode .stage .gal img:first-child").forEach(fitMedia);

  // ---- our own picker in place of the browser's select (Ask: who answers, model, effort, where to ask) ----------------
  const CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  const TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';
  function fancy(sel) {
    if (sel.dataset.fancy) return;
    sel.dataset.fancy = "1"; sel.classList.add("fsel-src");
    const wrap = document.createElement("span"); wrap.className = "fsel";
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "fsel-btn"; btn.setAttribute("aria-haspopup", "listbox");
    wrap.append(btn); sel.after(wrap);
    const label = () => { btn.innerHTML = `<span>${(sel.selectedOptions[0]?.textContent || "").replace(/</g, "&lt;")}</span>${CHEV}`; };
    label(); sel.addEventListener("change", label);
    new MutationObserver(label).observe(sel, { childList: true, subtree: true, characterData: true });
    let pop = null;
    const close = () => { if (!pop) return; const p = pop; pop = null; wrap.classList.remove("open"); p.classList.remove("on"); setTimeout(() => p.remove(), 140); document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", keys, true); };
    const away = (ev) => { if (pop && !pop.contains(ev.target) && !wrap.contains(ev.target)) close(); };
    const pick = (opt) => { if (sel.value !== opt.value) { sel.value = opt.value; sel.dispatchEvent(new Event("change", { bubbles: true })); } close(); btn.focus(); };
    const keys = (ev) => {
      if (!pop) return;
      const items = [...pop.querySelectorAll("button")]; let i = items.findIndex((b) => b.classList.contains("kb"));
      if (ev.key === "Escape") { ev.preventDefault(); close(); btn.focus(); }
      else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); items[i]?.classList.remove("kb"); i = (i + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; items[i].classList.add("kb"); items[i].scrollIntoView({ block: "nearest" }); }
      else if (ev.key === "Enter") { ev.preventDefault(); items[i]?.click(); }
    };
    const open = () => {
      if (pop) { close(); return; }
      pop = document.createElement("div"); pop.className = "fsel-pop"; pop.setAttribute("role", "listbox");
      const add = (o) => { const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "option"); b.setAttribute("aria-selected", String(o.selected));
        b.innerHTML = `<span>${o.textContent.replace(/</g, "&lt;")}</span>${o.selected ? TICK : ""}`; if (o.selected) b.classList.add("kb"); b.addEventListener("click", () => pick(o)); pop.append(b); };
      [...sel.children].forEach((c) => {
        if (c.tagName === "OPTGROUP") { const g = document.createElement("div"); g.className = "fg"; g.textContent = c.label; pop.append(g); [...c.children].forEach(add); } else add(c);
      });
      document.body.append(pop);
      const r = btn.getBoundingClientRect();
      pop.style.minWidth = Math.max(200, r.width) + "px";
      const below = r.bottom + 8 + Math.min(pop.offsetHeight, 340) < innerHeight;
      pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + "px";
      pop.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - pop.offsetHeight - 6)) + "px";
      wrap.classList.add("open"); requestAnimationFrame(() => pop?.classList.add("on"));
      pop.querySelector(".kb")?.scrollIntoView({ block: "nearest" });
      document.addEventListener("pointerdown", away, true); document.addEventListener("keydown", keys, true);
    };
    btn.addEventListener("click", open);
  }
  function fancyAll() { document.querySelectorAll(".askplace select, .askctlcol select, .actl-form select").forEach(fancy); }

  // the landing page's little stars, a few per press on anything pressable. Colours come round gold, pink, mint, lilac
  function sparkles() {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const hues = ["#ffd27a", "#ff8fb8", "#8fe5c2", "#b59cff"]; let n = 0;
    document.addEventListener("pointerdown", (ev) => {
      const g = window.gsap, hit = ev.target.closest?.("a, button, summary, [role=button], label.tgl, .sw, .fchip");
      if (!g || !hit || hit.matches(":disabled, .busy, [aria-disabled=true]") || ev.button) return;
      const c = hues[n++ % hues.length];
      for (let i = 0; i < 7; i++) {
        const s = document.createElement("i"); s.className = "spk"; s.style.background = c; document.body.append(s);
        const a = Math.random() * 6.28, d = 22 + Math.random() * 34;
        g.fromTo(s, { x: ev.clientX - 4, y: ev.clientY - 4, scale: 1.1, rotation: 0 },
          { x: ev.clientX - 4 + Math.cos(a) * d, y: ev.clientY - 4 + Math.sin(a) * d, scale: 0, rotation: 180, duration: .6, ease: "power2.out", onComplete: () => s.remove() });
      }
    }, true);
  }

  function start() {
    tooltips();
    sparkles();
    fancyAll();
    document.addEventListener("loadedmetadata", (ev) => { if (ev.target.matches?.(".stage video")) fitMedia(ev.target); }, true);
    document.addEventListener("load", (ev) => { if (ev.target.matches?.(".stage .gal img:first-child")) fitMedia(ev.target); }, true);
    fitAll();
    pageState();
    applyWorld();
    topState();
    smooth();
    addEventListener("scroll", () => { resting = performance.now() + 220; topState(); navState(); }, { passive: true });
    new MutationObserver(() => { pageState(); applyWorld(); topState(); fancyAll(); }).observe(document.body, { attributes: true, attributeFilter: ["data-page"] });
    const view = $("#view");
    if (view) new MutationObserver(() => { topState(); fitAll(); fancyAll(); if (!$("#mgopen")) watchTiles(); }).observe(view, { childList: true, subtree: true });
    document.addEventListener("mg-opened", watchTiles);
    if (root.classList.contains("opening")) opening(); else { reveal(); watchTiles(); }
  }
  start();
})();
