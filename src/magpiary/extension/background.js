/* Magpiary background worker. Talks to the hub on this Mac only, over localhost, with the key from pairing.
 * It sends the cleaned link, the optional note and board, and nothing else: no page text, title, cookies or history.
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

/** Send everything waiting. The outbox is cleared only for items the Mac acknowledged. */
async function flush() {
  const { key, outbox = [] } = await store.get(["key", "outbox"]);
  if (!key) return { state: "unpaired" };
  if (!outbox.length) return { state: "ok", waiting: 0 };
  let reply;
  try {
    reply = await hub("/v1/items", { method: "POST", body: { items: outbox }, key });
  } catch (_) {
    await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
    return { state: "offline", waiting: outbox.length };
  }
  if (reply.status === 401) return { state: "revoked", waiting: outbox.length };
  if (reply.status === 200 && reply.json && reply.json.ack === ACK) {
    const done = new Set([...(reply.json.accepted || []), ...(reply.json.rejected || []).map((r) => r.id)]);
    const left = outbox.filter((i) => !done.has(i.id));
    await store.set({ outbox: left });
    return { state: "ok", waiting: left.length, results: reply.json.results || [], message: reply.json.message };
  }
  await chrome.alarms.create(RETRY_ALARM, { delayInMinutes: 1 });
  return { state: "offline", waiting: outbox.length };
}

async function save({ url, note = "", board = "" }) {
  const { key } = await store.get(["key"]);
  if (!key) return { state: "unpaired" };
  const cleaned = MagpiaryClean.clean(url);
  if (cleaned.error) return { state: "unsupported", error: cleaned.error };
  const item = { id: itemId(), url: cleaned.url, shared_at: localStamp(), note: String(note).slice(0, 2000), v: 1 };
  if (/^[0-9a-f]{16}$/.test(board)) item.board = board;
  const { outbox = [] } = await store.get(["outbox"]);
  await store.set({ outbox: [...outbox, item] });
  const sent = await flush();
  const mine = (sent.results || []).find((r) => r.id === item.id);
  return { ...sent, url: cleaned.url, source: cleaned.source, savedCount: mine ? mine.saved_count : undefined };
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
  return { paired: Boolean(key), waiting: outbox.length };
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
  const run = { state, ping, seen: () => ask("/v1/seen", { urls: msg.urls }).then((r) => (r && r.results) || {}), suggest: () => ask("/v1/suggest", { url: msg.url }).then((r) => (r && r.suggestion) || null), pair: () => pair(msg.code), save: () => save(msg), boards, flush, unpair: async () => { await store.set({ key: "" }); return {}; } }[msg && msg.type];
  if (!run) return false;
  Promise.resolve(run()).then(respond, () => respond({ state: "error" }));
  return true;
});

chrome.alarms.onAlarm.addListener((a) => { if (a.name === RETRY_ALARM) flush(); });
chrome.runtime.onStartup.addListener(flush);
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "save", title: "Save to Magpiary", contexts: ["page", "link"] });
  flush();
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
