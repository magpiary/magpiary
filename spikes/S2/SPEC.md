# S2 / S3 / S6 — Shortcut build spec

You build three Shortcuts and one automation on your iPhone, against the throwaway receiver in `receiver.py`. Nothing here is the final product. The goal is to learn what iOS lets us do, then record findings.

I (Claude) can't see your phone or verify Shortcuts action names and menus. Action names below are from memory and may differ slightly on your iOS version. Where I'm unsure I say so; those are exactly the things to report back.

## What each spike must answer

| Spike | Question | Pass |
|---|---|---|
| **S2** | Can a Shortcut (a) expand and clean a link, (b) write a file to **local** phone storage, (c) POST it to `http://<mac>.local:8765`, (d) delete the file only after the Mac confirms it? | A shared reel appears in the Mac's database, and its queue file is gone from the phone only after the ack. A failed send leaves the file. |
| **S3** | Does a "joined home Wi-Fi" automation flush the queue **without a tap**? | Queue of 3 sent within about a minute of joining Wi-Fi, no tap. |
| **S6** | Does a QR code / `shortcuts://` link hand the Mac's address and pairing key to the Shortcut? | Scan or tap once, then the Shortcut has a saved config and no typing was needed. |

Also record every iOS prompt that appears, with its exact wording.

## 0. Mac side

1. Start the receiver (leave this Terminal window open):

   ```bash
   uv run spikes/S2/receiver.py
   ```

   It prints the Mac's Bonjour name (yours is `example-mac.local`), the port (8765), and creates a pairing key file `spikes/S2/.pairing_key` (mode 0600). The key is not printed unless you pass `--show-key`.
2. Open `http://localhost:8765/setup` in a browser on the Mac. It shows the pairing QR code, the config JSON and the `shortcuts://` link. Keep it open for S6.
3. In another Terminal, check the Mac reaches itself by name:

   ```bash
   curl http://example-mac.local:8765/v1/ping
   ```

   Expect `{"ok": true, ...}`.
4. Useful during the tests:

   ```bash
   sqlite3 spikes/S2/received.db "select canonical_url, saved_count from items"
   ```

   Testing the failure path: restart with `uv run spikes/S2/receiver.py --fail 1` and the first send gets a 503.

Your Mac's firewall is currently off, so you will **not** see macOS's "accept incoming connections" prompt. Real users with the firewall on will. That prompt is untested by this spike.

## 1. Prepare the phone

1. Same Wi-Fi as the Mac. Open **Safari** on the phone and visit `http://example-mac.local:8765/v1/ping`. Expect the JSON. **Write down** whether iOS asked for Local Network access (for Safari) and the wording. If this fails, stop and tell me: nothing else will work, and I'll try the Mac's IP address instead of `.local`.
2. In the **Files** app: **On My iPhone → Shortcuts**. Create a folder `Magpiary`, and inside it a folder `queue`. (If "On My iPhone" has no "Shortcuts" folder, create `ReelHub/queue` at the top of On My iPhone and tell me.)
3. Do not use iCloud Drive for any of this. If a "Save File" action will only offer iCloud, stop and tell me; that breaks a non-negotiable and we need to decide.

## 2. Shortcut A — "Magpiary Config" (S6)

Receives the pairing config and saves it.

1. **Receive** *Text* input from *Nowhere / Quick Actions* (the "Receive What's Passed Into the Shortcut" setting). Run via `input=text&text=...`, the config arrives as text.
2. **Get Dictionary from Input**.
3. **Text**: put *Shortcut Input* in it (the raw JSON text).
4. **Save File**: the Text from step 3 → destination `On My iPhone / Shortcuts / Magpiary`, filename `config.json`, **Ask Where to Save: off**, **Overwrite If File Exists: on**.
5. **Get Dictionary Value** `host` from the Dictionary, then **Show Notification**: "Magpiary paired with {host}".

Test: tap the link from `/setup`, or scan the QR code with the Camera app. Record: does the Camera offer to open it? Does it open Shortcuts directly or ask? Does Shortcuts ask permission to run? Does `config.json` appear in Files? If scanning doesn't work, paste the link into Notes on the Mac, open Notes on the phone and tap it (iOS often handles custom links this way), and tell me which method worked.

## 3. Shortcut B — "Magpiary Send Queue" (used by Shortcut C and the automation)

