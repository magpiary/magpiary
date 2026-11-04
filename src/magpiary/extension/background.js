/* Magpiary background worker. Talks to the hub on this Mac only, over localhost, with the key from pairing.
 * It sends the cleaned link, the optional note and board, and nothing else: no page text, title, cookies or history.
 * Only when the owner ticks "Save what I see" does it also send the page as it is drawn (its text and pictures, one
 * screenshot of the visible part and the browser's own copy of the page), and only to this Mac.
 * It makes no request to any site. */
importScripts("clean.js");

// One hub per Mac account: the first uses port 8765, the next account 8766, and so on. Pairing finds the one that issued the code.
const PORTS = Array.from({ length: 20 }, (_, i) => 8765 + i);
const ACK = "magpiary-ok";
const RETRY_ALARM = "magpiary-retry";

const store = {
  get: async (keys) => chrome.storage.local.get(keys),
  set: async (obj) => chrome.storage.local.set(obj),
};

function itemId() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  return `${stamp}-${100000 + (crypto.getRandomValues(new Uint32Array(1))[0] % 900000)}`;
}

/** The phone stamps shares in the owner's local time, and the hub files a post under Today by that date: so must we (not UTC). */
function localStamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const off = -d.getTimezoneOffset();   // minutes east of UTC; the hub reads a stamp without an offset as local time
  const zone = `${off < 0 ? "-" : "+"}${p(Math.floor(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}`;
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${zone}`;
}

async function hub(path, { method = "GET", body, key, timeout = 0, port } = {}) {
  if (!port) port = (await chrome.storage.local.get("port")).port || PORTS[0];
  const headers = {};
  if (key) headers.Authorization = `Bearer ${key}`;
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(`http://127.0.0.1:${port}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: "no-store", signal: timeout ? AbortSignal.timeout(timeout) : undefined });
  let json = null;
  try { json = await r.json(); } catch (_) { /* a refusal may have no body */ }
  return { status: r.status, json };
}

// One change to the outbox at a time: a save made while a send is in flight must not be overwritten by that send's old copy.
let outboxLock = Promise.resolve();
function withOutbox(fn) {
  const run = outboxLock.then(fn, fn);
  outboxLock = run.catch(() => {});
  return run;
}
const BATCH = 200;              // the Mac takes at most 1,000 items and 1 MB a request: send in slices so a long queue still drains
const BATCH_BYTES = 512 * 1024;

function slice(outbox) {
  const out = [];
  let bytes = 0;
  for (const item of outbox) {
    const size = JSON.stringify(item).length + 1;
    if (out.length && (out.length >= BATCH || bytes + size > BATCH_BYTES)) break;
    out.push(item);
    bytes += size;
  }
  return out;
}

/** Send everything waiting, a slice at a time. The outbox is cleared only for items the Mac acknowledged. */
function flush() {
  return withOutbox(async () => {
    const { key } = await store.get(["key"]);
    if (!key) return { state: "unpaired" };
    let results = [], message;
    for (;;) {
      const { outbox = [] } = await store.get(["outbox"]);
      if (!outbox.length) return { state: "ok", waiting: 0, results, message };
      const batch = slice(outbox);
      let reply;
      try {
        reply = await hub("/v1/items", { method: "POST", body: { items: batch }, key });
      } catch (_) {
        await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
        return { state: "offline", waiting: outbox.length, results };
      }
      if (reply.status === 401) return { state: "revoked", waiting: outbox.length, results };
      if (!(reply.status === 200 && reply.json && reply.json.ack === ACK)) {
        await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
        return { state: "offline", waiting: outbox.length, results };
      }
      const done = new Set([...(reply.json.accepted || []), ...(reply.json.rejected || []).map((r) => r.id)]);
      const latest = (await store.get(["outbox"])).outbox || [];   // read again: a save may have arrived meanwhile
      const left = latest.filter((i) => !done.has(i.id));
      await store.set({ outbox: left });
      results = results.concat(reply.json.results || []);
      message = reply.json.message || message;
      if (!batch.some((i) => done.has(i.id))) return { state: "ok", waiting: left.length, results, message };  // no progress: stop
    }
  });
}

async function save({ url, note = "", board = "" }) {
  const { key } = await store.get(["key"]);
  if (!key) return { state: "unpaired" };
  const cleaned = MagpiaryClean.clean(url);
  if (cleaned.error) return { state: "unsupported", error: cleaned.error };
  const item = { id: itemId(), url: cleaned.url, shared_at: localStamp(), note: String(note).slice(0, 2000), v: 1 };
  if (/^[0-9a-f]{16}$/.test(board)) item.board = board;
  await withOutbox(async () => {
    const { outbox = [] } = await store.get(["outbox"]);
    await store.set({ outbox: [...outbox, item] });
  });
  const sent = await flush();
  const mine = (sent.results || []).find((r) => r.id === item.id);
  return { ...sent, url: cleaned.url, source: cleaned.source, savedCount: mine ? mine.saved_count : undefined };
}

