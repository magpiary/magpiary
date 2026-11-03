// Settings: the folded Advanced blocks, the search box, and the health check page.
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mem = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window: it just starts folded */ } },
  };

  // ---- Glass strength: four steps; the whole hub (and the slider itself) changes as it moves, and it is saved when let go ----------
  const gsOf = (v) => 0.3 + (v - 25) * 0.7 / 75;  // the same mapping as ui.glass_gs
  function glassSet(form, v) {
    document.documentElement.style.setProperty("--gs", gsOf(v).toFixed(3));
    const o = $("output", form); if (o) o.textContent = v + "%";
    $$(".glassticks button", form).forEach((b) => b.classList.toggle("on", Number(b.dataset.lv) === Number(v)));
  }
  document.addEventListener("input", (ev) => {
    const r = ev.target.closest("#glasslvl input[type=range]");
    if (r) glassSet(r.form, r.value);
  });
  const glassSave = (form) => fetch("/hub/ui", { method: "POST", body: new URLSearchParams(new FormData(form)), headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  document.addEventListener("change", (ev) => {
    const r = ev.target.closest("#glasslvl input[type=range]");
    if (r) glassSave(r.form);
  });
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("#glasslvl .glassticks button");
    if (!b) return;
    const r = $("input[type=range]", b.form); r.value = b.dataset.lv; glassSet(b.form, r.value); glassSave(b.form);
  });

  // ---- Advanced: starts folded, remembers being opened, opens itself when a link points inside it -------------------------
  const advKey = () => "mag-adv:" + location.pathname;
  function wireAdv() {
    $$("details.adv[data-adv]").forEach((d) => {
      if (d.dataset.wired) return;
      d.dataset.wired = "1";
      if (mem.get(advKey()) === "1") d.open = true;
      d.addEventListener("toggle", () => { if (!d.dataset.auto) mem.set(advKey(), d.open ? "1" : "0"); delete d.dataset.auto; });
    });
    reveal(decodeURIComponent(location.hash.slice(1)), true);
  }
  function reveal(id, quiet) {
    const t = id && document.getElementById(id);
    if (!t) return false;
    for (let d = t.closest("details"); d; d = d.parentElement?.closest("details")) {
      if (!d.open) { if (d.matches("details.adv")) d.dataset.auto = "1"; d.open = true; }
    }
    requestAnimationFrame(() => {
      t.scrollIntoView({ block: "center", behavior: calm || quiet ? "auto" : "smooth" });
      t.classList.remove("found"); void t.offsetWidth; t.classList.add("found");
      setTimeout(() => t.classList.remove("found"), 2200);
    });
    return true;
  }
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest?.('#setpane a[href^="#"]');
    if (!a) return;
    const id = decodeURIComponent(a.getAttribute("href").slice(1));
    if (reveal(id)) { ev.preventDefault(); history.replaceState(history.state, "", "#" + id); }
  }, true);
  // a link to a setting on another page loads that page whole, so its hash reaches the Advanced block
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest?.('a[href^="/settings/"][href*="#"]');
    if (!a || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    const u = new URL(a.href);
    if (u.pathname === location.pathname) return;
    ev.preventDefault(); ev.stopPropagation(); location.assign(u.pathname + u.hash);
  }, true);
  window.addEventListener("hashchange", () => reveal(decodeURIComponent(location.hash.slice(1))));
  let queued = false;
  new MutationObserver(() => {
    if (queued || !$("details.adv:not([data-wired])")) return;
    queued = true; requestAnimationFrame(() => { queued = false; wireAdv(); });
  }).observe(document.body, { childList: true, subtree: true });
  wireAdv();

  // ---- a button that pastes into the field it points at ------------------------------------------------------------------
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest?.("[data-paste]");
    if (!b) return;
    const field = $(b.dataset.paste);
    if (!field) return;
    try {
      field.value = (await navigator.clipboard.readText()).trim();
      field.dispatchEvent(new Event("input", { bubbles: true }));
      b.classList.add("done"); setTimeout(() => b.classList.remove("done"), 1400);
    } catch { field.focus(); field.placeholder = "Press ⌘V to paste"; }
  });

  // ---- a button that copies what it carries ------------------------------------------------------------------------------
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest?.("[data-copy]");
    if (!b) return;
    const label = b.innerHTML;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch { b.textContent = "Press ⌘C"; }
    setTimeout(() => { b.innerHTML = label; }, 1600);
  });

  // ---- the search box -----------------------------------------------------------------------------------------------------
  const PAGES = { profile: "Your profile", ai: "AI & digest", phones: "Saving posts", storage: "Library & this Mac", boards: "Shared boards", appearance: "Appearance", privacy: "Privacy" };
  let cursor = -1;
  document.addEventListener("input", (ev) => {
    const box = ev.target.closest?.("[data-setsearch] input");
    if (!box) return;
    const root = box.closest("[data-setsearch]"), list = $(".setresults", root);
    let index = [];
    try { index = JSON.parse(root.dataset.index); } catch { /* none */ }
    const words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = words.length ? index.filter(([t, k]) => words.every((w) => (t + " " + k).toLowerCase().includes(w))).slice(0, 7) : [];
    cursor = -1;
    list.innerHTML = hits.map(([t, , p, a]) => `<a role="option" href="/settings/${p}#${a}"><b>${t.replace(/</g, "&lt;")}</b><small>${PAGES[p] || p}</small></a>`).join("")
      || (words.length ? '<p class="none">Nothing matches that.</p>' : "");
    list.hidden = !words.length;
  });
  document.addEventListener("keydown", (ev) => {
    const box = ev.target.closest?.("[data-setsearch] input");
    if (!box) return;
    const list = $(".setresults", box.closest("[data-setsearch]")), opts = $$("a", list);
    if (ev.key === "Escape") { box.value = ""; list.hidden = true; box.blur(); return; }
    if (!opts.length) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      cursor = (cursor + (ev.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle("on", i === cursor));
    } else if (ev.key === "Enter") { ev.preventDefault(); (opts[Math.max(cursor, 0)]).click(); }
  });
  document.addEventListener("click", (ev) => {
    const hit = ev.target.closest?.(".setresults a");
    if (hit) {
      const box = hit.closest("[data-setsearch]");
      $(".setresults", box).hidden = true; $("input", box).value = "";
      const u = new URL(hit.href);
      if (u.pathname === location.pathname) { ev.preventDefault(); history.replaceState(history.state, "", u.hash); reveal(decodeURIComponent(u.hash.slice(1))); }
      return;
    }
    if (!ev.target.closest?.("[data-setsearch]")) $$(".setresults").forEach((l) => { l.hidden = true; });
  });

  // ---- the health check ----------------------------------------------------------------------------------------------------
  // Settings: the Run button goes to the health page, and the tick beside it asks for the site and key test as well.
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest?.("[data-health]");
    if (!b || !$("#health-live")?.checked) return;
    ev.preventDefault();
    try { sessionStorage.setItem("magpiary-health-live", "1"); } catch { /* the health page still has a live-test button */ }
    location.href = "/doctor";
  }, true);
  // The page: the quick checks are already drawn. The site and key test streams in, a row at a time, under the verdict.
  function initHealth() {
    const hc = $("#hc"); if (!hc) return;
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const wait = (ms) => new Promise((r) => setTimeout(r, calm ? Math.min(ms, 30) : ms));
    const bar = $("#hc-bar i"), sub = $("#hc-sub"), h1 = $("#hc-h1"), liveBtn = $("#hc-live");
    const known = () => new Set($$("[data-k]").map((r) => r.dataset.k));
    const rowHtml = (c) => {
      const cls = c.state === "problem" ? "bad" : c.state === "warning" ? "warn" : "ok";
      return `<div class="hk ${cls}" data-k="${esc(c.area)}|${esc(c.name)}" data-state="${cls}" data-name="${esc(c.name)}" data-detail="${esc(c.detail)}">`
        + `<span class="hkm">${cls === "ok" ? "✓" : "!"}</span><div class="hkt"><b>${esc(c.name)}</b><small>${esc(c.detail)}</small>`
        + (c.fix ? `<small class="fix">${esc(c.fix)}</small>` : "") + `</div>${c.link ? `<a class="btn sm" href="${esc(c.link)}">${esc(c.label)}</a>` : ""}</div>`;
    };
    let running = false;
    async function live() {
      if (running) return; running = true;
      liveBtn.disabled = true; liveBtn.classList.add("busy"); hc.classList.add("hc-run");
      $(".hc-orb", hc).innerHTML = '<i class="hc-spin"></i>';
      liveBtn.innerHTML = '<span class="hc-bspin"></span>' + "Testing…"; h1.textContent = "Testing each site and key"; sub.textContent = "One request at a time, gently. This takes up to a minute.";
      bar.style.width = "6%";
      let box = $("#hc-sites");
      if (!box) {
        box = document.createElement("details"); box.id = "hc-sites"; box.className = "hc-grp"; box.open = true;
        box.innerHTML = '<summary><span class="hc-area">Sites and keys</span><span class="hc-n" id="hc-sn">testing…</span></summary><div class="hc-list"></div>';
        $("#hc-groups").prepend(box);
      }
      const list = $(".hc-list", box), seen = known(); let since = 0, shown = 0, last = null;
      try {
        const started = await fetch("/hub/doctor", { method: "POST", cache: "no-store",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ csrf: $('meta[name="csrf"]')?.content || "", live: "1" }) });
        if (!started.ok) throw new Error("Could not start the checks. Reload the page and try again.");
        for (let i = 0; i < 600; i++) {
          const j = await (await fetch("/doctor.json?since=" + since, { cache: "no-store" })).json();
          since = j.next;
          for (const c of j.items) {
            if (seen.has(c.area + "|" + c.name)) continue;
            seen.add(c.area + "|" + c.name);
            if (c.state === "ok") list.insertAdjacentHTML("beforeend", rowHtml(c));
            else {  // anything not fine goes up with the other things to look at
              const need = $("#hc-need");
              if (need.hidden) { need.hidden = false; need.insertAdjacentHTML("beforebegin", '<h2 class="hc-h">Needs a look<span id="hc-nn">0</span></h2>'); }
              need.insertAdjacentHTML("beforeend", rowHtml(c));
              const n = $("#hc-nn") || $(".hc-h span"); if (n) n.textContent = $$("#hc-need .hk").length;
            }
            shown++;
            bar.style.width = Math.min(94, 6 + shown * 14) + "%";
            $("#hc-sn").textContent = shown + " tested";
            await wait(160);
          }
          if (j.done) { last = j; break; }
          await wait(300);
        }
      } catch { sub.textContent = "The test could not run."; }
      running = false; liveBtn.disabled = false; liveBtn.classList.remove("busy"); hc.classList.remove("hc-run");
      liveBtn.classList.add("hc-done"); liveBtn.textContent = "Tested ✓";
      setTimeout(() => { liveBtn.classList.remove("hc-done"); liveBtn.textContent = "Test sites and keys again"; }, 1800);
      bar.style.width = "100%";
      if (last) {
        const p = last.problems, w = last.warnings, tone = p ? "bad" : w ? "warn" : "ok";
        hc.className = "hc hc-" + tone;
        const orb = $(".hc-orb", hc); orb.innerHTML = tone === "ok" ? '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>' : "!"; orb.classList.add("hc-pop");
        h1.textContent = p ? `${p} thing${p === 1 ? "" : "s"} need${p === 1 ? "s" : ""} fixing` : w ? `Working, with ${w} thing${w === 1 ? "" : "s"} to look at` : "Everything works, sites and keys too";
        sub.textContent = `Sites and keys tested at ${new Date().toTimeString().slice(0, 5)}. Nothing was sent except one test request per site.`;
        $("#hc-sn").textContent = `${shown} tested`;
      }
    }
    liveBtn.addEventListener("click", live);
    $("#hc-copy").addEventListener("click", async (ev) => {
      const b = ev.currentTarget; if (b.classList.contains("busy")) return;
      const mark = { ok: "✓", warn: "!", bad: "✗" }, was = b.textContent;
      b.classList.add("busy"); b.innerHTML = '<span class="hc-bspin"></span>' + "Copying…";
      const text = "Magpiary health check\n" + $$("[data-k]").map((r) => `${mark[r.dataset.state]} ${r.dataset.name}: ${r.dataset.detail}`).join("\n");
      let ok = true;
      try { await navigator.clipboard.writeText(text); } catch { ok = false; }
      await wait(450);
      b.classList.remove("busy"); b.classList.toggle("hc-done", ok); b.textContent = ok ? "Copied ✓" : "Couldn't copy";
      setTimeout(() => { b.classList.remove("hc-done"); b.textContent = was; }, 1600);
    });
    // Run again: show the checking state at once, fetch a fresh page, and swap it in (never less than a second, so it reads as work)
    $("#hc-again").addEventListener("click", async (ev) => {
      ev.preventDefault();
      if (running || hc.classList.contains("hc-run")) return;
      const b = ev.currentTarget, orb = $(".hc-orb", hc), kept = orb.innerHTML, t0 = Date.now();
      hc.classList.add("hc-run", "hc-check"); b.classList.add("busy"); b.innerHTML = '<span class="hc-bspin"></span>' + "Checking…"; liveBtn.disabled = true;
      orb.innerHTML = '<i class="hc-spin"></i>'; h1.textContent = "Checking this Mac"; sub.textContent = "The tools, models, service, keys and your library…";
      try {
        const html = await (await fetch("/doctor", { cache: "no-store" })).text();
        await wait(Math.max(0, 1100 - (Date.now() - t0)));
        const fresh = new DOMParser().parseFromString(html, "text/html").getElementById("hc-page");
        if (!fresh) throw 0;
        $("#hc-page").replaceWith(fresh); initHealth(); $(".hc-orb")?.classList.add("hc-pop");
      } catch {
        hc.classList.remove("hc-run", "hc-check"); b.classList.remove("busy"); b.textContent = "Run again"; liveBtn.disabled = false; orb.innerHTML = kept;
        h1.textContent = "The check could not run"; sub.textContent = "Magpiary did not answer. Try again in a moment.";
      }
    });
    let queuedLive = false;
    try {
      queuedLive = sessionStorage.getItem("magpiary-health-live") === "1";
      sessionStorage.removeItem("magpiary-health-live");
    } catch { /* a click on the page can still start it */ }
    if (queuedLive) live();
  }
  initHealth();

  // ---- folds that glide open and shut --------------------------------------------------------------------------------------
  const FOLDS = "details.adv, details.advmini, details.padv, details.acc, details.homewifi, details.xmore";
  function foldKids(d) {
    const rest = [...d.children].filter((c) => c.tagName !== "SUMMARY");
    return (rest.length === 1 ? [...rest[0].children] : rest).slice(0, 8);
  }
  function glide(d) {
    const g = window.gsap, sum = d.querySelector(":scope > summary");
    d._t?.kill();
    const from = d.offsetHeight, opening = !d.open;
    d.style.overflow = "hidden";
    if (opening) {
      d.open = true;
      const to = d.scrollHeight;
      const kids = foldKids(d);
      g.set(kids, { opacity: 0, y: 8 });
      d._t = g.timeline({ onComplete: () => { d.style.height = d.style.overflow = ""; g.set(kids, { clearProps: "all" }); } })
        .fromTo(d, { height: from }, { height: to, duration: .42, ease: "power3.out" }, 0)
        .to(kids, { opacity: 1, y: 0, duration: .45, ease: "back.out(1.8)", stagger: .045 }, .06);
    } else {
      d.classList.add("shut");
      const kids = foldKids(d);
      d._t = g.timeline({ onComplete: () => { d.open = false; d.classList.remove("shut"); d.style.height = d.style.overflow = ""; g.set(kids, { clearProps: "all" }); } })
        .to(kids, { opacity: 0, y: -4, duration: .16, ease: "power1.in" }, 0)
        .to(d, { height: sum.offsetHeight, duration: .32, ease: "power3.inOut" }, .04);
    }
  }
  document.addEventListener("click", (ev) => {
    const sum = ev.target.closest?.("summary");
    const d = sum?.parentElement;
    if (!d || !d.matches(FOLDS) || calm || !window.gsap || !d.closest("#setpane")) return;
    ev.preventDefault();
    glide(d);
  }, true);

  // ---- a highlight that slides under the chosen switch --------------------------------------------------------------------
  function thumbFor(bar) {
    if (bar.dataset.thumb) return bar.querySelector(".thumb");
    bar.dataset.thumb = "1";
    const t = document.createElement("span"); t.className = "thumb"; t.setAttribute("aria-hidden", "true");
    bar.prepend(t); bar.classList.add("hasthumb");
    return t;
  }
  const chosen = (bar) => bar.querySelector('button.on, button[aria-checked="true"]') || bar.querySelector("input:checked + span");
  function place(bar, animate) {
    const el = chosen(bar), t = bar.querySelector(".thumb");
    if (!el || !t || !bar.offsetWidth) return;
    const br = bar.getBoundingClientRect(), r = el.getBoundingClientRect();
    const to = { x: r.left - br.left, width: r.width };
    const g = window.gsap;
    if (g && animate && !calm) { bar._moving = true; g.killTweensOf(t); g.to(t, { x: to.x, duration: .5, ease: "back.out(1.1)", onComplete: () => { bar._moving = false; } }); g.to(t, { width: to.width, duration: .4, ease: "power3.out" }); }
    else if (g) g.set(t, to);
    else { t.style.transform = `translateX(${to.x}px)`; t.style.width = to.width + "px"; }
  }
  function wireBars() {
    document.querySelectorAll("#setpane .segbar, #setpane .pillbar").forEach((bar) => {
      if (bar.dataset.thumb) return;
      thumbFor(bar); place(bar, false);
      new ResizeObserver(() => { if (!bar._moving) place(bar, false); }).observe(bar);
      document.fonts?.ready.then(() => place(bar, false));
    });
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest?.("#setpane .segbar button");
    const bar = b?.parentElement;
    if (!b || !bar?.dataset.thumb || calm) return;
    ev.preventDefault(); ev.stopPropagation();  // the highlight does the work; the page is told quietly afterwards
    if (b.classList.contains("on") || bar.dataset.busy) return;
    bar.dataset.busy = "1";
    bar.querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
    place(bar, true);
    // save quietly once the highlight has settled: the hub's own "working" mark would widen the button and make the highlight jump
    const form = bar.closest("form"), data = new FormData(form);
    data.append(b.name, b.value);
    setTimeout(async () => {
      try { await fetch(form.action, { method: "POST", body: new URLSearchParams(data), credentials: "same-origin" }); } catch { /* the reload shows what stuck */ }
      location.reload();
    }, 560);
  }, true);
  document.addEventListener("change", (ev) => {
    const bar = ev.target.closest?.("#setpane .pillbar");
    if (bar?.dataset.thumb) place(bar, true);
  });
  wireBars();
  new MutationObserver(() => requestAnimationFrame(wireBars)).observe(document.body, { childList: true, subtree: true });
})();

