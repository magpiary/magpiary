// Contextual post tabs (views.py, hub_views.py): the clicking inside a category tab. Everything is delegated from the
// document, so a post opened over the library (inserted later) works without wiring. hub.js already does two things for
// us: every [data-tab] in a card switches panes (the More menu included), and every [data-t] button jumps the video.
// Each action answers on its own: a tick ticks and the count moves, a copy button says "Copied", the servings number
// changes and the amounts follow. No spinner; when saving fails, the tick goes back and the pane says so.
(() => {
  "use strict";
  const csrf = () => document.querySelector('meta[name="csrf"]')?.content || "";
  const FORM = { "Content-Type": "application/x-www-form-urlencoded" };
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pane = (el) => el.closest(".pvv");
  const say = (root, text) => { const live = root?.querySelector("[data-pvlive]"); if (live) { live.textContent = ""; setTimeout(() => { live.textContent = text; }, 30); } };

  // ---- the More menu (the foundation's bit): close it after a pick, on Escape and on a click outside -------------
  document.addEventListener("click", (ev) => {
    const t = ev.target instanceof Element ? ev.target : null;
    document.querySelectorAll("details.pvmore[open]").forEach((d) => { if (!t || !d.contains(t)) d.open = false; });
    if (!t) return;
    const tabs = t.closest(".pvtabs"), more = tabs?.querySelector(".pvmore");
    if (!more) return;
    if (t.closest(".pvmore a[data-tab]")) { more.open = false; more.classList.add("on"); }
    else if (t.closest("a[data-tab]")) more.classList.remove("on");
  });
  const place = (d) => {  // under its summary, right edges aligned, kept on screen
    const list = d.querySelector(".pvmorelist"), r = d.querySelector("summary").getBoundingClientRect();
    if (!list) return;
    const w = list.offsetWidth || 190;
    const x = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)), y = r.bottom + 6;
    list.style.left = x + "px"; list.style.top = y + "px";
    const got = list.getBoundingClientRect();  // a transformed ancestor (a post opened over the library) moves "fixed"
    if (Math.abs(got.left - x) > 1 || Math.abs(got.top - y) > 1) {
      list.style.left = (2 * x - got.left) + "px"; list.style.top = (2 * y - got.top) + "px";
    }
  };
  document.addEventListener("toggle", (ev) => {
    const d = ev.target; if (!(d instanceof HTMLDetailsElement) || !d.matches(".pvmore") || !d.open) return;
    place(d);
  }, true);
  const closeAll = () => document.querySelectorAll("details.pvmore[open]").forEach((d) => { d.open = false; });
  addEventListener("resize", closeAll);
  addEventListener("scroll", () => document.querySelectorAll("details.pvmore[open]").forEach(place), { passive: true, capture: true });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const open = document.querySelector("details.pvmore[open]");
    if (open) { ev.stopPropagation(); open.open = false; open.querySelector("summary")?.focus(); }
  }, true);

  // ---- saving a tick or the servings ----------------------------------------------------------------------------
  async function save(root, key, value) {
    const body = new URLSearchParams({ csrf: csrf(), id: root.dataset.pvid || "", tab: root.dataset.pvtab || "", key, value });
    try {
      const r = await fetch("/hub/pv/state", { method: "POST", body, headers: FORM, cache: "no-store" });
      const data = r.ok ? await r.json() : null;
      return !!(data && data.ok);
    } catch (e) { return false; }
  }

  function count(root) {
    const prog = root.querySelector("[data-pvprog]"); if (!prog) return;
    const n = root.querySelectorAll("input[data-pvkey]:checked").length;
    const out = prog.querySelector("[data-pvdone]"); if (out) out.textContent = String(n);
    prog.classList.toggle("all", n > 0 && n === +prog.dataset.total);
  }

  document.addEventListener("change", async (ev) => {
    const box = ev.target instanceof HTMLInputElement && ev.target.matches(".pvv input[data-pvkey]") ? ev.target : null;
    if (!box) return;
    const root = pane(box), row = box.closest("li"), on = box.checked;
    row?.classList.toggle("on", on);
    if (on && !calm) row?.animate([{ transform: "scale(.985)" }, { transform: "scale(1)" }], { duration: 220, easing: "cubic-bezier(.2,.9,.3,1)" });
    count(root);
    const name = row?.querySelector(".pvname")?.textContent || "Item";
    if (await save(root, box.dataset.pvkey, on ? "1" : "")) { say(root, `${name} ${on ? "ticked" : "unticked"}`); return; }
    box.checked = !on; row?.classList.toggle("on", !on); count(root);  // not saved: put it back and say so
    row?.classList.add("pvfail"); setTimeout(() => row?.classList.remove("pvfail"), 1600);
    say(root, "Couldn't save that tick. If the hub is locked, unlock it and try again.");
    flag(root, "Couldn't save that tick. If the hub is locked, unlock it and try again.");
  });

  function flag(root, text) {
    let p = root.querySelector(".pvflag");
    if (!p) { p = document.createElement("p"); p.className = "pvflag"; p.setAttribute("role", "status"); root.prepend(p); }
    p.textContent = text; clearTimeout(p._t); p._t = setTimeout(() => p.remove(), 5000);
  }

  // ---- the servings scaler (the Ingredients tab): the same rules as hub_views.scale_amount -----------------------
  const FRACS = { "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅙": "1/6", "⅚": "5/6" };
  const QTY = /^\s*(\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:[.,]\d+)?)(?:\s*([-–])\s*(\d+\/\d+|\d+(?:[.,]\d+)?))?/;
  const num = (t) => {
    t = t.replace(",", ".").trim();
    if (/\s/.test(t)) { const [w, f] = t.split(/\s+/); return +w + num(f); }
    if (t.includes("/")) { const [a, b] = t.split("/").map(Number); return b ? a / b : NaN; }
    return +t;
  };
  const show = (v, decimal) => {
    if (Math.abs(v - Math.round(v)) < 1e-9) return String(Math.round(v));
    if (!decimal && v < 10) {
      const eighths = Math.round(v * 8);
      if (eighths > 0 && Math.abs(eighths / 8 - v) < 1 / 50) {
        const whole = Math.floor(eighths / 8); let p = eighths % 8, q = 8;
        if (!p) return String(whole);
        while (p % 2 === 0) { p /= 2; q /= 2; }
        return (whole ? whole + " " : "") + p + "/" + q;
      }
    }
    return v.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  };
  function scale(amount, factor) {
    if (factor === 1 || !amount) return amount;
    let text = amount;
    for (const [sym, frac] of Object.entries(FRACS)) text = text.replace(new RegExp(`(\\d)\\s*${sym}`, "g"), `$1 ${frac}`).split(sym).join(frac);
    const m = QTY.exec(text); if (!m) return amount;
    const decimal = /[.,]/.test(m[0]);
    const a = num(m[1]), b = m[3] ? num(m[3]) : null;
    if (!isFinite(a) || (b !== null && !isFinite(b))) return amount;
    const lead = text.slice(0, text.length - text.trimStart().length);
    return lead + show(a * factor, decimal) + (b !== null ? m[2] + show(b * factor, decimal) : "") + text.slice(m[0].length);
  }
  const timers = new WeakMap();
  document.addEventListener("click", (ev) => {
    const b = ev.target instanceof Element ? ev.target.closest(".pvserv [data-pvservby]") : null; if (!b) return;
    const box = b.closest(".pvserv"), root = pane(box);
    const base = +box.dataset.base || 0, max = +box.dataset.max || 24, by = +b.dataset.pvservby;
    let chosen = by === 0 ? (base || 1) : Math.min(max, Math.max(1, (+box.dataset.chosen || base || 1) + by));
    box.dataset.chosen = String(chosen);
    const factor = base ? chosen / base : chosen;
    const out = box.querySelector(".pvservn"); out.textContent = base ? String(chosen) : "×" + chosen;
    if (!calm) out.animate([{ transform: `translateY(${by < 0 ? 6 : -6}px)`, opacity: .3 }, { transform: "none", opacity: 1 }], { duration: 200, easing: "ease-out" });
    box.querySelector('[data-pvservby="-1"]').disabled = chosen <= 1;
    box.querySelector('[data-pvservby="1"]').disabled = chosen >= max;
    box.querySelector('[data-pvservby="0"]').hidden = chosen === (base || 1);
    root.querySelectorAll(".pvamt[data-amt]").forEach((a) => {
      const next = scale(a.dataset.amt, factor);
      if (a.textContent !== next) { a.textContent = next; if (!calm) a.animate([{ backgroundColor: "color-mix(in srgb, var(--hi) 22%, transparent)" }, { backgroundColor: "transparent" }], { duration: 700 }); }
    });
    clearTimeout(timers.get(box));
    timers.set(box, setTimeout(async () => {
      const ok = await save(root, "servings", chosen === (base || 1) ? "" : String(chosen));
      say(root, ok ? (base ? `Amounts for ${chosen}` : `Amounts times ${chosen}`) : "Couldn't remember the servings; the amounts still changed here.");
      if (!ok) flag(root, "Couldn't remember the servings; the amounts still changed here.");
    }, 450));
  });

  // ---- copying (hex, code, prompts, quotes, a whole list) ---------------------------------------------------------
  async function writeCopy(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* the older way */ }
    const box = document.createElement("textarea"); box.value = text; box.style.position = "fixed"; box.style.opacity = "0";
    document.body.append(box); box.select(); let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    box.remove(); return ok;
  }
  function copied(btn, ok) {
    const label = btn.querySelector("span:not(.pvswc):not(.pvswt)") ;
    btn.classList.remove("pvdone", "pvbad"); void btn.offsetWidth;
    btn.classList.add(ok ? "pvdone" : "pvbad");
    if (label && !btn.classList.contains("pvsw")) { label.dataset.was ||= label.textContent; label.textContent = ok ? "Copied" : "Couldn't copy"; }
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.classList.remove("pvdone", "pvbad"); if (label?.dataset.was) { label.textContent = label.dataset.was; delete label.dataset.was; } }, 1600);
  }
  function listText(root) {
    const lines = [];
    root.querySelectorAll(".pvrows").forEach((ul) => {
      if (ul.dataset.group) lines.push((lines.length ? "\n" : "") + ul.dataset.group);
      ul.querySelectorAll("li").forEach((li) => {
        const amt = li.querySelector(".pvamt")?.textContent.trim(), name = li.querySelector(".pvname")?.textContent.trim();
        const done = li.querySelector("input")?.checked ? "[x] " : "[ ] ";
        lines.push("- " + done + (amt ? amt + " " : "") + name);
      });
    });
    return lines.join("\n");
  }
  document.addEventListener("click", async (ev) => {
    const b = ev.target instanceof Element ? ev.target.closest(".pvv [data-pvcopy], .pvv [data-pvcopylist]") : null; if (!b) return;
    const root = pane(b);
    const text = b.hasAttribute("data-pvcopylist") ? listText(root) : b.dataset.pvcopy;
    const ok = await writeCopy(text);
    copied(b, ok);
    say(root, ok ? `${b.dataset.pvwhat || "Text"} copied` : "Couldn't copy");
  });

  // ---- flashcards --------------------------------------------------------------------------------------------------
  const flip = (card, on) => {
    card.classList.toggle("flipped", on); card.setAttribute("aria-expanded", String(on));
    card.querySelector(".pvfcb")?.setAttribute("aria-hidden", String(!on));
    card.querySelector(".pvfcf")?.setAttribute("aria-hidden", String(on));
    const label = card.getAttribute("aria-label") || "";
    card.setAttribute("aria-label", label.replace(/(Show|Hide) the answer$/, on ? "Hide the answer" : "Show the answer"));
  };
  document.addEventListener("click", (ev) => {
    const t = ev.target instanceof Element ? ev.target : null; if (!t) return;
    const card = t.closest(".pvv .pvfc");
    if (card) { flip(card, !card.classList.contains("flipped")); return; }
    const all = t.closest(".pvv [data-pvflipall]"); if (!all) return;
    const on = all.getAttribute("aria-pressed") !== "true";
    pane(all).querySelectorAll(".pvfc").forEach((c) => flip(c, on));
    all.setAttribute("aria-pressed", String(on)); all.textContent = on ? "Hide all answers" : "Show all answers";
  });

  // ---- places: a dot on the little map shows its card ----------------------------------------------------------------
  document.addEventListener("click", (ev) => {
    const dot = ev.target instanceof Element ? ev.target.closest(".pvv [data-pvjumpto]") : null; if (!dot) return;
    ev.preventDefault();
    const card = document.getElementById(dot.dataset.pvjumpto); if (!card) return;
    card.scrollIntoView({ block: "nearest", behavior: calm ? "auto" : "smooth" });
    card.focus({ preventScroll: true });
    card.classList.remove("pvlit"); void card.offsetWidth; card.classList.add("pvlit");
  });

  // ---- events: an .ics file made here, in the browser (nothing is sent anywhere) ---------------------------------------
  const icsText = (s) => String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  const fold = (line) => { const out = []; while (line.length > 74) { out.push(line.slice(0, 74)); line = " " + line.slice(74); } out.push(line); return out.join("\r\n"); };
  function ics(d) {
    const ok = (v) => /^\d{8}(T\d{6})?$/.test(v || "");
    if (!ok(d.start) || !ok(d.end)) return "";
    const allday = d.allday === "1", stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
    const uid = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)) + "@magpiary.local";
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magpiary//Post view//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
      "UID:" + uid, "DTSTAMP:" + stamp,
      (allday ? "DTSTART;VALUE=DATE:" : "DTSTART:") + d.start, (allday ? "DTEND;VALUE=DATE:" : "DTEND:") + d.end,
      "SUMMARY:" + icsText(d.title)];
    if (d.place) lines.push("LOCATION:" + icsText(d.place));
    if (d.note) lines.push("DESCRIPTION:" + icsText(d.note));
    lines.push("END:VEVENT", "END:VCALENDAR");
    return lines.map(fold).join("\r\n") + "\r\n";
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target instanceof Element ? ev.target.closest(".pvv [data-pvical]") : null; if (!b) return;
    const root = pane(b), text = ics(b.dataset);
    if (!text) { say(root, "This date can't be added"); return; }
    const url = URL.createObjectURL(new Blob([text], { type: "text/calendar;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = ((b.dataset.title || "event").replace(/[^\p{L}\p{N} _-]+/gu, "").trim().slice(0, 60) || "event") + ".ics";
    a.hidden = true; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    const label = b.querySelector("span"); const was = label.textContent;
    b.classList.add("pvdone"); label.textContent = "Calendar file saved";
    setTimeout(() => { b.classList.remove("pvdone"); label.textContent = was; }, 2200);
    say(root, "Calendar file saved. Open it to add the event.");
  });

  // test hook for the smoke check (no effect on the page)
  window.MagpiaryViews = { scale, ics };
})();
