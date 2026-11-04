/* The toolbar panel: pair once, then save this page, or pick one post on a feed. */
const $ = (id) => document.getElementById(id);
const send = (msg) => chrome.runtime.sendMessage(msg);
const PICK_SITES = /(^|\.)(instagram\.com|threads\.com|threads\.net|reddit\.com|x\.com|twitter\.com|linkedin\.com)$/;
const SOURCE = { instagram: ["Instagram", "#c13584"], threads: ["Threads", "#8a8a8a"], reddit: ["Reddit", "#ff4500"],
  x: ["X", "#8a8a8a"], linkedin: ["LinkedIn", "#0a66c2"], other: ["Web page", "#8a8a8a"] };

function ago(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!(mins >= 0)) return "";
  if (mins < 2) return "just now";
  if (mins < 90) return `${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 36) return `${hours} hours ago`;
  const days = Math.round(hours / 24);
  return days < 45 ? `${days} days ago` : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function say(text, cls = "", el = $("msg")) { el.textContent = text; el.className = "note " + cls; }
function show(id) { for (const s of ["pair", "save", "done", "welcome"]) $(s).hidden = s !== id; }

async function shortcuts() {
  const all = await chrome.commands.getAll();
  const key = (name) => (all.find((c) => c.name === name) || {}).shortcut || "not set";
  $("key-open").textContent = key("_execute_action");
  $("key-pick").textContent = key("pick");
  $("pickkey").textContent = key("pick") === "not set" ? "" : key("pick");
}

async function hubStatus() {
  const r = await send({ type: "ping" }).catch(() => null);
  const old = !r;   // no answer from the background worker: it is an older copy until the extension is reloaded
  $("hub").className = "hubstat " + (!old && r.ok ? "ok" : "bad");
  $("hub").lastElementChild.textContent = old ? "Reload the extension" : r.ok ? "On this Mac" : "Magpiary isn't answering";
}

const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
let boardList = [{ id: "", name: "Just my library" }];

/** The board picker is our own list, not the browser's: it opens inline so the popup grows instead of clipping it. */
function setBoards(list) { boardList = [{ id: "", name: "Just my library" }, ...list]; renderPicker(); }
function renderPicker() {
  const ul = $("picklist");
  ul.innerHTML = "";
  for (const b of boardList) {
    const li = document.createElement("li");
    li.setAttribute("role", "option"); li.tabIndex = -1; li.dataset.id = b.id;
    li.setAttribute("aria-selected", String(b.id === $("board").value));
    const name = document.createElement("span"); name.textContent = b.name;
    li.append(name); li.insertAdjacentHTML("beforeend", CHECK);
    li.onclick = () => choose(b);
    ul.append(li);
  }
}
function choose(b) {
  $("board").value = b.id; $("picklabel").textContent = b.name; closePicker(true); renderPicker();
}
function openPicker() { renderPicker(); $("picklist").hidden = false; $("pickbtn").setAttribute("aria-expanded", "true"); (document.querySelector('#picklist [aria-selected="true"]') || $("picklist").firstChild).focus(); }
function closePicker(refocus) { $("picklist").hidden = true; $("pickbtn").setAttribute("aria-expanded", "false"); if (refocus) $("pickbtn").focus(); }
$("pickbtn").onclick = () => ($("picklist").hidden ? openPicker() : closePicker(false));
$("pickbtn").addEventListener("keydown", (e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); openPicker(); } });
$("picklist").addEventListener("keydown", (e) => {
  const items = [...$("picklist").children], i = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(i + 1, items.length - 1)].focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(i - 1, 0)].focus(); }
  else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(boardList[i]); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePicker(true); }
});

let hubPort = 8765;   // this Mac account's hub, found when the extension was paired

async function init() {
  send({ type: "hello" }).catch(() => {});   // lets the Mac know the extension is here and whether it is pinned
  hubPort = (await chrome.storage.local.get("port")).port || 8765;
  $("open").href = `http://localhost:${hubPort}/`;
  shortcuts();
  hubStatus();
  const st = await send({ type: "state" });
  $("unpair").hidden = !st.paired;
  if (!st.paired) { show("pair"); $("code").focus(); return; }
  // just paired: this screen stays until the person presses Got it, even if the panel is closed and opened again, because the
  // page they paired on is Magpiary itself and a quick press on Save would save that
  const { welcomePending } = await chrome.storage.local.get("welcomePending");
  if (welcomePending) { show("welcome"); $("gotit").focus(); return; }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = (tab && tab.url) || "";
  let host = "", port = "";
  try { const u = new URL(url); host = u.hostname.toLowerCase(); port = u.port; } catch (_) { /* chrome:// pages and the like */ }
  const onFeedSite = PICK_SITES.test(host);
  const onMagpiary = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(host) && Number(port) >= 8765 && Number(port) < 8785;   // Magpiary's own pages are never worth saving
  const cleaned = /^https?:/i.test(url) && !onMagpiary ? MagpiaryClean.clean(url) : { error: "not a web page" };
  show("save");
  $("pick").hidden = !onFeedSite;
  if (cleaned.error) {
    $("card").hidden = true; $("form").hidden = true; $("nopost").hidden = false;
    $("nopost").firstElementChild.textContent = onMagpiary ? "This is Magpiary" : onFeedSite ? "This page has many posts" : "This page can't be saved";
    $("nopost").lastElementChild.textContent = onMagpiary ? "Open a page or post you want to keep, then click the Magpiary icon." : onFeedSite ? "Choose the one you want, then save it." : "Magpiary saves web pages and posts.";
    if (onFeedSite) { $("pick").classList.add("dark"); $("pick").focus(); }
  } else {
    const [name, color] = SOURCE[cleaned.source] || SOURCE.other;
    $("pill").style.setProperty("--c", color);
    $("pill").lastElementChild.textContent = cleaned.source === "other" ? name : `${name} ${cleaned.kind || "post"}`;
    $("link").textContent = cleaned.url.replace(/^https?:\/\/(www\.)?/, "") + (cleaned.needsExpansion ? " · your Mac will expand this short link" : "");
    $("seenbox").hidden = cleaned.source !== "other";   // posts on the six feed sites are read by the Mac itself
    $("savego").onclick = () => doSave(cleaned, tab);
    $("addnote").onclick = () => { $("addnote").hidden = true; $("notebox").hidden = false; $("note").focus(); };
    $("note").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("savego").click(); });
    $("savego").focus();   // the shortcut opens this panel; Enter then saves
  }
  send({ type: "boards" }).then((list) => setBoards(list || []));
  if (!cleaned.error) {
    send({ type: "seen", urls: [cleaned.url] }).then((found) => {   // already in your library? asked of your Mac only
      const info = found && found[cleaned.url];
      if (!info || !info.saved) return;
      $("seen").hidden = false;
      $("seentitle").textContent = `Saved ${ago(info.last)}${info.count > 1 ? ` · ${info.count} times` : ""}`.replace("Saved  ", "Saved ");
      $("seenopen").href = `http://localhost:${hubPort}/item/${info.id}`;
      $("savego").firstChild.textContent = "Save again ";
    });
    send({ type: "suggest", url: cleaned.url }).then((sg) => {   // the board that fits, from what you've just been saving
      if (!sg) return;
      $("suggest").hidden = false;
      $("sugname").textContent = sg.name;
      $("sugwhy").textContent = sg.reason;
      $("sugbtn").onclick = () => {
        if (!boardList.some((b) => b.id === sg.id)) boardList.push({ id: sg.id, name: sg.name });
        choose({ id: sg.id, name: sg.name });
        $("suggest").hidden = true;
      };
    });
  }
  $("pick").onclick = async () => {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["clean.js", "pick.js"] });
    window.close();
  };
}

