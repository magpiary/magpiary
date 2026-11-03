# S2 / S3 / S6 — Shortcut queue, Wi-Fi automation, pairing hand-off

**Run:** 22 Oct 2026, the owner's iPhone (iOS version not recorded) and Mac (M1 Pro, macOS 27.0.1, firewall off), home Wi-Fi "Example Wi-Fi", Instagram reels only.
**Code:** `spikes/S2/` (`receiver.py`, `make_shortcuts.py`, `fake_phone.py`, `logo.png`; `SPEC.md` is the superseded first plan).
**Caveat:** one phone, one iOS version, one network, Instagram only. Treat as a strong first signal.

## Verdict

| Spike | Question | Result |
|---|---|---|
| **S2** | Expand/clean a link, queue on the phone's own storage, POST to `http://<mac>.local`, remove only after the Mac confirms | ✅ Works, with a redesign: one **outbox file** instead of one file per share (see below). |
| **S3** | Does a "joined home Wi-Fi" automation flush the queue with no tap? | ✅ **Yes.** Joining the network ran the Shortcut immediately and the queued reel reached the Mac. |
| **S6** | Hand the Mac's address and key to the phone with a QR / `shortcuts://` link | ✅ in a better form: **one QR installs a Shortcut that already contains the pairing** (the original two-QR `run-shortcut` hand-off was not needed and is untested). One-tap install is ❌ (needs https). |

## What works on the phone

- **Phone reaches the Mac over plain HTTP** at `http://example-mac.local:8765` (Bonjour name, no IP needed). Auth is a Bearer pairing key baked into the Shortcut.
- **We can generate Shortcuts.** `make_shortcuts.py` writes Shortcuts' plist format (from memory), `shortcuts sign --mode anyone` signs it on the Mac, and iOS imports it. No iCloud link, no hand-building.
- **One QR does install + pairing.** The Mac builds a personalised copy (host, port, key inside), signs it, and serves it behind a 15-minute token. Scan → Safari page → Download → open from Safari's downloads → Add Shortcut. `/setup` (which shows the QR) is served only to the Mac; the phone gets an error.
- **Share → ReelHub** on an Instagram reel: the link was cleaned on the phone (tracking tail removed with two regex Replace steps), stored on the Mac clean, `saved_count` rose on a repeat share, and the Mac's reply text was shown to the user.
- **Offline backlog:** reels shared while the Mac was off wait in the phone's `outbox.txt`; with the Mac up, running the Shortcut with no input sent them in one batch (`{'new': 2, 'empty': 1}`) and blanked the file.
- **Wi-Fi automation (S3):** created by hand as "When Example Wi-Fi is Joined → Run ReelHub" (named "Sync ReelHub"). With Wi-Fi off, one reel was shared and failed to send; on joining the network iOS showed "iPhone joining Example Wi-Fi, running Sync ReelHub", the Shortcut ran by itself, and the Mac received the reel (shared 20:17:52, stored 20:20:24).

## What failed, and what we did

| Problem | Cause (known or likely) | Fix / decision |
|---|---|---|
| `shortcuts://import-shortcut?url=…` says "The shortcut URL provided was invalid" (button and camera, 3 URL shapes) | Probably needs `https`; ours is `http` | Use the download route. One-tap install needs HTTPS (Tailscale later?) or a public iCloud Shortcut link. Open design question. |
| Custom Shortcut icon image ignored | iOS version or format | Only the tile **colour** works; glyph defaults to a wand. |
| Link and dates empty in the first runs | Generated Replace Text / Format Date inputs were not wired; the editor showed faded inputs | Regex on the Shortcut Input text; date formats applied inside text variables. |
| `If Shortcut Input has any value` never true | My generated condition on Shortcut Input | Removed all those Ifs; the Mac ignores empty items instead. `If … Contains` on an action's output **does** work. |
| Per-item queue files needed a Delete; iOS asks "Allow to delete 1 file?" with a preview **every time** (no Always Allow) | iOS privacy prompt | **Redesign: one outbox file, overwritten, never deleted.** Required anyway, because a delete prompt would block the unattended automation. |
| Offline backlog lost: second share overwrote the first, flush sent only a blank | `outbox.jsonl` was read back as nothing | `outbox.txt` + explicit "Get Text from Input" on the file; verified by the Mac's batch size. |
| Wrong key or a 503 would wipe the outbox | Shortcuts stops only on "can't connect", not on error replies | The Mac's 200 reply carries `"ack":"reelhub-ok"`; the Shortcut blanks the outbox only `If ack contains reelhub-ok`. Found with `fake_phone.py`; **the guard has not yet been seen running on the phone.** |
| Get File shows the previous action's output as its folder | No folder given | Writing `WFFolder` (LocalStorage, `ReelHub/queue`) **works for Save File**, **not for Get File**; Get File needs a manual folder pick per install. |
| Safari downloads stuck "↑ Error" in iCloud Drive/Downloads | iCloud storage full | Setup must tell users: Settings → Safari → Downloads → **On My iPhone**. |