// Ask Magpiary: while Claude Code or Codex is being set up in the background, look again every few seconds
(() => { if (document.querySelector("[data-askwait]")) setTimeout(() => location.reload(), 3000); 
  // ---- AI keys: drag a key by its handle (or use the arrow keys on it) to change the order they are tried in ----------
  (() => {
    const list = $("[data-keylist]");
    if (!list) return;
    const csrf = $('meta[name="csrf"]')?.content || "";
    const rows = () => $$(".keyrow", list);
    const renumber = () => {};
    const save = () => fetch("/hub/keys/order", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ csrf, ids: rows().map((r) => r.id.startsWith("key-") ? "key:" + r.id.slice(4) : r.id.replace("local-", "")).join(","), next: "/settings/ai" }) });
    let drag = null;
    list.addEventListener("pointerdown", (ev) => {
      const handle = ev.target.closest("[data-keyhandle]");
      if (!handle) return;
      ev.preventDefault();
      const row = handle.closest(".keyrow");
      drag = { row, start: ev.clientY, moved: false };
      row.classList.add("dragging");
      handle.setPointerCapture(ev.pointerId);
    });
    list.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const { row } = drag;
      row.style.transform = `translateY(${ev.clientY - drag.start}px)`;
      const mid = row.getBoundingClientRect().top + row.offsetHeight / 2;
      const prev = row.previousElementSibling, next = row.nextElementSibling;
      const swap = (other, before) => {
        const shift = other.getBoundingClientRect().top;
        list.insertBefore(row, before ? other : other.nextSibling);
        drag.start += other.getBoundingClientRect().top - shift;  // keep the row under the finger after the swap
        row.style.transform = `translateY(${ev.clientY - drag.start}px)`;
        if (!calm) other.animate([{ transform: `translateY(${shift - other.getBoundingClientRect().top}px)` }, { transform: "none" }],
                                 { duration: 180, easing: "cubic-bezier(.2,.8,.2,1)" });
        drag.moved = true; renumber();
      };
      if (prev?.classList.contains("keyrow") && mid < prev.getBoundingClientRect().top + prev.offsetHeight / 2) swap(prev, true);
      else if (next?.classList.contains("keyrow") && mid > next.getBoundingClientRect().top + next.offsetHeight / 2) swap(next, false);
    });
    const drop = () => {
      if (!drag) return;
      const { row, moved } = drag;
      drag = null;
      row.classList.remove("dragging");
      row.style.transform = "";
      if (moved) save();
    };
    list.addEventListener("pointerup", drop);
    list.addEventListener("pointercancel", drop);
    list.addEventListener("keydown", (ev) => {
      const handle = ev.target.closest("[data-keyhandle]");
      if (!handle || !["ArrowUp", "ArrowDown"].includes(ev.key)) return;
      ev.preventDefault();
      const row = handle.closest(".keyrow"), other = ev.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
      if (!other?.classList.contains("keyrow")) return;
      list.insertBefore(row, ev.key === "ArrowUp" ? other : other.nextSibling);
      renumber(); handle.focus(); save();
    });
  })();
})();
