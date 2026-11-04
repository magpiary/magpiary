"""The extension's outbox under Node with a fake Chrome (review 4 Nov 2026): a save made while a send is in flight is kept,
and a queue longer than the Mac takes in one request still drains, a slice at a time."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "src" / "magpiary" / "extension"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const data = { key: "k", outbox: [] };
const sent = [];
let gate = null;
const chrome = {
  storage: { local: { get: async (keys) => { const o = {}; for (const k of [].concat(keys)) if (k in data) o[k] = JSON.parse(JSON.stringify(data[k])); return o; },
                      set: async (obj) => { Object.assign(data, JSON.parse(JSON.stringify(obj))); } } },
  alarms: { create: async () => {}, onAlarm: { addListener() {} } },
  runtime: { onMessage: { addListener() {} }, onInstalled: { addListener() {} }, onStartup: { addListener() {} }, getManifest: () => ({ version: "t" }) },
  contextMenus: { create() {}, removeAll(cb) { cb && cb(); }, onClicked: { addListener() {} } },
  commands: { onCommand: { addListener() {} } }, action: { getUserSettings: async () => ({}) }, tabs: { query: async () => [] },
};
let offlineAt = 0;
async function fetch(url, opts) {
  const body = JSON.parse(opts.body);
  sent.push(body.items.length);
  if (offlineAt && sent.length === offlineAt) throw new TypeError("offline");
  if (gate) await gate;
  if (body.items.length > 1000) return { status: 413, json: async () => ({}) };
  return { status: 200, json: async () => ({ ack: "magpiary-ok", accepted: body.items.map((i) => i.id), results: [] }) };
}
const ctx = { chrome, fetch, console, crypto: require("crypto").webcrypto, AbortSignal, setTimeout, URL, URLSearchParams,
              importScripts: (f) => vm.runInContext(fs.readFileSync(process.argv[2] + "/" + f, "utf8"), ctx) };
ctx.self = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2] + "/background.js", "utf8"), ctx);
(async () => {
  // 1. a save arrives while the first send waits for the Mac
  let open; gate = new Promise((r) => (open = r)); offlineAt = 2;  // the second request finds the Mac gone
  const first = vm.runInContext("save({url: 'https://www.threads.com/@ada/post/AAA111'})", ctx);
  await new Promise((r) => setTimeout(r, 20));
  const second = vm.runInContext("save({url: 'https://www.threads.com/@bo/post/BBB222'})", ctx);
  await new Promise((r) => setTimeout(r, 20));
  open(); gate = null;
  await first; await second;
  const raceLeft = data.outbox.length; offlineAt = 0;
  // 2. 1,201 saves waiting: they go in slices and all are acknowledged
  data.outbox = Array.from({ length: 1201 }, (_, i) => ({ id: "x" + i, url: "https://example.com/" + i, shared_at: "", note: "", v: 1 }));
  sent.length = 0;
  const r = await vm.runInContext("flush()", ctx);
  console.log(JSON.stringify({ raceLeft, waiting: r.waiting, left: data.outbox.length, biggest: Math.max(...sent) }));
})();
"""


def test_outbox_keeps_a_save_made_mid_send_and_drains_a_long_queue(tmp_path):
    script = tmp_path / "harness.js"
    script.write_text(HARNESS)
    done = subprocess.run([NODE, str(script), str(EXT)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["raceLeft"] == 1  # the second save was not acknowledged, so it is still waiting (it used to vanish)
    assert out["left"] == 0 and out["waiting"] == 0 and out["biggest"] <= 200
