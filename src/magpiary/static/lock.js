// The hub lock in the browser: open tabs cover themselves the moment the hub locks, the PIN card, and Touch ID
// (the browser's passkey prompt at localhost). The rules are enforced by the service; this only asks and shows.
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  // the unlock card carries a fresh token; a tab left open across a restart still holds the old one in its <meta>
  const csrf = () => $('.lockcard input[name="csrf"]')?.value || $('meta[name="csrf"]')?.content || "";
  const FORM = { "Content-Type": "application/x-www-form-urlencoded" };
  const post = (action, fields) => fetch(action, { method: "POST", body: new URLSearchParams({ csrf: csrf(), ...fields }), headers: FORM });
  // an answer that is not JSON means Magpiary restarted under this tab (an expired page): start over with a fresh page
  const answer = async (r) => {
    try { return await r.json(); } catch (e) { setTimeout(() => location.reload(), 1200); return { error: "Magpiary was restarted. Reloading\u2026" }; }
  };
  const CRED = "mag-cred", OFFER = "mag-touch-offer", OFFER_NOW = "mag-touch-now";
  const get = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const put = (k, v) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* fine */ } };
  const b64d = (t) => Uint8Array.from(atob(t.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(t.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
  const b64e = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const canTouch = () => !!window.PublicKeyCredential && location.hostname === "localhost";
  // Touch ID is never hidden: when this browser can't use it the button is greyed out and says why
  const touchState = () => {
    if (!window.PublicKeyCredential) return { ok: false, hint: "This browser can't do Touch ID. Use your PIN." };
    if (location.hostname !== "localhost") return { ok: false, hint: "Open Magpiary at localhost:" + location.port + " to use Touch ID." };
    if (!get(CRED) || !ids.includes(get(CRED))) return { ok: false, hint: "Set up in Settings \u2192 Privacy." };
    return { ok: true, hint: "" };
  };
  const paintTouch = (btn, hint) => { const t = touchState(); btn.disabled = !t.ok; btn.title = t.hint; if (hint) hint.textContent = t.hint; return t.ok; };
  const standalone = () => !!$("#lockveil.standalone");

  let veil = null, saved = "", active = false, timer = 0, ids = [], on = false;

  // ---- Touch ID ----------------------------------------------------------------------------------------------------------------------
  async function challenge(purpose) {
    const r = await post("/hub/lock/challenge", { purpose });
    const d = await answer(r);
    if (!r.ok) throw new Error(d.error || "Not available.");
    return d;
  }

  async function touch(purpose) {
    const id = get(CRED);
    if (!id) throw new Error("Touch ID is not set up in this browser.");
    const d = await challenge(purpose);
    const cred = await navigator.credentials.get({ publicKey: {
      challenge: b64d(d.challenge), rpId: d.rp, allowCredentials: [{ type: "public-key", id: b64d(id) }], userVerification: "required", timeout: 60000 } });
    const a = cred.response;
    const r = await post("/hub/lock/verify", { purpose, id: b64e(cred.rawId), auth: b64e(a.authenticatorData), client: b64e(a.clientDataJSON), sig: b64e(a.signature) });
    const out = await answer(r);
    if (!r.ok || !out.ok) throw new Error(out.error || "That did not work.");
  }

  async function addTouch() {
    const d = await challenge("register");
    const cred = await navigator.credentials.create({ publicKey: {
      challenge: b64d(d.challenge), rp: { name: "Magpiary", id: d.rp }, user: { id: b64d(d.user), name: "magpiary", displayName: "Magpiary" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }], authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required", residentKey: "discouraged" },
      attestation: "none", timeout: 60000 } });
    const resp = cred.response;
    if (!resp.getPublicKey) throw new Error("This browser can't do Touch ID here. The PIN still works.");
    const ua = navigator.userAgent;
    const label = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "This browser";
    const r = await post("/hub/lock/register", { id: b64e(cred.rawId), key: b64e(resp.getPublicKey()), client: b64e(resp.clientDataJSON), label });
    const out = await answer(r);
    if (!r.ok || !out.ok) throw new Error(out.error || "That did not work.");
    put(CRED, b64e(cred.rawId));
  }

  const nice = (err) => (err && err.name === "NotAllowedError") ? "Touch ID was cancelled." : (err && err.message) || "That did not work.";

  // ---- the card ----------------------------------------------------------------------------------------------------------------------
  function done(card) {
    try { if (get(CRED) === null && canTouch() && get(OFFER) !== "no") sessionStorage.setItem(OFFER_NOW, "1"); } catch (e) { /* fine */ }
    if (standalone()) location.href = card.dataset.next || "/"; else location.reload();
  }

  function wireCard(card) {
    const pin = $(".lkpin", card), err = $(".lkerr", card), go = $(".lkgo", card), tbtn = $("[data-touch]", card);
    let clock = 0;
    const say = (t) => { err.textContent = t; };
    const hold = (secs) => {
      clearInterval(clock);
      const end = Date.now() + secs * 1000;
      const tick = () => {
        const left = Math.ceil((end - Date.now()) / 1000);
        if (left <= 0) { clearInterval(clock); pin.disabled = go.disabled = false; say(""); pin.focus(); return; }
        pin.disabled = go.disabled = true; say("Too many tries. Try again in " + left + " seconds.");
      };
      tick(); clock = setInterval(tick, 500);
    };
    if (+card.dataset.wait > 0) hold(+card.dataset.wait);
    const submit = async () => {
      if (pin.value.length !== 6) { say("The PIN is 6 digits."); return; }
      go.disabled = true;
      let d = {};
      try { d = await answer(await post("/hub/lock/pin", { pin: pin.value, json: "1" })); } catch (e) { d = { error: "Could not reach Magpiary." }; }
      if (d.ok) { done(card); return; }
      pin.value = ""; card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
      if (d.wait > 0) hold(d.wait); else { go.disabled = false; say(d.error || "That PIN is not right."); pin.focus(); }
    };
    card.addEventListener("submit", (ev) => { ev.preventDefault(); submit(); });
    pin.addEventListener("input", () => { pin.value = pin.value.replace(/\D/g, "").slice(0, 6); say(""); if (pin.value.length === 6) submit(); });
    const tryTouch = async () => {
      say("");
      try { await touch("unlock"); done(card); } catch (e) { say(nice(e)); pin.focus(); }
    };
    if (tbtn) {
      tbtn.addEventListener("click", tryTouch);
      if (paintTouch(tbtn, $("[data-touch-hint]", card))) {
        $("#lk-p", card).textContent = "Enter your 6-digit PIN, or use Touch ID.";
        if (standalone() && +card.dataset.wait === 0) tryTouch();
      }
    }
    pin.focus();
  }

  async function showVeil() {
    if (veil) return;
    const cover = document.createElement("div");
    cover.className = "lockveil"; cover.id = "lockveil";
    veil = cover;
    try {
      cover.innerHTML = await (await fetch("/lock?frag=1&next=" + encodeURIComponent(location.pathname + location.search), { cache: "no-store" })).text();
    } catch (e) { veil = null; return; }
    saved = document.title;
    document.title = "Magpiary";
    for (const el of [...document.body.children]) el.inert = true;
    document.documentElement.classList.add("islocked");
    document.body.append(cover);
    cover.inert = false;
    wireCard($(".lockcard", cover));
  }

  // ---- watching the lock -------------------------------------------------------------------------------------------------------------
  async function poll() {
    let d;
    try { d = await (await fetch("/lock.json" + (active ? "?a=1" : ""), { cache: "no-store" })).json(); } catch (e) { return; }
    active = false;
    on = d.on; ids = d.ids || [];
    if (get(CRED) && d.on && !ids.includes(get(CRED))) put(CRED, null);
    if (d.on && d.locked && !standalone()) showVeil();
  }

  if (standalone()) {
    fetch("/lock.json", { cache: "no-store" }).then((r) => r.json()).then((d) => { ids = d.ids || []; wireCard($(".lockcard")); });
    document.title = "Magpiary";
    return;
  }
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) addEventListener(ev, () => { active = true; }, { passive: true, capture: true });
  fetch("/lock.json", { cache: "no-store" }).then((r) => r.json()).then((d) => {
    on = d.on; ids = d.ids || [];
    if (get(CRED) && d.on && !ids.includes(get(CRED))) put(CRED, null);
    timer = setInterval(poll, 4000); // always: a tab opened before the lock was turned on must still cover itself
    if (d.on && d.locked) showVeil();
    afterLoad();
  }).catch(() => {});
  document.addEventListener("visibilitychange", () => { if (!document.hidden && on) poll(); });

  // ---- Settings → Privacy: the dialogs (PIN, Touch ID, confirm) -----------------------------------------------------------------
  // Everything here is delegated and wired when used: Settings pages arrive by hub.js swapping the view, not by a page load.
  const group = () => $("#lock[data-proven]");
  const here = () => !!get(CRED) && ids.includes(get(CRED));
  const proven = () => group()?.dataset.proven === "1";
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const showStep = (dlg, step) => { $$(".lkstep", dlg).forEach((p) => { p.hidden = p.dataset.step !== step; }); };

  // one step fades into the next inside the same dialog, and the title follows
  async function swap(dlg, step, title) {
    const from = $(".lkstep:not([hidden])", dlg), h = $(".lkdh h3", dlg);
    if (!calm && from && dlg.animate) await Promise.race([Promise.all([from, h].map((el) => el.animate({ opacity: [1, 0] }, { duration: 110, fill: "forwards" }).finished.catch(() => {}))),
      new Promise((r) => setTimeout(r, 300))]);  // never wait on an animation a hidden window may not run
    showStep(dlg, step);
    if (title) h.textContent = title;
    const to = $(`.lkstep[data-step="${step}"]`, dlg);
    if (!calm && dlg.animate) [to, h].forEach((el) => el.animate({ opacity: [0, 1], transform: ["translateY(6px)", "none"] }, { duration: 200, easing: "cubic-bezier(.2,.8,.2,1)" }));
    if (from) from.getAnimations().forEach((a) => a.cancel());
    h.getAnimations().filter((a) => a.effect.getComputedTiming().fill === "forwards").forEach((a) => a.cancel());
    ($("input.lkpin", to) || $("button.btn.dark", to))?.focus();
  }

  function wireDialog(dlg) {
    if (dlg.dataset.wired) return;
    dlg.dataset.wired = "1";
    dlg.addEventListener("click", (ev) => { if (ev.target === dlg || ev.target.closest("[data-lk-close]")) dlg.close(); });
    dlg.addEventListener("close", () => { if (dlg.dataset.reload) location.reload(); });
    let after = null; // what to do once the PIN or Touch ID is confirmed
    dlg._after = (f) => { after = f; };
    const proved = () => {
      const g = group(); if (g) g.dataset.proven = "1";
      if (after) { const f = after; after = null; dlg.close(); f(); } else swap(dlg, "main");
    };
    const form = $("[data-lk-confirm]", dlg);
    form?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const err = $(".lkerr", form), pin = $("input", form);
      let d = {};
      try { d = await answer(await post("/hub/lock/prove", { pin: pin.value, json: "1" })); } catch (e) { d = { error: "Could not reach Magpiary." }; }
      if (d.ok) { proved(); return; }
      pin.value = ""; err.textContent = d.error || "That PIN is not right."; pin.focus();
    });
    $("[data-touch-confirm]", dlg)?.addEventListener("click", async () => {
      try { await touch("confirm"); proved(); } catch (e) { $(".lkerr", form).textContent = nice(e); }
    });
    const pform = $("[data-lk-pin]", dlg);
    pform?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const err = $(".lkerr", pform), fields = Object.fromEntries(new FormData(pform));
      delete fields.csrf;
      let d = {};
      try { d = await answer(await post(pform.action, { ...fields, json: "1" })); } catch (e) { d = { error: "Could not reach Magpiary." }; }
      if (!d.ok) { err.textContent = d.error || "That did not work."; return; }
      // a first PIN goes straight on to Touch ID, inside this same dialog; a changed PIN just finishes
      if (/offer=touch/.test(d.next) && canTouch() && !here() && $('.lkstep[data-step="touch"]', dlg)) {
        dlg.dataset.reload = "1";
        await swap(dlg, "touch", "Set up Touch ID");
      } else location.href = d.next;
    });
    $$("[data-touch-add]", dlg).forEach((btn) => btn.addEventListener("click", async () => {
      const err = $("[data-touch-error]", dlg);
      btn.disabled = true; err.textContent = "";
      try { await addTouch(); delete dlg.dataset.reload; location.href = "/settings/privacy?note=" + encodeURIComponent("Touch ID is set up in this browser.") + "#lock"; }
      catch (e) { err.textContent = nice(e); btn.disabled = false; }
    }));
  }

  // the proof lasts two minutes on the Mac, and a page can stay open longer: ask before trusting what it was drawn with
  async function freshProof() {
    try {
      const d = await (await fetch("/lock.json", { cache: "no-store" })).json();
      const g = group(); if (g) g.dataset.proven = d.proven ? "1" : "0";
    } catch (e) { /* keep what the page says */ }
  }

  async function openDialog(name, step) {
    const dlg = $("#lkd-" + name);
    if (!dlg) return;
    wireDialog(dlg);
    await freshProof();
    const needs = dlg.dataset.confirmFirst === "1" && !proven();
    showStep(dlg, step || (needs ? "confirm" : "main"));
    $$(".lkerr", dlg).forEach((p) => { p.textContent = ""; });
    $$("input.lkpin", dlg).forEach((i) => { i.value = ""; });
    const tc = $("[data-touch-confirm]", dlg);
    if (tc) paintTouch(tc, $("[data-touch-hint]", dlg));
    dlg.showModal();
    ($("input.lkpin", dlg.querySelector(".lkstep:not([hidden])")) || $("button.btn.dark", dlg))?.focus();
  }

  document.addEventListener("click", (ev) => {
    const o = ev.target.closest("[data-lk-open]");
    if (o) { ev.preventDefault(); openDialog(o.dataset.lkOpen); }
  });
  // forms that change a lock setting ask for the PIN or Touch ID first when the last proof has run out
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest?.("form[data-lk-guard]");
    if (!f || f.dataset.passed) return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    const go = () => { f.dataset.passed = "1"; f.requestSubmit ? f.requestSubmit() : f.submit(); };
    freshProof().then(() => {
      if (proven()) { go(); return; }
      const dlg = $("#lkd-guard");
      wireDialog(dlg);
      dlg._after(go);
      openDialog("guard", "confirm");
    });
  }, true);
  document.addEventListener("change", (ev) => {
    const f = ev.target.closest?.("form[data-autosubmit]");
    if (f) f.requestSubmit ? f.requestSubmit() : f.submit();
  });

  // what the Touch ID row says depends on this browser; run when a page arrives (by load or by hub.js swapping the view)
  function decorate() {
    const g = group();
    if (!g) return;
    const note = $("[data-touch-note]", g), openBtn = $('[data-lk-open="touch"]', g);
    if (!canTouch()) {
      if (openBtn) openBtn.hidden = true;
      if (note) note.textContent = location.hostname === "localhost" ? "This browser can't do Touch ID here." : "Open Magpiary at localhost:" + location.port + " to use Touch ID.";
    } else if (here() && openBtn) {
      openBtn.textContent = "Set up again"; openBtn.className = "btn sm";
      if (note) note.textContent = "Set up in this browser.";
    }
  }
  let queued = 0;
  new MutationObserver(() => { cancelAnimationFrame(queued); queued = requestAnimationFrame(decorate); }).observe(document.body, { childList: true, subtree: true });

  function afterLoad() {
    decorate();
    let offer = false;
    try { offer = sessionStorage.getItem(OFFER_NOW) === "1"; sessionStorage.removeItem(OFFER_NOW); } catch (e) { /* fine */ }
    if (offer && !group() && canTouch() && !get(CRED) && get(OFFER) !== "no") showOffer();
  }

  function showOffer() {
    const box = document.createElement("div");
    box.className = "lkoffer"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Touch ID");
    box.innerHTML = '<b>Use Touch ID in this browser next time?</b><p>You would skip the PIN here. The PIN still works.</p>'
      + '<div><button class="btn sm dark" type="button" data-yes>Set it up</button><button class="btn sm" type="button" data-no>Not now</button></div><p class="lkerr" role="alert"></p>';
    document.body.append(box);
    $("[data-no]", box).addEventListener("click", () => { put(OFFER, "no"); box.remove(); });
    $("[data-yes]", box).addEventListener("click", async () => {
      try { await addTouch(); box.remove(); } catch (e) { $(".lkerr", box).textContent = nice(e); }
    });
  }
})();
