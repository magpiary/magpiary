/* The menu-bar panel. The app hands it the state with window.magpiaryPanel(state) and the result of a save with window.magpiarySaved(result).
   state: { kind: running|setup|stopped|locked, saves, waiting, need, percent, hub, latest: [{id, title, thumb}] } */
(() => {
  const STATES = {
    running: ["Running", "var(--ok-t)"], reading: ["Reading", "#ffd27a"], attention: ["Needs you", "var(--pink)"],
    setup: ["Setting up", "#ffd27a"], stopped: ["Stopped", "var(--bad-t)"], locked: ["Locked", "var(--fg-3)"],
  };
  const SAVE_WORDS = { saved: "Saved ✓", again: "Already saved", none: "Copy a link first", bad: "Can’t save that link", failed: "Couldn’t save it", locked: "Unlock Magpiary first" };
  let S = { kind: "running", saves: 0, waiting: 0, need: 0, latest: [] };
  let logo = "", saveWord = "", saveTimer = 0;
  const panel = document.getElementById("panel");
  const send = (message) => window.webkit?.messageHandlers?.panel?.postMessage(message);
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function shown() {
    if (S.kind !== "running") return S.kind;
    return S.need ? "attention" : S.waiting ? "reading" : "running";
  }
  const head = () => {
    const [label, colour] = STATES[shown()];
    return `<div class="mb-phead"><span class="logo">${logo}magpiary</span><span class="mb-state" style="--c:${colour}"><i></i>${label}</span></div>`;
  };
  const note = (text) => `<p class="mb-note">${text}</p>`;
  const message = () => S.kind === "stopped" ? note("Saves wait safely on your phone until Magpiary is back.")
    : S.kind === "setup" ? note("This happens once. You can close the window; it keeps going.")
    : S.kind === "locked" ? note("Magpiary is locked. Open it to unlock.")
    : !S.saves && !S.waiting ? note("Nothing saved yet. Share a post from your iPhone and it lands here.") : "";
  const progress = () => S.kind === "setup"
    ? `<div class="mb-progress"><div class="mb-prow"><span>Getting ready</span><b>${S.percent || 0}%</b></div><div class="mb-pbar"><i style="width:${S.percent || 0}%"></i></div></div>`
    : S.kind === "running" && S.waiting
    ? `<div class="mb-progress"><div class="mb-prow"><span>Reading ${S.waiting} new save${S.waiting === 1 ? "" : "s"}</span></div><div class="mb-pbar mb-moving"><i></i></div></div>` : "";
  const library = () => S.kind === "running" && S.saves
    ? `<label class="mb-psearch"><span>⌕</span><input id="q" type="text" placeholder="Search your saves" aria-label="Search your saves" autocomplete="off" spellcheck="false"></label>`
      + (S.latest.length ? `<div class="mb-recent"><small>Latest</small>${S.latest.map((p) => `<button class="mb-rrow" data-item="${Number(p.id)}"><i>${p.thumb ? `<img alt="" src="${esc(S.hub + p.thumb)}" onerror="this.remove()">` : ""}</i><span>${esc(p.title)}</span></button>`).join("")}</div>` : "") : "";
  const main = () => {
    const [label, action] = S.kind === "stopped" ? ["Start Magpiary", "start"] : S.kind === "setup" ? ["Show the installer", "installer"]
      : S.kind === "running" && S.need ? ["See what needs you", "open:/nest"] : ["Open Library", "open:/"];
    return `<button class="btn dark mb-wide" data-a="${action}">${label}</button>`;
  };
  const foot = () => {
    const save = S.kind === "running"
      ? `<button class="mb-tlink mb-save${saveWord === "saved" ? " mb-done" : ""}" data-a="save"${saveWord ? " disabled" : ""}>${saveWord ? SAVE_WORDS[saveWord] : "Save copied link"}</button>` : "<span></span>";
    return `<div class="mb-foot">${save}<button class="mb-tlink" data-a="quit">Quit</button></div>`;
  };

  function draw() {
    const box = document.getElementById("q");
    const typed = box ? box.value : "", focused = box && document.activeElement === box;
    panel.innerHTML = head() + message() + progress() + library() + main() + foot();
    const again = document.getElementById("q");
    if (again) { again.value = typed; if (focused) again.focus(); }
    send({ height: panel.offsetHeight });
  }

  document.addEventListener("click", (e) => {
    const row = e.target.closest("[data-item]");
    if (row) return send({ action: `open:/item/${row.dataset.item}` });
    const button = e.target.closest("[data-a]");
    if (button && !button.disabled) send({ action: button.dataset.a });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") send({ action: "close" });
    if (e.key === "Enter" && e.target.id === "q" && e.target.value.trim()) { send({ search: e.target.value.trim() }); e.target.value = ""; }
  });
  window.magpiaryPanel = (state) => {
    const same = JSON.stringify(state) === JSON.stringify(S);
    S = state;
    if (!same) draw();
  };
  window.magpiarySaved = (result) => {
    saveWord = result;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveWord = ""; draw(); }, 2500);
    draw();
  };
  fetch("/static/icon.svg").then((r) => r.text()).then((svg) => {
    logo = svg.replace(/<style>[\s\S]*?<\/style>/, "").replace(/class="k"/g, 'fill="currentColor"').replace("<svg ", '<svg class="mark" aria-hidden="true" ');
    draw();
  }).catch(draw);
  draw();
})();
