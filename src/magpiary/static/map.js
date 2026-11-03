/* The connections map: a small force layout on a canvas, no libraries. Finds every .cmap on the page (also ones the
   hub adds later, such as a post's Related tab) and draws the graph from its data-map-src. */
(() => {
  "use strict";
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PAL = { sky: "#6aa3ff", coral: "#ff7a70", lilac: "#a98bff", rose: "#ff6fa8", mint: "#4fd1a1", butter: "#f2c14e", peach: "#ff9a6a", aqua: "#4cc9d8" };
  const FOLD_AT = 120;  // more saves than this start with every pile folded into one dot
  const csrf = () => document.querySelector('meta[name="csrf"]')?.content || "";
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const typeName = (t) => ({ howto: "How to", news_opinion: "News", tool: "Tools", design: "Design", explainer: "Explainer", discussion: "Discussion", recipe: "Recipes", place: "Places", other: "Other" })[t] || t;
  const srcName = (s) => ({ instagram: "Instagram", threads: "Threads", youtube: "YouTube", reddit: "Reddit", x: "X", linkedin: "LinkedIn" })[s] || (s ? s[0].toUpperCase() + s.slice(1) : "Web");

  function openPost(id) {  // the hub's own click handler opens a post over the page
    const a = el("a"); a.href = "/item/" + id; a.hidden = true; document.body.append(a); a.click(); a.remove();
  }

  class CMap {
    constructor(root) {
      this.root = root; this.local = root.classList.contains("cmap-local");
      this.canvas = root.querySelector("canvas"); this.ctx = this.canvas.getContext("2d");
      this.tip = root.querySelector(".cmap-tip");
      this.view = { k: 1, x: 0, y: 0 }; this.alpha = 1; this.folded = new Set(); this.pos = new Map();
      this.hover = null; this.pinned = null; this.filter = { pile: "", type: "", source: "", text: "" };
      this.raf = 0; this.visible = true; this.drag = null; this.pointers = new Map();
      this.theme();
      new ResizeObserver(() => this.resize()).observe(root);
      new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; if (this.visible) this.kick(); }).observe(root);
      new MutationObserver(() => { this.theme(); this.draw(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      this.events();
      this.load();
    }

    theme() {
      const s = getComputedStyle(this.root);
      this.col = { fg: s.getPropertyValue("--fg").trim() || "#f5f3ee", fg3: s.getPropertyValue("--fg-3").trim() || "#97948b",
                   line: s.getPropertyValue("--line").trim() || "#262626", bg: s.getPropertyValue("--bg").trim() || "#0f0f0f" };
    }

    async load() {
      this.note("Drawing the map…");
      let data;
      try {
        const r = await fetch(this.root.dataset.mapSrc, { cache: "no-store", headers: { Accept: "application/json" } });
        data = await r.json();
      } catch (e) { return this.note("The map could not be loaded. If the hub is locked, unlock it and reload."); }
      if (!data.nodes.length || (!data.edges.length && !this.local)) return this.note("Nothing connects yet. Related saves appear here as you save more.");
      this.data = data; this.centre = data.centre || "";
      this.byId = new Map(data.nodes.map((n) => [n.id, n]));
      this.piles = new Map(data.piles.map((p) => [p.id, p]));
      const posts = data.nodes.filter((n) => n.kind === "post").length;
      if (!this.local && posts > FOLD_AT) data.piles.forEach((p) => this.folded.add(p.id));
      this.seed();
      this.note("");
      if (!this.local) this.toolbar();
      const focus = this.root.dataset.focus;
      if (focus && this.byId.get(focus)) {
        const f = this.byId.get(focus); this.folded.delete(f.pile); this.focusId = focus;
      }
      this.rebuild(true);
      this.resize();
      this.fit();
      if (this.focusId) this.centreOn(this.focusId);
      this.draw();
      this.kick();
    }

    note(text) {
      this.noteEl ||= this.root.appendChild(el("p", "cmap-note"));
      this.noteEl.textContent = text; this.noteEl.hidden = !text;
    }

    // ---- model -----------------------------------------------------------------------------------------------

    seed() {  // a starting place for every node: piles on a ring, their saves around them
      const piles = [...this.piles.keys()], ring = Math.max(120, piles.length * 26);
      const at = new Map(piles.map((id, i) => [id, [Math.cos(i / piles.length * 6.283) * ring, Math.sin(i / piles.length * 6.283) * ring]]));
      let n = 0;
      for (const node of this.data.nodes) {
        const c = at.get(node.pile) || [0, 0], a = (n++) * 2.399, d = 20 + 9 * Math.sqrt(n);
        const p = this.local ? [Math.cos(a) * 90, Math.sin(a) * 90] : [c[0] + Math.cos(a) * d % 60, c[1] + Math.sin(a) * d % 60];
        this.pos.set(node.id, { x: p[0] + (node.kind === "post" ? 0 : (Math.random() - .5) * 200), y: p[1], vx: 0, vy: 0 });
      }
      if (this.local && this.centre) Object.assign(this.pos.get(this.centre), { x: 0, y: 0 });
    }

    rep(node) { return node.kind === "post" && node.pile != null && this.folded.has(node.pile) ? "g" + node.pile : node.id; }

    rebuild(first) {  // the nodes and edges on screen now: folded piles become one dot each
      const nodes = [], seen = new Set();
      for (const n of this.data.nodes) {
        const id = this.rep(n);
        if (seen.has(id)) continue;
        seen.add(id);
        if (id === n.id) nodes.push({ ...n, r: this.radius(n) });
        else {
          const p = this.piles.get(n.pile), members = this.data.nodes.filter((m) => m.pile === n.pile);
          const cx = members.reduce((s, m) => s + this.pos.get(m.id).x, 0) / members.length, cy = members.reduce((s, m) => s + this.pos.get(m.id).y, 0) / members.length;
          if (!this.pos.has(id) || !first) this.pos.set(id, { x: cx, y: cy, vx: 0, vy: 0 });
          nodes.push({ id, kind: "pile", label: p.name, n: members.length, pile: n.pile, r: 7 + 3.2 * Math.sqrt(members.length), type: "", source: "" });
        }
      }
      const edges = new Map();
      for (const e of this.data.edges) {
        const a = this.rep(this.byId.get(e.a)), b = this.rep(this.byId.get(e.b));
        if (a === b) continue;
        const key = a < b ? a + "|" + b : b + "|" + a, old = edges.get(key);
        if (old) { old.count++; old.score = Math.max(old.score, e.score); }
        else edges.set(key, { a, b, score: e.score, why: e.why, count: 1, raw: a === e.a && b === e.b ? e : null, hub: !e.score });
      }
      this.nodes = nodes; this.nmap = new Map(nodes.map((n) => [n.id, n]));
      this.edges = [...edges.values()].filter((e) => this.nmap.has(e.a) && this.nmap.has(e.b));
      for (const e of this.edges) if (e.count > 1) e.why = e.hub ? "" : e.count + " links between these piles";
      this.alpha = Math.max(this.alpha, .9);
    }

    radius(n) { return n.id === this.centre ? 10 : n.kind === "post" ? 5 : n.kind === "thing" ? 4 + Math.min(4, n.n / 3) : 3.5 + Math.min(3, n.n / 4); }

    colour(n) { const p = this.piles.get(n.pile); return p ? PAL[p.colour] || this.col.fg : this.col.fg3; }

    // ---- physics ---------------------------------------------------------------------------------------------

    step() {
      const ns = this.nodes, P = this.pos, a = this.alpha;
      const grid = new Map(), S = 90;
      for (const n of ns) { const p = P.get(n.id), k = (p.x / S | 0) + "," + (p.y / S | 0); (grid.get(k) || grid.set(k, []).get(k)).push(n); }
      for (const n of ns) {
        const p = P.get(n.id), gx = p.x / S | 0, gy = p.y / S | 0;
        for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (const m of grid.get((gx + i) + "," + (gy + j)) || []) {
          if (m === n) continue;
          const q = P.get(m.id); let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy;
          if (d2 > S * S * 4) continue;
          if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
          const rr = n.r + m.r, f = (rr * rr * 3 + 400) / d2 * a, d = Math.sqrt(d2);
          p.vx += dx / d * f; p.vy += dy / d * f;
        }
      }
      for (const e of this.edges) {
        const p = P.get(e.a), q = P.get(e.b), dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 1;
        const rest = this.local ? (e.hub ? 95 : 110 - Math.min(e.score, 6) * 6) : e.hub ? 55 : e.count > 1 ? 150 : 36 + Math.max(0, 3 - e.score) * 14;
        const f = (d - rest) / d * (e.hub ? .012 : .03) * a;
        p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      }
      if (!this.local) {  // saves in one pile drift together
        const sum = new Map();
        for (const n of ns) if (n.kind === "post" && n.pile != null) { const p = P.get(n.id), s = sum.get(n.pile) || sum.set(n.pile, [0, 0, 0]).get(n.pile); s[0] += p.x; s[1] += p.y; s[2]++; }
        for (const n of ns) if (n.kind === "post" && n.pile != null) { const p = P.get(n.id), s = sum.get(n.pile); p.vx += (s[0] / s[2] - p.x) * .006 * a; p.vy += (s[1] / s[2] - p.y) * .006 * a; }
      }
      for (const n of ns) {
        const p = P.get(n.id);
        p.vx -= p.x * .0025 * a; p.vy -= p.y * .0025 * a;
        if (n === this.drag?.node || n.id === this.centre) { p.vx = p.vy = 0; if (n.id === this.centre && !this.drag?.node) { p.x *= .9; p.y *= .9; } continue; }
        p.vx *= .82; p.vy *= .82;
        const v = Math.hypot(p.vx, p.vy); if (v > 14) { p.vx *= 14 / v; p.vy *= 14 / v; }
        p.x += p.vx; p.y += p.vy;
      }
      this.alpha *= .985;
    }

    kick(heat) {
      if (heat) this.alpha = Math.max(this.alpha, heat);
      if (REDUCE) { this.settle(); this.draw(); return; }
      if (!this.raf && this.visible && !document.hidden) this.raf = requestAnimationFrame(() => this.frame());
    }

    settle() { for (let i = 0; i < Math.min(500, this.nodes?.length > 1500 ? 120 : 400) && this.alpha > .01; i++) this.step(); }

    frame() {
      this.raf = 0;
      if (!this.nodes) return;
      const busy = this.alpha > .012 || this.drag?.node;
      if (busy) { this.step(); this.step(); }
      this.draw();
      if (busy && this.visible && !document.hidden) this.raf = requestAnimationFrame(() => this.frame());
    }

    // ---- view ------------------------------------------------------------------------------------------------

    resize() {
      const r = this.root.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      this.w = r.width; this.h = r.height;
      this.canvas.width = Math.round(r.width * dpr); this.canvas.height = Math.round(r.height * dpr);
      this.dpr = dpr;
      if (this.nodes) { if (!this.fitted) this.fit(); this.draw(); }
    }

    fit() {
      if (!this.nodes || !this.w) return;
      this.settle();
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const n of this.nodes) { const p = this.pos.get(n.id); x0 = Math.min(x0, p.x - 30); x1 = Math.max(x1, p.x + 30); y0 = Math.min(y0, p.y - 20); y1 = Math.max(y1, p.y + 20); }
      const k = Math.min(this.w / (x1 - x0), this.h / (y1 - y0), this.local ? 2.4 : 1.5) * .92;
      this.view = { k, x: this.w / 2 - (x0 + x1) / 2 * k, y: this.h / 2 - (y0 + y1) / 2 * k };
      this.fitted = true;
    }

    centreOn(id) {
      const p = this.pos.get(this.rep(this.byId.get(id))); if (!p) return;
      this.view.k = Math.max(this.view.k, 1.6); this.view.x = this.w / 2 - p.x * this.view.k; this.view.y = this.h / 2 - p.y * this.view.k;
    }

    toWorld(px, py) { return [(px - this.view.x) / this.view.k, (py - this.view.y) / this.view.k]; }

    // ---- drawing ---------------------------------------------------------------------------------------------

    show(n) {
      const f = this.filter;
      if (f.pile && String(n.pile) !== f.pile) return false;
      if (f.type && n.kind === "post" && n.type !== f.type) return false;
      if (f.source && n.kind === "post" && n.source !== f.source) return false;
      if (f.text && !n.label.toLowerCase().includes(f.text)) return false;
      return true;
    }

    active() { const f = this.filter; return !!(f.pile || f.type || f.source || f.text); }

    draw() {
      if (!this.nodes) return;
      const c = this.ctx, { k, x, y } = this.view, col = this.col, act = this.active();
      c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0); c.clearRect(0, 0, this.w, this.h);
      c.translate(x, y); c.scale(k, k);
      const ok = new Map(this.nodes.map((n) => [n.id, !act || this.show(n)]));
      const near = this.hover?.kind === "node" ? new Set([this.hover.node.id, ...this.edges.filter((e) => e.a === this.hover.node.id || e.b === this.hover.node.id).flatMap((e) => [e.a, e.b])]) : null;
      c.lineCap = "round";
      for (const e of this.edges) {
        const p = this.pos.get(e.a), q = this.pos.get(e.b), a = this.nmap.get(e.a), b = this.nmap.get(e.b);
        const lit = ok.get(e.a) && ok.get(e.b), hot = this.hover?.edge === e || this.pinned?.edge === e || (near && near.has(e.a) && near.has(e.b) && (this.hover.node.id === e.a || this.hover.node.id === e.b));
        c.globalAlpha = (lit ? (e.hub ? .22 : .5) : .05) * (near && !hot ? .35 : 1) + (hot ? .4 : 0);
        c.strokeStyle = !e.hub && a.pile != null && a.pile === b.pile ? this.colour(a) : col.fg3;
        c.lineWidth = (e.hub ? .7 : .8 + Math.min(2.2, Math.max(0, e.score) * .5) + Math.min(2, (e.count - 1) * .4)) / Math.sqrt(k);
        if (e.hub) c.setLineDash([3 / k, 3 / k]); else c.setLineDash([]);
        c.beginPath(); c.moveTo(p.x, p.y); c.lineTo(q.x, q.y); c.stroke();
      }
      c.setLineDash([]);
      const labels = [];
      for (const n of this.nodes) {
        const p = this.pos.get(n.id), lit = ok.get(n.id), dim = (near && !near.has(n.id)) ? .3 : 1;
        c.globalAlpha = (lit ? 1 : .12) * dim;
        const colr = n.kind === "post" || n.kind === "pile" ? this.colour(n) : col.fg3;
        c.fillStyle = colr; c.strokeStyle = colr; c.lineWidth = 1.6 / k;
        if (n.kind === "thing") { c.save(); c.translate(p.x, p.y); c.rotate(.785); c.fillRect(-n.r * .7, -n.r * .7, n.r * 1.4, n.r * 1.4); c.restore(); }
        else if (n.kind === "tag") { c.beginPath(); c.arc(p.x, p.y, n.r, 0, 6.283); c.stroke(); }
        else { c.beginPath(); c.arc(p.x, p.y, n.r, 0, 6.283); c.fill(); if (n.kind === "pile") { c.globalAlpha *= .35; c.beginPath(); c.arc(p.x, p.y, n.r + 4, 0, 6.283); c.stroke(); } }
        if (n.id === this.centre || n.id === this.focusId) { c.globalAlpha = 1; c.strokeStyle = col.fg; c.lineWidth = 2 / k; c.beginPath(); c.arc(p.x, p.y, n.r + 4, 0, 6.283); c.stroke(); }
        if (act && lit && this.filter.text) { c.globalAlpha = 1; c.strokeStyle = col.fg; c.lineWidth = 1.5 / k; c.beginPath(); c.arc(p.x, p.y, n.r + 3, 0, 6.283); c.stroke(); }
        const crowded = !this.local && this.nodes.length > 60 && k < 1.3;  // a big map names only its big piles until you zoom in
        const named = this.hover?.node === n || this.pinned?.node === n || n.id === this.centre || this.local || k > 1.7
          || (n.kind === "pile" ? !crowded || n.n >= 10 : n.kind !== "post" && !crowded);
        if (named && (lit || this.hover?.node === n)) labels.push([n, p, dim]);
      }
      c.font = `${Math.max(10, 12 / Math.sqrt(k))}px "DM Sans", system-ui, sans-serif`; c.textBaseline = "middle";
      for (const [n, p, dim] of labels) {
        const text = n.kind === "pile" ? `${n.label} · ${n.n}` : n.label.length > 34 ? n.label.slice(0, 33) + "…" : n.label;
        const tx = p.x + n.r + 5 / k, ty = p.y;
        c.globalAlpha = dim; c.lineWidth = 3 / k; c.strokeStyle = col.bg; c.lineJoin = "round"; c.strokeText(text, tx, ty);
        c.fillStyle = n.kind === "post" ? col.fg : col.fg3; c.fillText(text, tx, ty);
      }
      c.globalAlpha = 1;
    }

    // ---- pointer ---------------------------------------------------------------------------------------------

    events() {
      const cv = this.canvas, at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      cv.addEventListener("pointerdown", (e) => {
        cv.setPointerCapture(e.pointerId); this.pointers.set(e.pointerId, at(e));
        if (this.pointers.size === 2) { this.drag = null; this.pinch = this.span(); return; }
        const [px, py] = at(e), hit = this.hitNode(px, py);
        this.drag = { sx: px, sy: py, node: hit, moved: false, vx: this.view.x, vy: this.view.y };
        if (hit) { this.kick(.3); }
      });
      cv.addEventListener("pointermove", (e) => {
        const [px, py] = at(e);
        if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, [px, py]);
        if (this.pointers.size === 2 && this.pinch) { const s = this.span(); this.zoomAt(this.mid(), s / this.pinch); this.pinch = s; return; }
        if (this.drag) {
          const dx = px - this.drag.sx, dy = py - this.drag.sy;
          if (Math.hypot(dx, dy) > 4) this.drag.moved = true;
          if (this.drag.moved) {
            if (this.drag.node) { const p = this.pos.get(this.drag.node.id), [wx, wy] = this.toWorld(px, py); p.x = wx; p.y = wy; this.kick(.3); this.draw(); }
            else { this.view.x = this.drag.vx + dx; this.view.y = this.drag.vy + dy; this.draw(); }
          }
          return;
        }
        this.look(px, py, e);
      });
      const up = (e) => {
        this.pointers.delete(e.pointerId); this.pinch = 0;
        const d = this.drag; this.drag = null;
        if (!d || d.moved) { this.kick(); return; }
        const [px, py] = at(e), hit = this.hitNode(px, py);
        if (hit) this.click(hit); else { const edge = this.hitEdge(px, py); this.pin(edge ? { edge } : null, e); }
      };
      cv.addEventListener("pointerup", up);
      cv.addEventListener("pointercancel", () => { this.pointers.clear(); this.drag = null; });
      cv.addEventListener("pointerleave", () => { if (!this.pinned) this.tip.hidden = true; this.hover = null; this.draw(); });
      cv.addEventListener("dblclick", (e) => {
        const [px, py] = at(e), hit = this.hitNode(px, py);
        if (hit?.kind === "post" && hit.pile != null && !this.local) { this.folded.add(hit.pile); this.rebuild(); this.kick(.5); }
      });
      cv.addEventListener("wheel", (e) => {
        if (this.local && !(e.ctrlKey || e.metaKey)) return;  // a small map leaves the page's scroll alone
        e.preventDefault(); this.zoomAt(at(e), Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0016)));
      }, { passive: false });
      this.root.addEventListener("click", (e) => { const b = e.target.closest("[data-cut]"); if (b) this.cut(); });
    }

    span() { const [a, b] = [...this.pointers.values()]; return Math.hypot(a[0] - b[0], a[1] - b[1]) || 1; }
    mid() { const [a, b] = [...this.pointers.values()]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; }

    zoomAt([px, py], f) {
      const v = this.view, k = Math.min(6, Math.max(.15, v.k * f)), r = k / v.k;
      v.x = px - (px - v.x) * r; v.y = py - (py - v.y) * r; v.k = k; this.draw();
    }

    hitNode(px, py) {
      const [wx, wy] = this.toWorld(px, py); let best = null, bd = 1e9;
      for (const n of this.nodes) {
        const p = this.pos.get(n.id), d = Math.hypot(p.x - wx, p.y - wy), reach = Math.max(n.r + 3, 9 / this.view.k);
        if (d < reach && d < bd) { best = n; bd = d; }
      }
      return best;
    }

    hitEdge(px, py) {
      const [wx, wy] = this.toWorld(px, py), reach = 6 / this.view.k; let best = null, bd = reach;
      for (const e of this.edges) {
        if (e.hub) continue;
        const p = this.pos.get(e.a), q = this.pos.get(e.b), dx = q.x - p.x, dy = q.y - p.y, l2 = dx * dx + dy * dy || 1;
        const t = Math.max(0, Math.min(1, ((wx - p.x) * dx + (wy - p.y) * dy) / l2)), d = Math.hypot(p.x + t * dx - wx, p.y + t * dy - wy);
        if (d < bd) { best = e; bd = d; }
      }
      return best;
    }

    look(px, py, e) {  // what the pointer is over, shown in the small caption
      const node = this.hitNode(px, py), edge = node ? null : this.hitEdge(px, py);
      this.canvas.style.cursor = node ? "pointer" : edge ? "help" : "grab";
      const was = this.hover;
      this.hover = node ? { kind: "node", node } : edge ? { kind: "edge", edge } : null;
      if (was?.node !== this.hover?.node || was?.edge !== this.hover?.edge) this.draw();
      if (!this.pinned) this.caption(this.hover, px, py);
    }

    caption(h, px, py) {
      if (!h) { this.tip.hidden = true; return; }
      this.tip.replaceChildren();
      if (h.node) {
        const n = h.node, p = this.piles.get(n.pile);
        this.tip.append(el("b", "", n.label));
        const sub = n.kind === "post" ? [typeName(n.type), srcName(n.source), p && p.name].filter(Boolean).join(" · ")
          : n.kind === "pile" ? `${n.n} saves · click to open the pile` : `${n.n} saves share this · click to search`;
        this.tip.append(el("small", "", sub));
      } else {
        const e = h.edge, a = this.nmap.get(e.a), b = this.nmap.get(e.b);
        this.tip.append(el("b", "", e.why || "Related"), el("small", "", `${a.label} ↔ ${b.label}`));
        if (this.canCut(e)) this.tip.append(el("small", "", "Click the line to say these are not related"));
      }
      this.place(px, py);
    }

    place(px, py) {
      this.tip.hidden = false;
      const w = this.tip.offsetWidth, h = this.tip.offsetHeight;
      this.tip.style.left = Math.max(6, Math.min(this.w - w - 6, px + 14)) + "px";
      this.tip.style.top = Math.max(6, Math.min(this.h - h - 6, py + 14)) + "px";
    }

    canCut(e) { return !!e.raw && !e.hub && e.a[0] === "p" && e.b[0] === "p" && e.a[1] !== "g"; }

    pin(h, ev) {
      this.pinned = h; this.draw();
      if (!h) { this.tip.hidden = true; return; }
      const r = this.canvas.getBoundingClientRect(), e = h.edge;
      this.caption({ edge: e }, ev.clientX - r.left, ev.clientY - r.top);
      if (this.canCut(e)) {
        const b = el("button", "cmap-cut", "Not related"); b.type = "button"; b.dataset.cut = "1";
        this.tip.append(b); this.place(ev.clientX - r.left, ev.clientY - r.top);
      }
    }

    async cut() {
      const e = this.pinned?.edge; if (!e || !this.canCut(e)) return;
      const body = new URLSearchParams({ csrf: csrf(), id: e.a.slice(1), other: e.b.slice(1), next: "/map" });
      try { await fetch("/hub/not-related", { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded" } }); }
      catch (err) { return; }
      this.data.edges = this.data.edges.filter((x) => !(x.a === e.a && x.b === e.b));
      this.pinned = null; this.tip.hidden = true; this.rebuild(); this.kick(.4); this.draw();
    }

    click(n) {
      if (n.kind === "post") return openPost(n.id.slice(1));
      if (n.kind === "pile") { this.folded.delete(n.pile); this.rebuild(); this.spread(n.pile, this.pos.get(n.id)); this.kick(.8); return; }
      const label = n.label.replace(/^#/, "");
      location.href = n.kind === "tag" ? "/?tag=" + encodeURIComponent(label) : "/?q=" + encodeURIComponent(label);
    }

    spread(pile, at) {  // saves leaving a folded pile start around its dot
      let i = 0;
      for (const n of this.data.nodes) if (n.pile === pile) { const p = this.pos.get(n.id), a = i++ * 2.399; p.x = at.x + Math.cos(a) * (12 + 5 * Math.sqrt(i)); p.y = at.y + Math.sin(a) * (12 + 5 * Math.sqrt(i)); p.vx = p.vy = 0; }
    }

    // ---- toolbar (the full map) ------------------------------------------------------------------------------

    toolbar() {
      if (this.bar) return;
      const bar = this.bar = el("div", "cmap-bar"), d = this.data;
      const search = el("input", "cmap-search"); search.type = "search"; search.placeholder = "Find a save on the map"; search.setAttribute("aria-label", "Find a save on the map");
      const sel = (name, label, opts) => {
        const s = el("select", "cmap-sel"); s.setAttribute("aria-label", label);
        s.append(new Option(label, ""), ...opts.map(([v, t]) => new Option(t, v)));
        s.addEventListener("change", () => { this.filter[name] = s.value; this.draw(); });
        return s;
      };
      search.addEventListener("input", () => { this.filter.text = search.value.trim().toLowerCase(); this.draw(); });
      search.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        const m = this.data.nodes.find((n) => n.kind === "post" && this.show(n));
        if (m) { this.folded.delete(m.pile); this.rebuild(); this.centreOn(m.id); this.kick(.3); }
      });
      const fold = el("button", "cmap-btn", this.folded.size ? "Open piles" : "Fold piles"); fold.type = "button";
      fold.addEventListener("click", () => {
        const open = this.folded.size > 0;
        if (open) this.folded.clear(); else d.piles.forEach((p) => this.folded.add(p.id));
        fold.textContent = open ? "Fold piles" : "Open piles"; this.rebuild(); this.fit(); this.kick(.8);
      });
      const fitb = el("button", "cmap-btn", "Fit"); fitb.type = "button"; fitb.addEventListener("click", () => { this.fit(); this.draw(); });
      const legend = el("span", "cmap-legend"); legend.append(el("i", "k-post"), "save", el("i", "k-thing"), "tool, place…", el("i", "k-tag"), "tag");
      bar.append(search,
        sel("pile", "All piles", d.piles.map((p) => [String(p.id), p.name])),
        sel("type", "All types", Object.keys(d.types).map((t) => [t, typeName(t)])),
        sel("source", "All sources", Object.keys(d.sources).map((s) => [s, srcName(s)])), fold, fitb, legend);
      this.root.before(bar);
    }
  }

  const mount = () => document.querySelectorAll(".cmap:not([data-mounted])").forEach((r) => { r.dataset.mounted = "1"; r.cmap = new CMap(r); });
  mount();
  document.addEventListener("DOMContentLoaded", mount);
  new MutationObserver(mount).observe(document.documentElement, { childList: true, subtree: true });
})();