## Behaviour to design around

- **A failed request stops the Shortcut and cannot be caught.** So the item must be saved **before** sending; "send first, queue on failure" is impossible.
- **Away from the Mac the failure is slow.** On mobile data the share showed "The request timed out" after a long wait (the Dynamic Island showed it still running); on home Wi-Fi with the Mac off it fails fast with "Could not connect to the server". The wait was not timed. Idea: check the Wi-Fi network first and skip the send when not home (an If on an action's output).
- **Prompts on first run**, each allowed once per kind: notifications; access to the queue folder; "save 1 Instagram item to a file"; "connect to example-mac.local"; "send 1 Instagram item / 1 text item to the local address" (a new prompt for each content type; the text one shows the whole body). Dismissing one by mistake gives "This shortcut can't access… change this in Shortcuts privacy settings".
- **The automation announces itself:** with Notify When Run, iOS shows a banner each time ("…running Sync ReelHub"). Automations cannot be generated or shared; the user makes it by hand.
- **Mac firewall was off**, so the macOS "accept incoming connections" prompt was not observed.

## Per-install manual steps that remain

1. Safari download location → On My iPhone.
2. Allow the first-run prompts (don't dismiss them).
3. Get File action: pick the `queue` folder (the Save actions come pre-filled).
4. Create the Wi-Fi automation by hand and choose Run Immediately.
5. Create the folders `ReelHub/queue` in Files first.

## Later change (22 Oct, 20:30): home-Wi-Fi check and one notification

Built after these results, **not yet tried on the phone**: the Shortcut saves first, checks the Wi-Fi name, sends only at home, and shows at most one notification (see `../onboarding-notes.md`). Apple's signing service failed once ("Failed to modify some records") and then worked; the generator now retries.

## Folder test (22 Oct 2026, 23:15): no folder needed
Phone tests of three default locations (generated "Magpiary Test A/B/C"):
- **A, no folder given:** fails ("Invalid file path. The provided file path must be contained within the directory"); iOS wires the previous action's output (the date) in as the folder.
- **B, top level of On My iPhone: works.** One permission prompt ("Allow ... to access On My iPhone"), saved and read back on every run, three runs gave three lines. Nothing created by hand.
- **C, the "Shortcuts" folder:** the first read fails with "The file doesn't exist" even with "error if not found" off, which stops the Shortcut.
Decision: the outbox is now `magpiary-outbox.txt` at the top of On My iPhone; the user creates no folder. The earlier `Magpiary/queue` path needed a folder made by hand and fails if it is missing.

## First-run permission froze inside Instagram (22 Oct 2026, 23:31)
With the no-folder build, the very first share from Instagram showed "Allow Magpiary to access your On My iPhone folder?" and the dialog froze (OK and Cancel did nothing); a notification then said "XPC error received on message reply handler". The Mac received nothing. The same prompt had worked when the test Shortcuts were run from the Shortcuts app itself. Likely cause: the share-sheet extension is a small, restricted process and the system file-permission prompt cannot complete there (not confirmed). Workaround to test: **run the Shortcut once from the Shortcuts app first** so every permission is granted there, then share. If that holds, the setup guide needs one step: "Tap Magpiary once in the Shortcuts app and allow the prompts."

## Result of the workaround (22 Oct 2026, 23:38)
After granting every permission by running Magpiary once from the Shortcuts app (Always Allow), the first share from Instagram still hung (stuck at 10 to 15%, nothing reached the Mac). the owner then killed the Shortcuts app, reopened Instagram and shared again: **it worked**, arriving on the Mac 4 seconds later (`{'new': 1}`, clean canonical link). Cause of the one hang not known (possibly the Shortcuts app still running right after the grant). Needs repeating a few times before calling it reliable. The no-folder build is therefore: no folder to create; install, run once from the Shortcuts app, allow every prompt, then share.

the owner added: from Instagram the Shortcut **prompted a couple of times again** (even after the in-app grant) before it worked. So expect a few permission prompts on the first share-sheet runs; the wording of each was not captured. Setup guide: "the first one or two shares may ask again; tap Allow each time, and if it freezes, close the Shortcuts app and share again."

## Wi-Fi automation with the Magpiary build (22 Oct 2026, 23:48)
Wi-Fi off, two Instagram reels shared (23:46:31 and 23:48:00, each answered "Saved. It will send when you're home."), Wi-Fi back on: the automation ran by itself and the Mac received **one batch of 3 lines at 23:48:06** (`{'new': 2, 'empty': 1}`: the two reels plus the empty run from the automation). The phone showed one notification, "Saved 2 items to Magpiary". The automation is confirmed with the renamed Shortcut and the no-folder queue.

## Sharing from Threads, YouTube Shorts and Reddit (22-23 Oct 2026)
All three apps list Magpiary in their share sheets, each asked for permission on its first use (tap Allow), and each gave one notification. The URL examples below are fictional replacements; the observed transport outcomes are retained:
| App | Stored | Notes |
|---|---|---|
| Threads | `https://www.threads.com/share/ExampleShare1/` | Short share link, **not expanded** on the phone. |
| YouTube Shorts | `https://www.youtube.com/shorts/Example0008` | Clean. |
| Reddit | `https://www.reddit.com/r/ExampleWorkshop/s/ExampleShare2` | Short share link, **not expanded**. |
The Mac can expand both with one plain redirect (tested with curl): Threads `/share/...` becomes `/@example.creator/post/Example0009`, Reddit `/s/...` becomes `/comments/examplepost/<slug>/`, each followed by tracking parameters (`xmt`, `share_id`, `utm_*`) that must be stripped. Decision: expand on the Mac, keep only the expanded canonical link, and do not keep the short share code (it identifies the sharer). Until that exists, two different share links to the same post would be stored twice.
**Regular YouTube videos:** the Shortcut used to strip everything after `?`, which would turn `watch?v=ID` into `watch`. Fixed in the generator (keep `?v=ID`, drop the rest); verified in the fake phone, to confirm on the phone after a reinstall.

**YouTube after the fix (23 Oct, 00:29):** a Short arrived as `youtube.com/shorts/Example0010` and a regular video as `youtube.com/watch?v=Example0011` (video ID kept, tracking tail gone), one notification each. The YouTube app's share button produced a `watch?v=` link for the regular video; a `youtu.be` link did not come up and is covered by the fake phone only.

## "Mac says no" (ack guard) on the phone (23 Oct 2026, 00:32)
Receiver set to answer the first two requests with 503. Two Instagram reels shared: each showed one notification, "Saved on your phone. The Mac didn't accept it yet." (Mac log: 503 with 1 item, then 503 with 2 items, so the queue was kept and grew). Magpiary then run from the Shortcuts app: one notification, "Saved 2 items to Magpiary", and the Mac stored both reels once each (batch of 3 lines, `{'new': 2, 'empty': 1}`). **The ack guard works on the phone**: a refusal never loses an item.

## Automation with the screen locked (23 Oct 2026, 00:47 to 00:54)
First attempt: reel shared 00:47:39 arrived 00:48:02 (23 s later, with the automation's empty line). Second attempt: reel shared 00:48:51 did **not** arrive by itself. Retest (two reels shared, Wi-Fi turned on from the lock screen's Control Center without unlocking): **one batch of 4 lines at 00:53:43, `{'new': 3, 'empty': 1}`**: the reel left over from the second attempt (00:48:51) plus the two new ones (00:51:29, 00:52:47). So the automation **runs while the phone is locked**, the queue survives a failed attempt, nothing was lost and nothing was stored twice. Why the 00:48:51 reel did not go out at once is not proven; the likely cause is that Wi-Fi came back within a short time of leaving the same network, and iOS does not treat that as a new "joined" (the earlier "reconnect within 3 minutes" question). Practical effect: a reel can wait until the next real join of the home network, or any later run of Magpiary.

## Mac asleep (23 Oct 2026, 01:02 to 01:06)
Mac put to sleep, reel shared at 01:02:54 from Instagram on home Wi-Fi: the Shortcut sat in the Dynamic Island for about a minute and then iOS showed its own notification, **"The request timed out."** (not our wording; a failed connection cannot be caught). The reel was already saved on the phone first. After the Mac woke, running Magpiary from the Shortcuts app gave "Saved to Magpiary" and the Mac stored the reel **once** (arrived 01:05:58, batch `{'new': 1, 'empty': 1}`). The Mac did not wake by itself: `pmset` shows `womp 0` (Wake for network access off) on the owner's Mac. Asleep Mac = slow failure (about a minute) but no loss.

**Retry by sharing, no manual tap (23 Oct, 01:11 to 01:15):** two reels shared while the Mac slept (01:11:12, 01:11:46, each timed out), Mac woken, a third reel shared at 01:15:04: **one batch of 3 at 01:15:04, `{'new': 3}`**, each stored once. So a normal share is enough to flush everything waiting; tapping Magpiary in the Shortcuts app is never required.

## Not tested (pending list)

Single-notification build on the phone; `Get Network Details` (location permission? what it returns on mobile data); automation run with nothing waiting stays silent; the `ack` guard on the phone; Mac asleep when the phone tries (T13); the automation with the **screen locked**; Expand URL on Threads and Reddit share links; Threads, Reddit, YouTube, X from the share sheet; reconnect-within-3-minutes behaviour of the automation; other iOS versions; a Mac with the firewall on; more than two queued items; very long outboxes.

## For M1

Keep the Shortcut **thin** and put the rules on the Mac (dedupe, retries, message text). Always verify queue behaviour by the **receiver's batch size**, not the phone's file. Run `fake_phone.py` before asking the phone to test. The generator works but is fragile (plist from memory); expect to re-validate after iOS updates.