// ---- "Save what I see": captures wait in IndexedDB (they can be megabytes), at most a few, until this Mac acknowledges each one

const CAPTURE_MAX_BYTES = 47 * 1000 * 1000;   // the Mac takes 48 MB a capture
const CAPTURE_WAITING = 5;

function captureDb() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("magpiary", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("captures", { keyPath: "capture" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function captures(mode, fn) {
  const db = await captureDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("captures", mode);
      const req = fn(tx.objectStore("captures"));
      tx.oncomplete = () => resolve(req && req.result);
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

async function base64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

/** Read the open tab as the owner sees it. Chrome lets us because the owner opened the panel on this tab and pressed Save. */
async function readTab(tab) {
  const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["capture.js"] });
  const page = result && result.result;
  if (!page || !Array.isArray(page.blocks) || !page.blocks.length) return null;
  let screen = "", mhtml = "";
  try { screen = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 72 }); } catch (_) { /* a page Chrome won't picture */ }
  try {
    const blob = await chrome.pageCapture.saveAsMHTML({ tabId: tab.id });   // the browser's own copy, from memory: the backup for pictures
    if (blob && blob.size < 30 * 1000 * 1000) mhtml = await base64(blob);
  } catch (_) { /* no copy: the Mac downloads the pictures itself */ }
  const body = { page, screen, mhtml };
  if (JSON.stringify(body).length > CAPTURE_MAX_BYTES) body.mhtml = "";
  if (JSON.stringify(body).length > CAPTURE_MAX_BYTES) body.screen = "";
  return body;
}

/** Send every waiting capture, oldest first. Each is removed only when the Mac's reply names it. */
let captureLock = Promise.resolve();
function flushCaptures() {
  const run = captureLock.then(async () => {
    const { key } = await store.get(["key"]);
    if (!key) return { state: "unpaired" };
    const waiting = ((await captures("readonly", (s) => s.getAll())) || []).sort((a, b) => a.at - b.at);
    const results = [];
    for (const c of waiting) {
      let reply;
      try {
        reply = await hub("/v1/capture", { method: "POST", body: { capture: c.capture, item: c.item, page: c.page, screen: c.screen, mhtml: c.mhtml }, key });
      } catch (_) {
        await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
        return { state: "offline", waiting: waiting.length - results.length, results };
      }
      if (reply.status === 401) return { state: "revoked", waiting: waiting.length - results.length, results };
      if (reply.status === 400 || reply.status === 413) {   // the Mac can't take this capture: keep the save as a plain link
        await captures("readwrite", (s) => s.delete(c.capture));
        await withOutbox(async () => { const { outbox = [] } = await store.get(["outbox"]); await store.set({ outbox: [...outbox, c.item] }); });
        await flush();
        results.push({ id: c.item.id, status: "link_only" });
        continue;
      }
      if (!(reply.status === 200 && reply.json && reply.json.ack === ACK && reply.json.capture === c.capture)) {
        await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
        return { state: "offline", waiting: waiting.length - results.length, results };
      }
      await captures("readwrite", (s) => s.delete(c.capture));
      results.push(...(reply.json.results || []));
    }
    return { state: "ok", waiting: 0, results };
  });
  captureLock = run.catch(() => {});
  return run;
}

async function saveSeen({ tabId, url, note = "", board = "" }) {
  const { key } = await store.get(["key"]);
  if (!key) return { state: "unpaired" };
  const cleaned = MagpiaryClean.clean(url);
  if (cleaned.error) return { state: "unsupported", error: cleaned.error };
  const waiting = (await captures("readonly", (s) => s.count())) || 0;
  if (waiting >= CAPTURE_WAITING) return { state: "full" };
  let tab;
  try { tab = await chrome.tabs.get(tabId); } catch (_) { return { state: "error" }; }
  const read = await readTab(tab).catch(() => null);
  if (!read) return { ...(await save({ url, note, board })), linkOnly: true };   // nothing readable: saved as a link
  const item = { id: itemId(), url: cleaned.url, shared_at: localStamp(), note: String(note).slice(0, 2000), v: 1 };
  if (/^[0-9a-f]{16}$/.test(board)) item.board = board;
  const capture = item.id;
  await captures("readwrite", (s) => s.put({ capture, at: Date.now(), item, ...read }));
  const sent = await flushCaptures();
  const mine = (sent.results || []).find((r) => r.id === item.id);
  return { ...sent, url: cleaned.url, source: cleaned.source, savedCount: mine ? mine.saved_count : undefined, linkOnly: Boolean(mine && mine.status === "link_only") };
}