1. **Get Contents of Folder**: `On My iPhone / Shortcuts / Magpiary / queue` (no subfolders). Variable: *Queue*.
2. **If** *Queue* **has any value**; otherwise **Stop This Shortcut** (**Show Notification**: "Magpiary queue empty").
3. **Get File**: `Magpiary/config.json` → **Get Dictionary from Input** → variables *host*, *port*, *key* (**Get Dictionary Value**).
4. **Repeat with Each** file in *Queue*:
   - **Get Dictionary from Input** (the file) → **Add to Variable** *Batch*.
5. **Get Contents of URL**
   - URL: `http://` + *host* + `:` + *port* + `/v1/items`
   - Method: **POST**
   - Headers: `Authorization` = `Bearer ` + *key*
   - Request Body: **JSON**, one field `items` of type *List* set to *Batch*.
   - If the JSON editor won't accept a variable list: make a **Dictionary** action with key `items` = *Batch*, and use Request Body **File** with that Dictionary. Tell me which one worked.
6. **Get Dictionary from Input** (the response) → **Get Dictionary Value** `accepted` → variable *Accepted*.
7. **Repeat with Each** file in *Queue*:
   - **Get Dictionary from Input** → **Get Dictionary Value** `id` → *ThisID*.
   - **If** *Accepted* **contains** *ThisID*: **Delete Files** (the file), **Confirm Before Deleting: off**, **Delete Immediately: on**.
8. **Show Notification**: "Magpiary: sent {count of Accepted}".

What I can't predict, and you should record:
- When the Mac is unreachable (receiver stopped, wrong Wi-Fi, Mac asleep), does Shortcut B stop with an error, show a dialog, or continue? **Get Contents of URL** may have no way to catch an error. This is fine as long as the files are still in the queue (they are deleted only in step 7).
- Whether iOS shows a Local Network prompt the first time, and for which app ("Shortcuts"?).

## 4. Shortcut C — "Magpiary" (the share-sheet one)

Name it `Magpiary`; in its settings turn on **Show in Share Sheet** and accept **URLs** and **Text**.

1. **Receive** input from the Share Sheet (URLs, Text). If nothing, **Stop This Shortcut**.
2. **Get URLs from Input** → **Get First Item** → *Shared*. If none: **Show Notification** "Not a supported link", **Stop**.
3. **Expand URL** (*Shared*) → *Expanded*. (Name may be "Expand URL" under Web.) Test whether it resolves `threads.com/share/…` and `reddit.com/r/…/s/…`; S1 showed a plain redirect-follow does, but Shortcuts may differ.
4. **Clean**:
   - **If** *Expanded* **matches** `^https?://(www\.|m\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+` → **Match Text** with that pattern → *Clean* (keeps `?v=ID`, drops the rest).
   - **Otherwise** → **Replace Text** pattern `[?#].*$` with nothing (**Regular Expression** on) in *Expanded* → *Clean* (drops the whole query and fragment).