async function doSave(cleaned, tab) {
  $("savego").disabled = true;
  const seen = !$("seenbox").hidden && $("whatisee").checked && tab && tab.id != null;
  if (seen) say("Reading the page…");
  const r = await send(seen ? { type: "saveSeen", tabId: tab.id, url: cleaned.url, note: $("note").value, board: $("board").value }
                            : { type: "save", url: cleaned.url, note: $("note").value, board: $("board").value });
  if (r.state === "ok") {
    show("done");
    const [name] = SOURCE[cleaned.source] || SOURCE.other;
    $("donetitle").textContent = r.savedCount > 1 ? "Saved again" : "Saved to Magpiary";
    $("donesub").textContent = `${cleaned.source === "other" ? (seen && !r.linkOnly ? "The page as you see it" : "Web page") : name + " " + (cleaned.kind || "post")}${r.savedCount > 1 ? ` · saved ${r.savedCount} times` : ""}`
      + (seen && r.linkOnly ? " · this page had nothing to read, so the link was saved" : "");
    setTimeout(() => window.close(), 1400);
  } else if (r.state === "offline") {
    say("Magpiary isn't answering. It will save when your Mac is ready.", "warn");
  } else if (r.state === "full") {
    say("Five pages are already waiting for Magpiary. Open Magpiary on this Mac, then save again.", "warn");
    $("savego").disabled = false;
  } else if (r.state === "revoked") {
    say("This browser was removed in Magpiary. Unpair and pair it again.", "bad");
    $("savego").disabled = false;
  } else {
    say("That link can't be saved.", "bad");
    $("savego").disabled = false;
  }
}

$("code").addEventListener("input", () => {   // ABCD-EFGH-JKLM as you type
  const raw = $("code").value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12);
  $("code").value = raw.replace(/(.{4})(?=.)/g, "$1-");
});
$("pairgo").onclick = async () => {
  $("pairgo").disabled = true;
  const r = await send({ type: "pair", code: $("code").value });
  $("pairgo").disabled = false;
  if (r.ok) { await chrome.storage.local.set({ welcomePending: true }); await init(); } else say(r.reason, "bad", $("pairmsg"));
};
$("gotit").onclick = async () => { await chrome.storage.local.remove("welcomePending"); window.close(); };
$("code").addEventListener("keydown", (e) => { if (e.key === "Enter") $("pairgo").click(); });
$("unpair").onclick = async () => { await send({ type: "unpair" }); await chrome.storage.local.remove("welcomePending"); location.reload(); };
$("keys").onclick = () => chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
document.addEventListener("keydown", (e) => { if (e.key === "Tab") document.body.classList.add("kbd"); });   // a focus ring only once you navigate by keyboard
document.addEventListener("mousedown", () => document.body.classList.remove("kbd"));
init();