async function boards() {
  const { key } = await store.get(["key"]);
  if (!key) return [];
  try {
    const r = await hub("/v1/boards", { key });
    if (r.status !== 200 || !r.json) return [];
    const today = new Date();
    const stamp = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, "0")}${String(today.getDate()).padStart(2, "0")}`;
    return String(r.json.boards || "").split("\n").map((line) => line.split("\t")).filter((p) => p.length === 3 && p[0].split(" ").includes(stamp)).map((p) => ({ name: p[1], id: p[2] }));
  } catch (_) {
    return [];
  }
}

/** Ask the hub about links: already saved? which board fits? Answers come from this Mac only; any failure is just "no answer". */
async function ask(path, body) {
  const { key } = await store.get(["key"]);
  if (!key) return null;
  try {
    const r = await hub(path, { method: "POST", body, key, timeout: 4000 });
    return r.status === 200 ? r.json : null;
  } catch (_) {
    return null;
  }
}

async function pair(code) {
  let reached = 0, refused = false;
  for (const port of PORTS) {   // the code only works on the hub that made it, so try each Magpiary on this Mac
    try {
      const r = await hub("/v1/pair", { method: "POST", body: { code }, port, timeout: 2000 });
      reached += 1;
      if (r.status === 200 && r.json && r.json.key) {
        await store.set({ key: r.json.key, port });
        return { ok: true };
      }
      if (r.status === 403) refused = true;
    } catch (_) { /* nothing listens on this port */ }
  }
  if (!reached) return { ok: false, reason: "Magpiary is not running on this Mac." };
  return { ok: false, reason: refused ? "That code was not accepted. It works once, for 15 minutes." : "Magpiary did not accept that." };
}

async function state() {
  const { key, outbox = [] } = await store.get(["key", "outbox"]);
  const seen = await captures("readonly", (s) => s.count()).catch(() => 0);
  return { paired: Boolean(key), waiting: outbox.length + (seen || 0) };
}

/** Tell the Mac this extension is installed, and whether its button is on the toolbar. Local address only; no key, no page data. */
async function hello() {
  let pinned = null;
  try { pinned = Boolean((await chrome.action.getUserSettings()).isOnToolbar); } catch (_) { /* older Chrome: not known */ }
  const { port } = await store.get(["port"]);
  for (const p of port ? [port] : PORTS) {
    try { await hub("/v1/hello", { method: "POST", body: { v: chrome.runtime.getManifest().version, pinned }, port: p, timeout: 1500 }); } catch (_) { /* nothing listens here */ }
  }
  return {};
}

async function badge(tabId, text, color) {
  await chrome.action.setBadgeBackgroundColor({ color, tabId });
  await chrome.action.setBadgeText({ text, tabId });
  setTimeout(() => chrome.action.setBadgeText({ text: "", tabId }).catch(() => {}), 2500);
}

async function ping() {
  try { return { ok: (await hub("/v1/ping", { timeout: 2500 })).status === 200 }; } catch (_) { return { ok: false }; }
}

chrome.runtime.onMessage.addListener((msg, sender, respond) => {
  const run = { state, ping, hello, seen: () => ask("/v1/seen", { urls: msg.urls }).then((r) => (r && r.results) || {}), suggest: () => ask("/v1/suggest", { url: msg.url }).then((r) => (r && r.suggestion) || null), pair: () => pair(msg.code), save: () => save(msg), saveSeen: () => saveSeen(msg), boards, flush, unpair: async () => { await store.set({ key: "" }); return {}; } }[msg && msg.type];
  if (!run) return false;
  Promise.resolve(run()).then(respond, () => respond({ state: "error" }));
  return true;
});

chrome.alarms.onAlarm.addListener((a) => { if (a.name === RETRY_ALARM) { flush(); flushCaptures(); } });
chrome.runtime.onStartup.addListener(() => { flush(); flushCaptures(); hello(); });
if (chrome.action.onUserSettingsChanged) chrome.action.onUserSettingsChanged.addListener(hello);   // Chrome 130+: pinned or unpinned
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "save", title: "Save to Magpiary", contexts: ["page", "link"] });
  flush();
  hello();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const r = await save({ url: info.linkUrl || info.pageUrl || (tab && tab.url) || "" });
  if (tab && tab.id != null) {
    if (r.state === "ok") await badge(tab.id, "✓", "#2e7d32");
    else if (r.state === "offline") await badge(tab.id, "…", "#8a6d00");
    else await badge(tab.id, "!", "#b3261e");
  }
});

// The "pick a post" shortcut: starts pick mode on the tab in front. Chrome grants this tab's access because the owner pressed it.
chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command !== "pick" || !tab || tab.id == null) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["clean.js", "pick.js"] });
  } catch (_) {
    await badge(tab.id, "!", "#b3261e");   // a page Chrome doesn't let extensions use, like chrome://
  }
});
