// Shared pieces for the C explorations: fictional covers, type colours, the A/A/A size
// control, and the lightbox with key moments pinned on the scene-frame timeline.
(function () {
  const M = window.MAG, F = window.MAG_FRAMES || {};
  const NO_THUMB = new Set([5, 12]);
  const esc = s => M.mark(s || "", "");
  const C = {
    esc,
    types: { "How-to": "howto", "News & opinion": "news", "Tool": "tool", "Design": "design", "Explainer": "explainer", "Discussion": "discussion", "Recipe": "recipe" },
    color: t => `var(--t-${C.types[t] || "none"})`,
    hasThumb: it => !it.noThumb && !NO_THUMB.has(it.id),
    grad: it => `linear-gradient(160deg,hsl(${it.hue} 70% 58%),hsl(${it.hue + 45} 65% 32%))`,
    bg: it => C.hasThumb(it) ? `url(example-cover.svg) center/cover, ${C.grad(it)}` : C.grad(it),
    secs: at => at.split(":").reduce((a, b) => a * 60 + +b, 0),
    frameSecs: path => +path.split("/").pop().replace(".jpg", "").replace("-", "."),
    shortTitle: it => it.title.split(/[:;—]/)[0].replace(/"/g, ""),
    // Size control: three "A"s, small to large. Persisted per viewer when storage allows.
    size(el, onChange) {
      let cur = "m";
      try { cur = localStorage.getItem("mag-size") || "m"; } catch (e) {}
      const set = v => {
        cur = v; document.documentElement.dataset.size = v;
        try { localStorage.setItem("mag-size", v); } catch (e) {}
        el.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.s === v));
        onChange && onChange(v);
      };
      el.innerHTML = [["s", "Small tiles"], ["m", "Medium tiles"], ["l", "Large tiles"]]
        .map(([s, l]) => `<button type="button" data-s="${s}" aria-label="${l}" title="${l}">A</button>`).join("");
      el.querySelectorAll("button").forEach(b => b.onclick = () => set(b.dataset.s));
      set(cur);
    },
    status(it) {
      return it.status === "summarising" ? `Being read · ${it.pct}%` : it.status === "waiting" ? "Not read yet" : it.status === "attention" ? "Couldn't open" : it.type;
    },
    lightbox(host, id, onClose) {
      const it = M.byId[id];
      if (!it || it.status === "attention") { host.classList.remove("on"); return; }
      const frames = F[id] || [];
      const dur = it.dur ? C.secs(it.dur) : 60;
      const pts = it.points.map((p, i) => [...p, i]).filter(p => p[0]);
      const done = it.status === "done";
      host.innerHTML = `<button class="lb-close" aria-label="Close">×</button>
        <div class="lb-stage"><div class="lb-media ${it.source === "youtube" || it.source === "linkedin" ? "wide" : ""}" style="background:${C.bg(it)}"><div class="lb-now" id="lb-now"></div><span class="lb-play">▶</span></div>
        ${frames.length ? `<div class="lb-tl"><div class="lb-track">${frames.map(f => `<div style="background:url(thumbs/${f}) center/cover"></div>`).join("")}
          ${pts.map(([at, , i]) => `<button class="lb-mk" data-k="${i}" style="left:${Math.min(97, C.secs(at) / dur * 100)}%">${i + 1}</button>`).join("")}</div>
          <div class="lb-lbl"><span>0:00</span><span>${frames.length} scene frames${pts.length ? " · key moments numbered" : ""}</span><span>${it.dur}</span></div></div>` : ""}</div>
        <div class="lb-info"><span class="lb-type" style="background:${C.color(it.type)}">${it.type || "Not read yet"}</span>
          <h2>${esc(it.title)}</h2><div class="lb-by">${it.author || ""} · ${M.sources[it.source]} · saved ${it.saved.toLowerCase()}</div>
          ${done ? `<p class="lb-sum">${esc(it.summary)}</p>
          ${it.points.length ? `<h4>Key moments</h4>${it.points.map(([at, t], i) => `<div class="lb-kp" data-k="${i}"><b>${i + 1}</b><div>${esc(t)}${at ? `<small>at ${at}</small>` : ""}</div></div>`).join("")}` : ""}
          ${it.extras ? `<h4>${it.type}</h4>${Object.entries(it.extras).map(([k, v]) => `<p class="lb-sum"><b>${k}:</b> ${esc(v)}</p>`).join("")}` : ""}
          ${it.discussion ? `<h4>The discussion</h4><p class="lb-sum">${esc(it.discussion)}</p>` : ""}
          ${it.things.length ? `<h4>Mentioned</h4><div class="lb-chips">${it.things.map(t => `<span>${t}</span>`).join("")}</div>` : ""}
          <h4>Tags</h4><div class="lb-chips">${it.tags.map(t => `<span>#${t}</span>`).join("")}<span class="dash">+ add</span></div>
          <div class="lb-act"><button>Open original ↗</button><button>Note</button><button>Done</button></div>`
          : `<p class="lb-sum" style="opacity:.7">${it.status === "summarising" ? `Being read right now: ${it.step.toLowerCase()} (${it.pct}%).` : "Waiting its turn. Here's the caption meanwhile:"}</p>${it.caption ? `<p class="lb-sum">${esc(it.caption)}</p>` : ""}`}</div>`;
      host.classList.add("on");
      host.querySelector(".lb-close").onclick = onClose;
      host.querySelectorAll("[data-k]").forEach(el => el.onclick = () => {
        const k = +el.dataset.k, p = it.points[k];
        host.querySelectorAll("[data-k]").forEach(x => x.classList.toggle("on", +x.dataset.k === k));
        const n = host.querySelector("#lb-now"); n.textContent = (p[0] ? p[0] + " · " : "") + p[1]; n.classList.add("show");
      });
    },
  };
  window.MAGC = C;
})();