5. **Validate**: **Match Text** against this pattern (case-insensitive) in *Clean*; if no match → "Not a supported link", **Stop**:

   ```
   ^https://(www\.|m\.)?(instagram\.com/(reel|reels|p|tv)/[A-Za-z0-9_-]+|threads\.(com|net)/@[^/]+/post/[A-Za-z0-9_-]+|youtube\.com/(shorts/[A-Za-z0-9_-]+|watch\?v=[A-Za-z0-9_-]+)|youtu\.be/[A-Za-z0-9_-]+|reddit\.com/r/[^/]+/comments/[A-Za-z0-9_]+|(x|twitter)\.com/[^/]+/status/[0-9]+)/?
   ```

   (This is only for the spike. The real cleaner is Python and has tests; the Shortcut's rules will be generated from the same table.)
6. **ID**: there is no UUID action that I know of. Build one: **Current Date** → **Format Date** custom `yyyyMMddHHmmss` → **Text**: that + `-` + **Random Number** between 100000 and 999999. Tell me if you find a real UUID action.
7. **Current Date** → **Format Date** ISO 8601 → *SharedAt*.
8. **Dictionary**: `id`, `url` = *Clean*, `shared_at` = *SharedAt*, `source` = (type the source by hand, or leave `""`; the receiver ignores it in this spike), `note` = `""`, `v` = `1` (Number).
9. **Save File**: Dictionary → `On My iPhone / Shortcuts / Magpiary / queue`, filename = ID + `.json`, **Ask Where to Save: off**.
10. **Show Notification**: "Saved to Magpiary queue".  (Queue first, notify second, send last: if sending then fails, nothing is lost.)
11. **Run Shortcut**: `Magpiary Send Queue`.

## 5. Automation (S3)

Shortcuts → **Automation** → **New Automation** → **Wi-Fi** → choose your example network → trigger when the phone **joins**; **Run Immediately** (not "Ask Before Running"); **Notify When Run**: your choice, record what you get → action **Run Shortcut** → `Magpiary Send Queue`.

Record: the exact options offered; whether Apple shows a notification each time; whether the automation actually runs with the phone locked.

## 6. Test script

Run in order. Keep the receiver running with its log visible. "Record" = tell me what happened, including any prompt wording.

| # | Do | Expect | Record |
|---|---|---|---|
| T1 | Safari on phone → `http://example-mac.local:8765/v1/ping` | JSON ok | Local Network prompt? |
| T2 | Run Shortcut A via the QR/link | `config.json` in Files, notification shows host | Which scan/tap method worked |
| T3 | Share an Instagram reel (from the app's Share menu) → Magpiary, on home Wi-Fi | Notification "Saved", then "sent 1"; receiver log shows `new`; queue folder empty; Mac database has a **clean** URL (no `igsh`) | Prompts, whether Magpiary appears in the share sheet, how many taps |
| T4 | Same reel again | Log shows `again`; `saved_count` 2 | |
| T5 | Share a Threads post | Share link expanded to a `/@user/post/…` URL | Did Expand URL work? |
| T6 | Share a Reddit post (share link `/s/…`) | Expanded to `/comments/…` | Did Expand URL work? |
| T7 | Share a YouTube Short, and a normal YouTube `watch?v=` link | Short drops `si=`; watch keeps `v=` only | |
| T8 | Share something unsupported (any other site) | "Not a supported link"; nothing queued | |
| T9 | Stop the receiver, share a reel | File stays in `queue`; "Saved" shown | What does the Shortcut do when it can't reach the Mac (error dialog? silent?) |
| T10 | Start the receiver with `--fail 1`, run `Magpiary Send Queue` | 503: file stays. Run again: file is sent and deleted | Files deleted only after ack |
| T11 | Turn on **Airplane mode** (or leave Wi-Fi and use mobile data), share 5 different reels | 5 files in `queue`; nothing lost | Does the share sheet still work offline? |
| T12 | Join home Wi-Fi without touching the phone (S3). Receiver running | All 5 arrive within about a minute, no tap | Time to arrival; notification shown by iOS; works while locked? |
| T13 | Put the Mac to sleep, share a reel, then wake the Mac | Item stays queued; arrives on the next send | Does the phone's request wake the Mac? (Probably not.) |
| T14 | Share the same reel from two different Instagram share routes ("Copy link" and the in-app share sheet) | One item, `saved_count` 2 | |
| T15 | Open `queue/` files in Files, read one | `id, url, shared_at, source, note, v` only; no device name, no account | Anything extra? |
| T16 | Check the Mac DB after the 5-reel run | 5 distinct canonical URLs, none containing `?` | |

## 7. If something fails

| Failure | Next move |
|---|---|
| T1/T3: cannot reach `.local` | Try the Mac's IP (`ipconfig getifaddr en0`) in the config. Tells us `.local` needs a fallback. |
| Shortcuts won't make an HTTP (not HTTPS) request | Test with the Mac's IP; if still blocked, the transport needs rethinking (HTTPS with a trusted certificate, or another route). Tell me before changing anything. |
| "Save File" only offers iCloud | Stop. This conflicts with non-negotiable #2 and your full iCloud. We discuss alternatives. |
| Automation only "Ask Before Running" | Then catch-up happens on each new share plus a Home Screen "Send queue" button. Also try an "Arrive at location" automation. |
| Unreachable Mac makes the Shortcut error out | Acceptable as long as the files remain in `queue`. Record the message. |
| `Expand URL` doesn't resolve Threads or Reddit share links | The Mac expands them instead (S1 showed that works). The phone then stores the share link, so it must be validated more loosely. |

## 8. After the tests

Send me your notes (a screenshot of each iOS prompt is ideal). I'll write `docs/findings/S2-S3-S6-shortcut.md`, update the handover, and turn what worked into the real Shortcut spec for M1.

Delete the test data when you're done: `spikes/S2/received.db` and `spikes/S2/.pairing_key` on the Mac, and the `Magpiary` folder in Files on the phone.
